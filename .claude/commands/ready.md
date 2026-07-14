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
     with that. Those rows may not be entered yet, and step 4 will replace them
     (backing them up first). Ask whether to run `.\Run-Encounters.ps1` now, or move on
     to dictating new ones.
   - **A valid batch from today** → he's probably mid-flow. Point him at step 6 and
     offer to run it.
   - **An invalid CSV** → show the validator's errors and point him at step 5: paste
     them back to Copilot.
   - **No CSV** → clean slate. Start at step 1.

4. Confirm `copilot_prompt.md` exists. If it doesn't, he needs to run
   `python library_export.py` then `python make_copilot_prompt.py` first.

## How to present it

Show the steps themselves — don't just tell him to go read the file. He's asking
*because* he wants the reminder in front of him.

Keep it tight and skimmable: the numbered steps, the exact commands, and what to copy
where. Lead with anything that needs a decision from him (a pending batch, a broken
CSV) before the routine steps.
