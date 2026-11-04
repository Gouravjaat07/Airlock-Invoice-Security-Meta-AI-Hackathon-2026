<# Airlock offline verification: every gate, one command.

Runs fully offline: no provider calls, no keys, no network, no database
touched (tests + evals use temp DBs). Exits nonzero on the first failed
gate. Reads take minutes (backend suite ~2 min).

Usage: powershell -File scripts\verify_repo.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$failures = @()
function Gate($name, [scriptblock]$cmd) {
    # Native nonzero exits do NOT throw under Stop preference, so check
    # $LASTEXITCODE explicitly; otherwise failures report as passes.
    Write-Host "`n=== GATE: $name ==="
    $global:LASTEXITCODE = 0
    try {
        & $cmd
        if ($global:LASTEXITCODE -ne 0) { throw "exit code $($global:LASTEXITCODE)" }
        Write-Host "PASS: $name"
    }
    catch { Write-Host "FAIL: $name -- $($_.Exception.Message)"; $script:failures += $name }
    finally { $global:LASTEXITCODE = 0 }
}
function Need($name, [scriptblock]$cmd) {
    Write-Host "`n--- check: $name ---"
    $global:LASTEXITCODE = 0
    & $cmd
    if ($global:LASTEXITCODE -ne 0) { throw "$name failed (exit $($global:LASTEXITCODE))" }
}

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Need "python >= 3.11" { & $py -c "import sys; assert sys.version_info >= (3, 11), sys.version; print(sys.version.split()[0])" }
Need "node available" { node --version }
Need "ruff available" { & $py -m ruff --version }

Gate "backend tests (offline)" { & $py -m pytest -q -p no:cacheprovider --basetemp=pytest-of-Dell }
Gate "ruff (app+scripts+tests)" { & $py -m ruff check app scripts tests }
Gate "fixture drift check" { & $py scripts/make_fixtures.py --check }
Gate "secret hygiene" { & $py scripts/check_secret_hygiene.py }
Gate "phase3 verdict eval" { & $py scripts/phase3_eval.py --output-dir results/phase3/eval }
Gate "phase5 eval (offline parts)" { & $py scripts/phase5_eval.py }
Gate "benchmark (5 cases)" { & $py scripts/phase5_benchmark.py --cases 5 }

Push-Location (Join-Path $root "web")
try {
    Gate "frontend typecheck" { npm run typecheck }
    Gate "frontend lint" { npm run lint }
    Gate "frontend tests" {
        $tmp = Join-Path (Get-Location) ".vitest-tmp"
        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        $env:TEMP = $tmp; $env:TMP = $tmp; $env:TMPDIR = $tmp
        try { npm test } finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
    }
    Gate "frontend build" { npm run build }
} finally { Pop-Location }

Remove-Item -Recurse -Force (Join-Path $root "pytest-of-Dell") -ErrorAction SilentlyContinue

Write-Host "`n===== SUMMARY ====="
if ($failures.Count -eq 0) { Write-Host "ALL GATES PASSED"; exit 0 }
Write-Host "FAILED GATES: $($failures -join ', ')"
exit 1
