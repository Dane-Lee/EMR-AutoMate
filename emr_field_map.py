"""
EMR field mapping — work area -> Department + Division (+ Category / Shift helpers)
==================================================================================
The Coaching Encounter form has four org dropdowns whose exact options were captured
to emr_field_options.json. Division does NOT auto-fill from Department in the EMR, so
we set both — this module supplies the Department<->Division correlation and an
area-text -> Department resolver so any input source (dictation, mobile capture) can
auto-fill all four.

DEPARTMENT_TO_DIVISION: (C) = confirmed by Dane 2026-07-01; (?) = inferred, verify as
new areas come up.
"""

import re

# Category is a single real option ("Temporary" is the only alternative).
CATEGORY_DEFAULT = "Full Time/Part Time"

# Department -> Division (Division is one of: Admin/Office, Assembly, Machine Operator,
# Maintenance, Material Handler, Paint Line, Quality, Weld).
DEPARTMENT_TO_DIVISION = {
    # ── Assembly ──
    "Finisher": "Assembly",              # C
    "Stations 40-70": "Assembly",        # C
    "Stations 80-95": "Assembly",        # C
    "Station 240-270": "Assembly",       # C
    "station 280-295": "Assembly",       # C
    "Packaging": "Assembly",             # C  (incl. station 2100 + pack out)
    "Parts Pick": "Assembly",            # C
    "Parts Box": "Assembly",             # C
    "Line Lead": "Assembly",             # C  (Dane note said "Team Lead" — not an option)
    "Assembly": "Assembly",              # ?
    "Assembly Line 2": "Assembly",       # ?
    "ABS": "Assembly",                   # ?
    "ACU Station": "Assembly",           # ?
    "Airlines": "Assembly",              # ?
    "Caulk Station": "Paint Line",       # C 2026-07-06
    "Hub to Rotor Station": "Assembly",  # ?
    "Pedestal Install": "Paint Line",    # C 2026-07-06
    "Pedestal Load": "Assembly",         # ?
    # ── Weld ──
    "Suspension": "Weld",                # C
    "Frame Bracket Press": "Weld",       # C
    "Frame Bracket": "Weld",             # C
    "Wrap Weld": "Weld",                 # C
    "Weld": "Weld",                      # ?
    "Weld Repair": "Weld",               # ?
    "Rework Weld": "Weld",               # ?
    "Sherlock Weld": "Weld",             # ?
    "Friction Weld": "Weld",             # ?
    "Beam": "Weld",                      # C 2026-07-06 (Beam Weld)
    "Beam Press": "Machine Operator",    # C 2026-07-06
    "Wrap": "Weld",                      # ?
    "Wrap Weld Load": "Weld",            # C 2026-07-06
    # ── Machine Operator ──
    "Bushing Press": "Machine Operator",  # C
    "Spiders Machine": "Machine Operator",  # C
    "THT/Cut Off": "Machine Operator",   # C
    "Machine Op": "Machine Operator",    # ?
    "Lathe": "Machine Operator",         # ?
    "Axle Offload": "Machine Operator",  # C 2026-07-06
    "Axle Repair": "Machine Operator",   # ?
    "Axle Upload": "Paint Line",         # C 2026-07-06
    # ── Material Handler ──
    "Material Handler": "Material Handler",  # C (incl. shipping/receiving, material handling)
    # ── Maintenance ──
    "Maintenance": "Maintenance",        # ?
    # ── Paint Line ──
    "Paint Line": "Paint Line",          # ?
    "Paint Booth": "Paint Line",         # ?
    # ── Quality ──
    "Quality": "Quality",                # ?
    # ── Admin/Office ──
    "Admin/Office": "Admin/Office",      # C
    "Supervisor": "Admin/Office",        # ?
    "Common Area": "Admin/Office",       # ?
    "NHO": "Admin/Office",               # ?
    "TIS": "Paint Line",                 # C 2026-07-06
}


def division_for(department):
    """Department -> Division ('' if the department isn't mapped)."""
    return DEPARTMENT_TO_DIVISION.get(department, "")


# Ordered (regex, Department). First match wins. Handles Dane's phrasings/synonyms.
_AREA_PATTERNS = [
    (r"\bfinish", "Finisher"),
    (r"parts?\s*pick", "Parts Pick"),
    (r"parts?\s*box", "Parts Box"),
    (r"pack\s*out|packaging", "Packaging"),
    (r"ship|receiv|material\s*hand", "Material Handler"),
    (r"wrap\s*weld\s*load", "Wrap Weld Load"),           # before 'wrap weld'
    (r"wrap\s*weld", "Wrap Weld"),
    (r"suspension", "Suspension"),
    (r"spider", "Spiders Machine"),
    (r"bushing", "Bushing Press"),
    (r"frame\s*bracket\s*press", "Frame Bracket Press"),
    (r"frame\s*bracket|tack", "Frame Bracket"),          # Tack Station -> Frame Bracket (Dane 7/6)
    (r"beam\s*press", "Beam Press"),
    (r"\bbeam\b", "Beam"),
    (r"axle\s*upload", "Axle Upload"),
    (r"axle\s*offload", "Axle Offload"),
    (r"caulk", "Caulk Station"),
    (r"ped(estal)?\s*install", "Pedestal Install"),
    (r"paint\s*booth", "Paint Booth"),
    (r"paint", "Paint Line"),
    (r"\btis\b", "TIS"),
    (r"airlines|hub\s*to\s*rotor|\bhtr\b", "Assembly"),  # Ins/Airlines/HTR -> Assembly (Dane 7/6)
    (r"\btht\b|cut\s*off", "THT/Cut Off"),
    (r"line\s*lead|team\s*lead", "Line Lead"),
    (r"new\s*hire\s*orient|\bnho\b", "NHO"),
    (r"\bhr\b|head of hr|admin|office", "Admin/Office"),
    (r"maintenance", "Maintenance"),
    (r"quality|\binspection\b", "Quality"),  # low priority — station rules run first
]


def _station_department(text):
    """Map a station number in the text to its Department range."""
    for num in re.findall(r"\b(\d{2,4})\b", text):
        n = int(num)
        if n == 2100 or n == 100:
            return "Packaging"                # station 100 -> Packaging (Dane 7/6)
        if 40 <= n <= 79:
            return "Stations 40-70"
        if 80 <= n <= 99:
            return "Stations 80-95"
        if 230 <= n <= 239:
            return "Assembly Line 2"          # station 232 -> Assembly Line 2 (Dane 7/6)
        if 240 <= n <= 279:
            return "Station 240-270"
        if 280 <= n <= 299:
            return "station 280-295"
    return None


def department_for(area_text):
    """Resolve a free-text work area to an EMR Department ('' if unknown).

    Station numbers take priority over the generic 'inspection'->Quality rule (an
    'inspection' at a numbered station belongs to that station's department).
    """
    t = (area_text or "").lower()
    # station number first (so 'station 85 inspection' -> Stations 80-95, not Quality)
    st = _station_department(t)
    if st:
        return st
    for pat, dept in _AREA_PATTERNS:
        if re.search(pat, t):
            return dept
    return ""


# Roles whose Department IS the role name; their Division comes from the line/area they
# lead or supervise (Dane 2026-07-07: e.g. "line lead, weld" -> Line Lead / Weld;
# "supervisor, weld" -> Supervisor / Weld). If no line is named, fall back to the role's
# default division below.
_ROLE_PATTERNS = [
    (r"\bsupervisor\b", "Supervisor"),
    (r"line\s*lead|team\s*lead", "Line Lead"),
]
_ROLE_DEFAULT_DIVISION = {"Line Lead": "Assembly", "Supervisor": "Admin/Office"}

# Keywords that name a Division directly (used to give a lead/supervisor their Division).
_DIVISION_KEYWORDS = [
    (r"\bweld", "Weld"),
    (r"assembly|\bassy\b", "Assembly"),
    (r"paint", "Paint Line"),
    (r"machine|\bmach\b", "Machine Operator"),
    (r"maintenance", "Maintenance"),
    (r"\bquality\b|\bqa\b", "Quality"),
    (r"material", "Material Handler"),
    (r"admin|office", "Admin/Office"),
]


def _division_keyword(text):
    for pat, div in _DIVISION_KEYWORDS:
        if re.search(pat, text):
            return div
    return ""


def resolve(area_text):
    """area text -> (department, division). Either may be '' if unknown.

    Leads/supervisors resolve to Department=role, Division=the line they're on: the
    Division is taken from a division keyword in the text ("line lead, weld" -> Weld),
    then from resolving the rest of the text, then the role's default division.
    """
    t = (area_text or "").lower()
    for pat, role in _ROLE_PATTERNS:
        if re.search(pat, t):
            div = _division_keyword(t)
            if not div:
                rest = re.sub(r"line\s*lead|team\s*lead|supervisor", " ", t)
                div = division_for(department_for(rest))
            return role, div or _ROLE_DEFAULT_DIVISION.get(role, "")
    dept = department_for(t)
    return dept, division_for(dept)


# Fallback when no work AREA is given (e.g. a general sweep): map the employee's
# Work Title -> (Department, Division). Coarser than area-based (uses the generic
# department), but better than blank. Team Lead is intentionally unmapped — a lead's
# department/division depends on the area they were in.
WORK_TITLE_MAP = {
    "assembler": ("Assembly", "Assembly"),
    "welder": ("Weld", "Weld"),
    "welder coop": ("Weld", "Weld"),
    "welder co-op": ("Weld", "Weld"),
    "machine operator": ("Machine Op", "Machine Operator"),
    "materials handler": ("Material Handler", "Material Handler"),
    "material handler": ("Material Handler", "Material Handler"),
}


def dept_div_from_title(work_title):
    """Work Title -> (Department, Division). ('', '') if unmapped (e.g. Team Lead)."""
    return WORK_TITLE_MAP.get((work_title or "").strip().lower(), ("", ""))
