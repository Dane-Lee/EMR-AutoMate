# Ready to enter — quick checklist

Everything runs in **VS Code's terminal**: press `` Ctrl+` `` to open it.
The `.\` in front of each command is required.

---

### 1 · Copy the prompt
Open **`copilot_prompt.md`** → click in it → `Ctrl+A` → `Ctrl+C`

### 2 · Paste into a **fresh** M365 Copilot chat
New chat every day — an old one drifts and starts inventing column values.
Copilot will acknowledge and wait for your notes.

### 3 · Dictate your encounters
Messy, out of order, run-on — all fine. It won't invent clinical content.
Anything it couldn't make out comes back marked `[unclear: ...]` for you to fix.

It replies with 3 sections: **CSV**, **ASSESSMENTS**, **NEW DESCRIPTIONS**.

### 4 · Copy its **whole reply** (not just the CSV), then:
```powershell
.\Paste-Encounters.ps1
```
Splits the reply up for you and validates it:
- CSV → `encounters.csv` *(previous batch backed up, never lost)*
- assessments → `assessments_todo.md` *(enter these by hand — tool can't yet)*
- new descriptions → `new_descriptions_todo.md` *(fold keepers into the workbook)*

> **Copy Copilot's reply immediately before running this.** The script reads whatever
> is on your clipboard right then. If it says "No CSV found," you copied something
> else in between — nothing is harmed, just re-copy and re-run.

### 5 · If it says INVALID
It names the row and the allowed values. Paste that line straight back to Copilot →
it fixes the row → copy the new reply → press **↑** in the terminal → Enter.
Repeat until `VALID`. A bad batch cannot reach the EMR.

### 6 · Enter the batch
```powershell
.\Run-Encounters.ps1
```
Browser opens → log in → confirm the worksite → approve the batch. It fills the forms.

### 7 · Finalize in the EMR
Everything saved as **drafts** in the InProgress list. Nothing is a record until you
review and finalize it there.

### 8 · Mop up
Check **`assessments_todo.md`** for anything needing manual entry.

---

## Handing step 6 to Claude
Just say **"run the encounters."** Claude never opens the CSV, and the output comes back
redacted — it sees `Employee #7 didn't match the roster`, not who that is.

## After you add descriptions to the workbook
```powershell
python library_export.py
python make_copilot_prompt.py
```
Regenerates `copilot_prompt.md` with the new descriptions baked in.

## Common snags
| What you see | What it means |
|---|---|
| `No CSV found in the clipboard` | You copied something else after Copilot's reply. Re-copy, re-run. |
| `INVALID - Row N: ...` | Copilot used a value the EMR doesn't accept. Paste the error back to it. |
| `encounters.csv: N row(s)` from an old date | A previous batch is still sitting there. Enter it, or let step 4 replace it (it backs it up first). |
| Browser opens to a login page | Expected. Log in; it remembers you next time. |
