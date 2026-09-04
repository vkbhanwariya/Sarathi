"""Evidence-based Legacy Font Detector for Roopa."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.font_conversion.models import (
    ConversionCandidate,
    ConversionDecision,
    LegacyFontProfile,
)
from sarathi.sutra import get_canonical_data_root

_CANONICAL_FONTS_DIR = get_canonical_data_root() / "fonts"

_KRUTI_SIGNATURES: tuple[str, ...] = (
    "[k", "vk", "vks", "vkS", "Fk", "/k", "Hk", "'k", ";Z", "jZ",
    ";k", "D;", "x~", "LVs", "cSa", ".k", "ñ", "ò", "ó", "ô",
    "õ", "ö", "÷", "ø", "ù", "ú", "û", "ü", "fdr", "fd",
    "fr", "fn", "fc", "f[", "fH", "fF", "fD", "fnY", "mRr",
)

_CHANAKYA_SIGNATURES: tuple[str, ...] = (
    "¥æ", "§Z", "§ü", "°ð", "ƒæ", "Ûæ", "ÿæ", "˜æ", "™æ", "æò",
    "æñ", "¥æò", "¥æð", "¥æñ", "¥ô", "¥õ",
)

_SHUSHA_SIGNATURES: tuple[str, ...] = (
    "aA", "bA", "cA", "dA", "uA", "vA", "wA", "pA", "sA", "tA",
    "rA", "yA",
)

_KNOWN_MODERN_FONTS: frozenset[str] = frozenset({
    "arial", "calibri", "timesnewroman", "times", "cambria", "georgia",
    "verdana", "tahoma", "couriernew", "courier", "segoeui", "segoe",
    "helvetica", "trebuchetms", "trebuchet", "bookmanoldstyle", "bookman",
    "garamond", "centurygothic", "mangal", "nirmalaui", "nirmala",
    "aparajita", "kokila", "utsaah", "gautami", "latha", "shruti",
})


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

        format_val, count, string_offset = struct.unpack(
            ">HHH", ttf_bytes[name_table_offset : name_table_offset + 6]
        )
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


def _validate_and_compile_profile(data: dict, source_name: str, seen_ids: set[str], seen_aliases: dict[str, str]) -> LegacyFontProfile:
    """Validate font profile schema strictly and compile forward/reverse regexes."""
    pid = data.get("profile_id")
    if not pid or not isinstance(pid, str) or not pid.strip():
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Font profile in '{source_name}' is missing a valid 'profile_id'.",
        )
    if pid in seen_ids:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Duplicate font profile_id '{pid}' in '{source_name}'.",
        )
    seen_ids.add(pid)

    family = data.get("family")
    if not family or not isinstance(family, str) or not family.strip():
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Font profile '{pid}' is missing a valid 'family'.",
        )

    name = data.get("name") or pid
    raw_aliases = data.get("aliases", ())
    if not isinstance(raw_aliases, (list, tuple)):
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Font profile '{pid}' aliases must be a list or tuple.",
        )

    aliases: list[str] = []
    for a in raw_aliases:
        if not isinstance(a, str) or not a.strip():
            continue
        cleaned_alias = "".join(c for c in a.lower() if c.isalnum())
        if cleaned_alias in seen_aliases and seen_aliases[cleaned_alias] != pid:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Font alias collision: alias '{a}' in profile '{pid}' conflicts with profile '{seen_aliases[cleaned_alias]}'.",
            )
        seen_aliases[cleaned_alias] = pid
        aliases.append(a.strip())

    mappings = data.get("mappings")
    if not isinstance(mappings, dict) or not mappings:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Font profile '{pid}' must contain a non-empty 'mappings' dictionary.",
        )

    for k, v in mappings.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Invalid mapping pair ({k!r}, {v!r}) in font profile '{pid}'.",
            )

    prefixes = data.get("prefixes", {})
    if not isinstance(prefixes, dict):
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Font profile '{pid}' prefixes must be a dictionary.",
        )

    postfix_reph = str(data.get("postfix_reph", "Z"))
    reph_unicode = str(data.get("reph_unicode", "र्"))

    post_corrections = tuple(
        tuple(c) for c in data.get("post_corrections", ())
        if isinstance(c, (list, tuple)) and len(c) == 2
    )
    family_corrections = tuple(
        tuple(c) for c in data.get("family_corrections", ())
        if isinstance(c, (list, tuple)) and len(c) == 2
    )
    symbols = dict(data.get("symbols", {}))
    reverse_preferred = dict(data.get("reverse_preferred", {}))

    det_sigs = tuple(str(s) for s in data.get("detection_signatures", ()))
    neg_sigs = tuple(str(s) for s in data.get("negative_signatures", ()))

    # Precompile forward transducer
    sorted_keys = sorted(mappings.keys(), key=len, reverse=True)
    forward_re = re.compile("|".join(re.escape(k) for k in sorted_keys)) if sorted_keys else None

    # Precompile reverse transducer
    reverse_map: dict[str, str] = dict(reverse_preferred)
    for leg_k, uni_v in mappings.items():
        if uni_v:
            if uni_v not in reverse_map or (reverse_map[uni_v] == uni_v and leg_k != uni_v):
                reverse_map[uni_v] = leg_k
    for leg_k, uni_v in prefixes.items():
        if uni_v and uni_v not in reverse_map:
            reverse_map[uni_v] = leg_k

    sorted_uni = sorted(reverse_map.keys(), key=len, reverse=True)
    reverse_re = re.compile("|".join(re.escape(u) for u in sorted_uni)) if sorted_uni else None

    return LegacyFontProfile(
        profile_id=pid,
        family=family,
        name=name,
        aliases=tuple(aliases),
        prefixes=prefixes,
        postfix_reph=postfix_reph,
        reph_unicode=reph_unicode,
        mappings=mappings,
        post_corrections=post_corrections,
        schema_version=data.get("schema_version", "1.0.0"),
        symbols=symbols,
        reverse_preferred=reverse_preferred,
        family_corrections=family_corrections,
        detection_signatures=det_sigs,
        negative_signatures=neg_sigs,
        compiled_forward_regex=forward_re,
        compiled_reverse_regex=reverse_re,
        compiled_reverse_map=reverse_map,
    )


def load_font_profiles(fonts_dir: Path | None = None) -> dict[str, LegacyFontProfile]:
    """Load and strictly validate all font mapping profiles from data/fonts/."""
    target_dir = fonts_dir.resolve() if fonts_dir is not None else _CANONICAL_FONTS_DIR
    profiles: dict[str, LegacyFontProfile] = {}
    if not target_dir.exists():
        return profiles

    seen_ids: set[str] = set()
    seen_aliases: dict[str, str] = {}

    for json_file in sorted(target_dir.glob("*.json")):
        try:
            raw_text = json_file.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as exc:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Failed to read or parse font profile JSON: {json_file.name}",
            ) from exc

        if not isinstance(data, dict):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Font profile JSON in '{json_file.name}' must be an object.",
            )

        prof = _validate_and_compile_profile(data, json_file.name, seen_ids, seen_aliases)
        profiles[prof.profile_id] = prof

    return profiles


def resolve_profile_from_font_name(
    font_name: str | None,
    profiles: dict[str, LegacyFontProfile] | None = None,
) -> tuple[str | None, str | None]:
    """Separate trusted font resolution from text detection.

    Returns:
        (profile_id, family) if matched to a validated legacy font profile.
        (None, "modern") if recognized as a modern Unicode font.
        (None, "unknown") if unrecognized.
    """
    if not font_name or not font_name.strip():
        return None, None

    cleaned = "".join(c for c in font_name.lower() if c.isalnum())
    if not cleaned:
        return None, None

    if cleaned in _KNOWN_MODERN_FONTS:
        return None, "modern"

    if profiles is None:
        global _DEFAULT_PROFILES
        if _DEFAULT_PROFILES is None:
            _DEFAULT_PROFILES = load_font_profiles()
        profiles = _DEFAULT_PROFILES

    cleaned_base = re.sub(r"(normal|regular|bold|italic|oblique|medium)$", "", cleaned)

    # Check against registered profiles
    for prof in profiles.values():
        cand_keys = [prof.profile_id, prof.name] + list(prof.aliases)
        for cand in cand_keys:
            cand_clean = "".join(c for c in cand.lower() if c.isalnum())
            if cleaned == cand_clean or (cleaned_base and cleaned_base == cand_clean):
                return prof.profile_id, prof.family

    return None, "unknown"


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
        [profiles[p] for p in candidate_profiles if p in profiles]
        if candidate_profiles
        else list(profiles.values())
    )

    candidates: list[ConversionCandidate] = []

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
            # Check how many characters or tokens are covered by mappings
            tokens = text.split()
            for t in tokens:
                # If word has at least 2 chars of legacy mapping
                m_chars = len(prof.compiled_forward_regex.findall(t))
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
        if fam == "modern":
            return ConversionDecision(
                decision="preserve",
                reason="known_modern_unicode_font",
            )
        if resolved_prof is not None:
            if run_text and run_text.strip():
                cands = rank_profiles_from_text(run_text, profiles)
                cand = next((c for c in cands if c.profile_id == resolved_prof), None)
                if cand is not None:
                    if cand.negative_signatures or (not cand.is_structurally_valid and "COLLAPSED_CONSONANTS" in cand.structural_defects):
                        return ConversionDecision(
                            decision="preserve",
                            reason="conflicting_profile_evidence",
                        )
                    if len(run_text.strip()) >= 8 and not cand.positive_signatures and cand.mapped_token_count == 0:
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

    candidates = rank_profiles_from_text(run_text, profiles)
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


class LegacyFontDetector:
    """Detects legacy font encoding from text statistical properties and profile clues."""

    def __init__(self, fonts_dir: Path | None = None) -> None:
        self._profiles = load_font_profiles(fonts_dir)

    @classmethod
    def is_legacy_text(cls, text: str) -> bool:
        """Public evidence-based check whether text contains legacy Devanagari font signatures."""
        if not text or not text.strip():
            return False
        k_count = sum(1 for s in _KRUTI_SIGNATURES if s in text)
        c_count = sum(1 for s in _CHANAKYA_SIGNATURES if s in text)
        s_count = sum(1 for s in _SHUSHA_SIGNATURES if s in text)
        return (k_count >= 2) or (c_count >= 2) or (s_count >= 2)

    def is_legacy_font(self, text: str) -> bool:
        """Instance check whether text contains sufficient legacy font evidence."""
        return self.is_legacy_text(text)

    def detect(self, text: str, font_hint: str | None = None) -> tuple[str | None, float]:
        """Detect legacy font profile from font hint or actual text evidence."""
        if not text or not text.strip():
            return None, 0.0

        candidates = rank_profiles_from_text(text, self._profiles)
        cand_map = {c.profile_id: c for c in candidates}

        if font_hint:
            prof_id, fam = resolve_profile_from_font_name(font_hint, self._profiles)
            if fam == "modern" or prof_id is None:
                return None, 0.0

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
                if candidates and candidates[0].profile_id != prof_id and candidates[0].score >= 3.0 and cand.score <= 0:
                    return None, 0.0

                conf = max(0.8, min(1.0, 0.5 + len(cand.positive_signatures) * 0.1))
                return prof_id, conf

        if not self.is_legacy_text(text):
            return None, 0.0

        if not candidates or candidates[0].score < 2.0:
            return None, 0.0

        top = candidates[0]
        if len(candidates) > 1:
            margin = top.score - candidates[1].score
            p1 = self._profiles.get(top.profile_id)
            p2 = self._profiles.get(candidates[1].profile_id)
            if p1 and p2 and {p1.family, p2.family} == {"krutidev", "devlys"} and margin < 1.0:
                # Ambiguous: cannot distinguish KrutiDev from DevLys on text alone, default to krutidev010
                return "krutidev010", min(1.0, 0.5 + len(top.positive_signatures) * 0.1)

        conf = min(1.0, 0.5 + len(top.positive_signatures) * 0.1)
        return top.profile_id, conf


_NORMALIZED_FAMILY_CACHE: dict[str, str] = {}
_DEFAULT_PROFILES: dict[str, LegacyFontProfile] | None = None


def normalize_font_family_name(font_name: str | None, profiles: dict[str, LegacyFontProfile] | None = None) -> str:
    """Normalize a font name or family string to a canonical semantic identity."""
    if not font_name:
        return ""
    if profiles is None and font_name in _NORMALIZED_FAMILY_CACHE:
        return _NORMALIZED_FAMILY_CACHE[font_name]

    cleaned = "".join(c for c in font_name.lower() if c.isalnum())
    if not cleaned:
        return ""

    if profiles is None:
        global _DEFAULT_PROFILES
        if _DEFAULT_PROFILES is None:
            _DEFAULT_PROFILES = load_font_profiles()
        profiles = _DEFAULT_PROFILES

    for prof in profiles.values():
        cand_keys = [prof.profile_id, prof.family, prof.name] + list(prof.aliases)
        for cand in cand_keys:
            cand_cleaned = "".join(c for c in cand.lower() if c.isalnum())
            if cleaned == cand_cleaned:
                if profiles is _DEFAULT_PROFILES:
                    _NORMALIZED_FAMILY_CACHE[font_name] = prof.family
                return prof.family

    if profiles is _DEFAULT_PROFILES:
        _NORMALIZED_FAMILY_CACHE[font_name] = cleaned
    return cleaned
