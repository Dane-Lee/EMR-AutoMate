# The daily workflow

How a day's coaching encounters get into the EMR. No dictation, no Copilot, no AI
anywhere in the path — the batch is built by checking names off the roster on this PC,
and the only host anything talks to is the EMR itself.

## Who sees what

| | PHI? | Job |
|---|---|---|
| **You** | obviously | Check names, set the coaching, click the browser dialogs. |
| **Your PC** | yes | The builder writes `encounters.csv`; the automation drives the EMR. |
| **Claude** | **never** | Writes and fixes the automation. Sees only redacted output. |
| **GitHub Copilot** | **never** | Not cleared. `.github/copilot-instructions.md` tells it so. |

---

## Every day

### 1. Build the batch

```powershell
python encounter_builder.py        # or:  python emr_automate.py → Build a Batch
```

- **Filter** the roster: shift checkboxes and the work-title list hide people you
  never coach (Admin, the other shift). Hidden groups stay hidden between runs.
- **Check off** everyone in the first group — filter + "Check all shown" takes a
  whole area at once. Checks survive filter changes.
- **Set the coaching once** for that group: type, details, description (the
  **Library…** button has your standard descriptions), date, prompted-by.
- **Department/shift per person** comes from the roster automatically ("Each
  employee's own"). For a one-area sweep, switch to "Same for everyone" and type the
  work area — "station 85" fills the dropdowns.
- **Add group to batch.** Repeat for each distinct group in the day.

### 2. Write & enter

The **Write & enter batch** button writes `encounters.csv` (backing up the previous
one), validates, and offers to start the EMR run. Or do it by hand:

```powershell
.\Run-Encounters.ps1 -Check    # validate only
.\Run-Encounters.ps1           # enter the batch
```

A browser opens. Log in, confirm the worksite, approve the batch. Every encounter
saves as a **draft** — nothing is final until you review it in the EMR's InProgress
list.

### 3. After the run

```powershell
python ati_coaching_encounter.py --audit
```

Shows what saved, what was skipped, and why. Then finalize the drafts in the EMR.

**If a name didn't match:** fix it in a **one-person group** in the builder and enter
just that one. **Never re-run the same encounters.csv** — that re-enters everyone
else as duplicate drafts.

**If a department was blank:** that person's work title isn't mapped yet — fill in
their row in `work_titles.csv` once and it's mapped forever.

---

## Handing the run to Claude

Ask Claude to run the batch and it still sees no PHI. It never opens
`encounters.csv`, and the script's console output is redacted whenever it's captured
rather than shown in a terminal: names print as `Employee #1`, descriptions as a
character count. So Claude can tell you *"row 12 was skipped — name not matched"*
and fix the matcher, without ever learning who row 12 is.

## Assessments

The builder covers the 11 coaching types. Physicals, HMAs, Office/Task assessments
and Work Readiness are separate EMR case types — enter those by hand for now.
