<#
.SYNOPSIS
Provisions and verifies declared RapidOCR ONNX model assets for Sarathi.

.DESCRIPTION
Reads data/ocr/manifest.json and ensures all declared model assets (det, rec,
rec_devanagari, rec_v6_en, cls) exist under data/ocr/models/ and strictly
match their expected SHA-256 checksums. Fails closed on any discrepancy.

.PARAMETER ProjectRoot
Optional path to Sarathi repository root. Defaults to script parent's parent.

.PARAMETER VerifyOnly
If specified, only verifies existing model files on disk without downloading.

.PARAMETER SourceDir
Optional directory containing pre-downloaded ONNX models to copy and verify.

.EXAMPLE
.\scripts\Setup-OCRModels.ps1 -VerifyOnly

.EXAMPLE
.\scripts\Setup-OCRModels.ps1 -SourceDir C:\Downloads\OCRModels
#>

[CmdletBinding()]
param(
    [Parameter()]
    [string] $ProjectRoot = '',

    [Parameter()]
    [switch] $VerifyOnly,

    [Parameter()]
    [string] $SourceDir = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0

function Resolve-SarathiRoot {
    param([string] $Root)
    if ($Root -and (Test-Path -LiteralPath (Join-Path $Root 'pyproject.toml') -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $Root).Path
    }
    $candidate = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    if (Test-Path -LiteralPath (Join-Path $candidate 'pyproject.toml') -PathType Leaf) {
        return $candidate
    }
    throw "Cannot determine Sarathi project root from '$Root' or script location."
}

$root = Resolve-SarathiRoot -Root $ProjectRoot
$manifestPath = Join-Path $root 'data\ocr\manifest.json'
$modelsDir = Join-Path $root 'data\ocr\models'

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "OCR manifest not found at '$manifestPath'."
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $manifest.models) {
    throw "OCR manifest at '$manifestPath' does not declare any models."
}

if (-not (Test-Path -LiteralPath $modelsDir -PathType Container)) {
    $null = New-Item -ItemType Directory -Path $modelsDir -Force
}

# Version-pinned canonical RapidOCR model catalog. Every downloaded file is
# independently verified against data/ocr/manifest.json before it is accepted.
$upstreamBaseUrl = 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2'
$modelRelativePaths = @{
    det            = 'onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx'
    rec            = 'onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx'
    rec_devanagari = 'onnx/PP-OCRv5/rec/devanagari_PP-OCRv5_rec_mobile.onnx'
    rec_v6_en      = 'onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx'
    cls            = 'onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx'
}

$models = $manifest.models.PSObject.Properties
$totalModels = 0
$validModels = 0

Write-Host "Verifying OCR models against manifest: $manifestPath" -ForegroundColor Cyan

foreach ($prop in $models) {
    $key = $prop.Name
    $info = $prop.Value
    $filename = $info.filename
    $expectedSha = $info.sha256.ToLowerInvariant()
    $destPath = Join-Path $modelsDir $filename
    $totalModels++

    Write-Host "[$key] Checking $filename... " -NoNewline

    $needFetch = $true
    if (Test-Path -LiteralPath $destPath -PathType Leaf) {
        $actualSha = (Get-FileHash -LiteralPath $destPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha -eq $expectedSha) {
            Write-Host "OK (checksum verified)" -ForegroundColor Green
            $validModels++
            $needFetch = $false
        } else {
            Write-Warning "Existing file $destPath has invalid checksum (expected $expectedSha, got $actualSha)."
            if ($VerifyOnly) {
                continue
            }
            Remove-Item -LiteralPath $destPath -Force
        }
    }

    if ($needFetch) {
        if ($VerifyOnly) {
            Write-Host "MISSING" -ForegroundColor Red
            continue
        }

        # Check local source directory if supplied.
        $sourced = $false
        if ($SourceDir -and (Test-Path -LiteralPath (Join-Path $SourceDir $filename) -PathType Leaf)) {
            $srcFile = Join-Path $SourceDir $filename
            Copy-Item -LiteralPath $srcFile -Destination $destPath -Force
            $sourced = $true
        } else {
            if (-not $modelRelativePaths.ContainsKey($key)) {
                throw "No upstream source mapping declared for OCR model '$key' ($filename)."
            }

            $relativePath = $modelRelativePaths[$key]
            $downloadUrl = "$upstreamBaseUrl/$relativePath"
            Write-Host "Downloading from $downloadUrl... " -NoNewline
            try {
                Invoke-WebRequest -Uri $downloadUrl -OutFile $destPath -UseBasicParsing
                $sourced = $true
            } catch {
                Write-Host "FAILED" -ForegroundColor Red
                throw "Failed to download model '$filename' from '$downloadUrl': $($_.Exception.Message)"
            }
        }

        if ($sourced -and (Test-Path -LiteralPath $destPath -PathType Leaf)) {
            $actualSha = (Get-FileHash -LiteralPath $destPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualSha -eq $expectedSha) {
                Write-Host "OK (verified)" -ForegroundColor Green
                $validModels++
            } else {
                Remove-Item -LiteralPath $destPath -Force
                throw "Downloaded file for model '$key' ($filename) failed SHA-256 verification (got $actualSha, expected $expectedSha)."
            }
        }
    }
}

Write-Host "----------------------------------------" -ForegroundColor Cyan
Write-Host "OCR Models Status: $validModels / $totalModels models ready and verified." -ForegroundColor $(if ($validModels -eq $totalModels) { 'Green' } else { 'Yellow' })

if ($validModels -ne $totalModels) {
    if ($VerifyOnly) {
        Write-Warning "Not all OCR models are provisioned. Run without -VerifyOnly to download, or supply -SourceDir."
        exit 1
    }
    throw "Failed to provision all required OCR models."
}
