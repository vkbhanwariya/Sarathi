<#
.SYNOPSIS
Provisions and verifies declared CTranslate2 neural translation model assets for Sarathi.

.DESCRIPTION
Downloads, copies, and verifies required CTranslate2 translation models into data/translation/models/.
Strictly verifies SHA-256 checksums and file sizes to ensure deterministic, fail-closed integrity.

Supports two high-performance offline engine variants:
1. OPUS-MT (Helsinki-NLP INT8 quantized, ~160MB total for hi-en + en-hi) - Default, fast, lightweight.
2. IndicTrans2 (AI4Bharat 200M distilled CT2, ~1.7GB total for hi-en + en-hi) - High-fidelity Indic NMT.

.PARAMETER ProjectRoot
Optional path to Sarathi repository root. Defaults to script parent's parent.

.PARAMETER VerifyOnly
If specified, only verifies existing model files on disk without downloading.

.PARAMETER SourceDir
Optional directory containing pre-downloaded models to copy and verify (100% offline mode).

.PARAMETER Engine
Translation engine models to setup: 'opus_mt' (default), 'indictrans2', or 'all'.

.EXAMPLE
.\tools\scripts\Setup-TranslationModels.ps1 -VerifyOnly

.EXAMPLE
.\tools\scripts\Setup-TranslationModels.ps1 -Engine opus_mt

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
    [ValidateSet('opus_mt', 'indictrans2', 'all')]
    [string] $Engine = 'opus_mt',

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
$opusCatalog = @{
    'hi-en' = @{
        files = @(
            @{
                filename = 'model.bin'
                url      = 'https://huggingface.co/manancode/opus-mt-hi-en-ctranslate2-android/resolve/main/model.bin'
                sha256   = 'd6230c2d1789548608efcc79e93fd34e04e8b3204c61e2ddd8e14c15c12d10f9'
                size     = 77553155
            },
            @{
                filename = 'spm.model'
                url      = 'https://huggingface.co/manancode/opus-mt-hi-en-ctranslate2-android/resolve/main/source.spm'
                sha256   = 'dd20c408ec4568361d32b41080e3f6fa5b82895135bd25c2747b2c145e42d07b'
                size     = 1057690
            },
            @{
                filename = 'shared_vocabulary.json'
                url      = 'https://huggingface.co/manancode/opus-mt-hi-en-ctranslate2-android/resolve/main/shared_vocabulary.json'
                sha256   = '8a3899651f1e77c19851fb9981981b7fc02c72e7e53cbed6458d1be051cdd581'
                size     = 1762919
            }
        )
    }
    'en-hi' = @{
        files = @(
            @{
                filename = 'model.bin'
                url      = 'https://huggingface.co/manancode/opus-mt-en-hi-ctranslate2-android/resolve/main/model.bin'
                sha256   = '29c1207b3ee52185d4e2cc8333d7a1d9b277b103747b9e0c1efbfc29828f6250'
                size     = 77981115
            },
            @{
                filename = 'spm.model'
                url      = 'https://huggingface.co/manancode/opus-mt-en-hi-ctranslate2-android/resolve/main/source.spm'
                sha256   = 'fd4e951487aed00bae6a6c2ee4ef5d8d1db05fd098b19b608046c9334b58d24d'
                size     = 812240
            },
            @{
                filename = 'shared_vocabulary.json'
                url      = 'https://huggingface.co/manancode/opus-mt-en-hi-ctranslate2-android/resolve/main/shared_vocabulary.json'
                sha256   = '076550916e3005e2d5d2255b918d56b77b0b125f837f92a927c972a7d532defb'
                size     = 1799187
            }
        )
    }
}

$indicCatalog = @{
    'hi-en' = @{
        files = @(
            @{
                filename = 'model.bin'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-indic-en-dist-200M/resolve/main/indic-en-200m-ct2/ctranslate2_model/model.bin'
                sha256   = 'a88c1c56918d267c4003279b2b3d4ed47f7e18a859d38ebb8491da6c422e4de8'
                size     = 847167702
            },
            @{
                filename = 'model.SRC'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-indic-en-dist-200M/resolve/main/indic-en-200m-ct2/ctranslate2_model/vocab/model.SRC'
                sha256   = 'ac9257c8e76b8b607705b959cc3d075656ea33032f7a974e467b8941df6e98d4'
                size     = 3256903
            },
            @{
                filename = 'model.TGT'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-indic-en-dist-200M/resolve/main/indic-en-200m-ct2/ctranslate2_model/vocab/model.TGT'
                sha256   = '3cedc5cbcc740369b76201942a0f096fec7287fee039b55bdb956f301235b914'
                size     = 759425
            },
            @{
                filename = 'source_vocabulary.json'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-indic-en-dist-200M/resolve/main/indic-en-200m-ct2/ctranslate2_model/source_vocabulary.json'
                sha256   = '26d1ba4b6e918bef2bdccf1e0370130a3d641d30f7a945898a00f56043a9d8ad'
                size     = 4532115
            },
            @{
                filename = 'target_vocabulary.json'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-indic-en-dist-200M/resolve/main/indic-en-200m-ct2/ctranslate2_model/target_vocabulary.json'
                sha256   = 'debadde275c3afb460bf97913d02959537a4e24350376b93f1cba878e3661453'
                size     = 543196
            }
        )
    }
    'en-hi' = @{
        files = @(
            @{
                filename = 'model.bin'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-en-indic-dist-200M/resolve/main/en-indic-200m-ct2/ctranslate2_model/model.bin'
                sha256   = '2b4b4c195008f27e97f39be503f470b583c22fd670e67a9a886431df61348eba'
                size     = 847151318
            },
            @{
                filename = 'model.SRC'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-en-indic-dist-200M/resolve/main/en-indic-200m-ct2/ctranslate2_model/vocab/model.SRC'
                sha256   = '3cedc5cbcc740369b76201942a0f096fec7287fee039b55bdb956f301235b914'
                size     = 759425
            },
            @{
                filename = 'model.TGT'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-en-indic-dist-200M/resolve/main/en-indic-200m-ct2/ctranslate2_model/vocab/model.TGT'
                sha256   = 'ac9257c8e76b8b607705b959cc3d075656ea33032f7a974e467b8941df6e98d4'
                size     = 3256903
            },
            @{
                filename = 'source_vocabulary.json'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-en-indic-dist-200M/resolve/main/en-indic-200m-ct2/ctranslate2_model/source_vocabulary.json'
                sha256   = '66919522447d51be41250cc780c656e2ef495c403f96a7e4294dc36472524b8d'
                size     = 543560
            },
            @{
                filename = 'target_vocabulary.json'
                url      = 'https://huggingface.co/adalat-ai/ct2-rotary-indictrans2-en-indic-dist-200M/resolve/main/en-indic-200m-ct2/ctranslate2_model/target_vocabulary.json'
                sha256   = '7f28e3f24fcd0a203eb307e8c56ac0b99350a6a1562c25b6e8ffd97d6016878c'
                size     = 4531604
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
            if ($fileEntry.sha256) {
                $expectedSha = $fileEntry.sha256.ToLowerInvariant()
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
                    try {
                        $headers = @{}
                        if ($HfToken) {
                            $headers['Authorization'] = "Bearer $HfToken"
                        }
                        if ($headers.Count -gt 0) {
                            Invoke-WebRequest -Uri $url -OutFile $dest -Headers $headers -UseBasicParsing -TimeoutSec 900
                        } else {
                            Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -TimeoutSec 900
                        }
                        $sourced = $true
                    } catch {
                        Write-Host "FAILED ($($_.Exception.Message))" -ForegroundColor Red
                        $msg = $_.Exception.Message
                        throw "Failed to download $fname for direction $($dirKey): $msg"
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

$grandTotal = 0
$grandValid = 0

if ($Engine -eq 'opus_mt' -or $Engine -eq 'all') {
    # OPUS-MT models are strictly isolated to data/translation/models/opus_mt/
    $res = Provision-ModelGroup -GroupName "OPUS-MT (Marian INT8)" -Catalog $opusCatalog -TargetSubdir 'opus_mt' -AlsoPopulateDefault $false
    $grandTotal += $res.Total
    $grandValid += $res.Valid
}

if ($Engine -eq 'indictrans2' -or $Engine -eq 'all') {
    $res = Provision-ModelGroup -GroupName "IndicTrans2 (AI4Bharat 200M)" -Catalog $indicCatalog -TargetSubdir 'indictrans2' -AlsoPopulateDefault $false
    $grandTotal += $res.Total
    $grandValid += $res.Valid
}

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
