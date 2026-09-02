"""Mukha Intake — Canonical Input Discovery, Normalization, and Preflight.

The sole owner of filesystem input discovery, pasted multiline string expansion,
path normalization, canonical deduplication, hidden/temporary filtering, and preflight validation.
Does not perform presentation projection or runtime execution.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha
from sarathi.mukha.state import (
    InputGroupView,
    InputItemView,
    InputSelectionView,
    PreflightView,
)
from sarathi.sankalpa import InputRef

_IGNORE_FILE_SUFFIXES = frozenset({".tmp", ".crdownload", ".part", ".swp", ".bak", ".lock"})


def _is_hidden_or_temporary(path: Path) -> bool:
    """Return True if path is a hidden or temporary file."""
    name = path.name
    if name.startswith(".") or name.startswith("~$"):
        return True
    if path.suffix.lower() in _IGNORE_FILE_SUFFIXES:
        return True
    return False


def _is_subpath(child: Path, parent: Path | None) -> bool:
    """Check if child is equal to or located within parent directory."""
    if parent is None:
        return False
    try:
        child_res = child.resolve()
        parent_res = parent.resolve()
        return child_res == parent_res or parent_res in child_res.parents
    except OSError:
        return False


def intake_from_paths(
    paths: Sequence[Path | str],
    *,
    kavacha: Kavacha | None = None,
    runtime_root: Path | None = None,
    output_root: Path | None = None,
    recursive: bool = False,
) -> tuple[tuple[InputRef, ...], InputSelectionView, PreflightView]:
    """Convert selected filesystem paths, pasted strings, or folders into canonical InputRefs.

    Enforces canonical intake rules:
    - Path normalization & pasted multiline path string expansion;
    - Directory discovery (recursive only when explicitly enabled);
    - Dynamic exclusion of active/effective Runtime and Output roots;
    - Automatic filtering of hidden (.*) and temporary (~$*, *.tmp) files;
    - Requires regular file existence;
    - Factual stat().st_size (never zero fallback);
    - Deduplication by canonical resolved path;
    - Kavacha source-destination overlap validation when configured;
    - Media/format type remains unavailable until factual Darshana detection.

    Args:
        paths: Sequence of paths or strings (e.g. from CLI or file dialog).
        kavacha: Optional Kavacha security service instance.
        runtime_root: Optional active/effective runtime root to exclude.
        output_root: Optional active/effective output root to exclude.
        recursive: Whether to recursively scan directory inputs.

    Returns:
        tuple of:
        - tuple of validated, deduplicated InputRef objects in deterministic selection order;
        - InputSelectionView presentation model;
        - PreflightView containing any non-fatal validation issues.
    """
    seen_paths: set[Path] = set()
    valid_refs: list[InputRef] = []
    input_items: list[InputItemView] = []
    format_groups: dict[str, list[int]] = {}
    issues: list[tuple[str, str]] = []
    total_size = 0

    # 1. Expand input elements (supporting pasted multiline strings and quoted tokens)
    expanded_candidates: list[Path] = []
    for raw in paths:
        if isinstance(raw, Path):
            expanded_candidates.append(raw)
        elif isinstance(raw, str):
            lines = raw.strip().splitlines()
            for line in lines:
                cleaned = line.strip().strip("\"'")
                if cleaned:
                    expanded_candidates.append(Path(cleaned))

    # 2. Security Policy Overlap Validation via Kavacha when configured
    if kavacha is not None and expanded_candidates:
        dest_roots: list[Path] = []
        if runtime_root is not None:
            dest_roots.append(runtime_root)
        if output_root is not None:
            dest_roots.append(output_root)
        if dest_roots:
            kavacha.validate_source_destination_overlap(expanded_candidates, dest_roots)

    # 3. Process each candidate
    for cand in expanded_candidates:
        display_name = cand.name or str(cand)

        # A. Resolve path safely
        try:
            resolved = cand.resolve()
        except OSError:
            issues.append((display_name, "cannot resolve path"))
            input_items.append(
                InputItemView(
                    input_id=f"inp-{len(input_items) + 1:03d}",
                    display_name=display_name,
                    size_bytes=0,
                    is_eligible=False,
                    issue_reason="cannot resolve path",
                )
            )
            continue

        # B. Check existence
        if not cand.exists():
            issues.append((display_name, "file does not exist"))
            input_items.append(
                InputItemView(
                    input_id=f"inp-{len(input_items) + 1:03d}",
                    display_name=display_name,
                    size_bytes=0,
                    is_eligible=False,
                    issue_reason="file does not exist",
                )
            )
            continue

        # C. Exclude active Runtime and Output roots
        if _is_subpath(resolved, runtime_root) or _is_subpath(resolved, output_root):
            issues.append((display_name, "path is inside runtime or output root"))
            input_items.append(
                InputItemView(
                    input_id=f"inp-{len(input_items) + 1:03d}",
                    display_name=display_name,
                    size_bytes=0,
                    is_eligible=False,
                    issue_reason="path is inside runtime or output root",
                )
            )
            continue

        # D. Directory discovery
        if cand.is_dir():
            dir_files: list[Path] = []
            try:
                if recursive:
                    for root, _, files in resolved.walk():
                        for f in files:
                            dir_files.append(root / f)
                else:
                    for entry in resolved.iterdir():
                        if entry.is_file():
                            dir_files.append(entry)
            except OSError:
                issues.append((display_name, "permission denied accessing directory"))
                continue

            folder_added = 0
            for df in sorted(dir_files):
                df_resolved = df.resolve()
                if _is_hidden_or_temporary(df):
                    continue
                if _is_subpath(df_resolved, runtime_root) or _is_subpath(df_resolved, output_root):
                    continue
                if df_resolved in seen_paths:
                    continue
                try:
                    st = df.stat()
                    size = st.st_size
                except OSError:
                    issues.append((df.name, "failed to stat file size"))
                    continue

                seen_paths.add(df_resolved)
                input_id = f"inp-{len(valid_refs) + 1:03d}"
                ref = InputRef(
                    input_id=input_id,
                    source_path=df,
                    display_name=df.name,
                    size_bytes=size,
                )
                valid_refs.append(ref)
                total_size += size
                folder_added += 1
                input_items.append(
                    InputItemView(
                        input_id=input_id,
                        display_name=df.name,
                        size_bytes=size,
                        is_eligible=True,
                    )
                )
                ext = df.suffix.lower() or "no_ext"
                format_groups.setdefault(ext, []).append(size)

            if folder_added == 0:
                issues.append((display_name, "not a regular file"))
            continue

        # E. Regular file handling
        if not cand.is_file():
            issues.append((display_name, "not a regular file"))
            input_items.append(
                InputItemView(
                    input_id=f"inp-{len(input_items) + 1:03d}",
                    display_name=display_name,
                    size_bytes=0,
                    is_eligible=False,
                    issue_reason="not a regular file",
                )
            )
            continue

        # F. Filter hidden and temporary files
        if _is_hidden_or_temporary(cand):
            issues.append((display_name, "hidden or temporary file ignored"))
            continue

        # G. Deduplication by canonical resolved path
        if resolved in seen_paths:
            issues.append((display_name, "duplicate input path"))
            input_items.append(
                InputItemView(
                    input_id=f"inp-{len(input_items) + 1:03d}",
                    display_name=display_name,
                    size_bytes=0,
                    is_eligible=False,
                    issue_reason="duplicate input path",
                )
            )
            continue

        # H. Factual stat size
        try:
            st = cand.stat()
            size = st.st_size
        except OSError:
            issues.append((display_name, "failed to read file size"))
            input_items.append(
                InputItemView(
                    input_id=f"inp-{len(input_items) + 1:03d}",
                    display_name=display_name,
                    size_bytes=0,
                    is_eligible=False,
                    issue_reason="failed to read file size",
                )
            )
            continue

        seen_paths.add(resolved)
        input_id = f"inp-{len(valid_refs) + 1:03d}"
        ref = InputRef(
            input_id=input_id,
            source_path=cand,
            display_name=display_name,
            size_bytes=size,
        )
        valid_refs.append(ref)
        total_size += size
        input_items.append(
            InputItemView(
                input_id=input_id,
                display_name=display_name,
                size_bytes=size,
                is_eligible=True,
            )
        )
        ext = cand.suffix.lower() or "no_ext"
        format_groups.setdefault(ext, []).append(size)

    # 4. Construct presentation models
    total_files = len(valid_refs) + len(issues)
    is_grouped = len(format_groups) > 0 and total_files > 10
    groups = (
        tuple(
            InputGroupView(format_name=fmt, file_count=len(sizes), total_size_bytes=sum(sizes))
            for fmt, sizes in sorted(format_groups.items())
        )
        if is_grouped
        else ()
    )

    preflight_view = PreflightView(
        eligible_count=len(valid_refs),
        issue_count=len(issues),
        issues=tuple(issues),
    )

    selection_view = InputSelectionView(
        total_files=total_files,
        total_size_bytes=total_size,
        is_grouped=is_grouped,
        groups=groups,
        items=tuple(input_items),
    )

    return tuple(valid_refs), selection_view, preflight_view
