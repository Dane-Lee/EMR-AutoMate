"""
intake_grid.py — the encounter intake sheet, as a window
========================================================
STEP 1 of the build: the grid itself. Type in it, tab around it, check rows off.
Nothing is sent anywhere yet and nothing is written to disk — this step exists to
settle whether the sheet FEELS right before any wiring goes behind it.

WHY A WINDOW AND NOT THE SPREADSHEET
    `Encounter Intake Template.xlsx` already works, but it is a staging area Dane
    fills in and then hands off by hand. The window is the same sheet with somewhere
    for the rows to GO: a checked row becomes a job, the job comes back as text, and
    the text lands in a cell to copy out. Excel cannot do the middle part.

COLUMNS
    Straight from the template's row 3 — A (ref), D (Encounter Type), E (Reason),
    F (Shift), G (Description / Incident Details) — plus a Kind cell in front of the
    type and the done box at the end. Columns B and C are Last and First. THEY ARE NOT
    HERE AND NEVER WILL BE; see PHI below. The PA-only columns (I-AC) and pwc_nwc are
    later steps, on their own tab.

    KIND is not in Dane's template. It splits the 18 encounter types into the two
    families that get handled differently downstream — assessments, which come back as
    field-by-field write-ups, and coaching, which comes back as one description and
    feeds the encounter builder. Setting it narrows the Encounter Type dropdown from 18
    to 7 or 11. It is a shortcut, not a gate: leave it blank and the dropdown offers
    all 18, and whichever type is picked back-fills the Kind.

    The date is not a column. In Dane's template it lives in the tab name and C1 —
    one date per sheet — so it sits in the header bar here, the same way.

PHI
    This sheet is the DE-IDENTIFIED side of the line. `ref` is Dane's key; he maps
    ref -> person on his own machine, where the names already live. No name column
    exists, so none can be sent. The description column is still the one that can
    leak (`ENCOUNTER_INTAKE.md`: "the guy on second shift back from knee surgery"
    identifies someone as surely as a name does) — that stays Dane's scan to make,
    and the send step, when it exists, is what has to enforce it.

RUN IT
    python intake_grid.py
"""

import json
import os
import queue
import re
import threading
from datetime import date, datetime

import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox

import intake_runner

_HERE = os.path.dirname(os.path.abspath(__file__))
SHEET_JSON = os.path.join(_HERE, "intake_sheet.json")     # what Dane has typed so far
OUTBOX_JSON = os.path.join(_HERE, "intake_outbox.json")   # rows handed off for writing

# -- palette: the builder's "Shift Board", so the two windows read as one tool ------
# Two palettes, same roles. Cells sit WELL clear of the window ground in both: at the
# builder's card colour the caret was lost against the field, and a sheet you click into
# needs the active cell to announce itself — it is the only thing saying where you are.
PALETTES = {
    "dark": {
        "bg": "#1b2027", "card": "#39424d", "row_alt": "#323b45", "focus": "#4d5966",
        "text": "#f2f5f8", "muted": "#98a3b0", "border": "#4a5561",
        "accent": "#f0a32b", "accent_soft": "#2a2419", "on_accent": "#14181d",
        "confirm": "#9dbe3b",
    },
    "light": {
        "bg": "#e7ebef", "card": "#ffffff", "row_alt": "#f3f5f8", "focus": "#fdf0d5",
        "text": "#161a1f", "muted": "#5b6572", "border": "#c2cad3",
        # Safety amber is unreadable as text on white, so light mode darkens it to a
        # burnt amber that still reads as the same colour but clears 4.5:1.
        "accent": "#a8690a", "accent_soft": "#fbf1dc", "on_accent": "#ffffff",
        "confirm": "#4d6a12",
    },
}

UI_BG = UI_CARD = UI_ROW_ALT = UI_FOCUS = UI_TEXT = UI_MUTED = UI_BORDER = ""
UI_ACCENT = UI_ACCENT_SOFT = UI_ON_ACCENT = UI_CONFIRM = ""


def apply_palette(name):
    """Point the UI_* names at one palette.

    Widgets read these at CREATION time, so switching is always followed by a rebuild.
    That is cheaper than it sounds and much cheaper than tracking every widget ever
    made so its colours can be poked individually."""
    global UI_BG, UI_CARD, UI_ROW_ALT, UI_FOCUS, UI_TEXT, UI_MUTED, UI_BORDER
    global UI_ACCENT, UI_ACCENT_SOFT, UI_ON_ACCENT, UI_CONFIRM
    p = PALETTES.get(name) or PALETTES["dark"]
    UI_BG, UI_CARD, UI_ROW_ALT = p["bg"], p["card"], p["row_alt"]
    UI_FOCUS, UI_TEXT, UI_MUTED, UI_BORDER = p["focus"], p["text"], p["muted"], p["border"]
    UI_ACCENT, UI_ACCENT_SOFT = p["accent"], p["accent_soft"]
    UI_ON_ACCENT, UI_CONFIRM = p["on_accent"], p["confirm"]


apply_palette("dark")

FONT_BODY = ("Segoe UI", 11)
FONT_CELL = ("Segoe UI", 10)
FONT_REF = ("Consolas", 10)      # tabular figures, so the ref column stays a column
_DISPLAY_FAMILY = "Bahnschrift"

# Encounter Type — the template's own D4:D22 list, verbatim except that the literal
# duplicate of "Task Assessment" (it appears at rows 6 and 11) is collapsed to one.
# "Prevention Mobilty" is misspelled in Dane's sheet; it is LEFT misspelled here. Both
# defects are noted in ENCOUNTER_INTAKE.md as his to confirm, and a dropdown is not the
# place to quietly decide that a value he may be matching on should read differently.
#
# Split into the two families the Kind cell chooses between. The split is exhaustive —
# 7 + 11 = the whole D4:D22 list — so narrowing by Kind can never hide a valid type.
ASSESSMENT_TYPES = [
    "Physical Assessment",
    "Follow-Up Assessment",
    "Task Assessment",
    "Human Movement Assessment",
    "HMA Follow-Up",
    "HMA Reassessment",
    "Office Assessment",
]
# Alphabetical (Dane, 2026-08-25). Eleven near-interchangeable labels have no natural
# order to remember, so the template's order is just the order they were typed in —
# alphabetical at least tells you where to look. Sorted here rather than by hand so a
# type added later cannot land out of order.
COACHING_TYPES = sorted([
    "Job-Specific",
    "Prevention Mobilty and Stretching",
    "Safety",
    "Ergonomic Adjustment",
    "Health and Wellness",
    "Relationship Development",
    "Group Class",
    "Near Miss Education",
    "Fitness Center Visit",
    "Friend/Family Consult",
    "General Medical",
])
ENCOUNTER_TYPE_OPTIONS = ASSESSMENT_TYPES + COACHING_TYPES

# Where a returned block goes. Tabs exist so a day's PAs are not interleaved with forty
# coaching lines while Dane copies them out one at a time — each tab is one errand.
#
# ⚠️ Office Assessment is a guess. It is an assessment, and PA / Follow-Up is the only
# assessment tab that would hold it, but Dane has not said it belongs there. Task
# Assessment gets its own tab because he wants it handed to the TA Assistant, which is a
# tool this code has not seen.
PAGE_SHEET = "Intake"       # the grid itself — the first bottom tab, always present
TAB_COACHING = "Coaching"
TAB_PA = "PA / Follow-Up"
TAB_HMA = "HMA"
TAB_TASK = "Task"
TAB_ORDER = [TAB_COACHING, TAB_PA, TAB_HMA, TAB_TASK]

TAB_OF_TYPE = {
    "Physical Assessment": TAB_PA,
    "Follow-Up Assessment": TAB_PA,
    "Office Assessment": TAB_PA,            # ⚠️ unconfirmed
    "Human Movement Assessment": TAB_HMA,
    "HMA Follow-Up": TAB_HMA,
    "HMA Reassessment": TAB_HMA,
    "Task Assessment": TAB_TASK,
}

KIND_ASSESSMENT = "Assessment"
KIND_COACHING = "Coaching"
KINDS = [KIND_COACHING, KIND_ASSESSMENT]   # Dane's order: Coaching box first
TYPES_BY_KIND = {KIND_ASSESSMENT: ASSESSMENT_TYPES, KIND_COACHING: COACHING_TYPES}
# The reverse lookup is what lets a type chosen from the full list BACK-FILL its Kind,
# so the cell is a shortcut in both directions and never a gate.
KIND_OF_TYPE = {t: k for k, types in TYPES_BY_KIND.items() for t in types}

# The builder parses these three out of new_identifier and colours its roster rail by
# them (SHIFT_RAIL). Same closed vocabulary here.
SHIFT_OPTIONS = ["1st", "2nd", "3rd"]

# (key, heading, width in characters, kind)
# The width is a MINIMUM. Description carries ELASTIC below, so it swallows whatever the
# window has spare instead of leaving a dead strip past the last column.
COLUMNS = [
    ("ref",         "#",              4,  "ref"),
    ("kind",        "Kind",           22, "toggle"),
    ("type",        "Encounter Type", 28, "choice"),
    ("reason",      "Reason",         22, "text"),
    ("shift",       "Shift",          6,  "choice"),
    ("description", "Description / Incident Details", 38, "text"),
    ("done",        "Done",           5,  "check"),
    ("status",      "Status",         9,  "status"),
]
ELASTIC = "description"

# Row lifecycle. A row is eligible for Send only from PENDING, so a second click on
# Send never re-hands rows that already went — the duplicate-submission problem.
ST_PENDING = ""
ST_SENT = "sent"
ST_RETURNED = "returned"

# The gate in front of Send. These find STRUCTURAL identifiers — runs of digits, dates,
# ages, emails. They cannot find a name and they cannot find shorthand: "the guy on
# second shift back from knee surgery" sails straight through, and ENCOUNTER_INTAKE.md
# is explicit that scanning for that is Dane's job, not a regex's. What this catches is
# the thing that is easy to leave in by accident and impossible to argue is not an
# identifier once it has left the machine.
_RISK_PATTERNS = [
    (re.compile(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b"), "a date"),
    (re.compile(r"\b\d{1,3}\s*(y/?o\b|yo\b|years?\s+old)", re.I), "an age"),
    (re.compile(r"[\w.+-]+@[\w-]+\.\w{2,}"), "an email address"),
    (re.compile(r"\b\d{4,}\b"), "a 4+ digit number"),
]
CHOICES = {"type": ENCOUNTER_TYPE_OPTIONS, "shift": SHIFT_OPTIONS}

# Typing the bare number picks the shift. "1st"/"2nd"/"3rd" is what the roster and the
# EMR use, but nobody types the ordinal twenty times a day.
SHIFT_KEYS = {"1": "1st", "2": "2nd", "3": "3rd"}

START_ROWS = 20          # the template numbers ref 1-40; 20 fits the screen, "+10 rows" adds more
ROWS_PER_ADD = 10


def _saved_theme():
    """Read the theme out of the sheet file before any widget exists — the palette has
    to be chosen before the first widget is built, not after."""
    try:
        with open(SHEET_JSON, encoding="utf-8") as fh:
            name = json.load(fh).get("theme")
    except (OSError, ValueError):
        return "dark"
    return name if name in PALETTES else "dark"


class Row:
    """One line of the sheet. Holds its cell widgets and its Tk variables."""

    def __init__(self, number):
        self.number = number
        self.vars = {}
        self.widgets = {}
        self.kind_buttons = {}      # Coaching / Assessment -> the box that selects it
        self.result = None          # what came back for this row, once it has

    def value(self, key):
        return str(self.vars[key].get()).strip()

    def payload(self):
        """What leaves the machine. Built from an explicit column list, so a column
        added later is not swept into the outbox just by existing."""
        return {"ref": self.number,
                "kind": self.value("kind"),
                "type": self.value("type"),
                "reason": self.value("reason"),
                "shift": self.value("shift"),
                "description": self.value("description")}

    def is_blank(self):
        """Kind alone does not make a row real — it is one click and easy to hit by
        accident, so a row with nothing but a Kind still counts as empty."""
        return not any(str(self.vars[k].get()).strip()
                       for k, _, _, kind in COLUMNS if kind in ("choice", "text"))


class IntakeGrid(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Encounter Intake")
        self._set_fonts()
        self._fit_to_screen()

        self.rows = []
        self.sheet_date = tk.StringVar(value=date.today().strftime("%m-%d-%y"))
        self._loading = False     # suppresses autosave while the sheet is being restored
        self._save_job = None
        self.theme = _saved_theme()
        apply_palette(self.theme)

        self._results_queue = queue.Queue()
        self._run_thread = None
        self._scrollables = []
        self._page_counts = {}
        self.current_page = PAGE_SHEET

        self._build_ui()
        self._load_sheet()
        while len(self.rows) < START_ROWS:
            self._add_row()
        self._render_results()
        self.sheet_date.trace_add("write", lambda *a: self._queue_save())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._focus_cell(0, "kind")

        # Launched from a detached process on Windows a Tk window often opens BEHIND
        # everything and never grabs focus, which looks exactly like "it did not open".
        self.lift()
        self.attributes("-topmost", True)
        self._topmost_job = self.after(
            300, lambda: self.winfo_exists() and self.attributes("-topmost", False))

    # -- setup ---------------------------------------------------------------
    def _build_ui(self):
        """Everything below the toplevel. Separate from __init__ so a theme change can
        tear it down and build it again."""
        self.grid_rowconfigure(1, weight=1)      # the pages take every spare pixel
        self.grid_columnconfigure(0, weight=1)
        self._scrollables = []
        self._measure_columns()
        self._build_header_bar()
        self._build_footer()      # before the pages: _show_page touches its buttons
        self._build_pages()

    def _toggle_theme(self):
        """Swap the palette and rebuild.

        Widgets bake their colours in at creation, so the sheet is serialised, the UI
        is destroyed, and it is all built again from the saved state. It is the only
        honest way to repaint a tk.Entry without hunting down every widget by hand."""
        self.theme = "light" if self.theme == "dark" else "dark"
        apply_palette(self.theme)

        state = self._sheet_state()
        keep_page, keep_subs = self.current_page, dict(self.sub_current)
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        for child in self.winfo_children():
            child.destroy()

        self.rows = []
        self._set_fonts()
        self._build_ui()
        self._restore(state)
        while len(self.rows) < START_ROWS:
            self._add_row()
        self.sub_current.update(keep_subs)
        self._render_results()
        self._show_page(keep_page)
        self._save_sheet()

    def _fit_to_screen(self):
        """Size to the screen that is actually there. Windows reports a *logical*
        size with display scaling already baked in, so a literal that looks right on
        one panel is taller than the whole desktop on another."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(1240, sw - 40)
        h = min(760, sh - 100)          # taskbar + title bar + a margin
        self.geometry(f"{w}x{h}+{max((sw - w) // 2, 0)}+{max((sh - h) // 3, 0)}")
        self.minsize(900, 480)

    def _set_fonts(self):
        global _DISPLAY_FAMILY
        if _DISPLAY_FAMILY not in set(tkfont.families(self)):
            _DISPLAY_FAMILY = "Segoe UI"

        self.configure(bg=UI_BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")     # flat and fully colour-configurable, unlike 'vista'
        except tk.TclError:
            pass
        style.configure(".", background=UI_BG, foreground=UI_TEXT, font=FONT_BODY,
                        borderwidth=0, focuscolor=UI_BG)
        style.configure("TFrame", background=UI_BG)
        style.configure("TLabel", background=UI_BG, foreground=UI_TEXT)
        style.configure("Muted.TLabel", background=UI_BG, foreground=UI_MUTED)
        style.configure("Head.TLabel", background=UI_BG, foreground=UI_MUTED,
                        font=(_DISPLAY_FAMILY, 10))
        style.configure("Title.TLabel", background=UI_BG, foreground=UI_ACCENT,
                        font=(_DISPLAY_FAMILY, 15))
        style.configure("Count.TLabel", background=UI_BG, foreground=UI_CONFIRM,
                        font=("Consolas", 11))
        style.configure("TButton", background=UI_CARD, foreground=UI_TEXT,
                        bordercolor=UI_BORDER, borderwidth=1, padding=(12, 6))
        style.map("TButton", background=[("active", UI_BORDER)])
        style.configure("Accent.TButton", background=UI_ACCENT, foreground=UI_ON_ACCENT,
                        bordercolor=UI_ACCENT, font=(_DISPLAY_FAMILY, 11))
        style.map("Accent.TButton",
                  background=[("disabled", UI_CARD), ("active", "#ffbb4d")],
                  foreground=[("disabled", UI_MUTED)],
                  bordercolor=[("disabled", UI_BORDER)])
        style.configure("TCombobox", fieldbackground=UI_CARD, background=UI_CARD,
                        foreground=UI_TEXT, arrowcolor=UI_MUTED,
                        bordercolor=UI_BORDER, borderwidth=1, padding=2, font=FONT_CELL)
        style.map("TCombobox",
                  fieldbackground=[("focus", UI_FOCUS), ("readonly", UI_CARD)],
                  background=[("focus", UI_FOCUS)],
                  foreground=[("focus", UI_TEXT)],
                  bordercolor=[("focus", UI_ACCENT)], arrowcolor=[("focus", UI_ACCENT)])
        style.configure("TNotebook", background=UI_BG, borderwidth=0, tabmargins=0)
        style.configure("TNotebook.Tab", background=UI_BG, foreground=UI_MUTED,
                        bordercolor=UI_BORDER, lightcolor=UI_BG, darkcolor=UI_BG,
                        borderwidth=0, padding=(14, 6), font=(_DISPLAY_FAMILY, 10))
        style.map("TNotebook.Tab",
                  background=[("selected", UI_CARD)],
                  foreground=[("selected", UI_ACCENT), ("active", UI_TEXT)],
                  expand=[("selected", (0, 0, 0, 0))])
        style.configure("TCheckbutton", background=UI_CARD, foreground=UI_TEXT,
                        focuscolor=UI_CARD, indicatorcolor=UI_CARD)
        style.map("TCheckbutton",
                  background=[("active", UI_CARD)],
                  indicatorcolor=[("selected", UI_ACCENT), ("active", UI_BORDER)])
        # The dropdown list itself is a Tk (not ttk) widget — it ignores the style.
        self.option_add("*TCombobox*Listbox.background", UI_CARD)
        self.option_add("*TCombobox*Listbox.foreground", UI_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", UI_ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", UI_ON_ACCENT)
        self.option_add("*TCombobox*Listbox.font", FONT_CELL)

    def _measure_columns(self):
        """Header and body are two different frames, so the only thing keeping their
        columns lined up is an identical pixel width on both. Measure it once from the
        cell font rather than trusting a char width to render the same in each."""
        cell = tkfont.Font(family=FONT_CELL[0], size=FONT_CELL[1])
        self.col_px = {key: cell.measure("0") * chars + 16
                       for key, _, chars, _ in COLUMNS}

    # -- the header bar (date + tally) ---------------------------------------
    def _build_header_bar(self):
        bar = ttk.Frame(self, padding=(14, 10, 14, 6))
        bar.grid(row=0, column=0, sticky="ew")

        ttk.Label(bar, text="ENCOUNTER INTAKE", style="Title.TLabel").pack(side="left")
        ttk.Label(bar, text="   Date", style="Muted.TLabel").pack(side="left")
        d = tk.Entry(bar, textvariable=self.sheet_date, width=10, justify="center",
                     font=FONT_REF, bg=UI_CARD, fg=UI_TEXT, insertbackground=UI_ACCENT,
                     insertwidth=3, selectbackground=UI_ACCENT,
                     selectforeground=UI_ON_ACCENT, relief="flat", highlightthickness=2,
                     highlightbackground=UI_CARD, highlightcolor=UI_ACCENT)
        d.pack(side="left", padx=(8, 0), ipady=3)
        d.bind("<FocusIn>", lambda e: d.configure(bg=UI_FOCUS))
        d.bind("<FocusOut>", lambda e: d.configure(bg=UI_CARD))

        tk.Button(bar, text="Light" if self.theme == "dark" else "Dark",
                  font=FONT_CELL, relief="flat", bd=0, padx=12, pady=3,
                  cursor="hand2", takefocus=0, bg=UI_CARD, fg=UI_MUTED,
                  activebackground=UI_ACCENT_SOFT, activeforeground=UI_ACCENT,
                  command=self._toggle_theme).pack(side="left", padx=(10, 0))

        self.count_label = ttk.Label(bar, text="", style="Count.TLabel")
        self.count_label.pack(side="right")

    # -- pages ---------------------------------------------------------------
    def _build_pages(self):
        """Excel's model: one page at a time, filling the window, with the tabs along
        the bottom. The split pane this replaced gave the sheet and the results half a
        window each and neither enough — on an 800px screen that is about nine rows and
        four lines of text."""
        holder = tk.Frame(self, bg=UI_BG)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)

        self.pages = {}
        for name in [PAGE_SHEET] + TAB_ORDER:
            page = tk.Frame(holder, bg=UI_BG)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[name] = page

        self._build_sheet(self.pages[PAGE_SHEET])
        self._build_results()
        self._show_page(PAGE_SHEET)

    def _show_page(self, name):
        page = self.pages.get(name)
        if page is None:
            return
        self.current_page = name
        page.tkraise()
        self._paint_page_tabs()
        # The sheet page owns Send and +rows; they make no sense on a results page.
        on_sheet = (name == PAGE_SHEET)
        for widget in (self.send_button, self.add_rows_button):
            widget.grid() if on_sheet else widget.grid_remove()
        self.copy_button.grid_remove() if on_sheet else self.copy_button.grid()
        self.after_idle(self._fit_result_boxes)

    def _paint_page_tabs(self):
        for name, tab in self.page_tabs.items():
            on = (name == self.current_page)
            label = name
            if name in TAB_ORDER:
                count = self._page_counts.get(name, 0)
                if count:
                    label = "%s  %d" % (name, count)
            tab.configure(text=label,
                          bg=UI_CARD if on else UI_BG,
                          fg=UI_ACCENT if on else UI_MUTED,
                          activebackground=UI_CARD if on else UI_ACCENT_SOFT,
                          activeforeground=UI_ACCENT)

    def _build_sheet(self, parent):
        wrap = ttk.Frame(parent, padding=(14, 0, 14, 0))
        wrap.pack(fill="both", expand=True)
        wrap.grid_rowconfigure(1, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        # Header row: its own frame so it never scrolls away from the rows it labels.
        head = tk.Frame(wrap, bg=UI_BG)
        head.grid(row=0, column=0, sticky="ew")
        for c, (key, heading, _, kind) in enumerate(COLUMNS):
            head.grid_columnconfigure(c, minsize=self.col_px[key],
                                      weight=1 if key == ELASTIC else 0)
            anchor = "center" if kind in ("ref", "check") else "w"
            ttk.Label(head, text=heading.upper(), style="Head.TLabel",
                      anchor=anchor).grid(row=0, column=c, sticky="ew",
                                          padx=1, pady=(0, 4))
        tk.Frame(head, bg=UI_BORDER, height=1).grid(
            row=1, column=0, columnspan=len(COLUMNS), sticky="ew")
        # A spacer the width of the scrollbar, so the headings sit over their columns.
        head.grid_columnconfigure(len(COLUMNS), minsize=16)

        self.canvas = tk.Canvas(wrap, bg=UI_BG, highlightthickness=0, bd=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        bar.grid(row=1, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=bar.set)

        self.body = tk.Frame(self.canvas, bg=UI_BG)
        self._body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        for c, (key, _, _, _) in enumerate(COLUMNS):
            self.body.grid_columnconfigure(c, minsize=self.col_px[key],
                                           weight=1 if key == ELASTIC else 0)

        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._body_id, width=e.width))
        self._register_scrollable(self.canvas)
        # One global hook that DISPATCHES by pointer position, rather than the old
        # bind_all straight to this canvas — that one swallowed the wheel everywhere.
        self.bind_all("<MouseWheel>", self._on_wheel)

    # -- scrolling -----------------------------------------------------------
    def _register_scrollable(self, canvas):
        self._scrollables.append(canvas)

    def _on_wheel(self, event):
        """Send the wheel to whichever scrollable the pointer is actually over.

        The old code bound the wheel globally straight to the sheet canvas, so the
        results panes could not scroll at all — the event was consumed before it
        reached them. Tk widget path names are hierarchical, so a widget belongs to a
        canvas exactly when its path starts with that canvas's path."""
        target = str(event.widget)
        for canvas in self._scrollables:
            try:
                if not canvas.winfo_exists():
                    continue
            except tk.TclError:
                continue
            path = str(canvas)
            if target == path or target.startswith(path + "."):
                canvas.yview_scroll(int(-event.delta / 120), "units")
                return "break"
        # Not over anything scrollable: fall back to the page the pointer is on.
        for canvas in self._scrollables:
            try:
                if canvas.winfo_exists() and canvas.winfo_ismapped():
                    canvas.yview_scroll(int(-event.delta / 120), "units")
                    return "break"
            except tk.TclError:
                continue

    def _scrollable_area(self, parent):
        """Canvas + inner frame + scrollbar, wired up. Three panes needed this."""
        canvas = tk.Canvas(parent, bg=UI_BG, highlightthickness=0, bd=0)
        canvas.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        bar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=bar.set)
        body = tk.Frame(canvas, bg=UI_BG)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e, c=canvas, w=window: c.itemconfigure(w, width=e.width))
        self._register_scrollable(canvas)
        return body

    # -- what came back ------------------------------------------------------
    def _build_results(self):
        """One page per destination. PA / Follow-Up, HMA and Task get a SUB-TAB per
        encounter, because each of those is a full screen of fields and stacking three
        of them means scrolling past two to reach the third. Coaching stays a list —
        its blocks are two lines each and a list is faster to work down."""
        self._result_boxes = []
        self.tab_body = {}          # simple list pages
        self.sub_holder = {}        # pages that carry a sub-tab strip
        self.sub_strip = {}
        self.sub_tabs = {}          # page -> {ref: button}
        self.sub_current = {}       # page -> which ref is showing

        for name in TAB_ORDER:
            page = self.pages[name]
            page.grid_rowconfigure(1, weight=1)
            page.grid_columnconfigure(0, weight=1)

            head = tk.Frame(page, bg=UI_BG)
            head.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
            tk.Label(head, text=name.upper(), font=(_DISPLAY_FAMILY, 12),
                     bg=UI_BG, fg=UI_ACCENT).pack(side="left")

            if name == TAB_COACHING:
                area = tk.Frame(page, bg=UI_BG)
                area.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 8))
                self.tab_body[name] = self._scrollable_area(area)
            else:
                strip = tk.Frame(page, bg=UI_BG)
                strip.grid(row=1, column=0, sticky="ew", padx=14)
                holder = tk.Frame(page, bg=UI_BG)
                holder.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 8))
                holder.grid_rowconfigure(0, weight=1)
                holder.grid_columnconfigure(0, weight=1)
                page.grid_rowconfigure(1, weight=0)
                page.grid_rowconfigure(2, weight=1)
                self.sub_strip[name] = strip
                self.sub_holder[name] = holder
                self.sub_tabs[name] = {}

    def _show_sub(self, page_name, ref):
        frames = self.sub_holder[page_name].winfo_children()
        for frame in frames:
            if getattr(frame, "_ref", None) == ref:
                frame.tkraise()
                self.sub_current[page_name] = ref
        for tab_ref, tab in self.sub_tabs[page_name].items():
            on = (tab_ref == ref)
            tab.configure(bg=UI_ACCENT if on else UI_CARD,
                          fg=UI_ON_ACCENT if on else UI_MUTED,
                          activebackground=UI_ACCENT if on else UI_ACCENT_SOFT,
                          activeforeground=UI_ON_ACCENT if on else UI_ACCENT)
        self.after_idle(self._fit_result_boxes)

    @staticmethod
    def _tab_for(encounter_type):
        """Coaching is the fallback, not a listed case: the eleven coaching types are
        the ones that get added to over time, and a new one landing on the Coaching tab
        is right far more often than it is wrong."""
        return TAB_OF_TYPE.get(encounter_type, TAB_COACHING)

    def _render_results(self):
        """One card per returned row, fields in their own cells.

        The flat "Label: value" list this replaced made two different jobs look the
        same. Some of what comes back is PASTED into the EMR; the rest is ANSWERED by
        picking the same option from a dropdown, and copying that is meaningless. The
        card splits them, so a glance says which fields need a click and which need
        Ctrl+V — the thing the original spreadsheet's separate cells did for free."""
        blocks = {name: [] for name in TAB_ORDER}
        for row in self.rows:
            if row.result:
                blocks[self._tab_for(row.value("type"))].append(row)

        self._result_boxes = []
        self._page_counts = {name: len(blocks[name]) for name in TAB_ORDER}

        for name in TAB_ORDER:
            if name in self.tab_body:
                self._render_list_page(name, blocks[name])
            else:
                self._render_sub_page(name, blocks[name])
        self._paint_page_tabs()
        self.after_idle(self._fit_result_boxes)

    def _render_list_page(self, name, rows):
        body = self.tab_body[name]
        for child in body.winfo_children():
            child.destroy()
        body.grid_columnconfigure(0, weight=1)
        if not rows:
            tk.Label(body, text="Nothing back yet.", font=FONT_CELL, bg=UI_BG,
                     fg=UI_MUTED, anchor="w").grid(row=0, column=0, sticky="ew",
                                                   padx=10, pady=10)
            return
        for i, row in enumerate(rows):
            self._build_card(body, row).grid(row=i, column=0, sticky="ew",
                                             padx=2, pady=(8, 0))

    def _render_sub_page(self, name, rows):
        """A sub-tab per encounter: '#2', '#5', '#9'. Each one is its own full page of
        fields, so nothing has to be scrolled past to reach the next."""
        strip, holder = self.sub_strip[name], self.sub_holder[name]
        for child in strip.winfo_children():
            child.destroy()
        for child in holder.winfo_children():
            child.destroy()
        self.sub_tabs[name] = {}

        if not rows:
            tk.Label(holder, text="Nothing back yet.", font=FONT_CELL, bg=UI_BG,
                     fg=UI_MUTED, anchor="w").grid(row=0, column=0, sticky="nw",
                                                   padx=10, pady=10)
            return

        for row in rows:
            frame = tk.Frame(holder, bg=UI_BG)
            frame._ref = row.number
            frame.grid(row=0, column=0, sticky="nsew")
            area = tk.Frame(frame, bg=UI_BG)
            area.pack(fill="both", expand=True)
            body = self._scrollable_area(area)
            body.grid_columnconfigure(0, weight=1)
            self._build_card(body, row).grid(row=0, column=0, sticky="ew",
                                             padx=2, pady=(4, 8))

            flagged = bool((row.result or {}).get("flags"))
            tab = tk.Button(strip, text="#%d%s" % (row.number, " !" if flagged else ""),
                            font=FONT_CELL, relief="flat", bd=0, padx=14, pady=5,
                            cursor="hand2", takefocus=0,
                            command=lambda n=name, r=row.number: self._show_sub(n, r))
            tab.pack(side="left", padx=(0, 2), pady=(4, 0))
            self.sub_tabs[name][row.number] = tab

        keep = self.sub_current.get(name)
        self._show_sub(name, keep if keep in self.sub_tabs[name] else rows[0].number)

    def _fit_result_boxes(self):
        for box in getattr(self, "_result_boxes", []):
            self._fit_box(box)

    @staticmethod
    def _fit_box(box):
        """Give one result box exactly the height its wrapped text needs.

        Guarded against its own <Configure>: setting the height fires another one, and
        without the equality check that is an endless loop."""
        try:
            if not box.winfo_exists() or box.winfo_width() <= 1:
                return
            lines = min(max(int(box.count("1.0", "end", "displaylines")[0]), 1), 14)
            if int(box.cget("height")) != lines:
                box.configure(height=lines)
        except (tk.TclError, TypeError):
            pass

    def _build_card(self, parent, row):
        result = row.result or {}
        card = tk.Frame(parent, bg=UI_CARD, highlightthickness=1,
                        highlightbackground=UI_BORDER)
        card.grid_columnconfigure(1, weight=1)
        line = [0]

        def head():
            state = result.get("status", "")
            bar = tk.Frame(card, bg=UI_CARD)
            bar.grid(row=line[0], column=0, columnspan=2, sticky="ew",
                     padx=10, pady=(8, 2))
            tk.Label(bar, text="#%d" % row.number, font=(_DISPLAY_FAMILY, 12),
                     bg=UI_CARD, fg=UI_ACCENT).pack(side="left")
            tk.Label(bar, text=row.value("type") or "no type", font=FONT_CELL,
                     bg=UI_CARD, fg=UI_TEXT).pack(side="left", padx=(8, 0))
            if state and state != "READY":
                tk.Label(bar, text=state, font=("Consolas", 9), bg=UI_ACCENT_SOFT,
                         fg=UI_ACCENT, padx=6).pack(side="left", padx=(8, 0))
            line[0] += 1

        def band(title):
            tk.Label(card, text=title, font=(_DISPLAY_FAMILY, 9), bg=UI_CARD,
                     fg=UI_MUTED, anchor="w").grid(row=line[0], column=0, columnspan=2,
                                                   sticky="ew", padx=10, pady=(8, 2))
            line[0] += 1

        def answer(label, value, options):
            """Picked in the EMR, never copied — so it gets no Copy button."""
            tk.Label(card, text=label, font=FONT_CELL, bg=UI_CARD, fg=UI_MUTED,
                     anchor="w").grid(row=line[0], column=0, sticky="w",
                                      padx=(10, 8), pady=2)
            if value:
                cell = tk.Label(card, text=value, font=FONT_CELL, bg=UI_ROW_ALT,
                                fg=UI_TEXT, anchor="w", padx=8, pady=3)
            elif options:
                cell = tk.Label(card, text="pick one:  " + "   ·   ".join(options),
                                font=FONT_CELL, bg=UI_ROW_ALT, fg=UI_ACCENT,
                                anchor="w", padx=8, pady=3, wraplength=620,
                                justify="left")
            else:
                cell = tk.Label(card, text="— nothing returned —", font=FONT_CELL,
                                bg=UI_ROW_ALT, fg=UI_MUTED, anchor="w", padx=8, pady=3)
            cell.grid(row=line[0], column=1, sticky="ew", padx=(0, 10), pady=2)
            line[0] += 1

        def paste(label, value):
            """Free text bound for the EMR. Its own box and its own Copy button, so a
            two-field PA is two clicks and never a hand-selected drag."""
            bar = tk.Frame(card, bg=UI_CARD)
            bar.grid(row=line[0], column=0, columnspan=2, sticky="ew",
                     padx=10, pady=(4, 0))
            tk.Label(bar, text=label, font=FONT_CELL, bg=UI_CARD,
                     fg=UI_MUTED).pack(side="left")
            tk.Button(bar, text="Copy", font=("Segoe UI", 9), relief="flat", bd=0,
                      bg=UI_ROW_ALT, fg=UI_TEXT, activebackground=UI_ACCENT,
                      activeforeground=UI_ON_ACCENT, padx=10, cursor="hand2",
                      command=lambda v=value, l=label: self._copy_field(l, v)
                      ).pack(side="right")
            line[0] += 1
            box = tk.Text(card, wrap="word", font=FONT_CELL, bg=UI_ROW_ALT, fg=UI_TEXT,
                          relief="flat", bd=0, padx=8, pady=6, height=1,
                          selectbackground=UI_ACCENT, selectforeground=UI_ON_ACCENT)
            box.insert("1.0", value)
            box.configure(state="disabled")
            box.grid(row=line[0], column=0, columnspan=2, sticky="ew",
                     padx=10, pady=(2, 4))
            # Sized to fit its text — but not yet. A Text asked how tall it wants to be
            # before the card has a width wraps at one character and answers 99 lines.
            # _fit_result_boxes does it once the layout is real.
            # Refit whenever the box is given a width — on first layout, on a tab
            # being shown for the first time, and on every window resize. Chasing the
            # right moment with after_idle got the first two wrong.
            box.bind("<Configure>", lambda e, b=box: self._fit_box(b))
            self._result_boxes.append(box)
            line[0] += 1

        head()

        answers = [("Primary Complaint", "primary_complaint"),
                   ("Mechanism", "mechanism")]
        shown = [(lbl, key) for lbl, key in answers
                 if key in result or (key + "_options") in result]
        if shown:
            band("ANSWER IN THE EMR — pick these, nothing to copy")
            for label, key in shown:
                answer(label, str(result.get(key) or "").strip(),
                       result.get(key + "_options") or [])

        pastes = [("Description", "description"),
                  ("Incident Details", "incident_details"),
                  ("Protective Recommendations", "protective_recs")]
        shown = [(lbl, key) for lbl, key in pastes if str(result.get(key) or "").strip()]
        if shown:
            band("PASTE INTO THE EMR")
            for label, key in shown:
                paste(label, str(result[key]).strip())

        slots = [lbl for lbl, key in (("Palpation", "palpation"),
                                      ("Observation", "observation"))
                 if key in result]
        if slots:
            band("YOURS TO FILL — exam findings, blank on purpose")
            for label in slots:
                tk.Label(card, text=label, font=FONT_CELL, bg=UI_CARD, fg=UI_MUTED,
                         anchor="w").grid(row=line[0], column=0, sticky="w",
                                          padx=(10, 8), pady=2)
                tk.Label(card, text="[ ]", font=FONT_REF, bg=UI_ROW_ALT, fg=UI_MUTED,
                         anchor="w", padx=8, pady=3).grid(
                    row=line[0], column=1, sticky="ew", padx=(0, 10), pady=2)
                line[0] += 1

        flags = result.get("flags") or []
        if flags:
            band("FLAGS")
            for flag in flags:
                tk.Label(card, text="!  " + str(flag), font=FONT_CELL, bg=UI_CARD,
                         fg=UI_CONFIRM, anchor="w", wraplength=760, justify="left"
                         ).grid(row=line[0], column=0, columnspan=2, sticky="ew",
                                padx=10, pady=1)
                line[0] += 1

        tk.Frame(card, bg=UI_CARD, height=6).grid(row=line[0], column=0)
        return card

    def _copy_field(self, label, value):
        self.clipboard_clear()
        self.clipboard_append(value)
        self.run_status.configure(text="copied %s" % label)

    def _copy_results(self):
        """Every paste field on the visible page, labeled. The answer fields are left
        out — they are dropdown picks, and pasting them into a text box is wrong.

        On a sub-tabbed page this takes only the encounter being shown: those pages
        exist because Dane works one encounter at a time."""
        current = self.current_page
        if current not in TAB_ORDER:
            return
        only = self.sub_current.get(current) if current in self.sub_tabs else None
        chunks = []
        for row in self.rows:
            if not row.result or self._tab_for(row.value("type")) != current:
                continue
            if only is not None and row.number != only:
                continue
            parts = ["#%d  %s" % (row.number, row.value("type") or "no type")]
            for label, key in (("Description", "description"),
                               ("Incident Details", "incident_details"),
                               ("Protective Recommendations", "protective_recs")):
                text = str(row.result.get(key) or "").strip()
                if text:
                    parts.append("%s: %s" % (label, text) if key != "description"
                                 else text)
            if len(parts) > 1:
                chunks.append("\n".join(parts))
        if not chunks:
            return
        self.clipboard_clear()
        self.clipboard_append("\n\n".join(chunks))
        self.run_status.configure(text="copied %s (%d)" % (current, len(chunks)))

    def _add_row(self):
        r = Row(len(self.rows) + 1)
        gr = len(self.rows)
        stripe = UI_CARD if gr % 2 == 0 else UI_ROW_ALT

        for c, (key, _, chars, kind) in enumerate(COLUMNS):
            if kind == "ref":
                w = tk.Label(self.body, text=str(r.number), font=FONT_REF,
                             bg=UI_BG, fg=UI_MUTED, anchor="center")
                w.grid(row=gr, column=c, sticky="ew", padx=1, pady=1, ipady=3)
                r.widgets[key] = w
                continue

            if kind == "status":
                var = tk.StringVar(value=ST_PENDING)
                w = tk.Label(self.body, text="—", font=FONT_CELL, bg=UI_BG,
                             fg=UI_MUTED, anchor="center")
                w.grid(row=gr, column=c, sticky="ew", padx=1, pady=1, ipady=3)
                var.trace_add("write", lambda *a, i=gr: self._paint_status(i))
                r.vars[key] = var
                r.widgets[key] = w
                continue

            if kind == "check":
                var = tk.BooleanVar(value=False)
                holder = tk.Frame(self.body, bg=stripe)
                holder.grid(row=gr, column=c, sticky="ew", padx=1, pady=1)
                w = ttk.Checkbutton(holder, variable=var, command=self._refresh_count)
                w.pack(expand=True, pady=2)
            elif kind == "toggle":
                # Two boxes, not one cycling cell: both choices are on screen and each
                # is one click away. The var holds the real value ("" / Coaching /
                # Assessment) — the boxes only paint it.
                var = tk.StringVar(value="")
                w = tk.Frame(self.body, bg=stripe, takefocus=1,
                             highlightthickness=1, highlightbackground=UI_BORDER,
                             highlightcolor=UI_ACCENT)
                w.grid(row=gr, column=c, sticky="ew", padx=1, pady=1)
                for k in KINDS:
                    b = tk.Button(w, text=k, font=FONT_CELL, relief="flat", bd=0,
                                  takefocus=0, padx=2, pady=1,
                                  command=lambda i=gr, kk=k: self._pick_kind(i, kk))
                    b.pack(side="left", expand=True, fill="both", padx=1, pady=1)
                    r.kind_buttons[k] = b
                var.trace_add("write", lambda *a, i=gr: self._paint_kind(i))
            elif kind == "choice":
                var = tk.StringVar(value="")
                w = ttk.Combobox(self.body, textvariable=var, values=CHOICES[key],
                                 state="readonly", width=chars, font=FONT_CELL)
                w.grid(row=gr, column=c, sticky="ew", padx=1, pady=1)
                if key == "type":
                    w.bind("<<ComboboxSelected>>",
                           lambda e, i=gr: self._on_type_chosen(i))
                else:
                    w.bind("<<ComboboxSelected>>",
                           lambda e, i=gr: self._on_cell_changed(i))
                if key == "shift":
                    for digit in SHIFT_KEYS:
                        w.bind(digit, lambda e, i=gr: self._set_shift(i, e.keysym))
            else:
                var = tk.StringVar(value="")
                w = tk.Entry(self.body, textvariable=var, width=chars, font=FONT_CELL,
                             bg=stripe, fg=UI_TEXT, insertbackground=UI_ACCENT,
                             insertwidth=3, selectbackground=UI_ACCENT,
                             selectforeground=UI_ON_ACCENT,
                             relief="flat", highlightthickness=2,
                             highlightbackground=stripe, highlightcolor=UI_ACCENT)
                w.grid(row=gr, column=c, sticky="ew", padx=1, pady=1, ipady=3)
                # The active cell lights up. A 3px amber caret is findable on its own,
                # but only once you know which of forty cells to look in.
                w.bind("<FocusIn>", lambda e, b=w: b.configure(bg=UI_FOCUS))
                w.bind("<FocusOut>", lambda e, b=w, s=stripe: b.configure(bg=s))
                var.trace_add("write", lambda *a, i=gr: self._on_cell_changed(i))

            r.vars[key] = var
            r.widgets[key] = w
            self._bind_navigation(w, gr, key)

        self.rows.append(r)
        self._paint_kind(gr)        # the trace only fires on a write, so seed it here
        self._refresh_count()

    # -- Kind: the filter in front of Encounter Type -------------------------
    def _pick_kind(self, row_index, kind):
        """Click a box to choose it. Clicking the one already lit clears the cell —
        with two fixed boxes there is otherwise no way back out of a misclick."""
        current = self.rows[row_index].vars["kind"].get()
        self._set_kind(row_index, "" if current == kind else kind)

    def _cycle_kind(self, row_index):
        """Space, for a keyboard pass down the sheet — flips to the other box."""
        current = self.rows[row_index].vars["kind"].get()
        self._set_kind(row_index,
                       KIND_COACHING if current == KIND_ASSESSMENT else KIND_ASSESSMENT)

    def _set_kind(self, row_index, kind):
        row = self.rows[row_index]
        if row.vars["kind"].get() == kind:
            return
        row.vars["kind"].set(kind)
        self._apply_kind_filter(row_index)
        self._refresh_count()

    def _apply_kind_filter(self, row_index):
        """Narrow the Encounter Type list to the chosen family. A type already picked
        from the other family is cleared — leaving it would show a value the Kind cell
        says is impossible, and one of the two would be a lie."""
        row = self.rows[row_index]
        kind = row.vars["kind"].get()
        options = TYPES_BY_KIND.get(kind, ENCOUNTER_TYPE_OPTIONS)
        row.widgets["type"].configure(values=options)
        if row.vars["type"].get() and row.vars["type"].get() not in options:
            row.vars["type"].set("")

    def _on_type_chosen(self, row_index):
        """Picking a type back-fills its Kind. Before a Kind is set the dropdown offers
        all 18, so the filter stays a shortcut rather than a gate you have to pass."""
        row = self.rows[row_index]
        kind = KIND_OF_TYPE.get(row.vars["type"].get())
        if kind:
            self._set_kind(row_index, kind)
        self._refresh_count()

    def _paint_kind(self, row_index):
        """Light the chosen box. Unchosen boxes sit at the row's own stripe colour so
        the cell reads as two empty slots, not as two buttons demanding attention."""
        row = self.rows[row_index]
        chosen = row.vars["kind"].get()
        stripe = UI_CARD if row_index % 2 == 0 else UI_ROW_ALT
        for k, button in row.kind_buttons.items():
            on = (k == chosen)
            button.configure(
                bg=UI_ACCENT if on else stripe,
                fg=UI_ON_ACCENT if on else UI_MUTED,
                activebackground=UI_ACCENT if on else UI_ACCENT_SOFT,
                activeforeground=UI_ON_ACCENT if on else UI_ACCENT)

    # -- status, and what an edit means after a row has gone ------------------
    def _paint_status(self, row_index):
        row = self.rows[row_index]
        state = row.vars["status"].get()
        face, colour = {ST_SENT: ("sent", UI_ACCENT),
                        ST_RETURNED: ("returned", UI_CONFIRM)}.get(state, ("—", UI_MUTED))
        row.widgets["status"].configure(text=face, fg=colour)

    def _on_cell_changed(self, row_index):
        """Editing a row that has already gone puts it back in the queue. The row on
        screen and the row that was handed off have diverged, and the copy Dane can see
        is the one he will act on — so the sent one is the stale one, not this."""
        if self._loading:
            return
        row = self.rows[row_index]
        if row.vars["status"].get() in (ST_SENT, ST_RETURNED):
            # Also the way to ask for a rewrite: change the input, the row requeues.
            # The old block stays on screen until a new one replaces it.
            row.vars["status"].set(ST_PENDING)
        self._refresh_count()
        self._queue_save()

    def _set_shift(self, row_index, keysym):
        self.rows[row_index].vars["shift"].set(SHIFT_KEYS[keysym])
        self._refresh_count()
        return "break"

    # -- moving around like a spreadsheet ------------------------------------
    def _bind_navigation(self, widget, row_index, key):
        widget.bind("<Return>", lambda e: self._move(row_index, key, 1))
        widget.bind("<Control-d>", lambda e: self._fill_down(row_index, key))
        widget.bind("<Tab>", lambda e: self._tab(row_index, key))
        # A readonly combobox needs Up/Down for its own list; on a text cell they are
        # free, so only there do they mean "next line".
        if not isinstance(widget, ttk.Combobox):
            widget.bind("<Down>", lambda e: self._move(row_index, key, 1))
            widget.bind("<Up>", lambda e: self._move(row_index, key, -1))
        if key == "kind":
            # A / C set it outright; Space cycles. Enter still means "next line", so a
            # keyboard pass down the sheet never stops here.
            widget.bind("<space>", lambda e: self._cycle_kind(row_index) or "break")
            widget.bind("a", lambda e: self._set_kind(row_index, KIND_ASSESSMENT))
            widget.bind("A", lambda e: self._set_kind(row_index, KIND_ASSESSMENT))
            widget.bind("c", lambda e: self._set_kind(row_index, KIND_COACHING))
            widget.bind("C", lambda e: self._set_kind(row_index, KIND_COACHING))

    def _editable_keys(self):
        return [k for k, _, _, kind in COLUMNS if kind != "ref"]

    def _move(self, row_index, key, delta):
        target = row_index + delta
        if target < 0:
            return "break"
        while target >= len(self.rows):
            self._add_row()
        self._focus_cell(target, key)
        return "break"

    def _tab(self, row_index, key):
        keys = self._editable_keys()
        i = keys.index(key)
        if i + 1 < len(keys):
            self._focus_cell(row_index, keys[i + 1])
        else:
            if row_index + 1 >= len(self.rows):
                self._add_row()
            self._focus_cell(row_index + 1, keys[0])
        return "break"

    def _fill_down(self, row_index, key):
        """Ctrl+D — copy the cell above. A day of coaching is the same Reason and the
        same Shift over and over; retyping it is the sheet's most repetitive act."""
        if row_index == 0 or key not in self.rows[row_index].vars:
            return "break"
        above = self.rows[row_index - 1].vars.get(key)
        if above is not None:
            self.rows[row_index].vars[key].set(above.get())
        return "break"

    def _focus_cell(self, row_index, key):
        w = self.rows[row_index].widgets.get(key)
        if w is None:
            return
        w.focus_set()
        if isinstance(w, tk.Entry):
            w.icursor("end")
        self._scroll_into_view(w)

    def _scroll_into_view(self, widget):
        self.update_idletasks()
        top = widget.winfo_y()
        bottom = top + widget.winfo_height()
        height = max(self.body.winfo_height(), 1)
        view_top = self.canvas.canvasy(0)
        view_bottom = view_top + self.canvas.winfo_height()
        if top < view_top:
            self.canvas.yview_moveto(top / height)
        elif bottom > view_bottom:
            self.canvas.yview_moveto((bottom - self.canvas.winfo_height()) / height)

    # -- footer --------------------------------------------------------------
    def _build_footer(self):
        """The bottom strip: sheet tabs on the left the way Excel puts them, and the
        actions for whichever page is showing on the right."""
        bar = tk.Frame(self, bg=UI_BG)
        bar.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 10))
        bar.grid_columnconfigure(0, weight=1)

        tabs = tk.Frame(bar, bg=UI_BG)
        tabs.grid(row=0, column=0, sticky="w")
        self.page_tabs = {}
        for name in [PAGE_SHEET] + TAB_ORDER:
            tab = tk.Button(tabs, text=name, font=FONT_CELL, relief="flat", bd=0,
                            padx=16, pady=6, cursor="hand2", takefocus=0,
                            command=lambda n=name: self._show_page(n))
            tab.pack(side="left", padx=(0, 2))
            self.page_tabs[name] = tab

        actions = tk.Frame(bar, bg=UI_BG)
        actions.grid(row=0, column=1, sticky="e")
        self.add_rows_button = ttk.Button(actions, text="+%d rows" % ROWS_PER_ADD,
                                          command=self._add_rows)
        self.add_rows_button.grid(row=0, column=0, padx=(0, 8))
        self.copy_button = ttk.Button(actions, text="Copy this page",
                                      command=self._copy_results)
        self.copy_button.grid(row=0, column=1, padx=(0, 8))
        self.send_button = ttk.Button(actions, text="Send checked rows",
                                      style="Accent.TButton", command=self._send)
        self.send_button.grid(row=0, column=2)
        self.run_status = ttk.Label(actions, text="", style="Muted.TLabel")
        self.run_status.grid(row=0, column=3, padx=(10, 0))

    def _add_rows(self):
        for _ in range(ROWS_PER_ADD):
            self._add_row()

    def _refresh_count(self):
        filled = sum(0 if r.is_blank() else 1 for r in self.rows)
        ready = len(self._eligible())
        sent = sum(1 for r in self.rows if r.vars["status"].get() == ST_SENT)
        back = sum(1 for r in self.rows if r.vars["status"].get() == ST_RETURNED)
        parts = ["%d filled" % filled, "%d ready" % ready]
        if sent:
            parts.append("%d sent" % sent)
        if back:
            parts.append("%d returned" % back)
        self.count_label.config(text="   ".join(parts))
        if hasattr(self, "send_button"):
            self.send_button.configure(state="normal" if ready else "disabled")

    # -- sending --------------------------------------------------------------
    def _eligible(self):
        """Checked, not blank, and not already gone."""
        return [r for r in self.rows
                if r.vars["done"].get()
                and r.vars["status"].get() == ST_PENDING
                and not r.is_blank()]

    def _risks(self, rows):
        """Structural identifiers in the free-text columns, as {ref: [what]}.

        The findings are never printed or logged — only shown in the window, by row
        number and category. Echoing the matched text to stdout would put the very
        thing being flagged somewhere it does not belong."""
        found = {}
        for row in rows:
            hits = []
            for field in ("reason", "description"):
                text = row.value(field)
                for pattern, label in _RISK_PATTERNS:
                    if pattern.search(text) and label not in hits:
                        hits.append(label)
            if hits:
                found[row.number] = hits
        return found

    def _send(self):
        rows = self._eligible()
        if not rows:
            return

        missing = [r.number for r in rows if not r.value("type")]
        if missing:
            messagebox.showwarning(
                "Encounter Type missing",
                "These rows have no Encounter Type, and it decides everything "
                "downstream:\n\n    %s\n\nSet it, or uncheck them."
                % ", ".join("#%d" % n for n in missing))
            return

        risky = self._risks(rows)
        if risky:
            lines = "\n".join("    #%d — %s" % (ref, ", ".join(what))
                              for ref, what in sorted(risky.items()))
            if not messagebox.askyesno(
                    "Check these rows first",
                    "These rows contain something that reads as an identifier:\n\n"
                    "%s\n\nThis only finds numbers, dates and emails. It cannot find a "
                    "name, and it cannot find shorthand that identifies someone without "
                    "one — that scan is yours.\n\nSend anyway?" % lines,
                    default="no"):
                return

        payload = {"written_at": datetime.now().isoformat(timespec="seconds"),
                   "sheet_date": self.sheet_date.get().strip(),
                   "rows": [r.payload() for r in rows]}
        try:
            with open(OUTBOX_JSON, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            messagebox.showerror("Could not write the outbox", str(exc))
            return

        for row in rows:
            row.vars["status"].set(ST_SENT)
        self._refresh_count()
        self._save_sheet()
        self._start_run(payload["rows"], payload["sheet_date"])

    # -- the headless run -----------------------------------------------------
    def _start_run(self, rows, sheet_date):
        """One call for the whole batch, on a worker thread. Tk is single-threaded and
        not thread-safe, so the worker only ever puts messages on a queue — every
        widget touch happens back on the main thread in _poll_run."""
        if self._run_thread and self._run_thread.is_alive():
            return
        self.send_button.configure(state="disabled")
        self.run_status.configure(text="Working...")

        def work():
            try:
                results = intake_runner.run(
                    rows, sheet_date,
                    on_progress=lambda msg: self._results_queue.put(("note", msg)))
                self._results_queue.put(("ok", results))
            except intake_runner.RunnerError as exc:
                self._results_queue.put(("err", str(exc)))
            except Exception as exc:                      # never lose the window
                self._results_queue.put(("err", "%s: %s" % (type(exc).__name__, exc)))

        self._run_thread = threading.Thread(target=work, daemon=True)
        self._run_thread.start()
        self.after(150, self._poll_run)

    def _poll_run(self):
        try:
            while True:
                kind, payload = self._results_queue.get_nowait()
                if kind == "note":
                    self.run_status.configure(text=payload)
                elif kind == "ok":
                    self._absorb(payload)
                elif kind == "err":
                    self._run_failed(payload)
        except queue.Empty:
            pass
        if self._run_thread and self._run_thread.is_alive():
            self.after(150, self._poll_run)
        else:
            self._refresh_count()

    def _absorb(self, results):
        results.pop("_meta", None)
        for row in self.rows:
            result = results.get(row.number)
            if result is None:
                continue
            row.result = result
            row.vars["status"].set(ST_RETURNED)
        self._render_results()
        self._refresh_count()
        self._save_sheet()
        # Count only. A running dollar figure is a meter reading against a plan, not a
        # bill, and putting it on screen makes every batch feel like a purchase.
        self.run_status.configure(
            text="%d returned" % len([k for k in results if isinstance(k, int)]))

    def _run_failed(self, message):
        """The rows go back to pending. A failed run must not leave them looking sent,
        or the next Send would skip exactly the rows that never got written."""
        for row in self.rows:
            if row.vars["status"].get() == ST_SENT:
                row.vars["status"].set(ST_PENDING)
        self.run_status.configure(text="failed")
        self._refresh_count()
        self._save_sheet()
        messagebox.showerror("The run did not finish", message)

    # -- persistence ----------------------------------------------------------
    def _queue_save(self):
        """Debounced: a keystroke per character would write the file per character."""
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(800, self._save_sheet)

    def _sheet_state(self):
        """Everything worth keeping, as plain data. Used by the autosave and by the
        theme rebuild, so the two can never drift apart."""
        return {"sheet_date": self.sheet_date.get().strip(),
                "theme": self.theme,
                "rows": [dict(r.payload(), done=bool(r.vars["done"].get()),
                              status=r.vars["status"].get(), result=r.result)
                         for r in self.rows if not r.is_blank()]}

    def _save_sheet(self):
        self._save_job = None
        try:
            with open(SHEET_JSON, "w", encoding="utf-8") as fh:
                json.dump(self._sheet_state(), fh, indent=2, ensure_ascii=False)
        except OSError:
            pass        # a failed autosave must never interrupt typing

    def _restore(self, data):
        saved = data.get("rows") or []
        if data.get("sheet_date"):
            self.sheet_date.set(data["sheet_date"])
        self._loading = True
        try:
            for i, saved_row in enumerate(saved):
                while i >= len(self.rows):
                    self._add_row()
                row = self.rows[i]
                for key in ("kind", "type", "reason", "shift", "description"):
                    row.vars[key].set(saved_row.get(key, ""))
                row.vars["done"].set(bool(saved_row.get("done")))
                row.vars["status"].set(saved_row.get("status", ST_PENDING))
                row.result = saved_row.get("result")
                self._apply_kind_filter(i)
        finally:
            self._loading = False
        self._refresh_count()

    def _load_sheet(self):
        if not os.path.exists(SHEET_JSON):
            return
        try:
            with open(SHEET_JSON, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        self._restore(data)
        self._render_results()

    def _on_close(self):
        # Cancel anything still scheduled: an after() that fires into a destroyed
        # interpreter raises out of the event loop rather than being ignored.
        for job in (self._save_job, getattr(self, "_topmost_job", None)):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._save_sheet()
        self.destroy()


def main():
    IntakeGrid().mainloop()


if __name__ == "__main__":
    main()
