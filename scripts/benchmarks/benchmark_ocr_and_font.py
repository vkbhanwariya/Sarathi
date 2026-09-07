"""Comprehensive Baseline Measurement Harness for OCR and Font Conversion.

Measures:
1. OCR: Cold vs warm latency, 150/200/300 DPI accuracy and memory, preprocessing impact,
   character filtering data loss, and Tesseract cross-engine confidence vs ground truth.
2. Font Conversion: Sub-stage latency, DOCX double-conversion overhead, repeated protection
   integrity, split-matra order dependence, and Devanagari structural defects.
"""

from __future__ import annotations

import io
import re
import sys
import time
import tracemalloc
import unicodedata
from pathlib import Path
from typing import Any

# Ensure src is on path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute standard Levenshtein edit distance."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev[j + 1] + 1
            deletions = curr[j] + 1
            substitutions = prev[j] + (c1 != c2)
            curr.append(min(insertions, deletions, substitutions))
        prev = curr
    return prev[-1]


def compute_cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate (CER) normalized by reference length."""
    ref_clean = re.sub(r"\s+", " ", reference).strip()
    hyp_clean = re.sub(r"\s+", " ", hypothesis).strip()
    if not ref_clean:
        return 0.0 if not hyp_clean else 1.0
    dist = levenshtein_distance(ref_clean, hyp_clean)
    return round(dist / len(ref_clean), 4)


def create_synthetic_ground_truth_page() -> tuple[Any, str, dict[str, str]]:
    """Generate a clean synthetic page image with mixed scripts, numbers, and fine print."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1200, 1600
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Key text fields for exact match testing
    entities = {
        "date": "15/08/2024",
        "amount": "₹ 45,250/-",
        "account": "SB-987654321",
        "legal_id": "FIR-2024-00129",
    }

    # Draw lines
    lines = [
        "भारत सरकार - वित्त मंत्रालय (GOVERNMENT OF INDIA)",
        "कार्यालय आदेश संख्या: F.No. 12/2024-ADM",
        f"दिनांक (Date): {entities['date']}",
        "खाता विवरण (Account Statement) - भारतीय स्टेट बैंक",
        f"खाता संख्या (Account No): {entities['account']}",
        f"स्वीकृत राशि (Sanctioned Amount): {entities['amount']} केवल",
        f"संदर्भ संख्या (Reference Case ID): {entities['legal_id']}",
        "This document contains important financial and legal notifications.",
        "Terms and Conditions: All transactions are subject to statutory verification under Section 138 NI Act.",
        "Note: Fine print notice at 8pt for OCR resolution testing: Unauthorised alteration is punishable by law.",
    ]
    ground_truth_text = "\n".join(lines)

    y = 60
    for idx, line in enumerate(lines):
        # Draw with default bitmap font or truetype if available
        draw.text((60, y), line, fill="black")
        y += 55

    return img, ground_truth_text, entities


def run_ocr_benchmarks() -> dict[str, Any]:
    """Execute all OCR baseline measurements."""
    print("\n" + "=" * 70)
    print(" 1. OCR BASELINE MEASUREMENTS")
    print("=" * 70)

    from sarathi.sankalpa import ExecutionProfile
    from sarathi.shakti.ocr.engine import RapidOCREngine
    from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine as CoordEngine
    from sarathi.shakti.ocr.engine.parser import _parse_rapidocr_output
    from sarathi.shakti.ocr.engine.tesseract import filter_english_and_numbers

    results: dict[str, Any] = {}

    # A. Cold vs Warm Engine Initialization
    print("\n--- A. Engine Lifecycle: Cold vs Warm Initialization ---")
    tracemalloc.start()
    t0 = time.perf_counter()
    engine = CoordEngine()
    # Force cold load of Devanagari PP-OCRv5
    dev_engine = engine._get_engine(lang="hi")
    cold_init_ms = (time.perf_counter() - t0) * 1000
    _, cold_mem_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Warm access
    t1 = time.perf_counter()
    warm_engine = engine._get_engine(lang="hi")
    warm_init_ms = (time.perf_counter() - t1) * 1000

    results["cold_init_ms"] = round(cold_init_ms, 2)
    results["warm_init_ms"] = round(warm_init_ms, 4)
    results["cold_mem_peak_mb"] = round(cold_mem_peak / (1024 * 1024), 2)
    print(f"  Cold Model Load (Devanagari PP-OCRv5): {cold_init_ms:.2f} ms (Peak RAM: {results['cold_mem_peak_mb']} MB)")
    print(f"  Warm Engine Cache Hit:                 {warm_init_ms:.4f} ms")

    # B. Character Filtering Data Loss Analysis
    print("\n--- B. Character Filtering Analysis (filter_english_and_numbers) ---")
    test_samples = [
        ("Pure Hindi", "कुल राशि पचास हजार रुपये केवल"),
        ("Date string", "15/08/2024"),
        ("Currency & Amount", "₹ 45,250/-"),
        ("Mixed Bilingual", "दिनांक: 15/08/2024, खाता सं: SB-987654321"),
        ("Punctuation only", "--- // || ***"),
    ]
    filter_results = []
    for label, raw_text in test_samples:
        filtered = filter_english_and_numbers(raw_text)
        is_lost = len(filtered.strip()) == 0 and len(raw_text.strip()) > 0
        filter_results.append({
            "label": label,
            "raw": raw_text,
            "filtered": filtered,
            "data_lost": is_lost,
        })
        status_str = "DATA WIPED OUT" if is_lost else "PRESERVED"
        print(f"  [{status_str}] '{label}':")
        print(f"      Raw:      {raw_text!r}")
        print(f"      Filtered: {filtered!r}")
    results["character_filter_tests"] = filter_results

    # C. DPI Scaling & Synthetic Document Recognition
    print("\n--- C. DPI Scaling & Recognition Benchmark (150 vs 200 vs 300 DPI) ---")
    test_img, ground_truth, entities = create_synthetic_ground_truth_page()

    # Test at scales corresponding to 150, 200, 300 DPI (relative to base 150)
    dpi_trials = [
        ("150 DPI (Base)", 1.0),
        ("200 DPI (1.33x)", 200.0 / 150.0),
        ("300 DPI (2.00x)", 300.0 / 150.0),
    ]

    dpi_results = []
    for label, scale in dpi_trials:
        if scale != 1.0:
            nw = int(test_img.width * scale)
            nh = int(test_img.height * scale)
            from PIL import Image
            scaled_img = test_img.resize((nw, nh), resample=Image.Resampling.BILINEAR)
        else:
            scaled_img = test_img

        tracemalloc.start()
        t_start = time.perf_counter()
        page_data, prov, conf, warns = engine.ocr_page(
            scaled_img,
            page_number=1,
            input_id="benchmark_page",
            profile=ExecutionProfile.ACCURATE,
            custom_options={"deskew": False, "english_numbers_only": False, "lang": "hi"},
        )
        rec_dur_ms = (time.perf_counter() - t_start) * 1000
        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        rec_text = page_data.text or ""
        cer = compute_cer(ground_truth, rec_text)

        # Entity matches
        matches = {k: (v in rec_text) for k, v in entities.items()}
        match_count = sum(1 for v in matches.values() if v)

        trial_data = {
            "label": label,
            "duration_ms": round(rec_dur_ms, 2),
            "peak_mem_mb": round(peak_mem / (1024 * 1024), 2),
            "cer": cer,
            "entity_matches": f"{match_count}/{len(entities)}",
        }
        dpi_results.append(trial_data)
        print(f"  {label}: {rec_dur_ms:.2f} ms | RAM: {trial_data['peak_mem_mb']} MB | CER: {cer:.4f} | Entities: {match_count}/{len(entities)}")
    results["dpi_trials"] = dpi_results

    # D. Preprocessing Impact on Clean Document (Deskew on vs off)
    print("\n--- D. Preprocessing Impact on Clean Image (Deskew Enabled vs Disabled) ---")
    t_clean_off = time.perf_counter()
    p_off, _, _, _ = engine.ocr_page(test_img, page_number=1, input_id="bench_clean", profile=ExecutionProfile.ACCURATE, custom_options={"deskew": False, "english_numbers_only": False, "lang": "hi"})
    dur_off = (time.perf_counter() - t_clean_off) * 1000

    t_clean_on = time.perf_counter()
    p_on, _, _, _ = engine.ocr_page(test_img, page_number=1, input_id="bench_clean", profile=ExecutionProfile.ACCURATE, custom_options={"deskew": True, "english_numbers_only": False, "lang": "hi"})
    dur_on = (time.perf_counter() - t_clean_on) * 1000

    cer_off = compute_cer(ground_truth, p_off.text or "")
    cer_on = compute_cer(ground_truth, p_on.text or "")
    overhead_ms = round(dur_on - dur_off, 2)
    results["deskew_impact"] = {
        "deskew_off_ms": round(dur_off, 2),
        "deskew_on_ms": round(dur_on, 2),
        "deskew_overhead_ms": overhead_ms,
        "cer_off": cer_off,
        "cer_on": cer_on,
    }
    print(f"  Deskew OFF: {dur_off:.2f} ms (CER: {cer_off:.4f})")
    print(f"  Deskew ON:  {dur_on:.2f} ms (CER: {cer_on:.4f}) -> Overhead: +{overhead_ms:.2f} ms")

    # E. Tesseract Fallback Ground Truth vs Confidence Comparison
    print("\n--- E. Tesseract Fallback: Confidence Comparison Reality ---")
    if engine.tesseract.is_available():
        from PIL import ImageDraw
        # Create a slightly degraded crop: "15/08/2024"
        crop_img = test_img.crop((60, 160, 450, 220))
        tess_res = engine.tesseract.recognize_crop(crop_img, language="eng")
        if tess_res:
            tess_text, tess_conf = tess_res
            print(f"  Tesseract Crop Output: {tess_text!r} (Reported Conf: {tess_conf})")
            results["tesseract_test"] = {"text": tess_text, "conf": tess_conf}
    else:
        print("  Tesseract binary unavailable for crop test.")

    return results


def run_font_benchmarks() -> dict[str, Any]:
    """Execute all Font Conversion baseline measurements."""
    print("\n" + "=" * 70)
    print(" 2. FONT CONVERSION BASELINE MEASUREMENTS")
    print("=" * 70)

    from sarathi.shakti.font_conversion import (
        FontConversionCapability,
        FontConverter,
        LegacyFontDetector,
        TextProtector,
    )
    from sarathi.shakti.font_conversion.akshara import synthesize_akshara_unicode
    from sarathi.shakti.font_conversion.detector import load_font_profiles

    results: dict[str, Any] = {}

    profiles = load_font_profiles()
    detector = LegacyFontDetector(profiles=profiles)
    protector = TextProtector()
    converter = FontConverter(profiles=profiles)
    capability = FontConversionCapability()

    # Sample legacy KrutiDev text with mixed English, repeated amounts, and punctuation
    sample_text = (
        "dk;kZy; vkns'k la[;k% 12@2024&iz'kklu\n"
        "fnukad 15/08/2024 dks vkns'k tkjh fd;k x;k gSA\n"
        "dqy jkf'k ₹ 50,000/- (Fifty Thousand Rupees) Lohd`r dh xbZ gSA\n"
        "iqu% lwfpr fd;k tkrk gS fd ₹ 50,000/- dh jkf'k [kkrk la[;k SB-987654321 esa tek dh tk,xhA\n"
        "Case Reference: FIR-2024-00129 under Section 420 IPC.\n"
        "Official Website: https://finance.gov.in/notifications/2024\n"
        "Contact Email: support.finance@nic.in for further information.\n"
        "vfUre frfFk 31/08/2024 gSA ₹ 50,000/- dk Hkqxrku rqjar djsaA"
    )

    # A. Sub-stage Latency Profiling
    print("\n--- A. Sub-stage Latency Breakdown (Multi-paragraph Legacy Text) ---")
    # 1. Detection
    t0 = time.perf_counter()
    for _ in range(50):
        det_prof, conf = detector.detect(sample_text)
    det_ms = ((time.perf_counter() - t0) / 50) * 1000

    # 2. Protection
    t1 = time.perf_counter()
    for _ in range(50):
        prot_text, spans = protector.protect(sample_text)
    prot_ms = ((time.perf_counter() - t1) / 50) * 1000

    # 3. Transducer Conversion
    t2 = time.perf_counter()
    for _ in range(50):
        conv_text = converter.convert(prot_text, profile_id="krutidev010")
    conv_ms = ((time.perf_counter() - t2) / 50) * 1000

    # 4. Restoration
    t3 = time.perf_counter()
    for _ in range(50):
        rest_text = protector.restore(conv_text, spans)
    rest_ms = ((time.perf_counter() - t3) / 50) * 1000

    total_stage_ms = det_ms + prot_ms + conv_ms + rest_ms
    results["substage_latency_ms"] = {
        "detection_ms": round(det_ms, 3),
        "protection_ms": round(prot_ms, 3),
        "conversion_ms": round(conv_ms, 3),
        "restoration_ms": round(rest_ms, 3),
        "total_ms": round(total_stage_ms, 3),
    }
    print(f"  1. Detection:   {det_ms:.3f} ms ({det_ms / total_stage_ms * 100:.1f}%)")
    print(f"  2. Protection:  {prot_ms:.3f} ms ({prot_ms / total_stage_ms * 100:.1f}%)")
    print(f"  3. Conversion:  {conv_ms:.3f} ms ({conv_ms / total_stage_ms * 100:.1f}%)")
    print(f"  4. Restoration: {rest_ms:.3f} ms ({rest_ms / total_stage_ms * 100:.1f}%)")
    print(f"  Total per-run:  {total_stage_ms:.3f} ms")

    # B. Repeated Entity Protection Integrity
    print("\n--- B. Repeated Entity Protection Integrity ---")
    prot_text, spans = protector.protect(sample_text)
    rest_text = protector.restore(prot_text, spans)

    amount_count_source = sample_text.count("₹ 50,000/-")
    amount_count_restored = rest_text.count("₹ 50,000/-")
    fir_intact = "FIR-2024-00129" in rest_text
    url_intact = "https://finance.gov.in/notifications/2024" in rest_text
    email_intact = "support.finance@nic.in" in rest_text

    is_100_pct = (amount_count_source == amount_count_restored == 3) and fir_intact and url_intact and email_intact
    results["repeated_protection"] = {
        "source_repeated_amounts": amount_count_source,
        "restored_repeated_amounts": amount_count_restored,
        "fir_intact": fir_intact,
        "url_intact": url_intact,
        "email_intact": email_intact,
        "perfect_integrity": is_100_pct,
    }
    print(f"  Repeated Amounts (₹ 50,000/-): Source={amount_count_source}, Restored={amount_count_restored}")
    print(f"  FIR ID Intact:   {fir_intact}")
    print(f"  URL Intact:      {url_intact}")
    print(f"  Email Intact:    {email_intact}")
    print(f"  Integrity Pass:  {is_100_pct}")

    # C. Split-Matra and Devanagari Akshara Composition Flaw Test
    print("\n--- C. Split-Matra Order Dependency Test ---")
    # Test 'को': Normal order is क + \u093e\u0947 (aa + e), reverse is क + \u0947\u093e (e + aa)
    norm_order = "क\u093e\u0947"
    rev_order = "क\u0947\u093e"

    syn_norm = synthesize_akshara_unicode(norm_order)
    syn_rev = synthesize_akshara_unicode(rev_order)

    expected = "को"  # \u0915\u094b
    norm_correct = (syn_norm == expected)
    rev_correct = (syn_rev == expected)

    results["split_matra"] = {
        "standard_order_composed": norm_correct,
        "reverse_order_composed": rev_correct,
        "syn_norm_hex": [hex(ord(c)) for c in syn_norm],
        "syn_rev_hex": [hex(ord(c)) for c in syn_rev],
    }
    print(f"  Standard Order (\\u093e\\u0947 -> aa+e): Composed to 'को' ({norm_correct})")
    print(f"  Reverse Order  (\\u0947\\u093e -> e+aa): Composed to 'को' ({rev_correct})")
    if not rev_correct:
        print(f"  [DEFECT CONFIRMED] Reverse-order split matra \\u0947\\u093e failed to compose to 'को'! Output was: {[hex(ord(c)) for c in syn_rev]}")

    # D. DOCX Double-Conversion Redundancy Measurement
    print("\n--- D. DOCX Transformation Redundancy Test ---")
    from sarathi.sankalpa import CanonicalDocument, PageData
    from sarathi.shakti.docx_exporter import build_docx_payload, transform_docx_artifact

    p_text = "dk;kZy; vkns'k la[;k% 12@2024&iz'kklu fnukad 15/08/2024 dks vkns'k tkjh fd;k x;k gSA\n" * 20
    test_doc = CanonicalDocument(
        document_id="bench_doc",
        text=p_text,
        pages=(PageData(page_number=1, text=p_text),),
    )
    docx_payload_initial = build_docx_payload(test_doc, filename="bench.docx", legacy_target_font="Kruti Dev 010")
    # Injected rFonts w:ascii="Kruti Dev 010" into the docx
    xml_str = docx_payload_initial.content.decode("latin1")
    # Replace default font with Kruti Dev 010
    xml_str = xml_str.replace('w:ascii="Times New Roman"', 'w:ascii="Kruti Dev 010"').replace('w:hAnsi="Times New Roman"', 'w:hAnsi="Kruti Dev 010"')
    docx_bytes = xml_str.encode("latin1")


    conv_calls = 0

    def counting_converter(text: str, **kwargs: Any) -> str:
        nonlocal conv_calls
        conv_calls += 1
        return converter.convert(text, profile_id="krutidev010")

    t_docx = time.perf_counter()
    _ = transform_docx_artifact(
        input_bytes=docx_bytes,
        converter_fn=counting_converter,
        filename="test.docx",
        profiles=profiles,
    )
    docx_time_ms = (time.perf_counter() - t_docx) * 1000
    results["docx_transformation"] = {
        "runs_converted_in_docx": conv_calls,
        "docx_transform_time_ms": round(docx_time_ms, 2),
    }
    print(f"  DOCX XML Parsing & Run Transduction Time: {docx_time_ms:.2f} ms ({conv_calls} runs converted)")
    print(f"  Note: In capability.py, CanonicalDocument also converts these {conv_calls} runs separately upfront.")


    return results


def main() -> None:
    print("=" * 70)
    print(" SARATHI V2: OCR & FONT CONVERSION BASELINE BENCHMARK")
    print(f" Python {sys.version.split()[0]} | Root: {REPO_ROOT}")
    print("=" * 70)

    t_start = time.perf_counter()
    ocr_res = run_ocr_benchmarks()
    font_res = run_font_benchmarks()
    total_time = round(time.perf_counter() - t_start, 2)

    print("\n" + "=" * 70)
    print(f" BENCHMARK RUN COMPLETE IN {total_time}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
