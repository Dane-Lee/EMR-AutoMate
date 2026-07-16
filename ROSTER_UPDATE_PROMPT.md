# Employee Roster Update — Spreadsheet Format Spec

This describes the `roster.xlsx` file that `update_employees.py` reads to update
employee **file information** in the ATI EMR. The encounter side of the tool is
`encounter_builder.py` — see [WORKFLOW.md](WORKFLOW.md).

`roster.xlsx` is also what `encounter_builder.py` reads to list people: it takes each
row's `name`, and parses the work title and shift back out of `new_identifier`
(`ID-Title-Shift`). So the identifier format below is load-bearing for both tools.

> **Field set (Dane, 2026-06-29): Name, Identifier, Date of Hire.** Identifier format
> (2026-06-30): **`ID-Title-Shift`**, e.g. `12345-Technician II-2nd`.

---

## Importing from the HC Reporting export (the usual source)
Dane's roster comes from an "Active Associates HC Reporting" Excel export with columns
`Associate ID`, `Associate Name` ("First Last"), `Shift`, `Primary Position`
("code - Title"), `Most Recent Hire Date`. Convert it into `roster.xlsx` with:

```
python update_employees.py --from-hc "<path to the HC Reporting .xlsx>"
```

This writes `roster.xlsx` with `identifier` (= Associate ID), `name` (converted to
`Last, First`), `new_identifier` (= `ID-Title-Shift`), and `date_of_hire`. **Review it**
before running the update. (Names are imported only as a match fallback — they are
NOT pushed as first/last, to avoid wiping existing `First "Nick"` entries.)

---

## How to use it
1. Copy `roster_template.xlsx` → `roster.xlsx` and fill it in — one employee per row.
2. Run EMR AutoMate → **Update employee info** (the "No" button on the launcher
   popup), or run `python update_employees.py` directly.
3. It validates the file, matches each row to an EMR employee, shows a confirmation
   popup, then applies the updates. Every change is recorded in
   `employee_updates_log.csv`.

## The two rules that control what gets changed
1. **Blank cell = leave that field alone.** Only cells with a value are written.
2. **A column you don't include = never touched.** The tool only edits the fields
   whose columns are present in the sheet.

The form's **medical-history / screening** section, **Date of Birth**, **Phone/Email**,
and the read-only **Location** are **never** touched. **Gender** is not edited either
(see below).

## Matching: Identifier first, then Name
Each row is matched to the EMR employee by the **`identifier`** (badge #) if it matches
someone in the worksite, otherwise by the **`name`** (`Last, First`) if exactly one
person matches. `identifier` and `name` are **match keys only — never written**.
Ambiguous names and no-match rows are skipped and reported (v1 updates existing
employees only).

## Columns
**Match keys (one required, never written):**
| Column | Format | Notes |
|---|---|---|
| `identifier` | badge number, e.g. `12345` | Primary match key. `12345` or `12345 - Materials Handler` both match. |
| `name` | `Last, First` | Match-key fallback. |

**Writable fields (optional; only non-blank cells are written):**
| Column | EMR field | Format |
|---|---|---|
| `first_name` | First Name | text — **embed nicknames here** (see below) |
| `middle_name` | Middle Name | text |
| `last_name` | Last Name | text |
| `new_identifier` | Identifier (badge) | `ID-Title-Shift`, e.g. `12345-Technician II-2nd` |
| `date_of_hire` | Date of Hire | `MM/DD/YYYY` (real Excel date cell ok) |

## Nicknames go in `first_name`, not a Nickname box
The EMR **only searches the First/Last name boxes**, so to be findable by *either* the
formal name or a nickname, the First Name must read **`First "Nick"`** — e.g.
`James "Jim"` (this matches the existing `Michael "Mike"` style). Put that quoted form
in the `first_name` column. The standalone Nickname box is not used.

- To find who likely needs this, run **`python update_employees.py --nicknames`** — it
  scans the live roster and writes `nickname_candidates.csv` (employees whose first
  name commonly has a nickname, with a suggested `First "Nick"`).

## Gender (not edited, but handled)
Gender is **not** changed by the tool. Because it's a required field, if a record's
Gender is **blank** the tool sets it to **`Male`** so Save succeeds, and adds that
employee to **`gender_review_needed.csv`** for you to review afterward.

> ⚠ **`new_identifier` overwrites the whole Identifier field.** Format is
> **`ID-Title-Shift`** (e.g. `12345-Technician II-2nd`), with no spaces around the
> joining dashes (the title keeps its own spaces). Suffixed IDs are preserved
> (`11111-01-Materials Handler-1st`). Leave the column blank/absent to keep a person's
> current Identifier untouched.

## Example
| identifier | name | first_name | date_of_hire |
|---|---|---|---|
| 12345 | Roe, James | James "Jim" | |
| | Doe, Julian | | 07/21/2025 |

Row 1 matches by badge and sets First Name to `James "Jim"` (findable as James or Jim).
Row 2 matches by name and sets only the hire date. Nothing else is touched.
