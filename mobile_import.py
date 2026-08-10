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
import phi_redact  # noqa: F401 — importing arms redaction on a captured stdout
from phi_redact import ph  # ph(name) -> 'Employee #1' unless Dane's own terminal

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

BAK = os.path.join(_HERE, "encounters.bak.csv")


def _already_entered():
    """(keys, key_fn) for encounters the audit log records as CONFIRMED saved.

    BOTH come from the entry engine, so there is exactly one definition of "already
    entered" and one normalisation of the key. A second, drifting copy of either is
    how a dedup quietly stops matching — the engine strips every field, and a caller
    that forgets to would miss every padded name and import the duplicate anyway.

    Returns an empty set and a None key_fn if the engine or its log isn't available;
    an import must still work on a machine that has never run a batch.
    """
    try:
        import ati_coaching_encounter as engine
        return set(engine._saved_keys_by_run()), engine._encounter_key
    except Exception:
        return set(), None


def import_mobile(json_path, out_path=None, skip_entered=True):
    """Convert a mobile export JSON into encounters.csv. Returns (rows, warnings).

    Backs up any existing batch to encounters.bak.csv first. This used to overwrite
    encounters.csv outright, which on a bad day silently destroys a batch that was
    half entered — and the audit log only knows what was SAVED, so the unsaved
    remainder would be gone with no way to reconstruct it.

    With `skip_entered`, records matching a confirmed save in encounter_log.csv are
    dropped here rather than at the desk. The entry engine gates on this too (see
    prepare_batch), so this is belt-and-braces — but a captured encounter is most
    likely to be a duplicate of one already entered, and the earlier it's dropped the
    fewer chances there are to click through the warning.
    """
    out_path = out_path or OUT
    with open(json_path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    records = data.get("records", data if isinstance(data, list) else [])

    entered, key_fn = _already_entered() if skip_entered else (set(), None)
    rows, warnings = [], []
    skipped = 0
    already = 0
    for r in records:
        # Only enter captures marked ready — skip already-'exported' ones.
        if r.get("captureStatus") != "ready_for_export":
            skipped += 1
            continue
        name = r.get("employeeDisplayName", "")
        etype = (r.get("encounterType") or "").strip()
        coaching = MOBILE_COACHING_MAP.get(etype.lower(), "")
        if etype and not coaching:
            warnings.append(f"{ph(name)}: unmapped encounterType '{etype}'")
        # Department/Division from the station (fall back to department), via the engine.
        dept, div = fm.resolve(r.get("station") or "")
        if not dept:
            dept, div = fm.resolve(r.get("department") or "")
        if not dept and (r.get("station") or r.get("department")):
            warnings.append(f"{ph(name)}: station/department "
                            f"'{r.get('station') or r.get('department')}' didn't resolve")
        row = {
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
        }
        key = key_fn(row["employee"], row["date"], row["coaching_type"]) if key_fn else None
        if key is not None and key in entered:
            already += 1
            warnings.append(f"{ph(name)}: already entered on a previous run — dropped")
            continue
        rows.append(row)

    # Preserve whatever batch is on disk before replacing it. The entry engine's own
    # backup lives at the same path and is likewise a single generation deep; that is
    # the established convention here, not an oversight.
    if os.path.exists(out_path):
        try:
            with open(out_path, newline="", encoding="utf-8-sig") as src:
                existing = src.read()
            if existing.strip():
                with open(BAK, "w", newline="", encoding="utf-8-sig") as dst:
                    dst.write(existing)
        except OSError as e:
            warnings.insert(0, f"could not back up the existing batch: {e}")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    if skipped:
        warnings.insert(0, f"skipped {skipped} record(s) not marked 'ready_for_export'")
    if already:
        warnings.insert(0, f"dropped {already} record(s) already entered on a previous run")
    return rows, warnings


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python mobile_import.py "<path to export.json>"')
        sys.exit(1)
    rows, warnings = import_mobile(sys.argv[1])
    print(f"Wrote {len(rows)} row(s) to {OUT}")
    for row in rows:
        # ph(): real names in Dane's terminal, 'Employee #1' when captured.
        print(f"  {ph(row['employee']):<20} {row['coaching_type'] or '(no type)':<40} "
              f"{row['department'] or '(no dept)'} | {row['date']}")
    for w in warnings:
        print("  note:", w)
