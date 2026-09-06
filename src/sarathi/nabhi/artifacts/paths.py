"""Filesystem path security, boundary containment, and directory validation."""

from __future__ import annotations

import re
from pathlib import Path

from sarathi.dosh import DoshError, FailureCode

_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_REQUIREMENT_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_-]+$")
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_SAFE_DOTTED_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$")
_ISO_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
_CHUNK_SIZE = 65536


def _is_path_relative_to(path: Path, base: Path) -> bool:
    """Check if path is strictly located within or equal to base directory."""
    try:
        resolved_path = path.resolve()
        resolved_base = base.resolve()
        resolved_path.relative_to(resolved_base)
        return True
    except ValueError:
        return False
    except OSError as err:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Failed to inspect filesystem path containment.",
        ) from err


def _check_symlink_escape(target_path: Path, base_dir: Path) -> None:
    """Verify that neither target_path nor any of its ancestor directories up to base_dir
    symlink outside of base_dir.
    """
    try:
        resolved_base = base_dir.resolve()
    except OSError as err:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Filesystem access error inspecting boundary base directory.",
        ) from err

    current = target_path
    while True:
        try:
            if current.is_symlink():
                resolved_link = current.resolve()
                if not _is_path_relative_to(resolved_link, resolved_base):
                    raise DoshError(
                        code=FailureCode.SECURITY_DENIED,
                        message="Symlink escape detected: target path resolves outside boundary root.",
                    )
            resolved_current = current.resolve()
        except OSError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Filesystem access error inspecting path.",
            ) from err

        if resolved_current == resolved_base or current == current.parent:
            break
        current = current.parent


def _validate_root_directory(
    root: Path | str,
    param_name: str,
) -> Path:
    """Validate that a root path argument is a valid non-empty path and can serve as a directory."""
    if isinstance(root, bool) or not isinstance(root, (str, Path)):
        raise TypeError(f"{param_name} must be a Path or str, got {type(root).__name__}.")

    raw_str = str(root).strip()
    if not raw_str:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"{param_name} cannot be an empty or whitespace path.",
        )

    try:
        resolved_path = Path(root).resolve()
    except OSError as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to inspect {param_name} directory.",
        ) from err

    try:
        if resolved_path.exists() and not resolved_path.is_dir():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"{param_name} exists but is not a directory.",
            )
    except OSError as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to inspect {param_name} directory.",
        ) from err

    return resolved_path


def _validate_root_separation(runtime_root: Path, output_root: Path) -> None:
    """Ensure runtime_root and output_root are distinct and not nested within each other."""
    if runtime_root == output_root:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message="runtime_root and output_root cannot be the same directory.",
        )

    if _is_path_relative_to(output_root, runtime_root) or _is_path_relative_to(runtime_root, output_root):
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message="runtime_root and output_root cannot be nested within each other.",
        )
