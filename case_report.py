"""
Case List report — what went into the EMR, by date
==================================================
READ-ONLY. Reads the EMR's **Case List** page and writes a local report of the
encounters and assessments in a date range, grouped

    date  ->  case type  ->  coaching type  ->  employee (alphabetical)

as an Excel workbook (openpyxl), a Word document (python-docx), or both. Dane picks
the range and the format in the encounter builder's "Case list report" tab; this
module is what that tab launches.

It navigates and reads. It opens no case for editing, clicks nothing that saves, and
writes nothing back to the EMR — the same standing as `update_employees --report`.

⚠️ THE OUTPUT IS PHI. Every line is a real person on a real date. The files are
gitignored (`case_report*.xlsx` / `case_report*.docx`) and belong on CLAUDE.md's
never-read list. Claude sees counts and category names on stdout; Dane opens the file.


WHAT WAS MEASURED (2026-09-08)
------------------------------
Two captures of the live page, plus four answers from Dane about things a capture
cannot show. Every selector below comes from `debug/20260908_10*_CASES_01_list.html`;
nothing here is inferred from what a case list "usually" looks like.

* The sidebar entry — `.side-menu` carrying `case-list.svg`.
* The row markup — see the ROW MARKUP block further down. Seven columns.
* 🚨 **The encounter date is not a column.** It is a labelled `title`/`value` pair
  inside the Employee cell, labelled **"Enc.D."** — and the employee's **date of
  birth sits in the same block**, two pairs above it. The parser matches on the
  label and refuses `dob`/`id` outright; it never reads by position.
* **The coaching type is not on this page**, and neither is a status. The chip in
  the case-type column carries an abbreviated case type ("HMA", ...) and that is all.
  Dane asked for a coaching-type level; the grouping still has one, but it stays
  empty until that value can be read from somewhere. The only place it could come
  from is each case's own summary page, which has never been captured — so it is not
  written.
* The pager — `.caselist-pagination .ati-paginator`, Previous / page numbers /
  Next, with page-size radios for 10, 20 and 30.

From Dane, and from the --survey run, because no capture answers them:

* 🚨 **A follow-up's own date is NOT on this page.** The row keeps showing the
  case's ORIGINAL Enc.D, so a follow-up entered in the range on an older case is
  invisible here. FOLLOWUP_CAVEAT says so on every report until the case summary page
  is captured and read. Only 104 of 2,211 cases carry follow-ups, and a follow-up is
  always after its case's first date — which is what makes opening them affordable.
* **The list is NOT ordered by the date it shows.** Measured over 2,211 rows: 174
  drops within a page, 5 between pages. So `harvest()` sweeps every page rather than
  stopping early — 74 pages, about two minutes, and no chance of truncating.
* **No date filter** exists on the page, so the range is applied after reading.
* **The specialist filter is mandatory.** Unfiltered the list carries other
  specialists' cases; `run_report` refuses without one.
* Every row is **his own worksite**.

`--capture` is still here and still read-only: it snaps the page and prints a
STRUCTURE CENSUS — tag/class signatures and counts, never text. Run it again if the
EMR changes and the parser starts coming up short.


USAGE
    python case_report.py --capture                     READ-ONLY page probe
    python case_report.py --from 09/01/2026 --to 09/08/2026 --format both
    python case_report.py --demo                        fake rows, real writers
"""

import argparse
import os
import re
import sys
from collections import Counter
from datetime import date, datetime
from html.parser import HTMLParser

import phi_redact

_HERE = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────
# NAVIGATION — measured, see the module docstring
# ─────────────────────────────────────────────

# The sidebar item. The preferred form keys off the icon filename; the fallback keys
# off the class attribute, which literally contains the words "Case List". Both come
# from the same capture, and having two costs nothing — a selector that matches
# nothing is a clean miss, not a wrong click.
CASE_LIST_MENU = '.side-menu:has(img[src*="case-list"])'
CASE_LIST_MENU_FALLBACK = '.side-menu[class*="Case List"]'

# Extra allowlist entries so the NEXT capture of this page shows its own labels
# instead of ‹redacted:9›. Registering a label that turns out not to exist costs
# nothing (an allowlist only ever permits an exact match) — the same reasoning that
# put the assessment tiles into phi_redact.UI_CHROME.
CASE_LIST_VOCAB = [
    # Confirmed present by the 2026-09-08 capture: "Case List", "Employee",
    # "Follow-up", "Encounter Type", "HMA" all came through un-redacted.
    "Case List", "Overview", "Ergo Profile List", "Add Ergo", "Employer",
    "Case Type", "Case Date", "Created", "Created On", "Date Created",
    "Encounter Date", "Date of Service", "Provider", "Specialist",
    "Open", "Closed", "Filter", "Filters", "From", "To", "Start Date", "End Date",
    "Rows per page", "Page", "First", "Last", "Sort",
    # Filter-chip chrome (2026-09-08). One of the four chips filters by specialist,
    # and the reader has to drive it: without it the EMR mixes in other specialists'
    # cases, out of order, and the newest-first early stop stops being sound.
    "Specialist", "Specialists", "Providers", "Case Manager", "Assigned",
    "Apply", "Apply Filters", "Select All", "Deselect All", "Clear All", "Done",
    "Search...", "Type to search", "Case Status", "Follow-up Status", "Follow Up Status",
    "Active Cases", "My Cases", "All Cases", "Unassigned",
    # Second pass. The capture showed a 9-char column header over the case-type
    # column that is NOT "Case Type", and a 13-char header over a column whose value
    # is the same width on all ten rows. An allowlist entry that matches nothing
    # reveals nothing, so guessing WIDE here is free — it is guessing what to TYPE
    # into a form that is forbidden, not guessing what to let through a filter.
    "Case Info", "Case Name", "Case Number", "Case ID", "Case #", "Case Status",
    "Type", "Types", "Case Types", "Visit Type", "Service Type", "Category",
    "Date", "Dates", "Visit Date", "Date of Visit", "Service Date", "Onset Date",
    "Date of Onset", "Reported Date", "Date Reported", "Recorded Date",
    "Date Recorded", "Last Modified", "Modified", "Updated", "Last Updated",
    "Date of Encounter", "Encounter", "Encounters", "Date of Case", "Opened",
    "Date Opened", "Closed Date", "Date Closed", "Due Date", "Next Follow-up",
    "Case Manager", "Provider Name", "Created By", "Entered By", "Assigned To",
    "Case Owner", "Owner", "Author", "Clinician", "Athletic Trainer", "EIS",
    "Location", "Site", "Worksite", "Facility", "Department", "Division", "Shift",
    "Employee ID", "Badge", "Badge ID", "Identifier", "Job Title", "Title",
    "Position", "Supervisor", "Manager", "Hire Date", "Date of Hire", "Gender",
    # Case-type chips. The 2026-09-08 capture showed "HMA" plus 2-char and 6-char
    # chips; these are the plausible codes for the case types the EMR offers.
    "CE", "PA", "OV", "TA", "WR", "FU", "EA", "GC", "PT", "RN",
    "PA F/U", "PA FU", "Ergo", "Coach", "Coaching", "Office", "Injury", "Triage",
    "Intake", "Wellness", "Fitness", "Class", "Group",
    # Pagination / footer chrome.
    "Showing", "Results", "Total", "Total Cases", "No results", "No cases",
    "Next", "Previous", "Prev", "Load more", "Show more", "View", "View All",
    "Case Overview", "Actions", "Export", "Download", "Clear all", "Reset",
]

# ─────────────────────────────────────────────
# THE ROW SCHEMA
# ─────────────────────────────────────────────
# One dict per case on the list:
#   date          datetime.date  — the Date of Encounter (Dane's choice, 2026-09-08)
#   case_type     str            — "Coaching Encounter", "Physical Assessment", ...
#   coaching_type str            — only meaningful on a Coaching Encounter
#   name          str            — EMR display name, "Last, First"
#   status        str            — "Completed" / "InProgress" / "" if the page has none

CASE_TYPE_ORDER = ["Coaching Encounter"]      # leads; everything else alphabetical
NO_CASE_TYPE = "(no case type)"
NO_COACHING_TYPE = "(no coaching type)"


class NeedsCapture(RuntimeError):
    """Raised when the Case List markup has not been measured yet."""


# Measured 2026-09-08 from debug/20260908_10*_CASES_01_list.html — see ROW MARKUP.
PARSER_READY = True

_NEEDS_CAPTURE_MSG = (
    "The Case List page has not been captured yet, so there is no measured markup to "
    "read it with.\n\n"
    "Run the capture once — it opens the page read-only and saves a scrubbed copy to "
    "./debug — then the parser gets written from what the page actually says:\n\n"
    "    python case_report.py --capture"
)

# ─────────────────────────────────────────────
# ROW MARKUP — measured 2026-09-08
# ─────────────────────────────────────────────
# The table is `.caselist-table`; rows are `.data-row` under `.table-body`. Seven
# columns, of which four carry anything the report wants:
#
#   .data-row-col.profile-row  .profile
#       .initials
#       .name                                  "Last, First"
#       <div><span class=title>DOB :   </span><span class=value>--          </span></div>
#       <div><span class=title>ID :    </span><span class=value>99999-Weld-1st</span></div>
#       <div><span class=title>Enc.D : </span><span class=value>Sep 08 2026 </span></div>
#   ^ labels and date format confirmed off the live page 2026-09-08 by diagnose_dates
#     (all 30 rows: labels ['DOB :', 'ID :', 'Enc.D :'], value shape 'Aaa 99 9999').
#   .data-row-col.case-type-row  .case-type-content
#       .case-id
#       .chipButton .chipText                  the case type, ABBREVIATED ("HMA", ...)
#   .data-row-col > .text-ellipsis.name-cell   (header names it; not the date)
#   .data-row-col.follow-up
#   .data-row-col.location > .text-ellipsis
#   .data-row-col > a[href="/cases/summary?id=<uuid>"] button.overview-btn
#   .data-row-col.action-row
#
# 🚨 THE DATE IS A LABELLED PAIR, AND DOB SITS IN THE SAME BLOCK.
# The encounter date is NOT a column — it is the third <span class=title>/<span
# class=value> pair inside the Employee cell, labelled "Enc.D." (Dane, 2026-09-08).
# The FIRST pair in that same block is the employee's DATE OF BIRTH. So this parser
# matches the date BY ITS LABEL and never by position: a positional read that slipped
# by one would file every case under a date of birth, in a document that goes to ATI.
# A row whose "Enc.D." pair cannot be found gets date=None and is counted out loud —
# it never falls back to whatever else is in the cell.
#
# What is NOT on this page: the coaching type, and any status. The chip carries the
# case type only, and abbreviated. Grouping below still has the coaching-type level
# Dane asked for; it simply stays empty until that value can be read from somewhere,
# which would mean opening each case's summary page — never captured, so not written.

CASE_TABLE = ".caselist-table"
ROW_SEL = ".caselist-table .table-body .data-row"
PAGER = ".caselist-pagination .ati-paginator"
PAGE_SIZE_RADIO = 'input[name="ati-paginator-item-dropdown"]'

# Which labelled pair in the Employee cell is the encounter date, normalised by
# _label_key ("Enc.D. :" -> "encd").
#
# Two rules, and the ORDER of them is the safety property: a forbidden label is
# rejected before anything else is considered, so no widening of the accept list can
# ever reach a date of birth. Widening the accept side is therefore cheap; widening
# the forbidden side is what must never be trimmed.
_ENC_DATE_PREFIX = "enc"
_ENC_DATE_KEYS = {"date", "dateofencounter", "encounterdate", "dateofservice",
                  "servicedate", "visitdate", "casedate", "dos", "encdate",
                  # The case summary page's own per-encounter date label is 15
                  # characters and is not "Encounter Date" (14, which does survive
                  # scrubbing on that page's detail block). These are the 15-char
                  # readings; an accept-list entry that matches nothing costs nothing.
                  "assessmentdate", "dateperformed", "performeddate", "datecompleted"}
_FORBIDDEN_LABELS = {"dob", "dateofbirth", "birthdate", "birth", "bday", "born",
                     "id", "identifier", "badge", "badgeid", "empid", "employeeid",
                     "ssn", "mrn"}


def _follow_up_count(text):
    """The Follow-up column as a number. -1 when it isn't one.

    -1, not 0: "no follow-ups" and "we couldn't read the column" must not collapse
    into the same value, because 0 is what decides a row can be trusted from the list
    alone. An unreadable count has to stay visibly unknown.
    """
    digits = re.search(r"\d+", str(text or ""))
    return int(digits.group()) if digits else -1


def _is_encounter_date_label(key):
    """True only for a label that means the date of the encounter."""
    if key in _FORBIDDEN_LABELS:
        return False                        # DOB and ID first, always
    return key.startswith(_ENC_DATE_PREFIX) or key in _ENC_DATE_KEYS


def _label_key(s):
    """'Enc.D. :' -> 'encd', 'DOB:' -> 'dob'. Punctuation and case carry no meaning."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").casefold())


def date_shape(value):
    """'Sep 3, 2026' -> 'Aaa 9, 9999'. A format, not a date.

    A column label is UI chrome and safe to print. A date attached to a person is not.
    So when the parser can't read a date and we need to know what it was looking at,
    what gets reported is the SKELETON: every digit becomes 9, every letter A or a.
    That is enough to add the right strptime format and it reveals nobody's date.
    """
    s = re.sub(r"\d", "9", str(value or ""))
    return re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", s))


def diagnose_dates(rows, where="the Case List"):
    """Why did no date come out? Labels and value shapes only — never a value."""
    labels = Counter(tuple(r.get("profile_labels") or ()) for r in rows)
    matched = [r for r in rows if r.get("date_label")]
    out = [f"WHY NO DATE CAME OUT OF {where.upper()}", "",
           f"rows read: {len(rows)}",
           f"rows where a date LABEL matched: {len(matched)}", "",
           "LABELS FOUND IN THE EMPLOYEE CELL (column labels, not patient data)"]
    for labs, n in labels.most_common(10):
        out.append(f"  {n:4d}  {list(labs)}")
    if matched:
        out += ["", "SHAPE OF THE VALUE UNDER THE MATCHED LABEL",
                "(digits -> 9, letters -> A/a; never the value itself)"]
        for shape, n in Counter(date_shape(r["date_raw"])
                                for r in matched).most_common(10):
            out.append(f"  {n:4d}  {shape!r}")
        out += ["", "The label matched, so the VALUE is what didn't parse — the shape "
                    "above says which strptime format to add to _DATE_FORMATS."]
    else:
        out += ["", "No label matched, so _ENC_DATE_PREFIX / _FORBIDDEN_LABELS are "
                    "what need adjusting — the labels above say to what."]
    return "\n".join(out)


class _DomTree(HTMLParser):
    """The census tree, plus the text of each node. Used to read the live page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "#root", "cls": "", "text": False, "own": [], "kids": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        node = {"tag": tag, "cls": a.get("class") or "", "href": a.get("href", ""),
                "text": False, "own": [], "kids": []}
        self.stack[-1]["kids"].append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        self.stack[-1]["kids"].append({"tag": tag, "cls": a.get("class") or "",
                                       "href": a.get("href", ""), "text": False,
                                       "own": [], "kids": []})

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1]["text"] = True
            self.stack[-1]["own"].append(data)


def _has_class(node, name):
    """Exact class-token match, so 'data-row' never matches 'data-row-col'."""
    return name in node["cls"].split()


def _find(node, name):
    """Every descendant carrying the class token `name`, in document order."""
    for n in _walk(node):
        if n is not node and _has_class(n, name):
            yield n


def _first(node, name):
    return next(_find(node, name), None)


def _text(node):
    """All text under a node, whitespace collapsed. '' for None."""
    if node is None:
        return ""
    parts = []
    for n in _walk(node):
        parts.extend(n["own"])
    return " ".join("".join(parts).split())


def _profile_pairs(profile):
    """The <span class=title>/<span class=value> pairs in the Employee cell.

    Returned as [(label_key, raw_label, value)] in document order — the caller picks
    by label, never by index.
    """
    pairs = []
    for node in _walk(profile):
        kids = node["kids"]
        for i, kid in enumerate(kids):
            if not _has_class(kid, "title"):
                continue
            val = next((v for v in kids[i + 1:] if _has_class(v, "value")), None)
            label = _text(kid)
            pairs.append((_label_key(label), label, _text(val)))
    return pairs


# ─────────────────────────────────────────────
# THE CASE SUMMARY PAGE — measured 2026-09-09
# ─────────────────────────────────────────────
# `/cases/summary?id=<uuid>`. This is where a follow-up's OWN date lives, and it is the
# whole reason the report was under-counting: the Case List shows a case's first date
# and nothing else, so a follow-up entered last week on a February case is invisible
# there. Captured 2026-09-09 (`debug/20260909_*_CASE_summary.html`).
#
#   .detail-row  .row-cell  p.field-label / p.field-value      the CASE's own fields
#       — "Encounter Date", "Location", "Department", "Division", "Category", "Shift"
#         all survive scrubbing, so those labels are confirmed
#   .data-row                                                  ONE PER ENCOUNTER
#       .data-row-cell   p.label (empty) + .chipButton .chipText     the type chip
#       .data-row-cell   p.label / p.value                           <- the date pair
#       .data-row-cell   p.label / p.value.text-ellipsis
#       .data-row-cell   p.label "Location" / p.value.text-ellipsis
#       .data-row-cell.width-25   the row menu
#
# ⚠️ `.data-row` is ALSO the Case List's row class. The two are told apart by their
# children — `.data-row-cell` here, `.data-row-col` there — not by the class itself.
#
# The date is matched by label exactly as on the Case List, through the same
# _is_encounter_date_label, so `dob` can no more be read as a date here than there.

CASE_SUMMARY_ROW_CELL = "data-row-cell"


def parse_case_encounters(html):
    """The encounters listed on one case's summary page, newest date wins nothing.

    Returns one dict per encounter row, same shape as a Case List row minus the
    employee (the summary page doesn't repeat it — the caller carries it across).
    """
    tree = _DomTree()
    tree.feed(html)
    tree.close()

    out = []
    for row in _find(tree.root, "data-row"):
        cells = list(_find(row, CASE_SUMMARY_ROW_CELL))
        if not cells:
            continue                     # a Case List row, not a summary row
        pairs = []
        for cell in cells:
            label = _first(cell, "label")
            value = _first(cell, "value")
            if label is None or value is None:
                continue
            pairs.append((_label_key(_text(label)), _text(label), _text(value)))

        enc_raw, enc_label = "", ""
        for key, label, value in pairs:
            if _is_encounter_date_label(key):
                enc_raw, enc_label = value, label
                break
        location = next((v for k, _, v in pairs if k == "location"), "")

        out.append({
            "date": parse_date(enc_raw),
            "date_raw": enc_raw,
            "date_label": enc_label,
            "case_type": _text(_first(row, "chipText")),
            "coaching_type": "",
            "name": "",                  # filled in by the caller
            "status": "",
            "case_id": "",
            "follow_ups": 0,
            "location": location,
            "extra": "",
            "extra_label": "",
            "href": "",
            "profile_labels": [label for _, label, _ in pairs],
        })
    return out


def parse_case_rows(html):
    """The Case List page -> row dicts. Structure measured 2026-09-08 (see above).

    Reads the LIVE page, so the text is real: this runs inside the browser session,
    not against a scrubbed capture.
    """
    tree = _DomTree()
    tree.feed(html)
    tree.close()

    table = _first(tree.root, "caselist-table") or tree.root
    headers = [_text(h) for h in _find(table, "header-column")]
    # The third column's header is whatever the EMR calls it; we carry the value
    # through under that name rather than deciding what it is.
    extra_label = headers[2] if len(headers) > 2 else ""

    rows = []
    for row in _find(table, "data-row"):
        # The case SUMMARY page uses the same `data-row` class for its encounter rows.
        # The two are told apart by their children — `data-row-col` here, `data-row-cell`
        # there — so require the Case List's shape rather than trusting the class.
        if not next(_find(row, "data-row-col"), None):
            continue
        profile = _first(row, "profile")
        name = _text(_first(profile, "name")) if profile else ""

        pairs = _profile_pairs(profile) if profile else []
        enc_raw, enc_label = "", ""
        for key, label, value in pairs:
            if _is_encounter_date_label(key):
                enc_raw, enc_label = value, label
                break

        link = next((n for n in _walk(row) if n["tag"] == "a" and n["href"]), None)
        rows.append({
            "date": parse_date(enc_raw),
            "date_raw": enc_raw,
            "date_label": enc_label,
            # Labels only — the diagnostic below needs to say WHAT it was looking at
            # when a date doesn't come out, without carrying values around to do it.
            "profile_labels": [label for _, label, _ in pairs],
            "case_type": _text(_first(row, "chipText")),
            "coaching_type": "",            # not on this page — see ROW MARKUP
            "name": name,
            "status": "",                   # ditto
            "case_id": _text(_first(row, "case-id")),
            # How many follow-ups the case has (Dane, 2026-09-08). Load-bearing: a
            # follow-up is entered on its own date but the row keeps showing the
            # ORIGINAL Enc.D, so a row with a non-zero count is a row whose real dates
            # are not on this page. It is also what makes fixing that affordable —
            # only these rows need opening.
            "follow_ups": _follow_up_count(_text(_first(row, "follow-up"))),
            "location": _text(_first(row, "location")),
            "extra": _text(_first(row, "name-cell")),
            "extra_label": extra_label,
            "href": link["href"] if link else "",
        })
    return rows


# ─────────────────────────────────────────────
# DATES
# ─────────────────────────────────────────────

# "%b %d %Y" is the one the Case List actually uses — "Sep 08 2026", NO COMMA.
# Measured 2026-09-08 by diagnose_dates(), which reported the shape 'Aaa 99 9999' for
# all 30 rows on the page. The comma'd form was in this list and the bare one was not,
# so every row came back dateless and the run stopped. The others are kept because
# they cost nothing and the EMR has changed its mind about formats before.
_DATE_FORMATS = ["%b %d %Y", "%b %d, %Y", "%B %d %Y", "%B %d, %Y",
                 "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%d %b %Y"]


def parse_date(raw):
    """Parse a date the EMR or the CLI might hand us. None if it isn't one."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = " ".join(str(raw or "").split())
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def filter_rows(rows, start, end):
    """Rows whose date falls inside [start, end], inclusive.

    Undated rows are dropped: a row with no date cannot be placed under a date
    heading, and filing it under today's would be a fabrication.
    """
    return [r for r in rows if r.get("date") and start <= r["date"] <= end]


# ─────────────────────────────────────────────
# GROUPING + SORTING
# ─────────────────────────────────────────────

def alpha_key(name):
    """Alphabetical key for an EMR display name.

    Names arrive "Last, First" (see update_employees._ROW_RE), so a plain casefold
    already sorts by surname. The EMR also embeds nicknames — 'Poe, William "Will"' —
    and those quotes sort between letters, so they come out before comparing.
    """
    n = re.sub(r'"[^"]*"', " ", str(name or ""))
    return " ".join(n.split()).casefold()


def _case_type_key(ct):
    try:
        return (CASE_TYPE_ORDER.index(ct), "")
    except ValueError:
        return (len(CASE_TYPE_ORDER), ct.casefold())


def _coaching_key(ct):
    return (ct == NO_COACHING_TYPE, ct.casefold())      # the blank bucket sorts last


def group_rows(rows):
    """rows -> [(date, [(case_type, [(coaching_type, [row, ...])])])], fully sorted.

    Dane's shape (2026-09-08): case type first, coaching type nested under it. Only
    Coaching Encounters get a coaching-type level — an assessment has no coaching
    type, and giving it an empty one would print a heading that says nothing. Those
    carry the bucket key "", and the writers render their names directly under the
    case type.
    """
    tree = {}
    for r in rows:
        ct = (r.get("case_type") or "").strip() or NO_CASE_TYPE
        if ct == "Coaching Encounter":
            sub = (r.get("coaching_type") or "").strip() or NO_COACHING_TYPE
        else:
            sub = ""
        tree.setdefault(r["date"], {}).setdefault(ct, {}).setdefault(sub, []).append(r)

    out = []
    for d in sorted(tree):
        types = []
        for ct in sorted(tree[d], key=_case_type_key):
            subs = []
            for sub in sorted(tree[d][ct], key=_coaching_key):
                subs.append((sub, sorted(tree[d][ct][sub],
                                         key=lambda r: alpha_key(r.get("name")))))
            types.append((ct, subs))
        out.append((d, types))
    return out


def summarize(rows):
    """Counts for the summary block — and the only thing stdout is allowed to say."""
    coaching = [r for r in rows
                if (r.get("case_type") or "").strip() == "Coaching Encounter"]
    return {
        "total": len(rows),
        "people": len({alpha_key(r.get("name")) for r in rows if r.get("name")}),
        "dates": len({r["date"] for r in rows if r.get("date")}),
        "by_case_type": Counter((r.get("case_type") or "").strip() or NO_CASE_TYPE
                                for r in rows),
        "by_coaching_type": Counter((r.get("coaching_type") or "").strip()
                                    or NO_COACHING_TYPE for r in coaching),
    }


# ⚠️ WHAT THIS REPORT CANNOT SEE, said out loud wherever it is written.
#
# Dane, 2026-09-08: a follow-up is entered on its own date, but the Case List row keeps
# showing the case's ORIGINAL Enc.D. So a follow-up done last week on a case opened in
# 1990 is invisible to a range filter over the displayed date — it neither appears in
# last week's report nor announces itself.
#
# That is under-reporting, and a report that under-reports silently is worse than one
# that doesn't run: a short list of last week's work looks exactly like a light week.
# So the caveat is stamped on the workbook, the document, and the finishing dialog,
# and it stays there until the follow-up dates can actually be read.
FOLLOWUP_CAVEAT = (
    "Counts cases by their ORIGINAL encounter date (Enc.D on the Case List). "
    "A follow-up entered in this range on an older case is NOT included — the list "
    "shows only the case's first date. The Follow-ups column flags which cases have "
    "them."
)


def followup_note(notes):
    """What the report can honestly say about follow-ups, given how the run went.

    The caveat above is what a run that never opened a case has to admit. A run that
    did open them says so instead — and still says it if some of them failed, because
    "mostly complete" is the kind of thing that has to be on the page rather than in
    someone's memory of how the run went.
    """
    opened = notes.get("opened", 0)
    if not opened:
        return FOLLOWUP_CAVEAT
    note = (f"Follow-up dates were read from the {opened} case(s) that carry them, so a "
            f"follow-up entered in this range on an older case IS included.")
    if notes.get("skipped_after_range"):
        note += (f" {notes['skipped_after_range']} case(s) starting after the range were "
                 f"not opened — a follow-up is always later than its own case.")
    if notes.get("failed"):
        note += (f" ⚠ {notes['failed']} case(s) would not open and are counted by their "
                 f"first date only.")
    if notes.get("undated_cases"):
        note += (f" ⚠ {notes['undated_cases']} case(s) opened with no readable date on "
                 f"their encounter rows.")
    if notes.get("hit_open_cap"):
        note += (f" ⚠ Stopped after {MAX_CASE_OPENS} cases; the rest are counted by "
                 f"their first date only.")
    return note


def _range_label(start, end):
    if start == end:
        return start.strftime("%m/%d/%Y")
    return f"{start.strftime('%m/%d/%Y')} - {end.strftime('%m/%d/%Y')}"


def _long_date(d):
    """'Wednesday, September 2, 2026' — no %-d, which Windows' strftime rejects."""
    return d.strftime("%A, %B ") + str(d.day) + d.strftime(", %Y")


def default_out_path(start, end, ext):
    return os.path.join(_HERE, f"case_report_{start:%Y-%m-%d}_to_{end:%Y-%m-%d}.{ext}")


# ─────────────────────────────────────────────
# EXCEL
# ─────────────────────────────────────────────

def write_xlsx(rows, path, start, end, worksite="", caveat=FOLLOWUP_CAVEAT):
    """Three sheets: the grouped read-it layout, a flat table, and the counts.

    "By date" is the report Dane asked for. "All rows" exists because a grouped
    layout cannot be filtered or pivoted — reading order is the wrong shape for that —
    and it costs five columns. "Summary" is the number a report deadline actually
    wants.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    stats = summarize(rows)
    wb = Workbook()

    title_font = Font(bold=True, size=14)
    sub_font = Font(size=10, color="5D564E")
    date_font = Font(bold=True, size=12, color="FFFFFF")
    date_fill = PatternFill("solid", fgColor="7D4104")
    case_font = Font(bold=True, size=11)
    case_fill = PatternFill("solid", fgColor="F0DFC2")
    coach_font = Font(italic=True, size=11)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="5D564E")
    thin = Side(style="thin", color="BDB5A9")

    # ---- By date -------------------------------------------------------
    ws = wb.active
    ws.title = "By date"
    ws["A1"] = "Case List report"
    ws["A1"].font = title_font
    ws["A2"] = _range_label(start, end)
    ws["A2"].font = Font(bold=True, size=11)
    bits = [f"{stats['total']} case(s)", f"{stats['people']} employee(s)",
            f"{stats['dates']} date(s)"]
    if worksite:
        bits.insert(0, worksite)
    bits.append(f"generated {datetime.now():%m/%d/%Y %H:%M}")
    ws["A3"] = "  |  ".join(bits)
    ws["A3"].font = sub_font
    ws["A4"] = "! " + caveat
    ws["A4"].font = Font(size=10, bold=True, color="7D4104")

    r = 6                       # row 4 is the caveat, row 5 stays blank
    for day, types in group_rows(rows):
        ws.cell(r, 1, _long_date(day))
        for c in range(1, 6):
            ws.cell(r, c).fill = date_fill
            ws.cell(r, c).font = date_font
        r += 1
        for case_type, subs in types:
            n = sum(len(g) for _, g in subs)
            ws.cell(r, 2, f"{case_type}  ({n})")
            ws.cell(r, 2).font = case_font
            for c in range(2, 6):
                ws.cell(r, c).fill = case_fill
            r += 1
            for coaching_type, group in subs:
                if coaching_type:
                    ws.cell(r, 3, f"{coaching_type}  ({len(group)})")
                    ws.cell(r, 3).font = coach_font
                    r += 1
                for row in group:
                    ws.cell(r, 4, row.get("name", ""))
                    ws.cell(r, 5, row.get("status", ""))
                    ws.cell(r, 5).font = sub_font
                    r += 1
        r += 1

    if not rows:
        ws.cell(6, 1, "No cases in this range.")

    for col, width in zip("ABCDE", (30, 34, 34, 34, 14)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A6"

    # ---- All rows ------------------------------------------------------
    # The five core columns are always there so the shape is stable; anything the
    # Case List also carried (Location, its own third column, the case id) is appended
    # only when it actually has values, rather than shipping empty columns.
    from openpyxl.utils import get_column_letter

    flat = wb.create_sheet("All rows")
    extra_label = next((r.get("extra_label") for r in rows if r.get("extra_label")), "")
    optional = [(label, key) for label, key in
                (("Follow-ups", "follow_ups"), ("Location", "location"),
                 (extra_label or "Column 3", "extra"), ("Case ID", "case_id"))
                if any(r.get(key) for r in rows)]
    headers = ["Date", "Case type", "Coaching type", "Employee", "Status"] \
        + [label for label, _ in optional]
    flat.append(headers)
    for i in range(1, len(headers) + 1):
        flat.cell(1, i).font = head_font
        flat.cell(1, i).fill = head_fill
    ordered = sorted(rows, key=lambda x: (
        x["date"],
        _case_type_key((x.get("case_type") or "").strip() or NO_CASE_TYPE),
        alpha_key(x.get("name"))))
    for row in ordered:
        flat.append([row["date"], (row.get("case_type") or "").strip(),
                     (row.get("coaching_type") or "").strip(),
                     row.get("name", ""), row.get("status", "")]
                    + [row.get(key, "") for _, key in optional])
    for cell in flat["A"][1:]:
        cell.number_format = "mm/dd/yyyy"
    for i, width in enumerate((13, 30, 34, 30, 14, 22, 22, 22), start=1):
        if i <= len(headers):
            flat.column_dimensions[get_column_letter(i)].width = width
    if ordered:
        flat.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(ordered) + 1}"
    flat.freeze_panes = "A2"

    # ---- Summary -------------------------------------------------------
    sm = wb.create_sheet("Summary")
    sm["A1"] = "Summary"
    sm["A1"].font = title_font
    sm["A2"] = _range_label(start, end)
    sm["A2"].font = sub_font
    sm["A4"], sm["B4"] = "Cases in range", stats["total"]
    sm["A5"], sm["B5"] = "Distinct employees", stats["people"]
    sm["A6"], sm["B6"] = "Dates with activity", stats["dates"]
    for header_row in (4, 5, 6):
        sm.cell(header_row, 1).font = Font(bold=True)

    # rr is set explicitly, NOT carried out of the loop above: leaking the loop
    # variable put this caveat on top of "Dates with activity" the first time.
    rr = 8
    sm.cell(rr, 1, "! " + caveat).font = Font(size=10, bold=True,
                                                       color="7D4104")
    rr += 2
    if rows and not any((r.get("coaching_type") or "").strip() for r in rows):
        sm.cell(rr, 1, "Coaching type is not shown on the EMR's Case List, so it is "
                       "blank throughout. Case type is the chip the list displays.")
        sm.cell(rr, 1).font = sub_font
        rr += 2
    for heading, counter in (("By case type", stats["by_case_type"]),
                             ("Coaching encounters by coaching type",
                              stats["by_coaching_type"])):
        sm.cell(rr, 1, heading).font = case_font
        rr += 1
        sm.cell(rr, 1, "Category")
        sm.cell(rr, 2, "Count")
        for c in (1, 2):
            sm.cell(rr, c).font = head_font
            sm.cell(rr, c).fill = head_fill
        rr += 1
        for key in sorted(counter, key=lambda k: (-counter[k], k.casefold())):
            sm.cell(rr, 1, key)
            sm.cell(rr, 2, counter[key])
            for c in (1, 2):
                sm.cell(rr, c).border = Border(top=thin)
            rr += 1
        rr += 2

    sm.column_dimensions["A"].width = 44
    sm.column_dimensions["B"].width = 10
    for row_cells in sm.iter_rows(min_col=2, max_col=2):
        for cell in row_cells:
            cell.alignment = Alignment(horizontal="right")

    wb.save(path)
    return path


# ─────────────────────────────────────────────
# WORD
# ─────────────────────────────────────────────

def write_docx(rows, path, start, end, worksite="", caveat=FOLLOWUP_CAVEAT):
    """The same grouped layout as the "By date" sheet, as a document.

    Word gets the reading layout only — a flat table and a pivot belong in Excel, and
    a document Dane pastes into a report wants headings and bullets.
    """
    from docx import Document
    from docx.shared import Pt

    stats = summarize(rows)
    doc = Document()
    doc.add_heading("Case List report", level=0)

    sub = doc.add_paragraph()
    sub.add_run(_range_label(start, end)).bold = True
    bits = [f"{stats['total']} case(s)", f"{stats['people']} employee(s)",
            f"{stats['dates']} date(s)"]
    if worksite:
        bits.insert(0, worksite)
    bits.append(f"generated {datetime.now():%m/%d/%Y %H:%M}")
    tail = sub.add_run("\n" + "  |  ".join(bits))
    tail.font.size = Pt(9)
    note_para = doc.add_paragraph()
    warn = note_para.add_run("! " + caveat)
    warn.bold = True
    warn.font.size = Pt(9)

    if not rows:
        doc.add_paragraph("No cases in this range.")
        doc.save(path)
        return path

    for day, types in group_rows(rows):
        doc.add_heading(_long_date(day), level=1)
        for case_type, subs in types:
            n = sum(len(g) for _, g in subs)
            doc.add_heading(f"{case_type} ({n})", level=2)
            for coaching_type, group in subs:
                if coaching_type:
                    doc.add_heading(f"{coaching_type} ({len(group)})", level=3)
                for row in group:
                    text = row.get("name", "")
                    status = (row.get("status") or "").strip()
                    if status and status.casefold() != "completed":
                        text = f"{text} - {status}"
                    doc.add_paragraph(text, style="List Bullet")

    doc.save(path)
    return path


def open_file(path):
    """Hand the finished report to Windows to open. Never raises.

    Dane asked for this (2026-09-08) rather than hunting the project folder for the
    file every time. It only ever opens what this run just wrote, on his own machine.
    """
    try:
        starter = getattr(os, "startfile", None)     # Windows-only, like the rest
        if starter is None:
            return False
        starter(path)
        return True
    except Exception as exc:
        print(f"  Couldn't open {os.path.basename(path)}: {exc}")
        return False


def newest_report(folder=None):
    """The most recently written case_report file, or None.

    A "both" run writes the Word file second, so a plain max-by-mtime would hand back
    the .docx every time. When the two are from the same run, the workbook is the one
    to open — it carries the flat sheet and the summary as well as the grouped layout.
    """
    import glob as _glob
    folder = folder or _HERE
    found = (_glob.glob(os.path.join(folder, "case_report*.xlsx"))
             + _glob.glob(os.path.join(folder, "case_report*.docx")))
    if not found:
        return None
    newest = max(found, key=os.path.getmtime)
    same_run = [f for f in found if f.endswith(".xlsx")
                and abs(os.path.getmtime(f) - os.path.getmtime(newest)) < 60]
    return max(same_run, key=os.path.getmtime) if same_run else newest


def write_report(rows, start, end, fmt="xlsx", worksite="", out=None,
                 caveat=FOLLOWUP_CAVEAT):
    """Write the chosen format(s). Returns the list of paths written."""
    written = []
    if fmt in ("xlsx", "both"):
        p = out if (out and fmt != "both") else default_out_path(start, end, "xlsx")
        written.append(write_xlsx(rows, p, start, end, worksite, caveat))
    if fmt in ("docx", "both"):
        p = out if (out and fmt != "both") else default_out_path(start, end, "docx")
        written.append(write_docx(rows, p, start, end, worksite, caveat))
    return written


# ─────────────────────────────────────────────
# STRUCTURE CENSUS — how the parser gets measured
# ─────────────────────────────────────────────

_VOID = {"br", "hr", "img", "input", "meta", "link", "source", "col", "area", "base"}


class _ShapeTree(HTMLParser):
    """A minimal DOM: tag, class, whether it held text, and children.

    Fed the SCRUBBED html only. The census reports classes and counts, and the text it
    reports on is already a ‹redacted:N› placeholder.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "#root", "cls": "", "text": False, "kids": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "cls": dict(attrs).get("class", "") or "",
                "text": False, "kids": []}
        self.stack[-1]["kids"].append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = {"tag": tag, "cls": dict(attrs).get("class", "") or "",
                "text": False, "kids": []}
        self.stack[-1]["kids"].append(node)

    def handle_endtag(self, tag):
        # Unwind to the nearest matching open tag; unbalanced markup is normal in a
        # live SPA dump and must not desync the whole tree.
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1]["text"] = True


# Every EMR page carries the whole worksite roster preloaded in the left sidebar —
# 957 rows on the 2026-09-08 capture. That buries the actual page content in the
# census: the "most repeated element" came back as div.initials (969) and the ten-row
# case list never surfaced. Pruned before counting, and the census says it pruned it.
_PRUNE_CLASSES = ("employee-list", "assigned-employee-list", "app-sidebar")


def _prune(node):
    """Copy the tree without the preloaded roster sidebar."""
    kids, dropped = [], 0
    for kid in node["kids"]:
        cls = kid["cls"]
        if any(c in cls for c in _PRUNE_CLASSES):
            dropped += 1 + sum(1 for _ in _walk(kid)) - 1
            continue
        sub, n = _prune(kid)
        kids.append(sub)
        dropped += n
    return {**node, "kids": kids}, dropped


def _sig(node):
    cls = " ".join(node["cls"].split())
    return f"{node['tag']}.{cls}" if cls else node["tag"]


def _walk(node):
    yield node
    for kid in node["kids"]:
        yield from _walk(kid)


def _shape_lines(node, depth=0, max_depth=4, out=None):
    out = [] if out is None else out
    if depth > max_depth:
        return out
    out.append("    " * depth + _sig(node) + ("  [text]" if node["text"] else ""))
    for kid in node["kids"]:
        _shape_lines(kid, depth + 1, max_depth, out)
    return out


def structure_census(scrubbed_html, top=30, out_path=None):
    """Report what the page is made of — signatures and counts, never content.

    This is the aggregate probe the project uses everywhere else (counts, never
    cells), pointed at markup instead of a spreadsheet. It is what lets the parser be
    written from a measurement without anyone reading a name.

    Prints, and with `out_path` also writes the same text to a file. Writing it means
    the measurement can be handed over as a file instead of copied out of a console —
    and it is safe to hand over by construction: the input is already scrubbed, tag
    and class names are structure, and a text node is reported as the marker [text],
    never as its content.
    """
    tree = _ShapeTree()
    tree.feed(scrubbed_html)
    tree.close()

    root, pruned = _prune(tree.root)
    nodes = list(_walk(root))[1:]
    counts = Counter(_sig(n) for n in nodes)

    out = [f"Elements: {len(nodes)}   distinct signatures: {len(counts)}"
           + (f"   ({pruned} more pruned: the preloaded roster sidebar)" if pruned else ""),
           "", "MOST REPEATED SIGNATURES"]
    out += [f"  {n:5d}  {sig}" for sig, n in counts.most_common(top)]

    tables = counts.get("table", 0) + counts.get("tbody", 0)
    if tables:
        out += ["", f"<table>/<tbody> present: {tables} — the list may be a real table "
                    f"({counts.get('tr', 0)} <tr>, {counts.get('td', 0)} <td>)"]

    # The likeliest "row": a CLASSED signature that repeats like a list AND has the
    # most structure under it. Ranking on repetition alone picks the leaf that occurs
    # inside every row (span.title, 31 of them) over the row itself (div.data-row, 10)
    # — the count is higher and the shape is useless.
    subtree = {}
    for n in nodes:
        s = _sig(n)
        if "." in s:
            subtree[s] = max(subtree.get(s, 0), sum(1 for _ in _walk(n)))
    candidates = sorted(((subtree[s], n, s) for s, n in counts.items()
                         if "." in s and n >= 3), reverse=True)
    candidates = [(n, s) for _, n, s in candidates]
    if not candidates:
        out += ["", "No repeated classed element found."]
    for _, sig in candidates[:3]:
        first = next(n for n in nodes if _sig(n) == sig)
        out += ["", f"SHAPE OF  {sig}   ({counts[sig]} of them)"]
        out += ["  " + line for line in _shape_lines(first, max_depth=4)]

    text = "\n".join(out)
    print("\n" + text)
    if out_path:
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"\n  Census written to {out_path}")
        except Exception as exc:
            print(f"  [census] could not write {out_path}: {exc}")
    return counts


# ─────────────────────────────────────────────
# THE BROWSER RUNS (read-only)
# ─────────────────────────────────────────────

async def open_case_list(page):
    """Click the sidebar's Case List item. Returns True if it moved.

    ⚠️ The "There are active encounters saved 'In Progress' — navigate to the In
    Progress case list?" modal pops on the dashboard whenever Dane has drafts, which
    after a batch is essentially always (Dane, 2026-09-08). It sits over the page and
    swallows the sidebar click, so it has to be answered NO first — Yes would navigate
    to the wrong list and the reader would page through drafts instead of cases. The
    dismisser is `ati_coaching_encounter`'s, unchanged: the entry engine has been
    clearing this same modal since 2026-07-23.
    """
    from ati_coaching_encounter import BASE_URL, dismiss_in_progress_prompt

    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")
    await dismiss_in_progress_prompt(page)
    for sel in (CASE_LIST_MENU, CASE_LIST_MENU_FALLBACK):
        item = page.locator(sel).first
        try:
            if await item.count():
                await item.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2500)
                # It can also surface on arrival, over the list itself.
                await dismiss_in_progress_prompt(page)
                print(f"  Opened the Case List via  {sel}")
                return True
        except Exception as exc:
            print(f"  {sel} did not click: {type(exc).__name__}")
    print("  Could not find the Case List item in the sidebar.")
    return False


async def run_capture():
    """READ-ONLY probe of the Case List page: snap it, then census it.

    Opens the page, saves the scrubbed HTML to ./debug, and prints the structure
    census. It writes no report and changes nothing in the EMR.
    """
    from playwright.async_api import async_playwright

    from ati_coaching_encounter import popup, snap
    from update_employees import _open_browser, read_worksite

    phi_redact.register_vocab(CASE_LIST_VOCAB)

    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            site = await read_worksite(page)
            print(f"\nHeader worksite: {site or '(could not read)'}")
            if not await open_case_list(page):
                await snap(page, "CASES_00_no_menu")
                popup("Could not find 'Case List' in the sidebar. The dashboard was "
                      "captured to ./debug (scrubbed) so the menu can be re-measured."
                      "\n\nNothing was changed.",
                      title="EMR AutoMate — case list probe")
                return

            await snap(page, "CASES_01_list")
            census = os.path.join(_HERE, "debug", "CASES_census.txt")
            structure_census(phi_redact.scrub_html(await page.content()),
                             out_path=census)

            popup("Captured the Case List to ./debug (scrubbed) and wrote its "
                  "structure to debug/CASES_census.txt.\n\nNothing was changed. Tell "
                  "Claude the capture is done — the census file is the measurement "
                  "the reader gets written from.",
                  title="EMR AutoMate — case list probe")
        finally:
            await context.close()


# The list runs to a four-digit page count — the whole account's history, not a
# month's. Two things keep a run finite: the biggest page size the EMR offers, and
# stopping the moment the newest-first order has carried us past the range.
PAGE_SIZE = 30
MAX_PAGES = 400              # ~12,000 cases; a wall, not an expected outcome


# ─────────────────────────────────────────────
# THE SPECIALIST FILTER — measured 2026-09-08
# ─────────────────────────────────────────────
# Dane: the Case List starts including other specialists' cases for no reason he can
# see, and theirs arrive OUT OF ORDER. Newest-first — the whole basis for stopping the
# walk early — only holds absolutely once the list is filtered to one specialist. So
# this is not a convenience; it is what makes the early stop sound and the run finite.
#
#   .case-list-filter .case-filter          one chip per filter
#       .field-value / .field-label         the count, and the filter's name
#       .filter-icon                        opens the overlay
#   .filter-list-overlay
#       .filter-headings                    legend
#       .filter-option-item                 one per specialist
#           input#filter-checkbox-<id>
#           label.checkbox-label            the specialist's name
#       .filter-actions  .reset-btn  .apply-btn
FILTER_CHIP = ".case-list-filter .case-filter"
FILTER_OVERLAY = ".filter-list-overlay"
FILTER_OPTION = f"{FILTER_OVERLAY} .filter-option-item"
FILTER_APPLY = f"{FILTER_OVERLAY} .apply-btn"
SPECIALIST_CHIP_HINT = "specialist"


class FilterProblem(RuntimeError):
    """The specialist filter could not be applied, so the run must not continue."""


def _person_key(s):
    """'Dane Lee' and 'Lee, Dane' -> the same key. Order and punctuation don't matter."""
    return tuple(sorted(re.findall(r"[a-z]+", str(s or "").casefold())))


def match_specialist(wanted, options):
    """Index of the one option that is `wanted`, or None.

    Exact token-set match first; then a unique option that CONTAINS every token of the
    wanted name (so "Dane Lee" still finds "Dane M Lee"). Ambiguity returns None rather
    than picking one — the same rule name_match.py uses on employees, and for the same
    reason: a wrong pick here silently reports someone else's caseload as yours.
    """
    want = set(_person_key(wanted))
    if not want:
        return None
    keys = [set(_person_key(o)) for o in options]
    exact = [i for i, k in enumerate(keys) if k == want]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    loose = [i for i, k in enumerate(keys) if want and want <= k]
    return loose[0] if len(loose) == 1 else None


async def apply_specialist_filter(page, specialist):
    """Tick one specialist in the Specialists chip and Apply. Raises FilterProblem.

    Console output is counts only. The option names are other staff, not patients, but
    they are nobody's business here either — the one place they appear is the dialog on
    Dane's own screen when the match fails and he needs to see what was offered.
    """
    chips = page.locator(FILTER_CHIP)
    n = await chips.count()

    # Which chip is the specialist filter? The chip LABEL is the obvious tell, but its
    # exact wording has never been read — a capture scrubs it, and the probe printed it
    # to a console nobody kept. So the label only decides the ORDER chips are tried in;
    # what identifies the filter is finding Dane's own name among its options. That is
    # a measurement, and it holds whatever the EMR decides to call the column.
    candidates = []
    for i in range(n):
        try:
            label = (await chips.nth(i).locator(".field-label").inner_text()).strip()
        except Exception:
            label = ""
        if await chips.nth(i).locator(".filter-icon").count():
            hinted = SPECIALIST_CHIP_HINT in label.casefold()
            candidates.append((0 if hinted else 1, i, label))
    candidates.sort()
    if not candidates:
        raise FilterProblem(
            f"None of the {n} filter chips above the Case List opens a dropdown, so "
            f"there is no specialist filter to apply.\n\n"
            f"Nothing was read and nothing was written.")

    tried = []
    for _, i, label in candidates:
        chip = chips.nth(i)
        try:
            await chip.locator(".filter-icon").first.click()
            await page.wait_for_selector(FILTER_OVERLAY, timeout=8000)
            await page.wait_for_timeout(600)
        except Exception:
            continue

        items = page.locator(FILTER_OPTION)
        count = await items.count()
        names = []
        for k in range(count):
            try:
                names.append((await items.nth(k).locator(".checkbox-label")
                              .inner_text()).strip())
            except Exception:
                names.append("")
        idx = match_specialist(specialist, names)
        print(f"  filter {label!r}: {count} option(s), "
              f"{'matched' if idx is not None else 'no match'}")

        if idx is None:
            tried.append((label, names))
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            continue

        await items.nth(idx).locator(".checkbox-label").click()
        await page.wait_for_timeout(300)
        apply_btn = page.locator(FILTER_APPLY)
        if not await apply_btn.count():
            raise FilterProblem(f"The '{label}' filter has no Apply button.")
        await apply_btn.first.click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)
        print(f"  Filtered to 1 of {count} option(s) in {label!r} and applied it.")
        return label

    # Nothing matched anywhere. Show what WAS on offer — on Dane's own screen — so he
    # can copy the spelling instead of guessing at it.
    detail = ""
    for label, names in tried:
        listed = [x for x in names if x][:25]
        if listed:
            detail += f"\n\n{label}:\n" + "\n".join(f"  • {x}" for x in listed)
    raise FilterProblem(
        f'Couldn\'t find "{specialist}" in any of the filters above the Case List.'
        + detail
        + "\n\nPut the name in the Specialist box exactly as it appears above."
          "\n\nNothing was read and nothing was written.")


async def set_page_size(page, size=PAGE_SIZE):
    """Switch the pager to `size` rows. Measured: radios of 10 / 20 / 30."""
    try:
        radio = page.locator(f'{PAGE_SIZE_RADIO}[value="{size}"]')
        if not await radio.count():
            return False
        if await radio.is_checked():
            return True
        # The <input> sits inside two nested <label>s; clicking the label is what a
        # person does and what actually fires the handler.
        label = page.locator(f'label[for="ati-paginator-item-dropdown-{size}"]').first
        await (label if await label.count() else radio).click()
        await page.wait_for_timeout(1500)
        return True
    except Exception as exc:
        print(f"  Could not set the page size to {size}: {type(exc).__name__}")
        return False


async def current_page_no(page):
    """The pager's active page number, or '' if it can't be read."""
    try:
        active = page.locator(f"{PAGER} li.page-item.active").first
        if await active.count():
            return (await active.inner_text()).strip()
    except Exception:
        pass
    return ""


async def go_next_page(page):
    """Click Next. False when there is no next page (or it didn't move)."""
    before = await current_page_no(page)
    nxt = page.locator(f"{PAGER} li.page-item.label", has_text="Next").first
    try:
        if not await nxt.count():
            return False
        classes = await nxt.get_attribute("class") or ""
        if "disabled" in classes:
            return False
        await nxt.click()
        await page.wait_for_timeout(1200)
        await page.wait_for_load_state("networkidle")
    except Exception as exc:
        print(f"  Next page didn't click: {type(exc).__name__}")
        return False
    return await current_page_no(page) != before


async def harvest(page, start, end):
    """Walk EVERY page of the filtered list, collecting all rows. Returns (rows, notes).

    ⚠️ NO EARLY STOP. It used to stop once a page's oldest date fell before `start`,
    on the strength of the list being newest-first. The 2026-09-08 survey measured
    that and it is false: across Dane's 2,211 cases the displayed date drops 174 times
    within a page and 5 times between pages. The list is ordered by something the page
    doesn't show — plausibly last activity — while displaying each case's ORIGINAL
    encounter date. An early stop on that order would cut the report short somewhere
    unpredictable, and a short report looks exactly like a quiet week.

    Sweeping instead is affordable precisely because the same survey measured it:
    74 pages at 30 rows, his entire caseload, in a couple of minutes. Cheap certainty
    beats clever truncation.

    Range filtering happens afterwards, in the caller, because a row's displayed date
    is not the whole story — see resolve_follow_ups.
    """
    out, pages, undated = [], 0, 0

    while pages < MAX_PAGES:
        pages += 1
        rows = parse_case_rows(await page.content())
        if not rows:
            break
        undated += sum(1 for r in rows if not r["date"])
        out.extend(rows)
        if pages % 10 == 0 or pages == 1:
            print(f"  page {await current_page_no(page) or pages}: "
                  f"{len(out)} row(s) read")
        if not await go_next_page(page):
            break

    notes = {"pages": pages, "seen": len(out), "undated": undated,
             "hit_cap": pages >= MAX_PAGES}
    return out, notes


async def run_capture_filters():
    """READ-ONLY probe of the four filter chips above the Case List.

    Dane, 2026-09-08: the list starts including OTHER specialists' cases for no reason
    he can see, and their cases arrive out of order — which breaks the newest-first
    assumption the whole early stop rests on. Filtering to himself first restores it
    absolutely. So the reader has to drive that filter, and to drive it we have to see
    it: this opens each chip in turn and snaps it.

    It clicks filter icons and Escape. It selects nothing and saves nothing.
    """
    from playwright.async_api import async_playwright

    from ati_coaching_encounter import popup, snap
    from update_employees import _open_browser

    phi_redact.register_vocab(CASE_LIST_VOCAB)

    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            if not await open_case_list(page):
                popup("Could not open the Case List. Nothing was changed.",
                      title="EMR AutoMate — filter probe")
                return
            await snap(page, "CASES_F0_bar")

            chips = page.locator(".case-list-filter .case-filter")
            n = await chips.count()
            print(f"\n  {n} filter chip(s) above the list")
            for i in range(n):
                chip = chips.nth(i)
                # A filter's LABEL and its count are UI chrome — the same class of
                # thing as the "Location" column header. Neither is patient data.
                label = value = ""
                try:
                    label = (await chip.locator(".field-label").inner_text()).strip()
                    value = (await chip.locator(".field-value").inner_text()).strip()
                except Exception:
                    pass
                icon = chip.locator(".filter-icon")
                kind = "dropdown" if await icon.count() else "checkbox"
                print(f"    chip {i}: {label!r}  (showing {value!r}, {kind})")
                if kind != "dropdown":
                    continue
                try:
                    await icon.first.click()
                    await page.wait_for_timeout(1500)
                    await snap(page, f"CASES_F{i + 1}_open")
                    html = phi_redact.scrub_html(await page.content())
                    census = os.path.join(_HERE, "debug", f"CASES_F{i + 1}_census.txt")
                    structure_census(html, top=18, out_path=census)
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(600)
                except Exception as exc:
                    print(f"      couldn't open it: {type(exc).__name__}")

            popup("Captured the filter chips to ./debug (scrubbed). Nothing was "
                  "selected and nothing was changed.\n\nTell Claude the filter probe "
                  "is done.", title="EMR AutoMate — filter probe")
        finally:
            await context.close()


async def run_survey(specialist="", max_pages=MAX_PAGES):
    """READ-ONLY. How big is this list, how ordered is it, and how many rows hide dates?

    Dane, 2026-09-08: a follow-up is entered on its own date, but the Case List row
    keeps showing the case's ORIGINAL Enc.D — so a week's work can sit behind a row
    dated years ago, and the displayed dates stop being monotonic. He isn't sure how
    the list orders itself once that happens.

    Guessing at the answer is how this project ships bugs, and asking him to eyeball a
    four-digit pager is not a measurement either. So this walks his filtered list and
    counts: how many pages, how many rows, how many carry follow-ups, and how badly
    the displayed dates depart from newest-first. Counts and one aggregate date span —
    never a row, never a name.

    What it decides: whether a full sweep is affordable, and whether the order can be
    leaned on at all.
    """
    from playwright.async_api import async_playwright

    from ati_coaching_encounter import popup, snap
    from update_employees import _open_browser

    phi_redact.register_vocab(CASE_LIST_VOCAB)

    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            if not await open_case_list(page):
                popup("Could not open the Case List.", title="EMR AutoMate — survey")
                return
            await apply_specialist_filter(page, specialist)
            await set_page_size(page)

            pages = rows_seen = undated = with_fu = unknown_fu = 0
            drops_in_page = drops_between = 0
            fu_hist, oldest, newest, last_tail = Counter(), None, None, None

            while pages < max_pages:
                pages += 1
                rows = parse_case_rows(await page.content())
                if not rows:
                    break
                rows_seen += len(rows)
                dated = [r["date"] for r in rows if r["date"]]
                undated += len(rows) - len(dated)
                for r in rows:
                    n = r.get("follow_ups", -1)
                    fu_hist[n] += 1
                    if n > 0:
                        with_fu += 1
                    elif n < 0:
                        unknown_fu += 1
                if dated:
                    drops_in_page += sum(1 for a, b in zip(dated, dated[1:]) if a < b)
                    if last_tail is not None and last_tail < dated[0]:
                        drops_between += 1
                    last_tail = dated[-1]
                    lo, hi = min(dated), max(dated)
                    oldest = lo if oldest is None else min(oldest, lo)
                    newest = hi if newest is None else max(newest, hi)
                if pages % 10 == 0 or pages == 1:
                    print(f"  page {pages}: {rows_seen} rows so far, "
                          f"{with_fu} with follow-ups")
                if not await go_next_page(page):
                    break

            await snap(page, "CASES_survey_last")
            lines = [
                "CASE LIST SURVEY (counts only)",
                "",
                f"pages walked        : {pages}" + ("  (hit the cap)"
                                                    if pages >= max_pages else ""),
                f"rows seen           : {rows_seen}",
                f"rows with follow-ups: {with_fu}"
                + (f"   <- these need opening individually" if with_fu else ""),
                f"follow-up count unreadable: {unknown_fu}",
                f"rows with no readable date: {undated}",
                "",
                "FOLLOW-UP COUNT HISTOGRAM (count -> how many rows)",
            ]
            for k in sorted(fu_hist):
                lines.append(f"  {k if k >= 0 else 'unreadable':>10}  {fu_hist[k]}")
            lines += [
                "",
                "ORDER OF THE DISPLAYED DATES",
                f"  drops within a page : {drops_in_page}",
                f"  drops between pages : {drops_between}",
                "  (0 and 0 would mean the list really is newest-first by the "
                "displayed date)",
                "",
                f"date span covered   : {oldest} .. {newest}",
            ]
            report = "\n".join(lines)
            print("\n" + report)
            try:
                path = os.path.join(_HERE, "debug", "CASES_survey.txt")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(report + "\n")
                print(f"\n  Written to {path}")
            except Exception as exc:
                print(f"  [survey] could not write it: {exc}")

            popup(f"Survey done — {pages} page(s), {rows_seen} case(s), "
                  f"{with_fu} with follow-ups.\n\nWritten to "
                  f"debug/CASES_survey.txt (counts only, no names, no rows).\n\n"
                  f"Nothing was changed. Tell Claude the survey is done.",
                  title="EMR AutoMate — case list survey")
        finally:
            await context.close()


async def run_capture_case(specialist=""):
    """READ-ONLY. Open ONE case that has follow-ups and snap its summary page.

    The follow-up dates are not on the Case List — the row shows only the case's
    original Enc.D. If they are anywhere, they are on the case's own summary page,
    which has never been captured. This opens the first row with a non-zero follow-up
    count, follows its Case Overview link, and snaps the result (scrubbed) plus a
    structure census. It reads one case and edits nothing.
    """
    from playwright.async_api import async_playwright

    from ati_coaching_encounter import popup, snap
    from update_employees import _open_browser

    phi_redact.register_vocab(CASE_LIST_VOCAB)

    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            if not await open_case_list(page):
                popup("Could not open the Case List.",
                      title="EMR AutoMate — case probe")
                return
            await apply_specialist_filter(page, specialist)
            await set_page_size(page)

            target = None
            for _ in range(10):                     # a few pages is plenty to find one
                rows = parse_case_rows(await page.content())
                counts = Counter(r.get("follow_ups", -1) for r in rows)
                print(f"  follow-up counts on this page: {dict(sorted(counts.items()))}")
                target = next((r for r in rows if r.get("follow_ups", 0) > 0), None)
                if target or not await go_next_page(page):
                    break
            if not target:
                popup("Couldn't find a case with follow-ups in the first few pages, "
                      "so there was nothing to open.\n\nNothing was changed.",
                      title="EMR AutoMate — case probe")
                return

            print(f"  opening one case with {target['follow_ups']} follow-up(s)")
            link = page.locator(f'a[href="{target["href"]}"]').first
            if await link.count():
                await link.click()
            else:
                from ati_coaching_encounter import BASE_URL
                await page.goto(BASE_URL.rstrip("/") + target["href"])
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2500)

            await snap(page, "CASE_summary")
            census = os.path.join(_HERE, "debug", "CASE_summary_census.txt")
            structure_census(phi_redact.scrub_html(await page.content()),
                             top=30, out_path=census)
            popup("Captured one case summary to ./debug (scrubbed) and wrote its "
                  "structure to debug/CASE_summary_census.txt.\n\nNothing was "
                  "changed. Tell Claude the case probe is done.",
                  title="EMR AutoMate — case probe")
        finally:
            await context.close()


MAX_CASE_OPENS = 300          # a wall; the measured population of follow-up cases is 104


async def resolve_follow_ups(page, rows, start, end):
    """Open the cases whose real dates aren't on the list, and read them.

    A case with follow-ups shows only its FIRST date on the Case List, so its later
    encounters are invisible to a range filter. For those cases the summary page is
    authoritative: its rows replace the list row entirely, which is also what stops the
    original encounter being counted twice.

    Which cases get opened, and why it is affordable:

    * `follow_ups == 0` — the list row is the only encounter there is. Not opened.
    * `follow_ups > 0` and the case's first date is **after** the range — a follow-up is
      always later than the case it belongs to, so nothing on it can be in range. Not
      opened.
    * everything else — opened.

    On the 2026-09-08 survey that was 104 cases out of 2,211.
    """
    from ati_coaching_encounter import BASE_URL, snap

    plain = [r for r in rows if r.get("follow_ups", 0) <= 0]
    todo = [r for r in rows
            if r.get("follow_ups", 0) > 0 and r["date"] and r["date"] <= end
            and r.get("href")]
    skipped_future = sum(1 for r in rows if r.get("follow_ups", 0) > 0
                         and r["date"] and r["date"] > end)

    resolved, opened, failed, undated = [], 0, 0, 0
    for i, row in enumerate(todo[:MAX_CASE_OPENS], 1):
        try:
            await page.goto(BASE_URL.rstrip("/") + row["href"])
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(900)
            found = parse_case_encounters(await page.content())
        except Exception as exc:
            print(f"    case {i}/{len(todo)}: could not open ({type(exc).__name__})")
            failed += 1
            resolved.append(row)          # keep the list row rather than losing the case
            continue
        opened += 1
        if not found:
            resolved.append(row)
            continue

        # ⚠️ A summary whose rows carry no readable date must FALL BACK to the list row.
        # Replacing a case with dateless encounters drops it out of the report entirely
        # — worse than the caveat it was meant to fix, because the case's own original
        # encounter disappears too. Keep the row, count it, and say so on the report.
        if not any(e["date"] for e in found):
            undated += 1
            resolved.append(row)
            if undated == 1:
                await snap(page, "CASE_ERR_no_dates")
                report = diagnose_dates(found, "a case summary page")
                print("\n" + report)
                try:
                    path = os.path.join(_HERE, "debug", "CASE_dates_diagnosis.txt")
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(report + "\n")
                    print(f"  Written to {path}")
                except Exception as exc:
                    print(f"  [diagnosis] could not write it: {exc}")
            continue

        for enc in found:
            enc = dict(enc)
            enc["name"] = row.get("name", "")
            enc["case_id"] = row.get("case_id", "")
            enc["extra"] = row.get("extra", "")
            enc["extra_label"] = row.get("extra_label", "")
            enc["href"] = row.get("href", "")
            enc["follow_ups"] = row.get("follow_ups", 0)
            enc["location"] = enc.get("location") or row.get("location", "")
            resolved.append(enc)
        if i % 10 == 0 or i == len(todo):
            print(f"    opened {i}/{len(todo)} case(s) with follow-ups")

    if len(todo) > MAX_CASE_OPENS:
        for row in todo[MAX_CASE_OPENS:]:
            resolved.append(row)

    notes = {"with_follow_ups": len(todo) + skipped_future,
             "opened": opened, "failed": failed, "undated_cases": undated,
             "skipped_after_range": skipped_future,
             "hit_open_cap": len(todo) > MAX_CASE_OPENS}
    return plain + resolved, notes


async def run_report(start, end, fmt="xlsx", out=None, open_when_done=True,
                     specialist=""):
    """Read the Case List and write the report. READ-ONLY.

    `specialist` is required. Without it the list mixes in other specialists' cases
    out of order, which both breaks the early stop and makes the walk unbounded — the
    2026-09-08 run that had to be killed. A filter that cannot be applied stops the
    run; it never quietly falls back to reading everything.
    """
    if not PARSER_READY:
        raise NeedsCapture(_NEEDS_CAPTURE_MSG)
    if not str(specialist or "").strip():
        raise FilterProblem(
            "No specialist given, so the Case List would be read unfiltered.\n\n"
            "Unfiltered it mixes in other specialists' cases, out of order — which "
            "makes the run walk thousands of pages and the early stop unsafe.\n\n"
            "Put your name in the Specialist box on the report tab, exactly as the "
            "EMR's Specialists filter spells it.")

    from playwright.async_api import async_playwright

    from ati_coaching_encounter import popup, snap
    from update_employees import _open_browser, read_worksite

    phi_redact.register_vocab(CASE_LIST_VOCAB)

    async with async_playwright() as p:
        context, page = await _open_browser(p)
        try:
            site = await read_worksite(page)
            if not await open_case_list(page):
                popup("Could not open the Case List. Nothing was written.",
                      title="EMR AutoMate — case list report")
                return []
            await snap(page, "CASES_01_list")
            # Filter FIRST, page size second: applying the filter reloads the list.
            await apply_specialist_filter(page, specialist)
            await set_page_size(page)
            await snap(page, "CASES_02_filtered")

            first = parse_case_rows(await page.content())
            if first and not any(r["date"] for r in first):
                # Every row on page 1 lacking a date means the Employee cell no longer
                # yields the "Enc.D." pair this parser matches on. Writing a report
                # from that would produce an empty file that reads as a quiet month.
                #
                # A capture cannot answer WHY: the label and the date are both scrubbed
                # out of it. So the diagnosis is taken here, off the live page, and it
                # carries labels (UI chrome) and value SHAPES (Aaa 9, 9999) only.
                await snap(page, "CASES_ERR_no_dates")
                report = diagnose_dates(first)
                print("\n" + report)
                try:
                    path = os.path.join(_HERE, "debug", "CASES_date_diagnosis.txt")
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(report + "\n")
                    print(f"\n  Written to {path}")
                except Exception as exc:
                    print(f"  [diagnosis] could not write it: {exc}")
                raise NeedsCapture(
                    "Read the Case List, but not one row had a readable date.\n\n"
                    "Nothing was written. The page was captured to ./debug, and "
                    "debug/CASES_date_diagnosis.txt says what it was looking at — "
                    "column labels and date SHAPES only, no dates and no names.\n\n"
                    "Tell Claude it's there.")

            all_rows, notes = await harvest(page, start, end)
            print(f"\n  Reading the cases that carry follow-ups...")
            all_rows, fu = await resolve_follow_ups(page, all_rows, start, end)
            notes.update(fu)
            kept = filter_rows(all_rows, start, end)
        finally:
            await context.close()

    stats = summarize(kept)
    print(f"\n  {notes['pages']} page(s), {notes['seen']} case(s) read; "
          f"{len(kept)} inside {_range_label(start, end)}.")
    if notes["hidden_candidates"]:
        print(f"  {notes['hidden_candidates']} older case(s) carry follow-ups whose "
              f"own dates are not on the list — see the caveat.")
    if notes["undated"]:
        print(f"  ⚠ {notes['undated']} row(s) had no readable Enc.D. date and were "
              f"left out.")
    if notes["hit_cap"]:
        print(f"  ⚠ stopped at the {MAX_PAGES}-page limit — the report may be short.")
    for key in sorted(stats["by_case_type"]):
        print(f"    {stats['by_case_type'][key]:4d}  {key}")

    paths = write_report(kept, start, end, fmt=fmt, worksite=site, out=out,
                         caveat=followup_note(notes))
    for path in paths:
        print(f"  Wrote {os.path.basename(path)}")
    if open_when_done and paths:
        # Open it BEFORE the dialog, so the file is already up when he clicks OK.
        open_file(paths[0])

    warn = "\n\n! " + followup_note(notes)
    if notes["undated"]:
        warn += f"\n\n⚠ {notes['undated']} row(s) had no readable date and were left out."
    if notes["hit_cap"]:
        warn += f"\n\n⚠ Stopped at {MAX_PAGES} pages — the report may be short."
    popup(f"{len(kept)} case(s) in {_range_label(start, end)}, "
          f"from {notes['seen']} read over {notes['pages']} page(s).\n\n"
          + "\n".join(os.path.basename(p) for p in paths)
          + ("\n\nOpening it now." if open_when_done and paths else "") + warn,
          title="EMR AutoMate — case list report")
    return paths


# ─────────────────────────────────────────────
# DEMO — the writers, with obviously fake people
# ─────────────────────────────────────────────

def _demo_rows():
    d1, d2 = date(2026, 9, 2), date(2026, 9, 3)

    def mk(dd, ct, coach, nm, st="Completed"):
        return {"date": dd, "case_type": ct, "coaching_type": coach,
                "name": nm, "status": st}

    return [
        mk(d1, "Coaching Encounter", "Safety Coaching", "Smith, Jane"),
        mk(d1, "Coaching Encounter", "Safety Coaching", "Doe, John"),
        mk(d1, "Coaching Encounter", "Ergonomic Adjustment", "Roe, Richard"),
        mk(d1, "Physical Assessment", "", "Doe, John"),
        mk(d2, "Coaching Encounter", "Health/Wellness Coaching", "Roe, Richard"),
        mk(d2, "Coaching Encounter", "", "Smith, Jane", "InProgress"),
        mk(d2, "PA Follow-Up", "", "Smith, Jane"),
        mk(d2, "Office Visit", "", "Doe, John"),
    ]


def main(argv=None):
    # A page walk must not die on the console codepage. Windows hands Python a cp1252
    # stdout often enough, and cp1252 cannot encode the warning glyph used below —
    # losing forty pages of reading to a UnicodeEncodeError on a print statement is
    # the stupidest possible way to fail.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="EMR Case List report (read-only)")
    ap.add_argument("--capture", action="store_true",
                    help="READ-ONLY probe: snap the Case List page and census it")
    ap.add_argument("--capture-filters", action="store_true",
                    help="READ-ONLY probe: open each filter chip and snap it")
    ap.add_argument("--survey", action="store_true",
                    help="READ-ONLY: walk the filtered list and report COUNTS only")
    ap.add_argument("--capture-case", action="store_true",
                    help="READ-ONLY: open one case with follow-ups and snap it")
    ap.add_argument("--demo", action="store_true",
                    help="write a report from fake rows — no browser, no PHI")
    ap.add_argument("--from", dest="start", help="range start, MM/DD/YYYY")
    ap.add_argument("--to", dest="end", help="range end, MM/DD/YYYY")
    ap.add_argument("--format", choices=["xlsx", "docx", "both"], default="xlsx")
    ap.add_argument("--out", help="output path (single format only)")
    ap.add_argument("--specialist", default="",
                    help="filter the Case List to this specialist (required for a "
                         "report; the list is unusable unfiltered)")
    ap.add_argument("--no-open", dest="open_when_done", action="store_false",
                    help="write the file but don't open it")
    args = ap.parse_args(argv)

    if args.capture or args.capture_filters or args.survey or args.capture_case:
        import asyncio
        from ati_coaching_encounter import popup
        try:
            if args.capture_filters:
                asyncio.run(run_capture_filters())
            elif args.survey:
                asyncio.run(run_survey(specialist=args.specialist))
            elif args.capture_case:
                asyncio.run(run_capture_case(specialist=args.specialist))
            else:
                asyncio.run(run_capture())
        except (NeedsCapture, FilterProblem) as exc:
            print(exc)
            popup(str(exc), title="EMR AutoMate - probe stopped")
            return 2
        return 0

    if args.demo:
        rows = _demo_rows()
        start, end = min(r["date"] for r in rows), max(r["date"] for r in rows)
        written = write_report(rows, start, end, fmt="both",
                               worksite="DEMO - fake names", out=args.out)
        for path in written:
            print(f"Wrote {path}")
        if args.open_when_done and written:
            open_file(written[0])
        return 0

    start, end = parse_date(args.start), parse_date(args.end)
    if not start or not end:
        ap.error("--from and --to are required (MM/DD/YYYY)")
    if end < start:
        start, end = end, start

    import asyncio

    # ⚠️ EVERY EXIT PATH ENDS IN A DIALOG. The success path always had one; the failure
    # paths only printed, so on 2026-09-08 a run that stopped on the date guard closed
    # its browser and left Dane looking at a console for a message he had no reason to
    # expect. A run launched from the builder is watched by someone waiting for a
    # window, not reading stdout — a silent end is indistinguishable from a crash.
    from ati_coaching_encounter import popup

    try:
        asyncio.run(run_report(start, end, fmt=args.format, out=args.out,
                               open_when_done=args.open_when_done,
                               specialist=args.specialist))
    except (NeedsCapture, FilterProblem) as exc:
        print(f"\n{exc}\n")
        popup(str(exc), title="EMR AutoMate — case list report stopped")
        return 2
    except KeyboardInterrupt:
        print("\nStopped.\n")
        return 130
    except Exception as exc:
        print(f"\n{type(exc).__name__}: {exc}\n")
        popup(f"The report run hit an error and wrote nothing.\n\n"
              f"{type(exc).__name__}: {str(exc).splitlines()[0][:400]}\n\n"
              f"The console window has the details.",
              title="EMR AutoMate — case list report failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
