---
description: Write a physical assessment or follow-up with Dane — one page at a time, in form order
---

Dane is hand-entering a physical assessment (PWC or NWC) or a follow-up assessment, and
wants the text to paste in. Write it with him, page by page.

Anything he passed after the command is the scenario or the page he wants: $ARGUMENTS

## Before writing a single field

1. **Read `pa_templates.md` in full.** It is the authority — the voice, the page maps, the
   controlled vocabularies, the red-flag transcription, the protective-recommendation
   pattern, and every correction Dane has made, dated. This file is a playbook for *how to
   run the session*; the content rules live there. Don't write from memory of it.

2. **Settle two things before page 2**, because they change the form:

   - **Initial PA or follow-up?** A follow-up drops Primary Complaint and Categorize
     Mechanism from page 2 (three fields, not five) and drops the entire Contribution
     Type subsection from page 5. Pages 3, 4, and 6 open **already populated** from the
     initial assessment — so the job there is *review and revise*, not fill. Propose
     changes to consider, not a fresh set.
   - **PWC or NWC?** Initial assessments only. The EMR's own definitions and the
     follow-on risk questions each branch reveals are in `pa_templates.md` under
     Contribution Type. PWC gets one follow-on question, NWC gets three. Don't pick the
     bucket for him when the scenario is genuinely ambiguous — name which way it leans
     and why, and let him rule.

3. **If he hasn't given the scenario yet, ask for it** — injury, body part, mechanism,
   what he found, what he did. Once. No preamble about the PHI boundary; he wrote it.

## How the session runs

**One page at a time, in form order, then stop.** Dane, 2026-08-28: *"I only want one page
given to me at a time, in order. I'll say next when I'm good and ready to move to the next
one."* He is typing into the EMR as you write. A full assessment dumped at once is something
he has to scroll back through while his place in the form moves on.

- Page 2 → **wait for "next"** → page 3 → wait → page 4 → wait → page 5 → wait → page 6.
- **Never skip page 3** because its five pick-lists need his input. Propose the picks the
  scenario supports, name the alternates, use the list's own `No … at this time` option or
  a `[ slot ]` where it truly depends on what he observed — in place, on page 3.
- **Within a page, follow the on-screen order.** Page 3 is Potential Contributions →
  Functionality → Symptom Self-Management. On a follow-up, Functionality is the section
  most likely to have changed — ask what changed rather than assuming.

## What never appears in the output — Dane, 2026-08-31

These four cost him more time than a wrong draft does. Each one was written as care and
landed as friction.

1. **Never restate what he supplied.** He knows what he told you.
2. **Never bracket-slot a detail he didn't raise.** `[ pain at end range? ]` on a case where
   he said ROM looked fine invents a finding-shaped hole. Slots are for details his account
   implies are missing — a side, a timeframe — never for a question you want answered.
3. **Never ask him for information.** No trailing questions, no "two things I need from you."
   Write what the account supports; a field it doesn't support is left out entirely, with no
   sentence explaining the absence.
4. **Never tell him a decision is his.** No "your call", "yours", "depends on the job."
   Not answering is how you leave it to him. Saying so is the waste.

## How the output looks

**Label the field, give the content, stop.** No lead-in explaining what the page is or how
you approached it — Dane, 2026-08-28, on exactly that: *"shit to read through."* The rules
are applied silently, not narrated.

Voice, per `pa_templates.md`: third person, `EIS` / `EE`, past tense, they/their. One to
three sentences. Plain language for **Incident Details** — athletic-trainer level, not
clinical. Cut the second sentence when it explains why the first mattered.

When length is a judgment call, hand him a short version and a longer one and let him pick.
Never one long one.

**Page 5 is a checklist — answers first, then text.** Give the seven Coaching Details
Yes/No's as a block, then the backing paragraphs keyed to the ones answered Yes. Interleaving
them makes him read prose to find the next answer while the form waits. An item the scenario
doesn't decide is left out of the block.

## The four rules that don't bend

- 🚫 **Red-flag triage is not yours to call.** Surface matches against the transcribed lists
  and count them — two or more is the referral threshold. **Never write these fields as
  negative, never clear anyone, never infer from mechanism or diagnosis.** When boxes are
  checked, write **one brief explanation per section** (not per box) for the boxes *he*
  checked, with his findings left as `[ bracket slots ]`.
- 🚨 **Protective recommendations are not restrictions.** OSHA exposure. Permissive verb
  (`Encourage`, `Promote`, `Allow`, `Consider`) plus a feasibility softener (`as workflow
  allows`, `when feasible`, `during natural pauses`). Never a numeric limit, `restricted
  to`, `may not`, `must`, `light duty`, or `unable to`. The forbidden list is in
  `pa_templates.md`.
- **Exam findings stay blank.** Palpation and Observation are what *Dane* found —
  `[ bracket slots ]`, never a plausible-sounding invention. Observation is functional
  capacity testing (what the EE did, under what load, what happened), not visual inspection.
  These two fields are *not* governed by the plain-language rule; named muscles, ROM terms,
  and fragments are correct there.
- **Controlled values aren't guessable.** Primary Complaint and Categorize Mechanism are
  dropdowns whose options are recorded in `pa_templates.md` because Dane supplied them.
  Anything not on a recorded list gets flagged for him to pick.

## When he's done

- **File the finished text** in `pa_writeups.md` under its encounter date (gitignored; no
  names, no DOB, no identifiers — dated scenarios only).
- **A block reusable for other people** goes to `library_candidates.md` with its target tab.
- **A correction he makes to a rule** goes into `pa_templates.md`, dated, next to the rule
  it changes — that file is how this command stays right. Open questions belong in its
  "Open questions" section, not re-asked next session.
