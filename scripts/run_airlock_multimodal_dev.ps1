<#!
.SYNOPSIS
  Start the Airlock backend with all three live multimodal providers.

.DESCRIPTION
  Loads an allowlist of variables from .env into THIS PROCESS ONLY
  ($env:, never persisted), forces the live development selection
  (spark reader + meta voice + sam vision), validates the isolated
  test environment, and starts FastAPI in the foreground.

  Safety properties:
  - Never prints secret values (presence-only: set/unset).
  - Never modifies .env and never runs git (no secret rewrite/commit).
  - Rejects duplicate active .env entries and unknown quoting tricks.
  - Refuses the production database path (./data/airlock.db).
  - Refuses AIRLOCK_ENV=production.
  - Requires MODEL_API_KEY and BASETEN_API_KEY to be present and distinct.
  - Requires the exact multimodal model IDs (or unset, letting the
    validated app defaults apply).

.EXAMPLE
  .\scripts\run_airlock_multimodal_dev.ps1 -CheckOnly
  # Validate only; do not start the server.

.EXAMPLE
  .\scripts\run_airlock_multimodal_dev.ps1
  # Start uvicorn in the foreground with the live selection.
#>
[CmdletBinding()]
param(
  [string]$EnvFile = ".env",
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8000,
  [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot

# --- Constants (must match app/config.py + docs) ---
$ExpectedModels = @{
  "SPARK_MODEL"              = "muse-spark-1.3"
  "VOICE_MODEL"              = "muse-voice-transcribe-1.0"
  "SAM_MODEL"                = "sam-3.1"
  "BASETEN_SPARK_OPEN_MODEL" = "meta-models/muse-spark-open-1026"
}
$ForcedSelection = @{
  "AIRLOCK_READER_PROVIDER" = "spark"
  "AIRLOCK_VOICE_PROVIDER"  = "meta"
  "AIRLOCK_VISION_PROVIDER" = "sam"
  "AIRLOCK_FIXTURE_READER"  = "1"
}
$SecretVars = @(
  "MODEL_API_KEY", "BASETEN_API_KEY", "GLIMMER_API_KEY",
  "AIRLOCK_PIN_HASH", "AIRLOCK_SESSION_SECRET", "AIRLOCK_BANK_HASH_KEY"
)
$RequiredSecrets = @("MODEL_API_KEY", "BASETEN_API_KEY")
$RequiredIsolated = @(
  "AIRLOCK_DB_PATH", "AIRLOCK_BLOB_DIR", "AIRLOCK_PIN_HASH",
  "AIRLOCK_SESSION_SECRET", "AIRLOCK_BANK_HASH_KEY"
)
# Approved .env-sourced variables (everything else is ignored, never loaded).
$Allowlist = @(
  "MODEL_API_KEY", "META_API_BASE", "SPARK_MODEL", "VOICE_MODEL", "SAM_MODEL",
  "BASETEN_API_KEY", "BASETEN_BASE_URL", "BASETEN_SPARK_OPEN_MODEL",
  "GLIMMER_BASE_URL", "GLIMMER_MODEL", "GLIMMER_API_KEY",
  "AIRLOCK_PIN_HASH", "AIRLOCK_SESSION_SECRET", "AIRLOCK_BANK_HASH_KEY",
  "AIRLOCK_DB_PATH", "AIRLOCK_BLOB_DIR", "AIRLOCK_ENV",
  "AIRLOCK_FIXTURE_READER", "AIRLOCK_FIXTURES_DIR",
  "AIRLOCK_CUSTOM_FIXTURES_DIR", "AIRLOCK_ENABLE_EVAL_API",
  "AIRLOCK_ALLOW_INSECURE_COOKIES",
  "AIRLOCK_READER_PROVIDER", "AIRLOCK_VOICE_PROVIDER", "AIRLOCK_VISION_PROVIDER",
  "AIRLOCK_MAX_UPLOAD_BYTES", "AIRLOCK_MAX_FILES_PER_CASE",
  "AIRLOCK_MAX_PDF_PAGES", "AIRLOCK_MAX_IMAGE_PIXELS",
  "AIRLOCK_MAX_AUDIO_SECONDS", "AIRLOCK_MAX_VIDEO_SECONDS",
  "AIRLOCK_PROCESSING_TIMEOUT_S", "AIRLOCK_MAX_CONCURRENT",
  "AIRLOCK_SESSION_MINUTES", "AIRLOCK_CHALLENGE_MINUTES",
  "AIRLOCK_PROPOSAL_TTL_MINUTES", "AIRLOCK_LOGIN_MAX_ATTEMPTS",
  "AIRLOCK_LOCKOUT_MINUTES", "AIRLOCK_RATE_PER_MINUTE",
  "AIRLOCK_LOG_LEVEL", "AIRLOCK_AUDIT_RETENTION_DAYS",
  "AIRLOCK_PROVIDER_CONNECT_TIMEOUT_S", "AIRLOCK_EXTRACTION_TIMEOUT_S",
  "AIRLOCK_VOICE_TIMEOUT_S", "AIRLOCK_SAM_TIMEOUT_S",
  "AIRLOCK_PROVIDER_MAX_INFLIGHT", "AIRLOCK_PROVIDER_MAX_RETRIES",
  "AIRLOCK_SPARK_MAX_OUTPUT_TOKENS"
)

function Fail([string]$Message) {
  Write-Error $Message
  exit 1
}

function Unquote([string]$Value) {
  # Strip ONE layer of matching surrounding single/double quotes only.
  if ($Value.Length -ge 2) {
    $first = $Value[0]
    $last = $Value[$Value.Length - 1]
    if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
      return $Value.Substring(1, $Value.Length - 2)
    }
  }
  return $Value
}

# --- 1. Read and parse .env (never printed) ---
$envPath = $EnvFile
if (-not [System.IO.Path]::IsPathRooted($envPath)) {
  $envPath = Join-Path $RepoRoot $envPath
}
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
  Fail "Env file not found: $envPath. Create it from .env.example first."
}
$seen = @{}
$loaded = @{}
$ignored = 0
$lineNo = 0
foreach ($rawLine in (Get-Content -LiteralPath $envPath)) {
  $lineNo += 1
  $line = $rawLine.Trim()
  if ($line -eq "" -or $line.StartsWith("#")) { continue }
  $eq = $line.IndexOf("=")
  if ($eq -le 0) { Fail ".env line ${lineNo}: not a KEY=VALUE entry." }
  $key = $line.Substring(0, $eq).Trim()
  if ($key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    Fail ".env line ${lineNo}: invalid variable name."
  }
  if ($seen.ContainsKey($key)) {
    Fail ".env has a duplicate active entry for $key (lines $($seen[$key]) and $lineNo). Refusing to guess."
  }
  $seen[$key] = $lineNo
  if ($Allowlist -notcontains $key) { $ignored += 1; continue }
  $value = Unquote($line.Substring($eq + 1).Trim())
  if ($value -eq "") { continue }  # empty = unset (same as app config)
  $loaded[$key] = $value
}

# --- 2. Required secrets: exactly one active entry each (dupes already rejected) ---
foreach ($name in $RequiredSecrets) {
  if (-not $loaded.ContainsKey($name)) {
    Fail "$name is not set in $envPath. Live multimodal mode needs it."
  }
}
if ($loaded["MODEL_API_KEY"] -eq $loaded["BASETEN_API_KEY"]) {
  Fail "MODEL_API_KEY and BASETEN_API_KEY must differ."
}

# --- 3. Isolated test environment must already be configured ---
foreach ($name in $RequiredIsolated) {
  if (-not $loaded.ContainsKey($name)) {
    Fail "$name is not set in $envPath. Configure the isolated test environment first (see docs/operations/MULTIMODAL_DEV_STARTUP.md)."
  }
}
$prodDb = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "data/airlock.db"))
$dbSetting = $loaded["AIRLOCK_DB_PATH"]
$dbFull = $dbSetting
try {
  if (-not [System.IO.Path]::IsPathRooted($dbFull)) {
    $dbFull = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $dbFull))
  } else {
    $dbFull = [System.IO.Path]::GetFullPath($dbFull)
  }
} catch {
  Fail "AIRLOCK_DB_PATH is not a usable path."
}
if ($dbFull -eq $prodDb) {
  Fail "AIRLOCK_DB_PATH points at the production database (data/airlock.db). Point it at an isolated test database first."
}
if (($loaded.ContainsKey("AIRLOCK_ENV")) -and ($loaded["AIRLOCK_ENV"].ToLower() -eq "production")) {
  Fail "AIRLOCK_ENV=production is not allowed for the multimodal dev launcher."
}

# --- 4. Exact model IDs (absent = validated app default, anything else refused) ---
foreach ($name in $ExpectedModels.Keys) {
  if ($loaded.ContainsKey($name) -and ($loaded[$name] -ne $ExpectedModels[$name])) {
    Fail "$name is '$($loaded[$name])'; this launcher requires '$($ExpectedModels[$name])'."
  }
}

# --- 5. Load into THIS PROCESS ONLY (never persisted, never printed) ---
foreach ($name in $loaded.Keys) {
  [System.Environment]::SetEnvironmentVariable($name, $loaded[$name], "Process") | Out-Null
}
foreach ($name in $ForcedSelection.Keys) {
  [System.Environment]::SetEnvironmentVariable($name, $ForcedSelection[$name], "Process") | Out-Null
}
# Defense in depth: production is never selectable through this launcher.
[System.Environment]::SetEnvironmentVariable("AIRLOCK_ENV", "development", "Process") | Out-Null

# --- 6. Report (secrets presence-only) ---
Write-Host "Airlock multimodal dev backend"
Write-Host "  env file:            $envPath"
Write-Host "  database:            $($loaded['AIRLOCK_DB_PATH'])"
Write-Host "  blob dir:            $($loaded['AIRLOCK_BLOB_DIR'])"
Write-Host "  reader provider:     spark ($($ExpectedModels['SPARK_MODEL']))"
Write-Host "  voice provider:      meta ($($ExpectedModels['VOICE_MODEL']))"
Write-Host "  vision provider:     sam ($($ExpectedModels['SAM_MODEL']))"
Write-Host "  fixture reader flag: 1 (dev/test support only; explicit live selection wins)"
Write-Host "  MODEL_API_KEY:       set"
Write-Host "  BASETEN_API_KEY:     set (distinct)"
Write-Host "  ignored .env keys:   $ignored (not on the allowlist)"
Write-Host "READY means configured and selectable, not live-tested."

if ($CheckOnly) {
  Write-Host "CheckOnly: validation passed; server not started."
  exit 0
}

# --- 7. Start FastAPI in the foreground (logs stay visible) ---
$venvPython = Join-Path $RepoRoot ".venv/Scripts/python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
Push-Location $RepoRoot
try {
  Write-Host "Starting: $python -m uvicorn app.main:app --host $BindHost --port $Port"
  & $python -m uvicorn app.main:app --host $BindHost --port $Port
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
