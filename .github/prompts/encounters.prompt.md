---
mode: agent
description: Turn Dane's dictated coaching notes into a validated encounters.csv for EMR AutoMate.
tools: ['codebase', 'editFiles', 'runCommands']
---

# Dictated notes → encounters.csv

Dane will dictate (talk-to-text) a day of coaching encounters. Convert them into
`encounters.csv`, which the EMR automation enters as drafts.

Dictation is messy: run-on, out of order, with speech-to-text errors. That's expected.
Clean it up, but **never invent clinical content that wasn't said.** If something is
garbled, keep it and flag it to Dane rather than guessing. A wrong detail in a medical
record is worse than a missing one.

## Before you start

1. Read `description_library.md` — the standard reusable descriptions. If it's missing
   or older than `EMR Easy Enter Worksheets.xlsx`, regenerate it: `python library_export.py`
2. If `encounters.csv` already exists with rows in it, **ask Dane before overwriting** —
   those may be entered already, or may be waiting to be entered.

## What you produce

**1. `encounters.csv`** — coaching encounters only. Exactly these columns, in order:

```
employee,date,encounter_type,department,division,category,shift,coaching_type,details,description,what_prompted
```

**2. `assessments_todo.md`** — anything that is *not* one of the 11 coaching types
below (Physical / PA Follow-Up, HMA / HMA Follow-Up / Reassessment, Office, Task, Work
Readiness…). The tool can't enter these yet. One bullet each: employee, assessment
type, date, details. Never put an assessment in the CSV.

**3. `new_descriptions_for_library.csv`** — append any description you had to write
from scratch. Columns: `date_added, suggested_sheet, scenario_label, coaching_type,
details, description`. Only log *new* ones; reused library descriptions are not logged.

## Field rules

The automation validates every row against the EMR's exact vocabulary and refuses to
run if anything is off. Use these values verbatim.

- **`employee`** — `"Last, First"`. Contains a comma, so **always double-quote it**.
- **`date`** — `MM/DD/YYYY`. Blank = today.
- **`department` / `division` / `category` / `shift`** — optional; blank if not said.
- **`details`** — zero or more labels from the chosen coaching type's list below,
  **separated by semicolons**: `Hydration; Stress`. Some types take none — leave blank.
  - If the encounter fits a type but no named detail matches, use **`Other`** (where
    the type offers it) and put the specifics in the description. Don't leave details
    blank just because nothing fits — `Other` is the catch-all.
  - A **PHD check-in / new-hire onboarding check** → `Health/Wellness Coaching`,
    details = `Other`.
- **`description`** — the free-text summary. **Reuse a library description whenever one
  fits**, filling any `____` placeholder with what was actually said. Keep the
  third-person EIS/EE voice. Only compose a new one if nothing fits — and log it (#3).
- **Any field containing a comma must be double-quoted.** When unsure, quote it.

**`encounter_type`** — one of: `In Person` · `Via Phone or Microsoft Teams` ·
`Via Telehealth Platform` · `Via Email`

**`what_prompted`** — one of: `Specialist Initiated` · `Employee Inquiry` ·
`Demonstrated risk factor at job site` · `Employer prompted contact`
Default to `Specialist Initiated` if not stated — Dane usually starts the conversation.

**`coaching_type`** and its allowed **`details`**:

| coaching_type | allowed details |
|---|---|
| Health/Wellness Coaching | Hydration · Nutrition · Sleep · Stress · Personal exercise/fitness · Other |
| Safety Coaching | 3-point contact · Awareness/alertness · PPE Use · Safety Hazard · Slip/trip/fall Prevention · Unsafe Behavior · Other |
| Job-Specific Coaching | Body Mechanics · Material handling · Postural/Position Coaching · Proper lifting · Proper loading/unloading · Proper push/pull · Rest break · Rest (task design) · Tool/equipment handling · Other job coaching |
| Ergonomic Adjustment | Industrial ergo adjustment · Office ergo adjustment · Tools adjustment · Other |
| General Medical Education | Blood Pressure/Pulse Check · Cold modality instruction · Thermal modality instruction · Extreme heat/cold education · OTC medications · Psychosocial · Self-care · Wound care instruction · Other |
| Fitness Center Visit | Focus: Class · Focus: Endurance · Focus: Flexibility · Focus: Strength · Focus: Recreational Event · Orientation |
| Group Class | New Hire Orientation · Safety Meeting · Pre-shift Meeting · Group Preventative Mobility · Annual Testing · Department Weekly/Monthly Safety Meetings · First Aid Team Meeting · Management Meetings · Safety Fair · Other |
| Relationship Development Encounter | Current Employee · New Hire |
| Friend/Family Consultation | *(none — leave blank)* |
| Job-Specific Preventative Mobility/Stretching | *(none — leave blank)* |
| Near Miss Education | *(none — leave blank)* |

Example rows:

```csv
employee,date,encounter_type,department,division,category,shift,coaching_type,details,description,what_prompted
"Smith, Jane",06/23/2026,In Person,,,,,Health/Wellness Coaching,Hydration; Stress,"Discussed hydration habits and stress from a recent schedule change; gave a water-intake target.",Employee Inquiry
"Doe, John",06/23/2026,Via Phone or Microsoft Teams,,,,,Safety Coaching,PPE Use,Reviewed correct glove selection for the task.,Specialist Initiated
```

## Then validate — don't skip this

```powershell
.\Run-Encounters.ps1 -Check
```

It prints `VALID - N encounter(s) ready to enter`, or names each bad row and value. If
it fails, fix the CSV and run it again until it passes. Don't hand Dane a CSV you
haven't validated.

## Finally, report back

Tell Dane, briefly:

- how many encounters are in the CSV, and that it validated
- **any `[unclear]` items you flagged** — these need his eyes before the batch runs
- any **new descriptions** you had to compose (so he can add the keepers to the workbook)
- any **assessments** parked in `assessments_todo.md` for manual entry

Then he runs `.\Run-Encounters.ps1` to enter the batch as drafts.

## PHI reminder

Everything above stays in the gitignored working files. Never write an employee name,
DOB, or clinical detail into a tracked file, a code comment, or a commit message. See
`.github/copilot-instructions.md`.
