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
    [switch]$Show
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
# Prefer a fenced ```csv block; fall back to "from the header line to the first
# blank line" if Copilot forgot the fence.
$csv = $null
$fenced = [regex]::Match($raw, '(?ms)```(?:csv)?\s*\r?\n\s*(employee,date,encounter_type.*?)\r?\n\s*```')
if ($fenced.Success) {
    $csv = $fenced.Groups[1].Value.Trim()
} else {
    $idx = $raw.IndexOf($header, [StringComparison]::OrdinalIgnoreCase)
    if ($idx -ge 0) {
        $tail = $raw.Substring($idx)
        $lines = @()
        foreach ($line in ($tail -split "\r?\n")) {
            if ([string]::IsNullOrWhiteSpace($line) -and $lines.Count -gt 1) { break }
            if ($line -match '^\s*```') { break }
            $lines += $line
        }
        $csv = ($lines -join "`n").Trim()
    }
}

if (-not $csv) {
    Write-Host "No CSV found in the clipboard." -ForegroundColor Red
    Write-Host "Expected a fenced ``````csv block starting with:" -ForegroundColor Yellow
    Write-Host "  $header"
    exit 1
}

# Back up whatever was there before — never destroy a batch that might not be entered.
if (Test-Path .\encounters.csv) {
    Copy-Item .\encounters.csv .\encounters.bak.csv -Force
    Write-Host "Backed up previous encounters.csv -> encounters.bak.csv" -ForegroundColor DarkGray
}

# UTF8 without BOM: Python's csv reader chokes on a BOM in the first column name.
[System.IO.File]::WriteAllText(
    (Join-Path $PSScriptRoot 'encounters.csv'),
    ($csv + "`n"),
    (New-Object System.Text.UTF8Encoding $false))

$rowCount = (@($csv -split "\r?\n") | Where-Object { $_.Trim() }).Count - 1
Write-Host "Wrote encounters.csv: $rowCount row(s)" -ForegroundColor Cyan

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
