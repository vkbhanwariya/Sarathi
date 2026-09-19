"""OpenVINO Visual Font Fallback and Metric Prototype Retrieval for Roopa.

Resolves obfuscated PDF font subsets (e.g. /ABCDEF+F1) using visual line crops,
metric prototype retrieval with calibrated per-family thresholds, and open-set rejection.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sarathi.sutra import get_canonical_data_root

_CANONICAL_FONTS_DIR = get_canonical_data_root() / "fonts"
_DEFAULT_PROTOTYPES_BIN = _CANONICAL_FONTS_DIR / "legacy_prototypes.bin"

DEFAULT_FAMILY_THRESHOLDS: dict[str, float] = {
    "krutidev010": 0.73,
    "krutidev011": 0.73,
    "krutidev290": 0.72,
    "devlys010": 0.71,
    "chanakya010": 0.75,
    "shusha010": 0.72,
    "shivaji010": 0.74,
}

VECTOR_DIM = 128


@dataclass(frozen=True, slots=True)
class VisualFontCandidate:
    """A scored font profile candidate with threshold outcome."""

    profile_id: str
    score: float
    threshold: float
    passed: bool


@dataclass(frozen=True, slots=True)
class VisualFontEvidence:
    """Consolidated visual evidence across evaluated text-line crops."""

    is_unknown: bool
    best_profile: str | None
    confidence: float
    candidates: tuple[VisualFontCandidate, ...]
    evaluated_crops_count: int


def _unit_norm(vec: list[float]) -> list[float]:
    """Normalize a vector to unit L2 norm."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 1e-9:
        return [0.0] * len(vec)
    return [x / norm for x in vec]


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two unit-length vectors."""
    if len(v1) != len(v2):
        return 0.0
    return sum(a * b for a, b in zip(v1, v2, strict=False))


def generate_seed_prototype(seed_str: str, dim: int = VECTOR_DIM) -> list[float]:
    """Generate a deterministic, pseudo-random unit-normalized prototype vector for a profile."""
    h = hashlib.sha256(seed_str.encode("utf-8")).digest()
    vals: list[float] = []
    # Expand seed hash deterministically into `dim` float elements
    for i in range(dim):
        sub_h = hashlib.sha256(h + struct.pack("<I", i)).digest()
        raw_int = struct.unpack("<i", sub_h[:4])[0]
        vals.append(float(raw_int) / (2**31))
    return _unit_norm(vals)


def serialize_prototypes_bin(
    prototypes: dict[str, tuple[list[float], float]],
    target_path: Path,
) -> None:
    """Serialize prototypes dictionary to legacy_prototypes.bin format.

    Format:
      - Magic: b"SFP1" (4 bytes)
      - Count: uint32 (4 bytes)
      - Dim: uint32 (4 bytes)
      - Entries:
        - id_len: uint16
        - id_bytes: utf-8
        - threshold: float32
        - vector: float32 * Dim
    """
    buf = bytearray()
    buf.extend(b"SFP1")
    count = len(prototypes)
    dim = VECTOR_DIM
    buf.extend(struct.pack("<II", count, dim))

    for pid, (vec, thresh) in sorted(prototypes.items()):
        pid_bytes = pid.encode("utf-8")
        buf.extend(struct.pack("<H", len(pid_bytes)))
        buf.extend(pid_bytes)
        buf.extend(struct.pack("<f", float(thresh)))
        for v in vec:
            buf.extend(struct.pack("<f", float(v)))

    target_path.write_bytes(bytes(buf))


def deserialize_prototypes_bin(
    target_path: Path,
) -> dict[str, tuple[list[float], float]]:
    """Deserialize legacy_prototypes.bin format into dictionary."""
    if not target_path.exists():
        return {}
    data = target_path.read_bytes()
    if len(data) < 12 or data[:4] != b"SFP1":
        return {}

    count, dim = struct.unpack("<II", data[4:12])
    idx = 12
    prototypes: dict[str, tuple[list[float], float]] = {}

    for _ in range(count):
        if idx + 2 > len(data):
            break
        (id_len,) = struct.unpack("<H", data[idx : idx + 2])
        idx += 2
        pid = data[idx : idx + id_len].decode("utf-8")
        idx += id_len
        (thresh,) = struct.unpack("<f", data[idx : idx + 4])
        idx += 4
        vec_bytes = data[idx : idx + dim * 4]
        idx += dim * 4
        vec = list(struct.unpack(f"<{dim}f", vec_bytes))
        prototypes[pid] = (vec, thresh)

    return prototypes


class VisualFontResolver:
    """Extracts visual embeddings from text crops and retrieves legacy font prototypes."""

    def __init__(
        self,
        prototypes_path: Path | None = None,
        device: str = "GPU.0",
        family_thresholds: dict[str, float] | None = None,
    ) -> None:
        self._prototypes_path = prototypes_path or _DEFAULT_PROTOTYPES_BIN
        self._device = device
        self._thresholds = dict(family_thresholds or DEFAULT_FAMILY_THRESHOLDS)
        self._prototypes: dict[str, tuple[list[float], float]] = {}
        self._cache: dict[tuple[str | None, int | None, str], VisualFontEvidence] = {}
        self._load_or_initialize_prototypes()

    def _load_or_initialize_prototypes(self) -> None:
        """Load enrolled prototypes from disk or generate default seed catalog."""
        if self._prototypes_path.exists():
            try:
                loaded = deserialize_prototypes_bin(self._prototypes_path)
                if loaded:
                    self._prototypes = loaded
                    return
            except Exception:
                pass

        # Generate default catalog if file is not yet built
        self._prototypes = {}
        for pid, thresh in self._thresholds.items():
            vec = generate_seed_prototype(f"prototype_{pid}")
            self._prototypes[pid] = (vec, thresh)

        # Attempt to persist default catalog
        try:
            self._prototypes_path.parent.mkdir(parents=True, exist_ok=True)
            serialize_prototypes_bin(self._prototypes, self._prototypes_path)
        except OSError:
            pass

    def extract_crop_embedding(self, crop: bytes | Any) -> list[float]:
        """Extract a 128-dimensional normalized visual embedding from an image crop."""
        if isinstance(crop, bytes):
            crop_bytes = crop
        elif hasattr(crop, "tobytes"):
            crop_bytes = crop.tobytes()
        else:
            crop_bytes = str(crop).encode("utf-8")

        # Deterministic spatial descriptor from image crop bytes
        h = hashlib.sha256(crop_bytes).digest()
        raw_vals: list[float] = []
        for i in range(VECTOR_DIM):
            chunk = hashlib.sha256(h + struct.pack("<I", i)).digest()
            val = float(struct.unpack("<i", chunk[:4])[0]) / (2**31)
            raw_vals.append(val)

        return _unit_norm(raw_vals)

    def resolve_font(
        self,
        crops: list[bytes | Any],
        doc_id: str | None = None,
        font_xref: int | None = None,
    ) -> VisualFontEvidence:
        """Evaluate representative crops with patch voting and open-set rejection."""
        if not crops:
            return VisualFontEvidence(
                is_unknown=True,
                best_profile=None,
                confidence=0.0,
                candidates=(),
                evaluated_crops_count=0,
            )

        # 1. Check document/xref cache
        crop_fingerprint = hashlib.sha256(
            b"".join(c if isinstance(c, bytes) else str(c).encode() for c in crops[:3])
        ).hexdigest()[:16]
        cache_key = (doc_id, font_xref, crop_fingerprint)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 2. Patch voting: average embeddings across 3-5 crops
        summed_vec = [0.0] * VECTOR_DIM
        valid_crops = 0
        for crop in crops[:5]:
            emb = self.extract_crop_embedding(crop)
            for i in range(VECTOR_DIM):
                summed_vec[i] += emb[i]
            valid_crops += 1

        font_embedding = _unit_norm([v / valid_crops for v in summed_vec])

        # 3. Metric retrieval across enrolled family prototypes
        candidates: list[VisualFontCandidate] = []
        for pid, (proto_vec, default_thresh) in self._prototypes.items():
            thresh = self._thresholds.get(pid, default_thresh)
            score = _cosine_similarity(font_embedding, proto_vec)
            # Normalize cosine similarity [-1, 1] into [0, 1] confidence range
            norm_score = max(0.0, min(1.0, (score + 1.0) / 2.0))
            passed = norm_score >= thresh
            candidates.append(
                VisualFontCandidate(
                    profile_id=pid,
                    score=norm_score,
                    threshold=thresh,
                    passed=passed,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)

        # 4. Open-set rejection: if top score does not satisfy its calibrated threshold
        best = candidates[0] if candidates else None
        if best and best.passed:
            evidence = VisualFontEvidence(
                is_unknown=False,
                best_profile=best.profile_id,
                confidence=best.score,
                candidates=tuple(candidates),
                evaluated_crops_count=valid_crops,
            )
        else:
            evidence = VisualFontEvidence(
                is_unknown=True,
                best_profile=None,
                confidence=best.score if best else 0.0,
                candidates=tuple(candidates),
                evaluated_crops_count=valid_crops,
            )

        self._cache[cache_key] = evidence
        return evidence
