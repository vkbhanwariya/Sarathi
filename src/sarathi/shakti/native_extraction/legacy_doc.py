"""Legacy Word 97-2003 (.doc) to OpenXML (.docx) converter for Windows hosts."""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

from sarathi.dosh import DoshError, FailureCode


def is_word_converter_available() -> bool:
    """Check if Microsoft Word COM automation is available on the current Windows host."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"):
            return True
    except OSError:
        return False


_CONVERT_PS_SCRIPT = r"""
param(
    [Parameter(Mandatory=$true)][string]$docPath,
    [Parameter(Mandatory=$true)][string]$docxPath,
    [Parameter(Mandatory=$false)][string]$pidPath
)
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $docPath)) {
    Write-Error "Source file does not exist: $docPath"
    exit 1
}

$beforePids = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

$afterPids = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$conversionPid = $afterPids | Where-Object { $beforePids -notcontains $_ } | Select-Object -First 1

if ($pidPath -and $conversionPid) {
    try {
        [System.IO.File]::WriteAllText($pidPath, [string]$conversionPid)
    } catch {}
}

try {
    # Open(FileName, ConfirmConversions, ReadOnly)
    $doc = $word.Documents.Open($docPath, $false, $true)
    # 16 = wdFormatXMLDocument (.docx)
    $doc.SaveAs2($docxPath, 16)
    $doc.Close($false)
} finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}
"""


def convert_doc_to_docx(
    doc_path: Path,
    output_dir: Path | None = None,
    timeout_seconds: float = 20.0,
) -> Path:
    """Convert a legacy .doc file to modern .docx using local Microsoft Word COM automation.

    Args:
        doc_path: Absolute or relative Path to source .doc file.
        output_dir: Directory where the converted .docx should be written.
        timeout_seconds: Maximum time in seconds to wait before terminating.

    Returns:
        Path to the converted .docx file.

    Raises:
        DoshError: If Word is not available, or conversion fails / times out.
    """
    resolved_doc = Path(doc_path).resolve()
    if not resolved_doc.is_file():
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message=f"Source legacy .doc file not found: '{doc_path}'.",
        )

    if not is_word_converter_available():
        raise DoshError(
            code=FailureCode.UNSUPPORTED,
            message=(
                "Microsoft Word is required on Windows to convert legacy .doc files. "
                "Please save the document as .docx in Microsoft Word or upload a .docx file."
            ),
        )

    target_dir = Path(output_dir).resolve() if output_dir else resolved_doc.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    out_filename = f"{resolved_doc.stem}_{uuid.uuid4().hex[:8]}.docx"
    target_docx = target_dir / out_filename

    pid_file = target_dir / f"_pid_{uuid.uuid4().hex[:8]}.txt"
    script_file = target_dir / f"_convert_{uuid.uuid4().hex[:8]}.ps1"
    script_file.write_text(_CONVERT_PS_SCRIPT, encoding="utf-8")

    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_file),
        str(resolved_doc),
        str(target_docx),
        str(pid_file),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if sys.platform == "win32" and pid_file.is_file():
            try:
                raw_pid = pid_file.read_text(encoding="utf-8").strip()
                if raw_pid.isdigit():
                    conversion_pid = int(raw_pid)
                    # Verify this process is indeed WINWORD.EXE owned by this conversion before terminating
                    chk = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {conversion_pid}", "/FO", "CSV", "/NH"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if "WINWORD.EXE" in chk.stdout.upper():
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(conversion_pid)],
                            capture_output=True,
                            check=False,
                        )
            except Exception:
                pass
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message=f"Conversion of legacy .doc file timed out after {timeout_seconds}s.",
        ) from exc
    except OSError as exc:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message=f"Failed to execute Word conversion subprocess: {exc}",
        ) from exc
    finally:
        for f in (script_file, pid_file):
            try:
                if f.exists():
                    f.unlink()
            except OSError:
                pass

    if proc.returncode != 0 or not target_docx.is_file() or target_docx.stat().st_size == 0:
        err_msg = (proc.stderr or proc.stdout or "Unknown conversion error").strip()
        if target_docx.exists():
            try:
                target_docx.unlink()
            except OSError:
                pass
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message=f"Failed to convert legacy .doc file '{doc_path.name}' to .docx: {err_msg}",
        )

    return target_docx
