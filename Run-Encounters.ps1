<#
    Run-Encounters.ps1 — enter the encounters in encounters.csv into the EMR.
    ==========================================================================
    This is the command to hand to an AI assistant (or a scheduled task) when you
    want the batch entered but do NOT want to hand over any PHI.

    THE SPLIT
        Copilot (cleared for PHI)  writes encounters.csv from your dictated notes.
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
    Write-Host "Have Copilot write one first (see TRANSCRIPTION_PROMPT.md for the column spec)."
    exit 1
}

# Report on the CSV without echoing its contents — the row count and modified time
# are enough to confirm the right file is about to run, and neither is PHI.
$info = Get-Item $csv
$rows = @(Import-Csv $csv).Count
Write-Host "encounters.csv: $rows row(s), last modified $($info.LastWriteTime)" -ForegroundColor Cyan

# Run the real validator (the same one the automation uses, so a pass here means the
# batch will actually run). Its error messages name the row number and the offending
# controlled value — "Row 4: coaching_type 'Safety' is not valid" — and never an
# employee name or a description, so this output is safe to show anyone.
$env:EMR_REDACT_CONSOLE = "1"
python -c @"
from ati_coaching_encounter import load_encounters_csv, ENCOUNTERS_CSV
import sys
encs, errors = load_encounters_csv(ENCOUNTERS_CSV)
if errors:
    print(f'INVALID - {len(errors)} problem(s):')
    for e in errors:
        print('  -', e)
    sys.exit(1)
print(f'VALID - {len(encs)} encounter(s) ready to enter.')
"@
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fix encounters.csv and re-run. Nothing was entered." -ForegroundColor Red
    exit 1
}

if ($Check) {
    Write-Host "-Check: validated only. Nothing was entered." -ForegroundColor Yellow
    exit 0
}

# Belt-and-braces: phi_redact already auto-redacts whenever stdout is not a
# terminal, but set the flag explicitly so this stays safe even if someone runs the
# script by hand in a console and pipes it somewhere later.
$env:EMR_REDACT_CONSOLE = "1"

Write-Host "Starting EMR AutoMate (console output is PHI-redacted)..." -ForegroundColor Cyan

# Straight into the encounters flow, skipping emr_automate.py's task chooser — this
# script has already decided which task is running.
python -c "import asyncio, ati_coaching_encounter; asyncio.run(ati_coaching_encounter.run())"
exit $LASTEXITCODE
