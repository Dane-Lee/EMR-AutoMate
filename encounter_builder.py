"""
encounter_builder.py — build encounters.csv by checking names off the roster
===========================================================================
The Copilot replacement. No dictation, no transcription, and nothing guessed.

One optional step reaches out: a description left as a NOTE, or a coaching type left as
SUGGEST_TYPE, is written by a headless `claude -p` when the batch is written. Notes
only — see _resolve_pending, which is where the guards live.

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
import queue
import re
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta

import tkinter as tk
from tkinter import ttk, messagebox

import emr_field_map as fm
import ati_coaching_encounter as ace
import case_report          # the Case list report tab (read-only, no browser on import)

_HERE = os.path.dirname(os.path.abspath(__file__))
ROSTER_XLSX = os.path.join(_HERE, "roster.xlsx")
OUT_CSV = os.path.join(_HERE, "encounters.csv")
BAK_CSV = os.path.join(_HERE, "encounters.bak.csv")
LIBRARY_XLSX = os.path.join(_HERE, "EMR Easy Enter Worksheets.xlsx")
PREFS_JSON = os.path.join(_HERE, "builder_prefs.json")

# No default. An unset coaching type blocks the group — see the module docstring.
PICK_ONE = "— pick one —"

# Coaching type left to Claude. A SENTINEL, not a value: it is never in
# COACHING_TYPE_UUIDS, so if one ever survived to the CSV the validator would reject the
# batch before a browser opened. _resolve_pending replaces every one of these with a real
# EMR value at write time, or nothing is written at all.
SUGGEST_TYPE = "— suggest it from my note —"
BLANK = ""

# Checked names get a filled box + a tinted row so the pick is obvious at a glance
# across a 261-name list — the faint "X" prefix was too easy to lose track of.
CHECK_ON = "☑"

# Narrowest the roster column is ever laid out at (its grid minsize). Anything drawn
# into that panel has to fit this, not the window width — the roster tally was written
# against the window and clipped for weeks because nothing tied the two together.
ROSTER_PANEL_PX = 430
CHECK_OFF = "☐"
CHECK_BG = "#f2d296"       # amber wash — the checked row. Deepened 2026-09-04:
                           # against the lighter card it sat at 1.11:1 and the
                           # "who did I check" signal was all but gone, while
                           # every text-contrast check still passed.
CHECK_FG = "#8a4b00"

# ── "Shift Board", warm-gray ground (Dane, 2026-09-03) ───────────────────────
# Was a near-black blue slate (#14181D). Dane: "Brighten the background overall to a
# warm gray instead of the black." So the ground flipped light, and every other value
# had to move with it — a palette is a set of relationships, not a list of colours, and
# the dark rail/accent/confirm values were all chosen to clear 4.5:1 against a dark
# card. They would all fail on a light one.
#
# What did NOT change is the grammar: warm gray is still the plant-floor register
# (equipment panels, signage board), amber still carries EVERY active state — selection,
# focus, primary action — so there is exactly one thing to look for, and the hi-vis
# green is still reserved for confirmation counts alone.
#
# ⚠️ The accent had to become TWO tokens, and this is the part that is easy to get wrong.
# On the dark ground one amber did every job. On a light ground no single amber can:
#
#   * bright enough to read as safety amber when FILLED (a button, a selected chip)
#     lands at ~2.4:1 as TEXT on the warm gray — unreadable for the section headers and
#     panel legends, which are the loudest text in the window
#   * dark enough to be legible TEXT is a brown, and a brown fill is not this UI
#
# So UI_ACCENT fills (with the dark ground colour as its text, exactly the grammar the
# dark theme used) and UI_ACCENT_TEXT draws accent-coloured text, focus rings and hover
# borders. Both were measured, not eyeballed — see the contrast block in the smoke test.
UI_BG = "#d9d3ca"            # warm gray ground — window / panel background
UI_CARD = "#f2efe9"          # inputs, cards, the name list — lifts off the ground
UI_TEXT = "#2b2723"          # primary text — warm near-black
UI_MUTED = "#5d564e"         # secondary / hint text
UI_BORDER = "#bdb5a9"        # thin borders and separators
UI_ACCENT = "#d4820e"        # safety amber — FILLS only (4.94:1 with UI_ON_ACCENT on it)
UI_ACCENT_TEXT = "#7d4104"   # accent as TEXT / focus ring (5.37:1 on the ground)
UI_ACCENT_SOFT = "#f0dfc2"   # hover / subtle fill (amber floated onto the warm gray)
UI_CONFIRM = "#405a0d"       # hi-vis — confirmation counts ONLY
UI_ON_ACCENT = "#2f2a24"     # text/glyphs sitting ON amber: the dark ground, not white
UI_ACCENT_HOVER = "#e89a2c"  # accent button, hover
UI_ACCENT_PRESS = "#b06a08"  # accent button, pressed

# The shift rail: a coloured bar down the left edge of every roster row, so shift —
# the thing Dane filters by constantly — reads without a column and without reading.
#
# Deliberately NOT amber or hi-vis. The mockup used amber for 1st shift, but amber
# already means "active/selected" everywhere else in this UI, and a colour cannot carry
# two meanings on one screen without the louder one winning. Blue/orchid/teal are
# distinct from each other, from the accent, and from the confirm green, and all four
# clear 4.5:1 against the #F8F6F3 list ground — darkened from the dark theme's pastels,
# which were picked against #1E242B and wash out completely on a light card.
#
# Darkening them for the light card also pushed 1st and 3rd TOGETHER: as pastels the
# blue and the teal were told apart by lightness as much as hue, and once both were
# taken down to ~5:1 they landed 33° apart and read as the same colour in a 1-glyph rail.
# So 1st went deeper blue and 3rd went green-teal — 58° now, measured, not eyeballed.
RAIL_GLYPH = "▌"
SHIFT_RAIL = {"1st": "#17539c", "2nd": "#7a3d95", "3rd": "#157a4f"}
SHIFT_RAIL_NONE = "#a8a099"  # shift unknown/blank — present but recessive

# Bahnschrift is Windows' DIN-derived industrial face — the lettering of machine panels
# and safety signage, which is exactly the register this tool works in. It ships with
# Windows 10+, but Tk silently substitutes when a family is missing, and a silent
# substitution is the kind of thing this project has been burned by, so resolve it
# against the real font list at startup instead of assuming.
FONT_BODY = ("Segoe UI", 11)
FONT_DATA = ("Consolas", 10)     # counts and tallies — tabular figures
_DISPLAY_FAMILY = "Bahnschrift"  # confirmed present, or swapped in _set_fonts()

def _legend(text):
    """Set a panel legend the way plant signage is set: caps, letter-spaced.

    Tk has no letter-spacing property, so the tracking has to be literal characters —
    U+200A HAIR SPACE, the narrowest that renders. That makes it a LAYOUT risk, not just
    a typographic one: the legend is what sets a LabelFrame's minimum width, so tracking
    a long string can widen the panel past the 860px minimum window. Measured before
    shipping (see _check_legend_widths) — keep legends short enough to stay under it.
    """
    return " ".join(text.upper())


class CollapsibleSection:
    """One foldable block of the encounter form (Dane, 2026-09-03).

    The form is a stack of option grids and only one of them is ever in play at a time,
    so each folds to a single line once it is settled. **Folded is not hidden** — the
    header carries the current value, so a fully folded form still reads as a summary of
    exactly what is about to be written. That is the whole reason this is safe to do to a
    form whose controlled values must never be guessed: nothing becomes invisible.

    Two fold triggers, and the difference is not cosmetic:

    * **Single-select** (encounter type, coaching type, category, prompted by) folds the
      moment a radio is clicked. The pick IS the "done" signal.
    * **Multi-select** (details) cannot use that trigger. Folding on the first checkbox
      would put the second one out of reach — the field would be unusable for any
      encounter needing two details, which is most of them. It folds when another
      section opens, or when its own header is clicked.

    Opening any section folds the others (`on_expand`), which is what keeps the form to
    one open block without anyone having to tidy up after themselves.
    """

    CHEVRON_OPEN = "▾"
    CHEVRON_SHUT = "▸"

    def __init__(self, parent, row, label, summary, collapsed=True, on_expand=None):
        self.summary = summary          # () -> str: the value shown while folded
        self.on_expand = on_expand      # told when this section opens (the accordion)
        self.collapsed = collapsed

        self.header = ttk.Frame(parent)
        self.header.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(7, 1))
        self.chevron = ttk.Label(self.header, text="", style="Section.TLabel", width=2)
        self.chevron.pack(side="left")
        self.title = ttk.Label(self.header, text=label, style="Section.TLabel")
        self.title.pack(side="left")
        self.value = ttk.Label(self.header, text="", style="SectionValue.TLabel")
        self.value.pack(side="left", padx=(10, 0))

        # Indented so the fold structure reads down the left edge at a glance.
        self.body = ttk.Frame(parent)
        self.body.grid(row=row + 1, column=0, columnspan=2, sticky="ew", padx=(20, 0))

        for w in (self.header, self.chevron, self.title, self.value):
            w.bind("<Button-1>", lambda e: self.toggle())
            try:
                w.configure(cursor="hand2")
            except tk.TclError:
                pass
        self._apply(collapsed)

    def _apply(self, collapsed):
        self.collapsed = collapsed
        (self.body.grid_remove if collapsed else self.body.grid)()
        self.chevron.config(text=self.CHEVRON_SHUT if collapsed else self.CHEVRON_OPEN)
        self.refresh()

    def refresh(self):
        """Re-read the current value into the header.

        Only while folded — open, the control itself already shows the pick, and a
        second copy of it in the header is one more thing to read past.
        """
        self.value.config(text=self.summary() if self.collapsed else "")

    def toggle(self):
        self.collapse() if not self.collapsed else self.expand()

    def collapse(self):
        self._apply(True)

    def expand(self):
        if self.on_expand:
            self.on_expand(self)        # fold the others first, then open
        self._apply(False)


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
# ROLE FILTER (item 1) — quick "show only the leads / supervisors" toggles
# ─────────────────────────────────────────────
# Dane thinks in "line lead" / "supervisor", but the roster spells those as job
# TITLES: 'Team Lead' (17) and 'Training Lead' (1) are the leads; 'Prod Sup' (8) and
# 'Maint Sup' (1) are the supervisors (measured 2026-07-22 from roster.xlsx, counts
# only). So each role matches by a title-word PREFIX, not by Dane's label — that's the
# only way the filter finds the people he means. Prefix (not whole word) so a fuller
# spelling like 'Supervisor' or 'Team Leader' still matches.
#   (label shown, (title-word prefixes it matches))
ROLE_FILTERS = [
    ("Line Leads",  ("lead",)),   # Team Lead, Training Lead
    ("Supervisors", ("sup",)),    # Prod Sup, Maint Sup
]


def title_matches_role(title, prefixes):
    """True if any WORD of `title` starts with one of `prefixes` (case-insensitive).
    Word-prefix, so 'Prod Sup' matches ('sup',) but 'Supplier'-style words would too —
    none exist in the roster's title vocabulary, and this only drives a view filter."""
    words = re.split(r"[^a-z0-9]+", (title or "").lower())
    return any(w.startswith(p) for w in words for p in prefixes)


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

    A "Choose ..." cell is NEVER a description, however long it runs. Testing the
    length first (as this did until 2026-07-31) misfiled three 60-to-153-char hints in
    NHO Encounters as pickable descriptions — instruction text offered as documentation,
    the same mistake in a new place.

    HINTS SIT ON THE ROW BELOW THEIR DESCRIPTION — measured, not assumed. A row-shape
    map of the 2026-07-31 workbook (structure only, no cell text) shows two conventions
    living side by side:

        Target-Check Ins / Target-Add-Ons / General-Relate /   NHO Encounters:
        Target-H&W / -JobMobility / -JobCoaching /
        General-GenMed / -GroupClass / New Hire-Check-Ins:

            row 3:  label  description                          row 2:  hint label description
            row 4:  hint   label                                row 5:  hint label description

    Associating only within a row — the original rule — caught the NHO form and dropped
    every other tab's hint on the floor: 1 of 64 descriptions had a usable hint. So a
    hint row carrying no description of its own attaches to the description row above it,
    and a same-row hint still wins. When one hint row follows a row holding several
    descriptions (Target-Add-Ons rows run label + 4), it applies to all of them —
    Dane's call, 2026-07-31: they're variations of one scenario sharing detail boxes.

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
        # Entries emitted by the most recent row that held descriptions — the ones a
        # bare hint row is allowed to reach back to. Per tab: a hint never crosses tabs.
        open_entries = []
        for row in wb[tab].iter_rows(values_only=True):
            cells = [str(c).strip() for c in (row or [])
                     if c is not None and str(c).strip()]
            if not cells:
                continue
            hint, labels, texts = "", [], []
            for cell in cells:
                if cell.lower().startswith("choose"):
                    # Length is irrelevant here: a reminder of which boxes to tick is
                    # never documentation. Extras beyond the first stay labels.
                    if not hint:
                        hint = cell
                    else:
                        labels.append(cell)
                elif len(cell) >= DESCRIPTION_MIN_CHARS:
                    texts.append(cell)
                else:
                    labels.append(cell)

            if texts:
                open_entries = [{"tab": tab,
                                 "label": " · ".join(labels) or tab,
                                 "hint": hint,
                                 "text": text} for text in texts]
                entries.extend(open_entries)
            elif hint:
                # A hint on its own row: it belongs to the descriptions above it. These
                # are the same dicts already in `entries`, so filling them in here is
                # what reaches the library. Consumed once, so a second hint row can't
                # overwrite the first.
                for entry in open_entries:
                    if not entry["hint"]:
                        entry["hint"] = hint
                open_entries = []
    wb.close()
    return entries


# Coaching-type words that say nothing about WHICH library tab to show — every type
# is a kind of "coaching"/"class"/"education", so these can't distinguish tabs.
_LIBRARY_STOPWORDS = {
    "coaching", "encounter", "class", "adjustment", "education", "visit",
    "development", "consultation", "general", "center", "and", "the", "of",
}


def library_category_for(coaching_type, tabs):
    """Best-matching library tab for a coaching type, or None (item 2).

    The workbook's tab names are Dane's own category words (Safety, Ergonomics, …), so
    map by distinctive token overlap: e.g. "Safety Coaching" -> "Safety",
    "Ergonomic Adjustment" -> "Ergonomics", "Health/Wellness Coaching" -> a
    "Health/Wellness" tab. A 4-char prefix bridges ergonomic/ergonomics and
    wellness/well. No confident match returns None so the Library just opens on "All
    categories" — a wrong default is only ever a starting filter Dane can change, never
    anything written to a record.
    """
    toks = [t for t in re.split(r"[^a-z]+", (coaching_type or "").lower())
            if len(t) > 2 and t not in _LIBRARY_STOPWORDS]
    best, best_score = None, 0
    for tab in tabs:
        tl = tab.lower()
        score = sum(1 for t in toks if t[:4] in tl)
        if score > best_score:
            best, best_score = tab, score
    return best


def coaching_type_for_tab(tab, coaching_types):
    """Reverse of library_category_for: the coaching type a library TAB best implies,
    or None. Used to auto-set the coaching type when a description is picked from the
    Library and none is chosen yet (the individual quick-entry flow). Same token-overlap
    scoring, so it stays consistent with the forward map. None -> leave the type unset."""
    tl = (tab or "").lower()
    best, best_score = None, 0
    for ct in coaching_types:
        toks = [t for t in re.split(r"[^a-z]+", ct.lower())
                if len(t) > 2 and t not in _LIBRARY_STOPWORDS]
        score = sum(1 for t in toks if t[:4] in tl)
        if score > best_score:
            best, best_score = ct, score
    return best


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


def _read_prefs(path=None):
    try:
        with open(path or PREFS_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_prefs(data, path=None):
    try:
        with open(path or PREFS_JSON, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass          # a pref file that won't save must never block entering encounters


def load_prefs(path=None):
    """Which work areas (divisions) / shifts are hidden. Set once, sticks between runs."""
    data = _read_prefs(path)
    return set(data.get("hidden_areas", [])), set(data.get("hidden_shifts", []))


def save_prefs(hidden_areas, hidden_shifts, path=None):
    # MERGE, don't overwrite: this file also holds the report tab's specialist name,
    # and a plain rewrite here would silently drop it the next time a filter changed.
    data = _read_prefs(path)
    data["hidden_areas"] = sorted(hidden_areas)
    data["hidden_shifts"] = sorted(hidden_shifts)
    _write_prefs(data, path)


def load_specialist(path=None):
    """The name to tick in the EMR's Specialists filter. '' until Dane sets it.

    Kept in builder_prefs.json — which is gitignored — rather than in the source: it
    is Dane's own name, it is his to set, and it has no business in a tracked file.
    """
    return str(_read_prefs(path).get("specialist", "") or "").strip()


def save_specialist(name, path=None):
    data = _read_prefs(path)
    data["specialist"] = str(name or "").strip()
    _write_prefs(data, path)


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
        # Which roster row the keyboard is on. Index into self.shown, so _refresh_list
        # re-clamps it whenever filtering changes what's visible.
        self._focus_idx = 0

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

        # Two ways to build the same batch. "groups": check many names, one shared
        # encounter (the original flow). "individuals": load ONE person, set their
        # encounter, "Add & Next" — for a day of distinct one-at-a-time encounters. An
        # individual is stored as a group of one, so everything downstream is unchanged.
        self.mode = tk.StringVar(value="groups")
        # Shift Pool mode: roll-call first, sort second. You check off everyone you saw
        # on a shift, then work through that much smaller list assigning coaching types,
        # instead of hunting 261 names again for every type. A person LEAVES the pool
        # when assigned — a second encounter the same day is rare enough that Dane would
        # rather re-select than have every assigned name linger.
        self.pool = []            # [name] still waiting to be assigned
        self.pool_shift = ""      # which shift the roll call was taken for

        # Two jobs on one window (2026-09-08). "Build a batch" is the original layout,
        # moved into a tab frame and otherwise untouched. "Case list report" reads
        # finished work back OUT of the EMR — the opposite direction, same worksite,
        # same browser profile, so it belongs here rather than in a second tool.
        self.book = ttk.Notebook(self)
        self.book.grid(row=0, column=0, sticky="nsew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.build_tab = ttk.Frame(self.book)
        self.book.add(self.build_tab, text="Build a batch")
        self.report_tab = ttk.Frame(self.book)
        self.book.add(self.report_tab, text="Case list report")

        # Row 0 (the panels) takes every spare pixel; row 1 (the batch bar) keeps its
        # own height no matter how small the window gets, so the buttons that finish
        # the job can never end up off-screen.
        self.build_tab.grid_rowconfigure(0, weight=1)
        self.build_tab.grid_rowconfigure(1, weight=0)
        # The roster takes the slack, not the form: the group panel needs a fixed
        # ~490px and no more, so every spare pixel goes to the name list — which is
        # the thing you actually read 262 lines of.
        self.build_tab.grid_columnconfigure(0, weight=1, minsize=ROSTER_PANEL_PX)
        # The form panel needs a firm width: its content is now a scroll canvas (which
        # requests no width of its own), and the coaching-type radios run two wide
        # columns. Without a minsize the column collapses and clips the right column.
        self.build_tab.grid_columnconfigure(1, weight=0, minsize=720)

        self._build_roster_panel()
        self._build_group_panel()
        self._build_batch_bar()
        self._build_report_tab()
        self._refresh_list()
        self._on_type_change()
        self._on_loc_mode()
        self._on_mode()          # apply the initial (groups) mode to both panels

        # Ctrl+Enter is "Add & Next" in individual mode — plain Enter is left free so it
        # still makes newlines while typing a description.
        self.bind("<Control-Return>",
                  lambda e: self._add_single() if self.mode.get() == "individuals"
                  else None)

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
        global _DISPLAY_FAMILY
        base = FONT_BODY
        # Resolve the display face for real rather than trusting it to be there.
        import tkinter.font as tkfont
        if _DISPLAY_FAMILY not in set(tkfont.families(self)):
            _DISPLAY_FAMILY = "Segoe UI Semibold"
            if _DISPLAY_FAMILY not in set(tkfont.families(self)):
                _DISPLAY_FAMILY = "Segoe UI"
        legend = (_DISPLAY_FAMILY, 11)

        self.configure(bg=UI_BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")     # flat + fully colour-configurable, unlike 'vista'
        except tk.TclError:
            pass

        style.configure(".", background=UI_BG, foreground=UI_TEXT, font=base,
                        bordercolor=UI_BORDER, focuscolor=UI_BG,
                        fieldbackground=UI_CARD, darkcolor=UI_BG, lightcolor=UI_BG,
                        troughcolor=UI_CARD, insertcolor=UI_TEXT)
        style.configure("TFrame", background=UI_BG)
        style.configure("TLabel", background=UI_BG, foreground=UI_TEXT)
        style.configure("TLabelframe", background=UI_BG, bordercolor=UI_BORDER,
                        relief="solid", borderwidth=1)
        # Panel legends are the signage layer: display face, tracked-out caps, amber.
        # Tk has no letter-spacing, so the spacing is put into the string itself by
        # _legend() at each call site.
        style.configure("TLabelframe.Label", background=UI_BG, foreground=UI_ACCENT_TEXT,
                        font=legend)
        # Tallies and counts — Consolas keeps digits in columns as the number changes.
        style.configure("Data.TLabel", background=UI_BG, foreground=UI_CONFIRM,
                        font=FONT_DATA)
        style.configure("Muted.TLabel", background=UI_BG, foreground=UI_MUTED)
        # Foldable section headers: the display face in accent, with the folded value
        # beside it in muted body text so the two read as label-then-value, not as two
        # competing headings.
        style.configure("Section.TLabel", background=UI_BG, foreground=UI_ACCENT_TEXT,
                        font=(_DISPLAY_FAMILY, 11))
        style.configure("SectionValue.TLabel", background=UI_BG, foreground=UI_TEXT,
                        font=("Segoe UI", 10))

        # Flat buttons with a thin border; hover tints toward the accent.
        style.configure("TButton", background=UI_CARD, foreground=UI_TEXT,
                        bordercolor=UI_BORDER, relief="solid", borderwidth=1,
                        padding=(11, 5))
        style.map("TButton",
                  background=[("pressed", UI_ACCENT_SOFT), ("active", UI_ACCENT_SOFT)],
                  bordercolor=[("active", UI_ACCENT_TEXT), ("focus", UI_ACCENT_TEXT)])
        # A filled accent button for the primary action. Text on amber is white — the
        # warm gray ground on #B8620A lands under 3:1 and is unreadable at button sizes.
        style.configure("Accent.TButton", background=UI_ACCENT, foreground=UI_ON_ACCENT,
                        bordercolor=UI_ACCENT, font=(_DISPLAY_FAMILY, 11))
        style.map("Accent.TButton",
                  background=[("pressed", UI_ACCENT_PRESS), ("active", UI_ACCENT_HOVER)],
                  foreground=[("disabled", UI_MUTED)])

        for w in ("TCheckbutton", "TRadiobutton"):
            style.configure(w, background=UI_BG, foreground=UI_TEXT, focuscolor=UI_BG)
            style.map(w, background=[("active", UI_BG)])
        # Slightly smaller variants for the dense radio/checkbox grids (coaching type,
        # details) so long labels fit two/three columns without overflowing the panel.
        style.configure("Radio10.TRadiobutton", background=UI_BG, foreground=UI_TEXT,
                        focuscolor=UI_BG, font=("Segoe UI", 10))
        style.map("Radio10.TRadiobutton", background=[("active", UI_BG)])
        style.configure("Radio10.TCheckbutton", background=UI_BG, foreground=UI_TEXT,
                        focuscolor=UI_BG, font=("Segoe UI", 10))
        style.map("Radio10.TCheckbutton", background=[("active", UI_BG)])
        style.configure("TEntry", fieldbackground=UI_CARD, bordercolor=UI_BORDER,
                        relief="solid", borderwidth=1, padding=5)
        style.map("TEntry", bordercolor=[("focus", UI_ACCENT_TEXT)])
        style.configure("TCombobox", fieldbackground=UI_CARD, background=UI_CARD,
                        bordercolor=UI_BORDER, arrowcolor=UI_TEXT, relief="solid",
                        borderwidth=1, padding=5, font=base)
        style.map("TCombobox", fieldbackground=[("readonly", UI_CARD)],
                  bordercolor=[("focus", UI_ACCENT_TEXT)])
        # Segmented control (the Groups / Individuals mode switch): radiobuttons drawn
        # as buttons, the selected one filled with the accent.
        style.configure("Toolbutton", background=UI_CARD, foreground=UI_MUTED,
                        bordercolor=UI_BORDER, relief="solid", borderwidth=1,
                        padding=(14, 6), font=(_DISPLAY_FAMILY, 11))
        style.map("Toolbutton",
                  background=[("selected", UI_ACCENT), ("active", UI_ACCENT_SOFT)],
                  foreground=[("selected", UI_ON_ACCENT), ("active", UI_ACCENT_TEXT)],
                  bordercolor=[("selected", UI_ACCENT)])
        # The tab strip (Build a batch / Case list report). Same grammar as the
        # segmented control above: the accent marks the live one.
        #
        # ⚠️ The SELECTED tab is the CARD colour and the unselected ones are the
        # ground, not the other way round. Written the intuitive way — selected sits
        # "flush" on the ground, unselected lifted on the card — the unselected tab is
        # the lighter of the two and reads as the active one. On a light theme the
        # lifted surface is the foreground, so the selected tab has to be the lifted
        # one; the amber alone does not out-shout a lightness difference.
        #
        # padding=0 so the tab page gets the window's full width. Measured, because the
        # first guess at why was wrong: at 1180x700 the notebook's own inset costs 8px
        # (1176 vs 1168 of usable width) and the roster panel sits at its 430px minsize
        # either way — it asks for 1137. The roster panel's buttons clip at this window
        # size with or without a notebook; that is the existing two-column layout, not
        # something the tab strip introduced. The 8px is free, so take it.
        style.configure("TNotebook", background=UI_BG, bordercolor=UI_BORDER,
                        tabmargins=(8, 6, 0, 0), padding=0, borderwidth=0)
        style.configure("TNotebook.Tab", background=UI_BG, foreground=UI_MUTED,
                        bordercolor=UI_BORDER, padding=(18, 7),
                        font=(_DISPLAY_FAMILY, 11))
        style.map("TNotebook.Tab",
                  background=[("selected", UI_CARD), ("active", UI_ACCENT_SOFT)],
                  foreground=[("selected", UI_ACCENT_TEXT), ("active", UI_ACCENT_TEXT)],
                  expand=[("selected", (0, 0, 0, 2))])
        style.configure("TSeparator", background=UI_BORDER)
        # The scrollbar is the one piece of chrome 'clam' draws with a visible trough;
        # sinking it into the ground keeps the slate unbroken.
        style.configure("Vertical.TScrollbar", background=UI_BORDER, troughcolor=UI_BG,
                        bordercolor=UI_BG, arrowcolor=UI_MUTED, relief="flat")
        style.map("Vertical.TScrollbar", background=[("active", UI_MUTED)])

        self.option_add("*TCombobox*Listbox.font", base)
        self.option_add("*TCombobox*Listbox.background", UI_CARD)
        self.option_add("*TCombobox*Listbox.foreground", UI_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", UI_ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", UI_ON_ACCENT)

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
                on[yy][x] = UI_ON_ACCENT

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
        """The roster list: a read-only tk.Text + scrollbar that grows with its container.

        WHY NOT A LISTBOX. It was one until 2026-07-31. A Listbox allows exactly ONE
        foreground per row, so the shift rail — a coloured bar that has to be a different
        colour from the name beside it — is impossible there. Text tags colour arbitrary
        character ranges, so the rail is simply the first character with its own tag.

        Losing nothing in the swap: the Listbox was created `selectmode=EXTENDED`, but
        `_on_click` returned "break", which pre-empts the class binding that would set a
        selection — so no mouse selection ever existed and `curselection()` was always
        empty. The real interaction has always been click-a-row-to-toggle, and that is
        preserved exactly. Keyboard access is now better than it was: a focus row that
        moves with Up/Down and toggles on Return/Space, which the dead curselection()
        binding only pretended to offer.

        state="disabled" makes it read-only; every write flips it back briefly.
        """
        wrap = ttk.Frame(parent)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        kw.pop("selectmode", None)          # a Text has no selectmode
        box = tk.Text(wrap, wrap="none", cursor="arrow", state="disabled",
                      bg=UI_CARD, fg=UI_TEXT, borderwidth=0, highlightthickness=1,
                      highlightbackground=UI_BORDER, highlightcolor=UI_BORDER,
                      insertwidth=0, spacing1=2, spacing3=2, padx=0, takefocus=True,
                      selectbackground=UI_CARD, selectforeground=UI_TEXT, **kw)
        box.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(wrap, orient="vertical", command=box.yview)
        bar.grid(row=0, column=1, sticky="ns")
        box.config(yscrollcommand=bar.set)

        # One tag per shift for the rail, plus the row states. Tagging a line THROUGH its
        # newline is what makes a background span the full width rather than stopping at
        # the last glyph — the one Text behaviour this layout depends on.
        for shift, colour in SHIFT_RAIL.items():
            box.tag_configure(f"rail_{shift}", foreground=colour)
        box.tag_configure("rail_none", foreground=SHIFT_RAIL_NONE)
        box.tag_configure("checked", background=CHECK_BG, foreground=CHECK_FG)
        box.tag_configure("focusrow", background=UI_ACCENT_SOFT)
        box.tag_raise("rail_1st"); box.tag_raise("rail_2nd")
        box.tag_raise("rail_3rd"); box.tag_raise("rail_none")
        return wrap, box

    # ── left: filters + the roster ────────────

    def _build_roster_panel(self):
        frame = ttk.LabelFrame(self.build_tab, text=_legend("Who did you see?"), padding=6)
        frame.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=(8, 0))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)      # the inner content takes the height

        # Mode switch (item 7). Lives here, on the left, because this panel has vertical
        # slack (the name list gives back any space); the right-hand form is too tight.
        mode_bar = ttk.Frame(frame)
        mode_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(mode_bar, text="Entry mode:").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(mode_bar, text="Groups", value="groups", variable=self.mode,
                        style="Toolbutton", command=self._on_mode).pack(side="left")
        ttk.Radiobutton(mode_bar, text="Individuals", value="individuals",
                        variable=self.mode, style="Toolbutton",
                        command=self._on_mode).pack(side="left", padx=(2, 0))
        ttk.Radiobutton(mode_bar, text="Shift Pool", value="pool",
                        variable=self.mode, style="Toolbutton",
                        command=self._on_mode).pack(side="left", padx=(2, 0))
        self.mode_hint = ttk.Label(mode_bar, text="", foreground=UI_MUTED)
        self.mode_hint.pack(side="left", padx=(10, 0))

        # Everything else lives in an inner frame so the mode bar can sit above it
        # without renumbering the rows below.
        inner = ttk.Frame(frame)
        inner.grid(row=1, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_rowconfigure(5, weight=1)      # the name list eats the spare height
        frame = inner                             # rows below are unchanged

        # Shift chips + role toggles — both small closed sets, so they live inline.
        shifts = ttk.Frame(frame)
        shifts.grid(row=0, column=0, sticky="w")
        ttk.Label(shifts, text="Shift:").pack(side="left", padx=(0, 8))
        self.shift_vars = {}
        for shift in self.all_shifts:
            var = tk.BooleanVar(value=shift not in self.hidden_shifts)
            self.shift_vars[shift] = var
            ttk.Checkbutton(shifts, text=shift, variable=var,
                            command=self._on_filter_change).pack(side="left", padx=(0, 12))

        # Role toggles (item 1): quick "show only the leads / supervisors". An
        # inclusion filter — inactive when neither is ticked, so the normal view is
        # unchanged. Not persisted: it's a momentary "just the leads today" view, not a
        # standing preference like a hidden shift. Matches by title (see ROLE_FILTERS).
        ttk.Separator(shifts, orient="vertical").pack(side="left", fill="y", padx=(6, 8))
        ttk.Label(shifts, text="Role:").pack(side="left", padx=(0, 8))
        self.role_vars = {}
        for label, prefixes in ROLE_FILTERS:
            var = tk.BooleanVar(value=False)
            self.role_vars[label] = (var, prefixes)
            ttk.Checkbutton(shifts, text=label, variable=var,
                            command=self._refresh_list).pack(side="left", padx=(0, 12))

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

        filter_sep = ttk.Separator(frame, orient="horizontal")
        filter_sep.grid(row=3, column=0, sticky="ew", pady=6)

        find = ttk.Frame(frame)
        find.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(find, text="Find:").pack(side="left", padx=(0, 6))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._refresh_list())
        entry = ttk.Entry(find, textvariable=self.filter_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.focus_set()
        self.find_entry = entry          # individual mode refocuses here after each add
        # Review the current pick: collapse the list to just who's checked.
        self.checked_only = tk.BooleanVar(value=False)
        self.checked_only_box = ttk.Checkbutton(find, text="checked only",
                                                variable=self.checked_only,
                                                command=self._refresh_list)
        self.checked_only_box.pack(side="left", padx=(8, 0))

        # Taller, roomier rows in a clean proportional font (was cramped monospace).
        wrap, self.listbox = self._scrolled_list(frame, font=("Segoe UI", 13), height=8)
        wrap.grid(row=5, column=0, sticky="nsew")
        self.listbox.bind("<Button-1>", self._on_click)
        self.listbox.bind("<Return>", lambda e: self._toggle_selection())
        self.listbox.bind("<space>", lambda e: self._toggle_selection())
        # Arrow keys move the focus row. Each returns "break" so the Text's own cursor
        # movement doesn't also run and scroll the view somewhere else.
        self.listbox.bind("<Up>", lambda e: self._move_focus(-1))
        self.listbox.bind("<Down>", lambda e: self._move_focus(1))
        self.listbox.bind("<Prior>", lambda e: self._move_focus(-10))
        self.listbox.bind("<Next>", lambda e: self._move_focus(10))
        # A Text is editable-looking by default; swallow anything that would type into it.
        self.listbox.bind("<Key>", lambda e: "break")

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

        # Bulk-check controls are group-only — one-at-a-time mode hides them (checking
        # many names would break the "exactly one loaded" invariant).
        self._roster_group_only = [buttons, pick]

        # Individual mode strips this panel to a search box and the roster, and nothing
        # else (Dane, 2026-09-03). The filters above are all GROUP tools: you narrow a
        # 261-name list to sweep an area or a shift. Picking one person is a different
        # act — you already know who, so you type the name. Every filter left on screen
        # is then a control that can only get in the way, and "shown / filtered out / on
        # roster" is a tally of a list you are not working as a list.
        #
        # Kept on the grid in individual mode: the mode switch (you have to be able to
        # leave), Find, and the name list.
        self._roster_individual_hide = [shifts, head, areas, filter_sep]

        # justify: the two lines are left-aligned, not centred on each other.
        # wraplength: a backstop for the one unbounded part — an employee name in
        # individual mode. The longest real one measures 378px, but a longer hire
        # should wrap rather than silently clip, which is the bug being fixed here.
        self.count_label = ttk.Label(frame, text="", font=("Segoe UI", 13, "bold"),
                                     foreground=CHECK_FG, justify="left",
                                     wraplength=ROSTER_PANEL_PX)
        self.count_label.grid(row=8, column=0, sticky="w", pady=(4, 0))
        self.roster_hint = ttk.Label(frame, text="", foreground=UI_MUTED, wraplength=600)
        self.roster_hint.grid(row=9, column=0, sticky="w")
        # The tally and the long hint go with the filters — see _roster_individual_hide.
        # mode_hint, up beside the mode switch, still carries the one-line instruction.
        self._roster_individual_hide += [self.count_label, self.roster_hint]

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
        # Individual mode: the search box is the ONLY filter. Its panel hides the
        # area/shift/role controls, and a filter you cannot see is a filter you cannot
        # undo — a name inside an area Dane has hidden between runs would simply never
        # appear, with nothing on screen to explain why or turn back on.
        if self.mode.get() == "individuals":
            return needle in person["name"].lower()
        # Reviewing the pick: show EVERY checked person, even one a hidden area/shift
        # would otherwise drop — the point is to see the whole group before adding it.
        if self.checked_only.get():
            return person["name"] in self.checked and needle in person["name"].lower()
        if person["div"] and person["div"] in self.hidden_areas:
            return False
        if person["shift"] and person["shift"] in self.hidden_shifts:
            return False
        # Role filter (item 1): if any role is ticked, keep only titles that match one.
        active = [pre for var, pre in self.role_vars.values() if var.get()]
        if active and not any(title_matches_role(person["title"], pre) for pre in active):
            return False
        return needle in person["name"].lower()

    def _display(self, person):
        """The row's text. The leading RAIL_GLYPH is coloured separately by _tag_row."""
        mark = CHECK_ON if person["name"] in self.checked else CHECK_OFF
        return f"{RAIL_GLYPH} {mark}  {person['name']}"

    @staticmethod
    def _rail_tag(person):
        shift = (person.get("shift") or "").lower()
        return f"rail_{shift}" if shift in SHIFT_RAIL else "rail_none"

    def _tag_row(self, idx, person):
        """Colour one row: the rail glyph by shift, the whole line by checked state.

        Order matters. The `checked` tag spans the line INCLUDING its newline (so the
        wash reaches the full width), which would otherwise repaint the rail in the
        checked foreground — so the rail tag is re-applied last and raised above it.
        """
        line = idx + 1
        checked = person["name"] in self.checked
        self.listbox.tag_remove("checked", f"{line}.0", f"{line + 1}.0")
        if checked:
            self.listbox.tag_add("checked", f"{line}.0", f"{line + 1}.0")
        self.listbox.tag_add(self._rail_tag(person), f"{line}.0", f"{line}.1")

    def _paint_row(self, idx, checked):
        """Kept for callers that only know the checked flag; the person carries the rail."""
        if 0 <= idx < len(self.shown):
            self._tag_row(idx, self.shown[idx])

    def _write(self, fn):
        """Run a mutation with the read-only Text briefly writable."""
        self.listbox.config(state="normal")
        try:
            fn()
        finally:
            self.listbox.config(state="disabled")

    def _refresh_list(self):
        self.shown = [p for p in self.people if self._visible(p)]
        # Build the whole block once and insert it in a single call — 261 individual
        # inserts each trigger a re-layout, which is visible as a stutter on a filter change.
        block = "".join(self._display(p) + "\n" for p in self.shown)

        def rebuild():
            self.listbox.delete("1.0", "end")
            if block:
                self.listbox.insert("1.0", block)
        self._write(rebuild)

        for i, person in enumerate(self.shown):
            self._tag_row(i, person)
        if self._focus_idx >= len(self.shown):
            self._focus_idx = max(len(self.shown) - 1, 0)
        self._paint_focus()
        self._update_count()

    def _paint_focus(self):
        """The keyboard focus row — a faint amber wash, under the checked wash."""
        self.listbox.tag_remove("focusrow", "1.0", "end")
        if self.shown and 0 <= self._focus_idx < len(self.shown):
            line = self._focus_idx + 1
            self.listbox.tag_add("focusrow", f"{line}.0", f"{line + 1}.0")
            self.listbox.tag_lower("focusrow", "checked")
            self.listbox.see(f"{line}.0")

    def _move_focus(self, delta):
        if not self.shown:
            return "break"
        self._focus_idx = max(0, min(len(self.shown) - 1, self._focus_idx + delta))
        self._paint_focus()
        return "break"

    def _update_count(self):
        filtered_out = sum(1 for p in self.people
                           if p["div"] in self.hidden_areas
                           or p["shift"] in self.hidden_shifts)
        # In individual mode the "checked" set is the single loaded person — say who,
        # not a count.
        if self.mode.get() == "individuals":
            loaded = next(iter(self.checked)) if self.checked else "—"
            lead = f"{CHECK_ON} Loaded: {loaded}      "
        else:
            # A name checked while a filter hid it still counts — say so, so a group can
            # never quietly include someone you can't currently see.
            hidden_checks = len(self.checked - {p["name"] for p in self.shown})
            extra = f"   ({hidden_checks} checked but hidden)" if hidden_checks else ""
            lead = f"{CHECK_ON} {len(self.checked)} checked{extra}"
        # TWO LINES, deliberately. On one line this needed 494-758px in a 431px panel
        # and had been clipping since before the redesign — the roster totals simply
        # ran off the edge. Measured at Segoe UI 13 bold: the lead peaks at 345px
        # (261 checked, 155 of them hidden) or 378px (longest real name in individual
        # mode), and the totals row is a fixed 350px at three digits. Both clear 431
        # with room, and no number had to be dropped to get there. `shown` is also
        # filtered by the search box and role filters, so it is NOT derivable from
        # `filtered_out` — the three counts are independent and all three are kept.
        self.count_label.config(
            text=f"{lead}\n{len(self.shown)} shown · {filtered_out} filtered out · "
                 f"{len(self.people)} on roster")

    def _on_click(self, event):
        # Text indexes by character, not by row: "@x,y" resolves the click to a position,
        # and its line number (1-based) is the row. Clicking past the last row lands on
        # the trailing empty line, which is why the bounds check still matters.
        self.listbox.focus_set()
        idx = int(self.listbox.index(f"@{event.x},{event.y}").split(".")[0]) - 1
        if 0 <= idx < len(self.shown):
            self._focus_idx = idx
            if self.mode.get() == "individuals":
                self._select_one(idx)
            else:
                self._toggle(idx)
                self._paint_focus()
        return "break"      # a Text would otherwise start a drag-selection

    def _toggle_selection(self):
        """Return/Space acts on the focus row."""
        if not self.shown or not 0 <= self._focus_idx < len(self.shown):
            return "break"
        if self.mode.get() == "individuals":
            self._select_one(self._focus_idx)
        else:
            self._toggle(self._focus_idx)
            self._paint_focus()
        return "break"

    def _select_one(self, idx):
        """Individual mode: load exactly this person, replacing any current pick."""
        self.checked = {self.shown[idx]["name"]}
        self._refresh_list()
        self._update_count()

    def _toggle(self, idx):
        person = self.shown[idx]
        name = person["name"]
        now_checked = name not in self.checked
        self.checked.add(name) if now_checked else self.checked.discard(name)
        # "Show checked only" is on: an unchecked row should drop out immediately.
        if self.checked_only.get() and not now_checked:
            self._refresh_list()
            return
        line = idx + 1
        self._write(lambda: (self.listbox.delete(f"{line}.0", f"{line + 1}.0"),
                             self.listbox.insert(f"{line}.0",
                                                 self._display(person) + "\n")))
        self._tag_row(idx, person)
        self._update_count()

    def _bulk(self, on):
        for person in self.shown:
            self.checked.add(person["name"]) if on else self.checked.discard(person["name"])
        self._refresh_list()

    def _clear_all(self):
        self.checked.clear()
        self._refresh_list()

    # ── right: the group ──────────────────────

    @staticmethod
    def _radios(parent, var, options, columns, command=None, font=None):
        """A grid of radio buttons — every option visible at once, no dropdown, no
        scrolling (Dane's requirement). Returns the frame; grid it into the form."""
        f = ttk.Frame(parent)
        style = "Radio10.TRadiobutton" if font == "small" else "TRadiobutton"
        for i, opt in enumerate(options):
            rb = ttk.Radiobutton(f, text=opt, value=opt, variable=var, style=style)
            if command:
                rb.config(command=command)
            rb.grid(row=i // columns, column=i % columns, sticky="w",
                    padx=(0, 14), pady=1)
        return f

    def _open_calendar(self, var=None):
        """Pop a small month calendar to pick a date — no typing.

        `var` is which StringVar to write MM/DD/YYYY into; it defaults to the
        encounter date so the existing call sites are unchanged. The report tab passes
        its own From/To vars, because a date that can be typed is a date that can be
        typed wrong, and this picker is already the one place that cannot be.
        """
        var = var or self.date_var
        import calendar as _cal
        try:
            cur = datetime.strptime(var.get().strip(), "%m/%d/%Y").date()
        except Exception:
            cur = date.today()
        top = tk.Toplevel(self)
        top.title("Pick a date")
        top.transient(self)
        top.resizable(False, False)
        top.configure(bg=UI_CARD)
        top.grab_set()
        st = {"y": cur.year, "m": cur.month}

        header = ttk.Frame(top, padding=(8, 8))
        header.pack(fill="x")
        title = ttk.Label(header, font=("Segoe UI", 12, "bold"), anchor="center")
        grid = ttk.Frame(top, padding=(8, 0))
        grid.pack()

        def pick(d):
            var.set(d.strftime("%m/%d/%Y"))
            top.destroy()

        def draw():
            for w in grid.winfo_children():
                w.destroy()
            title.config(text=date(st["y"], st["m"], 1).strftime("%B %Y"))
            for i, wd in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
                ttk.Label(grid, text=wd, foreground=UI_MUTED,
                          width=4, anchor="center").grid(row=0, column=i, pady=(0, 2))
            for r, week in enumerate(_cal.Calendar(0).monthdayscalendar(st["y"], st["m"]), 1):
                for c, day in enumerate(week):
                    if day == 0:
                        continue
                    d = date(st["y"], st["m"], day)
                    sel, today = d == cur, d == date.today()
                    b = tk.Button(grid, text=str(day), width=3, relief="flat", bd=0,
                                  bg=UI_ACCENT if sel else UI_CARD,
                                  fg=UI_ON_ACCENT if sel else UI_TEXT,
                                  activebackground=UI_ACCENT_SOFT, cursor="hand2",
                                  font=("Segoe UI", 10, "bold" if today else "normal"),
                                  command=lambda dd=d: pick(dd))
                    b.grid(row=r, column=c, padx=1, pady=1)

        def shift(delta):
            m = st["m"] - 1 + delta
            st["y"] += m // 12
            st["m"] = m % 12 + 1
            draw()

        ttk.Button(header, text="‹", width=3, command=lambda: shift(-1)).pack(side="left")
        title.pack(side="left", expand=True, fill="x")
        ttk.Button(header, text="›", width=3, command=lambda: shift(1)).pack(side="right")
        foot = ttk.Frame(top, padding=(8, 8))
        foot.pack(fill="x")
        ttk.Button(foot, text="Today", command=lambda: pick(date.today())).pack(side="left")
        ttk.Button(foot, text="Close", command=top.destroy).pack(side="right")
        draw()
        top.update_idletasks()
        top.geometry(f"+{self.winfo_rootx() + 300}+{self.winfo_rooty() + 120}")
        return top          # so a test can drive it; callers ignore it

    def _build_group_panel(self):
        # Legend is the short form: tracked, "WHAT WAS THE ENCOUNTER?" measures 224px
        # against a ~402px column at the 860px minimum window, where the old full string
        # tracked would run 497px and squeeze the roster panel. The dropped
        # "(applies to everyone checked)" is already said by self.mode_hint.
        outer = ttk.LabelFrame(self.build_tab, text=_legend("What was the encounter?"),
                               padding=(2, 2))
        outer.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=(8, 0))
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)
        self.group_frame = outer

        # Scrollable so the tall coaching-type radio block + details + location can never
        # clip the description on a short screen. Every option stays laid out and visible
        # — you never scroll to *pick* a coaching type; the panel only scrolls when the
        # whole form is taller than the window (heavy group cases). Individual entry and
        # light groups don't scroll at all.
        canvas = tk.Canvas(outer, highlightthickness=0, bg=UI_BG, width=690)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vsb.set)
        frame = ttk.Frame(canvas, padding=(6, 4))
        fwin = canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(fwin, width=e.width))
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        row = 0
        # Date — calendar picker, never typed.
        ttk.Label(frame, text="Date").grid(row=row, column=0, sticky="w", pady=2)
        self.date_var = tk.StringVar(value=date.today().strftime("%m/%d/%Y"))
        datef = ttk.Frame(frame)
        datef.grid(row=row, column=1, sticky="w")
        de = ttk.Entry(datef, textvariable=self.date_var, width=12, state="readonly")
        de.pack(side="left")
        de.bind("<Button-1>", lambda e: self._open_calendar())
        ttk.Button(datef, text="📅  Pick date",
                   command=self._open_calendar).pack(side="left", padx=(6, 0))

        # ── the foldable blocks ──
        # Each takes TWO grid rows (header, then body), so every `row` step below is +2.
        self.sections = []

        row += 1
        # Encounter type — radios, no dropdown. Collapsed by default: it has a real
        # default value and Dane changes it rarely, so it earns one line, not eight.
        self.etype_var = tk.StringVar(value=ace.ENCOUNTER_TYPES[0])
        self.etype_section = self._section(frame, row, "Encounter type",
                                           lambda: self.etype_var.get(), collapsed=True)
        self._radios(self.etype_section.body, self.etype_var, ace.ENCOUNTER_TYPES,
                     columns=2, command=self.etype_section.collapse).grid(
            row=0, column=0, sticky="w")

        row += 2
        # Coaching type — ALL options as radios (Dane: no dropdown, no scrolling).
        # Starts OPEN, unlike the rest: it is the one field with no default, a group will
        # not build without it, and nothing here may guess it. An unset field that folds
        # itself away is exactly the field you forget to set.
        #
        # SUGGEST_TYPE is the one exception, and it is not the tool guessing — it is Dane
        # asking for a recommendation he then reads back. It sits last so the eleven real
        # values are what the eye lands on first.
        self.type_var = tk.StringVar(value=PICK_ONE)
        self.type_section = self._section(frame, row, "Coaching type",
                                          lambda: self.type_var.get(), collapsed=False)
        self._radios(self.type_section.body, self.type_var,
                     COACHING_TYPES + [SUGGEST_TYPE], columns=2,
                     command=self._pick_coaching_type, font="small").grid(
            row=0, column=0, sticky="w")

        row += 2
        # Details — multi-select, so it folds on the accordion, never on a click. Opens
        # by itself the moment a coaching type is picked, because that is the only point
        # at which its boxes exist and it is the next thing to do.
        self.details_section = self._section(frame, row, "Details",
                                             self._details_summary, collapsed=True)
        self.details_frame = self.details_section.body

        row += 2
        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=2,
                                                       sticky="ew", pady=2)

        # ── where they were ──
        row += 1
        loc_header = ttk.Label(frame, text="Department / shift",
                               font=("Segoe UI", 11, "bold"))
        loc_header.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        self.loc_mode = tk.StringVar(value="per_employee")
        loc_radio1 = ttk.Radiobutton(frame, text="Each employee's own, from the roster  "
                                     "(use for a group spread across departments)",
                                     variable=self.loc_mode, value="per_employee",
                                     command=self._on_loc_mode)
        loc_radio1.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        loc_radio2 = ttk.Radiobutton(frame, text="Same for everyone in this group  "
                                     "(use for a sweep of one area)",
                                     variable=self.loc_mode, value="group",
                                     command=self._on_loc_mode)
        loc_radio2.grid(row=row, column=0, columnspan=2, sticky="w")

        row += 1
        self.group_loc = ttk.Frame(frame)
        self.group_loc.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(self.group_loc, text="Work area").grid(row=0, column=0, sticky="w", pady=3)
        self.area_var = tk.StringVar()
        area = ttk.Entry(self.group_loc, textvariable=self.area_var, width=38)
        area.grid(row=0, column=1, sticky="w")
        area.bind("<KeyRelease>", lambda e: self._resolve_area())
        ttk.Label(self.group_loc, text='e.g. "station 85", "wrap weld", "line lead weld"',
                  foreground=UI_MUTED).grid(row=1, column=1, sticky="w")

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
        self.loc_note = ttk.Label(frame, text="", foreground=UI_MUTED, wraplength=620)
        self.loc_note.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # The whole "where were they" block. Individual mode hides it — a single is
        # always located to that person's own roster dept/div/shift, so there's nothing
        # to choose, and hiding it gives the description box more room.
        self._loc_section_widgets = [loc_header, loc_radio1, loc_radio2,
                                     self.group_loc, self.loc_note]

        row += 1
        # Category — collapsed by default; it has a default value and rarely moves.
        self.cat_var = tk.StringVar(value=fm.CATEGORY_DEFAULT)
        self.cat_section = self._section(frame, row, "Category",
                                         lambda: self.cat_var.get(), collapsed=True)
        self._radios(self.cat_section.body, self.cat_var,
                     ace.FIELD_OPTIONS.get("Category", []), columns=2,
                     command=self.cat_section.collapse).grid(row=0, column=0, sticky="w")

        row += 2
        # Prompted by — folds after a pick. Left OPEN at startup: Dane asked for it to
        # collapse on selection but did not ask for it to start folded, and it is the
        # one remaining block where the default is worth seeing rather than trusting.
        self.prompted_var = tk.StringVar(value=ace.WHAT_PROMPTED_OPTIONS[0])
        self.prompted_section = self._section(frame, row, "Prompted by",
                                              lambda: self.prompted_var.get(),
                                              collapsed=False)
        self._radios(self.prompted_section.body, self.prompted_var,
                     ace.WHAT_PROMPTED_OPTIONS, columns=2,
                     command=self.prompted_section.collapse).grid(
            row=0, column=0, sticky="w")

        row += 2
        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=2,
                                                       sticky="ew", pady=2)

        row += 1
        head = ttk.Frame(frame)
        head.grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Label(head, text="Description").pack(side="left")
        if self.library:
            ttk.Button(head, text="Library…", width=10,
                       command=self._open_library).pack(side="left", padx=8)
            ttk.Label(head, text=f"{len(self.library)} standard descriptions in "
                                 f"{len({e['tab'] for e in self.library})} tabs",
                      foreground=UI_MUTED).pack(side="left")
        else:
            ttk.Label(head, text="(workbook not found — type the description)",
                      foreground=UI_MUTED).pack(side="left", padx=8)

        # Ticked, the box below holds a NOTE — "hydration and magnesium" — not a
        # description, and Claude turns it into one when the batch is written. One tick
        # rather than a second box: the note goes where the description goes, and there
        # is no note column in encounters.csv for it to be mistaken for a real one.
        self.note_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(head, text="Note only — Claude writes it",
                        variable=self.note_var,
                        style="Radio10.TCheckbutton").pack(side="right")

        row += 1
        # Fixed height inside the scroll canvas — 5 lines is plenty for entry, and the
        # panel scrolls rather than collapsing this box when the form is tall.
        self.desc_text = tk.Text(frame, height=5, wrap="word", font=("Segoe UI", 11),
                                 bg=UI_CARD, fg=UI_TEXT, borderwidth=1, relief="solid",
                                 highlightthickness=1, highlightbackground=UI_BORDER,
                                 highlightcolor=UI_ACCENT_TEXT, padx=6, pady=6)
        self.desc_text.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=4)
        frame.grid_columnconfigure(1, weight=1)

    # ── foldable form sections ────────────────

    def _section(self, parent, row, label, summary, collapsed):
        """Build a CollapsibleSection wired into this window's accordion."""
        sec = CollapsibleSection(parent, row, label, summary, collapsed=collapsed,
                                 on_expand=self._section_opened)
        self.sections.append(sec)
        return sec

    def _section_opened(self, opened):
        """Accordion: opening one block folds every other one."""
        for sec in self.sections:
            if sec is not opened and not sec.collapsed:
                sec.collapse()

    def _details_summary(self):
        """What the folded Details header shows.

        Names the picks rather than counting them — 'Hydration, Rest break' is what you
        are checking for when you glance at a folded form; '2 selected' would make you
        open it again to find out whether it is the right two.
        """
        if self.type_var.get() == PICK_ONE:
            return "—"
        picked = [n for n, v in self.detail_vars.items() if v.get()]
        if not picked:
            return "none" if self.detail_vars else "no details for this type"
        text = ", ".join(picked)
        return text if len(text) <= 58 else f"{text[:55]}…"

    def _pick_coaching_type(self):
        """A coaching type was clicked: rebuild its details, fold this, open those.

        The hand-off is the point. Picking a type is never the end of a thought — the
        details belong to the type and are the only thing that can be done next, so the
        form moves there rather than leaving Dane to notice a block that just refilled
        itself further down the panel.
        """
        self._on_type_change()
        self.type_section.collapse()
        self.details_section.expand()

    def _on_loc_mode(self):
        per_employee = self.loc_mode.get() == "per_employee"
        # Item 5: when the group-wide location doesn't apply (per-employee mode), HIDE
        # the whole dept/div/shift block rather than just disabling it. Five disabled
        # rows sitting there was what pushed the description box off-screen for a long
        # type like Group Class; removing them from the grid reclaims that height.
        if per_employee:
            self.group_loc.grid_remove()
        else:
            self.group_loc.grid()
            for widget, active_state in self._group_loc_widgets:
                widget.configure(state=active_state)
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
                      foreground=UI_MUTED).grid(row=0, column=0, sticky="w")
            self.details_section.refresh()
            return

        if chosen == SUGGEST_TYPE:
            # The boxes belong to the type, and the type isn't known yet — so there is
            # nothing here that could be ticked. Dane ticks them in the EMR either way.
            ttk.Label(self.details_frame,
                      text="(no boxes until the type is known — you tick them in the EMR)",
                      foreground=UI_MUTED).grid(row=0, column=0, sticky="w")
            self.details_section.refresh()
            return

        options = sorted(ace.CHECKBOX_UUID_MAP.get(chosen, {}))
        if not options:
            ttk.Label(self.details_frame, text="(this type has no details)",
                      foreground=UI_MUTED).grid(row=0, column=0, sticky="w")
            self.details_section.refresh()
            return

        # Long detail labels (some Group Class ones run 40+ chars) stay 2-up; short sets
        # go 3-up to save vertical room now that coaching type is a tall radio block.
        longest = max((len(n) for n in options), default=0)
        cols = 2 if longest > 24 else 3
        for i, name in enumerate(options):
            var = tk.BooleanVar()
            self.detail_vars[name] = var
            ttk.Checkbutton(self.details_frame, text=name, variable=var,
                            style="Radio10.TCheckbutton",
                            command=self.details_section.refresh).grid(
                row=i // cols, column=i % cols, sticky="w", padx=(0, 12))
        self.details_section.refresh()

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
        tabs = sorted({e["tab"] for e in self.library})
        cats = ["All categories"] + tabs
        # Item 2: open already filtered to the tab that matches the chosen coaching type,
        # so the relevant descriptions are the ones on screen. Falls back to "All".
        default_cat = library_category_for(self.type_var.get(), tabs) or "All categories"
        cat_var = tk.StringVar(value=default_cat)
        # Item 4: height = one row per category, so the whole list shows at once instead
        # of a short scrolling window. Capped so a huge workbook can't make it taller
        # than the screen.
        ttk.Combobox(top, textvariable=cat_var, values=cats, state="readonly",
                     width=24, height=min(len(cats), 25)).pack(side="left", padx=(0, 4))
        if default_cat != "All categories":
            ttk.Label(top, text=f"(matched to {self.type_var.get()})",
                      foreground=UI_MUTED).pack(side="left", padx=(0, 16))
        else:
            ttk.Label(top, text="", width=1).pack(side="left", padx=(0, 12))
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
            # If no coaching type is chosen yet, let the picked description set it (from
            # its tab). Only when UNSET — never override a type Dane deliberately chose.
            # This is what makes an individual entry "person + one library pick".
            auto_ct = None
            if self.type_var.get() == PICK_ONE:
                auto_ct = coaching_type_for_tab(entry["tab"], COACHING_TYPES)
                if auto_ct:
                    self.type_var.set(auto_ct)
                    self._on_type_change()      # rebuild the detail boxes for that type
            ticked = details_from_hint(entry["hint"], list(self.detail_vars))
            for name in ticked:
                self.detail_vars[name].set(True)
            # The library just set the type and ticked boxes on Dane's behalf. Fold the
            # type block (it is settled) and re-read the details header, so the folded
            # form shows what the pick actually did rather than what it said a moment ago.
            if auto_ct:
                self.type_section.collapse()
            self.details_section.refresh()
            win.destroy()
            note = []
            if auto_ct:
                note.append(f"Coaching set to {auto_ct}")
            if ticked:
                note.append("ticked " + ", ".join(ticked))
            if note:
                self.batch_detail.config(text="From your note: " + "; ".join(note))

        def render(*_):
            for child in inner.winfo_children():
                child.destroy()
            cat, needle = cat_var.get(), search_var.get().strip().lower()
            matches = [e for e in self.library
                       if (cat == "All categories" or e["tab"] == cat)
                       and needle in (e["tab"] + e["label"] + e["text"]).lower()]
            if not matches:
                ttk.Label(inner, text="No descriptions match.",
                          foreground=UI_MUTED).pack(anchor="w", padx=12, pady=14)
            for e in matches:
                # tk.Frame (not ttk) so it gets a clean 1px border + flat panel fill,
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
                tk.Label(head, text=e["tab"], bg=UI_ACCENT_SOFT, fg=UI_ACCENT_TEXT,
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
                  foreground=UI_MUTED).pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        render()

    # ── bottom: the batch ─────────────────────

    def _build_batch_bar(self):
        """The three buttons that finish the job. Pinned to the bottom row, which has
        no weight — it keeps its height however small the window gets, so these can
        never be pushed off-screen the way a fixed-size window pushed them off."""
        frame = ttk.Frame(self.build_tab, padding=(8, 6))
        frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        counts = ttk.Frame(frame)
        counts.grid(row=0, column=0, sticky="w")
        # The batch tally is the one CONFIRMED number on screen — rows actually banked —
        # so it gets the hi-vis green and Consolas, whose tabular figures stop the count
        # jittering sideways as it climbs. It sits in the full-width bottom bar, so
        # Consolas' extra width costs nothing here (unlike the roster tally, which is
        # already tight against its 431px panel).
        self.batch_label = ttk.Label(counts, text="Batch: 0 rows", style="Data.TLabel")
        self.batch_label.pack(anchor="w")
        self.batch_detail = ttk.Label(counts, text="Nothing added yet.", foreground=UI_MUTED)
        self.batch_detail.pack(anchor="w")

        actions = ttk.Frame(frame)
        actions.grid(row=0, column=1, sticky="e")
        # The primary add button's label + action swap with the mode (see _on_mode):
        # "Add group to batch" / "Add & Next".
        self.add_btn = ttk.Button(actions, text="Add group to batch",
                                  command=self._add_group)
        self.add_btn.pack(side="left")
        ttk.Button(actions, text="📥 From Tracker Lite",
                   command=self._import_tracker).pack(side="left", padx=6)
        ttk.Button(actions, text="Review batch…",
                   command=self._review_batch).pack(side="left", padx=6)
        ttk.Button(actions, text="Undo last group",
                   command=self._undo_group).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Write & enter batch", style="Accent.TButton",
                   command=self._write_csv).pack(side="left")

    def _import_tracker(self):
        """Pull floor captures from EMR Tracker Lite into the batch.

        Each capture becomes its own group of one — the same shape "Add & Next" makes —
        so they show up in Review, can be deleted individually, and are finished here
        before anything is written. A capture never bypasses the builder.

        Department, division and shift are taken from the ROSTER, not from the phone.
        Category and encounter type come from the form's current values, so whatever
        Dane has selected applies. The capture supplies only who / when / type /
        details / description / prompted-by.
        """
        try:
            import tracker_import as ti
            import ati_coaching_encounter as ace
        except Exception as exc:
            messagebox.showerror("Import unavailable", f"Couldn't load the importer:\n{exc}")
            return

        rows, pending, problems, errors, found = ti.import_for_builder(
            self.people,
            valid_coaching_types=set(ace.CHECKBOX_UUID_MAP),
            encounter_type=self.etype_var.get(),
            category=self.cat_var.get(),
        )

        if not found:
            # Name the real folder rather than describing one. Creating it here means
            # "Set folder" in Tracker Lite has something to point at.
            drop, created = ti.suggested_drop_folder()
            messagebox.showinfo(
                "No captures found",
                "No tracker_capture.json turned up.\n\n"
                f"Point Tracker Lite at:\n  {drop}\n"
                + ("(just created for you)\n" if created else "")
                + "\nIn Tracker Lite: Records → “Set folder” → pick that folder, then "
                  "“→ Send to Builder”. On iPhone/Safari there is no folder picker — the "
                  "send downloads the file and you move it there yourself.\n\n"
                "Looked in:\n  " + "\n  ".join(
                    d for d in ti.default_search_dirs() if d))
            return

        if not rows and not pending and not problems:
            messagebox.showinfo("Nothing to import",
                                f"{os.path.basename(found)} has no captures in it.")
            return

        detail = []
        if rows:
            detail.append(f"{len(rows)} capture(s) already have a name — ready to add.")
        if pending:
            total = sum(c["group_size"] for c in pending)
            detail.append(f"{len(pending)} capture(s) still need a name "
                          f"({total} encounter(s) once named). I'll walk you through them.")
        if problems:
            detail.append(f"\n{len(problems)} could NOT be used and will be left out:")
            for cap, why in problems[:8]:
                detail.append(f"   • {cap['employee'] or '(no name)'} — {why}")
            if len(problems) > 8:
                detail.append(f"   … and {len(problems) - 8} more")
        if errors:
            detail.append("\n" + "\n".join(errors))
        detail.append("\nWork area and shift come from the roster, not the phone.")
        detail.append("Continue?")

        if not rows and not pending:
            messagebox.showwarning("Nothing usable", "\n".join(detail))
            return
        if not messagebox.askyesno("Import from Tracker Lite", "\n".join(detail)):
            return

        for row in rows:
            self._add_tracker_row(row)

        # Walk the nameless ones one at a time. Cancelling stops the walk but keeps
        # everything already attached — a half-finished import is still progress.
        named_count = len(rows)
        for cap in pending:
            added = self._attach_names_to_capture(cap, ti)
            if added is None:          # Dane cancelled
                break
            named_count += added

        self._update_batch()

        archived = ti.archive_capture(found) if named_count else None
        messagebox.showinfo(
            "Imported",
            f"{named_count} encounter(s) added to the batch.\n\n"
            + (f"The capture file was renamed to\n{os.path.basename(archived)}\n"
               f"so the same encounters can't be imported twice."
               if archived else
               "The capture file was left in place."))

    def _add_tracker_row(self, row):
        """Add one imported row as its own group of one."""
        self.groups.append({
            "rows": [row],
            "label": (f"  1 person  ·  {row['coaching_type']}"
                      f"{'  ·  ' + row['details'] if row['details'] else ''}"
                      f"  ·  {row['date'] or 'today'}  ·  {row['employee']}"
                      f"   [Tracker Lite]"),
        })

    def _attach_names_to_capture(self, cap, ti):
        """Ask who a nameless capture was about. Returns rows added, or None if cancelled.

        The roster list is pre-filtered to the shift the capture was made on, because
        that is the one thing the phone CAN say without naming anybody, and it cuts 261
        names down to the ~100 who were actually there.
        """
        win = tk.Toplevel(self)
        win.title("Who was this encounter with?")
        win.configure(bg=UI_BG)
        win.transient(self)
        win.grab_set()

        want = cap["group_size"]
        head = (f"{cap['date']}   ·   {cap['coaching_type'] or 'no coaching type'}"
                + (f"   ·   {cap['shift']} shift" if cap["shift"] else ""))
        tk.Label(win, text=head, bg=UI_BG, fg=UI_TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(win, text=(f"Pick {want} " + ("person" if want == 1 else "people")
                            + (f"  ·  captured on {cap['shift']} shift"
                               if cap["shift"] else "")),
                 bg=UI_BG, fg=UI_MUTED).pack(anchor="w", padx=14)
        if cap["details"]:
            tk.Label(win, text=f"Details: {cap['details']}", bg=UI_BG, fg=UI_MUTED,
                     wraplength=520, justify="left").pack(anchor="w", padx=14, pady=(4, 0))
        if cap["description"]:
            tk.Label(win, text=cap["description"], bg=UI_BG, fg=UI_TEXT, wraplength=520,
                     justify="left").pack(anchor="w", padx=14, pady=(6, 0))
        elif "description" in cap["needs"]:
            tk.Label(win, text="No description yet — add it in the form after importing.",
                     bg=UI_BG, fg=UI_MUTED).pack(anchor="w", padx=14, pady=(6, 0))

        search_var = tk.StringVar()
        shift_only = tk.BooleanVar(value=bool(cap["shift"]))
        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=14, pady=(10, 4))
        ttk.Entry(bar, textvariable=search_var, width=30).pack(side="left")
        if cap["shift"]:
            ttk.Checkbutton(bar, text=f"only {cap['shift']} shift",
                            variable=shift_only).pack(side="left", padx=8)
        chosen_lbl = tk.Label(win, text="", bg=UI_BG, fg=CHECK_FG,
                              font=("Segoe UI", 11, "bold"))
        chosen_lbl.pack(anchor="w", padx=14)

        listbox = tk.Listbox(win, selectmode="extended", height=14, width=52,
                             bg=UI_CARD, fg=UI_TEXT, highlightthickness=0,
                             selectbackground=CHECK_FG, activestyle="none")
        listbox.pack(fill="both", expand=True, padx=14, pady=4)

        shown = []

        def refresh(*_):
            needle = search_var.get().strip().lower()
            shown.clear()
            for p in self.people:
                if shift_only.get() and cap["shift"] and p["shift"] != cap["shift"]:
                    continue
                if needle and needle not in p["name"].lower():
                    continue
                shown.append(p)
            listbox.delete(0, tk.END)
            for p in shown:
                extra = " · ".join(x for x in (p["dept"], p["shift"]) if x)
                listbox.insert(tk.END, f"{p['name']}    {extra}")
            update_count()

        def update_count(*_):
            n = len(listbox.curselection())
            chosen_lbl.config(
                text=f"{n} of {want} selected" + ("  ✓" if n == want else ""))

        search_var.trace_add("write", refresh)
        shift_only.trace_add("write", refresh)
        listbox.bind("<<ListboxSelect>>", update_count)
        refresh()

        result = {"added": None}

        def do_add():
            picks = [shown[i]["name"] for i in listbox.curselection()]
            if not picks:
                messagebox.showwarning("Pick someone",
                                       "Select at least one person.", parent=win)
                return
            if len(picks) != want and not messagebox.askyesno(
                    "Different number of people",
                    f"This capture says {want} " + ("person" if want == 1 else "people")
                    + f", but you picked {len(picks)}.\n\nUse {len(picks)}?",
                    parent=win):
                return
            pairs, unmatched = ti.resolve_pending(cap, picks, self.people)
            new_rows = ti.to_builder_rows(
                pairs, encounter_type=self.etype_var.get(), category=self.cat_var.get())
            for r in new_rows:
                self._add_tracker_row(r)
            result["added"] = len(new_rows)
            win.destroy()

        def do_skip():
            result["added"] = 0
            win.destroy()

        foot = ttk.Frame(win)
        foot.pack(fill="x", padx=14, pady=(4, 12))
        ttk.Button(foot, text="Add to batch", style="Accent.TButton",
                   command=do_add).pack(side="left")
        ttk.Button(foot, text="Skip this one", command=do_skip).pack(side="left", padx=6)
        ttk.Button(foot, text="Stop importing",
                   command=win.destroy).pack(side="right")

        win.update_idletasks()
        win.geometry(f"+{self.winfo_rootx() + 80}+{self.winfo_rooty() + 60}")
        self.wait_window(win)
        return result["added"]

        # Archive so the same encounters can't be pulled in twice. Renamed, not deleted.
        archived = ti.archive_capture(found)
        messagebox.showinfo(
            "Imported",
            f"{len(rows)} capture(s) added to the batch.\n\n"
            + (f"The capture file was renamed to\n{os.path.basename(archived)}\n"
               f"so the same encounters can't be imported twice."
               if archived else
               "NOTE: the capture file could not be renamed — delete or move it "
               "yourself, or the next import will add these again."))

    def _encounter_fields(self):
        """Validate and read the encounter fields both add paths share.
        Returns (raw_date, details, description), or None after showing a warning."""
        if self.type_var.get() == PICK_ONE:
            messagebox.showwarning(
                "Coaching type",
                "Pick a coaching type.\n\nIt is the clinical classification of the "
                "encounter and this tool will not guess it for you.")
            return None
        raw_date = self.date_var.get().strip()
        if raw_date:
            try:
                datetime.strptime(raw_date, "%m/%d/%Y")
            except ValueError:
                messagebox.showwarning("Date", f"'{raw_date}' isn't MM/DD/YYYY.")
                return None
        description = self.desc_text.get("1.0", "end-1c").strip()
        if not description:
            messagebox.showwarning(
                "Description",
                "Say what the note is about first — a topic is enough."
                if self.note_var.get() else
                "Write or pick a description first.")
            return None
        details = "; ".join(sorted(n for n, v in self.detail_vars.items() if v.get()))
        return raw_date, details, description

    def _make_row(self, name, raw_date, details, description, per_employee):
        person = self.by_name[name]
        return {
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
        }

    def _add_group(self):
        if not self.checked:
            messagebox.showwarning("No one checked", "Check at least one name first.")
            return
        fields = self._encounter_fields()
        if not fields:
            return
        raw_date, details, description = fields
        per_employee = self.loc_mode.get() == "per_employee"
        rows = [self._make_row(n, raw_date, details, description, per_employee)
                for n in sorted(self.checked, key=str.lower)]
        where = "per employee" if per_employee else (self.dept_var.get() or "no dept")
        self.groups.append({
            "rows": rows,
            "pending": self._group_pending(description),
            "label": (f"{len(rows):>3} people  ·  {self.type_var.get()}"
                      f"{'  ·  ' + details if details else ''}"
                      f"  ·  {raw_date or 'today'}  ·  {where}"),
        })
        self._clear_all()
        self.note_var.set(False)
        self._update_batch()

    def _add_single(self):
        """Individual mode: add the loaded person as a group of one, then clear for the
        next entry. Date / encounter type / prompted / category / coaching type carry
        forward; only the person, description and detail ticks reset."""
        if len(self.checked) != 1:
            messagebox.showwarning(
                "Pick a person",
                "Click one name in the list to load them, then Add & Next.")
            return
        fields = self._encounter_fields()
        if not fields:
            return
        raw_date, details, description = fields
        name = next(iter(self.checked))
        row = self._make_row(name, raw_date, details, description, per_employee=True)
        self.groups.append({
            "rows": [row],
            "pending": self._group_pending(description),
            "label": (f"  1 person  ·  {self.type_var.get()}"
                      f"{'  ·  ' + details if details else ''}"
                      f"  ·  {raw_date or 'today'}  ·  {name}"),
        })
        # Reset only the per-person bits; leave the carried-forward fields alone.
        # The note switch belongs to the description, so it resets with it.
        self.checked.clear()
        self.note_var.set(False)
        self.desc_text.delete("1.0", tk.END)
        for v in self.detail_vars.values():
            v.set(False)
        self.details_section.refresh()     # the folded header must not show last person's
        self.filter_var.set("")            # clear the search so the next name types fresh
        self._refresh_list()
        self._update_batch()
        self.find_entry.focus_set()

    def _on_mode(self):
        """Switch the panels between the entry modes."""
        mode = self.mode.get()
        # The filter block is group machinery — restore it for every mode but individuals.
        if mode != "individuals":
            for w in self._roster_individual_hide:
                w.grid()
            self.checked_only_box.pack(side="left", padx=(8, 0))
        if mode == "pool":
            # Roll call first: the roster panel keeps its bulk-check controls (you are
            # checking many people), but the encounter form is for the SUBSET you pick
            # out of the pool, not for everyone checked.
            for w in self._roster_group_only:
                w.grid()
            self.loc_mode.set("per_employee")
            self._on_loc_mode()
            for w in self._loc_section_widgets:
                w.grid_remove()
            self.add_btn.config(text="Add checked to pool →", command=self._fill_pool)
            self.group_frame.config(text="Shift Pool  ·  sort the people you saw")
            self.mode_hint.config(text="check who you saw → sort them by type")
            self.roster_hint.config(
                text="Check everyone you had an encounter with this shift, then "
                     "'Add checked to pool'. Sort them into coaching types from the "
                     "pool window — each one leaves the pool as you assign it.")
            self._refresh_list()
            self._update_count()
            self._show_pool_window()
            return

        individuals = mode == "individuals"
        if individuals:
            # A single is always located to that person's own roster record — force
            # per-employee and hide the location chooser and the bulk-check controls.
            self.loc_mode.set("per_employee")
            self._on_loc_mode()
            for w in (self._loc_section_widgets + self._roster_group_only
                      + self._roster_individual_hide):
                w.grid_remove()
            # 'checked only' is packed, not gridded, so it needs its own manager's forget.
            self.checked_only.set(False)
            self.checked_only_box.pack_forget()
            if len(self.checked) > 1:       # individual mode holds exactly one
                self.checked.clear()
            self.add_btn.config(text="Add & Next", command=self._add_single)
            self.group_frame.config(
                text="One encounter, one person  ·  Add & Next (Ctrl+Enter)")
            self.mode_hint.config(text="click a name → fill it → Add & Next")
            self.roster_hint.config(
                text="Click a person to load them into the form; set the encounter, "
                     "then Add & Next (or Ctrl+Enter). The date, type, prompted-by and "
                     "category carry over to the next one.")
        else:
            for w in self._loc_section_widgets + self._roster_group_only:
                w.grid()
            self._on_loc_mode()             # re-hide group_loc if per-employee
            self.add_btn.config(text="Add group to batch", command=self._add_group)
            self.group_frame.config(
                text="What was the encounter? (applies to everyone checked)")
            self.mode_hint.config(text="check many → one shared encounter")
            self.roster_hint.config(
                text="Click a name to check it (checked = green). 'checked only' "
                     "reviews your pick. Hidden areas/shifts are remembered between runs.")
        self._refresh_list()
        self._update_count()

    # ── Shift Pool ────────────────────────────
    # Roll call, then sort. The old flow made you find each person in a 261-name list
    # once per coaching type, because the roster cleared after every group. Here you
    # find everyone once, then work a short list down to nothing.

    def _fill_pool(self):
        """Move everyone currently checked into the pool."""
        if not self.checked:
            messagebox.showwarning(
                "No one checked",
                "Check the people you had an encounter with this shift, then add them "
                "to the pool.")
            return
        added = [n for n in sorted(self.checked, key=str.lower) if n not in self.pool]
        self.pool.extend(added)
        # Remember the shift if the roll call was taken with a single shift showing —
        # it is only a label, so a mixed selection just leaves it blank rather than
        # claiming a shift that isn't true of everyone.
        shifts = {self.by_name[n]["shift"] for n in self.pool if n in self.by_name}
        self.pool_shift = next(iter(shifts)) if len(shifts) == 1 else ""
        self.checked.clear()
        self._refresh_list()
        self._update_count()
        self._show_pool_window()

    def _show_pool_window(self):
        """Open (or re-focus) the sorting window."""
        existing = getattr(self, "pool_win", None)
        if existing is not None and existing.winfo_exists():
            self._refresh_pool_list()
            existing.deiconify()
            existing.lift()
            return

        win = tk.Toplevel(self)
        self.pool_win = win
        win.title("Shift Pool — sort by coaching type")
        win.configure(bg=UI_BG)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)   # hide, never lose the pool

        self.pool_head = tk.Label(win, text="", bg=UI_BG, fg=UI_TEXT,
                                  font=("Segoe UI", 13, "bold"))
        self.pool_head.pack(anchor="w", padx=14, pady=(12, 0))
        tk.Label(win, text="Select the people who had the SAME encounter, choose the "
                           "type, then Assign. They leave the pool.",
                 bg=UI_BG, fg=UI_MUTED, wraplength=460,
                 justify="left").pack(anchor="w", padx=14, pady=(2, 6))

        self.pool_list = tk.Listbox(win, selectmode="extended", height=16, width=46,
                                    bg=UI_CARD, fg=UI_TEXT, highlightthickness=0,
                                    selectbackground=CHECK_FG, activestyle="none",
                                    font=("Segoe UI", 11))
        self.pool_list.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        picker = ttk.Frame(win)
        picker.pack(fill="x", padx=14)
        ttk.Label(picker, text="Coaching type:").pack(side="left", padx=(0, 6))
        self.pool_type = tk.StringVar(value=PICK_ONE)
        # Same list the main form's radios use, so the two can never disagree about
        # what a valid coaching type is.
        ttk.Combobox(picker, textvariable=self.pool_type, state="readonly", width=34,
                     values=[PICK_ONE] + list(COACHING_TYPES)).pack(side="left")

        sel = ttk.Frame(win)
        sel.pack(fill="x", padx=14, pady=(6, 0))
        ttk.Button(sel, text="Select all", width=10,
                   command=lambda: self.pool_list.select_set(0, tk.END)).pack(side="left")
        ttk.Button(sel, text="Clear", width=8,
                   command=lambda: self.pool_list.selection_clear(0, tk.END)
                   ).pack(side="left", padx=4)
        self.pool_sel_lbl = tk.Label(sel, text="", bg=UI_BG, fg=CHECK_FG,
                                     font=("Segoe UI", 10, "bold"))
        self.pool_sel_lbl.pack(side="left", padx=8)
        self.pool_list.bind("<<ListboxSelect>>", lambda e: self._update_pool_sel())

        foot = ttk.Frame(win)
        foot.pack(fill="x", padx=14, pady=(8, 12))
        ttk.Button(foot, text="Assign selected →", style="Accent.TButton",
                   command=self._assign_from_pool).pack(side="left")
        ttk.Button(foot, text="Put back on roster",
                   command=self._return_to_roster).pack(side="left", padx=6)
        ttk.Button(foot, text="Close", command=win.withdraw).pack(side="right")

        self._refresh_pool_list()
        win.update_idletasks()
        win.geometry(f"+{self.winfo_rootx() + 250}+{self.winfo_rooty() + 90}")

    def _refresh_pool_list(self):
        if not getattr(self, "pool_win", None) or not self.pool_win.winfo_exists():
            return
        self.pool_list.delete(0, tk.END)
        for name in self.pool:
            p = self.by_name.get(name, {})
            extra = " · ".join(x for x in (p.get("dept", ""), p.get("shift", "")) if x)
            self.pool_list.insert(tk.END, f"{name}    {extra}")
        shift = f"{self.pool_shift} shift  ·  " if self.pool_shift else ""
        self.pool_head.config(
            text=f"{shift}{len(self.pool)} still to sort"
                 if self.pool else "Pool empty — everyone is accounted for")
        self._update_pool_sel()

    def _update_pool_sel(self):
        if getattr(self, "pool_sel_lbl", None):
            n = len(self.pool_list.curselection())
            self.pool_sel_lbl.config(text=f"{n} selected" if n else "")

    def _pool_picks(self):
        return [self.pool[i] for i in self.pool_list.curselection()]

    def _assign_from_pool(self):
        """Assign the selected people one shared encounter, then drop them from the pool."""
        picks = self._pool_picks()
        if not picks:
            messagebox.showwarning("Nobody selected",
                                   "Select the people who had the same encounter.",
                                   parent=self.pool_win)
            return
        if self.pool_type.get() == PICK_ONE:
            messagebox.showwarning(
                "Coaching type",
                "Pick the coaching type for these people.\n\nIt is the clinical "
                "classification of the encounter and this tool will not guess it.",
                parent=self.pool_win)
            return

        # Drive the main form so validation, the description box and the detail ticks
        # behave exactly as they do everywhere else — one definition of a valid
        # encounter, not a second one living in this window.
        self.type_var.set(self.pool_type.get())
        self._on_type_change()
        # The type came from the pool window, so the main form's type block is already
        # settled — fold it and open Details, which is what the popup below tells him to
        # go and fill in.
        self.type_section.collapse()
        self.details_section.expand()
        self.pool_win.withdraw()
        messagebox.showinfo(
            "Finish this encounter",
            f"{len(picks)} " + ("person" if len(picks) == 1 else "people")
            + f" · {self.pool_type.get()}\n\n"
              "Fill in the description and any detail boxes in the main window, then "
              "press “Assign group”.")

        self.checked = set(picks)
        self._pending_pool = picks
        self.add_btn.config(text=f"Assign group ({len(picks)})",
                            command=self._commit_pool_group)
        self._refresh_list()
        self._update_count()
        self.desc_text.focus_set()

    def _commit_pool_group(self):
        """Second half of an assignment: the form is filled, make the group."""
        picks = getattr(self, "_pending_pool", None)
        if not picks:
            return self._fill_pool()
        fields = self._encounter_fields()
        if not fields:
            return
        raw_date, details, description = fields
        rows = [self._make_row(n, raw_date, details, description, per_employee=True)
                for n in picks]
        self.groups.append({
            "rows": rows,
            "pending": self._group_pending(description),
            "label": (f"{len(rows):>3} people  ·  {self.type_var.get()}"
                      f"{'  ·  ' + details if details else ''}"
                      f"  ·  {raw_date or 'today'}  ·  from shift pool"),
        })
        for n in picks:
            if n in self.pool:
                self.pool.remove(n)
        self._pending_pool = None
        self.checked.clear()
        self.note_var.set(False)
        self.desc_text.delete("1.0", tk.END)
        for v in self.detail_vars.values():
            v.set(False)
        self.add_btn.config(text="Add checked to pool →", command=self._fill_pool)
        self._refresh_list()
        self._update_count()
        self._update_batch()
        self._show_pool_window()
        if not self.pool:
            messagebox.showinfo(
                "Pool cleared",
                "Everyone from that roll call is accounted for.\n\n"
                "Check more names on the roster to start another pool, or write the "
                "batch.", parent=self.pool_win)

    def _return_to_roster(self):
        """Take people back out of the pool without assigning them anything."""
        picks = self._pool_picks()
        if not picks:
            return
        for n in picks:
            self.pool.remove(n)
        self._refresh_pool_list()
        self._update_count()

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

    @staticmethod
    def _group_summary(group):
        """The display facts for one group, read back off its rows (item 3).

        Everything except department/shift is set once per group, so row 0 carries it.
        Department/division/shift may differ per person (the per-employee mode), so
        report the distinct set: one value if uniform, 'per employee' if it varies.
        """
        rows = group["rows"]
        r0 = rows[0]
        spec = group.get("pending") or {}
        waiting = [w for w, on in (("description", spec.get("description")),
                                   ("coaching type", spec.get("coaching_type"))) if on]
        depts = {r["department"] or "—" for r in rows}
        shifts = {r["shift"] or "—" for r in rows}
        where = next(iter(depts)) if len(depts) == 1 else "per employee"
        shift = next(iter(shifts)) if len(shifts) == 1 else "per employee"
        return {
            "count": len(rows),
            "names": [r["employee"] for r in rows],
            "coaching_type": r0["coaching_type"],
            "encounter_type": r0["encounter_type"],
            "date": r0["date"] or "today",
            "category": r0["category"] or "—",
            "prompted": r0["what_prompted"],
            "details": r0["details"],
            "description": r0["description"],
            "note_only": bool(spec.get("description")),
            "pending": ("Claude writes the " + " and the ".join(waiting)
                        + " when you write the batch" if waiting else ""),
            "where": where,
            "shift": shift,
        }

    def _review_batch(self):
        """See every group as a readable card — who's in it and exactly what was
        recorded — and delete any of them, not just the last (item 3)."""
        if getattr(self, "review_win", None) and self.review_win.winfo_exists():
            self.review_win.lift()
            return
        win = tk.Toplevel(self)
        self.review_win = win
        win.title("Batch — review before entering")
        win.geometry("860x620")
        win.configure(bg=UI_BG)
        win.transient(self)
        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)

        ttk.Label(win, text="Every group you've added, with who's in it and what will "
                            "be entered for them. Delete any group; the rest are "
                            "untouched.",
                  foreground=UI_MUTED, wraplength=820).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 6))

        canvas = tk.Canvas(win, highlightthickness=0, bg=UI_BG)
        canvas.grid(row=1, column=0, sticky="nsew", padx=(12, 0))
        vsb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vsb.set)
        self.review_inner = ttk.Frame(canvas)
        cwin = canvas.create_window((0, 0), window=self.review_inner, anchor="nw")
        self.review_inner.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        bar = ttk.Frame(win, padding=(12, 8))
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.review_total = ttk.Label(bar, text="", font=("Segoe UI", 11, "bold"))
        self.review_total.pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        self._fill_review()

    def _fill_review(self):
        inner = self.review_inner
        for child in inner.winfo_children():
            child.destroy()
        WRAP = 760

        if not self.groups:
            ttk.Label(inner, text="Nothing in the batch yet.",
                      foreground=UI_MUTED).pack(anchor="w", padx=12, pady=16)

        for i, group in enumerate(self.groups):
            s = self._group_summary(group)
            card = tk.Frame(inner, bg=UI_CARD, highlightbackground=UI_BORDER,
                            highlightthickness=1, bd=0, padx=14, pady=11)
            card.pack(fill="x", expand=True, padx=(0, 12), pady=6)
            card.columnconfigure(0, weight=1)

            head = tk.Frame(card, bg=UI_CARD)
            head.grid(row=0, column=0, sticky="ew")
            head.columnconfigure(0, weight=1)
            tk.Label(head, text=f"{s['count']} people  ·  {s['coaching_type']}",
                     bg=UI_CARD, fg=UI_TEXT, font=("Segoe UI", 12, "bold")).grid(
                row=0, column=0, sticky="w")
            ttk.Button(head, text="Delete", width=8,
                       command=lambda idx=i: self._confirm_delete(idx)).grid(
                row=0, column=1, sticky="e")

            meta = (f"{s['date']}  ·  {s['encounter_type']}  ·  {s['prompted']}"
                    f"  ·  Dept: {s['where']}  ·  Shift: {s['shift']}"
                    f"  ·  {s['category']}")
            tk.Label(card, text=meta, bg=UI_CARD, fg=UI_MUTED, wraplength=WRAP,
                     justify="left", font=("Segoe UI", 10)).grid(
                row=1, column=0, sticky="w", pady=(4, 0))

            if s["details"]:
                tk.Label(card, text=f"Details: {s['details']}", bg=UI_CARD, fg=UI_TEXT,
                         wraplength=WRAP, justify="left", font=("Segoe UI", 10)).grid(
                    row=2, column=0, sticky="w", pady=(4, 0))

            tk.Label(card,
                     text=(f"Note:  {s['description']}" if s["note_only"]
                           else s["description"]),
                     bg=UI_CARD, fg=UI_TEXT, wraplength=WRAP,
                     justify="left", font=("Segoe UI", 11)).grid(
                row=3, column=0, sticky="w", pady=(6, 2))

            if s["pending"]:
                tk.Label(card, text="⌛  " + s["pending"], bg=UI_CARD,
                         fg=UI_ACCENT_TEXT, wraplength=WRAP, justify="left",
                         font=("Segoe UI", 10, "bold")).grid(
                    row=5, column=0, sticky="w", pady=(6, 0))

            tk.Label(card, text="Who:  " + "   ".join(s["names"]), bg=UI_CARD,
                     fg=CHECK_FG, wraplength=WRAP, justify="left",
                     font=("Segoe UI", 10)).grid(row=4, column=0, sticky="w", pady=(4, 0))

        self.review_total.config(
            text=f"{len(self.batch)} encounter(s) in {len(self.groups)} group(s)")

    def _confirm_delete(self, index):
        if not (0 <= index < len(self.groups)):
            return
        s = self._group_summary(self.groups[index])
        if messagebox.askyesno(
                "Remove group?",
                f"Remove this group — {s['count']} encounter(s)?\n\n"
                f"{s['coaching_type']}  ·  {s['date']}\n\n"
                f"The other groups stay as they are.",
                parent=self.review_win):
            self._delete_group(index)

    # ── notes → descriptions ──────────────────
    #
    # The only place this tool talks to anything but the EMR. Dane types what he wants
    # said — "hydration and magnesium" — ticks "Note only", and at write time the whole
    # batch goes out in ONE headless `claude -p` call (cost tracks invocations, not rows:
    # the measurement is in intake_runner's docstring).
    #
    # WHAT CROSSES THE LINE
    #     A job is the note, how many people the group covers, and the coaching type.
    #     No name, no date, no department, no shift, no identifier. The map from a job
    #     back to the people in it is the group's position in this list and it never
    #     leaves the process. Nothing here is a new exception to the PHI boundary — it is
    #     ENCOUNTER_INTAKE.md's de-identified handover with the spreadsheet taken out.
    #
    # WHAT COMES BACK IS NOT TRUSTED
    #     A suggested coaching type is checked against COACHING_TYPE_UUIDS before it can
    #     reach a row. Detail checkboxes, encounter type, category, department and shift
    #     are never asked for and never accepted: Dane sets those himself.

    _NAME_MIN = 3

    def _roster_name_tokens(self):
        """Every name part on the loaded roster, lowercased.

        An allowlist of REAL names, not a pattern for name-shaped words. A regex would
        wave through the one surname that mattered and trip on "Rest"; this can only
        ever be wrong about words that genuinely are somebody's name.
        """
        tokens = set()
        for full in self.by_name:
            for part in re.split(r"[^A-Za-z]+", full):
                if len(part) >= self._NAME_MIN:
                    tokens.add(part.lower())
        return tokens

    def _notes_naming_people(self, pending):
        """(group index, the word) for every note carrying a roster name.

        ENCOUNTER_INTAKE.md concedes that Claude cannot make this check — by the time it
        could look, it has already read the note. In here it can: the roster is in memory
        and the check happens before anything is sent. The word is shown because this is
        Dane's screen and the roster is already on it, and because seeing it is what makes
        a surname that is also an ordinary word obvious in one glance.
        """
        tokens = self._roster_name_tokens()
        hits = []
        for idx, group in pending:
            for word in re.findall(r"[A-Za-z][A-Za-z'\-]*",
                                   group["pending"]["note"]):
                if len(word) >= self._NAME_MIN and word.lower() in tokens:
                    hits.append((idx, word))
                    break
        return hits

    def _group_pending(self, description):
        """What still has to be written for the group being added, or None.

        Group-level, never row-level. The row dicts ARE the CSV rows — DictWriter is
        built from ace.CSV_COLUMNS — so an extra key on a row would either raise or
        invent a column the EMR has never heard of. This dies with the batch.
        """
        needs_desc = bool(self.note_var.get())
        needs_type = self.type_var.get() == SUGGEST_TYPE
        if not (needs_desc or needs_type):
            return None
        return {"note": description, "description": needs_desc,
                "coaching_type": needs_type}

    def _library_examples(self, coaching_type, limit=4):
        """Real descriptions already in use, sent as the scale to write to.

        The workbook is the measurement; a rubric written from scratch would be a guess
        about what a coaching type's description should cover. For a known type they come
        from that type's own tab. For a suggestion there is no tab yet, so a thin spread
        across tabs carries the voice without implying a category.
        """
        if not self.library:
            return []
        tabs = sorted({e["tab"] for e in self.library})
        if coaching_type:
            tab = library_category_for(coaching_type, tabs)
            if not tab:
                return []
            return [e["text"] for e in self.library if e["tab"] == tab][:limit]
        seen, spread = set(), []
        for entry in self.library:
            if entry["tab"] in seen:
                continue
            seen.add(entry["tab"])
            spread.append(entry["text"])
            if len(spread) >= 8:
                break
        return spread

    def _run_with_progress(self, jobs, options):
        """Run the batch on a worker thread. Returns the results, or None after showing
        why it failed.

        Threaded because the call is a subprocess that can run for minutes and a frozen
        window reads as a crash. Tk must not be touched from the worker, so progress
        comes back over a queue and is drawn here.
        """
        try:
            import intake_runner
        except Exception as exc:        # not installed, or broken — say so, write nothing
            messagebox.showerror(
                "Nothing was written",
                f"intake_runner.py could not be loaded, so the notes could not be "
                f"turned into descriptions and encounters.csv was left exactly as it "
                f"was.\n\n{exc}")
            return None

        win = tk.Toplevel(self)
        win.title("Writing descriptions")
        win.configure(bg=UI_BG)
        win.resizable(False, False)
        win.transient(self)
        win.protocol("WM_DELETE_WINDOW", lambda: None)   # not closable mid-call
        tk.Label(win, text="Writing the descriptions…", bg=UI_BG, fg=UI_TEXT,
                 font=("Segoe UI", 12, "bold")).pack(padx=26, pady=(20, 2))
        tk.Label(win, text=f"{len(jobs)} group(s), one call.", bg=UI_BG, fg=UI_MUTED,
                 font=("Segoe UI", 10)).pack(padx=26)
        status = tk.Label(win, text="Starting…", bg=UI_BG, fg=UI_MUTED, width=46,
                          font=("Segoe UI", 10))
        status.pack(padx=26, pady=(8, 0))
        bar = ttk.Progressbar(win, mode="indeterminate", length=330)
        bar.pack(padx=26, pady=(8, 22))
        bar.start(12)
        win.update_idletasks()
        win.geometry("+%d+%d" % (
            self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2,
            self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 3))
        win.grab_set()

        box = queue.Queue()

        def work():
            try:
                box.put(("done", intake_runner.run_coaching(
                    jobs, options, on_progress=lambda m: box.put(("msg", m)))))
            except Exception as exc:        # RunnerError, or anything unforeseen
                box.put(("fail", exc))

        threading.Thread(target=work, daemon=True).start()

        out = {}

        def poll():
            try:
                while True:
                    kind, payload = box.get_nowait()
                    if kind == "msg":
                        status.config(text=payload)
                        continue
                    out["kind"], out["payload"] = kind, payload
                    win.destroy()
                    return
            except queue.Empty:
                pass
            win.after(120, poll)

        win.after(120, poll)
        self.wait_window(win)

        if out.get("kind") != "done":
            messagebox.showerror(
                "Nothing was written",
                f"The descriptions could not be written, so encounters.csv was left "
                f"exactly as it was.\n\n{out.get('payload')}")
            return None
        return out["payload"]

    def _resolve_pending(self):
        """Turn every note into a description and every suggestion into an EMR value.

        Returns True when the batch is ready to write. A batch is ALL-OR-NOTHING here:
        if one job comes back short, nothing is written. A note is not a description and
        the sentinel is not a coaching type, and neither of them belongs in a medical
        record because a run was half successful. Groups that did resolve keep their
        text, so pressing Write again re-sends only what is still outstanding.
        """
        pending = [(i, g) for i, g in enumerate(self.groups) if g.get("pending")]
        if not pending:
            return True

        hits = self._notes_naming_people(pending)
        if hits and not messagebox.askyesno(
                "A note has a name in it",
                "These notes contain a word that is also a name on the roster:\n\n"
                + "\n".join(f"      Group {i + 1} — \u201c{w}\u201d" for i, w in hits)
                + "\n\nThe note is the only thing that gets sent — the names in the "
                  "batch never leave this window. If one of those words is a person, "
                  "cancel and reword the note.\n\nSend anyway?",
                icon="warning"):
            return False

        jobs = []
        for i, group in pending:
            spec = group["pending"]
            chosen = group["rows"][0]["coaching_type"]
            jobs.append({
                "ref": i + 1,
                "note": spec["note"],
                "people": len(group["rows"]),
                "write_description": spec["description"],
                "suggest_type": spec["coaching_type"],
                "coaching_type": "" if spec["coaching_type"] else chosen,
                "examples": self._library_examples(
                    None if spec["coaching_type"] else chosen),
            })

        results = self._run_with_progress(jobs, COACHING_TYPES)
        if results is None:
            return False

        short = []
        for i, group in pending:
            spec = group["pending"]
            item = results.get(i + 1) or {}
            desc = (item.get("description") or "").strip()
            ctype = (item.get("coaching_type") or "").strip()

            if spec["description"] and not desc:
                short.append((i, "no description came back"))
                continue
            if spec["coaching_type"] and ctype not in ace.COACHING_TYPE_UUIDS:
                short.append((i, "it could not settle on a coaching type" if not ctype
                              else "the coaching type it gave is not an EMR value"))
                continue

            for row in group["rows"]:
                if spec["description"]:
                    row["description"] = desc
                if spec["coaching_type"]:
                    row["coaching_type"] = ctype
            if spec["coaching_type"]:
                group["label"] = group["label"].replace(SUGGEST_TYPE, ctype)
            group["pending"] = None

        self._update_batch()

        if short:
            messagebox.showerror(
                "Nothing was written",
                "These groups came back incomplete, so encounters.csv was left "
                "exactly as it was:\n\n"
                + "\n".join(f"      Group {i + 1} — {why}" for i, why in short)
                + "\n\nFill them in yourself, or reword the note and press Write "
                  "again — only the outstanding ones get sent.")
            return False
        return True

    def _write_csv(self):
        if not self.batch:
            messagebox.showwarning("Empty batch", "Add a group first.")
            return
        # Notes become descriptions and suggested types become EMR values HERE, before
        # the file exists. If any of it fails, encounters.csv is left exactly as it was.
        if not self._resolve_pending():
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

    # ─────────────────────────────────────────
    # CASE LIST REPORT TAB
    # ─────────────────────────────────────────

    def _build_report_tab(self):
        """Pick a date range, pick a format, get a report of what's already in the EMR.

        The reverse direction from the rest of this window: everything else puts
        encounters IN, this reads them back out. It runs READ-ONLY (see case_report),
        and like the batch entry it goes out to its own console process — the browser
        pauses on Windows dialogs for login and worksite, and those want a real
        terminal behind them, not a frozen Tk window.
        """
        tab = self.report_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)          # the note block takes the slack

        today = date.today()
        self.rep_from = tk.StringVar(value=today.replace(day=1).strftime("%m/%d/%Y"))
        self.rep_to = tk.StringVar(value=today.strftime("%m/%d/%Y"))
        self.rep_format = tk.StringVar(value="xlsx")

        # ── dates ──
        dates = ttk.LabelFrame(tab, text=_legend("Which dates?"), padding=(10, 8))
        dates.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 6))

        line = ttk.Frame(dates)
        line.grid(row=0, column=0, sticky="w")
        for i, (label, var) in enumerate((("From", self.rep_from), ("To", self.rep_to))):
            ttk.Label(line, text=label).pack(side="left", padx=(0 if i == 0 else 22, 6))
            ent = ttk.Entry(line, textvariable=var, width=12, state="readonly")
            ent.pack(side="left")
            ent.bind("<Button-1>", lambda e, v=var: self._open_calendar(v))
            ttk.Button(line, text="📅", width=4,
                       command=lambda v=var: self._open_calendar(v)).pack(side="left",
                                                                          padx=(6, 0))
        ttk.Label(dates, text="Both ends are included. The date used is the "
                              "Date of Encounter on the record.",
                  foreground=UI_MUTED).grid(row=1, column=0, sticky="w", pady=(6, 0))

        quick = ttk.Frame(dates)
        quick.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(quick, text="Quick:").pack(side="left", padx=(0, 8))
        for label, span in (("This week", "this_week"), ("Last week", "last_week"),
                            ("This month", "this_month"), ("Last month", "last_month"),
                            ("Today", "today")):
            ttk.Button(quick, text=label,
                       command=lambda s=span: self._report_preset(s)).pack(side="left",
                                                                           padx=(0, 4))

        # ── format ──
        fmt = ttk.LabelFrame(tab, text=_legend("What should it be?"), padding=(10, 8))
        fmt.grid(row=1, column=0, sticky="ew", padx=8, pady=6)
        row = ttk.Frame(fmt)
        row.grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="File:").pack(side="left", padx=(0, 10))
        for label, val in (("Excel (.xlsx)", "xlsx"), ("Word (.docx)", "docx"),
                           ("Both", "both")):
            ttk.Radiobutton(row, text=label, value=val, variable=self.rep_format,
                            style="Radio10.TRadiobutton").pack(side="left", padx=(0, 16))
        ttk.Label(fmt, text="Grouped by date, then case type, then coaching type — "
                            "names alphabetised inside each group.\n"
                            "Excel also gets a flat, filterable sheet and a summary "
                            "of the counts.",
                  foreground=UI_MUTED, justify="left").grid(row=1, column=0, sticky="w",
                                                            pady=(6, 0))

        # ── whose cases ──
        # Not optional. The EMR mixes other specialists' cases into the list, out of
        # order, and that is what made the 2026-09-08 run walk forever — the reader
        # ticks this name in the Specialists filter before it reads anything.
        who = ttk.Frame(fmt)
        who.grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Label(who, text="Specialist:").pack(side="left", padx=(0, 10))
        self.rep_specialist = tk.StringVar(value=load_specialist())
        ttk.Entry(who, textvariable=self.rep_specialist, width=28).pack(side="left")
        ttk.Label(who, text="as the EMR's Specialists filter spells it — remembered "
                            "between runs",
                  foreground=UI_MUTED).pack(side="left", padx=(10, 0))

        # ── actions ──
        bar = ttk.Frame(tab, padding=(8, 4))
        bar.grid(row=2, column=0, sticky="ew")
        ttk.Button(bar, text="Build the report", style="Accent.TButton",
                   command=self._run_report).pack(side="left")
        # The finished file opens itself, but a run from an earlier day is otherwise a
        # trip into the project folder to find — which is exactly what Dane didn't want
        # (2026-09-08). This reopens the newest one without leaving the window.
        self.rep_open_btn = ttk.Button(bar, text="Open last report",
                                       command=self._open_last_report)
        self.rep_open_btn.pack(side="left", padx=8)
        ttk.Button(bar, text="Capture the page (read-only)",
                   command=self._capture_case_list).pack(side="left")
        self.rep_status = ttk.Label(bar, text="", foreground=UI_ACCENT_TEXT)
        self.rep_status.pack(side="left", padx=12)
        self._refresh_last_report()
        # The run happens in another process, so this window never hears that a file
        # appeared. Re-checking whenever the tab is opened is enough: coming back to
        # this tab is exactly when you'd reach for the button.
        self.book.bind("<<NotebookTabChanged>>",
                       lambda e: self._refresh_last_report(), add="+")

        # ── the standing notes ──
        # ⚠️ HEIGHT BUDGET. _fit_to_screen gives this window 700px on Dane's 1280x800
        # desktop, not the 780 a wider screen shows — so anything packed at the bottom
        # of this tab has ~80px less room than it looks like it has while developing.
        # The capture warning is the one thing here that must never be the piece that
        # falls off the edge, so it goes FIRST, directly under the buttons, and the
        # bullets (which only restate what the tab already does) take the squeeze.
        note = ttk.Frame(tab, padding=(14, 4))
        note.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))

        if not case_report.PARSER_READY:
            tk.Label(note,
                     text="⚠  The Case List page has not been captured yet, so the "
                          "report cannot read it. Click “Capture the page” once — it "
                          "opens the page read-only and saves a scrubbed copy to "
                          "./debug — then Claude finishes the reader from what the "
                          "page actually says. Nothing is guessed at.",
                     bg=UI_ACCENT_SOFT, fg=UI_ACCENT_TEXT, justify="left",
                     wraplength=1000, anchor="w", font=("Segoe UI", 10),
                     padx=10, pady=8).pack(anchor="w", fill="x", pady=(0, 8))

        for text, colour in (
                ("A browser opens on your screen and pauses for you to log in and "
                 "confirm the worksite — same as entering a batch.", UI_TEXT),
                ("Nothing is written back to the EMR. It opens the Case List, reads "
                 "it, and closes.", UI_TEXT),
                ("It pages back from today until it passes your From date, 30 rows a "
                 "page — so an older range takes longer than a recent one. The console "
                 "shows each page as it goes.", UI_TEXT),
                ("Coaching type isn't shown on the Case List, so that level comes out "
                 "blank. Case type (the coloured chip) is there.", UI_MUTED),
                ("The file lands in the project folder as "
                 "case_report_<from>_to_<to>.xlsx / .docx. It has real names on it, "
                 "so it is gitignored and stays on this PC.", UI_MUTED)):
            tk.Label(note, text="•  " + text, bg=UI_BG, fg=colour, justify="left",
                     wraplength=1000, anchor="w", font=("Segoe UI", 10)
                     ).pack(anchor="w", pady=(0, 4))

    def _report_preset(self, span):
        """Fill From/To from a named span. Weeks start Monday, like the plant's."""
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        if span == "today":
            start = end = today
        elif span == "this_week":
            start, end = monday, today
        elif span == "last_week":
            start, end = monday - timedelta(days=7), monday - timedelta(days=1)
        elif span == "this_month":
            start, end = today.replace(day=1), today
        else:                                    # last_month
            first = today.replace(day=1)
            end = first - timedelta(days=1)
            start = end.replace(day=1)
        self.rep_from.set(start.strftime("%m/%d/%Y"))
        self.rep_to.set(end.strftime("%m/%d/%Y"))

    def _report_range(self):
        """The chosen range as (start, end), or None after showing why not."""
        start = case_report.parse_date(self.rep_from.get())
        end = case_report.parse_date(self.rep_to.get())
        if not start or not end:
            messagebox.showerror("Dates", "Pick a From and a To date.")
            return None
        if end < start:
            start, end = end, start
            self.rep_from.set(start.strftime("%m/%d/%Y"))
            self.rep_to.set(end.strftime("%m/%d/%Y"))
        return start, end

    @staticmethod
    def _console_python():
        """python.exe, even when this window was launched by pythonw.exe.

        pythonw has no console, and a child started from it inherits that — the report
        run would print its progress into nowhere. Same class of bug as _enter_now's
        reason for spawning a real terminal.
        """
        exe = sys.executable or "python"
        base = os.path.basename(exe).lower()
        if base.startswith("pythonw"):
            candidate = os.path.join(os.path.dirname(exe), base.replace("pythonw", "python", 1))
            if os.path.exists(candidate):
                return candidate
        return exe

    def _launch_case_report(self, args, status):
        """Run case_report.py in its own PowerShell window (-NoExit keeps the log)."""
        script = os.path.join(_HERE, "case_report.py")
        quoted = " ".join(f"'{a}'" for a in [self._console_python(), script] + list(args))
        try:
            subprocess.Popen(
                ["powershell", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
                 "& " + quoted],
                cwd=_HERE,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            self.rep_status.config(text=status)
        except Exception as exc:
            messagebox.showerror(
                "Couldn't start it",
                f"{exc}\n\nRun it yourself:\n\n    python case_report.py "
                + " ".join(args))

    def _refresh_last_report(self):
        """Grey the Open button out when there's nothing to open yet.

        Only ever asks for a filename and an mtime — the report is PHI and this window
        never reads inside it, it just hands the path to Windows.
        """
        latest = case_report.newest_report()
        self.rep_open_btn.config(state="normal" if latest else "disabled")
        return latest

    def _open_last_report(self):
        latest = self._refresh_last_report()
        if not latest:
            messagebox.showinfo(
                "Nothing yet",
                "No report has been built yet. Pick a date range and click "
                "'Build the report' — the file opens itself when it's done.")
            return
        if not case_report.open_file(latest):
            messagebox.showerror(
                "Couldn't open it",
                f"The file is here, Windows just wouldn't open it:\n\n{latest}")
            return
        self.rep_status.config(text=f"Opened {os.path.basename(latest)}")

    def _capture_case_list(self):
        self._launch_case_report(
            ["--capture"],
            "Capture running in its own window — read-only.")

    def _run_report(self):
        rng = self._report_range()
        if not rng:
            return
        start, end = rng
        if not case_report.PARSER_READY:
            if messagebox.askyesno(
                    "Capture it first",
                    "The Case List page hasn't been captured yet, so there is no "
                    "measured markup to read it with — and guessing at the layout is "
                    "exactly how a wrong row ends up in a report.\n\n"
                    "Run the read-only capture now? It opens the page, saves a "
                    "scrubbed copy to ./debug, and changes nothing."):
                self._capture_case_list()
            return
        who = self.rep_specialist.get().strip()
        if not who:
            messagebox.showerror(
                "Whose cases?",
                "Put your name in the Specialist box first — exactly as the EMR's "
                "Specialists filter spells it.\n\n"
                "Without it the Case List mixes in other specialists' cases, out of "
                "date order, and the run walks thousands of pages instead of stopping "
                "at your date range.")
            return
        save_specialist(who)
        self._launch_case_report(
            ["--from", start.strftime("%m/%d/%Y"), "--to", end.strftime("%m/%d/%Y"),
             "--format", self.rep_format.get(), "--specialist", who],
            f"Reading {start:%m/%d} – {end:%m/%d} — the file opens itself when it's done.")


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
