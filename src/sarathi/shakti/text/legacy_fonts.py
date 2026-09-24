"""Canonical legacy font profiles, profile loader, and font name resolver.

Low-level infrastructure shared across shakti capabilities and exporters
without circular package dependencies.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.text.legacy_detection import _KNOWN_MODERN_FONTS
from sarathi.sutra import get_canonical_data_root

try:
    from rapidfuzz import fuzz

    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

_CANONICAL_FONTS_DIR: Path = get_canonical_data_root() / "fonts"

_KNOWN_LATIN_FONTS: frozenset[str] = frozenset(
    {
        "arial",
        "calibri",
        "timesnewroman",
        "times",
        "cambria",
        "georgia",
        "verdana",
        "tahoma",
        "couriernew",
        "courier",
        "segoeui",
        "segoe",
        "helvetica",
        "trebuchetms",
        "trebuchet",
        "bookmanoldstyle",
        "bookman",
        "garamond",
        "centurygothic",
        "poppins",
        "inter",
        "roboto",
        "opensans",
        "dejavusans",
        "dejavuserif",
        "freesans",
        "liberationsans",
        "liberationserif",
    }
)

_KNOWN_MODERN_INDIC_FONTS: frozenset[str] = frozenset(
    {
        "mangal",
        "nirmalaui",
        "nirmala",
        "aparajita",
        "kokila",
        "utsaah",
        "gautami",
        "latha",
        "shruti",
        "notosansdevanagari",
        "notosans",
        "notoserifdevanagari",
        "notoserif",
        "lohitdevanagari",
        "lohit",
        "kalimati",
        "raghu",
    }
)

_KNOWN_UNSUPPORTED_LEGACY_FONTS: frozenset[str] = frozenset(
    {
        "akruti",
        "ajanta",
        "walkmanchanakya",
        "shree",
        "shreelipi",
        "aps",
        "dvb",
        "sulekh",
        "kanak",
        "hemraj",
        "jagran",
        "bhaskar",
        "panbilingual",
        "agra",
        "alolika",
        "anand",
        "amrit",
    }
)


@dataclass(frozen=True, slots=True)
class LegacyFontProfile:
    """Configuration and mappings for a legacy font encoding profile."""

    profile_id: str
    family: str
    name: str
    aliases: tuple[str, ...]
    prefixes: Mapping[str, str]
    postfix_reph: str
    reph_unicode: str
    mappings: Mapping[str, str]
    post_corrections: tuple[tuple[str, str], ...] = ()
    schema_version: str = "1.0.0"
    symbols: Mapping[str, str] | None = None
    reverse_preferred: Mapping[str, str] | None = None
    family_corrections: tuple[tuple[str, str], ...] = ()
    detection_signatures: tuple[str, ...] = ()
    negative_signatures: tuple[str, ...] = ()
    canonicalization_rules: tuple[tuple[str, str], ...] = ()
    context_rules: tuple[tuple[str, str], ...] = ()
    preserve_ascii_digits: bool = True
    cluster_pattern: str = ""
    compiled_forward_regex: Any = None
    compiled_reverse_regex: Any = None
    compiled_reverse_map: Mapping[str, str] | None = None
    compiled_context_rules: tuple[tuple[re.Pattern[str], str], ...] = ()


def _validate_and_compile_profile(
    data: dict, source_name: str, seen_ids: set[str], seen_aliases: dict[str, str]
) -> LegacyFontProfile:
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
        tuple(c) for c in data.get("post_corrections", ()) if isinstance(c, (list, tuple)) and len(c) == 2
    )
    family_corrections = tuple(
        tuple(c) for c in data.get("family_corrections", ()) if isinstance(c, (list, tuple)) and len(c) == 2
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

    canonicalization_rules = tuple(
        tuple(c) for c in data.get("canonicalization_rules", ()) if isinstance(c, (list, tuple)) and len(c) == 2
    )
    context_rules = tuple(
        tuple(c) for c in data.get("context_rules", ()) if isinstance(c, (list, tuple)) and len(c) == 2
    )
    compiled_context_rules = tuple(
        (re.compile(pat_str), repl) for pat_str, repl in context_rules
    )
    preserve_ascii_digits = bool(data.get("preserve_ascii_digits", True))
    cluster_pattern = str(data.get("cluster_pattern", ""))

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
        canonicalization_rules=canonicalization_rules,
        context_rules=context_rules,
        preserve_ascii_digits=preserve_ascii_digits,
        cluster_pattern=cluster_pattern,
        compiled_forward_regex=forward_re,
        compiled_reverse_regex=reverse_re,
        compiled_reverse_map=reverse_map,
        compiled_context_rules=compiled_context_rules,
    )


def _merge_profile_data(base: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a base profile dictionary with a child delta profile."""
    merged = dict(base)
    merged["abstract"] = child.get("abstract", False)
    for key, val in child.items():
        if key in ("extends", "abstract"):
            continue
        if key in ("mappings", "symbols", "reverse_preferred", "prefixes"):
            base_dict = dict(merged.get(key, {}))
            base_dict.update(val)
            merged[key] = base_dict
        elif key in ("post_corrections", "family_corrections", "canonicalization_rules", "context_rules"):
            base_list = list(merged.get(key, []))
            existing = {tuple(x) if isinstance(x, (list, tuple)) else x for x in base_list}
            for item in val:
                t_item = tuple(item) if isinstance(item, (list, tuple)) else item
                if t_item not in existing:
                    base_list.append(item)
                    existing.add(t_item)
            merged[key] = base_list
        elif key in ("aliases", "detection_signatures", "negative_signatures"):
            base_list = list(merged.get(key, []))
            for item in val:
                if item not in base_list:
                    base_list.append(item)
            merged[key] = base_list
        else:
            merged[key] = val
    return merged


def _resolve_profile_inheritance(
    pid: str,
    raw_profiles: dict[str, tuple[dict[str, Any], str]],
    resolved: dict[str, dict[str, Any]],
    visiting: set[str],
) -> dict[str, Any]:
    """Recursively resolve 'extends' profile inheritance."""
    if pid in resolved:
        return resolved[pid]
    if pid in visiting:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Cyclic font profile inheritance detected: {pid}",
        )
    visiting.add(pid)
    data, fname = raw_profiles[pid]
    parent_id = data.get("extends")
    if parent_id:
        if parent_id not in raw_profiles:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Font profile '{pid}' in '{fname}' extends unknown base profile '{parent_id}'.",
            )
        parent_data = _resolve_profile_inheritance(parent_id, raw_profiles, resolved, visiting)
        final_data = _merge_profile_data(parent_data, data)
    else:
        final_data = dict(data)

    visiting.remove(pid)
    resolved[pid] = final_data
    return final_data


def load_font_profiles(fonts_dir: Path | None = None) -> dict[str, LegacyFontProfile]:
    """Load, inherit, and strictly validate all font mapping profiles from data/fonts/."""
    target_dir = fonts_dir.resolve() if fonts_dir is not None else _CANONICAL_FONTS_DIR
    profiles: dict[str, LegacyFontProfile] = {}
    if not target_dir.exists():
        return profiles

    raw_profiles: dict[str, tuple[dict[str, Any], str]] = {}
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

        pid = str(data.get("profile_id", "")).strip().lower()
        if not pid:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Missing required 'profile_id' in font profile JSON: {json_file.name}",
            )
        raw_profiles[pid] = (data, json_file.name)

    # Resolve inheritance
    resolved_profiles: dict[str, dict[str, Any]] = {}
    for pid in raw_profiles:
        _resolve_profile_inheritance(pid, raw_profiles, resolved_profiles, set())

    seen_ids: set[str] = set()
    seen_aliases: dict[str, str] = {}

    for pid in sorted(resolved_profiles.keys()):
        data = resolved_profiles[pid]
        if data.get("abstract", False):
            continue  # Abstract base template, do not register as active runtime profile
        fname = raw_profiles[pid][1]
        prof = _validate_and_compile_profile(data, fname, seen_ids, seen_aliases)
        profiles[prof.profile_id] = prof

    return profiles


_DEFAULT_PROFILES: dict[str, LegacyFontProfile] | None = None


def resolve_profile_from_font_name(
    font_name: str | None,
    profiles: dict[str, LegacyFontProfile] | None = None,
) -> tuple[str | None, str | None]:
    """Separate trusted font resolution from text detection.

    Returns:
        (profile_id, family) if matched to a validated legacy font profile.
        (None, "modern") if recognized as a modern Unicode Indic font.
        (None, "latin") if recognized as a standard Latin font.
        (None, "unsupported_legacy") if recognized as a legacy Indic font without a mapped profile.
        (None, "unknown") if unrecognized.
    """
    if not font_name or not font_name.strip():
        return None, None

    raw_name = font_name.strip()
    if "+" in raw_name:
        parts = raw_name.split("+", 1)
        if len(parts[0]) == 6 and parts[0].isalpha() and parts[1].strip():
            raw_name = parts[1].strip()
        elif parts[1].strip():
            raw_name = parts[1].strip()

    cleaned = "".join(c for c in raw_name.lower() if c.isalnum())
    if not cleaned:
        return None, None

    cleaned_base = re.sub(r"(normal|regular|bold|italic|oblique|medium|truetype|opentype|type1|tt)$", "", cleaned)

    # 1. Check known modern Unicode Indic and Latin fonts
    if (
        cleaned in _KNOWN_MODERN_INDIC_FONTS
        or (cleaned_base and cleaned_base in _KNOWN_MODERN_INDIC_FONTS)
        or cleaned in _KNOWN_LATIN_FONTS
        or (cleaned_base and cleaned_base in _KNOWN_LATIN_FONTS)
        or cleaned in _KNOWN_MODERN_FONTS
        or (cleaned_base and cleaned_base in _KNOWN_MODERN_FONTS)
    ):
        return None, "modern"

    if profiles is None:
        global _DEFAULT_PROFILES
        if _DEFAULT_PROFILES is None:
            _DEFAULT_PROFILES = load_font_profiles()
        profiles = _DEFAULT_PROFILES

    # 4. Check against registered profiles
    for prof in profiles.values():
        cand_keys = [prof.profile_id, prof.name] + list(prof.aliases)
        for cand in cand_keys:
            cand_clean = "".join(c for c in cand.lower() if c.isalnum())
            if cleaned == cand_clean or (cleaned_base and cleaned_base == cand_clean):
                return prof.profile_id, prof.family

    # 5. Check known unsupported legacy Indic fonts (fail-closed before fuzzy matching)
    for unsupp in _KNOWN_UNSUPPORTED_LEGACY_FONTS:
        if cleaned.startswith(unsupp) or (cleaned_base and cleaned_base.startswith(unsupp)):
            return None, "unsupported_legacy"

    # 6. Fuzzy matching for noisy Word font names (e.g. "Shusha02_Normal", "KrutiDev-010-Rev")
    if _HAS_RAPIDFUZZ and len(cleaned) >= 5:
        best_match = None
        best_score = 0.0
        target = cleaned_base if cleaned_base else cleaned
        for prof in profiles.values():
            cand_keys = [prof.profile_id, prof.name] + list(prof.aliases)
            for cand in cand_keys:
                cand_clean = "".join(c for c in cand.lower() if c.isalnum())
                if not cand_clean:
                    continue
                score = max(fuzz.ratio(cleaned, cand_clean), fuzz.ratio(target, cand_clean))
                if score > best_score and score >= 85.0:
                    best_score = score
                    best_match = (prof.profile_id, prof.family)
        if best_match:
            return best_match

    return None, "unknown"


__all__ = [
    "LegacyFontProfile",
    "load_font_profiles",
    "resolve_profile_from_font_name",
]
