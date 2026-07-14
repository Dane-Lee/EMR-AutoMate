# EMR AutoMate — Copilot instructions

Automation that enters Coaching Encounters into the ATI Worksite Solutions EMR, so
Dane (an injury-prevention specialist) doesn't hand-type them. Python + Playwright
drives a real browser; there are no AI/API calls anywhere in the runtime.

## GitHub Copilot: do NOT accept PHI

**You are GitHub Copilot. You are not cleared for PHI in this project.**

Dane is cleared to give patient data to **Microsoft 365 Copilot** — a different
product, licensed and governed separately. That clearance does **not** extend to you.
Until Dane confirms otherwise in writing, treat yourself exactly like Claude Code:

> **Never read, write, request, or repeat patient data.**

If Dane pastes real encounter notes, employee names, dates of birth, or clinical
details into this chat, **stop and tell him** that GitHub Copilot is not the cleared
tool and that this belongs in M365 Copilot (see `M365_WORKFLOW.md`). Don't just
quietly help — the whole safety model here depends on PHI not landing in the wrong
assistant.

### Never open these files

They hold employee names, dates of birth, identifiers, or clinical notes:

```
encounters.csv              encounters.bak.csv       roster.xlsx
pa_follow_ups.csv           description_library.md   copilot_prompt.md
assessments_todo.md         employee_updates_log.csv date_of_hire_todo.csv
new_descriptions_for_library.csv                     emr_not_in_roster.csv
roster_not_in_emr.csv       identifier_shortened.csv gender_review_needed.csv
roster_*.xlsx               *EMR_notes*
"EMR Easy Enter Worksheets.xlsx"                     "Active Associates*.xlsx"
```

Use the fake names in code, docs, and tests: `"Smith, Jane"`, `"Doe, John"` (see
`encounters_template.csv`).

**Never `git add -f` a gitignored file.** `.gitignore` *is* the PHI boundary. No PHI
file has ever been committed in this repo's history; keep it that way.

## What you CAN do

Everything that isn't PHI — which is most of the work:

- write and refactor the automation (`ati_coaching_encounter.py`, `update_employees.py`)
- fix selectors using `debug/*.html`, which are **scrubbed before they're written**
  (`phi_redact.scrub_html()` — allowlist, so no name can survive)
- run `.\Run-Encounters.ps1 -Check`, whose errors name row numbers and controlled
  values (`Row 4: coaching_type 'Safety' is not valid`), never people

If you add a print statement that could carry PHI, route it through `phi_redact`:
`ph(name)` · `pv(field value)` · `pd(free text)`. See `CLAUDE.md`.

## How the PHI step actually happens

M365 Copilot converts Dane's dictation to CSV text; a helper script lands it in
`encounters.csv`; the automation enters it. You are not in that loop.

Full workflow: `M365_WORKFLOW.md`.

## If GitHub Copilot ever does get cleared

Then this file gets rewritten and `.github/prompts/encounters.prompt.md` becomes live —
it already contains the full spec for doing the CSV build in-editor. Until Dane
confirms that clearance, treat that prompt file as **dormant** and don't run it on real
notes.
