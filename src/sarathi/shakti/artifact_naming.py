"""Canonical Artifact Naming utilities for Shakti Capabilities."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from sarathi.sankalpa import InputRef

_UNSAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9_.-]")


def sanitize_filename_component(name: str) -> str:
    """Sanitize a string for safe inclusion in an artifact filename."""
    if not name:
        return "input"
    cleaned = _UNSAFE_CHARS_RE.sub("_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "input"


def format_artifact_filename(
    input_ref: InputRef,
    suffix: str,
    extension: str,
    *,
    all_inputs: Sequence[InputRef] | None = None,
    index: int | None = None,
) -> str:
    """Format an artifact filename cleanly and collision-safely.

    Args:
        input_ref: The target InputRef being processed.
        suffix: Suffix describing artifact role (e.g. 'ocr', 'extracted', 'converted').
        extension: File extension without leading dot (e.g. 'txt', 'docx', 'json').
        all_inputs: Optional full sequence of inputs for the request, used to detect duplicate basenames.
        index: Optional 0-based index in the batch.

    Returns:
        Clean, unambiguous artifact filename string.
    """
    raw_name = input_ref.display_name or (
        input_ref.source_path.name if input_ref.source_path else input_ref.input_id
    )
    stem = Path(raw_name).stem if raw_name else input_ref.input_id
    clean_stem = sanitize_filename_component(stem)

    ext = extension.lstrip(".")
    clean_suffix = suffix.strip("_")

    # Detect duplicate stem in batch
    is_duplicate = False
    if all_inputs is not None and len(all_inputs) > 1:
        stems = [
            sanitize_filename_component(
                Path(inp.display_name or (inp.source_path.name if inp.source_path else inp.input_id)).stem
            )
            for inp in all_inputs
        ]
        if stems.count(clean_stem) > 1:
            is_duplicate = True

    if is_duplicate:
        qualifier = f"_{index + 1}" if index is not None else f"_{sanitize_filename_component(input_ref.input_id)}"
        return f"{clean_stem}{qualifier}_{clean_suffix}.{ext}"

    return f"{clean_stem}_{clean_suffix}.{ext}"


def infer_cloud_media_type(path: Path) -> str:
    """Infer cloud provider media type from file extension."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


def resolve_source_input(
    inputs: Sequence[InputRef],
    source_input_id: str | None = None,
    document_id: str | None = None,
) -> InputRef:
    """Resolve the canonical source InputRef by exact identity.

    Rules:
    1. Match exact source_input_id if provided.
    2. Match exact document_id against input_id.
    3. If single input in request, return that input.
    4. Never match by substring (e.g. 'input-1' in 'input-10').
    5. If missing or ambiguous, return explicit fallback InputRef without guessing.
    """
    if source_input_id:
        for inp in inputs:
            if inp.input_id == source_input_id:
                return inp

    if document_id:
        for inp in inputs:
            if inp.input_id == document_id:
                return inp

    if len(inputs) == 1:
        return inputs[0]

    fallback_id = source_input_id or document_id or "unknown"
    return InputRef(
        input_id=fallback_id,
        source_path=Path(f"{fallback_id}.txt"),
        display_name=f"{fallback_id}.txt",
        size_bytes=0,
    )

