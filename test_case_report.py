"""Tests for the Case List report (case_report.py, 2026-09-08).

Run:  python test_case_report.py          (exit 0 = all pass)

WHAT THESE PROTECT
------------------
1. !! DOB IS NOT THE ENCOUNTER DATE. The EMR puts both in the same Employee cell:
   `DOB:` first, `ID:` second, `Enc.D. :` third. A parser that read by position and
   slipped one would file every case under a date of birth, in a document that goes to
   ATI. The fixture's first row has a REAL date in the DOB slot precisely so a
   positional read fails loudly here instead of quietly there. A row with no `Enc.D.`
   pair at all must come back dateless, never with the nearest date it could find.

2. THE SHAPE DANE ASKED FOR (2026-09-08): date -> case type -> coaching type -> name.
   Coaching Encounters lead each date; assessments get NO coaching-type level, because
   they have no coaching type and a heading that says nothing is worse than no heading.

3. ALPHABETICAL MEANS BY SURNAME, INCLUDING THE EMR'S NICKNAMES. The EMR writes
   'Poe, William "Will"', and a naive sort puts the quote character between letters.

4. BOTH ENDS OF THE RANGE ARE INCLUDED, and an undated row is dropped rather than
   filed under a date it never had.

5. BOTH WRITERS PRODUCE A FILE, including for an empty range — a report that says
   "no cases" is a result; a crash is not.

6. THE PARSER STILL FITS THE REAL PAGE. It is run against the scrubbed capture the
   selectors were derived from, which has the real structure and no real text: it must
   still find ten rows and every field, and must find NO dates there (the labels are
   redacted in a capture) rather than falling back to something that parses.

FAKE DATA ONLY — "Smith, Jane" / "Doe, John" / "Roe, Richard", per CLAUDE.md.
Needs no browser and no EMR.
"""

import glob
import io
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import case_report as cr

fails = []


def check(label, cond):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        fails.append(label)


D1, D2, D3 = date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 10)


def mk(d, case_type, coaching, name, status="Completed"):
    return {"date": d, "case_type": case_type, "coaching_type": coaching,
            "name": name, "status": status}


ROWS = [
    mk(D1, "Coaching Encounter", "Safety Coaching", "Smith, Jane"),
    mk(D1, "Coaching Encounter", "Safety Coaching", "Doe, John"),
    mk(D1, "Coaching Encounter", "Ergonomic Adjustment", "Roe, Richard"),
    mk(D1, "Physical Assessment", "", "Doe, John"),
    mk(D2, "Coaching Encounter", "", "Smith, Jane", "InProgress"),
    mk(D2, "PA Follow-Up", "", "Roe, Richard"),
    mk(D3, "Coaching Encounter", "Safety Coaching", "Doe, John"),
]


# ── the fixture: the measured markup, with fake people in it ────────────────
def _row(name, dob, ident, enc, chip, case_id, provider, loc):
    enc_pair = (f'<div><span class="title">Enc.D. :</span>'
                f'<span class="value">{enc}</span></div>') if enc else ""
    return f"""
  <div class="data-row">
    <div class="data-row-col profile-row"><div class="profile">
      <div class="initials">XX</div>
      <div>
        <div class="name"> {name}</div>
        <div><span class="title">DOB :</span><span class="value">{dob}</span></div>
        <div><span class="title">ID :</span><span class="value">{ident}</span></div>
        {enc_pair}
      </div>
    </div></div>
    <div class="data-row-col case-type-row"><div class="case-type-content">
      <div class="case-id">{case_id}</div>
      <div><div class="chipButton"><div class="chipText">{chip}</div>
        <div class="d-none"><span class="closeButton align-middle">x</span></div>
      </div></div>
    </div></div>
    <div class="data-row-col"><div class="text-ellipsis name-cell">{provider}</div></div>
    <div class="data-row-col follow-up">0</div>
    <div class="data-row-col location"><div class="text-ellipsis">{loc}</div></div>
    <div class="data-row-col"><a href="/cases/summary?id=abc-123">
      <button class="btn btn-secondary overview-btn">Case Overview</button></a></div>
    <div class="data-row-col action-row"><div class="action-hamburger">
      <img alt="menu" id="action-button" src="/x.svg"></div></div>
  </div>"""


FIXTURE = f"""<div class="table-container caselist-table">
 <div class="table-header-row">
   <div class="header-column profile-row">Employee</div>
   <div class="header-column case-type-row">Case Info</div>
   <div class="header-column">Provider Name</div>
   <div class="header-column follow-up">Follow-up</div>
   <div class="header-column">Location</div>
   <div class="header-column"></div>
   <div class="header-column action-row"></div>
 </div>
 <div class="table-body">
   {_row("Smith, Jane", "Mar 04 1988", "10001-Weld-1st", "Sep 02 2026", "CE",
         "CS-00000012345", "Lee, Dane", "Navarre")}
   {_row("Doe, John", "--", "10002-Assembler-2nd", "Sep 10 2026", "HMA",
         "CS-00000012346", "Lee, Dane", "Navarre")}
   {_row("Roe, Richard", "Jan 01 1990", "10003-Paint-1st", "", "PA",
         "CS-00000012347", "Lee, Dane", "Navarre")}
 </div>
</div>"""


# ── 1. the date comes from its label, never its position ────────────────────
print("\nTHE DATE COMES FROM ITS LABEL, NEVER ITS POSITION")

parsed = cr.parse_case_rows(FIXTURE)
check("all three rows found", len(parsed) == 3)

jane = parsed[0]
check("the Enc.D. value is the date", jane["date"] == date(2026, 9, 2))
check("!! the DOB in the same cell is NOT taken as the date",
      jane["date"] != date(1988, 3, 4))
check("the label it matched is recorded, so a wrong match is visible",
      cr._label_key(jane["date_label"]).startswith("enc"))

richard = parsed[2]
check("!! a row with no Enc.D. pair comes back dateless", richard["date"] is None)
check("...and does not borrow the DOB that IS there", richard["date_raw"] == "")

check("DOB and ID can never satisfy the date match",
      all(k in cr._FORBIDDEN_LABELS for k in ("dob", "id")))

# The accept list was widened 2026-09-08 after a live run matched nothing. Widening it
# is only safe because the forbidden check runs FIRST -- so every birth-date spelling
# anyone might put in that cell has to stay rejected no matter what gets added.
for bad in ("dob", "dateofbirth", "birthdate", "birth", "bday", "born",
            "id", "identifier", "badge", "employeeid", "ssn", "mrn"):
    if cr._is_encounter_date_label(bad):
        check(f"!! '{bad}' must never read as an encounter date", False)
check("no birth-date or identifier spelling can be read as the encounter date",
      not any(cr._is_encounter_date_label(b) for b in
              ("dob", "dateofbirth", "birthdate", "birth", "bday", "born", "id",
               "identifier", "badge", "employeeid", "ssn", "mrn")))
check("the labels that DO mean an encounter date are accepted",
      all(cr._is_encounter_date_label(k) for k in
          ("encd", "encdate", "encounterdate", "date", "dateofservice", "dos")))

print("\nTHE REST OF THE ROW")
check("employee name, leading space trimmed", jane["name"] == "Smith, Jane")
check("case type is the chip", [r["case_type"] for r in parsed] == ["CE", "HMA", "PA"])
check("coaching type is blank — it is not on this page",
      all(r["coaching_type"] == "" for r in parsed))
check("case id", jane["case_id"] == "CS-00000012345")
check("location", jane["location"] == "Navarre")
check("the third column is carried under the header the page gives it",
      jane["extra"] == "Lee, Dane" and jane["extra_label"] == "Provider Name")
check("the case link is kept", jane["href"].startswith("/cases/summary?id="))
check("a date with a padded day parses too",
      parsed[1]["date"] == date(2026, 9, 10))

check("PARSER_READY is on now that the markup is measured", cr.PARSER_READY is True)
check("the sidebar selector is the one that was measured",
      "case-list" in cr.CASE_LIST_MENU and "Case List" in cr.CASE_LIST_MENU_FALLBACK)


# ── 2. it still fits the real page ──────────────────────────────────────────
print("\nIT STILL FITS THE PAGE IT WAS MEASURED FROM")

captures = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "debug", "*CASES_01_list.html")))
if not captures:
    print("  SKIP  no debug/*CASES_01_list.html capture present")
else:
    real = cr.parse_case_rows(io.open(captures[-1], encoding="utf-8").read())
    check("finds the ten rows in the real capture", len(real) == 10)
    check("every row has a name and a case type",
          all(r["name"] and r["case_type"] for r in real))
    check("every row has a case link", all(r["href"] for r in real))
    # A capture is scrubbed, so "Enc.D :" is a ‹redacted:n› placeholder and nothing
    # should match. If a date appeared here, the parser found one somewhere it
    # should not have been looking.
    check("!! no dates come out of a scrubbed capture",
          not any(r["date"] for r in real))


# ── 3. the grouping shape ───────────────────────────────────────────────────
print("\nGROUPED THE WAY DANE ASKED (date -> case type -> coaching type)")

grouped = cr.group_rows(ROWS)
check("one block per date, in date order", [d for d, _ in grouped] == [D1, D2, D3])

day1 = dict(grouped[0][1])
check("case types are the second level",
      set(day1) == {"Coaching Encounter", "Physical Assessment"})
check("Coaching Encounter leads its date", grouped[0][1][0][0] == "Coaching Encounter")
check("coaching types are the third level, under Coaching Encounter only",
      set(dict(day1["Coaching Encounter"])) == {"Safety Coaching",
                                                "Ergonomic Adjustment"})
check("an assessment gets no coaching-type level",
      list(dict(day1["Physical Assessment"])) == [""])
check("a Coaching Encounter with no coaching type gets the named blank bucket",
      list(dict(dict(grouped[1][1])["Coaching Encounter"])) == [cr.NO_COACHING_TYPE])


# ── 4. alphabetical, by surname ─────────────────────────────────────────────
print("\nALPHABETISED INSIDE EACH GROUP")

names = [r["name"] for r in
         dict(dict(grouped[0][1])["Coaching Encounter"])["Safety Coaching"]]
check("names sort by surname inside a group", names == ["Doe, John", "Smith, Jane"])

quoted = [mk(D1, "Coaching Encounter", "Safety Coaching", n)
          for n in ['Poe, William "Will"', "Pace, Alice", "Post, Brian"]]
sorted_quoted = [r["name"] for r in dict(dict(cr.group_rows(quoted)[0][1])
                                         ["Coaching Encounter"])["Safety Coaching"]]
check("an embedded nickname doesn't push a name out of order",
      sorted_quoted == ["Pace, Alice", 'Poe, William "Will"', "Post, Brian"])


# ── 5. the date range ───────────────────────────────────────────────────────
print("\nTHE DATE RANGE")

check("both ends are included", len(cr.filter_rows(ROWS, D1, D2)) == 6)
check("outside the range is excluded",
      all(r["date"] <= D2 for r in cr.filter_rows(ROWS, D1, D2)))
check("a single-day range works", len(cr.filter_rows(ROWS, D3, D3)) == 1)
check("an undated row is dropped, not filed under a date it never had",
      cr.filter_rows([{"date": None, "name": "Doe, John"}], D1, D3) == [])

check("MM/DD/YYYY parses", cr.parse_date("09/02/2026") == D1)
check("the EMR's 'Sep 2, 2026' parses", cr.parse_date("Sep 02 2026") == D1)
# The live Case List writes it with NO comma -- "Sep 08 2026" (measured 2026-09-08 by
# diagnose_dates: shape 'Aaa 99 9999' on all 30 rows). That form was missing from
# _DATE_FORMATS and every row came back dateless, which stopped the first real run.
check("the format the Case List ACTUALLY uses parses",
      cr.parse_date("Sep 08 2026") == date(2026, 9, 8))
check("...and its single-digit-day sibling",
      cr.parse_date("Sep 8 2026") == date(2026, 9, 8))
check("the shape helper describes a format, not a date",
      cr.date_shape("Sep 08 2026") == "Aaa 99 9999")
check("a date object passes through", cr.parse_date(D1) == D1)
check("nonsense is None, not today", cr.parse_date("sometime last week") is None)
check("'--' is not a date", cr.parse_date("--") is None)


# ── 6. the counts ───────────────────────────────────────────────────────────
print("\nTHE SUMMARY COUNTS")

stats = cr.summarize(ROWS)
check("total is every row", stats["total"] == 7)
check("distinct employees counts people, not rows", stats["people"] == 3)
check("dates with activity", stats["dates"] == 3)
check("counts by case type", stats["by_case_type"]["Coaching Encounter"] == 5)
check("coaching-type counts cover coaching encounters only",
      sum(stats["by_coaching_type"].values()) == 5)


# ── 7. both writers ─────────────────────────────────────────────────────────
print("\nBOTH WRITERS PRODUCE A FILE")

tmp = tempfile.mkdtemp(prefix="case_report_test_")


def wrote(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


xlsx = cr.write_xlsx(ROWS, os.path.join(tmp, "r.xlsx"), D1, D3, "DEMO")
docx = cr.write_docx(ROWS, os.path.join(tmp, "r.docx"), D1, D3, "DEMO")
check("Excel written", wrote(xlsx))
check("Word written", wrote(docx))

empty_x = cr.write_xlsx([], os.path.join(tmp, "e.xlsx"), D1, D3)
empty_d = cr.write_docx([], os.path.join(tmp, "e.docx"), D1, D3)
check("an empty range still writes an Excel file", wrote(empty_x))
check("an empty range still writes a Word file", wrote(empty_d))

from openpyxl import load_workbook
wb = load_workbook(xlsx)
check("the workbook has the three sheets",
      wb.sheetnames == ["By date", "All rows", "Summary"])
flat = wb["All rows"]
check("the flat sheet has a row per case plus a header", flat.max_row == len(ROWS) + 1)
check("the flat sheet is filterable", flat.auto_filter.ref is not None)
check("no empty optional columns when the rows don't carry them",
      [c.value for c in flat[1]] == ["Date", "Case type", "Coaching type",
                                     "Employee", "Status"])

# Parsed rows DO carry location / case id / the third column — those columns appear.
parsed_dated = [r for r in cr.parse_case_rows(FIXTURE) if r["date"]]
px = cr.write_xlsx(parsed_dated, os.path.join(tmp, "p.xlsx"),
                   date(2026, 9, 1), date(2026, 9, 30), "Navarre")
pflat = load_workbook(px)["All rows"]
check("Location and the page's own third column reach the flat sheet",
      [c.value for c in pflat[1]] == ["Date", "Case type", "Coaching type", "Employee",
                                      "Status", "Location", "Provider Name", "Case ID"])

from docx import Document
styles = [p.style.name for p in Document(docx).paragraphs if p.text.strip()]
check("Word uses real headings, so it folds in a report",
      "Heading 1" in styles and "Heading 2" in styles and "List Bullet" in styles)

for p in (xlsx, docx, empty_x, empty_d, px):
    os.remove(p)
os.rmdir(tmp)


# ── 8. finding and opening the finished file ────────────────────────────────
print("\nFINDING THE FINISHED FILE")

import time

box = tempfile.mkdtemp(prefix="case_report_find_")
check("nothing to open in an empty folder", cr.newest_report(box) is None)

# A "both" run writes the Word file SECOND. Max-by-mtime would hand back the .docx;
# the workbook is the one worth opening, so the tie has to break toward .xlsx.
open(os.path.join(box, "case_report_a_to_b.xlsx"), "w").close()
time.sleep(0.05)
open(os.path.join(box, "case_report_a_to_b.docx"), "w").close()
check("a both-run hands back the workbook, not the newer Word file",
      cr.newest_report(box).endswith(".xlsx"))

old = os.path.join(box, "case_report_old.xlsx")
open(old, "w").close()
os.utime(old, (1, 1))                       # 1970: unmistakably an earlier run
check("an older run doesn't win", not cr.newest_report(box).endswith("old.xlsx"))
for f in os.listdir(box):
    os.remove(os.path.join(box, f))
os.rmdir(box)


# ── 9. the In Progress modal is answered before navigating ──────────────────
print("\nTHE IN PROGRESS MODAL IS CLEARED FIRST")

# Dane, 2026-09-08: after login the EMR asks "navigate to the In Progress case list?"
# and it sits over the page until answered. It swallows the sidebar click, so the
# reader has to say No first -- and Yes would page through drafts, not cases.
import inspect

src = inspect.getsource(cr.open_case_list)
check("open_case_list dismisses it before clicking the sidebar",
      src.index("dismiss_in_progress_prompt(page)") < src.index("CASE_LIST_MENU"))
check("and again after arriving on the list",
      src.count("dismiss_in_progress_prompt(page)") >= 2)

import ati_coaching_encounter as ace
check("the dismisser it reuses is the entry engine's, not a second copy",
      callable(getattr(ace, "dismiss_in_progress_prompt", None)))


# -- the specialist filter -------------------------------------------------
print("\nTHE SPECIALIST FILTER")

# Dane, 2026-09-08: the Case List mixes in OTHER specialists' cases, out of order,
# which both breaks the newest-first early stop and makes the walk unbounded. So the
# filter is not a convenience and a report must refuse to run without it.
import asyncio
try:
    asyncio.run(cr.run_report(D1, D2, specialist=""))
    check("!! a report refuses to run unfiltered", False)
except cr.FilterProblem:
    check("!! a report refuses to run unfiltered", True)
except Exception as exc:
    check(f"a report refuses to run unfiltered (got {type(exc).__name__})", False)

OPTIONS = ["Ashby, Dana", "Doe, John", "Roe, Richard", "Smith, Jane"]
check("a name matches however it is written",
      cr.match_specialist("John Doe", OPTIONS) == 1
      and cr.match_specialist("Doe, John", OPTIONS) == 1)
check("a middle name in the EMR's spelling still matches",
      cr.match_specialist("John Doe", ["Doe, John Michael", "Roe, Richard"]) == 0)
check("!! an ambiguous name picks nobody rather than guessing",
      cr.match_specialist("Doe", ["Doe, John", "Doe, Jane"]) is None)
check("a name that isn't there matches nothing",
      cr.match_specialist("Nobody, Alex", OPTIONS) is None)
check("an empty name matches nothing", cr.match_specialist("", OPTIONS) is None)


# ── 10. names never reach stdout ────────────────────────────────────────────
print("\nSTDOUT STAYS CLEAN")

printable = " ".join(str(v) for v in cr.summarize(ROWS).values())
check("the summary carries counts and categories, never a name",
      not any(n in printable for n in ("Smith", "Doe", "Roe")))


print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
