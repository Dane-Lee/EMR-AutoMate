"""Regression tests for the Tracker Lite -> encounter_builder bridge.

Run:  python test_tracker_import.py          (exit 0 = all pass)

THE GUARANTEE THESE PROTECT
---------------------------
A capture made on the floor supplies an identity and free text. Every CONTROLLED value
-- department, division, shift -- is looked up from the roster on this side, and the
coaching type is checked against the EMR's own list.

That split is the whole safety argument for the bridge. The phone's copy of an
employee's work area can be weeks stale, and a stale department is not a visible error:
it is a wrong value in a medical record that looks exactly like a right one. If these
tests stop passing, that guarantee is gone.

FAKE DATA ONLY. Fixtures are written to a temp directory.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker_import as ti

# A roster shaped like encounter_builder.load_roster() returns.
PEOPLE = [
    {"name": "Smith, Jane",  "title": "Technician II", "shift": "1st",
     "dept": "Frame Weld", "div": "Weld"},
    {"name": "Doe, John",    "title": "Assembler",     "shift": "2nd",
     "dept": "Assembly",   "div": "Assembly"},
    {"name": "Roe, Richard", "title": "Painter",       "shift": "1st",
     "dept": "Paint Line", "div": "Paint Line"},
]
VALID_TYPES = {"Safety Coaching", "Job-Specific Coaching", "Health/Wellness Coaching",
               "Relationship Development Encounter"}

_TMP = tempfile.mkdtemp(prefix="tracker_bridge_test_")
_FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")
        _FAILURES.append(label)


def write_capture(captures, schema=ti.SCHEMA, name="tracker_capture.json"):
    path = os.path.join(_TMP, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema": schema, "exportedAt": "2026-08-10T12:00:00Z",
                   "source": "EMR Tracker Lite", "captures": captures}, fh)
    return path


def cap(employee="Smith, Jane", date="2026-08-10", coaching_type="Safety Coaching",
        details=None, description="EIS reviewed lifting mechanics with the employee.",
        what_prompted="Specialist Initiated", cid="r1"):
    return {"id": cid, "employee": employee, "date": date,
            "coaching_type": coaching_type,
            "details": ["PPE Use"] if details is None else details,
            "description": description, "what_prompted": what_prompted}


# ── the guarantee ────────────────────────────────────────────────────────────

def test_controlled_values_come_from_the_roster_not_the_phone():
    """THE load-bearing test. Even when the capture carries its own department and
    shift, the roster's values are what reach the row."""
    print("\nControlled values come from the roster, never the capture")
    poisoned = cap()
    poisoned["department"] = "WRONG DEPARTMENT"
    poisoned["division"] = "WRONG DIVISION"
    poisoned["shift"] = "3rd"
    caps, _ = ti.load_captures(write_capture([poisoned]))
    matched, _ = ti.match_to_roster(caps, PEOPLE, VALID_TYPES)
    row = ti.to_builder_rows(matched)[0]
    check("department from roster", row["department"], "Frame Weld")
    check("division from roster", row["division"], "Weld")
    check("shift from roster", row["shift"], "1st")
    check("no stray keys from the phone survive",
          sorted(row.keys()),
          sorted(["employee", "date", "encounter_type", "department", "division",
                  "category", "shift", "coaching_type", "details", "description",
                  "what_prompted"]))


def test_row_matches_automate_csv_columns():
    print("\nRows match AutoMate's CSV schema exactly")
    import ati_coaching_encounter as ace
    caps, _ = ti.load_captures(write_capture([cap()]))
    matched, _ = ti.match_to_roster(caps, PEOPLE, VALID_TYPES)
    row = ti.to_builder_rows(matched)[0]
    check("key order identical to CSV_COLUMNS", list(row.keys()), ace.CSV_COLUMNS)


# ── refusals: nothing is guessed ─────────────────────────────────────────────

def test_unknown_coaching_type_is_refused():
    """A type the EMR does not accept must be refused, not corrected."""
    print("\nAn unknown coaching type is refused, not corrected")
    caps, _ = ti.load_captures(write_capture([cap(coaching_type="Vibes Coaching")]))
    matched, problems = ti.match_to_roster(caps, PEOPLE, VALID_TYPES)
    check("not matched", len(matched), 0)
    check("reported with a reason", "not one the EMR accepts" in problems[0][1], True)


def test_ambiguous_name_is_refused():
    print("\nAn ambiguous name is refused, not resolved to whoever sorts first")
    twins = PEOPLE + [{"name": "Smith, Janet", "title": "Tech", "shift": "2nd",
                       "dept": "Assembly", "div": "Assembly"}]
    caps, _ = ti.load_captures(write_capture([cap(employee="Smith, J")]))
    matched, problems = ti.match_to_roster(caps, twins, VALID_TYPES)
    check("not matched", len(matched), 0)
    check("reported", bool(problems), True)


def test_unknown_name_is_refused():
    print("\nA name not on the roster is refused")
    caps, _ = ti.load_captures(write_capture([cap(employee="Nobody, Here")]))
    matched, problems = ti.match_to_roster(caps, PEOPLE, VALID_TYPES)
    check("not matched", len(matched), 0)
    check("reason given", "no one on the roster" in problems[0][1], True)


def test_bad_rows_are_dropped_with_a_reason_not_repaired():
    print("\nMalformed captures are dropped with a reason, never repaired")
    caps, errors = ti.load_captures(write_capture([
        cap(cid="ok"),
        cap(employee="", cid="noname"),
        cap(date="not-a-date", cid="baddate"),
    ]))
    check("only the good one survives", [c["capture_id"] for c in caps], ["ok"])
    check("both failures explained", len(errors), 2)


# ── format handling ──────────────────────────────────────────────────────────

def test_iso_date_becomes_mdy():
    print("\nISO dates become MM/DD/YYYY")
    caps, _ = ti.load_captures(write_capture([cap(date="2026-08-10")]))
    check("converted", caps[0]["date"], "08/10/2026")


def test_details_list_becomes_semicolon_string():
    """AutoMate's CSV uses ';' so commas in a detail name can't split a column."""
    print("\nDetail lists join with semicolons")
    caps, _ = ti.load_captures(write_capture([cap(details=["PPE Use", "Rest break"])]))
    check("joined", caps[0]["details"], "PPE Use; Rest break")


def test_schema_mismatch_warns_but_still_reads():
    print("\nA schema mismatch warns without refusing the file")
    caps, errors = ti.load_captures(
        write_capture([cap()], schema="emr-tracker-lite/capture@99"))
    check("still read", len(caps), 1)
    check("warned", any("schema" in e for e in errors), True)


def test_bare_array_is_tolerated():
    print("\nA bare array (no wrapper object) is tolerated")
    path = os.path.join(_TMP, "bare.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([cap()], fh)
    caps, _ = ti.load_captures(path)
    check("read", len(caps), 1)


def test_missing_file_is_reported_not_crashed():
    print("\nA missing capture file is reported, not crashed")
    rows, problems, errors, found = ti.import_for_builder(
        PEOPLE, path=os.path.join(_TMP, "nope.json"))
    check("nothing found", found, None)
    check("explained", bool(errors), True)


def test_archive_prevents_double_import():
    print("\nArchiving renames the file so it can't be imported twice")
    path = write_capture([cap()], name="to_archive.json")
    moved = ti.archive_capture(path)
    check("original gone", os.path.exists(path), False)
    check("archive exists", bool(moved) and os.path.exists(moved), True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print()
    if _FAILURES:
        print(f"{len(_FAILURES)} FAILURE(S): {', '.join(_FAILURES)}")
        return 1
    print(f"ALL PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
