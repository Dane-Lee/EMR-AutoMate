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
    Department would be wrong for most of them. roster.xlsx carries each person's OWN
    department and division (Dane set them by hand for every employee), plus their shift
    (parsed from `new_identifier`, which import_hc_roster composes as 'ID-Title-Shift').
    So every row in a group carries that person's real work area, while the coaching is
    still set once for the whole group. A person with no department set just gets a
    blank one, which is safe — a wrong one is not.

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
import sys
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
PREFS_JSON = os.path.join(_HERE, "builder_prefs.json")

# No default. An unset coaching type blocks the group — see the module docstring.
PICK_ONE = "— pick one —"
BLANK = ""

# Checked names get a filled box + a soft green row so the pick is obvious at a glance
# across a 261-name list — the faint "X" prefix was too easy to lose track of.
CHECK_ON = "☑"
CHECK_OFF = "☐"
CHECK_BG = "#d8efd0"
CHECK_FG = "#166534"

# A flat, current palette — replaces tkinter's default beveled-gray ("Windows 95") look.
UI_BG = "#f3f4f6"          # window / panel background
UI_CARD = "#ffffff"        # inputs, cards, the name list
UI_TEXT = "#1f2933"        # primary text
UI_MUTED = "#6b7280"       # secondary / hint text
UI_BORDER = "#d3d7de"      # thin borders and separators
UI_ACCENT = "#2f6fed"      # focus / primary action
UI_ACCENT_SOFT = "#e7eefc"  # hover / subtle fill

COACHING_TYPES = sorted(ace.COACHING_TYPE_UUIDS)

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
# DATA LOADING
# ─────────────────────────────────────────────

def load_roster(path=None):
    """Roster people, sorted by name. Returns (people, problem).

    Each person: {name, title, shift, dept, div}. Department and division come STRAIGHT
    from the roster's own columns — Dane set the right work area for every employee by
    hand, so there is nothing to infer. (Title is still parsed from new_identifier, but
    only to drive the work-title filter; it no longer decides anyone's department.)

    Reuses update_employees.load_roster_xlsx so both tools agree on what the roster file
    means. Its row-level validation (dates, identifiers) is for the roster-update run
    and is irrelevant here — a bad date elsewhere in the sheet must not stop you
    entering encounters.
    """
    path = path or ROSTER_XLSX
    if not os.path.exists(path):
        return [], f"{os.path.basename(path)} not found in {_HERE}."
    try:
        import update_employees as ue
        rows, _errors, _warnings = ue.load_roster_xlsx(path)
    except Exception as exc:
        return [], f"Could not read {os.path.basename(path)}: {exc}"

    seen, people = set(), []
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        title, shift = parse_new_identifier(row.get("new_identifier"))
        people.append({
            "name": name,
            "title": title,
            "shift": shift,
            "dept": (row.get("department") or "").strip(),
            "div": (row.get("division") or "").strip(),
        })

    if not people:
        return [], f"{os.path.basename(path)} has no usable 'name' column."

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
    """Which work areas (divisions) / shifts are hidden. Set once, sticks between runs."""
    try:
        with open(path or PREFS_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        return set(data.get("hidden_areas", [])), set(data.get("hidden_shifts", []))
    except Exception:
        return set(), set()


def save_prefs(hidden_areas, hidden_shifts, path=None):
    try:
        with open(path or PREFS_JSON, "w", encoding="utf-8") as fh:
            json.dump({"hidden_areas": sorted(hidden_areas),
                       "hidden_shifts": sorted(hidden_shifts)}, fh, indent=2)
    except Exception:
        pass          # a pref file that won't save must never block entering encounters


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────

class EncounterBuilder(tk.Tk):

    def __init__(self, people, library, roster_problem=None, demo=False):
        super().__init__()
        self.title("Encounter Builder — check names, set the coaching once")
        self._fit_to_screen()
        self._set_fonts()

        self.demo = demo
        self.people = people
        self.library = library
        self.by_name = {p["name"]: p for p in people}

        # Filter people by their WORK AREA (division) — 8 clean options that Dane
        # actually thinks in (Assembly, Weld, Admin/Office, …), not the 30-odd job
        # titles the old filter listed. Every person now has a division from the
        # roster, so this covers everyone.
        self.all_areas = sorted({p["div"] for p in people if p["div"]})
        self.all_depts = sorted({p["dept"] for p in people if p["dept"]}, key=str.lower)
        self.all_shifts = sorted({p["shift"] for p in people if p["shift"]})
        # The demo starts clean and never persists — it must not read or clobber the
        # real builder_prefs.json (that bled Dane's live filters into the sandbox).
        self.hidden_areas, self.hidden_shifts = (set(), set()) if demo else load_prefs()
        self.hidden_areas &= set(self.all_areas)     # drop prefs for areas/shifts
        self.hidden_shifts &= set(self.all_shifts)   # that no longer exist

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
        self._refresh_list()
        self._on_type_change()
        self._on_loc_mode()

        # Come to the front. Launched from a detached process on Windows, a Tk window
        # often opens BEHIND the console/other windows and never grabs focus — which
        # looks exactly like "it didn't open". Briefly topmost, then release so it
        # doesn't stay pinned over everything else.
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.winfo_exists() and self.attributes("-topmost", False))

        if roster_problem:
            messagebox.showerror("Roster", roster_problem)

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

    def _set_fonts(self):
        """Give the whole app a flat, current look and readable text — the default
        theme is beveled 1990s gray and the 9pt controls were too small. Runs before any
        widget is built (option_add / ttk styles must precede widget creation)."""
        base = ("Segoe UI", 11)
        self.configure(bg=UI_BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")     # flat + fully colour-configurable, unlike 'vista'
        except tk.TclError:
            pass

        style.configure(".", background=UI_BG, foreground=UI_TEXT, font=base,
                        bordercolor=UI_BORDER, focuscolor=UI_BG,
                        fieldbackground=UI_CARD)
        style.configure("TFrame", background=UI_BG)
        style.configure("TLabel", background=UI_BG, foreground=UI_TEXT)
        style.configure("TLabelframe", background=UI_BG, bordercolor=UI_BORDER,
                        relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=UI_BG, foreground=UI_MUTED,
                        font=("Segoe UI", 11, "bold"))

        # Flat buttons with a thin border; hover tints toward the accent.
        style.configure("TButton", background=UI_CARD, foreground=UI_TEXT,
                        bordercolor=UI_BORDER, relief="solid", borderwidth=1,
                        padding=(11, 5))
        style.map("TButton",
                  background=[("pressed", UI_ACCENT_SOFT), ("active", UI_ACCENT_SOFT)],
                  bordercolor=[("active", UI_ACCENT), ("focus", UI_ACCENT)])
        # A filled accent button for the primary action.
        style.configure("Accent.TButton", background=UI_ACCENT, foreground="#ffffff",
                        bordercolor=UI_ACCENT)
        style.map("Accent.TButton",
                  background=[("pressed", "#1f5fe0"), ("active", "#3b78ef")],
                  foreground=[("disabled", "#e5e7eb")])

        for w in ("TCheckbutton", "TRadiobutton"):
            style.configure(w, background=UI_BG, foreground=UI_TEXT, focuscolor=UI_BG)
            style.map(w, background=[("active", UI_BG)])
        style.configure("TEntry", fieldbackground=UI_CARD, bordercolor=UI_BORDER,
                        relief="solid", borderwidth=1, padding=5)
        style.map("TEntry", bordercolor=[("focus", UI_ACCENT)])
        style.configure("TCombobox", fieldbackground=UI_CARD, background=UI_CARD,
                        bordercolor=UI_BORDER, arrowcolor=UI_TEXT, relief="solid",
                        borderwidth=1, padding=5, font=base)
        style.map("TCombobox", fieldbackground=[("readonly", UI_CARD)],
                  bordercolor=[("focus", UI_ACCENT)])
        style.configure("TSeparator", background=UI_BORDER)
        style.configure("Vertical.TScrollbar", background=UI_BG, troughcolor=UI_BG,
                        bordercolor=UI_BG, arrowcolor=UI_MUTED)

        self.option_add("*TCombobox*Listbox.font", base)
        self.option_add("*TCombobox*Listbox.background", UI_CARD)
        self.option_add("*TCombobox*Listbox.selectBackground", UI_ACCENT_SOFT)
        self.option_add("*TCombobox*Listbox.selectForeground", UI_TEXT)

        self._checkmark_indicator(style)

    def _checkmark_indicator(self, style):
        """Replace the flat theme's X-shaped checkbox mark with a real checkmark.

        The indicator is a theme-drawn element, so the only clean way to change the
        glyph is to swap in our own images: an empty white box, and an accent box with
        a white check. Images are kept on self so Tk doesn't garbage-collect them.
        """
        size = 16
        off = [[UI_BG] * size for _ in range(size)]
        on = [[UI_BG] * size for _ in range(size)]

        def box(grid, fill, border):
            for y in range(2, size - 1):
                for x in range(2, size - 1):
                    grid[y][x] = fill
            for i in range(2, size - 1):
                grid[2][i] = grid[size - 2][i] = border
                grid[i][2] = grid[i][size - 2] = border

        box(off, UI_CARD, UI_BORDER)
        box(on, UI_ACCENT, UI_ACCENT)
        for x, y in [(5, 8), (6, 9), (7, 10), (8, 9), (9, 8), (10, 7), (11, 6)]:
            for yy in (y, y - 1):        # 2px stroke so the check reads clearly
                on[yy][x] = "#ffffff"

        def to_img(grid):
            img = tk.PhotoImage(width=size, height=size, master=self)
            img.put(" ".join("{" + " ".join(r) + "}" for r in grid))
            return img

        self._chk_off, self._chk_on = to_img(off), to_img(on)
        try:
            style.element_create("Flat.Checkbutton.indicator", "image", self._chk_off,
                                 ("selected", self._chk_on), padding=(0, 0, 6, 0))
            style.layout("TCheckbutton", [
                ("Checkbutton.padding", {"sticky": "nswe", "children": [
                    ("Flat.Checkbutton.indicator", {"side": "left", "sticky": ""}),
                    ("Checkbutton.focus", {"side": "left", "sticky": "", "children": [
                        ("Checkbutton.label", {"sticky": "nswe"})]})]})])
        except tk.TclError:
            pass          # element already defined (another instance in this process)

    @staticmethod
    def _scrolled_list(parent, **kw):
        """A Listbox + scrollbar that grows with its container. tk.Listbox is a classic
        widget the ttk theme can't reach, so its flat look is set here directly."""
        wrap = ttk.Frame(parent)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        box = tk.Listbox(wrap, activestyle="none", exportselection=False,
                         bg=UI_CARD, fg=UI_TEXT, borderwidth=0, highlightthickness=1,
                         highlightbackground=UI_BORDER, highlightcolor=UI_BORDER,
                         selectbackground=UI_ACCENT_SOFT, selectforeground=UI_TEXT,
                         **kw)
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
                            command=self._on_filter_change).pack(side="left", padx=(0, 12))

        # Work-area filter: real checkboxes for the 8 divisions, not a scroll list of
        # 30 job titles. Two columns so all of them are on screen at once.
        head = ttk.Frame(frame)
        head.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        ttk.Label(head, text="Areas to show:").pack(side="left")
        ttk.Button(head, text="none", width=6,
                   command=lambda: self._all_areas(False)).pack(side="right")
        ttk.Button(head, text="all", width=5,
                   command=lambda: self._all_areas(True)).pack(side="right", padx=4)

        areas = ttk.Frame(frame)
        areas.grid(row=2, column=0, sticky="ew", pady=(0, 2))
        self.area_vars = {}
        for i, area in enumerate(self.all_areas):
            n = sum(1 for p in self.people if p["div"] == area)
            var = tk.BooleanVar(value=area not in self.hidden_areas)
            self.area_vars[area] = var
            ttk.Checkbutton(areas, text=f"{area} ({n})", variable=var,
                            command=self._on_filter_change).grid(
                                row=i // 2, column=i % 2, sticky="w", padx=(0, 14))

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
        # Review the current pick: collapse the list to just who's checked.
        self.checked_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(find, text="checked only", variable=self.checked_only,
                        command=self._refresh_list).pack(side="left", padx=(8, 0))

        # Taller, roomier rows in a clean proportional font (was cramped monospace).
        wrap, self.listbox = self._scrolled_list(frame, font=("Segoe UI", 13), height=8,
                                                 selectmode=tk.EXTENDED)
        wrap.grid(row=5, column=0, sticky="nsew")
        self.listbox.bind("<Button-1>", self._on_click)
        self.listbox.bind("<Return>", lambda e: self._toggle_selection())
        self.listbox.bind("<space>", lambda e: self._toggle_selection())

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, sticky="ew", pady=(6, 2))
        ttk.Button(buttons, text="Check all shown",
                   command=lambda: self._bulk(True)).pack(side="left")
        ttk.Button(buttons, text="Uncheck shown",
                   command=lambda: self._bulk(False)).pack(side="left", padx=4)
        ttk.Button(buttons, text="Clear all",
                   command=self._clear_all).pack(side="left")

        # Check everyone in one department in a single move — e.g. the whole of
        # "Finisher" for a sweep — without disturbing the current filter/view.
        pick = ttk.Frame(frame)
        pick.grid(row=7, column=0, sticky="w", pady=(6, 2))
        ttk.Label(pick, text="Check everyone in:").pack(side="left", padx=(0, 6))
        self.dept_pick_var = tk.StringVar(value="")
        combo = ttk.Combobox(pick, textvariable=self.dept_pick_var, state="readonly",
                             values=self.all_depts, width=26)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self._check_all_in_dept())

        self.count_label = ttk.Label(frame, text="", font=("Segoe UI", 13, "bold"),
                                     foreground=CHECK_FG)
        self.count_label.grid(row=8, column=0, sticky="w", pady=(4, 0))
        ttk.Label(frame, text="Click a name to check it (checked = green). "
                             "'checked only' reviews your pick. Hidden areas/shifts "
                             "are remembered between runs.",
                  foreground="#555", wraplength=600).grid(row=9, column=0, sticky="w")

    # ── work-area (division) filter ────────────

    def _all_areas(self, show):
        for var in self.area_vars.values():
            var.set(show)
        self._on_filter_change()

    def _on_filter_change(self):
        self.hidden_shifts = {s for s, v in self.shift_vars.items() if not v.get()}
        self.hidden_areas = {a for a, v in self.area_vars.items() if not v.get()}
        if not self.demo:
            save_prefs(self.hidden_areas, self.hidden_shifts)
        self._refresh_list()

    def _check_all_in_dept(self):
        dept = self.dept_pick_var.get()
        if not dept:
            return
        for p in self.people:
            if p["dept"] == dept:
                self.checked.add(p["name"])
        self.dept_pick_var.set("")     # reset so the same dept can be picked again
        self._refresh_list()

    # ── name list ─────────────────────────────

    def _visible(self, person):
        needle = self.filter_var.get().strip().lower()
        # Reviewing the pick: show EVERY checked person, even one a hidden area/shift
        # would otherwise drop — the point is to see the whole group before adding it.
        if self.checked_only.get():
            return person["name"] in self.checked and needle in person["name"].lower()
        if person["div"] and person["div"] in self.hidden_areas:
            return False
        if person["shift"] and person["shift"] in self.hidden_shifts:
            return False
        return needle in person["name"].lower()

    def _display(self, person):
        mark = CHECK_ON if person["name"] in self.checked else CHECK_OFF
        return f" {mark}  {person['name']}"

    def _paint_row(self, idx, checked):
        if checked:
            self.listbox.itemconfig(idx, background=CHECK_BG, foreground=CHECK_FG)
        else:
            self.listbox.itemconfig(idx, background="", foreground="")

    def _refresh_list(self):
        self.shown = [p for p in self.people if self._visible(p)]
        self.listbox.delete(0, tk.END)
        for i, person in enumerate(self.shown):
            self.listbox.insert(tk.END, self._display(person))
            self._paint_row(i, person["name"] in self.checked)
        self._update_count()

    def _update_count(self):
        filtered_out = sum(1 for p in self.people
                           if p["div"] in self.hidden_areas
                           or p["shift"] in self.hidden_shifts)
        # A name checked while a filter hid it still counts — say so, so a group can
        # never quietly include someone you can't currently see.
        hidden_checks = len(self.checked - {p["name"] for p in self.shown})
        extra = f"   ({hidden_checks} checked but hidden)" if hidden_checks else ""
        self.count_label.config(
            text=f"{CHECK_ON} {len(self.checked)} checked      "
                 f"{len(self.shown)} shown · {filtered_out} filtered out · "
                 f"{len(self.people)} on roster{extra}")

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
        now_checked = name not in self.checked
        self.checked.add(name) if now_checked else self.checked.discard(name)
        # "Show checked only" is on: an unchecked row should drop out immediately.
        if self.checked_only.get() and not now_checked:
            self._refresh_list()
            return
        self.listbox.delete(idx)
        self.listbox.insert(idx, self._display(person))
        self._paint_row(idx, now_checked)
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
        ttk.Label(frame, text="Date").grid(row=row, column=0, sticky="w", pady=2)
        self.date_var = tk.StringVar(value=date.today().strftime("%m/%d/%Y"))
        ttk.Entry(frame, textvariable=self.date_var, width=14).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(frame, text="Encounter type").grid(row=row, column=0, sticky="w", pady=2)
        self.etype_var = tk.StringVar(value=ace.ENCOUNTER_TYPES[0])
        ttk.Combobox(frame, textvariable=self.etype_var, values=ace.ENCOUNTER_TYPES,
                     state="readonly", width=38).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(frame, text="Coaching type").grid(row=row, column=0, sticky="w", pady=2)
        self.type_var = tk.StringVar(value=PICK_ONE)
        box = ttk.Combobox(frame, textvariable=self.type_var, values=[PICK_ONE] + COACHING_TYPES,
                           state="readonly", width=38)
        box.grid(row=row, column=1, sticky="w")
        box.bind("<<ComboboxSelected>>", lambda e: self._on_type_change())

        row += 1
        ttk.Label(frame, text="Details").grid(row=row, column=0, sticky="nw", pady=2)
        self.details_frame = ttk.Frame(frame)
        self.details_frame.grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=2,
                                                       sticky="ew", pady=4)

        # ── where they were ──
        row += 1
        ttk.Label(frame, text="Department / shift",
                  font=("Segoe UI", 11, "bold")).grid(row=row, column=0, columnspan=2,
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
        ttk.Label(frame, text="Category").grid(row=row, column=0, sticky="w", pady=2)
        self.cat_var = tk.StringVar(value=fm.CATEGORY_DEFAULT)
        ttk.Combobox(frame, textvariable=self.cat_var,
                     values=[BLANK] + ace.FIELD_OPTIONS.get("Category", []),
                     state="readonly", width=38).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(frame, text="Prompted by").grid(row=row, column=0, sticky="w", pady=2)
        self.prompted_var = tk.StringVar(value=ace.WHAT_PROMPTED_OPTIONS[0])
        ttk.Combobox(frame, textvariable=self.prompted_var, values=ace.WHAT_PROMPTED_OPTIONS,
                     state="readonly", width=38).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=2,
                                                       sticky="ew", pady=4)

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
        self.desc_text = tk.Text(frame, height=3, wrap="word", font=("Segoe UI", 11),
                                 bg=UI_CARD, fg=UI_TEXT, borderwidth=1, relief="solid",
                                 highlightthickness=1, highlightbackground=UI_BORDER,
                                 highlightcolor=UI_ACCENT, padx=6, pady=6)
        self.desc_text.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=4)
        frame.grid_rowconfigure(row, weight=1)
        frame.grid_columnconfigure(1, weight=1)

    def _on_loc_mode(self):
        per_employee = self.loc_mode.get() == "per_employee"
        for widget, active_state in self._group_loc_widgets:
            widget.configure(state="disabled" if per_employee else active_state)
        if per_employee:
            no_dept = sum(1 for p in self.people if not p["dept"])
            note = (f"Department, division and shift come from each person's roster "
                    f"record.")
            if no_dept:
                note += (f" {no_dept} of {len(self.people)} have no department set — "
                         f"those get a blank one (safe).")
            self.loc_note.config(text=note)
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
        """Browse standard descriptions as readable CARDS — full text visible, grouped
        by category, filterable. The old one-line-per-description list truncated every
        entry so you had to click each just to read it; this shows them."""
        WRAP = 940     # text wrap width inside a card (dialog is a fixed 1040 wide)
        win = tk.Toplevel(self)
        win.title("Standard descriptions")
        win.geometry("1040x680")
        win.transient(self)
        win.grab_set()
        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)

        # ── top: category + search ──
        top = ttk.Frame(win, padding=(12, 10))
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Category:").pack(side="left", padx=(0, 6))
        cats = ["All categories"] + sorted({e["tab"] for e in self.library})
        cat_var = tk.StringVar(value=cats[0])
        ttk.Combobox(top, textvariable=cat_var, values=cats, state="readonly",
                     width=24).pack(side="left", padx=(0, 16))
        ttk.Label(top, text="Search:").pack(side="left", padx=(0, 6))
        search_var = tk.StringVar()
        se = ttk.Entry(top, textvariable=search_var)
        se.pack(side="left", fill="x", expand=True)
        se.focus_set()

        # ── middle: a scrollable column of cards ──
        canvas = tk.Canvas(win, highlightthickness=0, bg=UI_BG)
        canvas.grid(row=1, column=0, sticky="nsew", padx=(12, 0))
        vsb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vsb.set)
        inner = ttk.Frame(canvas)
        cwin = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))
        # Mouse wheel scrolls the list while the (modal) dialog is up; released on close.
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        def use(entry):
            # ONLY the description text reaches the record — never the label or note.
            self.desc_text.delete("1.0", tk.END)
            self.desc_text.insert("1.0", entry["text"])
            ticked = details_from_hint(entry["hint"], list(self.detail_vars))
            for name in ticked:
                self.detail_vars[name].set(True)
            win.destroy()
            if ticked:
                self.batch_detail.config(
                    text="Ticked from your note: " + ", ".join(ticked))

        def render(*_):
            for child in inner.winfo_children():
                child.destroy()
            cat, needle = cat_var.get(), search_var.get().strip().lower()
            matches = [e for e in self.library
                       if (cat == "All categories" or e["tab"] == cat)
                       and needle in (e["tab"] + e["label"] + e["text"]).lower()]
            if not matches:
                ttk.Label(inner, text="No descriptions match.",
                          foreground="#777").pack(anchor="w", padx=12, pady=14)
            for e in matches:
                # tk.Frame (not ttk) so it gets a clean 1px border + white fill,
                # instead of the theme's beveled panel look.
                card = tk.Frame(inner, bg=UI_CARD, highlightbackground=UI_BORDER,
                                highlightthickness=1, bd=0, padx=14, pady=11)
                card.pack(fill="x", expand=True, padx=(0, 12), pady=6)
                card.columnconfigure(0, weight=1)
                head = tk.Frame(card, bg=UI_CARD)
                head.grid(row=0, column=0, sticky="ew")
                head.columnconfigure(0, weight=1)
                tk.Label(head, text=e["label"] or e["tab"], bg=UI_CARD, fg=UI_TEXT,
                         font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
                tk.Label(head, text=e["tab"], bg=UI_ACCENT_SOFT, fg=UI_ACCENT,
                         font=("Segoe UI", 9), padx=8, pady=2).grid(
                    row=0, column=1, sticky="e", padx=8)
                ttk.Button(head, text="Use", width=7, style="Accent.TButton",
                           command=lambda x=e: use(x)).grid(row=0, column=2, sticky="e")
                tk.Label(card, text=e["text"], bg=UI_CARD, fg=UI_TEXT, wraplength=WRAP,
                         justify="left", font=("Segoe UI", 11)).grid(
                    row=1, column=0, sticky="w", pady=(6, 0))
                if e["hint"]:
                    tk.Label(card, text=f"note: {e['hint']}", bg=UI_CARD, fg=UI_MUTED,
                             wraplength=WRAP, justify="left", font=("Segoe UI", 10)).grid(
                        row=2, column=0, sticky="w", pady=(4, 0))
                for w in (card, head):
                    w.bind("<Double-Button-1>", lambda ev, x=e: use(x))

        cat_var.trace_add("write", render)
        search_var.trace_add("write", render)

        bar = ttk.Frame(win, padding=(12, 10))
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(bar, text=f"{len(self.library)} standard descriptions · "
                            f"only the text you pick reaches the record",
                  foreground="#555").pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        render()

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
        ttk.Button(actions, text="Write & enter batch", style="Accent.TButton",
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


# ─────────────────────────────────────────────
# DEMO MODE — work on the UI without any PHI
# ─────────────────────────────────────────────
# `python encounter_builder.py --demo` loads obviously-fake people and descriptions
# but REAL EMR departments/divisions/shifts, so the interface behaves exactly as it
# does live. Nothing here reads roster.xlsx or the workbook, so a demo run — and a
# screenshot of it — carries no PHI. Any UI change applies to the real builder too;
# it's the same window, just handed fake data.

def _demo_people():
    surnames = ["Ashby", "Booker", "Calder", "Danforth", "Ellison", "Fenwick",
                "Grimes", "Hollis", "Ives", "Jansen", "Keller", "Larkin", "Mercer",
                "Nash", "Osgood", "Pryor", "Quill", "Ramsey", "Sutton", "Thorne",
                "Underwood", "Vance", "Whitlock", "Yates", "Zimmer", "Abbott",
                "Boyd", "Crane", "Doyle", "Ellis", "Frost", "Gray", "Hale", "Iverson"]
    firsts = ["Alex", "Bailey", "Casey", "Dana", "Emerson", "Finley", "Gale",
              "Harper", "Indy", "Jordan", "Kai", "Logan", "Morgan", "Noel", "Quinn",
              "Reese", "Sage", "Tatum", "Val", "Wren"]
    areas = [("Finisher", "Assembly"), ("Packaging", "Assembly"),
             ("Stations 40-70", "Assembly"), ("Stations 80-95", "Assembly"),
             ("Line Lead", "Assembly"), ("Suspension", "Weld"), ("Wrap Weld", "Weld"),
             ("Frame Bracket", "Weld"), ("Beam", "Weld"), ("Bushing Press", "Machine Operator"),
             ("THT/Cut Off", "Machine Operator"), ("Spiders Machine", "Machine Operator"),
             ("Material Handler", "Material Handler"), ("Paint Booth", "Paint Line"),
             ("Caulk Station", "Paint Line"), ("Admin/Office", "Admin/Office"),
             ("Supervisor", "Admin/Office"), ("NHO", "Admin/Office"),
             ("Maintenance", "Maintenance"), ("Quality", "Quality")]
    titles = ["Assembler", "Welder", "Machine Operator", "Materials Handler",
              "Line Lead", "Supervisor", "Technician II", "Painter", "Maintenance Tech",
              "Quality Inspector"]
    people = []
    for i, last in enumerate(surnames):
        dept, div = areas[i % len(areas)]
        people.append({"name": f"{last}, {firsts[i % len(firsts)]}",
                       "title": titles[i % len(titles)], "shift": ["1st", "2nd"][i % 2],
                       "dept": dept, "div": div})
    return people


def _demo_library():
    return [
        {"tab": "Safety", "label": 'PPE — gloves', "hint": 'Choose "PPE Use"',
         "text": "EIS reviewed correct glove selection for the task with the EE and "
                 "confirmed proper fit before work resumed."},
        {"tab": "Job Coaching", "label": "High heat index", "hint": 'Choose "Other", "Rest break"',
         "text": "EIS discussed hydration and pacing with the EE given the high heat "
                 "index, and reviewed the work-to-rest ratio for the shift."},
        {"tab": "Health/Wellness", "label": "Hydration", "hint": 'Choose "Hydration"',
         "text": "EIS coached the EE on daily water intake and signs of dehydration, "
                 "and set a simple hydration target for the shift."},
        {"tab": "Ergonomics", "label": "Workstation", "hint": 'Choose "Office ergo adjustment"',
         "text": "EIS adjusted the EE's workstation height and monitor position and "
                 "reviewed neutral posture."},
    ]


def main(demo=False):
    # Under pythonw.exe (GUI launch, no console) sys.stdout/stderr can be None, and a
    # later print() then crashes the process before the window ever shows. Give them a
    # sink so the builder runs the same whether launched with python or pythonw.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    demo = demo or "--demo" in sys.argv
    if demo:
        people, problem, library = _demo_people(), None, _demo_library()
    else:
        people, problem = load_roster()
        library = load_library()

    app = EncounterBuilder(people, library, problem, demo=demo)
    if demo:
        app.title("Encounter Builder — DEMO (fake names, real EMR options)")

    # Counts only — never a name — so a captured run stays PHI-free.
    no_area = sum(1 for p in people if not p["dept"])
    titles = len({p["title"] for p in people if p["title"]})
    print(f"{'DEMO — ' if demo else ''}Roster loaded : {len(people)} people, "
          f"{titles} work titles")
    print(f"Work area     : {len(people) - no_area} with a department, "
          f"{no_area} blank (blank is safe)")
    app.mainloop()


if __name__ == "__main__":
    main()
