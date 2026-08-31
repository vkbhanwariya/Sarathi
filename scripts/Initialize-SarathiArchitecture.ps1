<#
.SYNOPSIS
Creates the canonical Sarathi V2 project scaffold without overwriting existing files.

.DESCRIPTION
Runs on Windows PowerShell 5.1 and newer PowerShell releases on Windows 11.
No exact PowerShell version is required.

.EXAMPLE
.\scripts\Initialize-SarathiArchitecture.ps1

.EXAMPLE
.\scripts\Initialize-SarathiArchitecture.ps1 -ProjectRoot C:\Code\Sarathi

.EXAMPLE
.\scripts\Initialize-SarathiArchitecture.ps1 -ProjectRoot C:\Code\Sarathi -WhatIf
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter()]
    [string] $ProjectRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Resolve the project root after the param block so Windows PowerShell 5.1
# does not evaluate $PSScriptRoot too early.
$scriptRoot = $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    $scriptPath = $MyInvocation.MyCommand.Path

    if ([string]::IsNullOrWhiteSpace($scriptPath)) {
        throw 'Unable to determine the script location.'
    }

    $scriptRoot = Split-Path -Parent $scriptPath
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $scriptRoot
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    throw 'Unable to determine the Sarathi project root.'
}

if ($env:OS -ne 'Windows_NT') {
    throw 'This scaffold targets Windows 11 and must be run from PowerShell on Windows.'
}

$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$volumeRoot = [System.IO.Path]::GetPathRoot($resolvedRoot)
$trimCharacters = [char[]]@('\', '/')

if ($resolvedRoot.TrimEnd($trimCharacters) -eq $volumeRoot.TrimEnd($trimCharacters)) {
    throw "Refusing to scaffold a filesystem root: $resolvedRoot"
}

$createdDirectories = 0
$createdFiles = 0
$preservedItems = 0
$commandContext = $PSCmdlet
$utf8NoBomEncoding = New-Object System.Text.UTF8Encoding($false)

function Add-DirectoryIfMissing {
    param([Parameter(Mandatory)][string] $RelativePath)

    $targetPath = Join-Path $resolvedRoot $RelativePath
    if (Test-Path -LiteralPath $targetPath) {
        if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
            throw "Expected a directory but found a file: $targetPath"
        }
        $script:preservedItems++
        return
    }

    if ($commandContext.ShouldProcess($targetPath, 'Create directory')) {
        $null = New-Item -ItemType Directory -Path $targetPath
        $script:createdDirectories++
    }
}

function Add-FileIfMissing {
    param(
        [Parameter(Mandatory)][string] $RelativePath,
        [Parameter(Mandatory)][AllowEmptyString()][string] $Content
    )

    $targetPath = Join-Path $resolvedRoot $RelativePath
    if (Test-Path -LiteralPath $targetPath) {
        if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
            throw "Expected a file but found a directory: $targetPath"
        }
        $script:preservedItems++
        return
    }

    $parentPath = Split-Path -Parent $targetPath
    if ((-not $WhatIfPreference) -and (-not (Test-Path -LiteralPath $parentPath -PathType Container))) {
        throw "Parent directory was not created: $parentPath"
    }

    if ($commandContext.ShouldProcess($targetPath, 'Create file')) {
        [System.IO.File]::WriteAllText($targetPath, $Content, $utf8NoBomEncoding)
        $script:createdFiles++
    }
}

if (Test-Path -LiteralPath $resolvedRoot) {
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "Project root is not a directory: $resolvedRoot"
    }
    $preservedItems++
}
elseif ($commandContext.ShouldProcess($resolvedRoot, 'Create project root')) {
    $null = New-Item -ItemType Directory -Path $resolvedRoot
    $createdDirectories++
}

$directories = @(
    'scripts',
    'src/sarathi',
    'src/sarathi/agni',
    'src/sarathi/sankalpa',
    'src/sarathi/nabhi',
    'src/sarathi/yantra',
    'src/sarathi/darpana',
    'src/sarathi/darpana/exporters',
    'src/sarathi/mukha',
    'src/sarathi/smriti',
    'src/sarathi/kavacha',
    'src/sarathi/sutra',
    'src/sarathi/dosh',
    'src/sarathi/shakti',
    'src/sarathi/shakti/darshana',
    'src/sarathi/shakti/native_extraction',
    'src/sarathi/shakti/ocr',
    'src/sarathi/shakti/font_conversion',
    'src/sarathi/shakti/translation',
    'src/sarathi/shakti/bank_statements',
    'data/banks',
    'data/fonts',
    'data/ocr',
    'data/font_conversion',
    'data/translation',
    'data/bank_statements',
    'config',
    'Input',
    'Output',
    'Runtime/Work',
    'Runtime/Quarantine',
    'Runtime/Telemetry',
    'Runtime/Cache',
    'tests/artifacts',
    'tests/contracts',
    'tests/errors',
    'tests/configuration',
    'tests/native_extraction',
    'tests/ocr',
    'tests/font_conversion',
    'tests/translation',
    'tests/bank_statements',
    'Vedas'
)

foreach ($directory in $directories) {
    Add-DirectoryIfMissing $directory
}

$packageDirectories = @(
    'src/sarathi',
    'src/sarathi/agni',
    'src/sarathi/sankalpa',
    'src/sarathi/nabhi',
    'src/sarathi/yantra',
    'src/sarathi/darpana',
    'src/sarathi/darpana/exporters',
    'src/sarathi/mukha',
    'src/sarathi/smriti',
    'src/sarathi/kavacha',
    'src/sarathi/sutra',
    'src/sarathi/dosh',
    'src/sarathi/shakti',
    'src/sarathi/shakti/darshana',
    'src/sarathi/shakti/native_extraction',
    'src/sarathi/shakti/ocr',
    'src/sarathi/shakti/font_conversion',
    'src/sarathi/shakti/translation',
    'src/sarathi/shakti/bank_statements'
)

foreach ($packageDirectory in $packageDirectories) {
    Add-FileIfMissing (Join-Path $packageDirectory '__init__.py') ''
}

$pyproject = @'
[project]
name = "sarathi"
version = "2.0.0"
description = "Local, plugin-first document intelligence system"
requires-python = "==3.13.15"
dependencies = []

[build-system]
requires = ["uv_build>=0.12.7,<0.13"]
build-backend = "uv_build"
'@

$gitignore = @'
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
Input/
Output/
Runtime/
'@

Add-FileIfMissing '.python-version' "3.13.15"
Add-FileIfMissing 'pyproject.toml' $pyproject
Add-FileIfMissing '.gitignore' $gitignore

Write-Host "Sarathi V2 scaffold complete: $resolvedRoot"
Write-Host "Created directories: $createdDirectories"
Write-Host "Created files:       $createdFiles"
Write-Host "Preserved existing:  $preservedItems"

if (-not (Test-Path -LiteralPath (Join-Path $resolvedRoot 'README.md'))) {
    Write-Warning 'README.md is absent. Place the canonical Sarathi V2 README at the project root.'
}

Write-Host 'No capability implementation files or empty Anubhava data files were created.'
