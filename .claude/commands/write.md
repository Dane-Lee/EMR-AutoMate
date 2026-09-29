---
description: Write encounter or assessment text with Dane — routes to the coaching, assessment, or batch path
---

Dane has an encounter he needs text for and wants to paste it into the EMR. Write it with
him.

What he passed after the command is the scenario, or the type, or both: $ARGUMENTS

## First, decide which of three shapes this is

The routing is the whole job of this command. Get it wrong and he gets a six-page form
walk-through when he wanted one sentence, or one sentence when he needed the form.

1. **A coaching encounter** — Job-Specific, Safety, Health/Wellness, Ergonomic Adjustment,
   Prevention Mobility and Stretching, Relationship Development, Group Class, Near Miss
   Education, Fitness Center Visit, Friend/Family Consult, General Medical. One
   description field. **Handle it here**, below.

2. **An assessment** — Physical Assessment, Follow-Up Assessment, Task Assessment, Human
   Movement Assessment, HMA Follow-Up, HMA Reassessment, Office Assessment. Six pages,
   controlled vocabularies, red-flag triage, OSHA exposure on protective recommendations.
   **Stop and run `.claude/commands/pa.md`** — read it and `pa_templates.md` in full and
   follow that playbook, one page at a time. Don't improvise an assessment from this file;
   it doesn't carry the rules.

3. **A batch** — he points at `encounter_intake.xlsx`, or says he has a stack of them, or
   a date range. Read `ENCOUNTER_INTAKE.md` first: de-identified sheet in, blocks out,
   every block labeled with its `ref`. `intake_grid.py` builds the sheet and
   `intake_runner.py` runs it.

If the type is genuinely unclear, **ask once, in one line** — "coaching or assessment?" —
and nothing else. Don't explain the difference; he wrote it.

If he hasn't given the scenario yet, ask for it once: what happened, body part, mechanism,
what he found, what he did. No preamble about the PHI boundary — he wrote that too.

## The coaching path

### Check whether it's already written

Before drafting, look at `library_candidates.md` and the `EMR Easy Enter Worksheets.xlsx`
tab for that coaching type. Most coaching encounters are ordinary and a library entry
already covers them; the builder surfaces those automatically. If one fits, say which
entry and stop. Writing a fresh near-duplicate is work for both of you and it fragments
the library.

### The voice

Third person, `EIS` / `EE`, past tense, they/their. Plain language at athletic-trainer
level, not clinical — "rolled their ankle inward", not "inversion mechanism". The
translation table is in `pa_templates.md`.

**One to three sentences.** Coaching descriptions are the shortest thing in this project.
The measure is the workbook, not a number:

> EIS and EE discussed mobility and stretches for the shoulders to maintain shoulder
> health during work related tasks.

That is a complete, in-use description. Say what happened and what was covered, then stop.
Don't add why it mattered, list variations, or close with reassurance that wasn't part of
the encounter.

When length is a judgment call, hand him a short version and a longer one and let him
pick. Never one long one.

### Controlled values aren't guessable

The coaching type and the `Choose "…"` detail checkboxes are dropdowns. Name the type from
the recorded list above; if the scenario doesn't land cleanly on one, name the two it sits
between and let him rule. Never invent a detail-box label.

## What never appears in the output — either path

These four cost him more time than a wrong draft does. Each was written as care and landed
as friction.

1. **Never restate what he supplied.** He knows what he told you.
2. **Never bracket-slot a detail he didn't raise.** Slots are for details his account
   implies are missing — a side, a timeframe — never for a question you want answered.
3. **Never ask him for information.** No trailing questions, no "two things I need from
   you." Write what the account supports; a field it doesn't support is left out entirely,
   with no sentence explaining the absence.
4. **Never tell him a decision is his.** No "your call", "yours", "depends on the job."
   Not answering is how you leave it to him. Saying so is the waste.

**Label the field, give the content, stop.** No lead-in explaining the page or how you
approached it. The rules are applied silently, not narrated.

## The lines that don't bend, wherever they come up

- 🚨 **Protective recommendations are not restrictions.** OSHA exposure. Permissive verb
  (`Encourage`, `Promote`, `Allow`, `Consider`) plus a feasibility softener (`as workflow
  allows`, `when feasible`, `during natural pauses`). Never a numeric limit, `restricted
  to`, `may not`, `must`, `light duty`, or `unable to`. Forbidden list: `pa_templates.md`.
- 🚫 **Red-flag triage is not yours to call.** Surface and count matches against the
  transcribed lists — two or more is the referral threshold. Never write those fields as
  negative, never clear anyone.
- **Exam findings stay blank.** Palpation and Observation are what *Dane* found —
  `[ bracket slots ]`, never a plausible-sounding invention.
- **PHI stays on his side.** He describes scenarios; no names are needed and none are
  wanted. Never open the never-read files in `CLAUDE.md` — not to check a detail, not
  under a deadline. Saying so once is enough; don't repeat the rule at him.

## When he's done

- **Reusable text** → `library_candidates.md`, tagged with its target workbook tab.
- **An assessment write-up** → `pa_writeups.md` under its encounter date (gitignored).
- **A correction he makes to a rule** → into `pa_templates.md`, dated, next to the rule it
  changes. That file is how this stays right.
