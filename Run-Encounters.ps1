<#
    Run-Encounters.ps1 — enter the encounters in encounters.csv into the EMR.
    ==========================================================================
    This is the command to hand to an AI assistant (or a scheduled task) when you
    want the batch entered but do NOT want to hand over any PHI.

    THE SPLIT
        encounter_builder.py       writes encounters.csv — you check names off the
                                   roster and set the coaching once per group. It
                                   runs on this PC and talks to nothing.
        This script                reads encounters.csv and drives the EMR.
        Claude (never sees PHI)    just runs this script.

    WHY THAT IS SAFE
        The automation makes no AI/API calls of any kind — the only host it talks to
        is the EMR itself. So the assistant running it never sees encounters.csv;
        it only sees this script's stdout. And because stdout is captured (not a
        terminal) when an assistant runs it, phi_redact switches on automatically:
        names print as "Employee #1", the clinical description prints as a character
        count. Debug captures are scrubbed before they hit the disk regardless.

        Net effect: the assistant sees WHICH ROW failed and WHY, never WHO.

    USAGE
        pwsh -File .\Run-Encounters.ps1          # normal run
        pwsh -File .\Run-Encounters.ps1 -Check   # validate the CSV, enter nothing

    YOU WILL STILL CLICK THINGS
        The browser opens visibly and pauses on Windows dialogs for you to log in,
        confirm the worksite, and approve the batch. Those are yours to click; the
        assistant cannot see the browser window. Encounters save as DRAFTS
        (SAVE_MODE = "draft"), so nothing is finalized without you.
#>

[CmdletBinding()]
param(
    # Validate encounters.csv and print the plan, without opening a browser.
    [switch]$Check
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$csv = Join-Path $PSScriptRoot "encounters.csv"
if (-not (Test-Path $csv)) {
    Write-Host "No encounters.csv found in $PSScriptRoot" -ForegroundColor Yellow
    Write-Host "Build one:  python encounter_builder.py   (check names off the roster)"
    Write-Host "Full steps: RUN_CHECKLIST.md  (or ask Claude: 'ready to enter')"
    exit 1
}

# Report on the CSV without echoing its contents — the row count and modified time
# are enough to confirm the right file is about to run, and neither is PHI.
$info = Get-Item $csv
$rows = @(Import-Csv $csv).Count
Write-Host "encounters.csv: $rows row(s), last modified $($info.LastWriteTime)" -ForegroundColor Cyan

# Run the real validator (the same one the automation uses, so a pass here means the
# batch will actually run). Its error messages name the row number and the offending
# dropdown value — "Row 4: coaching_type 'Safety' is not valid" — and suppress any
# value too long to be a dropdown, which is how a misaligned row's clinical text would
# otherwise leak out.
#
# Redaction is NOT forced here: phi_redact keys off stdout.isatty(), so Dane sees real
# values in his terminal (he needs them to fix a row) while a captured run — an
# assistant, a log pipe — gets them redacted automatically.
python -c @"
from ati_coaching_encounter import load_encounters_csv, batch_warnings, ENCOUNTERS_CSV
import sys
encs, errors = load_encounters_csv(ENCOUNTERS_CSV)
if errors:
    print(f'INVALID - {len(errors)} problem(s):')
    for e in errors:
        print('  -', e)
    sys.exit(1)
print(f'VALID - {len(encs)} encounter(s) ready to enter.')
warns = batch_warnings(encs)
if warns:
    print()
    print('CHECK THESE (not errors, but worth a look before entering):')
    for w in warns:
        print('  !', w)
"@
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fix encounters.csv and re-run. Nothing was entered." -ForegroundColor Red
    exit 1
}

if ($Check) {
    Write-Host "-Check: validated only. Nothing was entered." -ForegroundColor Yellow
    exit 0
}

# No forced redaction flag: phi_redact decides from stdout.isatty(). Dane's own
# terminal shows real names; an assistant or log pipe capturing this gets aliases.
Write-Host "Starting EMR AutoMate..." -ForegroundColor Cyan

# Straight into the encounters flow, skipping emr_automate.py's task chooser — this
# script has already decided which task is running.
python -c "import asyncio, ati_coaching_encounter; asyncio.run(ati_coaching_encounter.run())"
exit $LASTEXITCODE
