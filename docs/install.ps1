# mimirlink installer — Windows (PowerShell 5.1+)
# Usage: irm https://comcy.github.io/kvasir/install.ps1 | iex

$ErrorActionPreference = "Stop"
$REPO_URL    = "https://github.com/comcy/kvasir.git"
$MIN_MINOR   = 11

function Write-Step { param($m) Write-Host "  → $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "  ✓ $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "  ! $m" -ForegroundColor Yellow }
function Fail       { param($m) Write-Host "  ✗ $m" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  mimirlink installer" -ForegroundColor White
Write-Host "  -------------------"
Write-Host ""

# ── Python 3.11+ ──────────────────────────────────────────────────────────────

Write-Step "Checking Python..."
$pyBin = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver -match "^(\d+)\.(\d+)$") {
            if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge $MIN_MINOR) {
                $pyBin = $candidate; Write-OK "Python $ver ($candidate)"; break
            }
        }
    } catch {}
}
if (-not $pyBin) {
    Fail "Python 3.${MIN_MINOR}+ not found. Install from https://python.org/downloads (check 'Add to PATH')"
}

# ── uv ────────────────────────────────────────────────────────────────────────

Write-Step "Checking uv..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Step "Installing uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    # Refresh PATH for this session
    $uvBin = "$env:LOCALAPPDATA\uv\bin"
    if (Test-Path $uvBin) { $env:PATH = "$uvBin;$env:PATH" }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-OK "uv ready"
} else {
    Write-Warn "uv installed but not in PATH. Restart PowerShell, then run:"
    Write-Host "  uv tool install `"git+$REPO_URL`""
    exit 0
}

# ── mimirlink ─────────────────────────────────────────────────────────────────

Write-Step "Installing mimirlink (clones and builds from GitHub)..."
uv tool install "git+$REPO_URL"
Write-OK "mimirlink installed"

# ── PATH ─────────────────────────────────────────────────────────────────────

try { uv tool update-shell 2>$null } catch {}

if (Get-Command mimirlink -ErrorAction SilentlyContinue) {
    Write-OK "mimirlink is in PATH"
} else {
    Write-Warn "mimirlink not in PATH yet. Add uv's tool directory:"
    Write-Host '  $env:PATH += ";$env:LOCALAPPDATA\uv\bin"'
    Write-Host "  Or add it permanently via: uv tool update-shell"
}

Write-Host ""
Write-Host "  Done! Quick start:" -ForegroundColor Green
Write-Host ""
Write-Host "    mimirlink workspace create private   # create your first workspace"
Write-Host "    mimirlink tui                        # launch the TUI"
Write-Host ""
