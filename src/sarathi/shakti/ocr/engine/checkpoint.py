"""Content-addressed per-page OCR checkpoint cache for atomic resumption and crash recovery.

Enables zero-recomputation on retry, crash recovery, and instant multi-pass reuse
by persisting completed page OCR results atomically under:
    Runtime/Cache/ocr_checkpoints/<doc_hash>/p<page_num>_<params_hash>.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sarathi.sankalpa import ExecutionProfile, PageData, ProvenanceRecord, TableData, TextSpan, WarningRecord

logger = logging.getLogger(__name__)

DEFAULT_CHECKPOINT_DIR: Path = Path("Runtime/Cache/ocr_checkpoints")
CHECKPOINT_SCHEMA_VERSION: int = 1


def get_default_checkpoint_dir(runtime_root: Path | None = None) -> Path:
    """Resolve the canonical checkpoint directory adhering to configured runtime root."""
    if DEFAULT_CHECKPOINT_DIR != Path("Runtime/Cache/ocr_checkpoints"):
        return DEFAULT_CHECKPOINT_DIR.resolve()
    if runtime_root is not None:
        return (runtime_root / "Cache" / "ocr_checkpoints").resolve()
    try:
        from sarathi.sutra import get_settings

        st = get_settings()
        if hasattr(st, "storage_runtime_root"):
            return (st.storage_runtime_root / "Cache" / "ocr_checkpoints").resolve()
    except Exception:
        pass
    return DEFAULT_CHECKPOINT_DIR.resolve()


def compute_doc_hash(data: bytes) -> str:
    """Compute deterministic SHA-256 fingerprint of input document bytes."""
    return hashlib.sha256(data).hexdigest()[:16]


def compute_params_hash(
    page_number: int,
    profile: str | ExecutionProfile,
    dpi: int = 200,
    lang: str = "hi",
    custom_options: Mapping[str, Any] | None = None,
    model_version: str = "v5_v6",
    asset_version: str | None = None,
) -> str:
    """Compute deterministic parameter fingerprint influencing page OCR output."""
    prof_str = profile.value if isinstance(profile, ExecutionProfile) else str(profile)
    opts = custom_options or {}

    # Extract all options that can alter page OCR text, layout, or confidence
    relevant_keys = (
        "deskew",
        "clahe",
        "english_numbers_only",
        "preserve_layout",
        "use_angle_cls",
        "use_cls",
        "review_threshold",
        "critical_review_threshold",
        "critical_retry_threshold",
        "max_critical_crops",
        "normalize_digits",
        "validation_enabled",
        "orientation_detection",
        "cls_thresh",
        "remove_stamps",
        "inpaint_stamps",
        "stamp_mode",
        "lightweight",
        "preprocess",
        "unpaper",
        "denoise",
        "shadow_removal",
    )
    extracted_opts = _clean_dict({k: opts[k] for k in relevant_keys if k in opts})
    eff_asset_version = asset_version or opts.get("asset_version", "")

    fingerprint_obj = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "page": page_number,
        "profile": prof_str,
        "dpi": dpi,
        "lang": str(getattr(lang, "value", lang)),
        "model_version": str(model_version),
        "asset_version": str(eff_asset_version),
        "options": extracted_opts,
    }
    canonical_str = json.dumps(fingerprint_obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:12]


def get_checkpoint_path(
    doc_hash: str,
    page_number: int,
    params_hash: str,
    cache_dir: Path | None = None,
) -> Path:
    """Resolve the canonical filesystem path for a specific page checkpoint."""
    base_dir = (cache_dir or get_default_checkpoint_dir()).resolve()
    return base_dir / doc_hash / f"p{page_number:04d}_{params_hash}.json"


def _clean_dict(d: Mapping[str, Any] | None) -> dict[str, Any]:
    """Ensure dictionary values are JSON serializable primitive types."""
    if not d:
        return {}
    res: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            res[str(k)] = v
        elif isinstance(v, Mapping):
            res[str(k)] = _clean_dict(v)
        elif isinstance(v, (list, tuple)):
            res[str(k)] = [
                _clean_dict(x) if isinstance(x, Mapping) else x
                for x in v
                if isinstance(x, (str, int, float, bool, Mapping)) or x is None
            ]
        else:
            res[str(k)] = str(v)
    return res


def serialize_page_data(page_data: PageData) -> dict[str, Any]:
    """Serialize PageData dataclass into a JSON-compatible dictionary."""
    spans_list = []
    for s in page_data.spans:
        spans_list.append(
            {
                "text": s.text,
                "confidence": s.confidence,
                "bounding_box": list(s.bounding_box) if s.bounding_box is not None else None,
                "language": s.language,
                "script": s.script,
                "metadata": _clean_dict(s.metadata),
            }
        )

    tables_list = []
    for t in page_data.tables:
        tables_list.append(
            {
                "name": t.name,
                "headers": list(t.headers),
                "rows": [list(row) for row in t.rows],
                "metadata": _clean_dict(t.metadata),
            }
        )

    return {
        "page_number": page_data.page_number,
        "text": page_data.text,
        "spans": spans_list,
        "tables": tables_list,
        "metadata": _clean_dict(page_data.metadata),
    }


def deserialize_page_data(d: dict[str, Any]) -> PageData:
    """Deserialize a JSON-compatible dictionary into a canonical PageData dataclass."""
    spans = [
        TextSpan(
            text=s["text"],
            confidence=float(s["confidence"]) if s.get("confidence") is not None else None,
            bounding_box=tuple(float(x) for x in s["bounding_box"]) if s.get("bounding_box") is not None else None,
            language=s.get("language"),
            script=s.get("script"),
            metadata=s.get("metadata", {}),
        )
        for s in d.get("spans", [])
    ]

    tables = [
        TableData(
            name=t.get("name", ""),
            headers=tuple(str(h) for h in t.get("headers", [])),
            rows=tuple(tuple(r) for r in t.get("rows", [])),
            metadata=t.get("metadata", {}),
        )
        for t in d.get("tables", [])
    ]

    return PageData(
        page_number=int(d["page_number"]),
        text=str(d.get("text", "")),
        spans=tuple(spans),
        tables=tuple(tables),
        metadata=d.get("metadata", {}),
    )


def serialize_provenance(prov: ProvenanceRecord | None) -> dict[str, Any] | None:
    """Serialize ProvenanceRecord dataclass into a JSON-compatible dictionary."""
    if prov is None:
        return None
    return {
        "source_input_id": prov.source_input_id,
        "source_file": prov.source_file,
        "stage": prov.stage,
        "plugin_id": prov.plugin_id,
        "capability_id": prov.capability_id,
        "page_number": prov.page_number,
        "region": prov.region,
        "evidence": _clean_dict(prov.evidence),
        "timestamp_utc": prov.timestamp_utc,
    }


def deserialize_provenance(d: dict[str, Any] | None) -> ProvenanceRecord | None:
    """Deserialize a JSON-compatible dictionary into a ProvenanceRecord dataclass."""
    if not d:
        return None
    return ProvenanceRecord(
        source_input_id=d.get("source_input_id"),
        source_file=d.get("source_file"),
        stage=d.get("stage"),
        plugin_id=d.get("plugin_id"),
        capability_id=d.get("capability_id"),
        page_number=d.get("page_number"),
        region=d.get("region"),
        evidence=d.get("evidence", {}),
        timestamp_utc=d.get("timestamp_utc"),
    )


def serialize_warnings(warnings: Sequence[WarningRecord]) -> list[dict[str, Any]]:
    """Serialize WarningRecord sequence into JSON-compatible dictionaries."""
    return [
        {
            "code": w.code,
            "message": w.message,
            "stage": w.stage,
            "context": _clean_dict(w.context),
        }
        for w in warnings
    ]


def deserialize_warnings(raw: list[dict[str, Any]]) -> list[WarningRecord]:
    """Deserialize JSON-compatible dictionaries into WarningRecord dataclasses."""
    return [
        WarningRecord(
            code=w["code"],
            message=w["message"],
            stage=w.get("stage"),
            context=w.get("context", {}),
        )
        for w in raw
    ]


def save_page_checkpoint(
    doc_hash: str,
    page_number: int,
    params_hash: str,
    page_data: PageData,
    provenance: ProvenanceRecord | None,
    warnings: Sequence[WarningRecord],
    cache_dir: Path | None = None,
) -> Path | None:
    """Atomically persist a completed page OCR result to the checkpoint cache.

    Writes to a temporary file and atomically renames it to target destination.
    Fail-safe: returns None rather than raising if disk write fails.
    """
    try:
        target_path = get_checkpoint_path(doc_hash, page_number, params_hash, cache_dir)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "doc_hash": doc_hash,
            "page_number": page_number,
            "params_hash": params_hash,
            "page_data": serialize_page_data(page_data),
            "provenance": serialize_provenance(provenance),
            "warnings": serialize_warnings(warnings),
        }

        # Atomic temp write + replace
        thread_id = threading.get_ident()
        pid = os.getpid()
        temp_path = target_path.with_name(f"{target_path.stem}.tmp.{pid}.{thread_id}")

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(temp_path, target_path)
            return target_path
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise
    except Exception as exc:
        logger.debug("Failed to write page checkpoint for doc %s page %d: %s", doc_hash, page_number, exc)
        return None


def load_page_checkpoint(
    doc_hash: str,
    page_number: int,
    params_hash: str,
    cache_dir: Path | None = None,
) -> tuple[PageData, ProvenanceRecord | None, list[WarningRecord]] | None:
    """Load and validate an existing page checkpoint.

    Returns (page_data, provenance, warnings) on valid hit, or None on miss/corruption.
    Corrupted files are cleaned up to prevent recurrent errors.
    """
    target_path = get_checkpoint_path(doc_hash, page_number, params_hash, cache_dir)
    if not target_path.is_file():
        return None

    try:
        with open(target_path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Invalid checkpoint JSON structure (not a dict)")

        if data.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            return None

        if (
            data.get("doc_hash") != doc_hash
            or data.get("page_number") != page_number
            or data.get("params_hash") != params_hash
        ):
            return None

        page_data = deserialize_page_data(data["page_data"])
        provenance = deserialize_provenance(data.get("provenance"))
        warnings = deserialize_warnings(data.get("warnings", []))

        return page_data, provenance, warnings
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        logger.debug("Removing corrupted page checkpoint %s: %s", target_path, exc)
        try:
            target_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    except OSError as exc:
        logger.debug("Transient I/O error reading checkpoint %s: %s", target_path, exc)
        return None


def evict_checkpoints(
    cache_dir: Path | None = None,
    max_bytes: int | None = None,
    max_age_seconds: float | None = None,
) -> int:
    """Evict old or excessive checkpoints based on age and total byte capacity.

    Returns the number of checkpoint files evicted.
    """
    base_dir = (cache_dir or get_default_checkpoint_dir()).resolve()
    if not base_dir.is_dir():
        return 0

    import time

    now = time.time()
    evicted_count = 0

    file_entries: list[tuple[Path, int, float]] = []
    try:
        for f in base_dir.rglob("p*.json"):
            if f.is_file() and not f.name.endswith(".tmp"):
                try:
                    st = f.stat()
                    file_entries.append((f, st.st_size, st.st_mtime))
                except OSError:
                    pass
    except OSError:
        return 0

    remaining_entries: list[tuple[Path, int, float]] = []
    for f_path, f_size, f_mtime in file_entries:
        if max_age_seconds is not None and (now - f_mtime) > max_age_seconds:
            try:
                f_path.unlink(missing_ok=True)
                evicted_count += 1
            except OSError:
                remaining_entries.append((f_path, f_size, f_mtime))
        else:
            remaining_entries.append((f_path, f_size, f_mtime))

    if max_bytes is not None:
        total_size = sum(sz for _, sz, _ in remaining_entries)
        if total_size > max_bytes:
            remaining_entries.sort(key=lambda x: x[2])
            for f_path, f_size, _ in remaining_entries:
                if total_size <= max_bytes:
                    break
                try:
                    f_path.unlink(missing_ok=True)
                    total_size -= f_size
                    evicted_count += 1
                except OSError:
                    pass

    return evicted_count


def clear_checkpoints(cache_dir: Path | None = None) -> int:
    """Purge all cached page OCR checkpoints from the filesystem, returning count of removed files."""
    base_dir = (cache_dir or get_default_checkpoint_dir()).resolve()
    if not base_dir.is_dir():
        return 0
    cleared = 0
    try:
        for f in base_dir.rglob("p*.json"):
            if f.is_file():
                try:
                    f.unlink(missing_ok=True)
                    cleared += 1
                except OSError:
                    pass
    except OSError:
        pass
    return cleared
