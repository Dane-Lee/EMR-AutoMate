"""Regression tests for dictated_batch.json — a batch dictated in chat, read by the builder.

Run:  python test_dictated_batch.py          (exit 0 = all pass)

WHAT THESE PROTECT
------------------
This file is written by a MODEL, which makes it the least trusted input the builder has.
Everything in it that can reach a medical record is checked against the EMR's own lists
first, and what fails is refused rather than corrected:

1. A COACHING TYPE THAT ISN'T AN EMR VALUE DROPS THE ROW. It is the clinical
   classification of the encounter; a near-miss spelling is not a reason to guess which
   one was meant.
2. A DETAIL BOX THAT ISN'T AN OPTION FOR THAT TYPE IS DROPPED AND REPORTED. A ticked box
   Dane didn't mean is a controlled value in someone's record. Silence is the failure
   mode that matters here, so the dropped names come back for the confirm dialog.
3. REFS SURVIVE EXACTLY AS WRITTEN. The ref is the only link between the text and the
   person it belongs to, and that mapping lives on Dane's side. Renumbering it silently
   would put one person's encounter on another.

FAKE DATA ONLY. Writes to a temp directory, never to the project's own file.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import encounter_builder as eb
import ati_coaching_encounter as ace

fails = []
def check(label, cond):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        fails.append(label)

tmp = tempfile.mkdtemp(prefix="dictated_")
path = os.path.join(tmp, "dictated_batch.json")

def write(rows, wrapper=True):
    payload = {"written": "2026-09-17", "rows": rows} if wrapper else rows
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

# A real type and two of its real boxes, read off the EMR's own map.
GOOD_TYPE = "Health/Wellness Coaching"
GOOD_BOXES = sorted(ace.CHECKBOX_UUID_MAP[GOOD_TYPE])[:2]

print("\nA clean batch comes through intact")
write([{"ref": 1, "coaching_type": GOOD_TYPE, "details": GOOD_BOXES,
        "description": "EIS and EE discussed hydration through the shift.",
        "library": "Hydration and magnesium"},
       {"ref": 2, "coaching_type": "Safety Coaching", "details": [],
        "description": "EIS spoke with EE about the heat in their work area."}])
rows, problems = eb.load_dictated_batch(path)
check("both rows load", len(rows) == 2 and not problems)
check("refs survive as written", [r["ref"] for r in rows] == ["1", "2"])
check("the detail boxes survive", rows[0]["details"] == GOOD_BOXES)
check("the library entry it came from is kept",
      rows[0]["library"] == "Hydration and magnesium")
check("group size defaults to one", rows[0]["group_size"] == 1)

print("\nAn off-list coaching type is refused, not corrected")
write([{"ref": 1, "coaching_type": "Wellness Coaching",   # not an EMR value
        "description": "EIS and EE discussed hydration."},
       {"ref": 2, "coaching_type": "", "description": "EIS and EE discussed sleep."},
       {"ref": 3, "coaching_type": GOOD_TYPE, "description": ""}])
rows, problems = eb.load_dictated_batch(path)
check("no row survives", rows == [])
check("each is reported against its own ref",
      [r for r, _ in problems] == ["1", "2", "3"])
check("the refused value is named back", "Wellness Coaching" in problems[0][1])
check("an empty description is its own problem", "description" in problems[2][1])

print("\nA detail box that isn't an option for that type is dropped and reported")
write([{"ref": 7, "coaching_type": GOOD_TYPE,
        "details": [GOOD_BOXES[0], "Ladder Safety"],
        "description": "EIS and EE discussed hydration through the shift."}])
rows, problems = eb.load_dictated_batch(path)
check("the row still loads", len(rows) == 1)
check("the real box is kept", rows[0]["details"] == [GOOD_BOXES[0]])
check("the invented one is dropped", "Ladder Safety" not in rows[0]["details"])
check("and comes back to be shown in the confirm dialog",
      rows[0]["dropped"] == ["Ladder Safety"])

print("\nCase and shape of the input don't decide a controlled value")
write([{"ref": 8, "coaching_type": GOOD_TYPE,
        "details": GOOD_BOXES[0].upper(),          # a string, not a list; wrong case
        "description": "EIS and EE discussed hydration through the shift."}])
rows, _ = eb.load_dictated_batch(path)
check("a semicolon string is read as details, matched case-insensitively",
      rows and rows[0]["details"] == [GOOD_BOXES[0]])

print("\nA broken file is reported, never guessed at")
open(path, "w", encoding="utf-8").write("{ not json")
rows, problems = eb.load_dictated_batch(path)
check("malformed JSON yields no rows and one problem",
      rows == [] and len(problems) == 1)
write({"nope": 1}, wrapper=False)
rows, problems = eb.load_dictated_batch(path)
check("a payload with no rows is reported", rows == [] and problems)
write([{"ref": 1, "coaching_type": GOOD_TYPE,
        "description": "EIS and EE discussed hydration."}], wrapper=False)
rows, problems = eb.load_dictated_batch(path)
check("a bare list of rows is accepted too", len(rows) == 1)
check("a missing file is silence, not an error",
      eb.load_dictated_batch(os.path.join(tmp, "nope.json")) == ([], []))

print("\nThe file is archived, not deleted, once its rows are in")
write([{"ref": 1, "coaching_type": GOOD_TYPE,
        "description": "EIS and EE discussed hydration."}])
dest = eb.archive_dictated_batch(path)
check("it was renamed", dest and os.path.exists(dest) and not os.path.exists(path))
check("and the same batch can't be imported twice",
      eb.load_dictated_batch(path) == ([], []))
check("archiving nothing is not an error", eb.archive_dictated_batch(path) is None)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
