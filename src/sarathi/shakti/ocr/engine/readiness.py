"""OCR Dependency and Model Preflight Readiness Checker for Sarathi.

Verifies required Python libraries, manifest integrity, and model file checksums
under strict local execution guarantees.
"""

from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Sequence
from pathlib import Path

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.ocr.engine.common import (
    CANONICAL_DATA_ROOT,
    HEX_64_PATTERN,
    REQUIRED_MODEL_KEYS,
)
from sarathi.shakti.ocr.engine.openvino import (
    disable_openvino_telemetry,
    is_safe_filename,
)


def verify_ocr_manifest_and_models(
    data_root: Path | None = None,
    target_keys: Sequence[str] | None = None,
    verified_cache: dict[str, str] | None = None,
) -> dict[str, str]:
    """Verify manifest integrity and SHA-256 checksums for requested OCR model keys.

    Args:
        data_root: Root directory containing manifest.json and models/.
        target_keys: Sequence of model keys to verify. Defaults to REQUIRED_MODEL_KEYS.
        verified_cache: Optional cache of previously verified model paths to avoid re-hashing.

    Returns:
        Mapping of model key to absolute model file path string.

    Raises:
        DoshError: If manifest or any model file is missing, invalid, or corrupted.
    """
    disable_openvino_telemetry()
    target_root = data_root.resolve() if data_root is not None else CANONICAL_DATA_ROOT
    manifest_file = target_root / "manifest.json"
    models_dir = target_root / "models"

    try:
        manifest_stat = manifest_file.lstat()
    except OSError as exc:
        raise DoshError(
            code=FailureCode.DEPENDENCY_UNAVAILABLE,
            message="Required local OCR model manifest is missing.",
        ) from exc

    if stat.S_ISLNK(manifest_stat.st_mode) or not stat.S_ISREG(manifest_stat.st_mode):
        raise DoshError(
            code=FailureCode.DEPENDENCY_UNAVAILABLE,
            message="Required local OCR model manifest is invalid or not a regular file.",
        )

    try:
        manifest_dict = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DoshError(
            code=FailureCode.DEPENDENCY_UNAVAILABLE,
            message="Failed to read or parse local OCR model manifest.",
        ) from exc

    if (
        not isinstance(manifest_dict, dict)
        or "models" not in manifest_dict
        or not isinstance(manifest_dict["models"], dict)
    ):
        raise DoshError(
            code=FailureCode.DEPENDENCY_UNAVAILABLE,
            message="Local OCR model manifest has an invalid structure.",
        )

    try:
        models_dir_stat = models_dir.lstat()
    except OSError as exc:
        raise DoshError(
            code=FailureCode.DEPENDENCY_UNAVAILABLE,
            message="Required local OCR model directory is missing.",
        ) from exc

    if stat.S_ISLNK(models_dir_stat.st_mode) or not stat.S_ISDIR(models_dir_stat.st_mode):
        raise DoshError(
            code=FailureCode.DEPENDENCY_UNAVAILABLE,
            message="Required local OCR model directory is invalid or a symlink.",
        )

    models_meta = manifest_dict["models"]

    # 1. Verify manifest structure for all required models
    for key in REQUIRED_MODEL_KEYS:
        if key not in models_meta or not isinstance(models_meta[key], dict):
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Local OCR model manifest is missing required model entry.",
            )

        entry = models_meta[key]
        filename = entry.get("filename")
        expected_sha = entry.get("sha256")

        if (
            not is_safe_filename(filename)
            or not isinstance(expected_sha, str)
            or not HEX_64_PATTERN.match(expected_sha)
        ):
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Local OCR model manifest contains invalid model entry.",
            )

    # 2. Verify disk assets and checksums for target models
    keys_to_verify = tuple(target_keys) if target_keys is not None else REQUIRED_MODEL_KEYS
    verified_paths: dict[str, str] = {}

    for key in keys_to_verify:
        if verified_cache is not None and key in verified_cache:
            verified_paths[key] = verified_cache[key]
            continue

        entry = models_meta[key]
        filename = entry["filename"]
        expected_sha = entry["sha256"]
        model_path = models_dir / str(filename)

        try:
            model_stat = model_path.lstat()
        except OSError as exc:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Required local OCR model asset is missing.",
            ) from exc

        if stat.S_ISLNK(model_stat.st_mode) or not stat.S_ISREG(model_stat.st_mode):
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Required local OCR model asset is not a regular file.",
            )

        h = hashlib.sha256()
        try:
            with open(model_path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
        except OSError as exc:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Failed to read local OCR model asset.",
            ) from exc

        if h.hexdigest().lower() != expected_sha.lower():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Local OCR model asset has invalid checksum.",
            )

        model_path_str = str(model_path)
        verified_paths[key] = model_path_str
        if verified_cache is not None:
            verified_cache[key] = model_path_str

    return verified_paths


_READINESS_VERIFIED_CACHE: dict[str, str] = {}


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

    try:
        verify_ocr_manifest_and_models(
            data_root=data_root,
            target_keys=REQUIRED_MODEL_KEYS,
            verified_cache=_READINESS_VERIFIED_CACHE,
        )
        return True, "Ready (RapidOCR + OpenVINO)"
    except DoshError as exc:
        return False, f"Unavailable ({exc.message})"
    except Exception:
        return False, "Unavailable (OCR preflight verification failed)"


__all__ = [
    "check_ocr_readiness",
    "verify_ocr_manifest_and_models",
]
