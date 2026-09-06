"""Tesseract 5 fallback adapter, binary discovery, and text filtering."""

from __future__ import annotations

import math
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from sarathi.dosh import DoshError, FailureCode

_ALPHANUMERIC_FILTER_RE = re.compile(r"[^\x20-\x7E₹€£\n\r\t]")
_HAS_ENGLISH_OR_DIGIT_RE = re.compile(r"[A-Za-z0-9]")


def filter_english_and_numbers(text: str) -> str:
    """Filter text to retain only English characters, numbers, and standard alphanumeric symbols."""
    cleaned = _ALPHANUMERIC_FILTER_RE.sub("", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    if not _HAS_ENGLISH_OR_DIGIT_RE.search(cleaned):
        return ""
    return cleaned


def find_tesseract_executable() -> Path | None:
    """Discover Tesseract 5 executable across PATH, standard Windows install locations, and Unix paths."""
    import shutil

    candidates: list[Path] = [
        Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Tesseract-OCR" / "tesseract.exe")

    prog_files = os.environ.get("ProgramFiles")
    if prog_files:
        candidates.append(Path(prog_files) / "Tesseract-OCR" / "tesseract.exe")

    which_tess = shutil.which("tesseract")
    if which_tess:
        p = Path(which_tess).resolve()
        if os.name == "nt":
            if p.suffix.lower() == ".exe" and p.is_file():
                candidates.insert(0, p)
        elif p.is_file():
            candidates.insert(0, p)

    candidates.extend(
        [
            Path("/usr/bin/tesseract"),
            Path("/usr/local/bin/tesseract"),
        ]
    )

    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                return cand.resolve()
        except OSError:
            continue

    return None


def configure_pytesseract(
    executable_path: Path | str | None = None,
    tessdata_dir: Path | str | None = None,
) -> bool:
    """Discover, wire, and configure Tesseract and pytesseract.

    Resolves the Tesseract binary across PATH and standard install paths,
    prepends its directory to os.environ["PATH"], points
    pytesseract.pytesseract.tesseract_cmd to the executable, and sets
    TESSDATA_PREFIX if tessdata directory is discovered.

    Returns:
        True if Tesseract was successfully discovered and configured, False otherwise.
    """
    resolved_exe: Path | None = None
    if executable_path is not None:
        p = Path(executable_path).resolve()
        if p.is_file():
            resolved_exe = p
    else:
        resolved_exe = find_tesseract_executable()

    if resolved_exe is None:
        return False

    bin_dir = str(resolved_exe.parent)
    current_path = os.environ.get("PATH", "")
    if bin_dir.lower() not in current_path.lower():
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{current_path}"

    resolved_tessdata: Path | None = None
    if tessdata_dir is not None:
        td = Path(tessdata_dir).resolve()
        if td.is_dir():
            resolved_tessdata = td
    elif "TESSDATA_PREFIX" in os.environ and Path(os.environ["TESSDATA_PREFIX"]).is_dir():
        resolved_tessdata = Path(os.environ["TESSDATA_PREFIX"]).resolve()
    else:
        candidate_td = resolved_exe.parent / "tessdata"
        if candidate_td.is_dir():
            resolved_tessdata = candidate_td

    if resolved_tessdata is not None and "TESSDATA_PREFIX" not in os.environ:
        os.environ["TESSDATA_PREFIX"] = str(resolved_tessdata)

    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = str(resolved_exe)
    except ImportError:
        pass

    return True


class TesseractFallbackAdapter:
    """Targeted Tesseract 5 fallback adapter for weak OCR bounding boxes."""

    def __init__(
        self,
        executable_path: Path | str | None = None,
        tessdata_dir: Path | str | None = None,
        language: str = "eng",
        timeout_seconds: float = 10.0,
    ) -> None:
        if executable_path is not None:
            self._executable_path: Path | None = Path(executable_path).resolve()
        else:
            self._executable_path = find_tesseract_executable()

        if tessdata_dir is not None:
            self._tessdata_dir: Path | None = Path(tessdata_dir).resolve()
        elif self._executable_path is not None and (self._executable_path.parent / "tessdata").is_dir():
            self._tessdata_dir = self._executable_path.parent / "tessdata"
        elif "TESSDATA_PREFIX" in os.environ and Path(os.environ["TESSDATA_PREFIX"]).is_dir():
            self._tessdata_dir = Path(os.environ["TESSDATA_PREFIX"]).resolve()
        else:
            self._tessdata_dir = None

        self._language: str = language
        self._timeout_seconds: float = timeout_seconds

        # Wire and configure pytesseract only on default discovery or explicit real executable
        if executable_path is None and self._executable_path is not None and self._executable_path.is_file():
            configure_pytesseract(self._executable_path, self._tessdata_dir)

    @property
    def executable_path(self) -> Path | None:
        """Return the resolved path to the Tesseract executable, or None if unavailable."""
        return self._executable_path

    @property
    def tessdata_dir(self) -> Path | None:
        """Return the resolved path to the tessdata directory, or None if unavailable."""
        return self._tessdata_dir

    def is_available(self) -> bool:
        """Return True only when fixed configured executable path exists on disk."""
        return self._executable_path is not None and self._executable_path.is_file()

    def recognize_crop(self, crop_image: Any, language: str | None = None) -> tuple[str, float | None]:
        """Run Tesseract 5 on cropped sub-image and return (text, confidence).

        Raises:
            DoshError(DEPENDENCY_UNAVAILABLE): If Tesseract is not configured or executable missing.
            DoshError(EXECUTION_FAILED): If subprocess execution fails, times out, or produces unusable output.
        """
        if not self.is_available() or self._executable_path is None:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Tesseract fallback engine is not available at configured executable path.",
            )

        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_f:
            tmp_path = Path(tmp_f.name)

        active_lang = language or self._language
        cmd = [str(self._executable_path), str(tmp_path), "stdout", "--psm", "6", "-l", active_lang, "tsv"]
        if self._tessdata_dir is not None:
            cmd.extend(["--tessdata-dir", str(self._tessdata_dir)])

        try:
            crop_image.save(tmp_path)
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                check=False,
            )
            if res.returncode != 0:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Tesseract fallback execution returned non-zero exit status.",
                )

            stdout_text = res.stdout or ""
            lines = [ln for ln in stdout_text.splitlines() if ln.strip()]
            words: list[str] = []
            conf_scores: list[float] = []

            # Check for TSV format header
            if lines and ("\tconf\ttext" in lines[0] or lines[0].startswith("level\t")):
                has_invalid_conf = False
                for line in lines[1:]:
                    parts = line.split("\t")
                    if len(parts) >= 12:
                        word = parts[11].strip()
                        conf_str = parts[10].strip()
                        if word:
                            words.append(word)
                            try:
                                conf_num = float(conf_str)
                                # Tesseract TSV confidence is valid only when finite and within raw 0..100; convert once to 0..1
                                if not math.isnan(conf_num) and not math.isinf(conf_num) and 0.0 <= conf_num <= 100.0:
                                    conf_scores.append(conf_num / 100.0)
                                else:
                                    has_invalid_conf = True
                            except (ValueError, TypeError):
                                has_invalid_conf = True
                if not words:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Tesseract fallback produced unusable output.",
                    )
                text = unicodedata.normalize("NFC", " ".join(words))
                if has_invalid_conf or len(conf_scores) != len(words) or not conf_scores:
                    measured_conf = None
                else:
                    measured_conf = sum(conf_scores) / len(conf_scores)
                return text, measured_conf
            else:
                # Fallback for plain text output without TSV confidence
                plain_text = unicodedata.normalize("NFC", (res.stdout or "").strip())
                if not plain_text:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Tesseract fallback produced unusable output.",
                    )
                return plain_text, None
        except (subprocess.SubprocessError, OSError, UnicodeDecodeError):
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Tesseract fallback execution failed.",
            ) from None
        finally:
            tmp_path.unlink(missing_ok=True)
