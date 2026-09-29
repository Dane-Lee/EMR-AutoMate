"""
ATI Worksite Solutions - Employee Roster Update
===============================================
Updates employee FILE INFORMATION (Name, Identifier, Date of Hire, Email, etc.)
in the ATI EMR from an Excel roster (roster.xlsx).

This is the second EMR AutoMate function. It is normally launched from
`emr_automate.py` (the menu popup), but can also be run directly:

    python update_employees.py                 # normal update run (reads roster.xlsx)
    python update_employees.py --report         # READ-ONLY: reconcile, change nothing
    python update_employees.py --capture-sites  # READ-ONLY: which worksite? how many?
    python update_employees.py --from-hc <xlsx> # convert an HC export to roster.xlsx
    python update_employees.py --capture        # STEP-0: capture the edit form HTML
    python update_employees.py --capture "Last, First"   # capture a specific person

HOW IT WORKS
    1. Reads + validates roster.xlsx BEFORE opening the browser.
    2. Opens the browser; you log in and pick the worksite (remembered between runs).
    3. Reads the dashboard's preloaded roster into an index (name/identifier -> UUID).
    4. Matches each spreadsheet row to an employee (Identifier first, then Name).
    5. For each match: opens /editemployee?id=<UUID>, fills only the columns present
       in the sheet, and SAVES (auto-apply). A before->after audit row is written to
       employee_updates_log.csv.

SAFETY
    - Update-existing-only: rows with no confident match are SKIPPED and reported
      (never created, never deactivated).
    - One up-front confirmation popup before any changes are made.
    - Per-row error isolation: one bad employee never sinks the batch.
    - employee_updates_log.csv records every old->new change for review.

STATUS: the /editemployee form was captured 2026-06-26 and EDIT_FIELD_SPECS now uses
  VERIFIED selectors (firstName/middleName/lastName/nickName, badgeNumber, contactEmail,
  area/exchange/subs phone, Gender react-select, Date of Hire / Date of Birth pickers,
  and the .save-button div). Still TODO before a wide run: a live single-employee test
  (esp. the date pickers — see _set_date) and Dane's final list of which fields/columns
  the tool is allowed to touch (only columns present in roster.xlsx are ever written).
"""

import asyncio
import csv
import os
import re
import sys
from datetime import date, datetime

from playwright.async_api import async_playwright, Page

# Reuse the proven helpers + config from the encounter tool (importing is safe — its
# __main__ guard means nothing runs on import).
import phi_redact
from name_match import (NICKNAMES, loose_name, normalize_name, quoted_nickname,
                        split_last_first)
from phi_redact import ph, pv  # ph(name) / pv(field value) — PHI-safe stdout

from ati_coaching_encounter import (
    snap,
    react_select,
    popup,
    BASE_URL,
    USER_DATA_DIR,
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))

# Excel roster the update run reads. Put it next to this script.
ROSTER_XLSX = os.path.join(_HERE, "roster.xlsx")

# Audit log: one row per attempted employee, with per-field old->new and status.
LOG_CSV = os.path.join(_HERE, "employee_updates_log.csv")

# Employees whose Gender was blank and got defaulted to "Male" — review afterward.
GENDER_REVIEW_CSV = os.path.join(_HERE, "gender_review_needed.csv")

# Employees whose Date of Hire could not be made to persist (calendar-picker bind
# failure) even after retries — for manual entry.
DATE_NOT_PERSISTED_CSV = os.path.join(_HERE, "date_not_persisted.csv")

# Employees whose first name commonly has a nickname (for the First "Nick" treatment).
NICKNAME_CSV = os.path.join(_HERE, "nickname_candidates.csv")

# The EMR Identifier box has NO client maxlength, but the SERVER silently truncates on
# save (confirmed 2026-07-07: a 58-char value came back cut off). The importer shortens
# the TITLE part (keeping ID + shift intact) to fit, logging each change to
# identifier_shortened.csv so Dane can swap the auto-trim for a proper abbreviation
# (e.g. '...EHS Manager...'). None = always write the full value.
MAX_IDENTIFIER_LEN = 30
IDENTIFIER_SHORTENED_CSV = os.path.join(_HERE, "identifier_shortened.csv")
# New hires with no department/division yet — the work-area worklist after an import.
NO_WORK_AREA_CSV = os.path.join(_HERE, "work_area_todo.csv")

# EMR employees that no active-roster row matched (i.e. not in the roster file).
EMR_NOT_IN_ROSTER_CSV = os.path.join(_HERE, "emr_not_in_roster.csv")

# Roster rows that matched NO one in the EMR — the "add these manually" worklist
# (genuinely-new hires), separated from ambiguous rows that ARE in the EMR.
ROSTER_NOT_IN_EMR_CSV = os.path.join(_HERE, "roster_not_in_emr.csv")

# ─────────────────────────────────────────────
# ROSTER COLUMN / FIELD SPEC
# ─────────────────────────────────────────────
# MATCH_COLS identify the employee (never written). The WRITE specs below map a
# column to a real edit-form control — selectors VERIFIED from the captured Edit
# Employee form (2026-06-26). A BLANK cell means "leave the EMR value alone", and a
# column you DON'T include in the sheet is never touched — that's how Dane controls
# exactly which fields the tool edits. The bottom "medical history / screening"
# section of the form (Annual PE, Lipids, Colonoscopy, signature, …) is intentionally
# NOT wired here.
#   col      — the .xlsx header (case-insensitive, spaces/underscores ignored)
#   kind     — "text" (by selector) | "date" (rc-calendar input by placeholder) |
#              "select" (ati-react-select by label) | "phone" (3-part area/exchange/subs)
#   selector — Playwright selector for text/date kinds
#   label    — on-form label (used for the select kind + logging)
MATCH_COLS = ["identifier", "name"]

# Field set chosen by Dane (2026-06-29): Name, Identifier, Date of Hire.
#   • Nickname: the EMR only searches the First/Last NAME boxes, so a nickname must be
#     embedded in First Name as  First "Nick"  (e.g. 'James "Jim"', like the existing
#     'Michael "Mike"'). The standalone Nickname box is NOT used. Put the quoted form
#     in the `first_name` column. (Use the nickname-candidates report to find who needs
#     it — see nickname_candidates() / `--nicknames`.)
#   • Gender: NOT edited. It's required, so if a record's Gender is blank we default it
#     to "Male" and add the person to gender_review_needed.csv for manual review.
#   • Date of Birth / Phone / Email: not edited (DOB is never available).
# The other fillers/helpers below are kept so columns can be re-enabled later.
# The Preventative Medical Schedule block at the foot of the edit form. Its date input
# does not exist until "Employee Signature Attained?" is answered Yes — MEASURED
# 2026-08-27: the block contained 0 datepickers before the click and exactly 1 after,
# an empty enabled `input[placeholder='Date']`.
SIG_YES_LABEL = "label[for='isWellnessCoachingConsentSigned-yes']"
SIG_YES_RADIO = "input#isWellnessCoachingConsentSigned-yes"
SIG_DATE_SELECTOR = ".preventative-bottom-container input[placeholder='Date']"


EDIT_FIELD_SPECS = [
    {"col": "first_name",     "kind": "text",   "selector": "input[name='firstName']",            "label": "First Name"},
    {"col": "middle_name",    "kind": "text",   "selector": "input[name='middleName']",           "label": "Middle Name"},
    {"col": "last_name",      "kind": "text",   "selector": "input[name='lastName']",             "label": "Last Name"},
    {"col": "new_identifier", "kind": "text",   "selector": "input[name='badgeNumber']",          "label": "Identifier"},
    {"col": "date_of_hire",   "kind": "date",   "selector": "input[placeholder='Date of Hire']",  "label": "Date of Hire"},
    # Preventative Medical Schedule date (2026-08-27). Answers "Employee Signature
    # Attained?" Yes to reveal the field, then sets it. Skipped entirely unless the
    # sheet carries this column with a value — see set_signature_date().
    {"col": "schedule_date",  "kind": "sigdate", "selector": SIG_DATE_SELECTOR,                   "label": "Preventative Medical Schedule Date"},
]

# Columns the roster carries for OTHER tools but this one never edits in the EMR.
# encounter_builder reads department/division per person; here they ride along so
# load_roster_xlsx keeps them instead of warning "unrecognized column", and the edit
# flow (which only writes EDIT_FIELD_SPECS) never touches them.
PASSTHROUGH_COLS = ["department", "division"]

# Columns that hold dates (validated + reformatted to MM/DD/YYYY on read).
DATE_COLS = {s["col"] for s in EDIT_FIELD_SPECS if s["kind"] == "date"}
# All recognized columns = match keys + passthrough + writable fields.
KNOWN_COLS = MATCH_COLS + PASSTHROUGH_COLS + [s["col"] for s in EDIT_FIELD_SPECS]


# ─────────────────────────────────────────────
# SMALL VALUE HELPERS
# ─────────────────────────────────────────────

def _norm_header(h):
    """Normalize a spreadsheet header for matching: lowercase, strip, spaces->_ ."""
    return re.sub(r"[\s]+", "_", str(h or "").strip().lower())


# normalize_name / loose_name / split_last_first / NICKNAMES now live in
# name_match.py, shared with the encounters tool. They used to be defined here,
# where ati_coaching_encounter couldn't reach them — so it used a plain regex that
# only matched nicknames which happen to be a PREFIX of the formal name ('Will' of
# 'William'). 'Bill', 'Bob' and 'Peggy' silently failed. One copy, both tools.


# format_identifier composes 'ID-Title-Shift' with NO spaces around the hyphens, and the
# ID itself may carry a '-NN' suffix. Anchor on the ID at the front: a leading run of
# digits, optionally '-NN', followed by a hyphen and anything at all. Same shape
# encounter_builder._IDENT_RE anchors on, from the other end.
#
# The tail must contain a NON-DIGIT to count as a job title. Without that guard,
# '11111-01' (an Associate ID whose own suffix is '-01') reduces to '11111' — the regex
# happily reads the '01' as the title and throws away half the ID.
_ID_FROM_COMPOSED = re.compile(r"^(\d+(?:-\d+)?)-(?=.*\D).+$")


def norm_identifier(s):
    """Normalize an identifier/badge to the bare Associate ID for matching.

    Handles all three shapes this system produces:
        '# 12345 - Materials Handler'  (EMR dashboard badge)   -> '12345'
        '12345 - Materials Handler'    (edit-form value)       -> '12345'
        '12345-Technician II-1st'      (format_identifier)     -> '12345'
        '11111-01-Technician II-1st'   (ID with a -NN suffix)  -> '11111-01'
        '12345'                        (roster identifier)     -> '12345'

    MEASURED 2026-08-27: the third shape was NOT handled, and it is the one Dane types
    into the badge field when clearing the identifier worklist. Splitting on ' - '
    (space-hyphen-space) finds nothing in it, so the whole 'ID-Title-Shift' string
    became the index key while the roster side still reduced to '12345' — identifier
    matching failed for every badge that had been corrected. Those people fell through
    to name matching, and the ones whose names were ambiguous or spelled differently
    were reported as 'not in EMR' despite existing with a correct badge. Fixing badges
    made the report worse, which is exactly backwards.
    """
    s = str(s or "").strip().lstrip("#").strip()
    s = s.split(" - ")[0].strip()
    m = _ID_FROM_COMPOSED.match(s)
    return m.group(1) if m else s


def cell_to_str(value, is_date=False):
    """Convert an openpyxl cell value to a clean string.

    - None -> ""
    - date columns -> MM/DD/YYYY (datetime cells are formatted; strings are parsed
      and reformatted); returns ("", error_msg) semantics handled by the caller.
    - whole-number floats (12345.0) -> "12345" so identifiers/badges stay clean.
    """
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%m/%d/%Y") if is_date else value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


_DATE_INPUT_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"]


def parse_date_to_mdy(raw):
    """Parse a date string into MM/DD/YYYY. Returns (value, error) — one is None."""
    raw = str(raw or "").strip()
    if not raw:
        return "", None
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%m/%d/%Y"), None
        except ValueError:
            continue
    return None, f"unrecognized date '{raw}' (use MM/DD/YYYY)"


# ─────────────────────────────────────────────
# ROSTER (.xlsx) READER + VALIDATION
# ─────────────────────────────────────────────

def load_roster_xlsx(path):
    """Read + validate roster.xlsx.

    Returns (rows, errors, warnings):
      rows     — list of dicts keyed by known column name (string values; blanks "")
      errors   — fatal problems (run must not proceed)
      warnings — non-fatal notes (e.g. unrecognized columns, ignored)
    """
    import openpyxl  # local import so --help/import of this module is cheap

    rows, errors, warnings = [], [], []

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    grid = list(ws.iter_rows(values_only=True))
    if not grid:
        errors.append("roster.xlsx is empty.")
        wb.close()
        return rows, errors, warnings

    # Header row → map column index -> known column name
    header = grid[0]
    col_at = {}          # index -> known col name
    seen = set()
    for idx, raw_h in enumerate(header):
        norm = _norm_header(raw_h)
        if not norm:
            continue
        if norm in KNOWN_COLS:
            col_at[idx] = norm
            seen.add(norm)
        else:
            warnings.append(f"Ignoring unrecognized column '{raw_h}'.")

    if "identifier" not in seen and "name" not in seen:
        errors.append("roster.xlsx must have at least an 'identifier' or 'name' "
                      "column to match employees.")
        wb.close()
        return rows, errors, warnings

    # Data rows (header is row 1; data starts at row 2)
    for line_no, raw_row in enumerate(grid[1:], start=2):
        record = {}
        any_value = False
        for idx, col in col_at.items():
            cell = raw_row[idx] if idx < len(raw_row) else None
            val = cell_to_str(cell, is_date=(col in DATE_COLS))
            if val:
                any_value = True
            record[col] = val
        if not any_value:
            continue  # skip fully blank line

        # Must have a match key
        if not record.get("identifier") and not record.get("name"):
            errors.append(f"Row {line_no}: needs an identifier or a name to match.")

        # Validate + reformat date columns
        for col in DATE_COLS:
            if record.get(col):
                fixed, err = parse_date_to_mdy(record[col])
                if err:
                    errors.append(f"Row {line_no}: {col}: {err}")
                else:
                    record[col] = fixed

        record["_line"] = line_no
        rows.append(record)

    wb.close()
    return rows, errors, warnings


# ─────────────────────────────────────────────
# HC ROSTER IMPORT  (Active Associates HC Reporting .xlsx -> roster.xlsx)
# ─────────────────────────────────────────────
# Dane's source export has columns: Associate ID, Associate Name ("First Last"),
# Shift ("1ST Shift"/"2ND Shift"), Primary Position ("code - Title"), Most Recent
# Hire Date. This converts it into the tool's roster.xlsx schema and builds the
# Identifier as  ID-Title-Shift  (e.g. "12345-Technician II-2nd").

# Each field lists every header HC has used for it, most recent first. The report
# builder renames columns between exports — the 8-25-26 Navarre export calls them
# "Name" and "Position Title" where the 7-17-26 one said "Associate Name" and "Primary
# Position" — and a single expected spelling turns that into "source missing expected
# column(s)" with no hint that the data is right there under another name.
HC_COLS = {
    "id":       ("Associate ID",),
    "name":     ("Name", "Associate Name"),
    "shift":    ("Shift",),
    "position": ("Position Title", "Primary Position"),
    "hire":     ("Most Recent Hire Date",),
}


def _find_col(header, names):
    """Index of the first accepted header spelling, or -1."""
    for name in names:
        if name in header:
            return header.index(name)
    return -1


def _existing_work_areas(path):
    """{identifier: (department, division)} from the roster being replaced.

    Department and Division are DANE'S work, not the HC export's — he set them by hand
    for every employee and no export has ever carried them for Navarre. An import that
    simply rewrites the file throws away all 261 of them, which is how a roster gets
    silently emptied of the one column encounter_builder needs."""
    if not os.path.exists(path):
        return {}
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        grid = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception:
        return {}
    if not grid:
        return {}
    header = [str(h or "").strip() for h in grid[0]]
    try:
        i_id = header.index("identifier")
        i_dept = header.index("department")
        i_div = header.index("division")
    except ValueError:
        return {}
    areas = {}
    for r in grid[1:]:
        if i_id >= len(r) or not r[i_id]:
            continue
        dept = str(r[i_dept]).strip() if i_dept < len(r) and r[i_dept] else ""
        div = str(r[i_div]).strip() if i_div < len(r) and r[i_div] else ""
        if dept or div:
            areas[_hc_id_str(r[i_id])] = (dept, div)
    return areas
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def first_last_to_last_first(name):
    """'Jane Doe' -> 'Doe, Jane'; 'John Roe Jr.' -> 'Roe Jr., John'."""
    parts = str(name or "").split()
    if len(parts) < 2:
        return str(name or "").strip()
    suffix = ""
    if parts[-1].lower().rstrip(".") in NAME_SUFFIXES:
        suffix = parts.pop()
    last = parts[-1]
    firsts = " ".join(parts[:-1])
    if suffix:
        last = f"{last} {suffix}"
    return f"{last}, {firsts}"


# The shift vocabulary is CLOSED — '1st' / '2nd' / '3rd'. encounter_builder parses the
# shift back out of new_identifier and colours its roster rail by it (SHIFT_RAIL), and
# intake_grid offers the same three. Anything else is not a shift this system knows.
_SHIFT_ORDINALS = {
    "1": "1st", "1st": "1st", "first": "1st", "a": "1st",
    "2": "2nd", "2nd": "2nd", "second": "2nd", "b": "2nd",
    "3": "3rd", "3rd": "3rd", "third": "3rd", "c": "3rd",
}


def _shift_ordinal(shift):
    """'2ND Shift' -> '2nd'; '1st Shift' -> '1st'; bare '1' -> '1st'. '' if unknown.

    MEASURED 2026-08-25: the 8-25-26 Navarre export writes the Shift column as a bare
    '1' or '2', where the 7-17-26 export wrote '1ST Shift'. The old version of this
    function lowercased the first token and returned it, so '1' became the identifier
    suffix '-1' instead of '-1st' — silently, with no warning, because nothing checked
    the result against the vocabulary. encounter_builder then found no shift on any of
    259 people and every roster row lost its shift rail.

    Every token is checked, not just the first, so 'Shift 2' works as well as '2 Shift'.
    """
    for token in str(shift or "").strip().split():
        hit = _SHIFT_ORDINALS.get(token.lower().strip(".,"))
        if hit:
            return hit
    return ""


def _position_title(position):
    """'31-H002817 - Technician II' -> 'Technician II'."""
    s = str(position or "").strip()
    return s.split(" - ", 1)[1].strip() if " - " in s else s


# Word/phrase abbreviations used to shrink a job TITLE so the 'ID-Title-Shift'
# identifier fits MAX_IDENTIFIER_LEN cleanly (instead of a mid-word truncation).
# Applied only when the full identifier is over the cap. Multi-word phrases first,
# then single words; matched whole-word and case-insensitively. Roman-numeral level
# suffixes (I/II/III) are left intact. Extend as new long titles appear.
_TITLE_ABBREVIATIONS = [
    ("environmental health & safety", "EHS"),
    ("environmental health and safety", "EHS"),
    ("continuous improvement", "CI"),
    ("human resources", "HR"),
    ("information technology", "IT"),
    ("quality assurance", "QA"),
    ("representative", "Rep"),
    ("coordinator", "Coord"),
    ("administrator", "Admin"),
    ("manufacturing", "Mfg"),
    ("engineering", "Eng"),
    ("engineer", "Eng"),
    ("maintenance", "Maint"),
    ("production", "Prod"),
    ("supervisor", "Sup"),
    ("associate", "Assoc"),
    ("assistant", "Asst"),
    ("specialist", "Splst"),
    ("technician", "Tech"),
    ("operator", "Op"),
    ("manager", "Mngr"),
    ("director", "Dir"),
    ("senior", "Sr"),
    ("junior", "Jr"),
]


def abbreviate_title(title):
    """Apply _TITLE_ABBREVIATIONS to a job title (whole-word, case-insensitive),
    collapsing any doubled spaces the substitutions leave behind."""
    out = str(title or "")
    for phrase, abbr in _TITLE_ABBREVIATIONS:
        out = re.sub(rf"\b{re.escape(phrase)}\b", abbr, out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


def format_identifier(associate_id, position, shift, maxlen=None):
    """Build 'ID-Title-Shift', e.g. '12345-Technician II-2nd' (per Dane's spec).

    If `maxlen` is set and the full value is too long, first abbreviate the TITLE
    (e.g. 'Production Supervisor' -> 'Prod Supv'); only if it's *still* too long do we
    hard-trim the title. The ID and shift are always kept intact. Returns
    (value, was_shortened).
    """
    aid = str(associate_id).strip()
    title = _position_title(position)
    sh = _shift_ordinal(shift)

    def compose(t):
        return "-".join(p for p in [aid, t, sh] if p)

    full = compose(title)
    if not maxlen or len(full) <= maxlen:
        return full, False

    # 1) Abbreviate the title; that alone usually gets us under the cap.
    title = abbreviate_title(title)
    if len(compose(title)) <= maxlen:
        return compose(title), True

    # 2) Still too long — hard-trim the (abbreviated) title as a last resort.
    overhead = len(aid) + (1 + len(sh) if sh else 0) + (1 if title else 0)
    avail = maxlen - overhead
    title = title[:avail].rstrip() if avail > 0 else ""
    return compose(title), True


def _hc_id_str(aid):
    if isinstance(aid, float) and aid.is_integer():
        return str(int(aid))
    return str(aid).strip()


def import_hc_roster(src_path, out_path=None):
    """Convert an HC Reporting .xlsx into the tool's roster.xlsx schema.

    Output columns: identifier (match key = Associate ID), name ('Last, First' for the
    name fallback), new_identifier ('ID-Title-Shift'), date_of_hire (MM/DD/YYYY), and
    department/division when the source has them (Dane's per-person work-area columns,
    read by encounter_builder). Names are NOT written as first/middle/last (that would
    wipe existing 'First "Nick"' entries — name corrections are a separate pass).
    Returns (rows_written, warnings).
    """
    import openpyxl
    out_path = out_path or ROSTER_XLSX
    wb = openpyxl.load_workbook(src_path, read_only=True, data_only=True)
    ws = wb.active
    grid = list(ws.iter_rows(values_only=True))
    wb.close()
    if not grid:
        return 0, ["source file is empty"]

    header = [str(h or "").strip() for h in grid[0]]
    ci = {k: _find_col(header, names) for k, names in HC_COLS.items()}
    missing = [" / ".join(HC_COLS[k]) for k, j in ci.items() if j < 0]
    if missing:
        return 0, [f"source missing expected column(s): {', '.join(missing)}"]

    # Department/Division are OPTIONAL — an older export won't have them. Copied
    # through verbatim (Dane maintains the exact EMR spellings himself; this tool does
    # not second-guess them). Absent columns just mean a blank work area, which is safe.
    dept_j = header.index("Department") if "Department" in header else -1
    div_j = header.index("Division") if "Division" in header else -1
    has_area = dept_j >= 0 and div_j >= 0

    # Carry the previous roster's work areas forward, ALWAYS — not only when the export
    # lacks the columns. MEASURED 2026-08-25: the 8-25-26 export gained Department and
    # Division but had them filled for 150 of 259 rows, so treating "the column exists"
    # as "the column is authoritative" would have replaced 243 known work areas with
    # 150. The merge is per FIELD: a value in the export wins, a blank falls back to
    # what Dane already set. Keyed on Associate ID, so a rename or a shift change keeps
    # the person's area.
    carried = _existing_work_areas(out_path) or _existing_work_areas(ROSTER_XLSX)
    kept = 0
    no_area = []

    warnings = []
    shortened = []  # (name, full, trimmed) when an identifier had to be cut to fit
    out = openpyxl.Workbook()
    osh = out.active
    osh.title = "roster"
    osh.append(["identifier", "name", "new_identifier", "date_of_hire",
                "department", "division"])

    written = 0
    for n, r in enumerate(grid[1:], start=2):
        def g(key):
            j = ci[key]
            return r[j] if 0 <= j < len(r) else None
        if g("id") in (None, ""):
            continue
        aid = _hc_id_str(g("id"))
        name_lf = first_last_to_last_first(g("name"))
        full_id, _ = format_identifier(aid, g("position"), g("shift"))
        new_id, was_cut = format_identifier(aid, g("position"), g("shift"),
                                            maxlen=MAX_IDENTIFIER_LEN)
        if was_cut:
            shortened.append((name_lf, full_id, new_id))
        hire = g("hire")
        if isinstance(hire, (datetime, date)):
            hire_s = hire.strftime("%m/%d/%Y")
        else:
            hire_s, err = parse_date_to_mdy(hire)
            if err:
                warnings.append(f"Row {n} ({name_lf}): {err}; hire left blank")
                hire_s = ""
        if not _position_title(g("position")):
            warnings.append(f"Row {n} ({name_lf}): no job title in Primary Position")
        if not _shift_ordinal(g("shift")):
            warnings.append(f"Row {n} ({name_lf}): unrecognized Shift '{g('shift')}'")
        dept = str(r[dept_j]).strip() if has_area and dept_j < len(r) and r[dept_j] else ""
        div = str(r[div_j]).strip() if has_area and div_j < len(r) and r[div_j] else ""
        was_blank = not (dept and div)
        if was_blank and aid in carried:
            prev_dept, prev_div = carried[aid]
            dept = dept or prev_dept        # per field: the export wins when it has a
            div = div or prev_div           # value, the old roster fills the gaps
            if dept or div:
                kept += 1
        if not (dept and div):
            no_area.append(name_lf)
        osh.append([aid, name_lf, new_id, hire_s, dept, div])
        written += 1

    if carried:
        warnings.append(f"work areas carried forward from the previous roster for "
                        f"{kept} of {written} employees")
        gone = len(set(carried) - {_hc_id_str(g_id) for g_id in
                                   (r[ci['id']] for r in grid[1:]
                                    if ci['id'] < len(r) and r[ci['id']] not in (None, ""))})
        if gone:
            warnings.append(f"{gone} employee(s) had a work area in the previous roster "
                            f"but are not in this export — off the active roster")
    if no_area:
        warnings.append(f"{len(no_area)} employee(s) have NO department/division — "
                        f"new hires needing a work area; see "
                        f"{os.path.basename(NO_WORK_AREA_CSV)}")
        with open(NO_WORK_AREA_CSV, "w", newline="", encoding="utf-8-sig") as nf:
            nw = csv.writer(nf)
            nw.writerow(["employee", "department", "division"])
            for nm in no_area:
                nw.writerow([nm, "", ""])

    out.save(out_path)

    if shortened:
        with open(IDENTIFIER_SHORTENED_CSV, "w", newline="", encoding="utf-8-sig") as sf:
            sw = csv.writer(sf)
            sw.writerow(["employee", "full_identifier", "shortened_identifier"])
            sw.writerows(shortened)
        warnings.append(f"{len(shortened)} identifier(s) shortened to fit "
                        f"MAX_IDENTIFIER_LEN={MAX_IDENTIFIER_LEN} — see "
                        f"{os.path.basename(IDENTIFIER_SHORTENED_CSV)}")
    return written, warnings


# ─────────────────────────────────────────────
# ROSTER INDEX + MATCHER
# ─────────────────────────────────────────────

# Matches each preloaded dashboard roster row and captures id (UUID), the class list,
# name, and badge.
#
# The EMR marks a deactivated employee with an `inactive` class on this same div —
# MEASURED 2026-08-18 across the saved dashboard captures in debug/, every one of which
# had 735 `class="details  "` rows and 203 `class="details  inactive"` rows (938 total).
# The class list is captured because that flag is the whole difference between "should
# be deactivated" and "Dane already deactivated this person last quarter". Until
# 2026-08-19 the pattern discarded it, so emr_not_in_roster.csv reported both as one
# undifferentiated pile.
_ROW_RE = re.compile(
    r'<div id="([0-9a-fA-F-]{36})" class="(details[^"]*)">'    # UUID + class list
    r'.*?<span class="name">([^<]*)</span>'                     # "Last, First"
    r'<span class="badge-id">([^<]*)</span>',                   # "# 12345 - Title"
    re.DOTALL,
)
def parse_badge_identifier(badge_text):
    """Pull the identifier out of a badge like '# 12345 - Materials Handler' or
    '# 11111-01 - Materials Handler'.

    The identifier is everything before the ' - ' (space-dash-space) that precedes
    the job title, so internal suffixes like '-01' are preserved (matches the
    Associate IDs in the HC roster).
    """
    s = str(badge_text or "").strip().lstrip("#").strip()
    return s.split(" - ")[0].strip()


def parse_roster_html(html):
    """Parse the dashboard's preloaded roster HTML into a list of employee dicts.

    Pure function (no Playwright) so it can be tested offline against a saved
    dashboard capture. Each item: {uuid, name, identifier, badge, active}.

    `active` is False when the row carries the EMR's `inactive` class. Split on
    whitespace rather than a substring test so a future class like "inactive-pending"
    can't silently read as inactive.
    """
    people = []
    for uuid, classes, name, badge in _ROW_RE.findall(html):
        people.append({
            "uuid": uuid,
            "name": name.strip(),
            "identifier": parse_badge_identifier(badge),
            "badge": badge.strip(),
            "active": "inactive" not in classes.split(),
        })
    return people


def build_index(people):
    """Build lookup maps from parsed roster people.

    Returns {by_identifier: {norm_id: uuid}, by_name: {norm_name: [uuids]},
             by_uuid: {uuid: person}, people: [...]}.
    """
    by_identifier, by_name, by_name_loose, by_name_nick = {}, {}, {}, {}
    for p in people:
        if p["identifier"]:
            by_identifier[norm_identifier(p["identifier"])] = p["uuid"]
        by_name.setdefault(normalize_name(p["name"]), []).append(p["uuid"])
        by_name_loose.setdefault(loose_name(p["name"]), []).append(p["uuid"])
        # The name the EMR says this person actually goes by. loose_name() drops the
        # quoted nickname and KEEPS the formal name, so 'Last, Robert "Bob"' reduces to
        # 'last robert' — and a roster that carries the short form as the first name
        # ('Last, Bob') never meets it. MEASURED 2026-08-27: that mismatch alone was
        # reported as a missing EMR account for someone who plainly had one.
        nick = quoted_nickname(p["name"])
        if nick:
            last, _first = split_last_first(p["name"])
            by_name_nick.setdefault(normalize_name(f"{last}, {nick}"), []).append(p["uuid"])
    return {"by_identifier": by_identifier, "by_name": by_name,
            "by_name_loose": by_name_loose, "by_name_nick": by_name_nick,
            "by_uuid": {p["uuid"]: p for p in people}, "people": people}


def resolve_employee(row, index):
    """Resolve a roster row to a UUID. Returns (uuid, matched_by) or (None, reason).

    Identifier first, then Name (per the agreed match strategy). A name that maps to
    more than one employee is treated as ambiguous and skipped (we never guess).
    """
    ident = norm_identifier(row.get("identifier"))
    if ident and ident in index["by_identifier"]:
        return index["by_identifier"][ident], "identifier"

    name = normalize_name(row.get("name"))
    if name:
        uuids = index["by_name"].get(name, [])
        if len(uuids) == 1:
            return uuids[0], "name"
        if len(uuids) > 1:
            # The name is NOT in this string. It is printed as `ph(label) — {info}`,
            # and ph() redacts the label while info goes out verbatim — so a name
            # embedded here walks straight past the redaction that the rest of the
            # line relies on. Found 2026-08-25, when a --report run printed six real
            # employees to a console Claude reads. The count is the useful part; the
            # Employee # on the same line says which row it is.
            return None, f"ambiguous name — {len(uuids)} EMR records share this name"

    # Fallback: forgiving match that ignores EMR nicknames/suffixes (e.g. the roster's
    # 'Smith, Jane' vs the EMR's 'Smith, Jane "JJ"'). Only accept a unique hit.
    loose = loose_name(row.get("name"))
    if loose:
        uuids = index.get("by_name_loose", {}).get(loose, [])
        # Distinct UUIDs only (an exact + loose key can point at the same person).
        uuids = list(dict.fromkeys(uuids))
        if len(uuids) == 1:
            return uuids[0], "name (loose)"
        if len(uuids) > 1:
            # The name is NOT in this string. It is printed as `ph(label) — {info}`,
            # and ph() redacts the label while info goes out verbatim — so a name
            # embedded here walks straight past the redaction that the rest of the
            # line relies on. Found 2026-08-25, when a --report run printed six real
            # employees to a console Claude reads. The count is the useful part; the
            # Employee # on the same line says which row it is.
            return None, f"ambiguous name — {len(uuids)} EMR records share this name"

    # Last resort: the roster carries the SHORT form as the first name, while the EMR
    # spells the formal name out with the short form quoted after it. loose_name()
    # cannot bridge that — it drops the quotes and keeps the formal name. Only a unique
    # hit is accepted, same as every other step.
    nick_key = normalize_name(row.get("name"))
    if nick_key:
        uuids = list(dict.fromkeys(index.get("by_name_nick", {}).get(nick_key, [])))
        if len(uuids) == 1:
            return uuids[0], "name (nickname)"
        if len(uuids) > 1:
            return None, f"ambiguous name — {len(uuids)} EMR records share this name"

    return None, "no match (identifier/name not found in this worksite)"


# ─────────────────────────────────────────────
# RECONCILIATION (roster <-> EMR, both directions)
# ─────────────────────────────────────────────
# Shared by run() and run_report() so the two can never drift. Nothing here touches
# the browser or edits a record — it is pure diffing over an already-loaded index.

def resolve_all(rows, index):
    """Resolve every roster row. Returns (resolved, unmatched).

    resolved:  [(row, uuid, matched_by)]
    unmatched: [(row, label, reason)]
    """
    resolved, unmatched = [], []
    for row in rows:
        uuid, info = resolve_employee(row, index)
        label = row.get("name") or row.get("identifier") or "(row)"
        if uuid:
            resolved.append((row, uuid, info))
        else:
            unmatched.append((row, label, info))
    return resolved, unmatched


def write_roster_not_in_emr(unmatched):
    """Roster rows that matched nobody in the EMR. Returns (new_hires, ambiguous).

    Two piles, because they need opposite actions:
      - "not in EMR" -> a genuinely-new hire to ADD manually.
      - "ambiguous"  -> already in the EMR; set a badge to disambiguate.
    """
    new_hires = [(r, l) for r, l, info in unmatched if info.startswith("no match")]
    ambiguous = [(r, l, info) for r, l, info in unmatched
                 if info.startswith("ambiguous")]
    with open(ROSTER_NOT_IN_EMR_CSV, "w", newline="", encoding="utf-8-sig") as rf:
        rw = csv.writer(rf)
        rw.writerow(["name", "identifier", "date_of_hire", "reason"])
        for r, l in new_hires:
            rw.writerow([r.get("name", ""), r.get("identifier", ""),
                         r.get("date_of_hire", ""), "not in EMR — add manually"])
        for r, l, info in ambiguous:
            rw.writerow([r.get("name", ""), r.get("identifier", ""),
                         r.get("date_of_hire", ""),
                         "ambiguous — in EMR, set the badge to disambiguate"])
    return new_hires, ambiguous


def write_emr_not_in_roster(index, matched_uuids):
    """EMR records no active-roster row matched. Returns (all_of_them, still_active).

    This is the deactivation worklist. People already marked inactive in the EMR are
    kept in the file (so the numbers reconcile) but flagged and sorted to the bottom —
    they need no action, and burying them in the same list is what made the previous
    report far longer than the work it actually represented.
    """
    not_in_roster = [p for p in index["people"] if p["uuid"] not in matched_uuids]
    still_active = [p for p in not_in_roster if p.get("active", True)]
    with open(EMR_NOT_IN_ROSTER_CSV, "w", newline="", encoding="utf-8-sig") as nf:
        nw = csv.writer(nf)
        nw.writerow(["name", "identifier", "uuid", "active_in_emr", "action"])
        for p in sorted(not_in_roster,
                        key=lambda q: (not q.get("active", True), q["name"].lower())):
            act = p.get("active", True)
            nw.writerow([p["name"], p["identifier"], p["uuid"],
                         "yes" if act else "no",
                         "review — deactivate?" if act else "already inactive — no action"])
    return not_in_roster, still_active


def report_rehires(index, resolved):
    """Roster rows that matched an EMR record marked inactive — i.e. likely rehires.

    Reported only; reactivating is Dane's call and this tool never does it.
    """
    return [(row, uuid) for row, uuid, _ in resolved
            if not index["by_uuid"].get(uuid, {}).get("active", True)]


def print_emr_not_in_roster(index, resolved):
    """Write the deactivation worklist and summarize it. Returns still_active."""
    all_rows, still_active = write_emr_not_in_roster(
        index, {uuid for _, uuid, _ in resolved})
    already = len(all_rows) - len(still_active)
    print(f"EMR records with no active-roster row: {len(all_rows)} "
          f"({len(still_active)} still active, {already} already inactive) "
          f"— see {EMR_NOT_IN_ROSTER_CSV}")
    rehires = report_rehires(index, resolved)
    if rehires:
        print(f"  note: {len(rehires)} roster row(s) matched an INACTIVE EMR "
              f"record — likely rehires to reactivate.")
    return still_active


# ─────────────────────────────────────────────
# NICKNAME CANDIDATES
# ─────────────────────────────────────────────
# The EMR only searches the First/Last NAME boxes, so to find someone by either their
# formal name or nickname, the First Name box must read  First "Nick"  (e.g.
# 'James "Jim"'). This flags employees whose first name commonly has a nickname so Dane
# can decide who needs that treatment. Curated common-US-name map (formal -> nicknames).
def nickname_candidates(people):
    """From parsed roster people, flag those whose first name commonly has a nickname
    and isn't already in  First "Nick"  form. Returns a list of dicts.
    """
    out = []
    for p in people:
        _, first_full = split_last_first(p["name"])
        if '"' in first_full or not first_full:
            continue  # already has a quoted nickname, or no first name
        first_token = first_full.split()[0]
        nicks = NICKNAMES.get(first_token.lower())
        if nicks:
            out.append({
                "identifier": p.get("identifier", ""),
                "name": p["name"],
                "current_first_name": first_full,
                "suggested_nicknames": ", ".join(nicks),
                "suggested_first_name": f'{first_token} "{nicks[0]}"',
            })
    return out


def write_nickname_candidates(candidates, path):
    """Write the nickname-candidates report CSV."""
    cols = ["identifier", "name", "current_first_name",
            "suggested_nicknames", "suggested_first_name"]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(candidates)


# ─────────────────────────────────────────────
# EDIT-FORM FIELD FILLERS  (selectors verified from the captured Edit Employee form)
# ─────────────────────────────────────────────

async def _read_text(page: Page, selector: str) -> str:
    """Best-effort read of an input's current value (for the audit diff)."""
    try:
        return (await page.locator(selector).first.input_value(timeout=2500)).strip()
    except Exception:
        return ""


async def _fill_text(page: Page, selector: str, value: str) -> bool:
    """Fill a text input by selector. Returns True on success."""
    try:
        loc = page.locator(selector).first
        await loc.scroll_into_view_if_needed(timeout=4000)
        await loc.fill(value, timeout=6000)
        return True
    except Exception as e:
        print(f"  WARNING: couldn't fill '{selector}': {str(e).splitlines()[0]}")
        return False


async def _read_select(page: Page, label: str) -> str:
    """Read an ati-react-select's current display value, located by its field label."""
    try:
        loc = page.locator(
            f"xpath=//label[normalize-space(.)='{label}']/following-sibling::div[1]"
            f"//div[contains(@class,'ati-react-select__single-value')]"
        ).first
        return (await loc.inner_text(timeout=2000)).strip()
    except Exception:
        return ""


async def _read_phone(page: Page) -> str:
    """Read the 3-part phone as '(area) exchange-subs' (blank if all empty)."""
    parts = []
    for name in ("area", "exchange", "subs"):
        try:
            parts.append((await page.locator(f"input[name='{name}']").first
                          .input_value(timeout=2000)).strip())
        except Exception:
            parts.append("")
    a, e, s = parts
    return f"({a}) {e}-{s}" if any(parts) else ""


async def _fill_phone(page: Page, value: str) -> bool:
    """Split a phone string into the EMR's area / exchange / subs inputs.

    Accepts any format and uses the digits only: 10 digits -> area+exchange+subs;
    7 digits -> exchange+subs (no area).
    """
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 10:
        a, e, s = digits[:3], digits[3:6], digits[6:]
    elif len(digits) == 7:
        a, e, s = "", digits[:3], digits[3:]
    else:
        print(f"  WARNING: phone '{pv(value)}' isn't 7 or 10 digits — skipping.")
        return False
    ok = True
    for name, val in (("area", a), ("exchange", e), ("subs", s)):
        try:
            await page.locator(f"input[name='{name}']").first.fill(val, timeout=6000)
        except Exception as ex:
            print(f"  WARNING: couldn't fill phone '{name}': {str(ex).splitlines()[0]}")
            ok = False
    return ok


_MONTH_ABBR = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# The Date of Hire input (also used to re-read the saved value for verification).
DOH_SELECTOR = "input[placeholder='Date of Hire']"

# The EMR shows dates as 'Apr 05 2022'; the roster uses 'MM/DD/YYYY'. Compare by
# parsing both to an actual date so display formatting can't cause a false mismatch.
_DATE_FORMATS = ("%m/%d/%Y", "%b %d %Y", "%B %d %Y", "%b %d, %Y",
                 "%B %d, %Y", "%m-%d-%Y", "%Y-%m-%d")


def _parse_date(s):
    s = str(s or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _same_date(a, b):
    """True iff a and b denote the same calendar date (format-agnostic)."""
    da, db = _parse_date(a), _parse_date(b)
    return da is not None and da == db


async def set_signature_date(page: Page, value: str):
    """Answer the signature question Yes and set the schedule date. Returns (old, ok).

    ⚠️ Answering Yes is a factual assertion that the employee signed — it is not a data
    copy like the other fields. It is only ever done for rows whose sheet carries a
    value in this column, so the sheet is the consent record.

    Once answered, the EMR LOCKS the whole block: on an already-signed record both
    radios come back `disabled` and the date is read-only. Measured on the first record
    checked, which had disabled=True/checked=True and a filled date. So this can fill a
    blank one and can never correct an existing one — those stay hand-work.
    """
    radio = page.locator(SIG_YES_RADIO).first
    try:
        await radio.scroll_into_view_if_needed(timeout=4000)
        disabled = await radio.is_disabled(timeout=3000)
        checked = await radio.is_checked(timeout=3000)
    except Exception as e:
        print(f"  WARNING: signature question not found: {str(e).splitlines()[0]}")
        return "", False

    if disabled:
        existing = ""
        try:
            existing = (await page.locator(SIG_DATE_SELECTOR).first
                        .input_value(timeout=2000)).strip()
        except Exception:
            pass
        # Already answered: the EMR locks the block, so neither this nor Dane can
        # change the date. Returning None marks it a SKIP rather than a failure — a
        # locked record is the expected state for anyone already done, and counting it
        # as a failure would trip the run's own alarm on normal data.
        return existing, None

    if not checked:
        try:
            await page.locator(SIG_YES_LABEL).first.click(timeout=6000)
            await page.wait_for_timeout(700)
        except Exception as e:
            print(f"  WARNING: couldn't answer Yes: {str(e).splitlines()[0]}")
            return "", False

    try:
        await page.locator(SIG_DATE_SELECTOR).first.wait_for(state="visible", timeout=5000)
    except Exception:
        print("  WARNING: the schedule date field never appeared")
        return "", False

    old = ""
    try:
        old = (await page.locator(SIG_DATE_SELECTOR).first
               .input_value(timeout=2000)).strip()
    except Exception:
        pass
    ok = await _set_date(page, SIG_DATE_SELECTOR, value, original=old)
    return old, ok


async def _set_date(page: Page, selector: str, value: str, original: str = "") -> bool:
    """Set the Date of Hire field. The input won't accept typing — clicking it opens an
    rc-calendar. We open it, navigate to the target month/year via the year/month
    buttons, click the day cell by its title ('January 5, 2026'), and Apply. If the day
    can't be located, Cancel so the original value is kept. Returns True only on a
    confirmed set.

    IMPORTANT: the page has TWO ati-datepickers (Date of Hire + Date of Birth), each
    with its own `.rc-calendar` in the DOM — so we scope every lookup to the VISIBLE
    calendar (`.rc-calendar:visible`). Targeting `.rc-calendar` unscoped was matching
    the wrong/hidden one and was the main cause of the batch date failures. Retries once.
    """
    target = datetime.strptime(value, "%m/%d/%Y")
    title = f"{target.strftime('%B')} {target.day}, {target.year}"  # "January 5, 2026"

    for attempt in range(2):
        try:
            inp = page.locator(selector).first
            await inp.scroll_into_view_if_needed(timeout=4000)
            await inp.click(timeout=6000)

            # Scope the calendar to THIS input's own .ati-datepicker.
            #
            # MEASURED 2026-08-28: the form holds two ati-datepickers and a CLOSED one
            # is not hidden — it is parked at `left:-999px; top:-1077px` with no
            # `rc-calendar-picker-hidden` class. Playwright treats that as VISIBLE (it
            # has a bounding box), so `.rc-calendar:visible` matched both calendars and
            # `.first` could drive the parked one: year read, day clicked, OK pressed,
            # and the field never touched. Blank fields failed 57/59 that way, while
            # pre-filled ones "passed" only because the value already matched before
            # any of it mattered.
            cal = inp.locator(
                "xpath=ancestor::div[contains(@class,'ati-datepicker')][1]"
            ).locator(".rc-calendar").first
            await cal.wait_for(state="visible", timeout=6000)
            # ...and wait for it to actually be ON SCREEN, not parked.
            for _ in range(20):
                box = await cal.bounding_box()
                if box and box["x"] > -500 and box["y"] > -500:
                    break
                await page.wait_for_timeout(100)
            await page.wait_for_timeout(300)  # let the header + day grid render

            cur_year = int((await cal.locator(".rc-calendar-year-select")
                            .inner_text()).strip())
            cur_month = _MONTH_ABBR.get((await cal.locator(".rc-calendar-month-select")
                                         .inner_text()).strip()[:3].lower(), target.month)
            ydelta = target.year - cur_year
            if ydelta:
                ybtn = cal.locator(".rc-calendar-next-year-btn" if ydelta > 0
                                   else ".rc-calendar-prev-year-btn")
                for _ in range(abs(ydelta)):
                    await ybtn.click()
                    await page.wait_for_timeout(70)
            mdelta = target.month - cur_month
            if mdelta:
                mbtn = cal.locator(".rc-calendar-next-month-btn" if mdelta > 0
                                   else ".rc-calendar-prev-month-btn")
                for _ in range(abs(mdelta)):
                    await mbtn.click()
                    await page.wait_for_timeout(70)

            cell = cal.locator(
                f"td[role='gridcell'][title='{title}']:not(.rc-calendar-disabled-cell)")
            if await cell.count() == 0:
                # The title format ('January 5, 2026') is an ASSUMPTION — phi_redact
                # scrubs those titles out of every capture, so it has never been read
                # back from a real page. Fall back to the day NUMBER within the current
                # month, excluding the grey leading/trailing cells that belong to the
                # neighbouring months.
                cell = cal.locator(
                    "td[role='gridcell']"
                    ":not(.rc-calendar-last-month-cell)"
                    ":not(.rc-calendar-next-month-cell)"
                    ":not(.rc-calendar-disabled-cell)"
                ).filter(has_text=re.compile(rf"^\s*{target.day}\s*$"))
            if await cell.count() == 0:
                cancel = cal.locator(".cancel-btn")
                if await cancel.count() > 0:
                    await cancel.first.click()
                else:
                    await page.keyboard.press("Escape")
                continue  # retry once

            await cell.first.click(timeout=4000)
            await page.wait_for_timeout(150)
            # Commit the selection: the footer OK button is what binds the value into
            # the form. Clicking the day cell alone can update the display but not the
            # underlying value, which is why dates looked set but didn't save.
            apply_btn = cal.locator(".btn-primary.calendar-btn")
            if await apply_btn.count() > 0:
                await apply_btn.first.click()
            else:
                print("  (no calendar OK button found — selection may not bind)")
            await page.wait_for_timeout(250)
            # Success only if the input now shows the TARGET date (not merely non-empty).
            if _same_date(await inp.input_value(), value):
                return True
        except Exception as e:
            print(f"  (date attempt {attempt + 1} failed: {str(e).splitlines()[0]})")
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass

    print(f"  WARNING: couldn't set date to {pv(value)} — left as '{pv(original) or 'unchanged'}'.")
    return False


async def commit_date_of_hire(page: Page, uuid: str, expected: str) -> tuple:
    """Ensure the Date of Hire actually PERSISTED, re-setting + re-saving if needed.

    The rc-calendar can show a value in the input without binding it into the form, so
    a plain save silently drops it. This re-opens the saved record, checks the stored
    Date of Hire, and if it doesn't match, re-picks the date and saves again (up to a
    few tries). Returns (persisted: bool, actual_value: str). Leaves the edit form open.
    """
    for attempt in range(3):
        if not await open_edit_form(page, uuid):
            return False, ""  # couldn't reload (session?) — caller logs the miss
        actual = await _read_text(page, DOH_SELECTOR)
        if _same_date(actual, expected):
            return True, actual
        # Didn't stick — pick it again on this freshly-loaded form and re-save.
        print(f"  Date of Hire not persisted (shows '{pv(actual) or 'blank'}') — "
              f"re-applying {expected} (try {attempt + 1}/3)")
        await _set_date(page, DOH_SELECTOR, expected)
        await save_employee(page)
    # Final check after the last re-save.
    if await open_edit_form(page, uuid):
        actual = await _read_text(page, DOH_SELECTOR)
        return _same_date(actual, expected), actual
    return False, ""


async def fill_employee_form(page: Page, row: dict):
    """Fill the edit form for the columns present in this row.

    Reads the current value first (for the audit diff), then writes the new value.
    Returns a list of (label, old, new, ok) tuples for logging. Each field is
    non-blocking so one stubborn field doesn't abort the employee. Only columns that
    are present (non-blank) in the row are touched — everything else is left alone.
    """
    changes = []
    for spec in EDIT_FIELD_SPECS:
        col, label, kind, selector = (spec["col"], spec["label"],
                                      spec["kind"], spec["selector"])
        new = row.get(col, "")
        if not new:
            continue  # blank cell -> leave EMR value alone

        if kind == "text":
            old = await _read_text(page, selector)
            ok = await _fill_text(page, selector, new)
        elif kind == "date":
            old = await _read_text(page, selector)
            ok = await _set_date(page, selector, new, original=old)
        elif kind == "sigdate":
            old, ok = await set_signature_date(page, new)
            if ok is None:
                continue      # already answered and locked — not a failure, just skip
        elif kind == "phone":
            old = await _read_phone(page)
            ok = await _fill_phone(page, new)
        elif kind == "select":
            old = await _read_select(page, label)
            try:
                await react_select(page, label, new, required=False)
                ok = True
            except Exception:
                ok = False
        else:
            continue

        changes.append((label, old, new, ok))
        if ok:
            print(f"  set {label}: '{pv(old)}' -> '{pv(new)}'")
    return changes


async def ensure_gender_set(page: Page) -> bool:
    """Gender is required but we don't edit it. If a record's Gender is BLANK, default
    it to 'Male' so Save doesn't fail, and return True so the caller can flag the
    employee for manual gender review. Returns False if Gender was already set.
    """
    if await _read_select(page, "Gender"):
        return False  # already has a value — leave it alone
    try:
        await react_select(page, "Gender", "Male", required=False)
        print("  Gender was blank — defaulted to 'Male' (flagged for review).")
    except Exception as e:
        print(f"  WARNING: Gender was blank and couldn't be defaulted: "
              f"{str(e).splitlines()[0]}")
    return True


async def save_employee(page: Page) -> bool:
    """Click the edit form's SAVE control (auto-apply). Returns True on click success.

    SAVE is a div, not a <button>: `.save-button` inside `.action-button-container`
    at the bottom of the form (next to BACK), so we scroll to it first.
    """
    btn = page.locator(".save-button")
    if await btn.count() == 0:
        print("  WARNING: couldn't find the SAVE control (.save-button) on the form.")
        return False
    try:
        await btn.first.scroll_into_view_if_needed(timeout=4000)
        await btn.first.click(timeout=8000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(800)
        return True
    except Exception as e:
        print(f"  WARNING: couldn't click SAVE: {str(e).splitlines()[0]}")
        return False


# ─────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────

LOG_COLUMNS = ["timestamp", "employee", "uuid", "matched_by", "status",
               "field", "old_value", "new_value", "note"]


def _log_writer():
    """Open employee_updates_log.csv for append, writing a header if new."""
    is_new = not os.path.exists(LOG_CSV)
    fh = open(LOG_CSV, "a", newline="", encoding="utf-8-sig")
    writer = csv.writer(fh)
    if is_new:
        writer.writerow(LOG_COLUMNS)
    return fh, writer


def log_rows(writer, employee, uuid, matched_by, status, changes=None, note=""):
    """Write one or more audit rows. If `changes`, write one row per field."""
    ts = datetime.now().isoformat(timespec="seconds")
    if changes:
        for label, old, new, ok in changes:
            writer.writerow([ts, employee, uuid, matched_by, status,
                             label, old, new, "" if ok else "fill failed"])
    else:
        writer.writerow([ts, employee, uuid, matched_by, status, "", "", "", note])


# ─────────────────────────────────────────────
# BROWSER SESSION + ROSTER INDEX
# ─────────────────────────────────────────────

async def _open_browser(p):
    """Launch the persistent context + run the login/worksite gate (reused pattern)."""
    context = await p.chromium.launch_persistent_context(
        USER_DATA_DIR, headless=False, slow_mo=100,
    )
    page = context.pages[0] if context.pages else await context.new_page()
    print("Opening browser...")
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")
    popup(
        "Log in to ATI in the browser if it asks, and make sure the correct "
        "worksite (e.g. Navarre) is selected at the top.\n\nThen click OK to continue.",
        title="EMR AutoMate — ready to start?",
    )
    await page.wait_for_load_state("networkidle")
    return context, page


async def load_index(page: Page):
    """Go to the dashboard, wait for the roster to preload, and build the index."""
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")
    # The roster preloads into .employee-list; wait until at least one row exists.
    try:
        await page.locator(".employee-list .details").first.wait_for(
            state="attached", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(1500)
    await snap(page, "EMP_01_dashboard")
    people = parse_roster_html(await page.content())
    active = sum(1 for p in people if p.get("active", True))
    print(f"Loaded {len(people)} employees from the dashboard roster "
          f"({active} active, {len(people) - active} already inactive).")
    return build_index(people)


# ─────────────────────────────────────────────
# STEP-0 CAPTURE MODE
# ─────────────────────────────────────────────

async def read_worksite(page: Page) -> str:
    """The worksite named in the dashboard header, or "" if it can't be read.

    STRUCTURE VERIFIED 2026-08-19 from the saved dashboard captures:
        <div class="info-container"> <div class="logo">..</div>
          <div class="details"><span class="title" title="..">..</span>
                               <span class="location">..</span></div>
    Note this header <div class="details"> is NOT an employee row — the rows carry an
    id= and live under .employee-list, which is why _ROW_RE requires the id.

    Whether the dashboard's employee list is SCOPED to this worksite is exactly the
    open question; this only reports what the header says, so a report can be labelled
    with the site it was taken under.
    """
    try:
        el = page.locator(".app-header .info-container .details")
        if not await el.count():
            return ""
        title = (await el.locator(".title").inner_text()).strip()
        loc = (await el.locator(".location").inner_text()).strip()
        return f"{title} — {loc}" if loc else title
    except Exception:
        return ""


async def run_capture_sites():
    """READ-ONLY probe: what worksite is selected, and what does the switcher offer?

    Dane's EMR account contains employees from other ATI sites, and he does not know
    how many sites there are (2026-08-19). Until we know whether the dashboard roster
    is one site or all of them, emr_not_in_roster.csv cannot be trusted as a
    deactivation list — an active employee at another site would appear on it.

    This opens the group switcher and snaps the page so the real markup can be read,
    the same way _ROW_RE and the edit-form selectors were derived. It clicks one menu
    icon and saves scrubbed HTML. It writes no CSV and edits nothing.
    """
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            people = index["people"]
            active = sum(1 for q in people if q["active"])
            site = await read_worksite(page)
            print(f"\nHeader worksite: {site or '(could not read)'}")
            print(f"Dashboard roster:  {len(people)} rows "
                  f"({active} active, {len(people) - active} inactive)")
            await snap(page, "EMP_sites_before")

            icon = page.locator(".nav-container .nav-item.group-icon")
            if not await icon.count():
                print("No .group-icon in the header — snapping the header anyway.")
            else:
                try:
                    await icon.click()
                    await page.wait_for_timeout(2000)
                    print("Opened the group/site switcher.")
                except Exception as e:
                    print(f"Could not open the switcher: {e}")
            await snap(page, "EMP_sites_menu")

            popup("Captured the site switcher to ./debug (scrubbed).\n\n"
                  f"Header worksite: {site or '(unreadable)'}\n"
                  f"Dashboard roster: {len(people)} rows, {active} active\n\n"
                  "Nothing was changed. Tell Claude the worksite name and how many "
                  "sites the switcher lists.",
                  title="EMR AutoMate — site probe")
        finally:
            await context.close()


async def run_capture(target_name=None, target_uuid=None):
    """STEP 0: open one employee's /editemployee form and snap it (no save).

    Run this once so we can finalize the real input selectors + Save button.

    `target_uuid` picks the record by the EMR's own key. Added 2026-08-26 for the
    deactivation work: the worklist there carries a uuid for every row and an
    identifier for almost none (427 of 511 blank), and choosing by name would mean
    reading names out of a PHI worklist just to aim a capture.
    """
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            people = index["people"]
            if not people:
                print("No employees found on the dashboard — can't capture.")
                return
            if target_uuid:
                match = next((p_ for p_ in people if p_["uuid"] == target_uuid), None)
                if not match:
                    print(f"uuid {pv(target_uuid)} is not on the dashboard roster.")
                    return
            elif target_name:
                key = normalize_name(target_name)
                match = next((p_ for p_ in people if normalize_name(p_["name"]) == key), None)
                if not match:
                    print(f"Couldn't find '{ph(target_name)}' — capturing the first employee instead.")
                    match = people[0]
            else:
                match = people[0]

            print(f"Capturing edit form for: {ph(match['name'])}  ({pv(match['uuid'])})")
            await page.goto(f"{BASE_URL}/editemployee?id={match['uuid']}")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2500)
            await snap(page, "EMP_editform_capture")
            popup("Captured the edit form to ./debug.\n\nReview the *_EMP_editform_capture "
                  "files, then click OK to close.", title="EMR AutoMate — capture done")
        finally:
            await context.close()


# ─────────────────────────────────────────────
# DEACTIVATION (2026-08-26)
# ─────────────────────────────────────────────

# The three Employee Status options, read off the form by Dane 2026-08-26. Picked by
# VISIBLE TEXT, because that is what the control exposes — the underlying value is a
# UUID held in React state and never appears in the DOM.
STATUS_ACTIVE = "Active"
STATUS_INACTIVE = "Inactive"
STATUS_CANDIDATE = "Candidate"

DEACTIVATE_XLSX = os.path.join(_HERE, "EMR Deactivate Worklist.xlsx")
# Stop after this many consecutive failures. The 2026-06-30 run logged 420 save-failures
# out of 633 rows: whatever was wrong was wrong for every record, and grinding through
# the rest of the list learned nothing it did not know after the fifth.
DEACTIVATE_BREAKER = 5


async def set_employee_status(page: Page, want: str) -> bool:
    """Set the Employee Status react-select to `want`, by visible option text.

    Targeted through `input[name='employeeStatus']` rather than the field label: the
    label next to this control captured as 10 characters, which is not "Employee
    Status" (15), and the input's name attribute is a fact rather than an inference.
    """
    container = (
        "xpath=//input[@name='employeeStatus']"
        "/ancestor::div[contains(@class,'container')][1]"
    )
    try:
        control = page.locator(f"{container}//div[contains(@class,'ati-react-select__control')]").first
        await control.scroll_into_view_if_needed(timeout=4000)
        await control.click(timeout=6000)
        await page.wait_for_timeout(400)
        option = page.locator(
            f"//div[contains(@class,'ati-react-select__option')]"
            f"[normalize-space(.)='{want}']").first
        await option.click(timeout=6000)
        await page.wait_for_timeout(300)
        shown = (await page.locator(
            f"{container}//div[contains(@class,'ati-react-select__single-value')]"
            ).first.inner_text(timeout=3000)).strip()
        if shown != want:
            print(f"  WARNING: status reads '{shown}' after picking '{want}'")
            return False
        return True
    except Exception as e:
        print(f"  WARNING: couldn't set status: {str(e).splitlines()[0]}")
        return False


def load_deactivate_worklist(path=None):
    """Read the worklist. Returns [{uuid, name}] for rows marked Deactivate.

    Keyed on uuid: `identifier` is blank on 427 of the 511 reviewed records, so it
    cannot be the key, and matching by name would re-introduce the ambiguity that made
    six of them unresolvable in the first place.
    """
    import openpyxl
    path = path or DEACTIVATE_XLSX
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    grid = list(ws.iter_rows(values_only=True))
    wb.close()
    head = [str(h or "").strip() for h in grid[0]]
    i_uuid = head.index("uuid")
    i_name = head.index("name") if "name" in head else -1
    i_dec = head.index("decision") if "decision" in head else -1
    out = []
    for r in grid[1:]:
        if i_uuid >= len(r) or not r[i_uuid]:
            continue
        if i_dec >= 0 and str(r[i_dec] or "").strip().lower() != "deactivate":
            continue
        out.append({"uuid": str(r[i_uuid]).strip(),
                    "name": str(r[i_name]).strip() if i_name >= 0 and r[i_name] else ""})
    return out


def already_deactivated(log_path=None):
    """UUIDs the audit log says were already set to Inactive — the --resume set."""
    log_path = log_path or LOG_CSV
    done = set()
    if not os.path.exists(log_path):
        return done
    try:
        with open(log_path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if (row.get("field") == "employeeStatus"
                        and row.get("status") == "updated"
                        and row.get("new_value") == STATUS_INACTIVE):
                    done.add((row.get("uuid") or "").strip())
    except (OSError, csv.Error):
        pass
    return done


async def run_deactivate(dry_run=True, limit=None, path=None):
    """Set Employee Status to Inactive for every uuid on the worklist.

    dry_run opens each record and reports the status it FINDS, saving nothing. That is
    the only way to confirm the selector works against real records before it is
    pointed at 483 of them.
    """
    people = load_deactivate_worklist(path)
    done = already_deactivated()
    todo = [p for p in people if p["uuid"] not in done]
    print(f"Worklist: {len(people)} row(s); {len(done)} already logged Inactive; "
          f"{len(todo)} to do.")
    if limit:
        todo = todo[:limit]
        print(f"Limited to the first {len(todo)}.")
    if not todo:
        return
    if dry_run:
        print("DRY RUN — nothing will be saved.\n")
    else:
        if not popup(
                f"About to set {len(todo)} employee record(s) to Inactive.\n\n"
                "This writes to the live EMR. Continue?",
                title="EMR AutoMate — deactivate", yes_no=True):
            print("Cancelled — nothing was changed.")
            return

    ok = failed = skipped = 0
    consecutive = 0
    log_fh, writer = (None, None) if dry_run else _log_writer()
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            for n, person in enumerate(todo, 1):
                label = ph(person["name"] or person["uuid"])
                try:
                    await page.goto(f"{BASE_URL}/editemployee?id={person['uuid']}")
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(1200)
                    current = (await page.locator(
                        "xpath=//input[@name='employeeStatus']"
                        "/ancestor::div[contains(@class,'container')][1]"
                        "//div[contains(@class,'ati-react-select__single-value')]"
                        ).first.inner_text(timeout=4000)).strip()
                except Exception as e:
                    print(f"{n:4d}. {label}: could not open — "
                          f"{str(e).splitlines()[0]}")
                    failed += 1
                    consecutive += 1
                    if consecutive >= DEACTIVATE_BREAKER:
                        print(f"\nSTOPPED: {consecutive} failures in a row.")
                        break
                    continue

                if current == STATUS_INACTIVE:
                    print(f"{n:4d}. {label}: already Inactive — skipped")
                    log_rows(writer, person["name"], person["uuid"], "uuid",
                             "skipped", note="already inactive") if writer else None
                    skipped += 1
                    consecutive = 0
                    continue

                if dry_run:
                    print(f"{n:4d}. {label}: status is '{current}' -> would set "
                          f"'{STATUS_INACTIVE}'")
                    consecutive = 0
                    continue

                set_ok = await set_employee_status(page, STATUS_INACTIVE)
                saved = await save_employee(page) if set_ok else False
                if set_ok and saved:
                    print(f"{n:4d}. {label}: {current} -> {STATUS_INACTIVE}")
                    log_rows(writer, person["name"], person["uuid"], "uuid",
                             "updated",
                             changes=[("employeeStatus", current, STATUS_INACTIVE, True)])
                    ok += 1
                    consecutive = 0
                else:
                    print(f"{n:4d}. {label}: FAILED")
                    log_rows(writer, person["name"], person["uuid"], "uuid",
                             "save-failed",
                             changes=[("employeeStatus", current, STATUS_INACTIVE, False)])
                    failed += 1
                    consecutive += 1
                    if consecutive >= DEACTIVATE_BREAKER:
                        print(f"\nSTOPPED: {consecutive} failures in a row. "
                              f"Re-run with --resume once the cause is fixed.")
                        break
        finally:
            await context.close()
            if log_fh:
                log_fh.close()      # flush every row: a killed run must still be resumable

    print(f"\n{'Would deactivate' if dry_run else 'Deactivated'}: {ok}   "
          f"skipped: {skipped}   failed: {failed}")
    if not dry_run:
        print(f"Logged to {os.path.basename(LOG_CSV)}. "
              f"Re-run with --resume to pick up where this stopped.")


async def run_capture_signature(target_uuid=None):
    """Open an employee's edit form, click YES on the signature question, and snap it.

    STEP 0 for the Preventative Medical Schedule date. That field does not exist in the
    DOM until the yes/no question near the bottom is answered Yes, so a plain edit-form
    capture cannot show it. The form carries exactly one yes/no radio pair
    (`isWellnessCoachingConsentSigned`, defaulting to 'no') and six
    `scheduleDetails[N].checked` boxes; which of those the revealed date belongs to is
    the thing this capture exists to establish.

    NOTHING IS SAVED. The radio is clicked in the page and the context is closed, so
    the record is left exactly as it was found.
    """
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            people = index["people"]
            match = next((p_ for p_ in people if p_["uuid"] == target_uuid), None) \
                if target_uuid else (people[0] if people else None)
            if not match:
                print("No such employee on the dashboard — can't capture.")
                return

            # On a record that is already signed the whole block comes back DISABLED,
            # so clicking it times out and the capture shows nothing new. Scan until an
            # unanswered one turns up — that is the state the writer has to handle.
            candidates = [match] + [p_ for p_ in people[:40] if p_ is not match]
            found = None
            for person in candidates[:15]:
                await page.goto(f"{BASE_URL}/editemployee?id={person['uuid']}")
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(1500)
                radio = page.locator("input#isWellnessCoachingConsentSigned-yes").first
                try:
                    disabled = await radio.is_disabled(timeout=3000)
                    checked = await radio.is_checked(timeout=3000)
                except Exception:
                    continue
                print(f"  {ph(person['name'])}: yes-radio disabled={disabled} checked={checked}")
                if not disabled:
                    found = person
                    break
            if not found:
                print("\nEvery record checked has the signature block DISABLED.")
                await snap(page, "EMP_sig_after")
                popup("All records checked already have the signature answered and the "
                      "block locked.\n\nNothing was saved. Click OK.",
                      title="EMR AutoMate — signature capture")
                return

            print(f"\nUnanswered record found: {ph(found['name'])}")
            await snap(page, "EMP_sig_before")
            try:
                lbl = page.locator("label[for='isWellnessCoachingConsentSigned-yes']").first
                await lbl.scroll_into_view_if_needed(timeout=4000)
                await lbl.click(timeout=6000)
                await page.wait_for_timeout(1200)
                print("Clicked YES on the signature question.")
            except Exception as e:
                print(f"Couldn't click YES: {str(e).splitlines()[0]}")
            await snap(page, "EMP_sig_after")
            popup("Captured the form before and after clicking YES.\n\n"
                  "NOTHING was saved — close the browser without saving.\n\nClick OK.",
                  title="EMR AutoMate — signature capture")
        finally:
            await context.close()


async def run_capture_status(target_uuid=None):
    """Open an employee's edit form, OPEN the Employee Status dropdown, and snap it.

    STEP 0 for deactivation. The status field is an ati-react-select backed by
    `<input name="employeeStatus" type="hidden">` whose value is a 36-char UUID, and
    react-select renders its options only while open — so a plain edit-form capture
    shows the control and none of the choices. Nothing is selected or saved here; the
    point is to learn the field's label and the exact option wording, because
    `react_select()` picks by visible text and a guessed option string is exactly the
    kind of guess that has broken this project before.
    """
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            people = index["people"]
            match = next((p_ for p_ in people if p_["uuid"] == target_uuid), None) \
                if target_uuid else (people[0] if people else None)
            if not match:
                print("No such employee on the dashboard — can't capture.")
                return

            print(f"Opening edit form for: {ph(match['name'])}  ({pv(match['uuid'])})")
            await page.goto(f"{BASE_URL}/editemployee?id={match['uuid']}")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2500)
            await snap(page, "EMP_status_before")

            control = page.locator(
                "xpath=//input[@name='employeeStatus']"
                "/ancestor::div[contains(@class,'container')][1]"
                "//div[contains(@class,'ati-react-select__control')]").first
            try:
                await control.scroll_into_view_if_needed(timeout=4000)
                await control.click(timeout=6000)
                await page.wait_for_timeout(1200)
                print("Opened the Employee Status dropdown.")
            except Exception as e:
                print(f"Couldn't open the status dropdown: {str(e).splitlines()[0]}")
            await snap(page, "EMP_status_menu")
            popup("Captured the Employee Status dropdown to ./debug.\n\n"
                  "NOTHING was selected or saved. Click OK to close.",
                  title="EMR AutoMate — status capture")
        finally:
            await context.close()


async def run_capture_datepicker(target_name=None):
    """Open an employee's edit form, OPEN the Date of Hire calendar, and snap it
    (read-only, no save) so we can wire the ati-datepicker calendar popup.
    """
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            people = index["people"]
            if not people:
                print("No employees found — can't capture.")
                return
            match = None
            if target_name:
                key = normalize_name(target_name)
                match = next((x for x in people if normalize_name(x["name"]) == key), None)

            if match is None:
                # Find one with a BLANK Date of Hire. MEASURED 2026-08-28: _set_date
                # succeeds only on records whose date is ALREADY correct (50/50) and
                # fails on every blank one (57/59) — so a capture of a pre-filled
                # calendar shows the case that works, not the case that is broken.
                for person in people[:25]:
                    await page.goto(f"{BASE_URL}/editemployee?id={person['uuid']}")
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(1400)
                    try:
                        val = (await page.locator("input[placeholder='Date of Hire']")
                               .first.input_value(timeout=3000)).strip()
                    except Exception:
                        continue
                    print(f"  {ph(person['name'])}: Date of Hire {'BLANK' if not val else 'filled'}")
                    if not val:
                        match = person
                        break
            match = match or people[0]
            print(f"Opening edit form for {ph(match['name'])} ({pv(match['uuid'])})")
            await page.goto(f"{BASE_URL}/editemployee?id={match['uuid']}")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)

            dh = page.locator("input[placeholder='Date of Hire']").first
            await dh.scroll_into_view_if_needed()
            await dh.click()
            await page.wait_for_timeout(1200)
            await snap(page, "EMP_datepicker_inputclick")
            # If the input click didn't open it, try the calendar icon/wrapper.
            if await page.locator(".ati-calender-wrapper *").count() == 0:
                wrap = page.locator(".ati-calender-wrapper").first
                if await wrap.count() > 0:
                    await wrap.click()
                    await page.wait_for_timeout(1200)
                    await snap(page, "EMP_datepicker_wrapperclick")
            popup("Captured the Date of Hire calendar (if it opened) to ./debug.\n\n"
                  "Click OK to close.", title="EMR AutoMate — datepicker capture")
        finally:
            await context.close()


# ─────────────────────────────────────────────
# MAIN UPDATE RUN
# ─────────────────────────────────────────────

def prepare_roster(path=None):
    """Load + validate the roster spreadsheet before the browser opens.

    `path` defaults to roster.xlsx next to the script; pass one (via --roster) to run a
    targeted sheet (e.g. a Date-of-Hire-only fix sheet) without swapping files.
    Returns the list of rows, or raises SystemExit if missing/empty/invalid.
    """
    path = path or ROSTER_XLSX
    name = os.path.basename(path)
    if not os.path.exists(path):
        print(f"No roster file found at {path}.")
        print("Create one from roster_template.xlsx (see ROSTER_UPDATE_PROMPT.md).")
        raise SystemExit(1)

    rows, errors, warnings = load_roster_xlsx(path)
    for w in warnings:
        print(f"  note: {w}")
    if not rows:
        print(f"{name} has no data rows.")
        raise SystemExit(1)
    if errors:
        print(f"\n⚠ Fix these problems in {name} before running ({len(errors)}):")
        for e in errors:
            print(f"   - {e}")
        raise SystemExit(1)

    print(f"\nLoaded {len(rows)} employee row(s) from {name}.")
    return rows


async def _edit_form_ready(page: Page, timeout: int = 15000) -> bool:
    """Wait for the edit form's key input to appear. False if it doesn't (e.g. the
    session logged us out and we're on the login screen)."""
    try:
        await page.locator("input[name='badgeNumber']").first.wait_for(
            state="visible", timeout=timeout)
        return True
    except Exception:
        return False


async def _looks_logged_out(page: Page) -> bool:
    try:
        if await page.get_by_text("Login to your account").count() > 0:
            return True
        if await page.get_by_role("button", name="Login", exact=True).count() > 0:
            return True
    except Exception:
        pass
    return False


async def open_edit_form(page: Page, uuid: str) -> bool:
    """Navigate to an employee's edit form, recovering from an expired session.

    The batch's #1 failure mode was the EMR session timing out mid-run: every later
    `editemployee` load silently landed on the login screen, so all fields/saves
    failed. Now, if we detect the login screen, we pause and ask Dane to log back in,
    then retry — so one timeout no longer sinks the rest of the run. Returns True once
    the form is ready.
    """
    for _ in range(4):
        await page.goto(f"{BASE_URL}/editemployee?id={uuid}")
        await page.wait_for_load_state("networkidle")
        if await _edit_form_ready(page):
            await page.wait_for_timeout(700)
            return True
        if await _looks_logged_out(page):
            popup("Your ATI session has logged out.\n\nLog back in in the browser "
                  "(and make sure Navarre is selected), then click OK to continue.",
                  title="EMR AutoMate — session expired")
            continue  # retry the navigation after re-login
        await page.wait_for_timeout(1500)  # transient slow load — try once more
    return False


async def run(roster_path=None):
    """Entry point for the employee-update flow (called by emr_automate.py).

    `roster_path` (from --roster) lets a targeted sheet drive the run; defaults to
    roster.xlsx.
    """
    rows = prepare_roster(roster_path)  # validates before opening anything

    async with async_playwright() as p:
        context, page = await _open_browser(p)
        fh, writer = _log_writer()
        try:
            index = await load_index(page)

            # Resolve every row first so we can report match coverage up front.
            resolved, unmatched = resolve_all(rows, index)
            for row, label, info in unmatched:
                log_rows(writer, label, "", "", "skipped", note=info)

            print(f"\nMatched {len(resolved)}, unmatched {len(unmatched)}.")
            for row, label, info in unmatched:
                print(f"  skip: {ph(label)} — {info}")

            # BOTH reconciliation reports are written HERE, before the confirmation
            # popup and before a single record is edited. They depend only on the
            # roster and the loaded index, and the edit loop changes neither — so
            # writing them early means a run cancelled at the popup, or killed halfway
            # by an expired session, still leaves Dane the full worklists. Until
            # 2026-08-19 emr_not_in_roster.csv was written at the very END of run(),
            # so answering "No" to the confirmation produced no worklist at all.
            new_hires, ambiguous = write_roster_not_in_emr(unmatched)
            print(f"  → {len(new_hires)} new hire(s) to add manually, "
                  f"{len(ambiguous)} ambiguous — see {ROSTER_NOT_IN_EMR_CSV}")
            print_emr_not_in_roster(index, resolved)

            if not resolved:
                popup("No roster rows matched an employee in this worksite. "
                      "Nothing to update.", title="EMR AutoMate")
                return

            if not popup(
                f"{len(resolved)} employee(s) matched and will be UPDATED now.\n"
                f"{len(unmatched)} row(s) unmatched and will be skipped.\n\n"
                "Apply these updates to the EMR?",
                yes_no=True,
            ):
                print("Cancelled — no changes made.")
                return

            updated = errored = 0
            gender_review = []  # (label, uuid) for records we defaulted to Male
            date_misses = []    # (label, expected, actual) where DoH wouldn't persist
            for i, (row, uuid, matched_by) in enumerate(resolved, 1):
                label = row.get("name") or row.get("identifier") or uuid
                print(f"\n══ {i}/{len(resolved)}: {label}  (matched by {matched_by}) ══")
                try:
                    if not await open_edit_form(page, uuid):
                        errored += 1
                        print("  ⚠ edit form didn't load (session/login?) — skipped")
                        await snap(page, f"EMP_ERROR_{i:03d}")
                        log_rows(writer, label, uuid, matched_by, "error",
                                 note="edit form didn't load (session/login?)")
                        continue
                    await snap(page, f"EMP_edit_{i:03d}")

                    changes = await fill_employee_form(page, row)
                    # Gender isn't edited, but it's required — default blanks to Male
                    # and flag them so Dane can review the orientation afterward.
                    if await ensure_gender_set(page):
                        gender_review.append((label, uuid))
                        changes.append(("Gender", "(blank)", "Male (defaulted)", True))
                    await snap(page, f"EMP_filled_{i:03d}")

                    saved = await save_employee(page)

                    # The Date of Hire uses a calendar picker that can look set without
                    # binding, so verify it actually persisted and re-apply if not. The
                    # audit log then reflects the VERIFIED value, never an optimistic one.
                    doh = row.get("date_of_hire", "")
                    if saved and doh and any(c[0] == "Date of Hire" for c in changes):
                        persisted, actual = await commit_date_of_hire(page, uuid, doh)
                        changes = [(l, o, n, (persisted if l == "Date of Hire" else ok))
                                   for (l, o, n, ok) in changes]
                        if persisted:
                            print(f"  ✓ Date of Hire verified: {pv(actual)}")
                        else:
                            date_misses.append((label, doh, actual))
                            print(f"  ⚠ Date of Hire STILL not persisted (shows "
                                  f"'{pv(actual) or 'blank'}') — logged for manual entry")

                    status = "updated" if saved else "save-failed"
                    log_rows(writer, label, uuid, matched_by, status, changes=changes)
                    if saved:
                        updated += 1
                        print(f"  ✓ saved ({len(changes)} field(s))")
                    else:
                        errored += 1
                except Exception as e:
                    errored += 1
                    print(f"  ⚠ error: {e}")
                    await snap(page, f"EMP_ERROR_{i:03d}")
                    log_rows(writer, label, uuid, matched_by, "error",
                             note=str(e).splitlines()[0])

            # Write the gender-review list (employees defaulted to Male).
            if gender_review:
                with open(GENDER_REVIEW_CSV, "w", newline="", encoding="utf-8-sig") as gf:
                    gw = csv.writer(gf)
                    gw.writerow(["employee", "uuid", "note"])
                    for lbl, uid in gender_review:
                        gw.writerow([lbl, uid, "Gender was blank; defaulted to Male — review"])

            # Any Date of Hire that could not be made to persist (for manual entry).
            if date_misses:
                with open(DATE_NOT_PERSISTED_CSV, "w", newline="", encoding="utf-8-sig") as df:
                    dw = csv.writer(df)
                    dw.writerow(["name", "date_of_hire", "value_in_emr"])
                    for lbl, exp, act in date_misses:
                        dw.writerow([lbl, exp, act])
                print(f"⚠ Date of Hire failed to persist for {len(date_misses)} — "
                      f"see {DATE_NOT_PERSISTED_CSV}")

            print(f"\nDone. Updated {updated}, skipped {len(unmatched)}, errors {errored}.")
            print(f"Audit log: {LOG_CSV}")
            if gender_review:
                print(f"Gender defaulted to Male for {len(gender_review)} — "
                      f"see {GENDER_REVIEW_CSV}")
            popup(f"Employee update complete.\n\nUpdated {updated}\n"
                  f"Skipped {len(unmatched)}\nErrors {errored}\n"
                  f"Gender review needed: {len(gender_review)}\n"
                  f"Date of Hire not persisted: {len(date_misses)}\n\n"
                  f"See employee_updates_log.csv"
                  + (" and gender_review_needed.csv" if gender_review else "")
                  + (" and date_not_persisted.csv" if date_misses else "")
                  + " for details.",
                  title="EMR AutoMate — done")
        finally:
            fh.close()
            await context.close()


IDENTIFIER_DIFF_XLSX = os.path.join(_HERE, "EMR Identifier Updates.xlsx")


async def run_identifier_diff(roster_path=None):
    """READ-ONLY: who in the EMR has an identifier that differs from the roster's.

    One dashboard load answers it — the roster rows the EMR preloads already carry the
    badge (`# 12345 - Title`), so no edit form is opened and no record is read
    individually. Writes a worklist of the mismatches and changes nothing.

    Needed because a saved dashboard capture cannot answer this: phi_redact scrubs both
    the name and the badge out of debug/*.html by design, so the question can only be
    asked against a live page.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    rows = prepare_roster(roster_path)
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            site = await read_worksite(page)
            print(f"Worksite in the header: {site or '(could not read)'}")

            differs, same, unmatched = [], 0, 0
            for row in rows:
                uuid, how = resolve_employee(row, index)
                if not uuid:
                    unmatched += 1
                    continue
                person = index["by_uuid"].get(uuid) or {}
                emr_id = (person.get("identifier") or "").strip()
                want = str(row.get("new_identifier") or "").strip()
                if not want:
                    continue
                if norm_identifier(emr_id) == norm_identifier(want):
                    same += 1
                else:
                    differs.append([row.get("name", ""), emr_id, want,
                                    "blank in EMR" if not emr_id else "differs", how])
        finally:
            await context.close()

    print(f"\nmatched and identical : {same}")
    print(f"matched and DIFFERENT : {len(differs)}")
    print(f"unmatched (no EMR row): {unmatched}")

    out = openpyxl.Workbook(); o = out.active; o.title = "Identifiers"
    cols = ["name", "identifier in EMR", "identifier it should be", "why", "matched by", "done?"]
    o.append(cols)
    for r in sorted(differs, key=lambda x: (x[3], str(x[0]))):
        o.append(r + [""])
    for c, w in enumerate([30, 34, 34, 16, 14, 8], start=1):
        cell = o.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        o.column_dimensions[get_column_letter(c)].width = w
    o.freeze_panes = "A2"
    o.auto_filter.ref = "A1:F%d" % (len(differs) + 1)
    out.save(IDENTIFIER_DIFF_XLSX)
    print(f"Wrote {os.path.basename(IDENTIFIER_DIFF_XLSX)} ({len(differs)} row(s)). "
          f"Report only — nothing in the EMR was changed.")


async def run_report(roster_path=None):
    """Read-only reconciliation: roster <-> EMR, both directions. Edits NOTHING.

    Runs the same matching and writes the same two worklists a real update run does,
    but the browser is only ever read from: no edit form is opened, no record is
    saved, and employee_updates_log.csv (an audit of *edits*) is left alone. Use this
    when the question is "who is in the EMR who should not be?" rather than "push the
    roster into the EMR".
    """
    rows = prepare_roster(roster_path)

    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            site = await read_worksite(page)
            print(f"Worksite in the header: {site or '(could not read)'}")
            resolved, unmatched = resolve_all(rows, index)

            print(f"\nMatched {len(resolved)}, unmatched {len(unmatched)}.")
            for row, label, info in unmatched:
                print(f"  skip: {ph(label)} — {info}")

            new_hires, ambiguous = write_roster_not_in_emr(unmatched)
            print(f"  → {len(new_hires)} new hire(s) to add manually, "
                  f"{len(ambiguous)} ambiguous — see {ROSTER_NOT_IN_EMR_CSV}")
            still_active = print_emr_not_in_roster(index, resolved)

            print("\nReport only — nothing in the EMR was changed.")
            popup(f"Reconciliation report done. Nothing was changed.\n\n"
                  f"Active in the EMR but NOT on the roster: {len(still_active)}\n"
                  f"   review these in {os.path.basename(EMR_NOT_IN_ROSTER_CSV)}\n\n"
                  f"New hires to add manually: {len(new_hires)}\n"
                  f"Ambiguous (need a badge): {len(ambiguous)}\n"
                  f"   see {os.path.basename(ROSTER_NOT_IN_EMR_CSV)}",
                  title="EMR AutoMate — report only")
        finally:
            await context.close()


async def run_nicknames():
    """Build the nickname-candidates report from the live EMR roster (no edits)."""
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            candidates = nickname_candidates(index["people"])
            write_nickname_candidates(candidates, NICKNAME_CSV)
            print(f"\nFound {len(candidates)} employees with likely nicknames.")
            print(f"Report: {NICKNAME_CSV}")
            popup(f"Nickname report done.\n\n{len(candidates)} employees have a first "
                  f"name that commonly has a nickname.\n\nSee nickname_candidates.csv.",
                  title="EMR AutoMate — nickname report")
        finally:
            await context.close()


if __name__ == "__main__":
    if "--capture-signature" in sys.argv:
        i = sys.argv.index("--capture-signature")
        uuid = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        asyncio.run(run_capture_signature(uuid))
    elif "--identifiers" in sys.argv:
        asyncio.run(run_identifier_diff())
    elif "--deactivate" in sys.argv:
        # Dry run is the DEFAULT. Writing to 483 medical records is opt-in, by a flag
        # you have to type, on top of the confirmation popup.
        live = "--go" in sys.argv
        limit = None
        if "--limit" in sys.argv:
            i = sys.argv.index("--limit")
            limit = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else None
        asyncio.run(run_deactivate(dry_run=not live, limit=limit))
    elif "--capture-status" in sys.argv:
        i = sys.argv.index("--capture-status")
        uuid = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        asyncio.run(run_capture_status(uuid))
    elif "--capture-uuid" in sys.argv:
        i = sys.argv.index("--capture-uuid")
        if len(sys.argv) <= i + 1:
            print("Usage: python update_employees.py --capture-uuid <uuid>")
            sys.exit(1)
        asyncio.run(run_capture(target_uuid=sys.argv[i + 1]))
    elif "--capture" in sys.argv:
        i = sys.argv.index("--capture")
        name = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        asyncio.run(run_capture(name))
    elif "--nicknames" in sys.argv:
        asyncio.run(run_nicknames())
    elif "--capture-date" in sys.argv:
        i = sys.argv.index("--capture-date")
        name = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        asyncio.run(run_capture_datepicker(name))
    elif "--from-hc" in sys.argv:
        i = sys.argv.index("--from-hc")
        if len(sys.argv) <= i + 1:
            print("Usage: python update_employees.py --from-hc <path-to-HC-xlsx>")
            sys.exit(1)
        n, warnings = import_hc_roster(sys.argv[i + 1])
        print(f"Wrote {n} row(s) to {ROSTER_XLSX}")
        for w in warnings:
            print("  note:", w)
    elif "--capture-sites" in sys.argv:
        asyncio.run(run_capture_sites())
    elif "--report" in sys.argv:
        # --report may be combined with --roster to diff a targeted sheet.
        path = None
        if "--roster" in sys.argv:
            i = sys.argv.index("--roster")
            path = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        asyncio.run(run_report(path))
    elif "--roster" in sys.argv:
        i = sys.argv.index("--roster")
        if len(sys.argv) <= i + 1:
            print("Usage: python update_employees.py --roster <path-to-xlsx>")
            sys.exit(1)
        asyncio.run(run(sys.argv[i + 1]))
    else:
        asyncio.run(run())
