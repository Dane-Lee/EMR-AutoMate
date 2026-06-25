# Dictation → encounters.csv — Transcription Spec

This is the instruction set for turning Dane's dictated coaching-encounter notes
into the `encounters.csv` file that `ati_coaching_encounter.py` reads.

**How to use it:** paste everything under "PROMPT" below into Claude (or ChatGPT),
then paste or dictate your notes after it. The AI returns a CSV. Save that CSV as
`encounters.csv` in this folder. (When Claude does it in-session, it writes the
file directly.)

The values below must match the EMR **exactly** — the script validates every row
and refuses to run if anything is off, naming the row and the bad value.

---

## PROMPT (paste this to the AI, then add your notes)

You are transcribing spoken coaching-encounter notes into a CSV for an automated
EMR entry tool. Output **only** the CSV — a header row plus one row per encounter,
nothing else. Organize and translate the spoken notes into the fields; do not
invent clinical content that wasn't said.

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
