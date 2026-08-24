# Encounter intake — batch description writing

How Dane hands over a batch of encounters for description writing without handing over
PHI. Agreed 2026-08-24, during the 8/17–8/21 backlog.

The one-at-a-time version of this ran all morning: Dane describes a scenario in chat,
Claude writes the description, Dane pastes it into the EMR. This is the same exchange in
bulk — a spreadsheet in, labeled blocks out.

## Why this is safe

The columns below carry **encounter type, reason, and a base description**. That is
exactly what Dane has been saying out loud, one encounter at a time, for a full session.
Batching changes the volume, not the sensitivity.

What makes it safe is what is **absent**: no names, no dates of birth, no badge or
identifier numbers, no employee UUIDs. The PHI boundary in `CLAUDE.md` is unchanged and
this does not sit on an exception to it.

## The `ref` column — do not skip it

Dane strips names, so nothing in the file says who a row is about. **He keeps a `ref`
column** — `1, 2, 3`, or codes of his own — and every block Claude hands back is labeled
with that ref. Dane maps ref → person on his side, where the names already live.

Without it the output is 40 correct descriptions and no way to tell whose is whose.

## ⚠️ Names out is necessary, not sufficient

The column that leaks is `base_description`, not the one that used to hold the name.
Shorthand like *"the guy on second shift back from knee surgery"* identifies a person in a
small department as surely as a name does. Free text can also carry a date of birth, an
age, a badge number, or a job title held by exactly one person.

**Dane scans the description column before handing the file over.** Claude cannot check
this — by the time it could look, it has already read the file.

If a row can only be true of one identifiable person, rewrite it to the scenario or leave
it out and handle it in chat.

## Name collision — read this before naming the file

`encounter_log.csv` already exists in this repo. It is the **automation's audit trail** of
what was entered, it contains PHI, and it is on the never-read list in `CLAUDE.md`.

Dane's intake spreadsheet is a different thing entirely. Name it **`encounter_intake.xlsx`**
so neither party reaches for the wrong file. It is **gitignored**.

## Dane's actual template — `Encounter Intake Template.xlsx`

Supplied 2026-08-24. **This supersedes the column list below**, which was written before
seeing it. Structure verified by probe; no encounter data in it (data rows hold only the
`ref` number).

### Shape

- **One tab per date**, named `8-24-26`, `8-25-26`, … The date lives in the **tab name**
  and in `C1` — there is no per-row date column, and none is needed.
- **Row 2** = section bands. **Row 3** = column headers. **Rows 4–22, column D** = the
  Encounter Type dropdown list. **Rows 23–62, column A** = `ref` 1–40, already numbered.
- Only the first tab carries the full 29-column PA layout. The other four are 8 columns —
  coaching only.

### Columns (row 3)

| Col | Header | Section |
|---|---|---|
| A | *(ref, numbered 1–40)* | key |
| B / C | Last / First | **names — Dane deletes these before handing the file over** |
| D | Encounter Type | core |
| E | Reason | core |
| F | Shift | core |
| G | Description / Incident Details | core |
| I | Primary Complaint | Page 2 — Symptom Details |
| J | Mechanism | Page 2 |
| K | Palpation | Page 2 |
| L | Observation | Page 2 |
| M | Work Factors | Page 3 — Root Cause Analysis |
| N | ADL's | Page 3 |
| O | Postures | Page 3 |
| P | Faulty Behaviors | Page 3 |
| Q | Suboptimal Human Movement Patterns | Page 3 |
| R | Red Flag Signs? | Page 4 — Red Flag Triage |
| S | Red Flag Mechanism of Injury? | Page 4 |
| T | Red Flag Symptoms? | Page 4 |
| U | Ergo Adjustments | Page 5 — Corrective Actions |
| V | Job Coaching | Page 5 |
| W | ADL Coaching | Page 5 |
| X | Mobility Reminder | Page 5 |
| Y | Conditioning Reminder | Page 5 |
| Z | H&W Education | Page 5 |
| AA | Capable of All Tasks? | Page 5 |
| AB | Protective Rec's Needed? | Page 5 |
| AC | First-Aid? | Page 5 |

Columns I–AC are marked **"Physical Assessment / Follow-Up Info Only"** in `I1`.

### Encounter Type values (D4:D22)

Physical Assessment · Follow-Up Assessment · Task Assessment · Human Movement Assessment ·
HMA Follow-Up · HMA Reassessment · Office Assessment · Task Assessment · Job-Specific ·
Prevention Mobilty and Stretching · Safety · Ergonomic Adjustment · Health and Wellness ·
Relationship Development · Group Class · Near Miss Education · Fitness Center Visit ·
Friend/Family Consult · General Medical

Two defects in that list, both Dane's to fix or to confirm are intentional:

- **`Task Assessment` appears twice** (rows 6 and 11).
- **`Prevention Mobilty and Stretching`** — missing an `i` in *Mobility*.

### Four columns worth adding

Not in the template, and each one prevents a specific wrong answer:

| Add | Because |
|---|---|
| `symptom_duration` | Decides `acute` / `subacute` / `chronic`. Without it the timeline is inferred from prose. |
| `body_part` | Decides which protective recommendations apply. |
| `side` | Left / right / bilateral — otherwise it becomes a bracket slot on every write-up. |
| `pwc_nwc` | Work-related or not. Decides the bucket, and it is never assumed. |

### Handing it over

1. Delete columns **B and C** (Last, First). Keep column **A** — that is the `ref`.
2. Scan column **G** for shorthand that identifies a person even without a name.
3. Copy the full 29-column layout onto any tab whose day includes PAs — four of the five
   currently have the 8-column coaching-only layout.

## Columns — original spec, superseded by the section above

Kept for the reasoning behind each field.

`ref`, `date`, `kind`, `reason`, and `base_description` are required. Everything else is
optional and improves the output when present.

| Column | Required | Notes |
|---|---|---|
| `ref` | ✅ | Dane's key. Any format. Never a name. |
| `date` | ✅ | Encounter date. Drives date-range pulls. |
| `kind` | ✅ | `coaching` / `PA` / `PA follow-up` |
| `coaching_type` | coaching rows | Safety, Health/Wellness, Job-Specific, Group Class, … |
| `reason` | ✅ | Why the encounter happened |
| `base_description` | ✅ | Dane's shorthand. **The column that leaks — scan it.** |
| `body_part` | PA / follow-up | Drives which protective recommendations apply |
| `side` | PA / follow-up | Left / right / bilateral |
| `symptom_duration` | PA / follow-up | Decides acute / subacute / chronic |
| `pwc_nwc` | PA / follow-up | Work-related or not. Decides the bucket. |
| `mechanism` | optional | If Dane already knows it, it is not re-derived |
| `palpation` | optional | His own exam findings, used verbatim |
| `observation` | optional | His own exam findings, used verbatim |
| `first_aid` | optional | Yes/No for the Corrective Actions page |

Extra columns are fine and are reported back during the mapping step, never silently
ignored.

## PA / follow-up columns — what can actually be filled today

Only **page 2 (Symptom Details)** and **page 5 (Corrective Actions)** are mapped. Root
Cause Analysis (3), Red Flag Triage (4), and Plan (6) have no recorded field list, so no
columns for them — a header invented now would be a guess.

### Page 2 — who supplies what

| Field | Type | Source |
|---|---|---|
| Incident Details | free text | **Claude writes it** from `base_description` |
| Primary Complaint | 14 controlled options | **Claude selects** |
| Categorize Mechanism | 13 controlled options | **Claude selects**, or flags when it decides work-relatedness |
| Palpation Comments | free text | **Dane** — Claude only formats. Never invented. |
| Observation Comments | free text | **Dane** — functional capacity testing, not visual inspection |

### Page 5 — who supplies what

| Field | Type | Source |
|---|---|---|
| 7 × Action Taken | Yes/No | **Dane** |
| First Aid provided | Yes/No | **Dane** |
| Protective recommendations text | free text | **Claude writes it** — permissive verbs only, see the 🚨 rule |
| 2 × instruction checkboxes | checkbox | **Dane** |

### Recommended columns

**Core:** `ref` · `date` · `kind` · `pwc_nwc` · `body_part` · `side` · `reason` ·
`base_description`

**`symptom_duration`** — *"3 weeks"*, *"since last night"*, *"on and off 2 months"*. This
decides `acute` / `subacute` / `chronic` under Dane's rule. Without it the timeline is
inferred from prose, which is where it will go wrong.

**Optional, skipped when supplied:** `primary_complaint` · `mechanism` · `palpation` ·
`observation`

**Page 5** — either eleven Yes/No columns:

`ergo_adjustments` · `job_coaching` · `adl_coaching` · `reminded_mobility` ·
`reminded_conditioning` · `educated_hw` · `capable_all_tasks` · `protective_recs_needed` ·
`first_aid` · `advised_seek_treatment` · `refused_referral`

…or a single `page5` column listing only the exceptions (`"ergo=Y, first_aid=Y"`), with
everything unlisted taking Dane's default. **That default has not been recorded yet** —
see the open item in `pa_templates.md`.

## Process

1. **Probe the columns first.** Headers, row count, and per-column fill counts — an
   aggregate probe, no cell contents. This is the same technique used to map the roster
   and the workbook.
2. **Confirm the mapping with Dane** before generating anything. Which column is which,
   what the `kind` values actually say, how many rows of each type. Guessing at a column's
   meaning is the failure mode this step exists to prevent.
3. **Generate**, one labeled block per `ref`.
4. **File the output** — see below.
5. **Flag, never guess.** Anything unclassifiable comes back flagged with what is missing.

## Output

One block per `ref`, in the order the sheet gives them.

- **Coaching rows** — a single description, sized to the workbook's register (one to three
  sentences, detail-light). Reusable ones are staged in `library_candidates.md` with their
  target tab.
- **PA and follow-up rows** — broken across the page-2 fields (Incident Details, Primary
  Complaint, Categorize Mechanism, Palpation Comments, Observation Comments), plus page-5
  Corrective Actions text where it applies. Filed in `pa_writeups.md` under the encounter
  date, keyed by `ref`.
- **Status per block** — `READY`, `SLOTS` (bracket slots for Dane to complete), or `OPEN`
  (waiting on a decision or a page that isn't mapped yet).

## What still gets flagged rather than decided

These are Dane's calls and a batch run does not change that:

- **Controlled values not on a recorded list.** Primary Complaint and Categorize Mechanism
  options are recorded in `pa_templates.md`; anything outside them is flagged.
- **PWC vs NWC**, when the row does not say. It decides work-relatedness.
- **Exam findings.** Palpation and observation stay bracket slots unless Dane supplied
  them in the sheet. A guessed finding in a medical record is worse than a blank one.
- **Protective recommendations** near the restriction line — see the 🚨 section of
  `pa_templates.md`. OSHA exposure; permissive verbs only.

## Related files

| File | Holds | Git |
|---|---|---|
| `encounter_intake.xlsx` | Dane's de-identified batch, input to this process | **gitignored** |
| `pa_writeups.md` | finished PA / follow-up write-ups by date | **gitignored** |
| `library_candidates.md` | reusable descriptions staged for the workbook | committable |
| `pa_templates.md` | PA shapes, controlled vocabularies, voice rules | committable |
| `encounter_log.csv` | the automation's audit trail — **not this** | PHI, never read |
