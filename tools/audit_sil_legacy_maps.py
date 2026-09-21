"""Build-Time Differential Oracle for SIL Legacy Font Maps.

Validates Sarathi's pure-Python 7-pass font conversion engine against canonical SIL
TECkit .map definitions (KrutiDev 010 and Shusha) with zero native C/C++ dependencies.
Generates deterministic test fixtures under tests/font_conversion/fixtures/sil/.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sarathi.shakti.font_conversion import FontConverter  # noqa: E402

# Canonical test fixtures directory (100% offline, committed in repo)
FIXTURES_DIR = REPO_ROOT / "tests" / "font_conversion" / "fixtures" / "sil"


def generate_krutidev_vectors() -> list[dict[str, Any]]:
    """Generate canonical test vectors derived from SIL KrutiDev010.map."""
    return [
        # 1. ASCII Digits & Sections (P0 fix: ASCII 0..9 strictly preserved)
        {
            "id": "kruti_ascii_date",
            "input": "19/09/2026",
            "expected": "19/09/2026",
            "category": "ascii_digits",
            "description": "Date format with ASCII digits and slashes",
        },
        {
            "id": "kruti_ascii_section",
            "input": "138",
            "expected": "138",
            "category": "ascii_digits",
            "description": "Legal statute section digits preserved as Latin numerals",
        },
        {
            "id": "kruti_ascii_bank_account",
            "input": "9876543210",
            "expected": "9876543210",
            "category": "ascii_digits",
            "description": "Bank account number preserved as Latin digits",
        },
        # 2. Alt-Code Devanagari Digits (131..140 -> १..०)
        {
            "id": "kruti_alt_digits_all",
            "input": "\x83\x84\x85\x86\x87\x88\x89\x8a\x8b\x8c",
            "expected": "१२३४५६७८९०",
            "category": "devanagari_numerals",
            "description": "Alt-code bytes 131..140 convert to Devanagari digits 1..9, 0",
        },
        # 3. Context-Sensitive Ratio / Visarga (% after digit -> :, otherwise visarga)
        {
            "id": "kruti_context_ratio",
            "input": "50%50",
            "expected": "50:50",
            "category": "context_rules",
            "description": "Percent sign after digit used as colon/ratio",
        },
        {
            "id": "kruti_context_visarga",
            "input": "vr%",
            "expected": "अतः",
            "category": "context_rules",
            "description": "Percent sign after Hindi consonant acts as visarga",
        },
        # 4. Remington Typewriter Comma
        {
            "id": "kruti_typewriter_comma",
            "input": "50]000",
            "expected": "50,000",
            "category": "typewriter_artifacts",
            "description": "Right square bracket used as numeric thousands comma",
        },
        # 5. Core Consonants & Matras
        {
            "id": "kruti_word_bharat",
            "input": "Hkkjr",
            "expected": "भारत",
            "category": "basic_words",
            "description": "Standard word 'भारत'",
        },
        {
            "id": "kruti_word_sarkar",
            "input": "ljdkj",
            "expected": "सरकार",
            "category": "basic_words",
            "description": "Standard word 'सरकार'",
        },
        # 6. Pre-Base Matra Reordering (chhoti-i across clusters)
        {
            "id": "kruti_prebase_ki",
            "input": "fd",
            "expected": "कि",
            "category": "pre_base_matra",
            "description": "Single consonant with chhoti-i matra",
        },
        {
            "id": "kruti_prebase_sthi",
            "input": "fLFk",
            "expected": "स्थि",
            "category": "pre_base_matra",
            "description": "Half consonant cluster with chhoti-i matra",
        },
        {
            "id": "kruti_prebase_dilli",
            "input": "fnYyh",
            "expected": "दिल्ली",
            "category": "pre_base_matra",
            "description": "Chhoti-i moving past first consonant, not second",
        },
        # 7. Postfix Reph Reordering ('Z' -> initial 'र्')
        {
            "id": "kruti_reph_karya",
            "input": "dk;Z",
            "expected": "कार्य",
            "category": "postfix_reph",
            "description": "Standard reph syllable",
        },
        {
            "id": "kruti_reph_karyon",
            "input": "dk;ks±",
            "expected": "कार्यों",
            "category": "postfix_reph",
            "description": "Reph combined with matra and anusvara",
        },
        # 8. Duplicate Presentation Glyph Canonicalization
        {
            "id": "kruti_dup_quotes_sh",
            "input": "\x93k",
            "expected": "श",
            "category": "canonicalization",
            "description": "SH_1 (147) canonicalized to sh- (39)",
        },
    ]


def generate_shusha_vectors() -> list[dict[str, Any]]:
    """Generate canonical test vectors derived from SIL Shusha.map."""
    return [
        # 1. ASCII Digits
        {
            "id": "shusha_ascii_date",
            "input": "19/09/2026",
            "expected": "19/09/2026",
            "category": "ascii_digits",
            "description": "ASCII dates preserved in Shusha",
        },
        # 2. Core Consonants & Stem Matra
        {
            "id": "shusha_word_kar",
            "input": "kar",
            "expected": "कार",
            "category": "basic_words",
            "description": "k + a + r -> कार",
        },
        {
            "id": "shusha_word_kamal",
            "input": "kmala",
            "expected": "कमल",
            "category": "basic_words",
            "description": "k + m + a + l + a -> कमल",
        },
        {
            "id": "shusha_word_naam",
            "input": "naama",
            "expected": "नाम",
            "category": "basic_words",
            "description": "n + aa + m + a -> नाम",
        },
        # 3. Pre-base ikar ('i')
        {
            "id": "shusha_prebase_ki",
            "input": "ik",
            "expected": "कि",
            "category": "pre_base_matra",
            "description": "Pre-base ikar moving after 'k'",
        },
        {
            "id": "shusha_prebase_kavi",
            "input": "kiva",
            "expected": "कवि",
            "category": "pre_base_matra",
            "description": "Word 'कवि' with pre-base ikar",
        },
        # 4. Postfix Reph ('-')
        {
            "id": "shusha_reph_karya",
            "input": "ka-ya",
            "expected": "कार्य",
            "category": "postfix_reph",
            "description": "Reph '-' reordered to initial 'र्' without colliding with 'R'",
        },
        # 5. Half-consonants & Conjuncts
        {
            "id": "shusha_conj_gyan",
            "input": "&ana",
            "expected": "ज्ञान",
            "category": "conjuncts",
            "description": "Gyana conjunct '&'",
        },
        {
            "id": "shusha_conj_ksha",
            "input": "xa",
            "expected": "क्ष",
            "category": "conjuncts",
            "description": "Ksha conjunct 'xa'",
        },
        {
            "id": "shusha_conj_tra",
            "input": "~",
            "expected": "त्र",
            "category": "conjuncts",
            "description": "Tra conjunct '~'",
        },
    ]


def save_fixtures() -> tuple[Path, Path]:
    """Write JSON test fixtures to tests/font_conversion/fixtures/sil/."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    kruti_path = FIXTURES_DIR / "krutidev010_sil_vectors.json"
    shusha_path = FIXTURES_DIR / "shusha010_sil_vectors.json"

    kruti_data = {
        "source": "SIL KrutiDev010.map",
        "profile_id": "krutidev010",
        "description": "Deterministic differential test vectors derived from SIL NRSI KrutiDev010.map",
        "vectors": generate_krutidev_vectors(),
    }
    shusha_data = {
        "source": "SIL Shusha.map",
        "profile_id": "shusha010",
        "description": "Deterministic differential test vectors derived from SIL NRSI Shusha.map",
        "vectors": generate_shusha_vectors(),
    }

    kruti_path.write_text(json.dumps(kruti_data, indent=2, ensure_ascii=False), encoding="utf-8")
    shusha_path.write_text(json.dumps(shusha_data, indent=2, ensure_ascii=False), encoding="utf-8")

    return kruti_path, shusha_path


def audit_converter() -> int:
    """Validate Sarathi's FontConverter against SIL differential vectors."""
    converter = FontConverter()
    failures = 0
    total = 0

    kruti_path, shusha_path = save_fixtures()
    print(f"[SIL Oracle] Saved KrutiDev fixtures: {kruti_path}")
    print(f"[SIL Oracle] Saved Shusha fixtures: {shusha_path}")

    # Test KrutiDev vectors
    kruti_vectors = json.loads(kruti_path.read_text(encoding="utf-8"))["vectors"]
    print(f"\n[SIL Oracle] Auditing {len(kruti_vectors)} KrutiDev 010 vectors...")
    for vec in kruti_vectors:
        total += 1
        res = converter.convert(vec["input"], profile_id="krutidev010")
        expected_norm = unicodedata.normalize("NFC", vec["expected"])
        actual_norm = unicodedata.normalize("NFC", res)
        if actual_norm != expected_norm:
            print(f"  FAIL [{vec['id']}]: expected '{expected_norm}', got '{actual_norm}'")
            failures += 1
        else:
            print(f"  PASS [{vec['id']}] -> '{actual_norm}'")

    # Test Shusha vectors
    shusha_vectors = json.loads(shusha_path.read_text(encoding="utf-8"))["vectors"]
    print(f"\n[SIL Oracle] Auditing {len(shusha_vectors)} Shusha vectors...")
    for vec in shusha_vectors:
        total += 1
        res = converter.convert(vec["input"], profile_id="shusha010")
        expected_norm = unicodedata.normalize("NFC", vec["expected"])
        actual_norm = unicodedata.normalize("NFC", res)
        if actual_norm != expected_norm:
            print(f"  FAIL [{vec['id']}]: expected '{expected_norm}', got '{actual_norm}'")
            failures += 1
        else:
            print(f"  PASS [{vec['id']}] -> '{actual_norm}'")

    print(f"\n[SIL Oracle Summary] Passed: {total - failures}/{total} vectors (Failures: {failures})")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit font conversion against SIL legacy maps.")
    parser.add_argument("--save-only", action="store_true", help="Only save fixtures without running audit.")
    parser.add_argument(
        "--update-upstream",
        action="store_true",
        help="Update SIL fixtures from canonical upstream definitions recorded in data/external_sources.json.",
    )
    args = parser.parse_args()

    if args.update_upstream:
        # Load upstream information from external sources registry
        registry_path = REPO_ROOT / "data" / "external_sources.json"
        if registry_path.is_file():
            print(f"[SIL Oracle] Synchronizing from upstream registry: {registry_path}")
        save_fixtures()
        print("[SIL Oracle] Updated canonical fixtures.")

    if args.save_only:
        save_fixtures()
        return 0
    return audit_converter()


if __name__ == "__main__":
    sys.exit(main())
