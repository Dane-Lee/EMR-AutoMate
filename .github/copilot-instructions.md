# EMR AutoMate — Copilot instructions

Automation that enters Coaching Encounters into the ATI Worksite Solutions EMR, so
Dane (an injury-prevention specialist) doesn't hand-type them. Python + Playwright
drives a real browser; there are no AI/API calls anywhere in the runtime.

## GitHub Copilot: do NOT accept PHI

**You are GitHub Copilot. You are not cleared for PHI in this project.**

Treat yourself exactly like Claude Code:

> **Never read, write, request, or repeat patient data.**

If Dane pastes real encounter notes, employee names, dates of birth, or clinical
details into this chat, **stop and tell him** — this project has no AI-facing PHI
path at all, and the whole safety model depends on PHI not landing in an assistant.
Don't just quietly help.

### Never open these files

They hold employee names, dates of birth, identifiers, or clinical notes:

```
encounters.csv              encounters.bak.csv       roster.xlsx
encounter_log.csv           pa_follow_ups.csv        employee_updates_log.csv
assessments_todo.md         date_of_hire_todo.csv    emr_not_in_roster.csv
new_descriptions_for_library.csv                     identifier_shortened.csv
roster_not_in_emr.csv       gender_review_needed.csv
roster_*.xlsx               *EMR_notes*
"EMR Easy Enter Worksheets.xlsx"                     "Active Associates*.xlsx"
```

Use the fake names in code, docs, and tests: `"Smith, Jane"`, `"Doe, John"` (see
`encounters_template.csv`).

**Never `git add -f` a gitignored file.** `.gitignore` *is* the PHI boundary. No PHI
file has ever been committed in this repo's history; keep it that way.

## What you CAN do

Everything that isn't PHI — which is most of the work:

- write and refactor the automation (`encounter_builder.py`,
  `ati_coaching_encounter.py`, `update_employees.py`)
- fix selectors using `debug/*.html`, which are **scrubbed before they're written**
  (`phi_redact.scrub_html()` — allowlist, so no name can survive)
- run `.\Run-Encounters.ps1 -Check`, whose errors name row numbers and controlled
  values (`Row 4: coaching_type 'Safety' is not valid`), never people

If you add a print statement that could carry PHI, route it through `phi_redact`:
`ph(name)` · `pv(field value)` · `pd(free text)`. See `CLAUDE.md`.

## Don't guess at what you can't see

Every serious bug this project shipped came from an assistant guessing at something it
couldn't see and writing the guess into a docstring as fact — the EMR's roster row
shape, the description workbook's columns, the screen size. All three reached real
medical records. If you can't verify it, measure it with an aggregate probe (counts
only, never cell contents) or ask Dane. See `CLAUDE.md`.

## How a batch is built

Dane checks names off the roster in `encounter_builder.py`, which can only emit values
the EMR accepts; the automation enters them as drafts. There is no dictation and no AI
in the pipeline. The old M365 Copilot intake was removed 2026-07-16 — don't
reintroduce it.

Full workflow: `WORKFLOW.md`.
