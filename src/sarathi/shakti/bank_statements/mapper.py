"""Header Mapper for Bank Statements in Sarathi.

Maps extracted table headers to canonical financial fields:
- date, description, reference_number, cheque_number, debit, credit, amount, direction, balance

Resolution hierarchy:
1. Bank Exact Match
2. Generic Exact Match
3. Bank Fuzzy Match (Score >= 92%)
4. Generic Fuzzy Match (Score >= 92%)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from rapidfuzz import fuzz

    def _calc_similarity(s1: str, s2: str) -> float:
        return fuzz.ratio(s1, s2) / 100.0

except ImportError:
    from difflib import SequenceMatcher

    def _calc_similarity(s1: str, s2: str) -> float:
        return SequenceMatcher(None, s1, s2).ratio()

import yaml

from sarathi.dosh import DoshError, FailureCode
from sarathi.sutra import get_canonical_data_root

_CANONICAL_BANKS_DIR = get_canonical_data_root() / "banks"
CANONICAL_FIELDS = (
    "date",
    "value_date",
    "time",
    "description",
    "reference_number",
    "cheque_number",
    "debit",
    "credit",
    "amount",
    "direction",
    "balance",
)


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """Mapping of a source column index to a canonical field."""

    column_index: int
    source_header: str
    canonical_field: str
    match_type: str
    confidence: float


def load_bank_profile_yaml(path: Path) -> dict[str, Any]:
    """Canonical single-owner loader for bank profile YAML files with fail-fast validation."""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to parse bank profile YAML: {path.name}",
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Bank profile YAML root must be a mapping: {path.name}",
        )
    return data


def _normalize_header_token(raw: str) -> str:
    """Normalize raw header string by stripping parenthetical markers, currency symbols, and excess whitespace."""
    s = raw.lower().strip()
    s = re.sub(r"[\(\)\[\]\{\}\.\:\-\_\/]+", " ", s)
    s = re.sub(r"\b(inr|rs|₹)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _preindex_header_aliases(source: dict[str, Any]) -> dict[str, tuple[tuple[str, str], ...]]:
    indexed: dict[str, tuple[tuple[str, str], ...]] = {}
    for field, aliases in source.items():
        if isinstance(aliases, (list, tuple)):
            pairs: list[tuple[str, str]] = []
            for a in aliases:
                a_clean = str(a).strip().lower()
                a_norm = _normalize_header_token(a_clean)
                pairs.append((a_clean, a_norm))
            indexed[field] = tuple(pairs)
    return indexed


class HeaderMapper:
    """Resolves raw table headers to canonical field names."""

    def __init__(self, banks_dir: Path | None = None) -> None:
        self._banks_dir = banks_dir.resolve() if banks_dir is not None else _CANONICAL_BANKS_DIR
        self._common_config = load_bank_profile_yaml(self._banks_dir / "common.yaml")
        self._profiles = (
            {
                data["profile_id"]: data
                for f in self._banks_dir.glob("*.yaml")
                if f.name != "common.yaml"
                and isinstance((data := load_bank_profile_yaml(f)), dict)
                and "profile_id" in data
            }
            if self._banks_dir.exists()
            else {}
        )
        self._common_aliases_indexed = _preindex_header_aliases(self._common_config.get("aliases", {}))
        self._profiles_headers_indexed = {
            pid: _preindex_header_aliases(data.get("headers", {}))
            for pid, data in self._profiles.items()
        }

    def map_headers(
        self,
        headers: list[str] | tuple[str, ...],
        profile_id: str | None = None,
    ) -> list[ColumnMapping]:
        """Map raw header strings to canonical field names."""
        bank_headers_indexed = self._profiles_headers_indexed.get(profile_id or "", {})
        common_aliases_indexed = self._common_aliases_indexed

        mappings: list[ColumnMapping] = []
        mapped_fields: set[str] = set()

        for idx, raw_h in enumerate(headers):
            cleaned = str(raw_h).strip().lower()
            if not cleaned:
                continue

            mapping = self._match_header(
                idx, cleaned, str(raw_h), bank_headers_indexed, common_aliases_indexed, mapped_fields
            )
            if mapping:
                mappings.append(mapping)
                mapped_fields.add(mapping.canonical_field)

        return mappings

    def _score_mappings(
        self,
        mappings: list[ColumnMapping],
        is_candidate: bool = False,
        candidate_profile: str | None = None,
    ) -> float:
        """Calculate a composite quality score for a candidate column mapping."""
        if not mappings:
            return 0.0
        fields = {m.canonical_field: m for m in mappings}
        score = 0.0

        if "date" in fields:
            score += 3.0
        if "description" in fields:
            score += 2.0
        if "balance" in fields:
            score += 2.5
        if "debit" in fields:
            score += 2.0
        if "credit" in fields:
            score += 2.0
        if "amount" in fields:
            score += 2.0
        if "reference_number" in fields or "cheque_number" in fields:
            score += 1.0
        if "value_date" in fields:
            score += 0.5

        for m in mappings:
            if m.match_type == "bank_exact":
                score += 2.0
            elif m.match_type == "bank_fuzzy":
                score += 1.0
            elif m.match_type == "generic_exact":
                score += 0.5

        if is_candidate and candidate_profile and candidate_profile != "generic":
            score += 1.0

        return score

    def resolve_best_profile(
        self,
        headers: list[str] | tuple[str, ...],
        candidate_profile: str | None = None,
    ) -> tuple[str | None, list[ColumnMapping], float]:
        """Score all registered bank profiles against the extracted table headers and resolve the best match.

        Returns:
            Tuple of (best_profile_id, column_mappings, score).
        """
        candidate_mappings = self.map_headers(headers, profile_id=candidate_profile)
        candidate_score = self._score_mappings(
            candidate_mappings, is_candidate=True, candidate_profile=candidate_profile
        )

        best_profile: str | None = (
            candidate_profile if (candidate_profile and candidate_profile != "generic") else None
        )
        best_mappings = candidate_mappings
        best_score = candidate_score

        generic_mappings = self.map_headers(headers, profile_id=None)
        generic_score = self._score_mappings(generic_mappings, is_candidate=False)
        if generic_score > best_score:
            best_profile = None
            best_mappings = generic_mappings
            best_score = generic_score

        for prof_id in self._profiles:
            if prof_id == candidate_profile:
                continue
            prof_mappings = self.map_headers(headers, profile_id=prof_id)
            prof_score = self._score_mappings(prof_mappings, is_candidate=False)

            if prof_score > best_score:
                best_profile = prof_id
                best_mappings = prof_mappings
                best_score = prof_score

        return best_profile, best_mappings, round(best_score, 2)


    def _match_header(
        self,
        idx: int,
        cleaned: str,
        raw_header: str,
        bank_headers: dict[str, Any],
        common_aliases: dict[str, Any],
        already_mapped: set[str],
    ) -> ColumnMapping | None:
        available = [f for f in CANONICAL_FIELDS if f not in already_mapped]
        norm_cleaned = _normalize_header_token(cleaned)

        # 1. Exact matches: Bank exact -> Generic exact (with token normalization)
        for match_type, source in [("bank_exact", bank_headers), ("generic_exact", common_aliases)]:
            for field in available:
                for a in source.get(field, ()):
                    if isinstance(a, tuple) and len(a) == 2:
                        a_clean, a_norm = a
                    else:
                        a_clean = str(a).strip().lower()
                        a_norm = _normalize_header_token(a_clean)
                    if cleaned == a_clean or (norm_cleaned and norm_cleaned == a_norm):
                        return ColumnMapping(idx, raw_header, field, match_type, 1.0)

        # 2. Fuzzy matches: Bank fuzzy -> Generic fuzzy
        # Veda specification: >= 0.92 automatic when unambiguous; 0.85-0.91 only if beats runner-up by >= 0.05
        for match_type, source in [("bank_fuzzy", bank_headers), ("generic_fuzzy", common_aliases)]:
            scored = []
            for field in available:
                for a in source.get(field, ()):
                    if isinstance(a, tuple) and len(a) == 2:
                        a_clean, a_norm = a
                    else:
                        a_clean = str(a).strip().lower()
                        a_norm = _normalize_header_token(a_clean)
                    score = max(
                        _calc_similarity(cleaned, a_clean),
                        _calc_similarity(norm_cleaned, a_norm) if norm_cleaned and a_norm else 0.0,
                    )
                    scored.append((score, field))
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                best_score, best_field = scored[0]
                runner_up_score = scored[1][0] if len(scored) > 1 else 0.0

                if best_score >= 0.92:
                    if len(scored) > 1 and scored[1][0] == best_score and scored[1][1] != best_field:
                        # Ambiguous tie: leave unresolved
                        continue
                    return ColumnMapping(idx, raw_header, best_field, match_type, round(best_score, 4))
                elif 0.85 <= best_score < 0.92:
                    if (best_score - runner_up_score) >= 0.05:
                        return ColumnMapping(idx, raw_header, best_field, match_type, round(best_score, 4))

        return None
