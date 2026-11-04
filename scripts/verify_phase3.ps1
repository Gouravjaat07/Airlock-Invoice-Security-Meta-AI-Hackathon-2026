# Airlock Phase 3.1 offline verification runner (owner-operated).
#
# Runs the full offline verification battery from the repository root
# using the project virtualenv, captures one exit code per check, and
# prints a sanitized machine-readable summary. It never prints
# environment variables, `.env` contents, or secrets; it makes no live
# provider calls (smoke runs preflight-only); it does not touch the
# user's database or rewrite Phase 1/Phase 2 reports.
#
# Usage (standard Windows PowerShell, from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts\verify_phase3.ps1
#
# Paste the trailing JSON summary back for the verification record.

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$id, [string]$name, [string]$status,
                    [int]$code, [string]$detail) {
    $results.Add([pscustomobject]@{
        check_id  = $id
        name      = $name
        status    = $status   # PASS | FAIL | BLOCKED | SKIPPED | NOT_TESTED
        exit_code = $code
        detail    = $detail   # command run or reason; never secrets
    })
}

function Invoke-Check([string]$id, [string]$name, [string[]]$argv,
                      [string[]]$needs) {
    foreach ($need in $needs) {
        if (-not (Test-Path (Join-Path $root $need))) {
            Add-Result $id $name "SKIPPED" 127 "missing: $need"
            return
        }
    }
    Write-Host ""
    Write-Host "=== [$id] $name ===" -ForegroundColor Cyan
    Write-Host ("$ " + ($argv -join " "))
    & $argv[0] $argv[1..($argv.Length - 1)]
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    if ($code -eq 0) {
        Add-Result $id $name "PASS" $code ($argv -join " ")
        Write-Host "[$id] PASS" -ForegroundColor Green
    } else {
        Add-Result $id $name "FAIL" $code ($argv -join " ")
        Write-Host "[$id] FAIL (exit $code)" -ForegroundColor Red
    }
}

# V-00: interpreter gate. Everything else is BLOCKED without it.
if (-not (Test-Path $python)) {
    Add-Result "V-00" "project virtualenv" "BLOCKED" 127 `
        "missing: .venv\Scripts\python.exe (create the venv first)"
} else {
    Add-Result "V-00" "project virtualenv" "PASS" 0 `
        "using .venv\Scripts\python.exe"
    & $python --version

    # V-01: full test suite (offline; live tests self-skip).
    Invoke-Check "V-01" "full pytest suite" `
        @($python, "-m", "pytest", "-p", "no:cacheprovider") @("tests")

    # V-02: lint gate.
    Invoke-Check "V-02" "ruff" `
        @($python, "-m", "ruff", "check", "scripts", "tests", "app") @()

    # V-03: configuration validation (no secrets printed).
    Invoke-Check "V-03" "config validation" `
        @($python, "scripts/validate_config.py") @("scripts/validate_config.py")

    # V-04: secret hygiene.
    Invoke-Check "V-04" "secret hygiene" `
        @($python, "scripts/check_secret_hygiene.py") `
        @("scripts/check_secret_hygiene.py")

    # V-05: Phase 2 strict regression gate.
    Invoke-Check "V-05" "phase 2 strict gate" `
        @($python, "scripts/phase2_check.py", "--strict") `
        @("scripts/phase2_check.py")

    # V-06: offline evaluation (synthetic fixtures only).
    Invoke-Check "V-06" "phase 3 offline eval" `
        @($python, "scripts/phase3_eval.py") @("scripts/phase3_eval.py")

    # V-07: Phase 3 strict gate (suites + docs + preflight smoke).
    Invoke-Check "V-07" "phase 3 strict gate" `
        @($python, "scripts/phase3_check.py", "--strict") `
        @("scripts/phase3_check.py")

    # V-08: live smoke defaults to preflight-only (proves no live call).
    Invoke-Check "V-08" "smoke preflight default" `
        @($python, "scripts/smoke_phase3.py") @("scripts/smoke_phase3.py")
}

$summary = [pscustomobject]@{
    tool       = "verify_phase3.ps1"
    timestamp  = (Get-Date).ToUniversalTime().ToString("o")
    root       = $root
    live_calls = "none (preflight-only by default)"
    checks     = $results
}
$pass = @($results | Where-Object { $_.status -eq "PASS" }).Count
$fail = @($results | Where-Object { $_.status -eq "FAIL" }).Count
$other = $results.Count - $pass - $fail

Write-Host ""
Write-Host "=== Summary: $pass PASS, $fail FAIL, $other BLOCKED/SKIPPED ==="
$summary | ConvertTo-Json -Depth 6 -Compress:$false

if ($fail -gt 0) { exit 1 }
exit 0
