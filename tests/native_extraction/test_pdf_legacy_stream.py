"""Unit and integration tests for stream-order ingestion, font-run arbitration, and MacRoman normalization."""

from __future__ import annotations

import pymupdf
import pytest

from sarathi.shakti.font_conversion.byte_normalizer import (
    has_macroman_signatures,
    is_macroman_text,
    normalize_macroman_bytes,
)
from sarathi.shakti.font_conversion.detector import (
    decide_run_profile,
    load_font_profiles,
    resolve_profile_from_font_name,
)
from sarathi.shakti.native_extraction.readers.pdf import read_pdf

# ---------------------------------------------------------------------------
# Part 1: Byte Normalizer Unit Tests
# ---------------------------------------------------------------------------


def test_byte_normalizer_signature_detection() -> None:
    """Verify diagnostic MacRoman signature characters are detected accurately."""
    assert has_macroman_signatures("\u2044U\u00ca\u00a1S\u00d5\u00ca\u0178") is True
    assert is_macroman_text("Regular Latin text") is False
    assert is_macroman_text("Hkkjr ljdkj") is False
    assert is_macroman_text("भारत सरकार") is False
    assert is_macroman_text("") is False


def test_byte_normalizer_inversion() -> None:
    """Verify MacRoman-encoded bytes are inverted back to Windows-1252 representation."""
    # MacRoman string with fraction slash ⁄ (0xDA) and Y with diaeresis Ÿ (0xD9)
    mac_sample = "\u2044U\u00ca\u00a1S\u00d5\u00ca\u0178"
    normalized = normalize_macroman_bytes(mac_sample)
    # Encoded bytes in MacRoman: [0xDA, 0x55, 0xE6, 0xC1, 0x53, 0xCD, 0xE6, 0xD9]
    # In Windows-1252: Ú (0xDA), U (0x55), æ (0xE6), Á (0xC1), S (0x53), Í (0xCD), æ (0xE6), Ù (0xD9)
    assert normalized.encode("cp1252") == b"\xdaU\xe6\xc1S\xcd\xe6\xd9"

    # Idempotent for normal text
    assert normalize_macroman_bytes("Hello World") == "Hello World"
    assert normalize_macroman_bytes("भारत सरकार") == "भारत सरकार"
    assert normalize_macroman_bytes("") == ""


# ---------------------------------------------------------------------------
# Part 2: Font-Run Arbitration Tests
# ---------------------------------------------------------------------------


def test_font_resolution_known_categories() -> None:
    """Verify resolution of modern Indic, standard Latin, and legacy font categories."""
    profiles = load_font_profiles()

    # Modern Unicode Indic fonts
    assert resolve_profile_from_font_name("Mangal", profiles) == (None, "modern")
    assert resolve_profile_from_font_name("Nirmala UI", profiles) == (None, "modern")
    assert resolve_profile_from_font_name("NotoSansDevanagari-Regular", profiles) == (None, "modern")

    # Standard Latin fonts
    assert resolve_profile_from_font_name("Times New Roman", profiles) == (None, "modern")
    assert resolve_profile_from_font_name("Calibri-Bold", profiles) == (None, "modern")
    assert resolve_profile_from_font_name("Arial", profiles) == (None, "modern")

    # Supported legacy fonts
    p_id, fam = resolve_profile_from_font_name("Kruti Dev 010", profiles)
    assert p_id == "krutidev010" and fam == "krutidev"

    p_id, fam = resolve_profile_from_font_name("DevLys 010", profiles)
    assert p_id == "devlys010" and fam == "devlys"

    # Unsupported legacy fonts (fail-closed invariant)
    assert resolve_profile_from_font_name("AkrutiDev01", profiles) == (None, "unsupported_legacy")
    assert resolve_profile_from_font_name("AjantaNormal", profiles) == (None, "unsupported_legacy")
    assert resolve_profile_from_font_name("ShreeLipi-001", profiles) == (None, "unsupported_legacy")


def test_decide_run_profile_arbitration() -> None:
    """Verify fail-closed arbitration decisions."""
    profiles = load_font_profiles()

    # Modern and Latin fonts must be preserved verbatim even with ambiguous text
    dec_latin = decide_run_profile("Times New Roman", "rail case thou vkSj", profiles=profiles)
    assert dec_latin.decision == "preserve"
    assert dec_latin.reason == "known_modern_unicode_font"

    dec_modern = decide_run_profile("Mangal", "भारत सरकार", profiles=profiles)
    assert dec_modern.decision == "preserve"
    assert dec_modern.reason == "known_modern_unicode_font"

    # Supported legacy font converts
    dec_kd = decide_run_profile("Kruti Dev 010", "Hkkjr ljdkj", profiles=profiles)
    assert dec_kd.decision == "convert"
    assert dec_kd.profile == "krutidev010"

    # Unsupported legacy font fails-closed (no conversion, warning reason)
    dec_unsupp = decide_run_profile("AkrutiDev01", "some text", profiles=profiles)
    assert dec_unsupp.decision == "preserve"
    assert dec_unsupp.reason == "unsupported_legacy_font"


# ---------------------------------------------------------------------------
# Part 3: Stream-Order Ingestion & Pipeline Inversion Tests in read_pdf
# ---------------------------------------------------------------------------


def test_stream_order_preservation_elevated_matra(tmp_path: pytest.TempPathFactory) -> None:
    """Validate that stream-order ingestion preserves keystroke sequence (vkSj -> और), preventing spatial sort jumbling."""
    pdf_path = tmp_path / "stream_order_sample.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)

    # Insert keystrokes in typing stream order:
    # "vk" at (100, 100), "S" (elevated matra) at (109, 94), "j" at (115, 100)
    page.insert_text((100, 100), "vk")
    page.insert_text((109, 94), "S")
    page.insert_text((115, 100), "j")

    fonts = doc_pdf.get_page_fonts(0)
    if fonts:
        doc_pdf.xref_set_key(fonts[0][0], "BaseFont", "/ABCDEF+KrutiDev010")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    doc, provs, warns = read_pdf(pdf_path.read_bytes(), "inp-stream-1", convert_legacy_fonts=True)

    # In KrutiDev, "vkSj" is "और" (\u0914\u0930).
    # If spatially jumbled into "vkjS", it would produce "आरै" (\u0906\u0930\u0948).
    assert "और" in doc.text or (doc.pages and "और" in doc.pages[0].text)
    assert "आरै" not in doc.text

    # Provenance record for font conversion must be emitted
    conv_prov = [p for p in provs if p.capability_id == "font_conversion"]
    assert len(conv_prov) == 1
    assert conv_prov[0].stage == "convert_legacy_fonts"
    assert "krutidev010" in conv_prov[0].evidence.get("profile", [])


def test_pdf_font_arbitration_latin_preserved(tmp_path: pytest.TempPathFactory) -> None:
    """Validate that known Latin fonts are preserved without false-positive legacy conversion."""
    pdf_path = tmp_path / "latin_doc.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    latin_text = "The railway station and court case Section 138"
    page.insert_text((72, 72), latin_text)

    fonts = doc_pdf.get_page_fonts(0)
    if fonts:
        doc_pdf.xref_set_key(fonts[0][0], "BaseFont", "/TimesNewRomanPSMT")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    doc, provs, warns = read_pdf(pdf_path.read_bytes(), "inp-latin-1", convert_legacy_fonts=True)

    assert latin_text in doc.text
    conv_prov = [p for p in provs if p.capability_id == "font_conversion"]
    assert len(conv_prov) == 0


def test_pdf_font_arbitration_unsupported_legacy_warning(tmp_path: pytest.TempPathFactory) -> None:
    """Validate that unsupported legacy fonts are preserved with UNSUPPORTED_LEGACY_FONT warning."""
    pdf_path = tmp_path / "unsupported_legacy.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    raw_text = "Akruti sample unmapped text"
    page.insert_text((72, 72), raw_text)

    fonts = doc_pdf.get_page_fonts(0)
    if fonts:
        doc_pdf.xref_set_key(fonts[0][0], "BaseFont", "/AkrutiDev01-Regular")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    doc, provs, warns = read_pdf(pdf_path.read_bytes(), "inp-unsupp-1", convert_legacy_fonts=True)

    # Text must be preserved without corrupting
    assert raw_text in doc.text
    # Warning must be emitted
    unsupp_warns = [w for w in warns if w.code == "UNSUPPORTED_LEGACY_FONT"]
    assert len(unsupp_warns) >= 1
    # No conversion provenance
    conv_prov = [p for p in provs if p.capability_id == "font_conversion"]
    assert len(conv_prov) == 0
