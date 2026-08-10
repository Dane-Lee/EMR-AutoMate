"""Regression tests for the never-draft-anyone-twice guarantee.

Run:  python test_dedup.py          (exit 0 = all pass)

WHY THIS FILE EXISTS
--------------------
On 2026-08-10 a batch from 2026-07-31 — already 34 of 36 entered — was still sitting
in encounters.csv. A plain run entered it again from row 1 and created a SECOND draft
for two people before the browser was closed. Two duplicate records about two real
employees, in a medical system, from a tool whose entire safety model is "drafts only,
nothing twice".

The audit log had every fact needed to prevent it. Nothing consulted it:

  * `--resume` scoped its saved-set to max(run_started) — the LAST run only. Resuming
    that file would have dropped the 2 rows saved that morning and handed back 34 rows
    to enter a second time.
  * Nothing at all checked, before entry, whether a row had already been entered. Every
    other pre-flight check asks whether a row CAN be entered.

FAKE DATA ONLY. Every name here is a project placeholder (see CLAUDE.md). The fixtures
are written to a temp directory and the module's file constants are pointed at them, so
a run of this file never reads or writes the real encounters.csv or encounter_log.csv.
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ati_coaching_encounter as a

PEOPLE = ["Smith, Jane", "Doe, John", "Roe, Richard", "Poe, Paula", "Moe, Marvin"]
DATE = "07/31/2026"
COACHING_TYPE = "Health/Wellness Coaching"
DESCRIPTION = ("EIS reviewed stretching technique with the employee and confirmed "
               "understanding before returning them to the line.")

_TMP = tempfile.mkdtemp(prefix="emr_dedup_test_")
ENC = os.path.join(_TMP, "encounters.csv")
LOG = os.path.join(_TMP, "encounter_log.csv")
BAK = os.path.join(_TMP, "encounters.bak.csv")
a.ENCOUNTERS_CSV, a.ENCOUNTER_LOG_CSV, a.ENCOUNTERS_BAK_CSV = ENC, LOG, BAK

_FAILURES = []
_POPUPS = []


def _fake_popup(msg, yes_no=False, title=""):
    """Stand-in for the Windows dialog: records the call, answers `_fake_popup.answer`."""
    _POPUPS.append({"title": title, "yes_no": yes_no, "msg": msg})
    return _fake_popup.answer


_fake_popup.answer = True
a.popup = _fake_popup


def write_encounters(names):
    with open(ENC, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=a.CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for name in names:
            row = {c: "" for c in a.CSV_COLUMNS}
            row.update(employee=name, date=DATE, coaching_type=COACHING_TYPE,
                       description=DESCRIPTION)
            w.writerow(row)


def write_log(entries):
    """entries: (run_started, employee, status)"""
    with open(LOG, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=a.ENCOUNTER_LOG_COLUMNS)
        w.writeheader()
        for i, (run, name, status) in enumerate(entries, 1):
            w.writerow({"run_started": run, "logged_at": run, "row": i,
                        "employee": name, "matched_to": name,
                        "coaching_type": COACHING_TYPE, "date": DATE,
                        "status": status, "note": ""})


def rows_left():
    with open(ENC, newline="", encoding="utf-8-sig") as fh:
        return [r["employee"] for r in csv.DictReader(fh)
                if any((v or "").strip() for v in r.values())]


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")
        _FAILURES.append(label)


def saved(run, names):
    return [(run, n, "saved") for n in names]


# ── --resume ─────────────────────────────────────────────────────────────────

def test_resume_drops_saves_from_every_run():
    """THE 2026-08-10 BUG. A batch part-entered on one day and re-run on another.

    Old behaviour: only the last run's saves were dropped, so rows entered days
    earlier came back and were drafted again.
    """
    print("\n--resume drops rows saved by ANY run, not just the last")
    write_encounters(PEOPLE)
    write_log(saved("2026-07-31 15:39:41", PEOPLE[:3]) +
              saved("2026-08-10 09:55:50", PEOPLE[:2]))
    a.resume_batch()
    check("only the never-saved rows remain", rows_left(), PEOPLE[3:])


def test_resume_keeps_errored_rows():
    """An errored row entered nothing — the debug captures show those die before the
    form is reached — so it must survive a resume."""
    print("\n--resume keeps errored and unmatched rows")
    write_encounters(PEOPLE[:3])
    write_log([("2026-08-10 09:55:50", PEOPLE[0], "saved"),
               ("2026-08-10 09:55:50", PEOPLE[1], "error"),
               ("2026-08-10 09:55:50", PEOPLE[2], "name-unmatched")])
    a.resume_batch()
    check("errored + unmatched kept", rows_left(), PEOPLE[1:3])


def test_resume_is_idempotent():
    """Run it twice and the second pass must not eat a different helping."""
    print("\n--resume is idempotent")
    write_encounters(PEOPLE[:3])
    write_log(saved("2026-08-10 09:55:50", [PEOPLE[0]]))
    a.resume_batch()
    first = rows_left()
    a.resume_batch()
    check("unchanged on the second pass", rows_left(), first)


def test_resume_on_empty_batch():
    print("\n--resume on an empty batch says so, and changes nothing")
    write_encounters([])
    write_log(saved("2026-08-10 09:55:50", [PEOPLE[0]]))
    a.resume_batch()
    check("still empty", rows_left(), [])


# ── the pre-entry gate ───────────────────────────────────────────────────────

def test_wholly_stale_batch_refuses_to_enter():
    """A finished batch left on disk must not be enterable, even by saying yes."""
    print("\nA wholly already-entered batch refuses to enter")
    write_encounters(PEOPLE[:3])
    write_log(saved("2026-07-31 15:39:41", PEOPLE[:3]))
    _POPUPS.clear()
    _fake_popup.answer = True          # a 'yes' must not rescue it
    check("returns None — nothing to enter", a.prepare_batch(), None)
    check("popup was informational, not a yes/no", _POPUPS[-1]["yes_no"], False)
    check("title names the problem", "already entered" in _POPUPS[-1]["title"], True)


def test_partial_overlap_declined():
    print("\nPartial overlap, declined -> nothing entered")
    write_encounters(PEOPLE[:3])
    write_log(saved("2026-07-31 15:39:41", [PEOPLE[0]]))
    _POPUPS.clear()
    _fake_popup.answer = False
    check("returns None", a.prepare_batch(), None)
    check("was a yes/no prompt", _POPUPS[-1]["yes_no"], True)


def test_partial_overlap_accepted():
    print("\nPartial overlap, accepted -> only the fresh rows are entered")
    write_encounters(PEOPLE[:3])
    write_log(saved("2026-07-31 15:39:41", [PEOPLE[0]]))
    _POPUPS.clear()
    _fake_popup.answer = True
    batch = a.prepare_batch()
    check("the entered row was dropped",
          [e["employee_search"] for e in batch], PEOPLE[1:3])


def test_clean_batch_is_not_nagged():
    """A genuinely fresh batch must not gain an extra popup — a gate that cries wolf
    gets clicked through, and then it protects nothing."""
    print("\nA clean batch sees no already-entered warning")
    write_encounters(PEOPLE[:3])
    write_log(saved("2026-07-31 15:39:41", ["Nobody, Here"]))
    _POPUPS.clear()
    _fake_popup.answer = True
    batch = a.prepare_batch()
    check("all rows returned", len(batch), 3)
    check("exactly one popup — the batch confirm", len(_POPUPS), 1)
    check("and it is the batch confirm",
          "confirm this batch" in _POPUPS[0]["title"], True)


def test_repeat_encounter_same_day_is_flagged():
    """Same person, same date, same type is treated as already-entered. That is the
    intended trade: a genuine same-day repeat gets one question, whereas the opposite
    default silently duplicates a medical record."""
    print("\nSame person/date/type is treated as a repeat")
    write_encounters([PEOPLE[0]])
    write_log(saved("2026-07-31 15:39:41", [PEOPLE[0]]))
    encounters, _ = a.load_encounters_csv(ENC)
    check("flagged", a.already_saved_rows(encounters)[0], [1])


# ── key normalisation ────────────────────────────────────────────────────────

def test_whitespace_is_normalised():
    """log_encounter() strips the name before writing; the CSV may not have. If the two
    sides disagree the dedup silently misses and the duplicate goes in."""
    print("\nPadded CSV names still match the stripped log")
    write_encounters(["  Smith, Jane  "])
    write_log(saved("2026-07-31 15:39:41", ["Smith, Jane"]))
    encounters, _ = a.load_encounters_csv(ENC)
    check("padded name matches", a.already_saved_rows(encounters)[0], [1])


def test_empty_batch_flags_nothing():
    print("\nAn empty batch flags nothing")
    check("no rows, no runs", a.already_saved_rows([]), ([], []))


def test_no_log_file_is_survivable():
    """A fresh install has no audit log. That must not crash the pre-flight."""
    print("\nA missing audit log is survivable")
    missing = os.path.join(_TMP, "does_not_exist.csv")
    real, a.ENCOUNTER_LOG_CSV = a.ENCOUNTER_LOG_CSV, missing
    try:
        check("no keys, no crash", a._saved_keys_by_run(), {})
        check("nothing flagged", a.already_saved_rows([]), ([], []))
    finally:
        a.ENCOUNTER_LOG_CSV = real


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
