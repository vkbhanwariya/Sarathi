"""Header Mapper for Bank Statements in Sarathi V2.

Maps extracted table headers to canonical financial fields:
- date
- description
- reference_number
- cheque_number
- debit
- credit
- balance

Resolution hierarchy:
1. Bank Exact Match
2. Generic Exact Match
3. Bank Fuzzy Match (Score >= 92)
4. Generic Fuzzy Match (Score >= 92)
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
import yaml


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """Mapping of a source column index to a canonical field."""

    column_index: int
    source_header: str
    canonical_field: str
    match_type: str
    confidence: float


class HeaderMapper:
    """Resolves raw table headers to canonical field names."""

    def __init__(self, banks_dir: Path | None = None) -> None:
        self._banks_dir = banks_dir or Path("E:/Sarathi/data/banks")
        self._common_config = self._load_common_config()
        self._profiles = self._load_profiles()

    def _load_common_config(self) -> dict[str, Any]:
        common_path = self._banks_dir / "common.yaml"
        if common_path.exists():
            try:
                data = yaml.safe_load(common_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _load_profiles(self) -> dict[str, dict[str, Any]]:
        profiles = {}
        if self._banks_dir.exists():
            for f in self._banks_dir.glob("*.yaml"):
                if f.name == "common.yaml":
                    continue
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "profile_id" in data:
                        profiles[data["profile_id"]] = data
                except Exception:
                    continue
        return profiles

    def map_headers(
        self,
        headers: list[str] | tuple[str, ...],
        profile_id: str | None = None,
    ) -> list[ColumnMapping]:
        """Map raw header strings to canonical field names.

        Args:
            headers: List of raw header strings from row 0.
            profile_id: Optional bank profile ID (e.g. 'sbi').

        Returns:
            List of ColumnMapping instances for recognized columns.
        """
        bank_profile = self._profiles.get(profile_id or "", {})
        bank_headers = bank_profile.get("headers", {})
        common_aliases = self._common_config.get("aliases", {})

        mappings: list[ColumnMapping] = []
        mapped_fields: set[str] = set()

        for idx, raw_h in enumerate(headers):
            cleaned = str(raw_h).strip().lower()
            if not cleaned:
                continue

            mapping = self._match_header(
                idx=idx,
                cleaned_header=cleaned,
                raw_header=str(raw_h),
                bank_headers=bank_headers,
                common_aliases=common_aliases,
                already_mapped=mapped_fields,
            )

            if mapping is not None:
                mappings.append(mapping)
                mapped_fields.add(mapping.canonical_field)

        return mappings

    def _match_header(
        self,
        idx: int,
        cleaned_header: str,
        raw_header: str,
        bank_headers: dict[str, Any],
        common_aliases: dict[str, Any],
        already_mapped: set[str],
    ) -> ColumnMapping | None:
        canonical_fields = ["date", "description", "reference_number", "cheque_number", "debit", "credit", "balance"]

        # 1. Bank Exact Match
        for field_name in canonical_fields:
            if field_name in already_mapped:
                continue
            aliases = bank_headers.get(field_name, [])
            if any(cleaned_header == str(a).strip().lower() for a in aliases):
                return ColumnMapping(idx, raw_header, field_name, "bank_exact", 1.0)

        # 2. Generic Exact Match
        for field_name in canonical_fields:
            if field_name in already_mapped:
                continue
            aliases = common_aliases.get(field_name, [])
            if any(cleaned_header == str(a).strip().lower() for a in aliases):
                return ColumnMapping(idx, raw_header, field_name, "generic_exact", 1.0)

        # 3. Bank Fuzzy Match (>= 92%)
        best_field: str | None = None
        best_score = 0.0
        best_match_type = ""

        for field_name in canonical_fields:
            if field_name in already_mapped:
                continue
            aliases = bank_headers.get(field_name, [])
            for a in aliases:
                ratio = SequenceMatcher(None, cleaned_header, str(a).strip().lower()).ratio()
                if ratio > best_score:
                    best_score = ratio
                    best_field = field_name
                    best_match_type = "bank_fuzzy"

        # 4. Generic Fuzzy Match (>= 92%)
        if best_score < 0.92:
            for field_name in canonical_fields:
                if field_name in already_mapped:
                    continue
                aliases = common_aliases.get(field_name, [])
                for a in aliases:
                    ratio = SequenceMatcher(None, cleaned_header, str(a).strip().lower()).ratio()
                    if ratio > best_score:
                        best_score = ratio
                        best_field = field_name
                        best_match_type = "generic_fuzzy"

        if best_score >= 0.92 and best_field is not None:
            return ColumnMapping(idx, raw_header, best_field, best_match_type, best_score)

        return None
