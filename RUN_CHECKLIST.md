# Ready to enter — quick checklist

Everything runs in **VS Code's terminal**: press `` Ctrl+` `` to open it.
The `.\` in front of each command is required.

---

### 1 · Open the builder
```powershell
python encounter_builder.py
```
*(or `python emr_automate.py` → **Build a Batch**)*

### 2 · Check off who you saw
Filter by shift / work title, click names to check them. Filter + **Check all shown**
takes a whole area in one go. Checks survive filter changes.

### 3 · Set the coaching once per group
Coaching type (it will not guess one for you), details, description — **Library…**
holds your standard ones. Department & shift come from each person's roster record;
switch to "Same for everyone" for a one-area sweep. **Add group to batch**, repeat.

### 4 · Write & enter
The **Write & enter batch** button validates and offers to start the run.
Previous `encounters.csv` is backed up first, never lost. By hand instead:
```powershell
.\Run-Encounters.ps1 -Check    # validate only, enter nothing
.\Run-Encounters.ps1           # enter the batch
```

### 5 · Click the browser dialogs
Log in → confirm the worksite → approve the batch. It fills the forms. The console
prints `Roster loaded: ~948 employee(s)` and then resolves every name **before**
entering anything — a bad name is skipped, not guessed.

### 6 · Finalize in the EMR
Everything saved as **drafts** in the InProgress list. Nothing is a record until you
review and finalize it there.

### 7 · Mop up
```powershell
python ati_coaching_encounter.py --audit
```
Anything skipped is listed with its row and reason.
- **Unmatched name** → build a **one-person group** in the builder and enter just
  that one. **Never re-run the same encounters.csv** — the other rows would draft
  again as duplicates.
- **Blank department** → map that work title once in `work_titles.csv`.

---

## Handing step 4–5 to Claude
Just say **"run the encounters."** Claude never opens the CSV, and the output comes
back redacted — it sees `Employee #7 didn't match the roster`, not who that is.

## Common snags
| What you see | What it means |
|---|---|
| `INVALID - Row N: ...` | A value the EMR doesn't accept. The builder can't produce one — a hand-edit can. Rebuild the row in the builder. |
| `Roster loaded: 0 employee(s)` / "roster didn't load" | The dashboard wasn't ready — browser not logged in or worksite not selected. Fix in the browser, run again. Nothing was entered. |
| `1 name(s) could NOT be resolved` | That person isn't in the EMR list under that name (new hire, spelling). Skipped safely; see Mop up. |
| `encounters.csv: N row(s)` from an old date | A previous batch is still sitting there. Enter it, or write over it from the builder (it backs up first). |
| Browser opens to a login page | Expected. Log in; it remembers you next time. |
