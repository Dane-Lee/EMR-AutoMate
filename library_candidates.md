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

## Safety Coaching -- EE instructs EIS on a task and its hazards

**Tab:** `Target-JobCoaching` (where the suspension-weld sibling lives) ·
**Coaching type:** Safety Coaching -- Dane's call 2026-09-08. The sibling entries on that
tab are Job-Specific Coaching, so confirm the tab at merge time or the builder surfaces
this under the wrong type.

Approved by Dane 2026-09-08, verbatim (paint booth):

> EIS asked EE what cleaning the paint booth involves and what hazards come with it. EE
> instructed EIS on the process and explained that they are responsible for the employees
> who clean the booth out. EE said they go over the hazards with their crew and the steps
> they take to prevent incidents during the cleaning.

Generic, for any task a lead walks EIS through:

> EIS asked EE what [ task ] involves and what hazards come with it. EE instructed EIS on
> the process and explained that they are responsible for the employees who [ do the task ].
> EE said they go over the hazards with their crew and the steps they take to prevent
> incidents during [ the task ].

He took the three-sentence version over the two-sentence one -- see the note dated
2026-09-08 in `pa_templates.md` for why, because it is an exception to the usual
shorter-is-better default.

---

# Written 2026-09-08

Ten coaching descriptions from one session. Station and equipment names are kept where
Dane used them and slotted where the shape generalises — a station number names a place,
not a person, so these stay safe to commit.

## General Medical — psychosocial check-in

**Tab:** `General-GenMed` · **Coaching type:** General Medical ·
**Choose:** `Psychosocial`

> EIS spoke with EE about how things had been going for them outside of work. EE said they
> had been having some issues with friends and had been feeling depressed. EE said things
> had gotten better since then and that they were doing well now.

Shorter:

> EIS spoke with EE about how things had been going for them. EE said they had been having
> some issues with friends and had been feeling depressed, but that things were better now.

`General-GenMed` carries the `Choose` hints with no text at all, so this is the first
description on that tab.

## General Medical — wound care around swimming

**Tab:** `General-GenMed` · **Coaching type:** General Medical ·
**Choose:** `Wound care instruction`

> EE asked EIS about keeping a wound from welding debris clean while swimming at a water
> park over the weekend. EE said they were concerned about the site getting infected. EIS
> and EE went over keeping the wound covered while in the water, cleaning and re-dressing it
> afterward, and what to watch for at the site.

Generic:

> EE asked EIS about keeping a wound clean while [ activity ]. EE said they were concerned
> about the site getting infected. EIS and EE went over keeping the wound covered, cleaning
> and re-dressing it afterward, and what to watch for at the site.

## Health/Wellness — supplementation, hydration, electrolytes, beverage nutrition

**Tab:** `Target-H&W` · **Coaching type:** Health/Wellness Coaching ·
**Choose:** `Hydration`, `Nutrition`, `Sleep`, `Other`

> EIS and EE discussed supplementation options to help with sleep quality and reduce muscle
> cramping. EIS went over proper hydration protocols for the shift and the sources EE could
> get electrolytes from. EIS and EE reviewed the nutritional content of EE's beverage
> choices and what to look for when picking them.

Shorter:

> EIS and EE discussed supplementation for sleep quality and muscle cramping, proper
> hydration protocols and electrolyte sources, and the nutritional content of EE's beverage
> choices.

`Target-H&W` has a Sleep row and a Nutrition row carrying only the `Choose` hint and no
text — this fills both.

⚠️ The first draft of this one flattened the four topics into a single noun-string and Dane
sent it back: *"your description needs to be better than that. I gave you more than that to
work with."* The fix is the same as the page-5 total-health-and-wellness rule in
`pa_templates.md` — **name what was actually covered**, with each topic keeping its own
substance. Listing topics is not covering them.

## Safety Coaching — carrying a load by hand instead of using the crane

**Tab:** `Target-JobCoaching` · **Coaching type:** Safety Coaching ·
**Choose:** `Safety Hazard`, `Unsafe Behavior`, `Other`

> EIS spoke with EE about carrying the beams over to the bushing press by hand instead of
> using the crane. EIS and EE went over the hazards that come with moving the beams that
> way. EIS reviewed using the crane for the transfer instead.

Generic:

> EIS spoke with EE about carrying [ the load ] over to [ the station ] by hand instead of
> using the crane. EIS and EE went over the hazards that come with moving it that way. EIS
> reviewed using the crane for the transfer instead.

Runs the same crane-versus-carry theme as the workbook's suspension-weld entry on this tab,
from the other direction — file them near each other.

## Safety Coaching — EE reports a trip hazard

**Tab:** `Target-JobCoaching` · **Coaching type:** Safety Coaching ·
**Choose:** `Safety Hazard`, `Slip/trip/fall Prevention`, `Other`

Report only:

> EE told EIS that something needed to be done about the anti-fatigue flooring at Parts Box.
> EE said they were tripping over it while moving the carts into position by their desk.

Request passed along:

> EE told EIS that something needed to be done about the anti-fatigue flooring at Parts Box.
> EE said they were tripping over it while moving the carts into position by their desk. EIS
> told EE they would pass the request along to [ EHS / their supervisor / maintenance ].

Same two-version shape as the heat/fans candidate above.

## Job-Specific Coaching — EE walks EIS through a station

**Tab:** `Target-JobCoaching` · **Coaching type:** Job-Specific Coaching ·
**Choose:** `Material handling`, `Proper loading/unloading`, `Tool/equipment handling`

> EIS asked EE about the working conditions at station 232 and how the station is meant to
> run. EE instructed EIS on the material handling, loading and unloading, and tool handling
> the station involves. EE explained how many employees are meant to be working the station.

If EIS was coaching rather than being walked through:

> EIS and EE discussed proper working conditions at station 232, including the material
> handling, loading and unloading, and tool handling the station involves. EIS and EE went
> over how many employees are meant to be working the station.

## Job-Specific Coaching — heat forecast and rest breaks

**Tab:** `Target-JobCoaching` · **Coaching type:** Job-Specific Coaching ·
**Choose:** `Other job coaching`, `Rest break` — the workbook's high-heat rows also carry
`Rest (task design)`

> EIS and EE discussed working the wrap weld station in the heat. EIS went over the
> temperatures expected through the week and how conditions at the station would change from
> day to day. EIS reviewed taking rest breaks through the shift on the hotter days.

Generic:

> EIS and EE discussed working [ the station ] in the heat. EIS went over the temperatures
> expected through the week and how conditions at the station would change from day to day.
> EIS reviewed taking rest breaks through the shift on the hotter days.

Forward-looking, unlike the existing high-heat entries on that tab, which are same-shift
hydration checks.

## Ergonomic Adjustment — marking equipment for identification

**Tab:** `Target-JobCoaching` · **Coaching type:** Ergonomic Adjustment ·
**Choose:** `Industrial ergo adjustment`

> EIS and EE discussed painting the Mag Liners so they can be identified.

If the EE raised it:

> EE asked EIS about painting the Mag Liners so they can be identified.

## Ergonomic Adjustment — fixing matting so it can be used

**Tab:** `Target-JobCoaching` · **Coaching type:** Ergonomic Adjustment ·
**Choose:** `Industrial ergo adjustment`

> EIS and EE looked at the anti-fatigue matting at EE's station, which EE had not been able
> to use as it was. EIS fixed the matting so EE could stand on it while packing parts.

Shorter:

> EIS fixed the anti-fatigue matting at EE's station so EE could stand on it while packing
> parts.

## Ergonomic Adjustment — weighing a tool before getting it

**Tab:** `Target-JobCoaching` · **Coaching type:** Ergonomic Adjustment ·
**Choose:** `Industrial ergo adjustment` — `Tools adjustment` if the encounter is about the
tool itself

> EIS asked EE whether getting magnet handles would help with restocking the shims at
> station 260.

Generic:

> EIS asked EE whether getting [ the tool ] would help with [ the task ].

This is the shape for **considering** equipment, not using it — the first draft wrote it as
instruction on using the handles and Dane corrected it: *"we talked about IF I was to get
magnet handles, would they help much with restocking."*
