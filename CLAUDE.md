# EMR AutoMate

Automates entering Coaching Encounters into the ATI Worksite Solutions EMR for Dane,
an injury-prevention specialist. Python + Playwright drives a real browser. The only
host the automation itself talks to is the EMR.

Dane builds a batch by checking names off the roster in `encounter_builder.py`; the
automation enters it as drafts. There is no dictation anywhere in the pipeline — the
M365 Copilot intake was removed 2026-07-16 because the dictation round-trip was
miserable and an LLM kept guessing at controlled values it had no business guessing.
**Don't reintroduce it.**

### The one AI call, and why it is not that (added 2026-09-04)

`encounter_builder.py` can now send a batch's **description notes** to a headless
`claude -p` when Dane writes the batch: he ticks "Note only", types *"hydration and
magnesium"*, and gets the description back. He can also leave the coaching type as
**"— suggest it from my note —"** and get a recommendation. Dane asked for both.

That is not the thing that was removed, and the difference is worth being precise about:

| removed 2026-07-16 | added 2026-09-04 |
|---|---|
| dictation → transcript → an LLM | Dane types the note himself |
| the LLM chose controlled values from prose | he sets every controlled value but one |
| its picks flowed to the record unreviewed | he reviews every suggestion, and ticks every detail box himself |

The guards, in `_resolve_pending`:

- **A suggested coaching type is checked against `COACHING_TYPE_UUIDS`** before it can
  touch a row. An off-list answer is refused, not corrected.
- **All or nothing.** If any job comes back short, `encounters.csv` is not written. A
  note is not a description and the sentinel is not a coaching type.
- **Detail checkboxes, encounter type, category, department, shift and date are never
  asked for and never accepted.** Dane sets all of them.
- **The notes are scanned against the loaded roster before anything is sent.**
  `ENCOUNTER_INTAKE.md` concedes Claude cannot make that check — by the time it could
  look it has already read the note. The builder can, because the names are in memory.

What crosses the line is the note, a head count, and the coaching type. No name, no
date, no department, no shift. The map from a job back to the people in it is the
group's index in the batch and never leaves the process. This is
`ENCOUNTER_INTAKE.md`'s de-identified handover with the spreadsheet taken out, and it
sits on no new exception to the PHI boundary. Tests: `test_description_writing.py`.

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
case_report*.xlsx           case_report*.docx
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

python case_report.py --capture                 # READ-ONLY: snap + census the Case List
python case_report.py --capture-filters         # READ-ONLY: snap each filter chip
python case_report.py --survey --specialist X   # READ-ONLY: counts only (pages, rows)
python case_report.py --capture-case --specialist X   # READ-ONLY: one case summary
python case_report.py --from 09/01/2026 --to 09/08/2026 --format both --specialist X
python case_report.py --demo                    # the writers, fake names, no browser
```

`--specialist` is **required** for a report and takes the name as the EMR's Specialists
filter spells it; the builder passes it from `builder_prefs.json`.

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

## Reading a batch back out: the Case list report (added 2026-09-08)

The builder is now a **two-tab window**. "Build a batch" is everything above,
unchanged, moved onto a tab. **"Case list report"** runs the other direction: pick a
date range, pick Excel / Word / both, and `case_report.py` opens the EMR's **Case
List**, reads it, and writes a local report grouped

    date → case type → coaching type → employee (alphabetical)

Dane chose that shape and chose the **Date of Encounter** as the date it filters on
(2026-09-08) — not when the case was keyed in, which drifts whenever a batch goes in
days later. Excel also gets a flat filterable sheet and a counts summary; Word gets
the reading layout only.

It is **read-only**, the same standing as `update_employees --report`: it navigates,
it reads, it closes. It never opens a case for editing.

The **"In Progress" modal blocks the way in.** After login the EMR asks *"navigate to
the 'In Progress' case list?"* whenever Dane has drafts — i.e. nearly always — and it
sits over the page and swallows the sidebar click. `open_case_list` answers **No**
first, reusing `ati_coaching_encounter.dismiss_in_progress_prompt` (the entry engine
has cleared this same modal since 2026-07-23). Yes would land on the drafts list, and
the reader would page through drafts instead of cases.

The finished file **opens itself** (`open_file`), and the tab has an **Open last
report** button for a run from another day — Dane asked not to go hunting in the
project folder (2026-09-08). `--no-open` suppresses it. Neither path reads the file;
they hand the path to Windows.

**The output is PHI** — every line is a real person on a real date. `case_report*.xlsx`
and `case_report*.docx` are gitignored and on the never-read list above.

### 🚨 The encounter date sits next to the date of birth

Measured 2026-09-08, and the single most dangerous thing on that page. **The date is
not a column.** It is the third labelled `title`/`value` pair inside the *Employee*
cell:

```
Smith, Jane
DOB:      --                 ← the employee's DATE OF BIRTH
ID:       99999-Weld-1st
Enc.D. :  Jan 01, 1990       ← the date the report filters on
```

`parse_case_rows` matches **by label**, normalising `"Enc.D. :"` to `encd`, and
`_FORBIDDEN_LABELS` refuses `dob` and `id` outright. It never reads by position, and a
row with no `Enc.D.` pair comes back `date=None` and is counted out loud rather than
borrowing whatever date is nearby. A positional read that slipped one row would file
every case under a date of birth, in a document that goes to ATI.
`test_case_report.py` puts a real date in the DOB slot to keep that honest.

### What the Case List does and doesn't carry

- **Case type** is the coloured chip, and it is **abbreviated** (`HMA`, and two- and
  six-character codes). It goes into the report as the page writes it — no invented
  expansion to a full name.
- **Coaching type is not on this page at all.** Dane asked for that level and the
  grouping still has it; it simply comes out empty, and both the tab and the report's
  Summary sheet say so. The only place it could come from is each case's own summary
  page, which has never been captured — so it is not written.
- **No status** either.
- **Location** is there, and every row is Dane's own worksite (he checked 2026-09-08).

### 🚨 A follow-up's date is NOT on the Case List — the report is incomplete

Dane, 2026-09-08. A follow-up is entered with **its own date**, but the Case List row
keeps showing the case's **original** Enc.D. So a follow-up done last week on a case
opened in February is invisible to a range filter over the displayed date.

`FOLLOWUP_CAVEAT` is stamped on the workbook, the Word document and the finishing
dialog. **That is a stopgap.** Under-reporting silently is the worst failure this tool
has: a short list of last week's work looks exactly like a light week. The fix needs
the case summary page (`/cases/summary?id=…`), which **has never been captured** —
`--capture-case` is the one command that unblocks it. See `TODO.md`.

Only **104 of 2,211** cases carry follow-ups (measured), and a follow-up is always
*after* its case's original date, so cases originating after the range end can be
skipped. That is what makes opening them one at a time affordable.

### The specialist filter is mandatory, and the walk sweeps everything

**Unfiltered, the list mixes in other specialists' cases.** `run_report` refuses
without a `--specialist`, and `apply_specialist_filter` ticks that name and applies it
before anything is read. Which chip is the specialist filter is **not** decided by its
label — it tries the likeliest first, but what identifies it is finding the name among
its options. Ambiguous name → picks nobody. The name lives in `builder_prefs.json`
(gitignored); it is Dane's own and has no business in tracked source.

`harvest()` walks **every page, every time** — there is no early stop. There used to
be one, resting on the list being newest-first. The survey measured that and it is
false: across 2,211 cases the displayed date drops **174 times within a page and 5
times between pages**. The list is ordered by something the page doesn't show,
plausibly last activity, while displaying each case's original date. Truncating on an
order that isn't there would cut the report short somewhere unpredictable.

Sweeping is affordable because the same survey measured it: **74 pages at 30 rows,
about two minutes** for his whole caseload (2026-02-24 .. 2026-09-03 — six months, not
the years the four-digit pager implied; that count was other specialists' cases).
`MAX_PAGES = 400` is a wall, and hitting it is reported, not hidden.

### The read-only probes, and why there are four

Each one exists because something could not be answered from a desk. All are
read-only, all write to `debug/`, none change the EMR.

- `--capture` — the page's markup + a **structure census** (tag/class signatures and
  counts, never text), with the preloaded 957-row employee sidebar pruned so the real
  content isn't buried.
- `--capture-filters` — opens each filter chip and snaps it. This is how the
  specialist filter's markup was measured.
- `--survey` — walks the filtered list and reports **counts only**: pages, rows,
  follow-up histogram, how far the dates depart from newest-first. This is the run
  that killed the early stop.
- `--capture-case` — opens one case that has follow-ups and snaps its summary page.
  **Not yet run.** It is the next step.

`diagnose_dates` deserves its own note: when no date parses it writes
`debug/CASES_date_diagnosis.txt` with the labels and the value's **shape** —
`Aaa 99 9999`, digits to 9 and letters to A/a. A shape is a format, not a date, so it
can be read freely; that is how `Sep 08 2026` (no comma) was found without anyone
looking at a real one.

### The capture is still there

`--capture` opens the page read-only, snaps the scrubbed HTML to `debug/`, and prints a
**structure census** — tag/class signatures and counts, never text, with the preloaded
957-row employee sidebar pruned so the actual page content isn't buried. Run it again
if the EMR changes and the reader starts coming up short; that is how the parser was
written in the first place, and `PARSER_READY` is the switch that keeps a
never-measured page from being read by a guess.

## Layout

- `encounter_builder.py` — the batch builder (roster checklist, group apply, library),
  and the note → description round trip described above (`_resolve_pending`).
  Two tabs since 2026-09-08: the builder, and the Case list report
- `case_report.py` — the report tab's engine. READ-ONLY read of the EMR's Case List,
  the grouping/sorting, both writers, and the structure census that measures the page.
  Tests: `test_case_report.py`
- `intake_runner.py` — the headless `claude -p` transport. `run()` serves the intake
  grid; `run_coaching()` serves the builder. One call per batch, never one per row
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
