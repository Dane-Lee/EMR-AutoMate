# The daily workflow (M365 Copilot)

How a day's coaching encounters get from your mouth into the EMR, without any patient
data reaching Claude.

## Who sees what

| | PHI? | Job |
|---|---|---|
| **You** | obviously | Dictate. Click the browser dialogs. |
| **M365 Copilot** | **yes — cleared** | Turns your dictation into CSV text. |
| **Your PC** | yes | Scripts land the CSV and drive the EMR. Talk to nothing but the EMR. |
| **Claude** | **never** | Writes and fixes the automation. Sees only redacted output. |
| **GitHub Copilot** | **never** | Not cleared. Treat it like Claude. |

The automation makes **no AI or API calls of any kind** — the only host it contacts is
the EMR itself. So nothing you dictate ever leaves your machine except into M365
Copilot, which you're cleared to use.

---

## One-time setup

```powershell
python library_export.py        # workbook  -> description_library.md
python make_copilot_prompt.py   # spec + library -> copilot_prompt.md
```

Re-run **both** whenever you add descriptions to `EMR Easy Enter Worksheets.xlsx`.

---

## Every day

### 1. Start a Copilot chat and paste the prompt

Open `copilot_prompt.md`, select all, copy, paste into a **fresh** M365 Copilot chat.
It contains the column spec, the EMR's exact vocabularies, and your whole description
library. Copilot will wait for your notes.

*(Fresh chat each day — an old one drifts and starts inventing column values.)*

### 2. Dictate

Talk through the day's encounters however they come out. Messy is fine; it cleans up.
It won't invent clinical content, and anything garbled comes back marked
`[unclear: ...]` for you to fix rather than silently guessed at.

### 3. Copy its whole reply, then run one command

```powershell
.\Paste-Encounters.ps1
```

It reads the clipboard and splits the reply up for you:

- the `csv` block → **`encounters.csv`** (your previous one is backed up, never lost)
- `ASSESSMENTS` → **`assessments_todo.md`** — the tool can't enter these yet; do them by hand
- `NEW DESCRIPTIONS` → **`new_descriptions_todo.md`** — fold the keepers into the workbook

Then it validates. If Copilot got a value wrong, you'll see exactly which row and what's
allowed:

```
INVALID - 1 problem(s):
  - Row 3: detail 'Bogus Detail' is not valid for Safety Coaching.
    Valid: 3-point contact, Awareness/alertness, Other, PPE Use, ...
```

Paste that line back to Copilot, it fixes the row, re-copy, re-run. It won't let a bad
batch through to the EMR.

### 4. Enter the batch

```powershell
.\Run-Encounters.ps1
```

A browser opens. Log in, confirm the worksite, approve the batch — the automation fills
each form. Encounters save as **drafts**, so nothing is final until you review them in
the EMR's InProgress list.

---

## Handing it to Claude

You can ask Claude to run step 4 (`.\Run-Encounters.ps1`) and it still sees no PHI.
It never opens `encounters.csv`, and the script's console output is redacted whenever
it's captured rather than shown in a terminal: names print as `Employee #1`,
descriptions as a character count.

So Claude can tell you *"Employee #7 didn't match the roster"* and go fix the matcher,
without ever learning who Employee #7 is.

## The files Claude must never open

`encounters.csv` · `encounters.bak.csv` · `copilot_prompt.md` ·
`description_library.md` · `assessments_todo.md` · `new_descriptions_todo.md` ·
`roster.xlsx` · `pa_follow_ups.csv` · the source workbooks

All gitignored, and listed in `CLAUDE.md`. No PHI file has ever been committed to this
repo — worth keeping true.

## If GitHub Copilot ever gets cleared

`.github/prompts/encounters.prompt.md` already has the full spec for doing this
in-editor, where Copilot writes `encounters.csv` directly and steps 1–3 collapse into
"dictate into VS Code." It's dormant until you confirm that clearance. Don't use it on
real notes before then.
