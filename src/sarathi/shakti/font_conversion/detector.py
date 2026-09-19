import struct
from pathlib import Path

from sarathi.shakti.font_conversion.models import (
    ConversionCandidate,
    ConversionDecision,
)
from sarathi.shakti.text.legacy_detection import (
    _CHANAKYA_SIGNATURES,
    _KNOWN_MODERN_FONTS,
    _KRUTI_SIGNATURES,
    _SHUSHA_SIGNATURES,
)
from sarathi.shakti.text.legacy_detection import (
    LegacyFontDetector as BaseLegacyFontDetector,
)
from sarathi.shakti.text.legacy_fonts import (
    _KNOWN_LATIN_FONTS,
    _KNOWN_MODERN_INDIC_FONTS,
    _KNOWN_UNSUPPORTED_LEGACY_FONTS,
    LegacyFontProfile,
    _merge_profile_data,
    _resolve_profile_inheritance,
    _validate_and_compile_profile,
    load_font_profiles,
    resolve_profile_from_font_name,
)
from sarathi.sutra import get_canonical_data_root

_CANONICAL_FONTS_DIR = get_canonical_data_root() / "fonts"

__all__ = [
    "BaseLegacyFontDetector",
    "ConversionCandidate",
    "ConversionDecision",
    "LegacyFontDetector",
    "LegacyFontProfile",
    "_CANONICAL_FONTS_DIR",
    "_CHANAKYA_SIGNATURES",
    "_KNOWN_LATIN_FONTS",
    "_KNOWN_MODERN_FONTS",
    "_KNOWN_MODERN_INDIC_FONTS",
    "_KNOWN_UNSUPPORTED_LEGACY_FONTS",
    "_KRUTI_SIGNATURES",
    "_SHUSHA_SIGNATURES",
    "_merge_profile_data",
    "_resolve_profile_inheritance",
    "_validate_and_compile_profile",
    "decide_run_profile",
    "load_font_profiles",
    "rank_profiles_from_text",
    "resolve_profile_from_font_name",
]


def extract_ttf_font_family(ttf_bytes: bytes) -> str | None:
    """Parse TrueType SFNT binary header 'name' table to extract font family or full name."""
    if not isinstance(ttf_bytes, (bytes, bytearray)) or len(ttf_bytes) < 12:
        return None

    try:
        sfnt_version, num_tables = struct.unpack(">IH", ttf_bytes[:6])
        name_table_offset = None

        for i in range(num_tables):
            offset = 12 + i * 16
            if offset + 16 > len(ttf_bytes):
                break
            tag, _, offset_val, _ = struct.unpack(">4sIII", ttf_bytes[offset : offset + 16])
            if tag == b"name":
                name_table_offset = offset_val
                break

        if name_table_offset is None or name_table_offset + 6 > len(ttf_bytes):
            return None

        format_val, count, string_offset = struct.unpack(">HHH", ttf_bytes[name_table_offset : name_table_offset + 6])
        for i in range(count):
            rec_off = name_table_offset + 6 + i * 12
            if rec_off + 12 > len(ttf_bytes):
                break
            platform_id, encoding_id, language_id, name_id, length, offset = struct.unpack(
                ">HHHHHH", ttf_bytes[rec_off : rec_off + 12]
            )
            # Name ID 1 = Font Family, Name ID 4 = Full Name
            if name_id in (1, 4):
                start = name_table_offset + string_offset + offset
                end = start + length
                if end <= len(ttf_bytes):
                    raw_name = ttf_bytes[start:end]
                    try:
                        name_str = raw_name.decode(
                            "utf-16be" if platform_id in (0, 3) else "latin1", errors="ignore"
                        ).strip()
                        if name_str:
                            return name_str
                    except Exception:
                        pass
    except (struct.error, ValueError, IndexError):
        return None

    return None


_DEFAULT_PROFILES: dict[str, LegacyFontProfile] | None = None


def rank_profiles_from_text(
    text: str,
    profiles: dict[str, LegacyFontProfile] | None = None,
    candidate_profiles: list[str] | tuple[str, ...] | None = None,
) -> list[ConversionCandidate]:
    """Rank legacy font profiles from text statistical properties and mapping evidence."""
    if not text or not text.strip():
        return []

    if profiles is None:
        global _DEFAULT_PROFILES
        if _DEFAULT_PROFILES is None:
            _DEFAULT_PROFILES = load_font_profiles()
        profiles = _DEFAULT_PROFILES

    eval_profiles = (
        [profiles[p] for p in candidate_profiles if p in profiles] if candidate_profiles else list(profiles.values())
    )

    candidates: list[ConversionCandidate] = []
    tokens = text.split()
    sample_tokens = tokens[:60] if len(tokens) > 60 else tokens

    for prof in eval_profiles:
        # Signatures
        pos_sigs = prof.detection_signatures
        if not pos_sigs:
            if prof.family in ("krutidev", "devlys"):
                pos_sigs = _KRUTI_SIGNATURES
            elif prof.family == "chanakya":
                pos_sigs = _CHANAKYA_SIGNATURES
            elif prof.family == "shusha":
                pos_sigs = _SHUSHA_SIGNATURES
            else:
                pos_sigs = ()

        neg_sigs = prof.negative_signatures

        matched_pos = tuple(s for s in pos_sigs if s in text)
        matched_neg = tuple(s for s in neg_sigs if s in text)

        # Token mapping coverage
        mapped_count = 0
        unmapped_count = 0
        unmapped_samples: list[str] = []

        if prof.compiled_forward_regex is not None:
            # Check how many characters or tokens are covered by mappings in sampled tokens
            for t in sample_tokens:
                # If word has at least 2 chars of legacy mapping
                m_chars = sum(len(m.group(0)) for m in prof.compiled_forward_regex.finditer(t))
                if m_chars > 0:
                    mapped_count += m_chars
                    diff = len(t) - m_chars
                    if diff > 0:
                        unmapped_count += diff
                else:
                    unmapped_count += len(t)
                    if len(unmapped_samples) < 5:
                        unmapped_samples.append(t)

        total_tokens = mapped_count + unmapped_count
        coverage = (mapped_count / total_tokens) if total_tokens > 0 else 0.0

        # Score computation
        pos_score = len(matched_pos) * 2.0
        neg_score = len(matched_neg) * 3.0
        cov_score = coverage * 5.0
        score = pos_score + cov_score - neg_score

        # Check structural validity
        defects: list[str] = []
        is_valid = True
        if matched_pos or coverage > 0.4:
            # Check for residual legacy markers
            if any(ch in text for ch in "ñòóôõö÷øùúûü") and prof.family not in ("krutidev", "devlys"):
                defects.append("RESIDUAL_LEGACY_GLYPHS")
                is_valid = False
                score -= 4.0

        candidates.append(
            ConversionCandidate(
                profile_id=prof.profile_id,
                score=score,
                positive_signatures=matched_pos,
                negative_signatures=matched_neg,
                mapping_coverage=coverage,
                mapped_token_count=mapped_count,
                unmapped_token_count=unmapped_count,
                unmapped_tokens=tuple(unmapped_samples),
                is_structurally_valid=is_valid,
                structural_defects=tuple(defects),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def decide_run_profile(
    run_font: str | None,
    run_text: str,
    doc_profile: str | None = None,
    profiles: dict[str, LegacyFontProfile] | None = None,
) -> ConversionDecision:
    """Determine the conversion decision for a specific run without document profile leakage."""
    if profiles is None:
        global _DEFAULT_PROFILES
        if _DEFAULT_PROFILES is None:
            _DEFAULT_PROFILES = load_font_profiles()
        profiles = _DEFAULT_PROFILES

    # 1. Direct font evidence
    if run_font:
        resolved_prof, fam = resolve_profile_from_font_name(run_font, profiles)
        if fam in ("modern", "latin"):
            return ConversionDecision(
                decision="preserve",
                reason="known_modern_unicode_font",
            )
        if fam == "unsupported_legacy":
            return ConversionDecision(
                decision="preserve",
                reason="unsupported_legacy_font",
            )
        if resolved_prof is not None:
            if run_text and run_text.strip():
                from sarathi.shakti.font_conversion.byte_normalizer import normalize_macroman_bytes

                eval_text = normalize_macroman_bytes(run_text)
                cands = rank_profiles_from_text(eval_text, profiles, candidate_profiles=[resolved_prof])
                cand = cands[0] if cands else None
                if cand is not None:
                    if cand.negative_signatures or (
                        not cand.is_structurally_valid and "COLLAPSED_CONSONANTS" in cand.structural_defects
                    ):
                        return ConversionDecision(
                            decision="preserve",
                            reason="conflicting_profile_evidence",
                        )
                    if len(eval_text.strip()) >= 8 and not cand.positive_signatures and cand.mapped_token_count == 0:
                        return ConversionDecision(
                            decision="preserve",
                            reason="insufficient_evidence",
                        )
            return ConversionDecision(
                decision="convert",
                profile=resolved_prof,
                reason="exact_source_font_alias",
            )

    # 2. Text evidence fallback
    if not run_text or not run_text.strip():
        return ConversionDecision(decision="preserve", reason="insufficient_evidence")

    from sarathi.shakti.font_conversion.byte_normalizer import normalize_macroman_bytes

    norm_text = normalize_macroman_bytes(run_text)
    candidates = rank_profiles_from_text(norm_text, profiles)
    if not candidates or candidates[0].score <= 0 or not candidates[0].positive_signatures:
        return ConversionDecision(decision="preserve", reason="insufficient_evidence")

    top = candidates[0]
    margin = (top.score - candidates[1].score) if len(candidates) > 1 else top.score

    # KrutiDev vs DevLys ambiguity check
    if len(candidates) > 1:
        c1, c2 = candidates[0], candidates[1]
        p1 = profiles.get(c1.profile_id)
        p2 = profiles.get(c2.profile_id)
        if p1 and p2 and {p1.family, p2.family} == {"krutidev", "devlys"} and margin < 1.0:
            if doc_profile and doc_profile in (c1.profile_id, c2.profile_id):
                return ConversionDecision(
                    decision="convert",
                    profile=doc_profile,
                    reason="exact_source_font_alias",
                    candidate_rank=1,
                    candidate_margin=margin,
                )
            return ConversionDecision(
                decision="ambiguous",
                profile=None,
                reason="conflicting_profile_evidence",
                candidate_rank=1,
                candidate_margin=margin,
            )

    if top.score >= 2.0 and top.is_structurally_valid:
        return ConversionDecision(
            decision="convert",
            profile=top.profile_id,
            reason="strong_text_evidence",
            candidate_rank=1,
            candidate_margin=margin,
        )

    return ConversionDecision(
        decision="preserve",
        reason="insufficient_evidence",
        candidate_margin=margin,
    )


class LegacyFontDetector(BaseLegacyFontDetector):
    """Detects legacy font encoding from text statistical properties and profile clues."""

    def __init__(
        self,
        fonts_dir: Path | None = None,
        profiles: dict[str, LegacyFontProfile] | None = None,
    ) -> None:
        super().__init__(fonts_dir=fonts_dir)
        self._profiles = profiles if profiles is not None else load_font_profiles(fonts_dir)

    @property
    def profiles(self) -> dict[str, LegacyFontProfile]:
        """Return the immutable mapping of loaded font profiles."""
        return self._profiles

    def detect(self, text: str, font_hint: str | None = None) -> tuple[str | None, float]:
        """Detect legacy font profile from font hint or actual text evidence."""
        if not text or not text.strip():
            return None, 0.0

        if font_hint:
            prof_id, fam = resolve_profile_from_font_name(font_hint, self._profiles)
            if fam == "modern" or prof_id is None:
                return None, 0.0

            candidates = rank_profiles_from_text(text, self._profiles)
            cand_map = {c.profile_id: c for c in candidates}
            cand = cand_map.get(prof_id)
            if cand is not None:
                # Reject hint if text exhibits negative signatures or severe structural collapse
                if cand.negative_signatures:
                    return None, 0.0
                if not cand.is_structurally_valid and "COLLAPSED_CONSONANTS" in cand.structural_defects:
                    return None, 0.0
                # If text has substantial length, require at least some legacy evidence
                if len(text.strip()) >= 15 and not cand.positive_signatures:
                    return None, 0.0
                # If another family has overwhelmingly strong evidence
                if (
                    candidates
                    and candidates[0].profile_id != prof_id
                    and candidates[0].score >= 3.0
                    and cand.score <= 0
                ):
                    return None, 0.0

                conf = max(0.8, min(1.0, 0.5 + len(cand.positive_signatures) * 0.1))
                return prof_id, conf

        if not self.is_legacy_text(text):
            return None, 0.0

        candidates = rank_profiles_from_text(text, self._profiles)
        if not candidates or candidates[0].score < 2.0:
            return None, 0.0

        top = candidates[0]
        if len(candidates) > 1:
            margin = top.score - candidates[1].score
            p1 = self._profiles.get(top.profile_id)
            p2 = self._profiles.get(candidates[1].profile_id)
            if p1 and p2 and {p1.family, p2.family} == {"krutidev", "devlys"} and margin < 1.0:
                # Ambiguous: cannot distinguish KrutiDev from DevLys on text alone without font hint
                return None, 0.0

        conf = min(1.0, 0.5 + len(top.positive_signatures) * 0.1)
        return top.profile_id, conf
