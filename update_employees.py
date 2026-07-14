"""
ATI Worksite Solutions - Employee Roster Update
===============================================
Updates employee FILE INFORMATION (Name, Identifier, Date of Hire, Email, etc.)
in the ATI EMR from an Excel roster (roster.xlsx).

This is the second EMR AutoMate function. It is normally launched from
`emr_automate.py` (the menu popup), but can also be run directly:

    python update_employees.py                 # normal update run (reads roster.xlsx)
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
from name_match import (NICKNAMES, loose_name, normalize_name,
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
EDIT_FIELD_SPECS = [
    {"col": "first_name",     "kind": "text",   "selector": "input[name='firstName']",            "label": "First Name"},
    {"col": "middle_name",    "kind": "text",   "selector": "input[name='middleName']",           "label": "Middle Name"},
    {"col": "last_name",      "kind": "text",   "selector": "input[name='lastName']",             "label": "Last Name"},
    {"col": "new_identifier", "kind": "text",   "selector": "input[name='badgeNumber']",          "label": "Identifier"},
    {"col": "date_of_hire",   "kind": "date",   "selector": "input[placeholder='Date of Hire']",  "label": "Date of Hire"},
]

# Columns that hold dates (validated + reformatted to MM/DD/YYYY on read).
DATE_COLS = {s["col"] for s in EDIT_FIELD_SPECS if s["kind"] == "date"}
# All recognized columns = match keys + writable fields.
KNOWN_COLS = MATCH_COLS + [s["col"] for s in EDIT_FIELD_SPECS]


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


def norm_identifier(s):
    """Normalize an identifier/badge for matching.

    Drops a leading '#' and any ' - <job title>' suffix, so the dashboard badge
    '# 12345 - Materials Handler', the edit-form value '12345 - Materials Handler',
    and a plain '12345' in the sheet all match on '12345'.
    """
    s = str(s or "").strip().lstrip("#").strip()
    return s.split(" - ")[0].strip()


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

HC_COLS = {
    "id": "Associate ID", "name": "Associate Name", "shift": "Shift",
    "position": "Primary Position", "hire": "Most Recent Hire Date",
}
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


def _shift_ordinal(shift):
    """'2ND Shift' -> '2nd'; '1ST Shift' -> '1st'. '' if unrecognized."""
    tok = str(shift or "").strip().split()
    return tok[0].lower() if tok else ""


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
    name fallback), new_identifier ('ID-Title-Shift'), date_of_hire (MM/DD/YYYY).
    Names are NOT written as first/middle/last (that would wipe existing 'First "Nick"'
    entries — name corrections are a separate pass). Returns (rows_written, warnings).
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
    ci = {k: (header.index(v) if v in header else -1) for k, v in HC_COLS.items()}
    missing = [HC_COLS[k] for k, j in ci.items() if j < 0]
    if missing:
        return 0, [f"source missing expected column(s): {', '.join(missing)}"]

    warnings = []
    shortened = []  # (name, full, trimmed) when an identifier had to be cut to fit
    out = openpyxl.Workbook()
    osh = out.active
    osh.title = "roster"
    osh.append(["identifier", "name", "new_identifier", "date_of_hire"])

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
        osh.append([aid, name_lf, new_id, hire_s])
        written += 1

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

# Matches each preloaded dashboard roster row and captures id (UUID), name, badge.
_ROW_RE = re.compile(
    r'<div id="([0-9a-fA-F-]{36})" class="details[^"]*">'      # UUID
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
    dashboard capture. Each item: {uuid, name, identifier, badge}.
    """
    people = []
    for uuid, name, badge in _ROW_RE.findall(html):
        people.append({
            "uuid": uuid,
            "name": name.strip(),
            "identifier": parse_badge_identifier(badge),
            "badge": badge.strip(),
        })
    return people


def build_index(people):
    """Build lookup maps from parsed roster people.

    Returns {by_identifier: {norm_id: uuid}, by_name: {norm_name: [uuids]},
             people: [...]}.
    """
    by_identifier, by_name, by_name_loose = {}, {}, {}
    for p in people:
        if p["identifier"]:
            by_identifier[norm_identifier(p["identifier"])] = p["uuid"]
        by_name.setdefault(normalize_name(p["name"]), []).append(p["uuid"])
        by_name_loose.setdefault(loose_name(p["name"]), []).append(p["uuid"])
    return {"by_identifier": by_identifier, "by_name": by_name,
            "by_name_loose": by_name_loose, "people": people}


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
            return None, f"ambiguous name — {len(uuids)} employees match '{row.get('name')}'"

    # Fallback: forgiving match that ignores EMR nicknames/suffixes (e.g. the roster's
    # 'Skelton, Wilma' vs the EMR's 'Skelton, Wilma "Sissy"'). Only accept a unique hit.
    loose = loose_name(row.get("name"))
    if loose:
        uuids = index.get("by_name_loose", {}).get(loose, [])
        # Distinct UUIDs only (an exact + loose key can point at the same person).
        uuids = list(dict.fromkeys(uuids))
        if len(uuids) == 1:
            return uuids[0], "name (loose)"
        if len(uuids) > 1:
            return None, f"ambiguous name — {len(uuids)} employees match '{row.get('name')}'"

    return None, "no match (identifier/name not found in this worksite)"


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

            cal = page.locator(".rc-calendar:visible").first
            await cal.wait_for(state="visible", timeout=6000)
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
    print(f"Loaded {len(people)} employees from the dashboard roster.")
    return build_index(people)


# ─────────────────────────────────────────────
# STEP-0 CAPTURE MODE
# ─────────────────────────────────────────────

async def run_capture(target_name=None):
    """STEP 0: open one employee's /editemployee form and snap it (no save).

    Run this once so we can finalize the real input selectors + Save button.
    """
    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            index = await load_index(page)
            people = index["people"]
            if not people:
                print("No employees found on the dashboard — can't capture.")
                return
            if target_name:
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
            resolved, unmatched = [], []
            for row in rows:
                uuid, info = resolve_employee(row, index)
                label = row.get("name") or row.get("identifier") or "(row)"
                if uuid:
                    resolved.append((row, uuid, info))
                else:
                    unmatched.append((row, label, info))
                    log_rows(writer, label, "", "", "skipped", note=info)

            print(f"\nMatched {len(resolved)}, unmatched {len(unmatched)}.")
            for row, label, info in unmatched:
                print(f"  skip: {ph(label)} — {info}")

            # Split the unmatched into the two piles Dane cares about:
            #   • "not in EMR" → genuinely-new hires to ADD manually.
            #   • "ambiguous"  → already in the EMR, just need a badge to disambiguate.
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
            print(f"  → {len(new_hires)} new hire(s) to add manually, "
                  f"{len(ambiguous)} ambiguous — see {ROSTER_NOT_IN_EMR_CSV}")

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

            # EMR employees that no roster row matched (i.e. not in the active roster).
            matched_uuids = {uuid for _, uuid, _ in resolved}
            not_in_roster = [p for p in index["people"] if p["uuid"] not in matched_uuids]
            with open(EMR_NOT_IN_ROSTER_CSV, "w", newline="", encoding="utf-8-sig") as nf:
                nw = csv.writer(nf)
                nw.writerow(["name", "identifier", "uuid"])
                for p in not_in_roster:
                    nw.writerow([p["name"], p["identifier"], p["uuid"]])
            print(f"EMR employees not in the roster: {len(not_in_roster)} — "
                  f"see {EMR_NOT_IN_ROSTER_CSV}")

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
    if "--capture" in sys.argv:
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
    elif "--roster" in sys.argv:
        i = sys.argv.index("--roster")
        if len(sys.argv) <= i + 1:
            print("Usage: python update_employees.py --roster <path-to-xlsx>")
            sys.exit(1)
        asyncio.run(run(sys.argv[i + 1]))
    else:
        asyncio.run(run())
