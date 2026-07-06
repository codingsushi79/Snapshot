#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Repo = if ($env:SNAPSHOT_REPO) { $env:SNAPSHOT_REPO } else { "https://github.com/codingsushi79/Snapshot.git" }
$Ref = if ($env:SNAPSHOT_REF) { $env:SNAPSHOT_REF } else { "main" }
$InstallSpec = "git+$Repo@$Ref"

function Write-Info($msg) { Write-Host "→ $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "! $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "✗ $msg" -ForegroundColor Red }

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            $ok = & $cmd -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $cmd }
        }
    }
    return $null
}

function Ensure-Pip($py) {
    & $py -m pip --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Info "Bootstrapping pip…"
        & $py -m ensurepip --upgrade 2>$null | Out-Null
    }
    & $py -m pip --version 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

Write-Info "Installing snapshot from $InstallSpec"

$py = Find-Python
if (-not $py) {
    Write-Err "Python 3.10+ is required."
    Write-Err "Install from https://www.python.org/downloads/ and re-run this script."
    exit 1
}

if (-not (Ensure-Pip $py)) {
    Write-Err "pip is required but could not be installed."
    exit 1
}

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    Write-Info "Installing snapshot with pipx…"
    pipx install --force $InstallSpec
} else {
    Write-Info "Installing snapshot with pip…"
    & $py -m pip install --user --upgrade $InstallSpec
}

$localBin = Join-Path $env:USERPROFILE ".local\\bin"
$scriptsDir = Join-Path $env:APPDATA "Python\\Python312\\Scripts"
$paths = @($localBin, $scriptsDir) | Where-Object { Test-Path $_ }
if ($paths.Count -gt 0) {
    $env:PATH = ($paths -join ";") + ";" + $env:PATH
}

if (Get-Command snapshot -ErrorAction SilentlyContinue) {
    Write-Info "Installed snapshot."
    Write-Info "Run: snapshot https://example.com ./mirror"
} else {
    Write-Warn "snapshot installed, but not on PATH."
    Write-Warn "Restart your terminal or add Python Scripts to PATH."
}
