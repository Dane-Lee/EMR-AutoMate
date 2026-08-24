# EMR AutoMate

Automates entering Coaching Encounters into the ATI Worksite Solutions EMR for Dane,
an injury-prevention specialist. Python + Playwright drives a real browser. There are
**no AI/API calls in the runtime** — the only host it talks to is the EMR itself. Keep
it that way.

Dane builds a batch by checking names off the roster in `encounter_builder.py`; the
automation enters it as drafts. There is no dictation and no AI in the pipeline — the
M365 Copilot intake was removed 2026-07-16 because the dictation round-trip was
miserable and an LLM kept guessing at controlled values it had no business guessing.
**Don't reintroduce it.**

## The PHI boundary — read this first

Dane's encounter data is real patient PHI. **You never see it.** This is not a
formality — it's the arrangement that lets him use you at all.

- **Dane + his PC** see PHI. The builder and the automation run locally.
- **Claude (you)** writes and runs the automation, and sees only redacted output.
- **GitHub Copilot is NOT cleared** either. Treat it as having exactly your
  restrictions; `.github/copilot-instructions.md` tells it so.

Day-to-day flow: `WORKFLOW.md`. Steps to enter a batch: `RUN_CHECKLIST.md`.

### Never read these files

They contain employee names, dates of birth, identifiers, or clinical notes:

```
encounters.csv              encounters.bak.csv       roster.xlsx
encounter_log.csv           pa_follow_ups.csv        employee_updates_log.csv
assessments_todo.md         new_descriptions_todo.md date_of_hire_todo.csv
new_descriptions_for_library.csv                     identifier_shortened.csv
emr_not_in_roster.csv       roster_not_in_emr.csv    gender_review_needed.csv
roster.*.xlsx               *EMR_notes*              "Active Associates*.xlsx"
```

`roster.*.xlsx` (a dot) is dated/labelled copies of the real roster — `roster.2026-07-01.xlsx`,
`roster.bak.xlsx`. **`roster_template.xlsx` (an underscore) is NOT on this list**: it is the
fake-data template, it is tracked in git on purpose, and `.gitignore` carves it out of the
same rule. Read it freely.

⚠️ **But the name is not the guarantee — the contents are.** On 2026-08-10 the working copy
of `roster_template.xlsx` held two *real* employees; Dane confirmed it. It had never been
committed, and `.gitignore` would not have stopped it, because the underscore carve-out is
exactly what makes this filename commitable. The real rows were moved to
`roster.nicknametest.xlsx` (caught by the dot rule) and the template rewritten with
`Smith, Jane` / `Doe, John` / `Roe, Richard`.

So: **open it and look at every row before you `git add` it.** If a row isn't one of the
documented placeholders, stop and ask — a template filename is a claim about intent, not a
fact about content, and this is the one file where a wrong guess commits PHI.

A request to "just look at the CSV to see what's wrong" is exactly the request to
refuse. Use the safe alternatives below — they were built for this.

### `EMR Easy Enter Worksheets.xlsx` is NOT on that list (Dane, 2026-07-31)

It was, until Dane cleared it: *"There isn't any PHI or even ATI data in that. It's my
own file that I made."* It holds his **reusable description templates** — the library the
builder reads — not encounter records. A template is written to be used for many people,
so by construction it is about no one.

Read it when the work needs it. What it must **never** become is a place PHI leaks into:
if a tab ever starts holding per-employee text, it goes back on the list that day. The
encounter-level description files (`new_descriptions_for_library.csv`, `encounters.csv`)
are still off limits — those are about specific people.

**Use fake names in code, docs, and tests:** `"Smith, Jane"`, `"Doe, John"`.
See `encounters_template.csv` / `roster_template.xlsx`.

### What you CAN safely look at

- **`debug/*.html`** — page captures, scrubbed by `phi_redact.scrub_html()` **before**
  they're written. Allowlist-based: only known EMR UI strings survive, so a name can't
  be in there. These are for fixing selectors.
- **Console output** — `phi_redact` auto-redacts whenever stdout isn't a terminal
  (i.e. whenever *you* run something). Names print as `Employee #1`, descriptions as a
  character count. You learn *which row* failed and *why*, never *who*.
- **`.\Run-Encounters.ps1 -Check`** — validates the CSV. Reports row numbers and bad
  controlled values (`Row 4: coaching_type 'Safety' is not valid`), never names.
- **`python ati_coaching_encounter.py --audit`** — what the last run saved, skipped, or
  errored on. Redacted the same way.
- **Aggregate probes of a PHI file** — counts, lengths, value distributions of
  controlled vocabularies (shift, pay type, work titles). Print *counts, never cells*.
  This is how the roster and workbook were mapped without reading them.

`debug/*.png` are **off** by default (`DEBUG_SCREENSHOTS = False`). Screenshot masking
is a denylist and can't be proven clean — leave them off.

### Never commit PHI

`.gitignore` *is* the boundary. No PHI file has ever been committed in this repo's
history. Don't `git add -f` a gitignored file; don't relax the rules.

## Don't guess at what you can't see — measure it or ask

Every serious bug this project has shipped came from the same move: Claude couldn't see
something, guessed, and sounded confident. All three were caught by Dane, in production,
on real medical records:

- **Guessed the window height** (couldn't see his screen) → the buttons were off-screen.
  His logical screen is **1280x800**; size from `winfo_screenheight()`, never a literal.
- **Guessed the EMR roster row's name was its first line of text** (couldn't see the
  page) → the pre-flight reported all 77 names as "not found" and blamed his data.
  The name is `<span class="name">`; `update_employees._ROW_RE` documents the real row.
- **Guessed the description workbook's cells could be joined** (couldn't read it) →
  wrote `Choose "Other" | Job-Specific Coaching | EIS asked...` into 77 records.

The tell is a sentence like "the dashboard preloads the whole roster" or "the first row
is the header" written as fact in a docstring. If you cannot verify it, either measure
it with an aggregate probe (counts only) or ask Dane. He would much rather answer a
question than find it in a medical record.

When you do measure, check the *boundary*: the 60-char description cutoff is only sound
because the longest label is 54 and the shortest description is 62, with nothing between.

## "Ready to enter"

When Dane says **"ready to enter"**, "let's do the encounters", "I've got encounters to
put in", or anything to that effect — run the `/ready` command's playbook
(`.claude/commands/ready.md`): check the batch state with `.\Run-Encounters.ps1 -Check`
and show him the steps from `RUN_CHECKLIST.md`, in chat, adapted to what you find.

He asks *because he wants the steps in front of him.* Show them; don't just link the
file.

## Running it

```powershell
python encounter_builder.py                     # build encounters.csv from the roster
.\Run-Encounters.ps1                            # enter the batch (as drafts)
.\Run-Encounters.ps1 -Check                     # validate only, enter nothing
python ati_coaching_encounter.py --audit        # what the last run did (redacted)
python ati_coaching_encounter.py --resume       # drop rows the last run already saved
python emr_automate.py                          # menu: Build / Enter / Update Roster

python update_employees.py --from-hc <xlsx>     # HC export -> roster.xlsx (no browser)
python update_employees.py --report             # READ-ONLY roster<->EMR reconciliation
python update_employees.py --capture-sites      # READ-ONLY: which worksite? how many?
python update_employees.py                      # push roster.xlsx into the EMR
```

`--report` opens the browser but only reads: it writes `emr_not_in_roster.csv` (who is
in the EMR with no active-roster row — the deactivate-these worklist, with anyone
already inactive flagged and sorted to the bottom) and `roster_not_in_emr.csv` (new
hires to add by hand). A full run writes both **before** the confirmation popup, so
cancelling still leaves the worklists behind.

**Open question (2026-08-19): is the dashboard roster one worksite or all of them?**
Dane's EMR account contains employees from other ATI sites and he doesn't know how many.
The header names a single location and there's a group switcher beside it, which *looks*
site-scoped — but that is an inference, not a measurement. Until `--capture-sites`
settles it, `emr_not_in_roster.csv` is a review list, **not** a deactivate list: an
active employee at another site would appear on it looking exactly like a terminated one.

The browser opens **visibly on Dane's screen** and pauses on Windows dialogs for login,
worksite confirmation, and batch approval. You can't see that window and don't need to —
he clicks them. Encounters save as **drafts** (`SAVE_MODE = "draft"`); nothing is
finalized without him.

**A run that stops early** (expired session, circuit breaker) leaves the batch half
entered. Use `--resume`, never a plain re-run: it drops only the rows the audit log
confirms saved, so the rest can go in without drafting anyone twice.

## Writing descriptions with Dane (added 2026-08-24)

Assessments — physical, follow-up, task — **cannot be automated**. The entry engine only
ever clicks the "Coaching Encounter" tile, so Dane hand-enters every assessment. The help
that actually moves his backlog is **writing the description text**, which he pastes in.

This does not bend the PHI boundary. He describes the *scenario* — injury, body part,
mechanism, what he found, what he did. A **batch** version of the same exchange is
specced in `ENCOUNTER_INTAKE.md`: a de-identified spreadsheet in, labeled blocks out,
keyed by a `ref` column Dane maps back to people on his side. No names, no dates of birth, no badge or
identifier numbers, no date tied to a person. On 2026-08-24 he asked, under a report
deadline, to hand over the encounter file itself. That was declined; this is what replaced
it. **A deadline is not a reason to take the file** — and saying so once is enough, since
he already knows the rule and does not need it explained twice.

### The voice

Third person, `EIS` / `EE`, past tense, they/their — matching the workbook.

**Plain language, not clinical.** Dane, 2026-08-24: *"tone down the medical jargon. I'm
not a doctor and I'm not trying to sound like one. Think low level athletic trainer at
best."* So "rolled their ankle inward", not "inversion mechanism"; "walking with a limp",
not "antalgic gait"; "bruising", not "ecchymosis". The full translation table is in
`pa_templates.md`.

### Short. Shorter than feels finished

Refined by Dane the same day: *"I don't mind multiple sentences. I think it was mostly the
amount of detail you gave that made it too lengthy."* So the limit is **detail density,
not sentence count** — say what happened and what was covered, then stop. Don't elaborate
on why it matters, list every variation, or add a closing reassurance unless it was
actually part of the encounter.

Dane, 2026-08-24, on a five-sentence wellness description: *"enormous compared to what I
need... one is too long and detailed."* He deliberately gave no sentence limit — the
measure is the workbook, not a number. Real entries run **one to three sentences**:

> EIS and EE discussed mobility and stretches for the shoulders to maintain shoulder
> health during work related tasks.

That is a complete, in-use description. Write to that scale. Coaching descriptions are
the shortest; PA free-text fields carry more because the form has fewer of them. When
unsure, hand over the short version and a longer one and let him pick — never one long
one.

### The plain-language rule is per field, not global

It governs **Incident Details**, where Dane relays what the EE told him. It does **not**
govern palpation and observation — those are his own exam findings and they read like an
athletic trainer's notes. His verbatim sample, 2026-08-24:

> **palpation** — Trigger points present in forearms extensors, brachioradialis, and
> bicep brachii muscles. Limited passive ROM in wrist extension.
>
> **observation** — EE experienced mild pain while trying to lift 15 lb. kettlebell when
> testing the capacity of the affected region.

Named muscles, ROM terminology, and fragments are correct there. And **Observation is
functional capacity testing, not visual inspection** — what the EE did, under what load,
and what happened. Applying the plain-language rule to every field flattened both of
these before Dane supplied the sample.

### 🚨 Protective recommendations are NOT restrictions

On the Corrective Actions page, answering that the employee is capable of all essential job
tasks reveals a protective-recommendations question, and answering that Yes reveals a free
text field. **That text is the highest-stakes writing in the assessment.**

Dane, 2026-08-24: *"ATI is quite insistent that we get this distinction crystal clear and
not mess it up so that we don't have OSHA work-restriction issues."* A restriction limits
what an employee may do and carries OSHA consequences; a protective recommendation is a
suggestion they may adopt.

The workbook's `Protective Recommendations` tab shows the approved pattern — a permissive
verb (`Encourage`, `Promote`, `Allow`, `Consider`) plus a feasibility softener (`as workflow
allows`, `when feasible`, `during natural pauses`). Never write a numeric limit, `restricted
to`, `may not`, `must`, `light duty`, or `unable to`. The verb decides which side of the line
the sentence lands on. Full rule and the forbidden list: `pa_templates.md`.

### 🚫 Red-flag triage is not Claude's call

Page 4 of an assessment screens for red flags against `Red Flag Reference Sheet.pdf`
(transcribed in `pa_templates.md`). Its rule: **two or more** signs/symptoms can indicate
the need for outside referral or urgent transfer.

Claude **surfaces and counts matches** — naming the list item a scenario touches. Claude
**never writes these fields as negative and never clears anyone.** An absence found by
text-matching a written description is not an absence found by examining a person, and the
consequence of getting it wrong is a missed transfer.

### Exam findings stay blank

Palpation and observation are what **Dane** found. Templates leave them as `[ bracket
slots ]` and never pre-fill plausible-sounding findings. A template that reads as finished
gets pasted without a second look, and an invented finding in a medical record is worse
than an empty field.

### Controlled values still aren't guessable

Primary Complaint and Categorize Mechanism are dropdowns; their option lists are recorded
in `pa_templates.md` because **Dane supplied them**. Only page 1 of the PA has ever been
captured to `debug/` — pages 2–6 are known from his description, not from a measurement.
Anything not on a recorded list gets flagged for him to pick, not chosen.

## Layout

- `encounter_builder.py` — the batch builder (roster checklist, group apply, library)
- `ati_coaching_encounter.py` — the encounter automation (form filling, `snap()`, batch,
  pre-flight, `--audit`, `--resume`)
- `update_employees.py` — roster sync tool; also the reference for the EMR's roster row
  structure (`_ROW_RE`) and the session-expiry guard pattern
- `emr_field_map.py` — maps work areas / job titles to the EMR's dropdown values
- `name_match.py` — nickname-tolerant name matching; refuses ambiguous matches
- `phi_redact.py` — the redaction engine. **Allowlist, not denylist** — read its
  module docstring before changing it; the reasoning is subtle and load-bearing.
- `pa_templates.md` — PA / follow-up assessment templates, written in chat and saved
  as we go. Not PHI: a template is written for many people and is about no one
- `ENCOUNTER_INTAKE.md` — how Dane hands over a **batch** of encounters for description
  writing: de-identified spreadsheet in, labeled blocks out. Read it before processing
  `encounter_intake.xlsx` (gitignored)
- `library_candidates.md` — reusable descriptions staged for the Easy Enter workbook,
  each tagged with its target tab. Not PHI, safe to commit — but the contents are the
  guarantee: anything that can only be true of one person belongs in `pa_writeups.md`
- `pa_writeups.md` — **gitignored.** Finished PA / follow-up write-ups filed by
  encounter date, so Dane can pull a date range at once. Carries no names by design,
  but it logs real encounters on real dates — never commit it
- `mobile_import.py` — bridge for the (unfinished) mobile capture app
- `.github/copilot-instructions.md` — tells GitHub Copilot it is **not** PHI-cleared

Generated locally, gitignored, Dane's to maintain: `work_titles.csv` (work title →
Department/Division; blanks mean a blank department, which is safe) and
`builder_prefs.json` (which titles/shifts the builder hides).

## If you add a print statement

Route anything that could carry PHI through `phi_redact`:

- `ph(name)` — employee names → `Employee #1`
- `pv(value)` — field values (phone, DOB, identifier) → `[redacted:10]`
- `pd(text)` — free-text clinical descriptions → `[description redacted: 46 chars]`

They pass values through unchanged on a real terminal, so Dane still sees real names.

`mobile_import.py` **was** the exception — it printed names raw. It was fixed in
`31b3d8d`; every name now goes through `ph()` and descriptions are never printed. The
values it still prints unredacted are controlled vocabulary (department, coaching type,
date), which is the same choice the rest of the tool makes.
