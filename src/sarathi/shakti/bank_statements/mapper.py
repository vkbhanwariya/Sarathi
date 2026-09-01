"""Header Mapper for Bank Statements in Sarathi V2.

Maps extracted table headers to canonical financial fields:
- date, description, reference_number, cheque_number, debit, credit, amount, direction, balance

Resolution hierarchy:
1. Bank Exact Match
2. Generic Exact Match
3. Bank Fuzzy Match (Score >= 92%)
4. Generic Fuzzy Match (Score >= 92%)
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
import yaml

_CANONICAL_BANKS_DIR = Path(__file__).resolve().parents[4] / "data" / "banks"
CANONICAL_FIELDS = (
    "date", "description", "reference_number", "cheque_number",
    "debit", "credit", "amount", "direction", "balance"
)


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
        self._banks_dir = banks_dir.resolve() if banks_dir is not None else _CANONICAL_BANKS_DIR
        self._common_config = self._load_yaml(self._banks_dir / "common.yaml")
        self._profiles = {
            data["profile_id"]: data
            for f in self._banks_dir.glob("*.yaml")
            if f.name != "common.yaml" and isinstance((data := self._load_yaml(f)), dict) and "profile_id" in data
        } if self._banks_dir.exists() else {}

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                pass
        return {}

    def map_headers(
        self,
        headers: list[str] | tuple[str, ...],
        profile_id: str | None = None,
    ) -> list[ColumnMapping]:
        """Map raw header strings to canonical field names."""
        bank_headers = self._profiles.get(profile_id or "", {}).get("headers", {})
        common_aliases = self._common_config.get("aliases", {})

        mappings: list[ColumnMapping] = []
        mapped_fields: set[str] = set()

        for idx, raw_h in enumerate(headers):
            cleaned = str(raw_h).strip().lower()
            if not cleaned:
                continue

            mapping = self._match_header(idx, cleaned, str(raw_h), bank_headers, common_aliases, mapped_fields)
            if mapping:
                mappings.append(mapping)
                mapped_fields.add(mapping.canonical_field)

        return mappings

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

        # 1. Exact matches: Bank exact -> Generic exact
        for match_type, source in [("bank_exact", bank_headers), ("generic_exact", common_aliases)]:
            for field in available:
                if any(cleaned == str(a).strip().lower() for a in source.get(field, [])):
                    return ColumnMapping(idx, raw_header, field, match_type, 1.0)

        # 2. Fuzzy matches (>= 92%): Bank fuzzy -> Generic fuzzy
        for match_type, source in [("bank_fuzzy", bank_headers), ("generic_fuzzy", common_aliases)]:
            scored = [
                (SequenceMatcher(None, cleaned, str(a).strip().lower()).ratio(), field)
                for field in available
                for a in source.get(field, [])
            ]
            if scored:
                best_score, best_field = max(scored, key=lambda x: x[0])
                if best_score >= 0.92:
                    return ColumnMapping(idx, raw_header, best_field, match_type, best_score)

        return None
