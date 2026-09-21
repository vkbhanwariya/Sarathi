"""Mapping Candidate Miner from Aligned Legacy/Unicode Text Pairs.

Extracts novel or missing legacy glyph mappings from dual-stream texts
(raw legacy byte stream aligned with verified Unicode OCR or reference text).
Uses sequence alignment across token/akshara boundaries to extract candidates:
    MappingCandidate(legacy, unicode, support, confidence)
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sarathi.shakti.font_conversion.detector import load_font_profiles  # noqa: E402


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    legacy: str
    unicode: str
    support: int
    confidence: float
    status: str  # "novel", "concordant", "conflicting"


def mine_mapping_candidates(
    legacy_text: str,
    unicode_text: str,
    existing_mappings: dict[str, str] | None = None,
    min_support: int = 1,
) -> list[MappingCandidate]:
    """Mine character/token mapping candidates from aligned parallel texts."""
    legacy_words = legacy_text.split()
    unicode_words = unicode_text.split()

    matcher = difflib.SequenceMatcher(None, legacy_words, unicode_words)
    pair_counts: Counter[tuple[str, str]] = Counter()
    legacy_totals: Counter[str] = Counter()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        # Check 1:1 word alignments
        if (i2 - i1) == 1 and (j2 - j1) == 1:
            lw = legacy_words[i1]
            uw = unicode_words[j1]

            # Intra-word character alignment
            char_matcher = difflib.SequenceMatcher(None, lw, uw)
            for ctag, ci1, ci2, cj1, cj2 in char_matcher.get_opcodes():
                if ctag in ("replace", "equal"):
                    l_sub = lw[ci1:ci2]
                    u_sub = uw[cj1:cj2]
                    if l_sub and u_sub and (l_sub != u_sub or not l_sub.isascii()):
                        pair_counts[(l_sub, u_sub)] += 1
                        legacy_totals[l_sub] += 1

    candidates: list[MappingCandidate] = []
    existing = existing_mappings or {}

    for (l_sub, u_sub), count in pair_counts.most_common():
        if count < min_support:
            continue
        total = legacy_totals[l_sub]
        conf = round(count / total, 3) if total > 0 else 0.0

        if l_sub not in existing:
            status = "novel"
        elif existing[l_sub] == u_sub:
            status = "concordant"
        else:
            status = "conflicting"

        candidates.append(
            MappingCandidate(
                legacy=l_sub,
                unicode=u_sub,
                support=count,
                confidence=conf,
                status=status,
            )
        )

    return candidates


def main() -> None:
    """CLI entry point for mine_mapping_candidates."""
    parser = argparse.ArgumentParser(description="Mine legacy-to-Unicode mapping candidates from aligned text.")
    parser.add_argument("--legacy-file", type=Path, required=True, help="Path to raw legacy text file.")
    parser.add_argument("--unicode-file", type=Path, required=True, help="Path to reference Unicode text file.")
    parser.add_argument("--profile", type=str, default=None, help="Existing profile ID to check against.")
    parser.add_argument("--min-support", type=int, default=1, help="Minimum occurrence count.")
    parser.add_argument("--json", action="store_true", help="Output candidates as JSON.")
    args = parser.parse_args()

    legacy_text = args.legacy_file.read_text(encoding="utf-8", errors="replace")
    unicode_text = args.unicode_file.read_text(encoding="utf-8", errors="replace")

    profiles = load_font_profiles()
    existing_map = dict(profiles[args.profile].mappings) if args.profile and args.profile in profiles else None

    candidates = mine_mapping_candidates(
        legacy_text=legacy_text,
        unicode_text=unicode_text,
        existing_mappings=existing_map,
        min_support=args.min_support,
    )

    if args.json:
        print(json.dumps([asdict(c) for c in candidates], indent=2, ensure_ascii=False))
    else:
        print(f"=== Mined {len(candidates)} Mapping Candidates ===")
        for c in candidates:
            print(
                f"[{c.status.upper():11s}] {c.legacy!r:>6s} -> {c.unicode!r:<6s} (support: {c.support}, conf: {c.confidence})"
            )


if __name__ == "__main__":
    main()
