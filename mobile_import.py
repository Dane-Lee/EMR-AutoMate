"""
Mobile Encounter Companion export (JSON) -> encounters.csv
==========================================================
Converts a `mobile_capture_export` JSON (from the mobile-encounter-companion) into the
`encounters.csv` that ati_coaching_encounter.py drafts. Interim bridge until the live
mobile -> ETS -> AutoMate pipeline is built.

USAGE
    python mobile_import.py "<path to export.json>"

Fields the phone doesn't capture (modality, what-prompted, category, shift, detail
checkboxes) take sensible defaults / are left blank for Dane to finish at finalize.
"""

import csv
import json
import os
import sys
from datetime import datetime

import emr_field_map as fm

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(_HERE, "encounters.csv")

# Mobile encounterType -> EMR coaching_type (from PLAN.md mapping table). Keys matched
# case-insensitively; add variants as the app's real labels come in.
MOBILE_COACHING_MAP = {
    "job-specific coaching": "Job-Specific Coaching",
    "job-specific mobility / stretching": "Job-Specific Preventative Mobility/Stretching",
    "job-specific preventative mobility/stretching": "Job-Specific Preventative Mobility/Stretching",
    "safety coaching": "Safety Coaching",
    "ergonomic adjustments": "Ergonomic Adjustment",
    "ergonomic adjustment": "Ergonomic Adjustment",
    "health and wellness coaching": "Health/Wellness Coaching",
    "health/wellness coaching": "Health/Wellness Coaching",
    "general medical coaching": "General Medical Education",
    "general medical education": "General Medical Education",
    "relationship development": "Relationship Development Encounter",
    "relationship development encounter": "Relationship Development Encounter",
    "group class": "Group Class",
    "large group class": "Group Class",
    "fitness center visit": "Fitness Center Visit",
    "near miss education": "Near Miss Education",
    "friend/family consultation": "Friend/Family Consultation",
}

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def first_last_to_last_first(name):
    parts = str(name or "").split()
    if len(parts) < 2:
        return str(name or "").strip()
    suffix = ""
    if parts[-1].lower().rstrip(".") in _SUFFIXES:
        suffix = parts.pop()
    last, firsts = parts[-1], " ".join(parts[:-1])
    if suffix:
        last = f"{last} {suffix}"
    return f"{last}, {firsts}"


def _shift(val):
    """Normalize a shift value ('1ST Shift', '1st', '1' -> '1st'). '' if absent.
    (The mobile app will add a shift field later; this reads it when present.)"""
    v = str(val or "").strip().lower()
    if v.startswith("1"):
        return "1st"
    if v.startswith("2"):
        return "2nd"
    if v.startswith("3"):
        return "3rd"
    return ""


def _date_mdy(rec):
    raw = (rec.get("encounterDate") or "")[:10] or (rec.get("occurredAt") or "")[:10]
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(raw, fmt).strftime("%m/%d/%Y")
        except ValueError:
            pass
    return ""


COLUMNS = ["employee", "date", "encounter_type", "department", "division", "category",
           "shift", "coaching_type", "details", "description", "what_prompted"]


def import_mobile(json_path, out_path=None):
    """Convert a mobile export JSON into encounters.csv. Returns (rows, warnings)."""
    out_path = out_path or OUT
    with open(json_path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    records = data.get("records", data if isinstance(data, list) else [])

    rows, warnings = [], []
    skipped = 0
    for r in records:
        # Only enter captures marked ready — skip already-'exported' ones.
        if r.get("captureStatus") != "ready_for_export":
            skipped += 1
            continue
        name = r.get("employeeDisplayName", "")
        etype = (r.get("encounterType") or "").strip()
        coaching = MOBILE_COACHING_MAP.get(etype.lower(), "")
        if etype and not coaching:
            warnings.append(f"{name}: unmapped encounterType '{etype}'")
        # Department/Division from the station (fall back to department), via the engine.
        dept, div = fm.resolve(r.get("station") or "")
        if not dept:
            dept, div = fm.resolve(r.get("department") or "")
        if not dept and (r.get("station") or r.get("department")):
            warnings.append(f"{name}: station/department "
                            f"'{r.get('station') or r.get('department')}' didn't resolve")
        rows.append({
            "employee": first_last_to_last_first(name),
            "date": _date_mdy(r),
            "encounter_type": "In Person",
            "department": dept,
            "division": div,
            "category": fm.CATEGORY_DEFAULT,
            "shift": _shift(r.get("shift")),
            "coaching_type": coaching,
            "details": "",
            "description": (r.get("summaryShort") or "").strip(),
            "what_prompted": "Specialist Initiated",
        })

    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    if skipped:
        warnings.insert(0, f"skipped {skipped} record(s) not marked 'ready_for_export'")
    return rows, warnings


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python mobile_import.py "<path to export.json>"')
        sys.exit(1)
    rows, warnings = import_mobile(sys.argv[1])
    print(f"Wrote {len(rows)} row(s) to {OUT}")
    for row in rows:
        print(f"  {row['employee']:<20} {row['coaching_type'] or '(no type)':<40} "
              f"{row['department'] or '(no dept)'} | {row['date']}")
    for w in warnings:
        print("  note:", w)
