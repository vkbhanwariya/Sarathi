<#
.SYNOPSIS
Creates Sarathi's Python 3.13.15 uv environment and installs locked dependencies.

.DESCRIPTION
Dependencies are installed only from pyproject.toml and uv.lock. This script
never maintains a second package list. It runs on Windows PowerShell 5.1 and
newer PowerShell releases on Windows 11; no exact PowerShell version is required.

.EXAMPLE
.\scripts\Setup-SarathiEnvironment.ps1

.EXAMPLE
.\scripts\Setup-SarathiEnvironment.ps1 -InstallUv

.EXAMPLE
.\scripts\Setup-SarathiEnvironment.ps1 -RefreshLock -AllExtras -AllGroups
#>

[CmdletBinding()]
param(
    [Parameter()]
    [string] $ProjectRoot = '',

    [Parameter()]
    [string] $PythonVersion = '3.13.15',

    [Parameter()]
    [string] $UvVersion = '0.12.7',

    [Parameter()]
    [switch] $InstallUv,

    [Parameter()]
    [switch] $RecreateEnvironment,

    [Parameter()]
    [switch] $RefreshLock,

    [Parameter()]
    [switch] $AllExtras,

    [Parameter()]
    [switch] $AllGroups
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Resolve the script location only after param() has been evaluated.
# This is required for reliable Windows PowerShell 5.1 behavior.
$scriptRoot = $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    $scriptPath = $MyInvocation.MyCommand.Path

    if ([string]::IsNullOrWhiteSpace($scriptPath)) {
        throw 'Unable to determine the script location.'
    }

    $scriptRoot = Split-Path -Parent $scriptPath
}

# Default project root is the parent of the scripts directory.
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $scriptRoot
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    throw 'Unable to determine the Sarathi project root.'
}

if ($env:OS -ne 'Windows_NT') {
    throw 'This environment setup targets Windows 11 and must be run from PowerShell on Windows.'
}

$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot)

Write-Host ''
Write-Host '=== Sarathi V2 Environment Setup ==='
Write-Host "Script directory : $scriptRoot"
Write-Host "Project root     : $resolvedRoot"
Write-Host "Python version   : $PythonVersion"
Write-Host "uv version       : $UvVersion"
Write-Host ''

$volumeRoot = [System.IO.Path]::GetPathRoot($resolvedRoot)
$trimCharacters = [char[]]@('\', '/')

if ($resolvedRoot.TrimEnd($trimCharacters) -eq $volumeRoot.TrimEnd($trimCharacters)) {
    throw "Refusing to configure a filesystem root: $resolvedRoot"
}

if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
    throw "Project root does not exist: $resolvedRoot"
}

$pyprojectPath = Join-Path $resolvedRoot 'pyproject.toml'
if (-not (Test-Path -LiteralPath $pyprojectPath -PathType Leaf)) {
    throw 'pyproject.toml is missing. Run Initialize-SarathiArchitecture.ps1 first.'
}

function Resolve-UvExecutable {
    $existingCommand = Get-Command 'uv' -ErrorAction SilentlyContinue
    if ($null -ne $existingCommand) {
        return $existingCommand.Source
    }

    if (-not $InstallUv) {
        throw "uv is not installed. Install uv $UvVersion or rerun with -InstallUv."
    }

    $installerUri = "https://astral.sh/uv/$UvVersion/install.ps1"
    $temporaryInstaller = Join-Path ([System.IO.Path]::GetTempPath()) "sarathi-uv-$([guid]::NewGuid().ToString('N')).ps1"

    try {
        Write-Host "Downloading the official uv $UvVersion installer..."
        Invoke-WebRequest -Uri $installerUri -OutFile $temporaryInstaller -UseBasicParsing

        $powerShellExecutable = if ($PSVersionTable.PSEdition -eq 'Desktop') {
            Join-Path $PSHOME 'powershell.exe'
        }
        else {
            Join-Path $PSHOME 'pwsh.exe'
        }
        & $powerShellExecutable -NoProfile -ExecutionPolicy Bypass -File $temporaryInstaller
        if ($LASTEXITCODE -ne 0) {
            throw "uv installer failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryInstaller -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryInstaller -Force
        }
    }

    $userProfilePath = [Environment]::GetFolderPath('UserProfile')
    $installedCandidate = Join-Path $userProfilePath '.local/bin/uv.exe'
    if (Test-Path -LiteralPath $installedCandidate -PathType Leaf) {
        return $installedCandidate
    }

    $refreshedCommand = Get-Command 'uv' -ErrorAction SilentlyContinue
    if ($null -eq $refreshedCommand) {
        throw 'uv installed but is not available in this process. Restart PowerShell and rerun the script.'
    }

    return $refreshedCommand.Source
}

$uvExecutable = Resolve-UvExecutable
$reportedUvVersion = (& $uvExecutable --version).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to read the uv version.'
}

$actualUvVersion = ($reportedUvVersion -replace '^uv\s+', '').Split(' ')[0]
if ($actualUvVersion -ne $UvVersion) {
    throw "Expected uv $UvVersion but found $actualUvVersion at $uvExecutable."
}

function Invoke-Uv {
    param([Parameter(Mandatory)][string[]] $Arguments)

    Write-Host "uv $($Arguments -join ' ')"
    & $uvExecutable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code $LASTEXITCODE."
    }
}

Push-Location $resolvedRoot
try {
    $pythonVersionPath = Join-Path $resolvedRoot '.python-version'
    if (Test-Path -LiteralPath $pythonVersionPath -PathType Leaf) {
        $pinnedPython = (Get-Content -LiteralPath $pythonVersionPath -Raw).Trim()
        if ($pinnedPython -ne $PythonVersion) {
            throw ".python-version pins $pinnedPython; expected $PythonVersion."
        }
    }
    else {
        $utf8NoBomEncoding = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($pythonVersionPath, $PythonVersion, $utf8NoBomEncoding)
    }

    Invoke-Uv -Arguments @('python', 'install', $PythonVersion)

    $environmentPath = Join-Path $resolvedRoot '.venv'
    $environmentPython = Join-Path $environmentPath 'Scripts/python.exe'

    if ($RecreateEnvironment -and (Test-Path -LiteralPath $environmentPath -PathType Container)) {
        Write-Host "Removing requested environment: $environmentPath"
        Remove-Item -LiteralPath $environmentPath -Recurse -Force
    }

    if (Test-Path -LiteralPath $environmentPython -PathType Leaf) {
        $environmentVersion = (& $environmentPython -c 'import platform; print(platform.python_version())').Trim()
        if ($environmentVersion -ne $PythonVersion) {
            throw "Existing .venv uses Python $environmentVersion. Rerun with -RecreateEnvironment."
        }
        Write-Host "Reusing .venv with Python $environmentVersion."
    }
    else {
        Invoke-Uv -Arguments @('venv', $environmentPath, '--python', $PythonVersion)
    }

    $lockPath = Join-Path $resolvedRoot 'uv.lock'
    if ((Test-Path -LiteralPath $lockPath -PathType Leaf) -and (-not $RefreshLock)) {
        Invoke-Uv -Arguments @('lock', '--check')
    }
    else {
        Invoke-Uv -Arguments @('lock')
    }

    $syncArguments = New-Object 'System.Collections.Generic.List[string]'
    $syncArguments.Add('sync')
    $syncArguments.Add('--locked')

    if ($AllExtras) {
        $syncArguments.Add('--all-extras')
    }
    if ($AllGroups) {
        $syncArguments.Add('--all-groups')
    }

    Invoke-Uv -Arguments $syncArguments.ToArray()
    Invoke-Uv -Arguments @('run', '--locked', 'python', '-c', 'import platform; print(platform.python_version())')

    Write-Host "Sarathi environment ready: $environmentPath"
    Write-Host 'Run project commands through: uv run --locked <command>'
}
finally {
    Pop-Location
}
