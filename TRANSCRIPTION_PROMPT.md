# Dictation → encounters.csv — Transcription / Intake Spec

This is the instruction set (a paste-ready prompt for a temporary assistant — an AI
like Claude/ChatGPT) for turning Dane's dictated notes into the `encounters.csv` file
that `ati_coaching_encounter.py` enters, **plus** a separate list of any assessments
for manual entry.

**How to use it:** paste everything under "PROMPT" below into the assistant, then paste
or dictate your notes after it. It returns (1) the CSV and (2) an ASSESSMENTS list if
any. Save the CSV as `encounters.csv` in this folder. (When Claude does it in-session,
it writes the file directly.)

The values below must match the EMR **exactly** — the script validates every row and
refuses to run if anything is off, naming the row and the bad value.

> **Coaching encounters vs. assessments:** the tool currently enters only the 11
> **coaching-encounter** types listed below. **Assessments** (Physical / PA Follow-Up,
> Human Movement Assessment (HMA) / HMA Follow-Up / Reassessment, Office Assessment,
> Task Assessment, Work Readiness, etc.) are a different EMR case type the tool can't
> enter yet — so the assistant lists those separately for Dane to enter by hand.

## Description sourcing (when Claude Code builds the CSV in-session)
For each encounter's `description`, first try to **reuse a matching standard
description** from `EMR Easy Enter Worksheets.xlsx` (fill any `____` placeholders with
the dictated specifics), keeping the third-person EIS/EE voice. If nothing fits, **write
a new description in that same voice** — and whenever a NEW one is written:
1. **Append it** to `new_descriptions_for_library.csv`
   (`date_added, suggested_sheet, scenario_label, coaching_type, details, description`).
2. **Surface the new ones to Dane** at the end of the CSV build so he can add the keepers
   to the worksheet for future reuse.
Reused (not new) descriptions are NOT logged — only the freshly-composed ones.

---

## PROMPT (paste this to the AI, then add your notes)

You are organizing Dane's spoken clinical notes for an automated EMR entry tool.
Split what you hear into two buckets and output **both**:

1. **Coaching encounters** → a CSV (header + one row per encounter), exactly as
   specified below. Output the CSV first, inside a code block, and nothing else in it.
2. **Assessments** (Physical / PA Follow-Up, HMA / HMA Follow-Up / Reassessment,
   Office, Task, Work Readiness, or anything that isn't one of the 11 coaching types
   below) → do **NOT** put these in the CSV. After the CSV, add a section titled
   `ASSESSMENTS — manual entry` and list each one as a bullet with the employee, the
   assessment type, the date, and any details said. If there are none, write
   `ASSESSMENTS — manual entry: none`.

Organize and translate the spoken notes into the fields; do not invent clinical
content that wasn't said.

**Columns, in this exact order:**

```
employee,date,encounter_type,department,division,category,shift,coaching_type,details,description,what_prompted
```

**Rules:**
- `employee` — "Last, First". It contains a comma, so **wrap it in double quotes**:
  `"Smith, Jane"`.
- `date` — `MM/DD/YYYY`. If no date is mentioned, leave blank (defaults to today).
- `department`, `division`, `category`, `shift` — optional; leave blank if not
  mentioned.
- `details` — zero or more labels **separated by semicolons** (e.g.
  `Hydration; Stress`). Must come from the chosen coaching type's allowed list
  below. Some types have no details — leave blank.
  - If the encounter clearly belongs to a coaching type but the specifics don't
    match any named detail, use **"Other"** (when that type offers it) and put the
    specifics in the description. Don't leave details blank just because nothing
    fits — "Other" is the catch-all.
  - **PHD check-in / new-hire onboarding check** → coaching_type
    `Health/Wellness Coaching`, details = **`Other`**.
- `description` — the free-text summary. If it contains a comma, **wrap it in
  double quotes**.
- Any field with a comma MUST be double-quoted. When unsure, quote it.
- Use only the exact allowed values below for `encounter_type`, `coaching_type`,
  and `what_prompted`.

**`encounter_type` — one of:**
- In Person
- Via Phone or Microsoft Teams
- Via Telehealth Platform
- Via Email

**`what_prompted` — one of (default to "Specialist Initiated" if not stated, since
Dane usually initiates the conversation):**
- Specialist Initiated
- Employee Inquiry
- Demonstrated risk factor at job site
- Employer prompted contact

**`coaching_type` and its allowed `details`:**

- **Health/Wellness Coaching** — Hydration · Nutrition · Sleep · Stress ·
  Personal exercise/fitness · Other
- **Safety Coaching** — 3-point contact · Awareness/alertness · PPE Use ·
  Safety Hazard · Slip/trip/fall Prevention · Unsafe Behavior · Other
- **Job-Specific Coaching** — Body Mechanics · Material handling ·
  Postural/Position Coaching · Proper lifting · Proper loading/unloading ·
  Proper push/pull · Rest break · Rest (task design) · Tool/equipment handling ·
  Other job coaching
- **Ergonomic Adjustment** — Industrial ergo adjustment · Office ergo adjustment ·
  Tools adjustment · Other
- **General Medical Education** — Blood Pressure/Pulse Check ·
  Cold modality instruction · Thermal modality instruction ·
  Extreme heat/cold education · OTC medications · Psychosocial · Self-care ·
  Wound care instruction · Other
- **Fitness Center Visit** — Focus: Class · Focus: Endurance · Focus: Flexibility ·
  Focus: Strength · Focus: Recreational Event · Orientation
- **Group Class** — New Hire Orientation · Safety Meeting · Pre-shift Meeting ·
  Group Preventative Mobility · Annual Testing ·
  Department Weekly/Monthly Safety Meetings · First Aid Team Meeting ·
  Management Meetings · Safety Fair · Other
- **Relationship Development Encounter** — Current Employee · New Hire
- **Friend/Family Consultation** — (no details — leave the column blank)
- **Job-Specific Preventative Mobility/Stretching** — (no details — leave blank)
- **Near Miss Education** — (no details — leave blank)

**Example output:**

```
employee,date,encounter_type,department,division,category,shift,coaching_type,details,description,what_prompted
"Smith, Jane",06/23/2026,In Person,,,,,Health/Wellness Coaching,Hydration; Stress,"Discussed hydration habits and stress from a recent schedule change; gave water-intake target.",Employee Inquiry
"Doe, John",06/23/2026,Via Phone or Microsoft Teams,,,,,Safety Coaching,PPE Use,Reviewed correct glove selection for the task.,Specialist Initiated
```

ASSESSMENTS — manual entry
- Garcia, Maria — Physical Assessment (PA Follow-Up) — 06/23/2026 — reviewed lifting tolerance, cleared for full duty
- Lee, Sam — Human Movement Assessment (HMA) — 06/23/2026 — baseline screen, follow-up in 2 weeks
