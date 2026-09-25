"""Turn the assessment rows of Dane's tracking workbook into a hand-entry worksheet.

    python assessments_to_workbook.py

The entry engine only ever clicks the Coaching Encounter tile, so every physical
assessment and follow-up in the workbook is entered by hand. This writes them into
`pa_workbook.py`'s one-sheet-per-assessment layout, in the order the EMR asks for the
fields, so Dane copies cells into the form instead of being walked through six pages.

WHAT THIS DELIBERATELY DOES NOT WRITE
-------------------------------------
* **Palpation and Observation** come out as `[ bracket slots ]`. They are Dane's own exam
  findings. A template that reads as finished gets pasted without a second look, and an
  invented finding in a medical record is worse than an empty field.
* **Every red-flag field is left empty.** Nothing here writes one as negative and nothing
  clears anyone. Where the dictation brushes against a red-flag list item, that is
  written to `RED_FLAG_REVIEW.txt` — a reviewer's note, never a cell he might paste.
  An absence found by text-matching a description is not an absence found by examining a
  person.
* **Protective recommendations** are not generated. That field is the highest-stakes
  writing in the assessment and it is written with Dane, per `pa_templates.md`.
* **Primary Complaint and Categorize Mechanism** are dropdowns whose option lists are
  only partly recorded. Nothing is guessed into them.

NO NAMES. Each sheet is keyed by Dane's own code plus the workbook tab and row, so he
maps a sheet to a person on his side. Output is gitignored.
"""

import json
import os
import sys
from datetime import date

import pa_workbook
import workbook_to_batches as wtb

_HERE = os.path.dirname(os.path.abspath(__file__))
ASSESSMENTS = os.path.join(wtb.WORK_DIR, "assessments.json")

PALPATION_SLOT = "[ EIS palpation findings ]"
OBSERVATION_SLOT = "[ EIS functional capacity testing — what EE did, under what load, " \
                   "and what happened ]"


def build_records(assessment_rows, written):
    """pa_workbook records, plus [(ref, [touched red-flag items])] for the review list."""
    records, touches, missing = [], [], []
    for rec in assessment_rows:
        key = f"{rec['tab']}#{rec['n']}|{rec['code']}"
        text = written.get(key)
        if not text:
            missing.append(key)
            continue

        ref = f"{rec['code']} {rec['tab']}#{rec['n']}"
        follow = text.get("kind", "follow-up").lower().startswith("follow")
        out = {
            "ref": ref,
            "kind": text.get("kind", "follow-up"),
            "bucket": text.get("bucket", "") or rec.get("optional", ""),
            "title": text.get("title", ""),
            "page2": {"incident": text.get("incident", ""),
                      "palpation": PALPATION_SLOT,
                      "observation": OBSERVATION_SLOT},
            "page6": {"focus": text.get("focus", []),
                      "assessment_type": "PA Follow up" if follow else "Physical Assessment"},
        }
        records.append(out)
        if text.get("touches"):
            touches.append((ref, text["touches"]))
    return records, touches, missing


def write_review(touches, path):
    """The red-flag review list. A prompt to look, never a finding and never a clearance."""
    lines = [
        "RED FLAG REVIEW — items the dictation touches, for Dane to check on page 4.",
        "",
        "This is NOT a finding, NOT a count, and NOT a clearance. It is a list of red-flag",
        "list items that the words in each encounter brush against, so none of them gets",
        "past you while you hand-enter. An absence found by reading a description is not",
        "an absence found by examining a person. Page 4's rule stands: two or more",
        "signs/symptoms can indicate the need for outside referral or urgent transfer, and",
        "that call is yours.",
        "",
        f"Written {date.today().isoformat()}.  {len(touches)} of the assessments touch something.",
        "",
    ]
    for ref, items in touches:
        lines.append(f"  #{ref}")
        for item in items:
            lines.append(f"       - {item}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def main():
    _coaching, assessment, _problems = wtb.read_rows()
    rows = wtb.assessment_rows(assessment)

    with open(ASSESSMENTS, encoding="utf-8") as fh:
        written = {k: v for k, v in json.load(fh).items() if not k.startswith("_")}

    records, touches, missing = build_records(rows, written)
    print(f"assessment rows: {len(rows)}  ->  {len(records)} sheet(s)")
    for key in missing:
        print(f"  ! {key}: no text written yet")
    if not records:
        print("nothing to write.")
        return 1

    dest = os.path.join(wtb.WORK_DIR,
                        f"pa_worksheets_{date.today().strftime('%Y-%m-%d')}.xlsx")
    out = pa_workbook.write_workbook(records, dest)
    print(f"  wrote {os.path.relpath(out, _HERE)}")

    review = write_review(touches, os.path.join(wtb.WORK_DIR, "RED_FLAG_REVIEW.txt"))
    print(f"  wrote {os.path.relpath(review, _HERE)}  ({len(touches)} to check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
