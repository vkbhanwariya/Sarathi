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
$ErrorActionPreference = 'Stop'
$docPath = $args[0]
$docxPath = $args[1]

if (-not (Test-Path $docPath)) {
    Write-Error "Source file does not exist: $docPath"
    exit 1
}

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

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

    import json

    ps_script = f"""
$ErrorActionPreference = 'Stop'
$docPath = {json.dumps(str(resolved_doc))}
$docxPath = {json.dumps(str(target_docx))}

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

try {{
    $doc = $word.Documents.Open($docPath, $false, $true)
    $doc.SaveAs2($docxPath, 16)
    $doc.Close($false)
}} finally {{
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}}
"""

    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        ps_script,
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
        # Try to kill lingering winword processes if any was orphaned
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "WINWORD.EXE"],
                capture_output=True,
                check=False,
            )
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message=f"Conversion of legacy .doc file timed out after {timeout_seconds}s.",
        ) from exc
    except OSError as exc:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message=f"Failed to execute Word conversion subprocess: {exc}",
        ) from exc

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
