# EMR AutoMate

Automates entering Coaching Encounters into the ATI Worksite Solutions EMR for Dane,
an injury-prevention specialist. Python + Playwright drives a real browser. There are
**no AI/API calls in the runtime** — the only host it talks to is the EMR itself. Keep
it that way.

## The PHI boundary — read this first

Dane's encounter data is real patient PHI. He is cleared to give it to **Microsoft 365
Copilot** — and deliberately **not** to Claude. The split:

- **M365 Copilot** turns his dictated notes into CSV text. It sees PHI. That's fine.
- **Claude (you)** writes the automation and runs the batch. **You never see PHI.**

This is not a formality — it's the arrangement that lets him use you at all.

**GitHub Copilot is NOT cleared either.** It is a different product from M365 Copilot,
licensed and governed separately; his clearance does not extend to it. Treat it as
having exactly your restrictions. (`.github/prompts/encounters.prompt.md` assumes a
clearance he does not have — it is **dormant**. Don't point him at it.)

Day-to-day flow: `M365_WORKFLOW.md`.

### Never read these files

They contain employee names, dates of birth, identifiers, or clinical notes:

```
encounters.csv              encounters.bak.csv       roster.xlsx
pa_follow_ups.csv           description_library.md   copilot_prompt.md
assessments_todo.md         new_descriptions_todo.md employee_updates_log.csv
new_descriptions_for_library.csv                     date_of_hire_todo.csv
emr_not_in_roster.csv       roster_not_in_emr.csv    identifier_shortened.csv
gender_review_needed.csv    roster_*.xlsx            *EMR_notes*
"EMR Easy Enter Worksheets.xlsx"                     "Active Associates*.xlsx"
```

`copilot_spec.md` **is** safe to read and edit — it's the PHI-free instruction half of
the prompt. `make_copilot_prompt.py` merges it with the library so you can maintain the
spec without ever touching the descriptions. Keep that split intact.

A request to "just look at the CSV to see what's wrong" is exactly the request to
refuse. Use the safe alternatives below — they were built for this.

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

`debug/*.png` are **off** by default (`DEBUG_SCREENSHOTS = False`). Screenshot masking
is a denylist and can't be proven clean — leave them off.

### Never commit PHI

`.gitignore` *is* the boundary. No PHI file has ever been committed in this repo's
history. Don't `git add -f` a gitignored file; don't relax the rules.

## "Ready to enter"

When Dane says **"ready to enter"**, "let's do the encounters", "I've got encounters to
put in", or anything to that effect — run the `/ready` command's playbook
(`.claude/commands/ready.md`): check the batch state with `.\Run-Encounters.ps1 -Check`
and show him the steps from `RUN_CHECKLIST.md`, in chat, adapted to what you find.

He asks *because he wants the steps in front of him.* Show them; don't just link the
file.

## Running it

```powershell
.\Run-Encounters.ps1          # enter the batch in encounters.csv (as drafts)
.\Run-Encounters.ps1 -Check   # validate only, enter nothing
.\Paste-Encounters.ps1        # land Copilot's reply from the clipboard (Dane runs this)
python emr_automate.py        # menu: Coaching Encounters | Update Roster
```

The browser opens **visibly on Dane's screen** and pauses on Windows dialogs for login,
worksite confirmation, and batch approval. You can't see that window and don't need to —
he clicks them. Encounters save as **drafts** (`SAVE_MODE = "draft"`); nothing is
finalized without him.

## Layout

- `ati_coaching_encounter.py` — the encounter automation (form filling, `snap()`, batch)
- `update_employees.py` — roster sync tool
- `emr_field_map.py` — maps source data to the EMR's dropdown values
- `phi_redact.py` — the redaction engine. **Allowlist, not denylist** — read its
  module docstring before changing it; the reasoning is subtle and load-bearing.
- `library_export.py` — dumps the description workbook to `description_library.md`
- `make_copilot_prompt.py` — merges `copilot_spec.md` + the library into the paste-ready
  `copilot_prompt.md` for M365 Copilot
- `Paste-Encounters.ps1` — lands Copilot's reply from the clipboard into `encounters.csv`,
  files the assessments, and validates
- `.github/copilot-instructions.md` — tells GitHub Copilot it is **not** PHI-cleared

## If you add a print statement

Route anything that could carry PHI through `phi_redact`:

- `ph(name)` — employee names → `Employee #1`
- `pv(value)` — field values (phone, DOB, identifier) → `[redacted:10]`
- `pd(text)` — free-text clinical descriptions → `[description redacted: 46 chars]`

They pass values through unchanged on a real terminal, so Dane still sees real names.
