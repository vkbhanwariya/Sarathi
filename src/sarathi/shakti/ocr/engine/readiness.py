"""OCR Dependency and Model Preflight Readiness Checker for Sarathi.

Verifies required Python libraries, manifest integrity, and model file checksums
under strict local execution guarantees.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sarathi.shakti.ocr.engine.common import CANONICAL_DATA_ROOT
from sarathi.shakti.ocr.engine.openvino import (
    disable_openvino_telemetry,
    is_safe_filename,
)


def check_ocr_readiness(data_root: Path | None = None) -> tuple[bool, str]:
    """Verify that all required OCR dependencies, manifest, and model files are factually valid.

    Returns:
        (is_ready, status_or_reason)
    """
    disable_openvino_telemetry()
    import importlib.util

    for mod in ("rapidocr", "openvino", "PIL", "numpy"):
        if importlib.util.find_spec(mod) is None:
            return False, "Unavailable (Missing required OCR Python libraries)"

    target_root = data_root.resolve() if data_root is not None else CANONICAL_DATA_ROOT
    manifest_file = target_root / "manifest.json"
    models_dir = target_root / "models"

    try:
        if not manifest_file.exists() or manifest_file.is_symlink() or not manifest_file.is_file():
            return False, "Unavailable (OCR model manifest is missing or invalid)"
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or "models" not in manifest or not isinstance(manifest["models"], dict):
            return False, "Unavailable (OCR model manifest structure is invalid)"

        if not models_dir.exists() or models_dir.is_symlink() or not models_dir.is_dir():
            return False, "Unavailable (OCR models directory is missing or invalid)"

        models_meta = manifest["models"]
        for key in ("det", "rec", "cls", "rec_devanagari", "rec_v6_en"):
            if key not in models_meta or not isinstance(models_meta[key], dict):
                return False, f"Unavailable (OCR model manifest is missing required model entry '{key}')"
            entry = models_meta[key]
            filename = entry.get("filename")
            expected_sha = entry.get("sha256")
            if not filename or not expected_sha or not is_safe_filename(filename):
                return False, f"Unavailable (OCR model specification for '{key}' is invalid)"

            model_path = models_dir / filename
            if not model_path.exists() or model_path.is_symlink() or not model_path.is_file():
                return False, f"Unavailable (Required OCR model asset '{key}' is missing)"

            h = hashlib.sha256()
            with open(model_path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            if h.hexdigest().lower() != expected_sha.lower():
                return False, f"Unavailable (OCR model asset '{key}' checksum mismatch)"

        return True, "Ready (RapidOCR + OpenVINO)"
    except Exception:
        return False, "Unavailable (OCR preflight verification failed)"
