"""Akshara-aware Legacy Font to Unicode Converter for Roopa."""

from __future__ import annotations

import re
import tomllib
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import ProvenanceRecord
from sarathi.shakti.font_conversion.akshara import (
    reorder_pre_base_matra_legacy,
    reorder_reph_unicode,
    synthesize_akshara_unicode,
)
from sarathi.shakti.font_conversion.detector import load_font_profiles
from sarathi.shakti.font_conversion.models import (
    FontConversionResult,
    LegacyFontProfile,
)
from sarathi.sutra import get_canonical_data_root

_CANONICAL_FONTS_DIR = get_canonical_data_root() / "fonts"
_CANONICAL_ANUBHAVA_PATH = get_canonical_data_root() / "font_conversion" / "anubhava.toml"

# Kruti/Remington legacy cluster regex pattern:
# Captures optional half-consonants (D, P, R, F, Y, O, L, C, H, E, U, I, x~, etc.) + base consonant + optional sub-ra ('z')
# In Remington: uppercase letters D, P, R, F, Y, O, L, C, H, E, U, I, X are half-consonants (क्, च्, त्, थ्, ल्, व्, स्, ब्, भ्, म्, न्, प्, ग्)
# Lowercase letters d, x, p, t, T, V, B, M, r, n, u, c, ;, j, y, o, ?, g, h, K, s, e are base consonants (क, ग, च, ज, झ, ट, ठ, ड, त, द, न, ब, य, र, ल, व, ?, घ, ह, ज्ञ, स, म)
_KRUTI_HALF_CONSONANTS = r"(?:[DPRFYOCLHUIX\xb6\xd9\x27\u2018\u2019\u201c\u201d]|E(?!$)|x~|\{|\&|J~|\.)"
_KRUTI_BASE_CONSONANTS = r"(?:\[k|\?k|Fk|/k|Hk|'k|\"k|\.k|\{k|[\u2018\u2019\u201c\u201d]k|\xd9k|[ldixptTVBMrnuc;jyo\?ghKsQeJK\xe7\xe4\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xfb\xfc\xfd\xfe=\}\xd8\)])"
_KRUTI_CONSONANT_CLUSTER = rf"(?:{_KRUTI_HALF_CONSONANTS})*{_KRUTI_BASE_CONSONANTS}z?"


class AnubhavaStore(dict[str, dict[str, str]]):
    """Structured container for multi-type Anubhava approved corrections."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pre_corrections: dict[str, dict[str, str]] = {}
        self.post_corrections: dict[str, dict[str, str]] = {}
        self.regex_corrections: list[tuple[re.Pattern[str], str]] = []


def _load_anubhava_corrections(anubhava_path: Path | None = None) -> AnubhavaStore:
    """Load and return approved corrections directly from capability-owned anubhava.toml."""
    path = (anubhava_path or _CANONICAL_ANUBHAVA_PATH).resolve()
    store = AnubhavaStore()
    if not path.exists():
        return store
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to parse font conversion Anubhava TOML: {path.name}",
        ) from exc

    for item in data.get("corrections", []):
        if not isinstance(item, dict) or not item.get("verified", False):
            continue
        pid = str(item.get("profile_id", "generic"))
        src = str(item.get("source", ""))
        tgt = str(item.get("target", ""))
        m_type = str(item.get("mapping_type", "")).strip().lower()

        if not src:
            continue

        # Standard dict mapping for backward compatibility
        store.setdefault(pid, {})[src] = tgt

        if m_type == "regex":
            try:
                pat = re.compile(src)
                store.regex_corrections.append((pat, tgt))
            except re.error:
                continue
        elif m_type == "post_conversion":
            store.post_corrections.setdefault(pid, {})[src] = tgt
        elif m_type == "pre_conversion":
            store.pre_corrections.setdefault(pid, {})[src] = tgt
        else:
            # Automatic classification if mapping_type is omitted
            is_indic_src = any(0x0900 <= ord(c) <= 0x0DFF for c in src)
            if is_indic_src:
                store.post_corrections.setdefault(pid, {})[src] = tgt
                store.pre_corrections.setdefault(pid, {})[src] = tgt
            else:
                store.pre_corrections.setdefault(pid, {})[src] = tgt

    return store


class FontConverter:
    """Converts legacy font text into canonical Unicode Devanagari."""

    def __init__(
        self,
        fonts_dir: Path | None = None,
        anubhava_path: Path | None = None,
        profiles: dict[str, LegacyFontProfile] | None = None,
    ) -> None:
        self._profiles = profiles if profiles is not None else load_font_profiles(fonts_dir)
        self._anubhava_corrections: AnubhavaStore = _load_anubhava_corrections(anubhava_path)

    @property
    def profiles(self) -> dict[str, LegacyFontProfile]:
        """Return the immutable mapping of loaded font profiles."""
        return self._profiles

    def convert_result(
        self,
        text: str,
        profile_id: str,
        original_text: str | None = None,
        confidence: float = 1.0,
        protected_spans_count: int = 0,
    ) -> FontConversionResult:
        """Apply declarative 7-pass legacy-to-Unicode transduction and capture telemetry metrics."""
        orig = text if original_text is None else original_text
        profile = self._profiles.get(profile_id)
        if profile is None:
            return FontConversionResult(
                converted_text=text,
                original_text=orig,
                detected_profile=None,
                confidence=0.0,
                protected_spans_count=protected_spans_count,
            )

        if text.strip() in (",", ",,", ",,,"):
            return FontConversionResult(
                converted_text=text,
                original_text=orig,
                detected_profile=profile_id,
                confidence=confidence,
                protected_spans_count=protected_spans_count,
            )

        cur_text = text
        replacement_ops = 0
        reorder_ops = 0

        # Pass 1: Canonicalize Duplicate Presentation Glyphs (profile-driven)
        if profile.canonicalization_rules:
            for src, tgt in profile.canonicalization_rules:
                if src in cur_text:
                    cnt = cur_text.count(src)
                    cur_text = cur_text.replace(src, tgt)
                    replacement_ops += cnt

        # Pass 2: Input Repair & Typist Artifacts
        generic_corrections = self._anubhava_corrections.pre_corrections.get("generic", {})
        for src, tgt in generic_corrections.items():
            if src in cur_text:
                cnt = cur_text.count(src)
                cur_text = cur_text.replace(src, tgt)
                replacement_ops += cnt

        profile_corrections = self._anubhava_corrections.pre_corrections.get(profile_id, {})
        for src, tgt in profile_corrections.items():
            if src in cur_text:
                cnt = cur_text.count(src)
                cur_text = cur_text.replace(src, tgt)
                replacement_ops += cnt

        # Pass 3: Context-Sensitive Rewrites
        active_context_rules = (
            profile.compiled_context_rules
            if profile.compiled_context_rules
            else tuple((re.compile(p), r) for p, r in profile.context_rules)
        )
        for pat, repl in active_context_rules:
            new_text, cnt = pat.subn(repl, cur_text)
            if cnt > 0:
                cur_text = new_text
                replacement_ops += cnt

        # Pass 4: Declarative Pre-Base Matra Reordering (zero family branching)
        if profile.prefixes:
            cluster_pat = (
                profile.cluster_pattern
                if profile.cluster_pattern
                else (_KRUTI_CONSONANT_CLUSTER if profile.family in ("krutidev", "devlys") else r"[^\s]")
            )
            for pfx, matra_uni in profile.prefixes.items():
                if pfx in cur_text:
                    before_reorder = cur_text
                    cur_text = reorder_pre_base_matra_legacy(
                        cur_text,
                        prefix_char=pfx,
                        matra_unicode=matra_uni,
                        consonant_chars_pattern=cluster_pat,
                    )
                    if cur_text != before_reorder:
                        reorder_ops += before_reorder.count(pfx)

        # Pass 5: Longest-Match Forward Mapping
        mapped_chars_count = 0
        unmapped_histogram: Counter[str] = Counter()
        if profile.compiled_forward_regex is not None:
            mapping = profile.mappings

            def _replace_match(m: re.Match[str]) -> str:
                nonlocal mapped_chars_count, replacement_ops
                matched_str = m.group(0)
                mapped_chars_count += len(matched_str)
                replacement_ops += 1
                return mapping[matched_str]

            mapped_text = profile.compiled_forward_regex.sub(_replace_match, cur_text)
            for c in cur_text:
                if c not in mapping and ord(c) >= 128:
                    unmapped_histogram[c] += 1
            cur_text = mapped_text

        # Pass 6: Postfix Reph Reordering
        reph_char = profile.postfix_reph
        reph_uni = profile.reph_unicode
        if reph_char and reph_char in cur_text:
            before_reph = cur_text
            cur_text = reorder_reph_unicode(cur_text, reph_marker=reph_char, reph_unicode=reph_uni)
            if cur_text != before_reph:
                reorder_ops += before_reph.count(reph_char)

        # Pass 7: Unicode NFC Normalization, Post-corrections, & Joiner Policy
        for src, tgt in profile.post_corrections:
            if src in cur_text:
                cnt = cur_text.count(src)
                cur_text = cur_text.replace(src, tgt)
                replacement_ops += cnt
            elif any(ch in src for ch in ("\\", "(", "[", "?", "^", "$")):
                try:
                    new_text, cnt = re.subn(src, tgt, cur_text)
                    if cnt > 0:
                        cur_text = new_text
                        replacement_ops += cnt
                except re.error:
                    pass

        for src, tgt in profile.family_corrections:
            if src in cur_text:
                cnt = cur_text.count(src)
                cur_text = cur_text.replace(src, tgt)
                replacement_ops += cnt
            elif any(ch in src for ch in ("\\", "(", "[", "?", "^", "$")):
                try:
                    new_text, cnt = re.subn(src, tgt, cur_text)
                    if cnt > 0:
                        cur_text = new_text
                        replacement_ops += cnt
                except re.error:
                    pass

        generic_post = self._anubhava_corrections.post_corrections.get("generic", {})
        for src, tgt in generic_post.items():
            if src in cur_text:
                cnt = cur_text.count(src)
                cur_text = cur_text.replace(src, tgt)
                replacement_ops += cnt

        profile_post = self._anubhava_corrections.post_corrections.get(profile_id, {})
        for src, tgt in profile_post.items():
            if src in cur_text:
                cnt = cur_text.count(src)
                cur_text = cur_text.replace(src, tgt)
                replacement_ops += cnt

        for pat, repl in self._anubhava_corrections.regex_corrections:
            new_text, cnt = pat.subn(repl, cur_text)
            if cnt > 0:
                cur_text = new_text
                replacement_ops += cnt

        cur_text = synthesize_akshara_unicode(cur_text)

        # Presentation joiner policy: preserve eyelash Ra (र्\u200d) only
        cur_text = re.sub(r"(?<!\u0930\u094d)\u200d", "", cur_text)
        cur_text = re.sub(r"\u200c(?!\w)", "", cur_text)

        final_text = unicodedata.normalize("NFC", cur_text)

        provenance = (
            ProvenanceRecord(
                stage="font_conversion",
                evidence={
                    "profile_id": profile_id,
                    "mapped_chars_count": mapped_chars_count,
                    "replacement_operations": replacement_ops,
                    "reorder_operations": reorder_ops,
                    "unmapped_symbols_histogram": dict(unmapped_histogram),
                },
            ),
        )

        return FontConversionResult(
            converted_text=final_text,
            original_text=orig,
            detected_profile=profile_id,
            confidence=confidence,
            protected_spans_count=protected_spans_count,
            provenance=provenance,
            mapped_chars_count=mapped_chars_count,
            replacement_operations=replacement_ops,
            reorder_operations=reorder_ops,
            unmapped_symbols_histogram=dict(unmapped_histogram),
        )

    def convert(self, text: str, profile_id: str) -> str:
        """Apply legacy-to-Unicode mapping, profile-specific pre-base matra reordering, and Akshara synthesis."""
        result = self.convert_result(text, profile_id=profile_id)
        return result.converted_text

    def convert_to_legacy(self, text: str, target_profile_id: str = "krutidev010") -> str:
        """Convert standard Unicode Devanagari text into legacy font encoding using precompiled reverse transducers."""
        pid = target_profile_id.lower().strip()
        profile = self._profiles.get(pid)
        if profile is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Requested target font profile is not supported or loaded: {target_profile_id!r}",
            )

        norm_text = unicodedata.normalize("NFC", text)

        # 1. Handle pre-base choti-i matra 'ि': in Unicode it follows consonant, in Kruti it precedes
        norm_text = re.sub(r"((?:[क-ह]्)*[क-ह])ि", r"f\1", norm_text)

        # 2. Handle reph 'र्': in Unicode it precedes consonant, in Kruti/DevLys 'Z' follows
        norm_text = re.sub(r"र्((?:[क-ह]्)*[क-ह](?:[ाीुूेैोौ]|ं|ँ)?)", r"\1Z", norm_text)

        # 3. Apply precompiled reverse mapping (Unicode -> Legacy)
        if profile.compiled_reverse_regex is not None:
            rev_map = profile.compiled_reverse_map
            norm_text = profile.compiled_reverse_regex.sub(lambda m: rev_map[m.group(0)], norm_text)

        return norm_text

    def reverse_convert(self, text: str, target_profile_id: str = "krutidev010") -> str:
        """Alias for convert_to_legacy."""
        return self.convert_to_legacy(text, target_profile_id=target_profile_id)
