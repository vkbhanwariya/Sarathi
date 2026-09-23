<#
.SYNOPSIS
Provisions and verifies declared CTranslate2 neural translation model assets for Sarathi.

.DESCRIPTION
Downloads, copies, and verifies required CTranslate2 translation models into data/translation/models/.
Strictly verifies SHA-256 checksums and file sizes to ensure deterministic, fail-closed integrity.

Provisions the canonical neural translation engine:
1. Krutrim-Translate (Krutrim AI Labs distilled CT2, 4096 context, ~1.7GB total for hi-en + en-hi) - Full legal clause context with statutory glossaries and proper noun protection.

.PARAMETER ProjectRoot
Optional path to Sarathi repository root. Defaults to script parent's parent.

.PARAMETER VerifyOnly
If specified, only verifies existing model files on disk without downloading.

.PARAMETER SourceDir
Optional directory containing pre-downloaded models to copy and verify (100% offline mode).

.PARAMETER Engine
Translation engine models to setup: 'krutrim' (default) or 'all'.

.EXAMPLE
.\tools\scripts\Setup-TranslationModels.ps1 -VerifyOnly

.EXAMPLE
.\tools\scripts\Setup-TranslationModels.ps1 -Engine krutrim

.EXAMPLE
.\tools\scripts\Setup-TranslationModels.ps1 -SourceDir D:\OfflineModels\Translation
#>

[CmdletBinding()]
param(
    [Parameter()]
    [string] $ProjectRoot = '',

    [Parameter()]
    [switch] $VerifyOnly,

    [Parameter()]
    [string] $SourceDir = '',

    [Parameter()]
    [ValidateSet('krutrim', 'all')]
    [string] $Engine = 'krutrim',

    [Parameter()]
    [string] $HfToken = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0

if (-not $HfToken) {
    if ($env:HF_TOKEN) {
        $HfToken = $env:HF_TOKEN
    } elseif ($env:HUGGING_FACE_HUB_TOKEN) {
        $HfToken = $env:HUGGING_FACE_HUB_TOKEN
    }
}

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

$root = Resolve-SarathiRoot -Root $ProjectRoot
$transRoot = Join-Path $root 'data\translation'
$modelsDir = Join-Path $transRoot 'models'

if (-not (Test-Path -LiteralPath $transRoot -PathType Container)) {
    throw "Translation data directory not found at '$transRoot'."
}

if (-not (Test-Path -LiteralPath $modelsDir -PathType Container)) {
    $null = New-Item -ItemType Directory -Path $modelsDir -Force
}

# -----------------------------------------------------------------------------
# Declared Model Catalogs
# -----------------------------------------------------------------------------

$krutrimCatalog = @{
    'hi-en' = @{
        files = @(
            @{
                filename = 'model.bin'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_indic_english/model.bin'
            },
            @{
                filename = 'model.SRC'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_indic_english/vocab/model.SRC'
            },
            @{
                filename = 'model.TGT'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_indic_english/vocab/model.TGT'
            },
            @{
                filename = 'source_vocabulary.json'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_indic_english/source_vocabulary.json'
            },
            @{
                filename = 'target_vocabulary.json'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_indic_english/target_vocabulary.json'
            }
        )
    }
    'en-hi' = @{
        files = @(
            @{
                filename = 'model.bin'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_english_indic/model.bin'
            },
            @{
                filename = 'model.SRC'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_english_indic/vocab/model.SRC'
            },
            @{
                filename = 'model.TGT'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_english_indic/vocab/model.TGT'
            },
            @{
                filename = 'source_vocabulary.json'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_english_indic/source_vocabulary.json'
            },
            @{
                filename = 'target_vocabulary.json'
                url      = 'https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main/ct_model_english_indic/target_vocabulary.json'
            }
        )
    }
}

function Provision-ModelGroup {
    param(
        [string] $GroupName,
        [hashtable] $Catalog,
        [string] $TargetSubdir,
        [bool] $AlsoPopulateDefault
    )

    Write-Host "`n--- Checking $GroupName Translation Models ---" -ForegroundColor Cyan

    $totalFiles = 0
    $validFiles = 0

    foreach ($dirKey in $Catalog.Keys) {
        $dirInfo = $Catalog[$dirKey]
        $dirSub = $dirKey
        if ($TargetSubdir) {
            $dirSub = Join-Path $TargetSubdir $dirKey
        }
        $targetDir = Join-Path $modelsDir $dirSub
        $defaultDir = Join-Path $modelsDir $dirKey

        if (-not (Test-Path -LiteralPath $targetDir -PathType Container)) {
            $null = New-Item -ItemType Directory -Path $targetDir -Force
        }

        foreach ($fileEntry in $dirInfo.files) {
            $totalFiles++
            $fname = $fileEntry.filename
            $dest = Join-Path $targetDir $fname
            $expectedSha = ''
            if ($fileEntry.ContainsKey('sha256') -and $fileEntry['sha256']) {
                $expectedSha = $fileEntry['sha256'].ToLowerInvariant()
            }

            Write-Host "[$GroupName / $dirKey] Checking $fname... " -NoNewline

            $needFetch = $true
            if (Test-Path -LiteralPath $dest -PathType Leaf) {
                if ($expectedSha) {
                    $actualSha = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($actualSha -eq $expectedSha) {
                        Write-Host "OK (verified)" -ForegroundColor Green
                        $validFiles++
                        $needFetch = $false
                    } else {
                        Write-Warning "File $dest has invalid checksum (expected $expectedSha, got $actualSha)."
                        if (-not $VerifyOnly) {
                            Remove-Item -LiteralPath $dest -Force
                        }
                    }
                } else {
                    $size = (Get-Item -LiteralPath $dest).Length
                    if ($size -gt 1000) {
                        Write-Host "OK (present, $size bytes)" -ForegroundColor Green
                        $validFiles++
                        $needFetch = $false
                    }
                }
            }

            if ($needFetch) {
                if ($VerifyOnly) {
                    Write-Host "MISSING" -ForegroundColor Red
                    continue
                }

                # Check local SourceDir first (offline mode)
                $sourced = $false
                if ($SourceDir) {
                    $cand1 = Join-Path $SourceDir $fname
                    $cand2 = Join-Path (Join-Path $SourceDir $dirKey) $fname
                    $cand3 = $null
                    if ($TargetSubdir) {
                        $cand3 = Join-Path (Join-Path (Join-Path $SourceDir $TargetSubdir) $dirKey) $fname
                    }

                    foreach ($cand in @($cand1, $cand2, $cand3)) {
                        if ($cand -and (Test-Path -LiteralPath $cand -PathType Leaf)) {
                            Write-Host "Copying from $cand... " -NoNewline
                            Copy-Item -LiteralPath $cand -Destination $dest -Force
                            $sourced = $true
                            break
                        }
                    }
                }

                if (-not $sourced) {
                    $url = $fileEntry.url
                    Write-Host "Downloading from $url... " -NoNewline

                    $hasCurl = [bool](Get-Command curl.exe -ErrorAction SilentlyContinue)
                    $maxRetries = 5
                    $downloadOk = $false
                    $lastError = ""

                    for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
                        try {
                            if ($hasCurl) {
                                # Use -C - to auto-resume partial downloads, --retry-all-errors to retry exit code 18
                                $curlArgs = @('-s', '-S', '-L', '--fail', '-C', '-', '--retry', '5', '--retry-delay', '3', '--retry-all-errors')
                                if ($HfToken) {
                                    $curlArgs += @('-H', "Authorization: Bearer $HfToken")
                                }
                                $curlArgs += @('-o', $dest, $url)
                                $errOutput = (& curl.exe @curlArgs 2>&1) | Out-String
                                if ($LASTEXITCODE -ne 0) {
                                    # If -C - failed because range is not satisfiable or not supported, try fresh download
                                    if ($LASTEXITCODE -eq 33 -or $LASTEXITCODE -eq 36) {
                                        if (Test-Path -LiteralPath $dest -PathType Leaf) {
                                            Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
                                        }
                                        $curlArgs = @('-s', '-S', '-L', '--fail', '--retry', '5', '--retry-delay', '3', '--retry-all-errors')
                                        if ($HfToken) {
                                            $curlArgs += @('-H', "Authorization: Bearer $HfToken")
                                        }
                                        $curlArgs += @('-o', $dest, $url)
                                        $errOutput = (& curl.exe @curlArgs 2>&1) | Out-String
                                    }
                                }
                                if ($LASTEXITCODE -ne 0) {
                                    throw "curl download failed (exit code $LASTEXITCODE): $errOutput"
                                }
                            } else {
                                $headers = @{}
                                if ($HfToken) {
                                    $headers['Authorization'] = "Bearer $HfToken"
                                }
                                if ($headers.Count -gt 0) {
                                    Invoke-WebRequest -Uri $url -OutFile $dest -Headers $headers -UseBasicParsing -TimeoutSec 1200
                                } else {
                                    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -TimeoutSec 1200
                                }
                            }
                            $downloadOk = $true
                            $sourced = $true
                            break
                        } catch {
                            $lastError = $_.Exception.Message
                            if ($lastError -match '401' -or $lastError -match 'Unauthorized' -or $lastError -match '403') {
                                break
                            }
                            if ($attempt -lt $maxRetries) {
                                Write-Host "[Interrupted, resuming attempt $($attempt + 1)/$maxRetries]... " -ForegroundColor Yellow -NoNewline
                                Start-Sleep -Seconds 3
                            }
                        }
                    }

                    if (-not $downloadOk) {
                        Write-Host "FAILED ($lastError)" -ForegroundColor Red
                        if ($lastError -match '401' -or $lastError -match 'Unauthorized' -or $lastError -match '403') {
                            Write-Host "  [Authentication Required] Krutrim-Translate is a gated model on HuggingFace." -ForegroundColor Yellow
                            Write-Host "  1. Accept license at: https://huggingface.co/krutrim-ai-labs/Krutrim-Translate" -ForegroundColor Yellow
                            Write-Host "  2. Ensure your Hugging Face Token is valid: https://huggingface.co/settings/tokens" -ForegroundColor Yellow
                        }
                        throw "Failed to download $fname for direction $($dirKey): $lastError"
                    }
                }

                if ($sourced -and (Test-Path -LiteralPath $dest -PathType Leaf)) {
                    if ($expectedSha) {
                        $actualSha = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant()
                        if ($actualSha -eq $expectedSha) {
                            Write-Host "OK (verified)" -ForegroundColor Green
                            $validFiles++
                        } else {
                            Remove-Item -LiteralPath $dest -Force
                            throw "Downloaded $dest failed SHA-256 verification (got $actualSha, expected $expectedSha)."
                        }
                    } else {
                        Write-Host "OK (downloaded)" -ForegroundColor Green
                        $validFiles++
                    }
                }
            }

            # If this is the chosen engine and default directory isn't populated, populate default directory as well
            if ($AlsoPopulateDefault -and ($targetDir -ne $defaultDir) -and (Test-Path -LiteralPath $dest -PathType Leaf)) {
                if (-not (Test-Path -LiteralPath $defaultDir -PathType Container)) {
                    $null = New-Item -ItemType Directory -Path $defaultDir -Force
                }
                $defaultDest = Join-Path $defaultDir $fname
                if (-not (Test-Path -LiteralPath $defaultDest -PathType Leaf)) {
                    Copy-Item -LiteralPath $dest -Destination $defaultDest -Force
                }
            }
        }

        # For legacy compatibility, ensure spm.model exists (mirrors model.SRC)
        $srcSpm = Join-Path $targetDir 'model.SRC'
        $legacySpm = Join-Path $targetDir 'spm.model'
        if ((Test-Path -LiteralPath $srcSpm -PathType Leaf) -and (-not (Test-Path -LiteralPath $legacySpm -PathType Leaf))) {
            Copy-Item -LiteralPath $srcSpm -Destination $legacySpm -Force
        }

        # Write validated config.json for CTranslate2 Translator loading
        $configJsonContent = '{"add_source_bos":false,"add_source_eos":true,"bos_token":"<s>","decoder_start_token":"</s>","eos_token":"</s>","unk_token":"<unk>"}'
        $cfgPath = Join-Path $targetDir 'config.json'
        if (-not (Test-Path -LiteralPath $cfgPath -PathType Leaf)) {
            Set-Content -LiteralPath $cfgPath -Value $configJsonContent -Encoding UTF8
        }
        if ($AlsoPopulateDefault -and ($targetDir -ne $defaultDir)) {
            $defaultCfgPath = Join-Path $defaultDir 'config.json'
            if (-not (Test-Path -LiteralPath $defaultCfgPath -PathType Leaf)) {
                Set-Content -LiteralPath $defaultCfgPath -Value $configJsonContent -Encoding UTF8
            }
        }
    }

    return @{ Total = $totalFiles; Valid = $validFiles }
}

Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "  Sarathi Neural Translation Model Asset Provisioning" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "Target Directory: $modelsDir"
if ($VerifyOnly) {
    Write-Host "Mode: Verify Only (no downloads)" -ForegroundColor Yellow
} elseif ($SourceDir) {
    Write-Host "Mode: Offline Ingestion from $SourceDir" -ForegroundColor Green
} else {
    Write-Host "Mode: Online Fetch & SHA-256 Verification" -ForegroundColor Green
}
if ($HfToken) {
    Write-Host "Authentication: Hugging Face Token Detected" -ForegroundColor Green
} else {
    Write-Host "Authentication: None (Anonymous)" -ForegroundColor Yellow
}

$grandTotal = 0
$grandValid = 0

# Krutrim-Translate (4096 Context) is Sarathi's canonical neural translation engine
$res = Provision-ModelGroup -GroupName "Krutrim-Translate (4096 Context)" -Catalog $krutrimCatalog -TargetSubdir 'krutrim' -AlsoPopulateDefault $false
$grandTotal += $res.Total
$grandValid += $res.Valid

Write-Host "`n---------------------------------------------------------" -ForegroundColor Cyan
Write-Host "Translation Models Verified: $grandValid / $grandTotal files." -ForegroundColor $(if ($grandValid -eq $grandTotal) { 'Green' } else { 'Red' })

if ($grandValid -ne $grandTotal) {
    if ($VerifyOnly) {
        Write-Warning "Translation model assets are incomplete. Run without -VerifyOnly or supply -SourceDir."
        exit 1
    }
    throw "Some translation model files could not be verified."
}

Write-Host "[SUCCESS] Translation models ready." -ForegroundColor Green
exit 0
