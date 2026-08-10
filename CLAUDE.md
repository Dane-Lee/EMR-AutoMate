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
```

The browser opens **visibly on Dane's screen** and pauses on Windows dialogs for login,
worksite confirmation, and batch approval. You can't see that window and don't need to —
he clicks them. Encounters save as **drafts** (`SAVE_MODE = "draft"`); nothing is
finalized without him.

**A run that stops early** (expired session, circuit breaker) leaves the batch half
entered. Use `--resume`, never a plain re-run: it drops only the rows the audit log
confirms saved, so the rest can go in without drafting anyone twice.

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
**`mobile_import.py` does not do this** — it prints names raw and must be fixed before
it is used again.
