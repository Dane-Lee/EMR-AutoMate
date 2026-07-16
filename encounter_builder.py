"""
encounter_builder.py — build encounters.csv by checking names off the roster
===========================================================================
The Copilot replacement. No AI, no cloud, no dictation, no transcription.

A day of coaching is mostly ONE fact repeated: the same coaching, delivered to a list
of people. Dictating that makes you recall and pronounce every name, then hope
speech-to-text and an LLM carry them all intact. This inverts it — the roster is
already on screen with the EMR's own spelling, you check who you saw, and you set the
coaching once for the whole group. Names are never typed, so they can never be
mis-transcribed.

WHERE EACH PERSON'S DEPARTMENT AND SHIFT COME FROM
    A group is not always one department. "High heat index" job coaching goes to
    people scattered across weld, assembly and the paint line — so a single group-level
    Department would be wrong for most of them. import_hc_roster composes roster.xlsx's
    `new_identifier` as 'ID-Title-Shift' (e.g. '12345-Technician II-2nd'), so each
    person's job title and shift are already in the roster. Parse them back out and
    every row can carry that person's OWN department and shift, while the coaching is
    still set once for the whole group.

    WORK_TITLE_MAP only knows the shop-floor titles. Every other title is written to
    work_titles.csv for Dane to map once; anything he fills in wins. Unmapped means a
    blank department, which is safe — a wrong one is not.

Every controlled value is picked from the SAME tables the validator and the EMR driver
use (imported from ati_coaching_encounter, never copied), so anything this writes is a
value the EMR accepts. `coaching_type` deliberately has no default and a group will not
build without one: it is the field that must never be guessed, and here nothing can
guess it.

RUN IT
    python encounter_builder.py

    Hide the groups you never see (Admin, a shift) — that sticks between runs.
    Check the names  ->  set the group's coaching  ->  "Add group to batch".
    Repeat for each distinct group in the day. Then "Write encounters.csv":

        .\\Run-Encounters.ps1 -Check
        .\\Run-Encounters.ps1

PHI
    Employee names appear in the window — that is the point, it is Dane's screen.
    stdout gets counts only, so a captured run stays PHI-free.
"""

import csv
import json
import os
import re
import subprocess
from datetime import date, datetime

import tkinter as tk
from tkinter import ttk, messagebox

import emr_field_map as fm
import ati_coaching_encounter as ace

_HERE = os.path.dirname(os.path.abspath(__file__))
ROSTER_XLSX = os.path.join(_HERE, "roster.xlsx")
OUT_CSV = os.path.join(_HERE, "encounters.csv")
BAK_CSV = os.path.join(_HERE, "encounters.bak.csv")
LIBRARY_XLSX = os.path.join(_HERE, "EMR Easy Enter Worksheets.xlsx")
TITLES_CSV = os.path.join(_HERE, "work_titles.csv")
PREFS_JSON = os.path.join(_HERE, "builder_prefs.json")

# No default. An unset coaching type blocks the group — see the module docstring.
PICK_ONE = "— pick one —"
BLANK = ""

COACHING_TYPES = sorted(ace.COACHING_TYPE_UUIDS)
VALID_DEPTS = set(ace.FIELD_OPTIONS.get("Department", []))
VALID_DIVS = set(ace.FIELD_OPTIONS.get("Division", []))

# format_identifier composes '-'.join([id, title, shift]). The ID may carry a '-NN'
# suffix and the shift is a closed vocabulary, so anchor both ends and take the middle.
_IDENT_RE = re.compile(r"^(\d+(?:-\d+)?)-(.*?)(?:-(1st|2nd|3rd))?$", re.IGNORECASE)


def parse_new_identifier(ident):
    """'12345-Technician II-2nd' -> ('Technician II', '2nd'). ('', '') if it doesn't fit."""
    m = _IDENT_RE.match(str(ident or "").strip())
    if not m:
        return "", ""
    return (m.group(2) or "").strip(), (m.group(3) or "").lower()


# ─────────────────────────────────────────────
# WORK TITLE -> DEPARTMENT / DIVISION
# ─────────────────────────────────────────────

def sync_title_file(titles, path=None):
    """Keep work_titles.csv in step with the roster; return {title: (dept, div)}.

    emr_field_map.WORK_TITLE_MAP covers the shop-floor titles and nothing else — a real
    roster has ~32. Rather than guess the rest (a wrong department is worse than none),
    every title is listed here with its people-count, pre-filled where WORK_TITLE_MAP
    already knows it, blank otherwise. Dane fills the blanks in once and they win from
    then on.

    Existing rows are never overwritten — new titles are appended, gone ones dropped.
    Titles and counts only, no names: this file carries no PHI.
    """
    path = path or TITLES_CSV
    existing = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                title = (row.get("work_title") or "").strip()
                if title:
                    existing[title] = ((row.get("department") or "").strip(),
                                       (row.get("division") or "").strip())

    resolved, rows = {}, []
    for title, count in sorted(titles.items(), key=lambda kv: (-kv[1], kv[0].lower())):
        dept, div = existing.get(title, ("", ""))
        if not dept and not div:
            dept, div = fm.dept_div_from_title(title)      # pre-fill what we do know
        resolved[title] = (dept, div)
        rows.append({"work_title": title, "people": count,
                     "department": dept, "division": div})

    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["work_title", "people",
                                                "department", "division"])
        writer.writeheader()
        writer.writerows(rows)
    return resolved


def validate_title_map(resolved):
    """Titles whose mapped department/division isn't a real EMR option.

    A typo here would otherwise sail through to the CSV and be caught late, by the
    validator, as a row error with no hint of where it came from.
    """
    problems = []
    for title, (dept, div) in sorted(resolved.items()):
        if dept and dept not in VALID_DEPTS:
            problems.append(f"'{title}': department '{dept}' is not an EMR option")
        if div and div not in VALID_DIVS:
            problems.append(f"'{title}': division '{div}' is not an EMR option")
    return problems


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────

def load_roster(path=None):
    """Roster people, sorted by name. Returns (people, problem).

    Each person: {name, title, shift, dept, div}. Reuses update_employees.load_roster_xlsx
    so both tools agree on what the roster file means. Its row-level validation (dates,
    identifiers) is for the roster-update run and is irrelevant here — a bad date
    elsewhere in the sheet must not stop you entering encounters.
    """
    path = path or ROSTER_XLSX
    if not os.path.exists(path):
        return [], f"{os.path.basename(path)} not found in {_HERE}."
    try:
        import update_employees as ue
        rows, _errors, _warnings = ue.load_roster_xlsx(path)
    except Exception as exc:
        return [], f"Could not read {os.path.basename(path)}: {exc}"

    seen, people, titles = set(), [], {}
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        title, shift = parse_new_identifier(row.get("new_identifier"))
        people.append({"name": name, "title": title, "shift": shift})
        if title:
            titles[title] = titles.get(title, 0) + 1

    if not people:
        return [], f"{os.path.basename(path)} has no usable 'name' column."

    resolved = sync_title_file(titles)
    for person in people:
        person["dept"], person["div"] = resolved.get(person["title"], ("", ""))

    people.sort(key=lambda p: p["name"].lower())
    return people, None


# A cell this long or longer is a description; shorter ones are labels/hints. The
# real descriptions run 100-430 characters; the labels and "Choose ..." notes run
# 14-54. Nothing sits near the boundary.
DESCRIPTION_MIN_CHARS = 60


def load_library(path=None):
    """[{tab, label, hint, text}] — one entry per DESCRIPTION cell in the workbook.

    DON'T PARSE THIS BY COLUMN. The workbook is hand-maintained and has no header row
    and no fixed schema: a single row mixes Dane's own note-to-self ('Choose "Other",
    "Rest Break"'), a scenario label ('High Heat Index Days'), and one or more long
    description texts — in whatever columns suited the day. Tabs disagree with each
    other, and some rows carry two unrelated descriptions side by side.

    So classify by length instead. Every long cell becomes its own pickable entry;
    the short cells in its row become its label. A cell starting with "Choose" is
    Dane's reminder of which detail boxes to tick, kept as `hint` so the tool can tick
    them for him.

    Joining a row's cells together — and dropping row 1 as a "header" — is what put
    'Choose "Other" | Job-Specific Coaching (High Heat Index Days) | EIS asked...'
    into 77 medical records, and hid the first description of every tab.

    Missing or unreadable workbook just means no Library button — never a crash.
    """
    path = path or LIBRARY_XLSX
    if not os.path.exists(path):
        return []
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=True, read_only=True)
    except Exception:
        return []

    entries = []
    for tab in wb.sheetnames:
        for row in wb[tab].iter_rows(values_only=True):
            cells = [str(c).strip() for c in (row or [])
                     if c is not None and str(c).strip()]
            if not cells:
                continue
            hint, labels, texts = "", [], []
            for cell in cells:
                if len(cell) >= DESCRIPTION_MIN_CHARS:
                    texts.append(cell)
                elif not hint and cell.lower().startswith("choose"):
                    hint = cell
                else:
                    labels.append(cell)
            for text in texts:
                entries.append({"tab": tab,
                                "label": " · ".join(labels) or tab,
                                "hint": hint,
                                "text": text})
    wb.close()
    return entries


def details_from_hint(hint, valid_details):
    """Detail names quoted in a "Choose ..." note, matched to the EMR's own list.

    Dane writes 'Choose "Other", "Rest Break", and "Rest (Task Design)"' next to a
    description — the boxes that description expects. Match those to the chosen
    coaching type's real options (case-insensitively; "Other" maps to whatever that
    type calls its catch-all, e.g. "Other job coaching"). Anything that doesn't match
    a real detail — a coaching type name, say — is ignored rather than guessed at.
    """
    wanted = re.findall(r'"([^"]+)"', hint or "")
    matched = []
    for want in wanted:
        for name in valid_details:
            if name.lower() == want.lower() or (
                    want.lower() == "other" and name.lower().startswith("other")):
                if name not in matched:
                    matched.append(name)
                break
    return matched


def load_prefs(path=None):
    """Which titles/shifts are hidden. Set once, sticks between runs."""
    try:
        with open(path or PREFS_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        return set(data.get("hidden_titles", [])), set(data.get("hidden_shifts", []))
    except Exception:
        return set(), set()


def save_prefs(hidden_titles, hidden_shifts, path=None):
    try:
        with open(path or PREFS_JSON, "w", encoding="utf-8") as fh:
            json.dump({"hidden_titles": sorted(hidden_titles),
                       "hidden_shifts": sorted(hidden_shifts)}, fh, indent=2)
    except Exception:
        pass          # a pref file that won't save must never block entering encounters


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────

class EncounterBuilder(tk.Tk):

    def __init__(self, people, library, roster_problem=None, title_problems=()):
        super().__init__()
        self.title("Encounter Builder — check names, set the coaching once")
        self._fit_to_screen()

        self.people = people
        self.library = library
        self.by_name = {p["name"]: p for p in people}

        self.all_titles = sorted({p["title"] for p in people if p["title"]},
                                 key=str.lower)
        self.all_shifts = sorted({p["shift"] for p in people if p["shift"]})
        self.hidden_titles, self.hidden_shifts = load_prefs()
        # Drop stale prefs for titles/shifts that no longer exist in the roster.
        self.hidden_titles &= set(self.all_titles)
        self.hidden_shifts &= set(self.all_shifts)

        self.shown = []               # people currently passing every filter
        self.checked = set()          # persists across filter changes — the whole point
        # Each entry: {"rows": [...], "label": "..."} — kept as GROUPS, not one flat
        # list, so any group can be reviewed and deleted, not just the last one.
        self.groups = []
        self.detail_vars = {}

        # Row 0 (the panels) takes every spare pixel; row 1 (the batch bar) keeps its
        # own height no matter how small the window gets, so the buttons that finish
        # the job can never end up off-screen.
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        # The roster takes the slack, not the form: the group panel needs a fixed
        # ~490px and no more, so every spare pixel goes to the name list — which is
        # the thing you actually read 262 lines of.
        self.grid_columnconfigure(0, weight=1, minsize=430)
        self.grid_columnconfigure(1, weight=0)

        self._build_roster_panel()
        self._build_group_panel()
        self._build_batch_bar()
        self._refresh_titles()
        self._refresh_list()
        self._on_type_change()
        self._on_loc_mode()

        if roster_problem:
            messagebox.showerror("Roster", roster_problem)
        if title_problems:
            messagebox.showwarning(
                "work_titles.csv",
                "These rows in work_titles.csv aren't valid EMR options and will be "
                "ignored:\n\n" + "\n".join(f"  • {p}" for p in title_problems[:12]))

    def _fit_to_screen(self):
        """Size the window to the screen, not to a number I made up.

        Windows reports a *logical* screen size that already has display scaling baked
        in, so a hardcoded height that looks fine on a 1080p panel can be taller than
        the whole desktop at 133%. Ask what's actually there, leave room for the
        taskbar and title bar, and never exceed it.
        """
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(1180, sw - 40)
        h = min(780, sh - 100)          # taskbar + title bar + a margin
        self.geometry(f"{w}x{h}+{max((sw - w) // 2, 0)}+{max((sh - h) // 3, 0)}")
        # Small enough to fit a 1024x768 desktop; below this, scrollbars do the work.
        self.minsize(860, 540)

    @staticmethod
    def _scrolled_list(parent, **kw):
        """A Listbox + scrollbar that grows with its container."""
        wrap = ttk.Frame(parent)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        box = tk.Listbox(wrap, activestyle="none", exportselection=False, **kw)
        box.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(wrap, orient="vertical", command=box.yview)
        bar.grid(row=0, column=1, sticky="ns")
        box.config(yscrollcommand=bar.set)
        return wrap, box

    # ── left: filters + the roster ────────────

    def _build_roster_panel(self):
        frame = ttk.LabelFrame(self, text="Who did you see?", padding=6)
        frame.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=(8, 0))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(5, weight=1)      # the name list eats the spare height

        # Shift chips — a small closed set, so they live inline.
        shifts = ttk.Frame(frame)
        shifts.grid(row=0, column=0, sticky="w")
        ttk.Label(shifts, text="Shift:").pack(side="left", padx=(0, 8))
        self.shift_vars = {}
        for shift in self.all_shifts:
            var = tk.BooleanVar(value=shift not in self.hidden_shifts)
            self.shift_vars[shift] = var
            ttk.Checkbutton(shifts, text=shift, variable=var,
                            command=self._on_filter_change).pack(side="left", padx=(0, 10))

        head = ttk.Frame(frame)
        head.grid(row=1, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(head, text="Work titles to show:").pack(side="left")
        ttk.Button(head, text="None", width=6,
                   command=lambda: self._all_titles(False)).pack(side="right")
        ttk.Button(head, text="All", width=5,
                   command=lambda: self._all_titles(True)).pack(side="right", padx=4)

        # A Listbox, not 32 Checkbuttons: it scrolls natively and toggles with the same
        # click idiom as the name list below it. height=4 keeps its *requested* size
        # small so a short window spends its pixels on the names instead.
        wrap, self.titles_box = self._scrolled_list(frame, font=("Consolas", 10), height=4)
        wrap.grid(row=2, column=0, sticky="nsew")
        self.titles_box.bind("<Button-1>", self._on_title_click)

        ttk.Separator(frame, orient="horizontal").grid(row=3, column=0, sticky="ew",
                                                       pady=6)

        find = ttk.Frame(frame)
        find.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(find, text="Find:").pack(side="left", padx=(0, 6))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._refresh_list())
        entry = ttk.Entry(find, textvariable=self.filter_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.focus_set()

        wrap, self.listbox = self._scrolled_list(frame, font=("Consolas", 12), height=8,
                                                 selectmode=tk.EXTENDED)
        wrap.grid(row=5, column=0, sticky="nsew")
        self.listbox.bind("<Button-1>", self._on_click)
        self.listbox.bind("<Return>", lambda e: self._toggle_selection())
        self.listbox.bind("<space>", lambda e: self._toggle_selection())

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, sticky="ew", pady=(6, 2))
        ttk.Button(buttons, text="Check all shown",
                   command=lambda: self._bulk(True)).pack(side="left")
        ttk.Button(buttons, text="Uncheck all shown",
                   command=lambda: self._bulk(False)).pack(side="left", padx=4)
        ttk.Button(buttons, text="Clear all",
                   command=self._clear_all).pack(side="left")

        self.count_label = ttk.Label(frame, text="", font=("Segoe UI", 10, "bold"))
        self.count_label.grid(row=7, column=0, sticky="w", pady=(2, 0))
        ttk.Label(frame, text="Click a name to check it. Hidden titles/shifts are "
                             "remembered between runs.",
                  foreground="#555", wraplength=600).grid(row=8, column=0, sticky="w")

    # ── title filter ──────────────────────────

    def _title_line(self, title):
        n = sum(1 for p in self.people if p["title"] == title)
        return f"{'X' if title not in self.hidden_titles else ' '}  {title} ({n})"

    def _refresh_titles(self):
        self.titles_box.delete(0, tk.END)
        for title in self.all_titles:
            self.titles_box.insert(tk.END, self._title_line(title))

    def _on_title_click(self, event):
        idx = self.titles_box.nearest(event.y)
        if 0 <= idx < len(self.all_titles):
            title = self.all_titles[idx]
            if title in self.hidden_titles:
                self.hidden_titles.discard(title)
            else:
                self.hidden_titles.add(title)
            self.titles_box.delete(idx)
            self.titles_box.insert(idx, self._title_line(title))
            self._on_filter_change()
        return "break"

    def _all_titles(self, show):
        self.hidden_titles = set() if show else set(self.all_titles)
        self._refresh_titles()
        self._on_filter_change()

    def _on_filter_change(self):
        self.hidden_shifts = {s for s, v in self.shift_vars.items() if not v.get()}
        save_prefs(self.hidden_titles, self.hidden_shifts)
        self._refresh_list()

    # ── name list ─────────────────────────────

    def _visible(self, person):
        if person["title"] and person["title"] in self.hidden_titles:
            return False
        if person["shift"] and person["shift"] in self.hidden_shifts:
            return False
        return self.filter_var.get().strip().lower() in person["name"].lower()

    def _display(self, person):
        return f"{'X' if person['name'] in self.checked else ' '}  {person['name']}"

    def _refresh_list(self):
        self.shown = [p for p in self.people if self._visible(p)]
        self.listbox.delete(0, tk.END)
        for person in self.shown:
            self.listbox.insert(tk.END, self._display(person))
        self._update_count()

    def _update_count(self):
        filtered_out = sum(1 for p in self.people
                           if p["title"] in self.hidden_titles
                           or p["shift"] in self.hidden_shifts)
        # A name checked while a filter hid it still counts — say so, so a group can
        # never quietly include someone you can't currently see.
        hidden_checks = len(self.checked - {p["name"] for p in self.shown})
        extra = f"  ({hidden_checks} checked but not shown)" if hidden_checks else ""
        self.count_label.config(
            text=f"{len(self.checked)} checked  ·  {len(self.shown)} shown  ·  "
                 f"{filtered_out} filtered out  ·  {len(self.people)} on roster{extra}")

    def _on_click(self, event):
        idx = self.listbox.nearest(event.y)
        if 0 <= idx < len(self.shown):
            self._toggle(idx)
        return "break"      # don't let the click also drive selection highlighting

    def _toggle_selection(self):
        for idx in self.listbox.curselection():
            self._toggle(idx)

    def _toggle(self, idx):
        person = self.shown[idx]
        name = person["name"]
        self.checked.discard(name) if name in self.checked else self.checked.add(name)
        self.listbox.delete(idx)
        self.listbox.insert(idx, self._display(person))
        self._update_count()

    def _bulk(self, on):
        for person in self.shown:
            self.checked.add(person["name"]) if on else self.checked.discard(person["name"])
        self._refresh_list()

    def _clear_all(self):
        self.checked.clear()
        self._refresh_list()

    # ── right: the group ──────────────────────

    def _build_group_panel(self):
        frame = ttk.LabelFrame(self, text="What was the encounter? (applies to everyone checked)",
                               padding=6)
        frame.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=(8, 0))
        self.group_frame = frame

        row = 0
        ttk.Label(frame, text="Date").grid(row=row, column=0, sticky="w", pady=4)
        self.date_var = tk.StringVar(value=date.today().strftime("%m/%d/%Y"))
        ttk.Entry(frame, textvariable=self.date_var, width=14).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(frame, text="Encounter type").grid(row=row, column=0, sticky="w", pady=4)
        self.etype_var = tk.StringVar(value=ace.ENCOUNTER_TYPES[0])
        ttk.Combobox(frame, textvariable=self.etype_var, values=ace.ENCOUNTER_TYPES,
                     state="readonly", width=38).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(frame, text="Coaching type").grid(row=row, column=0, sticky="w", pady=4)
        self.type_var = tk.StringVar(value=PICK_ONE)
        box = ttk.Combobox(frame, textvariable=self.type_var, values=[PICK_ONE] + COACHING_TYPES,
                           state="readonly", width=38)
        box.grid(row=row, column=1, sticky="w")
        box.bind("<<ComboboxSelected>>", lambda e: self._on_type_change())

        row += 1
        ttk.Label(frame, text="Details").grid(row=row, column=0, sticky="nw", pady=4)
        self.details_frame = ttk.Frame(frame)
        self.details_frame.grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=2,
                                                       sticky="ew", pady=8)

        # ── where they were ──
        row += 1
        ttk.Label(frame, text="Department / shift",
                  font=("Segoe UI", 9, "bold")).grid(row=row, column=0, columnspan=2,
                                                     sticky="w")
        row += 1
        self.loc_mode = tk.StringVar(value="per_employee")
        ttk.Radiobutton(frame, text="Each employee's own, from the roster  "
                                    "(use for a group spread across departments)",
                        variable=self.loc_mode, value="per_employee",
                        command=self._on_loc_mode).grid(row=row, column=0, columnspan=2,
                                                        sticky="w")
        row += 1
        ttk.Radiobutton(frame, text="Same for everyone in this group  "
                                    "(use for a sweep of one area)",
                        variable=self.loc_mode, value="group",
                        command=self._on_loc_mode).grid(row=row, column=0, columnspan=2,
                                                        sticky="w")

        row += 1
        self.group_loc = ttk.Frame(frame)
        self.group_loc.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(self.group_loc, text="Work area").grid(row=0, column=0, sticky="w", pady=3)
        self.area_var = tk.StringVar()
        area = ttk.Entry(self.group_loc, textvariable=self.area_var, width=38)
        area.grid(row=0, column=1, sticky="w")
        area.bind("<KeyRelease>", lambda e: self._resolve_area())
        ttk.Label(self.group_loc, text='e.g. "station 85", "wrap weld", "line lead weld"',
                  foreground="#555").grid(row=1, column=1, sticky="w")

        ttk.Label(self.group_loc, text="Department").grid(row=2, column=0, sticky="w", pady=3)
        self.dept_var = tk.StringVar()
        dept = ttk.Combobox(self.group_loc, textvariable=self.dept_var,
                            values=[BLANK] + ace.FIELD_OPTIONS.get("Department", []),
                            state="readonly", width=36)
        dept.grid(row=2, column=1, sticky="w")

        ttk.Label(self.group_loc, text="Division").grid(row=3, column=0, sticky="w", pady=3)
        self.div_var = tk.StringVar()
        div = ttk.Combobox(self.group_loc, textvariable=self.div_var,
                           values=[BLANK] + ace.FIELD_OPTIONS.get("Division", []),
                           state="readonly", width=36)
        div.grid(row=3, column=1, sticky="w")

        ttk.Label(self.group_loc, text="Shift").grid(row=4, column=0, sticky="w", pady=3)
        self.shift_var = tk.StringVar()
        shift = ttk.Combobox(self.group_loc, textvariable=self.shift_var,
                             values=[BLANK] + ace.FIELD_OPTIONS.get("Shift", []),
                             state="readonly", width=36)
        shift.grid(row=4, column=1, sticky="w")

        # (widget, the state it returns to when the group mode is active). A Combobox
        # must go back to "readonly", not "normal" — "normal" would let a free-typed
        # value that the EMR has never heard of into the CSV.
        self._group_loc_widgets = [(area, "normal"), (dept, "readonly"),
                                   (div, "readonly"), (shift, "readonly")]

        row += 1
        self.loc_note = ttk.Label(frame, text="", foreground="#555", wraplength=620)
        self.loc_note.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 0))

        row += 1
        ttk.Label(frame, text="Category").grid(row=row, column=0, sticky="w", pady=4)
        self.cat_var = tk.StringVar(value=fm.CATEGORY_DEFAULT)
        ttk.Combobox(frame, textvariable=self.cat_var,
                     values=[BLANK] + ace.FIELD_OPTIONS.get("Category", []),
                     state="readonly", width=38).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(frame, text="Prompted by").grid(row=row, column=0, sticky="w", pady=4)
        self.prompted_var = tk.StringVar(value=ace.WHAT_PROMPTED_OPTIONS[0])
        ttk.Combobox(frame, textvariable=self.prompted_var, values=ace.WHAT_PROMPTED_OPTIONS,
                     state="readonly", width=38).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=2,
                                                       sticky="ew", pady=8)

        row += 1
        head = ttk.Frame(frame)
        head.grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Label(head, text="Description").pack(side="left")
        if self.library:
            ttk.Button(head, text="Library…", width=10,
                       command=self._open_library).pack(side="left", padx=8)
            ttk.Label(head, text=f"{len(self.library)} standard descriptions in "
                                 f"{len({e['tab'] for e in self.library})} tabs",
                      foreground="#555").pack(side="left")
        else:
            ttk.Label(head, text="(workbook not found — type the description)",
                      foreground="#555").pack(side="left", padx=8)

        row += 1
        # height=4 keeps the *requested* height small so the whole panel fits a short
        # screen; the row weight lets it grow into whatever space is actually spare.
        self.desc_text = tk.Text(frame, height=4, wrap="word", font=("Segoe UI", 9))
        self.desc_text.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=4)
        frame.grid_rowconfigure(row, weight=1)
        frame.grid_columnconfigure(1, weight=1)

    def _on_loc_mode(self):
        per_employee = self.loc_mode.get() == "per_employee"
        for widget, active_state in self._group_loc_widgets:
            widget.configure(state="disabled" if per_employee else active_state)
        if per_employee:
            no_dept = sum(1 for p in self.people if not p["dept"])
            self.loc_note.config(
                text=f"From each person's roster record. "
                     f"{len(self.people) - no_dept} of {len(self.people)} are mapped; "
                     f"the other {no_dept} get a blank department (safe) until you map "
                     f"them in work_titles.csv.")
        else:
            self.loc_note.config(text="Every row in the group gets the same department, "
                                      "division and shift.")

    def _on_type_change(self):
        """Rebuild the detail checkboxes for the chosen type.

        Sourced from ati_coaching_encounter.CHECKBOX_UUID_MAP, so the boxes on screen
        are exactly the ones the EMR form has for that type — an invalid combination
        is not expressible.
        """
        for child in self.details_frame.winfo_children():
            child.destroy()
        self.detail_vars = {}

        chosen = self.type_var.get()
        if chosen == PICK_ONE:
            ttk.Label(self.details_frame, text="(pick a coaching type first)",
                      foreground="#555").grid(row=0, column=0, sticky="w")
            return

        options = sorted(ace.CHECKBOX_UUID_MAP.get(chosen, {}))
        if not options:
            ttk.Label(self.details_frame, text="(this type has no details)",
                      foreground="#555").grid(row=0, column=0, sticky="w")
            return

        for i, name in enumerate(options):
            var = tk.BooleanVar()
            self.detail_vars[name] = var
            ttk.Checkbutton(self.details_frame, text=name, variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 16))

    def _resolve_area(self):
        dept, div = fm.resolve(self.area_var.get())
        if dept:
            self.dept_var.set(dept)
        if div:
            self.div_var.set(div)

    def _open_library(self):
        """Pick ONE standard description — never a whole worksheet row."""
        win = tk.Toplevel(self)
        win.title("Standard descriptions")
        win.geometry("1000x560")
        win.transient(self)
        win.grab_set()
        win.grid_rowconfigure(2, weight=1)
        win.grid_rowconfigure(4, weight=0)
        win.grid_columnconfigure(0, weight=1)

        search_var = tk.StringVar()
        top = ttk.Frame(win, padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Search:").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(top, textvariable=search_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.focus_set()

        ttk.Label(win, text="One line per description. Pick one and only its text goes "
                            "in — the tab name and your \"Choose …\" note stay out of "
                            "the record.",
                  foreground="#555").grid(row=1, column=0, sticky="w", padx=10)

        wrap, box = self._scrolled_list(win, font=("Consolas", 10), height=12)
        wrap.grid(row=2, column=0, sticky="nsew", padx=10, pady=(4, 6))

        ttk.Label(win, text="Full text of the selected description:",
                  foreground="#555").grid(row=3, column=0, sticky="w", padx=10)
        preview = tk.Text(win, height=6, wrap="word", font=("Segoe UI", 9))
        preview.grid(row=4, column=0, sticky="nsew", padx=10)

        shown = []

        def refresh(*_):
            needle = search_var.get().strip().lower()
            shown[:] = [e for e in self.library
                        if needle in (e["tab"] + e["label"] + e["text"]).lower()]
            box.delete(0, tk.END)
            for e in shown:
                one_line = " ".join(e["text"].split())
                box.insert(tk.END, f"{e['tab']} · {e['label']}  —  {one_line[:90]}…")

        def on_select(*_):
            sel = box.curselection()
            preview.delete("1.0", tk.END)
            if not sel:
                return
            entry_ = shown[sel[0]]
            preview.insert("1.0", entry_["text"])
            if entry_["hint"]:
                preview.insert(tk.END, f"\n\n[your note: {entry_['hint']}]")

        def use():
            sel = box.curselection()
            if not sel:
                return
            chosen = shown[sel[0]]
            # ONLY the description text. Not the tab, not the label, not the note.
            self.desc_text.delete("1.0", tk.END)
            self.desc_text.insert("1.0", chosen["text"])
            ticked = details_from_hint(chosen["hint"], list(self.detail_vars))
            for name in ticked:
                self.detail_vars[name].set(True)
            win.destroy()
            if ticked:
                self.batch_detail.config(
                    text="Ticked from your note: " + ", ".join(ticked))

        search_var.trace_add("write", refresh)
        box.bind("<<ListboxSelect>>", on_select)
        box.bind("<Double-Button-1>", lambda e: use())

        bar = ttk.Frame(win, padding=(10, 8))
        bar.grid(row=5, column=0, sticky="ew")
        ttk.Label(bar, text=f"{len(self.library)} descriptions",
                  foreground="#555").pack(side="left")
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="Use this one", command=use).pack(side="right", padx=6)
        refresh()

    # ── bottom: the batch ─────────────────────

    def _build_batch_bar(self):
        """The three buttons that finish the job. Pinned to the bottom row, which has
        no weight — it keeps its height however small the window gets, so these can
        never be pushed off-screen the way a fixed-size window pushed them off."""
        frame = ttk.Frame(self, padding=(8, 6))
        frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        counts = ttk.Frame(frame)
        counts.grid(row=0, column=0, sticky="w")
        self.batch_label = ttk.Label(counts, text="Batch: 0 rows",
                                     font=("Segoe UI", 10, "bold"))
        self.batch_label.pack(anchor="w")
        self.batch_detail = ttk.Label(counts, text="Nothing added yet.", foreground="#555")
        self.batch_detail.pack(anchor="w")

        actions = ttk.Frame(frame)
        actions.grid(row=0, column=1, sticky="e")
        ttk.Button(actions, text="Add group to batch",
                   command=self._add_group).pack(side="left")
        ttk.Button(actions, text="Review batch…",
                   command=self._review_batch).pack(side="left", padx=6)
        ttk.Button(actions, text="Undo last group",
                   command=self._undo_group).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Write & enter batch",
                   command=self._write_csv).pack(side="left")

    def _add_group(self):
        if not self.checked:
            messagebox.showwarning("No one checked", "Check at least one name first.")
            return
        if self.type_var.get() == PICK_ONE:
            messagebox.showwarning(
                "Coaching type",
                "Pick a coaching type.\n\nIt is the clinical classification of the "
                "encounter and this tool will not guess it for you.")
            return

        raw_date = self.date_var.get().strip()
        if raw_date:
            try:
                datetime.strptime(raw_date, "%m/%d/%Y")
            except ValueError:
                messagebox.showwarning("Date", f"'{raw_date}' isn't MM/DD/YYYY.")
                return

        description = self.desc_text.get("1.0", "end-1c").strip()
        if not description:
            messagebox.showwarning("Description", "Write or pick a description first.")
            return

        per_employee = self.loc_mode.get() == "per_employee"
        details = "; ".join(sorted(n for n, v in self.detail_vars.items() if v.get()))

        rows = []
        for name in sorted(self.checked, key=str.lower):
            person = self.by_name[name]
            rows.append({
                "employee": name,
                "date": raw_date,
                "encounter_type": self.etype_var.get(),
                "department": person["dept"] if per_employee else self.dept_var.get(),
                "division": person["div"] if per_employee else self.div_var.get(),
                "category": self.cat_var.get(),
                "shift": person["shift"] if per_employee else self.shift_var.get(),
                "coaching_type": self.type_var.get(),
                "details": details,
                "description": description,
                "what_prompted": self.prompted_var.get(),
            })

        where = "per employee" if per_employee else (self.dept_var.get() or "no dept")
        self.groups.append({
            "rows": rows,
            "label": (f"{len(rows):>3} people  ·  {self.type_var.get()}"
                      f"{'  ·  ' + details if details else ''}"
                      f"  ·  {raw_date or 'today'}  ·  {where}"),
        })
        self._clear_all()
        self._update_batch()

    @property
    def batch(self):
        """Every row across every group, in the order they were added."""
        return [row for group in self.groups for row in group["rows"]]

    def _undo_group(self):
        if self.groups:
            self.groups.pop()
            self._update_batch()

    def _delete_group(self, index):
        if 0 <= index < len(self.groups):
            self.groups.pop(index)
            self._update_batch()

    def _update_batch(self):
        by_type = {}
        for row in self.batch:
            by_type[row["coaching_type"]] = by_type.get(row["coaching_type"], 0) + 1
        self.batch_label.config(text=f"Batch: {len(self.batch)} rows "
                                     f"in {len(self.groups)} group(s)")
        self.batch_detail.config(
            text="  ·  ".join(f"{n} {t}" for t, n in sorted(by_type.items()))
                 or "Nothing added yet.")
        if getattr(self, "review_win", None) and self.review_win.winfo_exists():
            self._fill_review()

    # ── review / edit the batch ───────────────

    def _review_batch(self):
        """See every group and delete any of them — not just the last one."""
        if getattr(self, "review_win", None) and self.review_win.winfo_exists():
            self.review_win.lift()
            return
        win = tk.Toplevel(self)
        self.review_win = win
        win.title("Batch — review and edit")
        win.geometry("900x420")
        win.transient(self)
        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)

        ttk.Label(win, text="Every group in the batch. Select one to remove it — the "
                            "rest are untouched.",
                  foreground="#555").grid(row=0, column=0, columnspan=2,
                                          sticky="w", padx=10, pady=(10, 4))

        wrap, self.review_box = self._scrolled_list(win, font=("Consolas", 10), height=12)
        wrap.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10)

        bar = ttk.Frame(win, padding=(10, 8))
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.review_total = ttk.Label(bar, text="", font=("Segoe UI", 10, "bold"))
        self.review_total.pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="Delete selected group",
                   command=self._delete_selected).pack(side="right", padx=6)
        self._fill_review()

    def _fill_review(self):
        self.review_box.delete(0, tk.END)
        for i, group in enumerate(self.groups, 1):
            self.review_box.insert(tk.END, f"{i:>2}.  {group['label']}")
        self.review_total.config(
            text=f"{len(self.batch)} row(s) in {len(self.groups)} group(s)")

    def _delete_selected(self):
        sel = self.review_box.curselection()
        if not sel:
            messagebox.showinfo("Nothing selected",
                                "Pick a group in the list first.", parent=self.review_win)
            return
        index = sel[0]
        group = self.groups[index]
        if messagebox.askyesno(
                "Remove group?",
                f"Remove group {index + 1} — {len(group['rows'])} row(s)?\n\n"
                f"{group['label']}\n\nThe other groups stay as they are.",
                parent=self.review_win):
            self._delete_group(index)

    def _write_csv(self):
        if not self.batch:
            messagebox.showwarning("Empty batch", "Add a group first.")
            return
        if os.path.exists(OUT_CSV):
            replaced = sum(1 for _ in open(OUT_CSV, encoding="utf-8-sig")) - 1
            if not messagebox.askyesno(
                    "Replace encounters.csv?",
                    f"encounters.csv currently holds {max(replaced, 0)} row(s).\n\n"
                    f"It will be backed up to encounters.bak.csv and replaced with "
                    f"your {len(self.batch)} row(s). Continue?"):
                return
            with open(OUT_CSV, encoding="utf-8-sig") as src, \
                 open(BAK_CSV, "w", encoding="utf-8-sig", newline="") as dst:
                dst.write(src.read())

        # QUOTE_ALL: an unquoted comma shifts every later column one place left and
        # silently corrupts the row. Quoting everything makes that impossible.
        with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=ace.CSV_COLUMNS, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(self.batch)

        if messagebox.askyesno(
                "Written — enter them now?",
                f"{len(self.batch)} row(s) written to encounters.csv.\n\n"
                f"Enter them into the EMR now?\n\n"
                f"A browser opens and pauses for you to log in, confirm the worksite "
                f"and approve the batch. Everything saves as a draft — nothing is "
                f"finalised without you."):
            self._enter_now()
        else:
            messagebox.showinfo(
                "Saved",
                "encounters.csv is ready. When you want to enter it, either press "
                "'Write & enter batch' again or run:\n\n    .\\Run-Encounters.ps1")

    def _enter_now(self):
        """Hand the batch to Run-Encounters.ps1, in its own console window.

        A separate process rather than importing the automation: it drives Playwright,
        opens a browser and pops Windows dialogs, and it needs a REAL terminal —
        phi_redact keys off stdout.isatty(), so piping its output into this GUI would
        redact the very names Dane needs to read while approving the batch. It also
        validates before entering and refuses to run a bad batch, so there is nothing
        to check first.
        """
        script = os.path.join(_HERE, "Run-Encounters.ps1")
        try:
            subprocess.Popen(
                ["powershell", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", script],
                cwd=_HERE,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        except Exception as exc:
            messagebox.showerror(
                "Couldn't start it",
                f"{exc}\n\nencounters.csv is written and fine — run it yourself:\n"
                f"    .\\Run-Encounters.ps1")


def main():
    people, problem = load_roster()
    resolved = {p["title"]: (p["dept"], p["div"]) for p in people if p["title"]}
    titles = set(resolved)
    app = EncounterBuilder(people, load_library(), problem, validate_title_map(resolved))
    # Counts only — never a name — so a captured run stays PHI-free.
    unmapped = sum(1 for p in people if not p["dept"])
    print(f"Roster loaded : {len(people)} people, {len(titles)} work titles")
    print(f"Work area     : {len(people) - unmapped} mapped, {unmapped} unmapped "
          f"(fill work_titles.csv to map the rest)")
    app.mainloop()


if __name__ == "__main__":
    main()
