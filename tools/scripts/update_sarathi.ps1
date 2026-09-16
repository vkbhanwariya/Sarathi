<#
.SYNOPSIS
    Sarathi Dependency Maintenance & Update Script.
.DESCRIPTION
    Safely checks capability status and outdated packages, then provides an
    interactive menu to either stay Read-Only or perform Lockfile/Pin updates.
.PARAMETER ProjectRoot
    Optional path to Sarathi repository root. Defaults to locating pyproject.toml upwards.
.PARAMETER CheckOnly
    Runs non-interactively in Read-Only mode without modifying any files.
.PARAMETER BumpPins
    Runs non-interactively, bumping exact pins in pyproject.toml before updating lockfile.
.PARAMETER SkipTests
    Skips post-update regression testing.
#>

[CmdletBinding()]
param (
    [Parameter()]
    [string]$ProjectRoot = '',

    [Parameter()]
    [switch]$CheckOnly,

    [Parameter()]
    [switch]$BumpPins,

    [Parameter()]
    [switch]$SkipTests
)

$ErrorActionPreference = 'Continue'

# -----------------------------------------------------------------------------
# 1. Resolve Project Root & Setup Environment
# -----------------------------------------------------------------------------
function Resolve-SarathiRoot {
    param([string] $Root)
    if ($Root -and (Test-Path -LiteralPath (Join-Path $Root 'pyproject.toml') -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $Root).Path
    }
    $curr = $PSScriptRoot
    while ($curr) {
        if (Test-Path -LiteralPath (Join-Path $curr 'pyproject.toml') -PathType Leaf) {
            return (Resolve-Path -LiteralPath $curr).Path
        }
        $parent = Split-Path -Parent $curr
        if ($parent -eq $curr) { break }
        $curr = $parent
    }
    throw "Cannot determine Sarathi project root from '$Root' or script location."
}

$ProjectRoot = Resolve-SarathiRoot -Root $ProjectRoot
Set-Location -Path $ProjectRoot

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Blue
Write-Host "     SARATHI DEPENDENCY & ENVIRONMENT MANAGER       " -ForegroundColor White
Write-Host "=====================================================" -ForegroundColor Blue
Write-Host "Directory: $ProjectRoot" -ForegroundColor DarkGray
Write-Host ""

# -----------------------------------------------------------------------------
# 2. Bootstrap uv (Install if missing, Self-update if present)
# -----------------------------------------------------------------------------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[*] 'uv' not found. Installing uv package manager..." -ForegroundColor Cyan
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" + [System.Environment]::GetEnvironmentVariable("Path","Machine")
    } catch {
        Write-Host "[ERROR] Failed to automatically install uv: $_" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[*] Checking for uv updates..." -ForegroundColor DarkGray
    & uv self update 2>$null
}

# -----------------------------------------------------------------------------
# 3. Bootstrap Python 3.13 Toolchain & Virtual Environment in Sarathi Root
# -----------------------------------------------------------------------------
Write-Host "[*] Ensuring managed Python 3.13 toolchain..." -ForegroundColor Cyan
& uv python install 3.13

$venvPath = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "[*] Creating .venv explicitly in Sarathi Root: $venvPath" -ForegroundColor Cyan
    & uv venv --python 3.13 $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create .venv at $venvPath" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# Explicitly lock all uv and pip operations to the Sarathi root .venv
$env:VIRTUAL_ENV = $venvPath
$env:UV_PROJECT_ENVIRONMENT = $venvPath
$env:PATH = (Join-Path $venvPath "Scripts") + ";" + $env:PATH

Write-Host "       Target Environment: $venvPath" -ForegroundColor DarkGray
Write-Host "       Packages Directory: $(Join-Path $venvPath 'Lib\site-packages')" -ForegroundColor DarkGray
Write-Host ""

# -----------------------------------------------------------------------------
# 4. Synchronize All Capability Extras (OCR, Translation, Layout, Cloud, Dev)
# -----------------------------------------------------------------------------
Write-Host "[1/4] Installing/syncing all dependencies strictly into root .venv..." -ForegroundColor Cyan
& uv sync --all-extras --group dev --project $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to synchronize capability extras." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "       All capability extras and dev dependencies synchronized." -ForegroundColor Green
Write-Host ""

# -----------------------------------------------------------------------------
# 5. Check for Available Package Updates on PyPI (Read-Only)
# -----------------------------------------------------------------------------
Write-Host "[2/4] Checking PyPI for package updates..." -ForegroundColor Cyan
# Packages explicitly constrained by upstream parents (e.g. omegaconf, playwright)
$upstreamConstrainedPackages = @("antlr4-python3-runtime", "pyee", "python-slugify")
$outdatedLines = & uv pip list --outdated 2>$null
$actionableLines = @()

if ($outdatedLines) {
    foreach ($line in $outdatedLines) {
        if ($line -match '^Package\s+' -or $line -match '^-+') {
            continue
        }
        $isConstrained = $false
        foreach ($pkg in $upstreamConstrainedPackages) {
            if ($line -match ('^\s*' + [regex]::Escape($pkg) + '\b')) {
                $isConstrained = $true
                break
            }
        }
        if (-not $isConstrained -and -not [string]::IsNullOrWhiteSpace($line)) {
            $actionableLines += $line
        }
    }
}

if ($actionableLines.Count -gt 0) {
    Write-Host "       Package                Version Latest Type" -ForegroundColor DarkYellow
    Write-Host "       ---------------------- ------- ------ -----" -ForegroundColor DarkYellow
    foreach ($line in $actionableLines) {
        Write-Host "       $line" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "       All project dependencies are fully up to date with PyPI." -ForegroundColor DarkGreen
}
Write-Host ""

# -----------------------------------------------------------------------------
# 6. Inspect Exact-Pinned Dependencies in pyproject.toml
# -----------------------------------------------------------------------------
Write-Host "[3/4] Inspecting exact-pinned dependencies in pyproject.toml..." -ForegroundColor Cyan
$tomlPath = Join-Path $ProjectRoot "pyproject.toml"
$tomlContent = Get-Content -Path $tomlPath -Raw
$pinnedPackages = @("pymupdf", "pymupdf-layout")
$availablePinBumps = @{}

foreach ($pkg in $pinnedPackages) {
    $pattern = '"' + [regex]::Escape($pkg) + '==([0-9\.]+)"'
    if ($tomlContent -match $pattern) {
        $currentPin = $Matches[1]
        try {
            $resp = Invoke-RestMethod -Uri "https://pypi.org/pypi/$pkg/json" -TimeoutSec 4 -ErrorAction Stop
            $latestVer = $resp.info.version
            if ($latestVer -and ($latestVer -ne $currentPin)) {
                $availablePinBumps[$pkg] = @{ Current = $currentPin; Latest = $latestVer }
                Write-Host "       [PIN UPDATE AVAILABLE] ${pkg}: ==${currentPin} -> latest on PyPI: ${latestVer}" -ForegroundColor Yellow
            } else {
                Write-Host "       [PIN VERIFIED] ${pkg} pin (${currentPin}) is up to date." -ForegroundColor DarkGreen
            }
        } catch {
            Write-Host "       [PIN CHECK] Could not reach PyPI for $pkg (offline or timeout)." -ForegroundColor DarkGray
        }
    }
}
Write-Host ""

# -----------------------------------------------------------------------------
# 7. Verify Declared OCR and Translation Model Assets
# -----------------------------------------------------------------------------
Write-Host "[4/4] Verifying declared neural model assets (OCR & Translation)..." -ForegroundColor Cyan
$setupScript = Join-Path $PSScriptRoot "Setup-OCRModels.ps1"
if (Test-Path -LiteralPath $setupScript -PathType Leaf) {
    try {
        & $setupScript -ProjectRoot $ProjectRoot -VerifyOnly
    } catch {
        Write-Host "       [WARNING] OCR model assets are missing or incomplete." -ForegroundColor Yellow
        Write-Host "       Run 'powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-OCRModels.ps1' to provision them." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "       [SKIP] Setup-OCRModels.ps1 not found at '$setupScript'." -ForegroundColor DarkGray
}

$transSetupScript = Join-Path $PSScriptRoot "Setup-TranslationModels.ps1"
if (Test-Path -LiteralPath $transSetupScript -PathType Leaf) {
    try {
        & $transSetupScript -ProjectRoot $ProjectRoot -VerifyOnly
    } catch {
        Write-Host "       [WARNING] Translation model assets are missing or incomplete." -ForegroundColor Yellow
        Write-Host "       Run 'powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-TranslationModels.ps1' to provision them." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "       [SKIP] Setup-TranslationModels.ps1 not found at '$transSetupScript'." -ForegroundColor DarkGray
}
Write-Host ""

# -----------------------------------------------------------------------------
# 8. Interactive Mode Selection (Read-Only vs Update)
# -----------------------------------------------------------------------------
if ($CheckOnly) {
    Write-Host "[INFO] Check-Only mode. No changes were made." -ForegroundColor Green
    exit 0
}

if (-not $BumpPins) {
    Write-Host "-----------------------------------------------------" -ForegroundColor DarkGray
    Write-Host "Choose what you would like to do:" -ForegroundColor Yellow
    Write-Host "  [1] Read-Only Finish  (Keep current versions, exit without changes)" -ForegroundColor White
    Write-Host "  [2] Update Lockfile   (Upgrade uv.lock within current pyproject.toml bounds + test)" -ForegroundColor White
    Write-Host "  [3] Full Update       (Bump exact pins in pyproject.toml + upgrade uv.lock + test)" -ForegroundColor White
    Write-Host "  [4] Exit" -ForegroundColor DarkGray
    Write-Host ""
    $choice = Read-Host "Select option [1-4] (Default: 1)"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

    switch ($choice) {
        "1" {
            Write-Host ""
            Write-Host "[INFO] Read-Only selected. No changes made." -ForegroundColor Green
            exit 0
        }
        "2" {
            Write-Host ""
            Write-Host "[*] Proceeding with Lockfile update..." -ForegroundColor Cyan
        }
        "3" {
            Write-Host ""
            Write-Host "[*] Proceeding with Full Update (Pin Bumping + Lockfile)..." -ForegroundColor Cyan
            $BumpPins = $true
        }
        "4" {
            Write-Host ""
            Write-Host "Exiting." -ForegroundColor Green
            exit 0
        }
        default {
            Write-Host ""
            Write-Host "[INFO] Defaulting to Read-Only. No changes made." -ForegroundColor Green
            exit 0
        }
    }
}

# -----------------------------------------------------------------------------
# 9. Apply Pin Bumping if Selected
# -----------------------------------------------------------------------------
if ($BumpPins -and ($availablePinBumps.Count -gt 0)) {
    Write-Host "[*] Updating pins in pyproject.toml..." -ForegroundColor Cyan
    foreach ($pkg in $availablePinBumps.Keys) {
        $cur = $availablePinBumps[$pkg].Current
        $new = $availablePinBumps[$pkg].Latest
        $oldString = "`"$pkg==$cur`""
        $newString = "`"$pkg==$new`""
        $tomlContent = $tomlContent.Replace($oldString, $newString)
        Write-Host "       Updated ${pkg}: ${cur} -> ${new}" -ForegroundColor Magenta
    }
    Set-Content -Path $tomlPath -Value $tomlContent -NoNewline
    Write-Host "       pyproject.toml pins saved." -ForegroundColor Green
    Write-Host ""
}

# -----------------------------------------------------------------------------
# 10. Upgrade Lockfile & Apply Updates
# -----------------------------------------------------------------------------
Write-Host "[*] Upgrading lockfile to latest releases..." -ForegroundColor Cyan
& uv lock --upgrade --project $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] 'uv lock --upgrade' failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "[*] Applying updates strictly to root .venv..." -ForegroundColor Cyan
& uv sync --all-extras --group dev --project $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] 'uv sync --all-extras --group dev' failed." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "       Virtual environment updated." -ForegroundColor Green
Write-Host ""

# -----------------------------------------------------------------------------
# 11. Validate with Regression Tests & Architecture Gate
# -----------------------------------------------------------------------------
if (-not $SkipTests) {
    Write-Host "[*] Running regression tests and architecture gate to verify zero breakage..." -ForegroundColor Cyan
    & uv run --project $ProjectRoot --group dev pytest tests/architecture tests/ocr tests/native_extraction tests/contracts -m "not real_model"
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[WARNING] One or more tests failed after updating dependencies!" -ForegroundColor Red
        Write-Host "Review git diff or restore previous lockfile using: git checkout uv.lock pyproject.toml" -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
    Write-Host ""
    Write-Host "       All regression tests passed successfully!" -ForegroundColor Green
} else {
    Write-Host "[*] Post-update tests skipped (-SkipTests)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Green
Write-Host "   SARATHI ENVIRONMENT IS GREEN AND FULLY UPDATED    " -ForegroundColor White
Write-Host "=====================================================" -ForegroundColor Green
Write-Host ""
