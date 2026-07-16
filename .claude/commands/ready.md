---
description: Show the encounter-entry checklist, with the current state of the batch
---

Dane is ready to enter a batch of coaching encounters. Show him the steps, tailored to
what's actually on disk right now.

## Do this

1. Read `RUN_CHECKLIST.md`.

2. Check the current state — **without ever opening `encounters.csv`**:

   ```powershell
   .\Run-Encounters.ps1 -Check
   ```

   That prints the row count, the file's date, and whether it validates. Its errors name
   row numbers and bad dropdown values, never people. **Never `Read` the CSV itself** —
   it is PHI, and the whole arrangement depends on you not looking. See `CLAUDE.md`.

3. Show him the checklist in chat, adapted to what you found:

   - **A pending batch from an earlier date** (rows exist, dated before today) → lead
     with that. Those rows may not be entered yet, and writing from the builder will
     replace them (backing them up first). Ask whether to run `.\Run-Encounters.ps1`
     now, or build today's batch first.
   - **A valid batch from today** → he's probably mid-flow. Point him at
     `.\Run-Encounters.ps1` and offer to run it.
   - **An invalid CSV** → show the validator's errors. The fix is rebuilding those
     rows in `encounter_builder.py`, not hand-editing the CSV.
   - **No CSV** → clean slate. Start at step 1: `python encounter_builder.py`.

4. If he mentions a *skipped* or *unmatched* name from a previous run, remind him:
   fix it as a **one-person group** in the builder — never re-run the same
   `encounters.csv` (the other rows would draft again as duplicates). The redacted
   details are in `python ati_coaching_encounter.py --audit`.

## How to present it

Show the steps themselves — don't just tell him to go read the file. He's asking
*because* he wants the reminder in front of him.

Keep it tight and skimmable: the numbered steps, the exact commands, and what to click
where. Lead with anything that needs a decision from him (a pending batch, a broken
CSV) before the routine steps.
