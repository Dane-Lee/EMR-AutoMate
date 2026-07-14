<#
    Paste-Encounters.ps1 — land M365 Copilot's reply into encounters.csv
    =====================================================================
    Copy Copilot's ENTIRE reply (all three sections), then run this. It pulls the
    pieces apart for you so you never hand-edit a CSV:

        the ```csv block      -> encounters.csv        (then validates it)
        ASSESSMENTS section   -> assessments_todo.md   (appended, dated)
        NEW DESCRIPTIONS      -> new_descriptions_todo.md (appended, dated)

    USAGE
        .\Paste-Encounters.ps1           # read the clipboard
        .\Paste-Encounters.ps1 -Show     # also print the CSV to the screen

    THIS SCRIPT TOUCHES PHI, AND THAT IS FINE — it runs on YOUR machine and talks to
    nothing. By default it prints only counts and the validator's output (which names
    row numbers and bad dropdown values, never people), so its output stays safe to
    show Claude. -Show prints the actual rows; only use it when nobody's watching.

    Your previous encounters.csv is backed up to encounters.bak.csv, never destroyed.
#>

[CmdletBinding()]
param(
    # Print the CSV contents to the screen (PHI!). Off by default.
    [switch]$Show,

    # Add these rows to the existing encounters.csv instead of replacing it. Use when
    # Copilot hands back a long batch in chunks — dictate 25, paste, dictate 25 more,
    # paste with -Append.
    [switch]$Append
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$raw = Get-Clipboard -Raw
if ([string]::IsNullOrWhiteSpace($raw)) {
    Write-Host "Clipboard is empty. Copy Copilot's reply first." -ForegroundColor Red
    exit 1
}

$header = "employee,date,encounter_type,department,division,category,shift,coaching_type,details,description,what_prompted"

# ── 1. the CSV ────────────────────────────────────────────────────────────────
# Collect EVERY fenced csv block, not just the first. A long batch often comes back
# split across several blocks ("...continued"), and taking only the first silently
# dropped the rest — which is exactly how an 80-encounter batch arrived as 25.
$dataRows = @()
$blocks = [regex]::Matches($raw, '(?ms)```(?:csv)?\s*\r?\n\s*(employee,date,encounter_type.*?)\r?\n\s*```')
foreach ($b in $blocks) {
    foreach ($line in ($b.Groups[1].Value.Trim() -split "\r?\n")) {
        if ($line -match '^\s*employee,date,encounter_type') { continue }  # repeated header
        if ($line.Trim()) { $dataRows += $line }
    }
}

# Fall back to "from the header line onward" if Copilot forgot the fence entirely.
if ($dataRows.Count -eq 0) {
    $idx = $raw.IndexOf($header, [StringComparison]::OrdinalIgnoreCase)
    if ($idx -ge 0) {
        foreach ($line in ($raw.Substring($idx) -split "\r?\n")) {
            if ($line -match '^\s*```') { break }
            if ($line -match '^\s*employee,date,encounter_type') { continue }
            if (-not $line.Trim()) { if ($dataRows.Count) { break } else { continue } }
            $dataRows += $line
        }
    }
}

if ($dataRows.Count -eq 0) {
    Write-Host "No CSV found in the clipboard." -ForegroundColor Red
    Write-Host "Expected a fenced ``````csv block starting with:" -ForegroundColor Yellow
    Write-Host "  $header"
    exit 1
}

if ($blocks.Count -gt 1) {
    Write-Host "Found $($blocks.Count) CSV blocks in the reply - merged them." -ForegroundColor DarkGray
}

$csv = ($dataRows -join "`n")

# Back up whatever was there before — never destroy a batch that might not be entered.
# This is not paranoia: it is what saved an 80-row batch when a Copilot rerun came back
# truncated to 25 and overwrote it.
$existingRows = @()
if (Test-Path .\encounters.csv) {
    Copy-Item .\encounters.csv .\encounters.bak.csv -Force
    Write-Host "Backed up previous encounters.csv -> encounters.bak.csv" -ForegroundColor DarkGray
    if ($Append) {
        $existingRows = @(Get-Content .\encounters.csv | Where-Object {
            $_.Trim() -and $_ -notmatch '^\s*employee,date,encounter_type'
        })
    }
}

$allRows = $existingRows + $dataRows

# UTF8 without BOM: Python's csv reader chokes on a BOM in the first column name.
# NB: @($header) + $allRows, not ($header, $allRows) — the latter nests the array and
# -join stringifies it into one space-separated line.
[System.IO.File]::WriteAllText(
    (Join-Path $PSScriptRoot 'encounters.csv'),
    ((@($header) + $allRows) -join "`n") + "`n",
    (New-Object System.Text.UTF8Encoding $false))

if ($Append) {
    Write-Host ("Appended {0} row(s) to {1} existing -> encounters.csv now has {2}" -f `
        $dataRows.Count, $existingRows.Count, $allRows.Count) -ForegroundColor Cyan
} else {
    Write-Host "Wrote encounters.csv: $($dataRows.Count) row(s)" -ForegroundColor Cyan
}

# A batch that suddenly shrinks is the signature of a truncated Copilot reply. Say so
# loudly rather than letting it pass as a clean run.
$prev = @($existingRows).Count
if (-not $Append -and (Test-Path .\encounters.bak.csv)) {
    $prev = @(Import-Csv .\encounters.bak.csv).Count
    if ($prev -gt $dataRows.Count) {
        Write-Host ""
        Write-Host ("WARNING: the previous batch had {0} rows, this one has only {1}." -f `
            $prev, $dataRows.Count) -ForegroundColor Red
        Write-Host "Copilot may have truncated its reply. If you expected more, ask it to" -ForegroundColor Red
        Write-Host "re-output the REST in a second block, then re-run with -Append." -ForegroundColor Red
        Write-Host "The previous batch is intact in encounters.bak.csv." -ForegroundColor Red
        Write-Host ""
    }
}

if ($Show) { Write-Host ""; Write-Host $csv; Write-Host "" }

# ── 2. assessments + new descriptions ────────────────────────────────────────
function Save-Section {
    param([string]$Pattern, [string]$File, [string]$Label)

    $m = [regex]::Match($raw, $Pattern)
    if (-not $m.Success) { return 0 }

    $body = $m.Groups[1].Value.Trim()
    if (-not $body -or $body -match '^\s*none\s*$') { return 0 }

    $bullets = @($body -split "\r?\n" | Where-Object { $_ -match '^\s*[-*]' })
    if ($bullets.Count -eq 0) { return 0 }

    $stamp = Get-Date -Format 'MM/dd/yyyy'
    $entry = "`n## $stamp`n`n" + ($bullets -join "`n") + "`n"
    Add-Content -Path $File -Value $entry -Encoding utf8
    Write-Host "$Label -> $File ($($bullets.Count))" -ForegroundColor Yellow
    return $bullets.Count
}

$assess = Save-Section '(?ms)ASSESSMENTS[^\n]*\n(.*?)(?=\n#+\s|\nNEW DESCRIPTIONS|\z)' `
                       'assessments_todo.md' 'Assessments for manual entry'
$newdesc = Save-Section '(?ms)NEW DESCRIPTIONS[^\n]*\n(.*?)(?=\n#+\s|\z)' `
                        'new_descriptions_todo.md' 'New descriptions to add to the workbook'

# ── 3. validate ──────────────────────────────────────────────────────────────
Write-Host ""
& (Join-Path $PSScriptRoot 'Run-Encounters.ps1') -Check
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nAsk Copilot to fix the rows named above, then re-copy and re-run this." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Ready. Run .\Run-Encounters.ps1 to enter the batch as drafts." -ForegroundColor Green
if ($assess)  { Write-Host "  $assess assessment(s) still need manual entry - see assessments_todo.md" -ForegroundColor Yellow }
if ($newdesc) { Write-Host "  $newdesc new description(s) to fold into the workbook - see new_descriptions_todo.md" -ForegroundColor Yellow }
