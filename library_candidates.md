# Library candidates — reusable descriptions awaiting a home in the workbook

Descriptions written in chat that are **reusable**, staged here with the
`EMR Easy Enter Worksheets.xlsx` tab they belong in. Dane folds them into the workbook
when he has a moment; the builder picks them up from there automatically.

**Not PHI, and safe to commit** — but the contents are the guarantee, not the filename.
A reusable description is about no one: no names, no dates, no identifiers, nothing that
narrows to a person. If an entry can only be true of one individual, it is not a library
candidate — it belongs in `pa_writeups.md` (gitignored) instead.

## How this differs from the files next to it

| File | Holds | PHI |
|---|---|---|
| `EMR Easy Enter Worksheets.xlsx` | the live library the builder reads | no |
| `library_candidates.md` (this) | reusable text not yet merged into the workbook | no |
| `new_descriptions_for_library.csv` | per-encounter descriptions from the 2026-06-30 batch | **yes** — never read |
| `pa_templates.md` | PA / follow-up shapes, 5 fields, bracket slots | no |
| `pa_writeups.md` | finished PA write-ups by date | **yes-adjacent** — gitignored |

`new_descriptions_for_library.csv` came from an era when descriptions were composed per
person, which is exactly why it is encounter-level and off limits. This file is not its
replacement — it is the thing that file was trying to be, done safely.

## The `Choose` hint

Workbook rows can carry a `Choose "…"` cell naming which detail boxes to tick, and the
builder ticks them automatically. Those aren't known for the entries below — Dane fills
them in at merge time, or leaves them off.

## Merge checklist

Before pasting a candidate into the workbook:

1. Confirm the tab. A wrong tab means the builder surfaces it under the wrong coaching type.
2. Put the description in **its own cell**. `load_library()` emits one entry per long
   cell and uses the short cells in the row as its label — joining them is what put
   `Choose "Other" | Job-Specific Coaching | EIS asked…` into 77 records.
3. A `Choose …` hint goes on the row **below** the description, or in the same row.
4. Delete the entry from this file once it is in the workbook.

---

# Candidates

## Health & Wellness — shoulder mobility

**Tab:** `Target-H&W` *(or `Target-JobMobility` if you'd rather file it by content than
by how it came up)* · **Coaching type:** Health/Wellness Coaching

> EIS and EE discussed shoulder tightness and reviewed mobility and stretching options to
> help improve it. EIS demonstrated stretches EE could perform before, during, and after
> their shift.

Shorter variant:

> EIS and EE discussed stretches and exercises to improve shoulder mobility and reduce
> tightness.

## Job-Specific Mobility — low back

**Tab:** `Target-JobMobility` · **Coaching type:** Job-Specific Mobility/Stretching

> EIS and EE discussed low back discomfort and went over mobility and stretches to help
> relieve it. EIS demonstrated stretches EE could do before, during, and after their
> shift, along with exercises to build strength through the hips and core.

Shorter variant:

> EIS and EE discussed mobility, stretches, and exercises to help with low back discomfort
> during work tasks.

## Safety Coaching — heat, fans requested

**Tab:** `Target-JobCoaching` *(where the existing heat-index and hydration entries live)*
· **Coaching type:** Safety Coaching

Request only:

> EIS spoke with EE about the heat in their work area. EE asked about getting the fans
> turned on and running. EIS told EE they would pass the request along to [ EHS / their
> supervisor / maintenance ] and reminded EE to keep up with water and electrolytes while
> working in the heat.

Request resolved same shift:

> EIS spoke with EE about the heat in their work area. EE asked about getting the fans
> turned on and running. EIS passed the request along to [ EHS / their supervisor /
> maintenance ] and the fans were turned on for the shift. EIS reminded EE to keep up with
> water and electrolytes while working in the heat.

## Group Class — observing pre-shift stretching

**Tab:** `General-GroupClass` · **Coaching type:** Group Class Coaching

> EIS observed the pre-shift stretching session for [ shift ] to confirm EE's were
> participating and performing the stretches correctly.

With correction:

> EIS observed the pre-shift stretching session for [ shift ] to confirm EE's were
> participating and performing the stretches correctly. EIS corrected stretching form as
> needed and answered EE questions during the session.
