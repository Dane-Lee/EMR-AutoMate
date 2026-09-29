"""Regression tests for library_additions.json — the builder's second description source.

Run:  python test_library_additions.py          (exit 0 = all pass)

WHAT THESE PROTECT
------------------
Dane asked (2026-09-16) that any description written for him show up in the builder's
Library dialog under the right tab, so he can find it later without going through chat.
The builder's dialog reads `EMR Easy Enter Worksheets.xlsx`, which is his own file and
usually open in Excel, so additions live in a JSON file loaded alongside it.

1. A BROKEN FILE MUST NOT STOP THE BUILDER. The library is a convenience; the batch is
   the job. Malformed JSON, a dict where a list belongs, an entry with no text — each
   drops out quietly and the builder still opens.
2. ENTRIES MUST LOOK LIKE WORKBOOK ENTRIES. Every consumer reads tab/label/hint/text off
   these dicts. A missing key is an AttributeError in the middle of the Library dialog.
3. NO SILENT DUPLICATES. The whole point of use-it / adapt-it / write-it is a library
   that doesn't grow three versions of one description.

FAKE DATA ONLY. Writes to a temp directory, never to the project's own file.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import encounter_builder as eb

fails = []
def check(label, cond):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        fails.append(label)

tmp = tempfile.mkdtemp(prefix="libadd_")
path = os.path.join(tmp, "library_additions.json")

print("\nWriting and reading one back")
wrote = eb.append_library_addition(
    {"tab": "Target-H&W", "label": "Hydration and magnesium",
     "text": "EIS and EE discussed hydration through the shift and the role magnesium "
             "plays in muscle cramping."}, path=path)
check("append reports it wrote", wrote is True)

entries = eb.load_additions(path)
check("one entry comes back", len(entries) == 1)
e = entries[0]
check("it carries the four keys every consumer reads",
      all(k in e for k in ("tab", "label", "hint", "text")))
check("the tab is preserved, so it files under the right category",
      e["tab"] == "Target-H&W")
check("it is stamped with a date, not the word 'added'",
      e["added"] and e["added"] != "added")

print("\nThe same text twice is not an addition")
again = eb.append_library_addition(
    {"tab": "Target-H&W", "label": "Different label, same words",
     "text": "EIS and EE discussed hydration through the shift and the role magnesium "
             "plays in muscle cramping."}, path=path)
check("a duplicate is refused", again is False)
check("and nothing was appended", len(eb.load_additions(path)) == 1)

print("\nAn adapted entry records what it came from")
eb.append_library_addition(
    {"tab": "Target-H&W", "label": "Hydration, heat index day",
     "text": "EIS and EE discussed hydration and electrolytes through the shift on a "
             "high heat index day.",
     "from": "Hydration and magnesium"}, path=path)
adapted = [x for x in eb.load_additions(path) if x["label"].endswith("heat index day")]
check("the source entry is named in `from`",
      len(adapted) == 1 and adapted[0]["from"] == "Hydration and magnesium")
check("`hint` is left empty rather than holding provenance", adapted[0]["hint"] == "")

print("\nA broken file never stops the builder")
open(path, "w", encoding="utf-8").write("{ this is not json")
check("malformed JSON reads as no additions", eb.load_additions(path) == [])
json.dump({"tab": "Target-H&W"}, open(path, "w", encoding="utf-8"))
check("a dict where a list belongs reads as no additions", eb.load_additions(path) == [])
json.dump([{"tab": "Target-H&W"}, {"text": "no tab, no home"}, "not a dict",
           {"tab": "Target-H&W", "text": "a real one, long enough to be a description."}],
          open(path, "w", encoding="utf-8"))
kept = eb.load_additions(path)
check("entries with no text or no tab drop out, the good one stays", len(kept) == 1)
check("a missing label falls back to the tab", kept[0]["label"] == "Target-H&W")
check("a missing file reads as no additions",
      eb.load_additions(os.path.join(tmp, "nope.json")) == [])

print("\nAn entry with nothing to file is refused outright")
try:
    eb.append_library_addition({"tab": "Target-H&W", "text": "   "}, path=path)
    check("empty text raises", False)
except ValueError:
    check("empty text raises", True)
try:
    eb.append_library_addition({"text": "words, but no tab to file them under"}, path=path)
    check("a missing tab raises", False)
except ValueError:
    check("a missing tab raises", True)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
