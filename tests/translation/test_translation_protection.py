"""Tests for Translation Span Protection and Restoration."""

import json
from pathlib import Path
from typing import Any

import pytest

from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.shakti.translation.protector import TranslationProtector


def _fake_translation_data_root(tmp_path: Path) -> Path:
    """Create the minimal on-disk asset shape required by mocked native-backend tests."""
    root = tmp_path / "translation"
    model_dir = root / "models" / "krutrim" / "hi-en"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"test-ct2-placeholder")
    (model_dir / "spm.model").write_bytes(b"test-sentencepiece-placeholder")
    (root / "manifest.json").write_text(
        json.dumps({"models": {"hi-en": {"source_lang": "hin_Deva", "target_lang": "eng_Latn"}}}),
        encoding="utf-8",
    )
    return root


def test_factual_spans_and_identifiers_preserved_byte_for_byte(test_backend: Any) -> None:
    protector = TranslationProtector()
    engine = CTranslate2TranslationEngine(backend=test_backend, protector=protector)

    sample = (
        "दिनांक 15/08/2026 को खाता संख्या ACC-998811 में ₹ 1,50,000.50 जमा (100%) किए गए। "
        "विवरण https://sbi.co.in/txn तथा ईमेल contact@gov.in पर देखें।"
    )

    result = engine.translate(sample, direction=TranslationDirection.HI_TO_EN)
    translated = result.translated_text

    # Verify factual spans survive byte-for-byte
    assert "15/08/2026" in translated
    assert "ACC-998811" in translated
    assert "1,50,000.50" in translated
    assert "(100%)" in translated
    assert "https://sbi.co.in/txn" in translated
    assert "contact@gov.in" in translated


def test_span_protection_detects_corrupted_or_dropped_placeholders() -> None:
    """Verify restore_with_validation reports missing or duplicated placeholders."""
    from dataclasses import dataclass

    from sarathi.shakti.text.span_protection import BaseSpanProtector

    @dataclass
    class DummySpan:
        placeholder: str
        original_text: str

    protector = BaseSpanProtector()
    p0 = protector.format_placeholder(0)
    p1 = protector.format_placeholder(1)
    spans = [
        DummySpan(placeholder=p0, original_text="₹1000"),
        DummySpan(placeholder=p1, original_text="PAN-ABCDE1234F"),
    ]

    # Case 1: Model deleted p0 from output
    text_missing = f"The client paid and has PAN {p1}"
    restored, issues = protector.restore_with_validation(text_missing, spans)
    assert len(issues) == 1
    assert issues[0]["code"] == "PROTECTED_SPAN_MISSING"
    assert issues[0]["original_text"] == "₹1000"
    assert "PAN-ABCDE1234F" in restored

    # Case 2: Model duplicated p0 in output
    text_duplicated = f"The client paid {p0} twice: {p0}, with PAN {p1}"
    restored, issues = protector.restore_with_validation(text_duplicated, spans)
    assert len(issues) == 1
    assert issues[0]["code"] == "PROTECTED_SPAN_DUPLICATED"
    assert issues[0]["count"] == 2
    assert "₹1000 twice: ₹1000" in restored


def test_translation_protector_shields_glossary_terms() -> None:
    protector = TranslationProtector()
    glossary = {"High Court": "उच्च न्यायालय", "Supreme Court": "सर्वोच्च न्यायालय"}
    text = "The High Court issued an order to the Supreme Court."
    protected_text, spans = protector.protect(text, glossary_mappings=glossary)
    assert "High Court" not in protected_text
    assert "Supreme Court" not in protected_text
    assert len(spans) == 2


def test_translation_protector_numeric_placeholders_and_dictionary_words() -> None:
    """Verify TranslationProtector uses SentencePiece-safe numeric placeholders and ignores English words."""
    protector = TranslationProtector()

    # Verify placeholder format
    assert protector.format_placeholder(0) == "9990000"
    assert protector.format_placeholder(1) == "9990001"

    # Verify uppercase English words are NOT masked as IDs
    sample = "THE COURT ISSUED AN ORDER TO THE POLICE STATION IN DELHI REGARDING TABLE DATA."
    protected, spans = protector.protect(sample)
    assert "THE" in protected
    assert "COURT" in protected
    assert "ORDER" in protected
    assert "POLICE" in protected
    assert "TABLE" in protected
    assert len(spans) == 0

    # Verify alphanumeric IDs with numbers or hyphens ARE protected
    id_sample = "Case REF-2026, Account ACC-998811, Section 120B, DL12AB1234."
    protected_id, id_spans = protector.protect(id_sample)
    assert "REF-2026" not in protected_id
    assert "ACC-998811" not in protected_id
    assert "120B" not in protected_id
    assert "DL12AB1234" not in protected_id
    assert len(id_spans) == 4

    # Verify restoration byte-for-byte
    restored, issues = protector.restore_with_validation(protected_id, id_spans)
    assert issues == []
    assert restored == id_sample


def test_translation_protector_recovers_collapsed_digits() -> None:
    """Verify TranslationProtector recovers placeholders when NMT collapses or modifies 999 to 99."""
    from dataclasses import dataclass

    @dataclass
    class DummySpan:
        placeholder: str
        original_text: str

    protector = TranslationProtector()
    spans = [
        DummySpan(placeholder="9990003", original_text="5"),
        DummySpan(placeholder="9990004", original_text="PMLA-2002"),
    ]

    # Model collapsed 9990003 to 990003 and inserted spaces in 999 0004
    corrupted_output = "उचित कार्रवाई कर रहे हैं u/s990003of PMLA तथा नियम 9 9 9 0004 के तहत।"
    restored, issues = protector.restore_with_validation(corrupted_output, spans)

    assert issues == []
    assert "u/s5of PMLA" in restored
    assert "नियम PMLA-2002 के तहत" in restored


def test_translation_protector_word_boundaries_prevent_substring_corruption() -> None:
    """Verify that word boundaries prevent terms like 'order' from corrupting 'border' or 'disorder'."""
    protector = TranslationProtector()
    glossary = {"order": "आदेश", "ऋण": "Debt"}
    sample = "The border patrol observed no disorder, but executed the court order. वह ऋण मुक्त है।"

    protected, spans = protector.protect(sample, glossary_mappings=glossary)

    assert "border" in protected
    assert "disorder" in protected
    assert "court 999" in protected or "999" in protected
    # Only "order" and "ऋण" should be protected
    assert len(spans) == 2

    restored, issues = protector.restore_with_validation(protected, spans)
    assert issues == []
    assert "The border patrol observed no disorder, but executed the court आदेश." in restored
    assert "वह Debt मुक्त है।" in restored


def test_local_translation_engine_preserves_statutory_citations_and_glossaries(test_backend: Any) -> None:
    """Verify CTranslate2TranslationEngine preserves case law citations, FIRs, and applies scoped glossary."""
    protector = TranslationProtector()
    engine = CTranslate2TranslationEngine(backend=test_backend, protector=protector)

    sample = (
        "माननीय उच्चतम न्यायालय ने (2021) 4 SCC 123 तथा AIR 1980 SC 1789 में अभिनिर्धारित किया। "
        "याचिकाकर्ता के विरुद्ध प्राथमिकी FIR No. 123/2024 दर्ज की गई। अभियोजन पक्ष विफल रहा।"
    )

    custom_citations = ("(2021) 4 SCC 123", "AIR 1980 SC 1789", "FIR No. 123/2024")
    scoped_glossary = {
        "उच्चतम न्यायालय": "Supreme Court",
        "याचिकाकर्ता": "Petitioner",
        "अभियोजन पक्ष": "Prosecution",
    }

    result = engine.translate(
        sample,
        direction=TranslationDirection.HI_TO_EN,
        glossary_terms=scoped_glossary,
        custom_terms=custom_citations,
    )
    translated = result.translated_text

    # Verify statutory and case citations survive verbatim
    assert "(2021) 4 SCC 123" in translated
    assert "AIR 1980 SC 1789" in translated
    assert "FIR No. 123/2024" in translated

    # Verify domain legal terminology is restored
    assert "Supreme Court" in translated
    assert "Petitioner" in translated
    assert "Prosecution" in translated


def test_bug_T1_number_regex_whitespace() -> None:
    """T1: Number regex eats whitespace and beats the date regex."""
    protector = TranslationProtector()
    text = "Sec. 3 of the Act dated 12.03.2024, Rs. 5.50 lakh"
    protected_text, spans = protector.protect(text)

    # 1. Assert the date is exactly one date span
    date_spans = [s for s in spans if s.span_type == "date"]
    assert len(date_spans) == 1, f"Expected exactly 1 date span, got {date_spans}"
    assert date_spans[0].original_text == "12.03.2024"

    # 2. Assert no span text starts or ends with whitespace
    for s in spans:
        assert s.original_text == s.original_text.strip(), f"Span '{s.original_text}' has leading/trailing whitespace"

    # 3. Assert the protected text still has a space before and after each placeholder
    for s in spans:
        p = s.placeholder
        idx = protected_text.find(p)
        assert idx != -1
        if idx > 0 and text[0:1] != p:
            assert protected_text[idx - 1] == " ", f"Expected space before {p} in '{protected_text}'"
        after_char = protected_text[idx + len(p)] if idx + len(p) < len(protected_text) else ""
        assert after_char in (" ", ",", "."), (
            f"Expected space or punctuation after {p}, got '{after_char}' in '{protected_text}'"
        )

    # 4. Assert restore_with_validation returns the original string exactly (identity round trip)
    restored, issues = protector.restore_with_validation(protected_text, spans)
    assert issues == []
    assert restored == text


def test_bug_T2_sentence_splitter_abbreviations() -> None:
    """T2: Sentence splitter breaks on abbreviations and drops newlines."""
    from sarathi.shakti.translation.engine import split_sentences

    # 1. "Dr. A. K. Singh appeared. He left." -> 2 segments
    t1 = "Dr. A. K. Singh appeared. He left."
    s1 = split_sentences(t1)
    assert len(s1) == 2, f"Expected 2 segments, got {s1}"
    assert s1[0][0] == "Dr. A. K. Singh appeared."
    assert s1[1][0] == "He left."

    # 2. "vide No. ECIR/HQ/12/2023." -> 1 segment
    t2 = "vide No. ECIR/HQ/12/2023."
    s2 = split_sentences(t2)
    assert len(s2) == 1, f"Expected 1 segment, got {s2}"
    assert s2[0][0] == "vide No. ECIR/HQ/12/2023."

    # 3. "पहली पंक्ति।\nदूसरी पंक्ति।" -> rejoined output equals input, including \n
    t3 = "पहली पंक्ति।\nदूसरी पंक्ति।"
    s3 = split_sentences(t3)
    rejoined3 = "".join(seg + sep for seg, sep in s3)
    assert rejoined3 == t3, f"Expected exact rejoin, got {rejoined3!r}"

    # 4. "Rs. 5.50 lakh approx. i.e. five lakh." -> 1 segment
    t4 = "Rs. 5.50 lakh approx. i.e. five lakh."
    s4 = split_sentences(t4)
    assert len(s4) == 1, f"Expected 1 segment, got {s4}"
    assert s4[0][0] == t4


def test_bug_T3_type_error_cascades_translation() -> None:
    """T3: Fake engine raising TypeError inside translate_batch must not trigger retry cascades."""
    import pytest

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, ExecutionProfile, Request, Result
    from sarathi.shakti.translation.capability import TranslationCapability

    call_count = 0

    class BuggyEngine:
        def translate_batch(self, batch: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            raise TypeError("boom")

    cap = TranslationCapability(engine=BuggyEngine())
    doc = CanonicalDocument(document_id="doc1", text="Hello world.")
    from pathlib import Path

    from sarathi.sankalpa import InputRef

    req = Request(
        request_id="req1",
        requirement="translation",
        inputs=(InputRef(input_id="in-1", display_name="doc1.txt", source_path=Path("doc1.txt"), size_bytes=10),),
        profile=ExecutionProfile.INSTANT,
    )
    ctx = ExecutionContext(request_id="req1", run_id="run1", trace_id="trace1", span_id="span1")

    with pytest.raises(TypeError, match="boom"):
        cap.execute(req, context=ctx, prior_result=Result(data=doc))

    assert call_count == 1, f"Expected engine to be called exactly once, but was called {call_count} times"


def test_bug_T4_glossary_matching_zero_recompiles(monkeypatch: Any) -> None:
    """T4: After the first protect() on a glossary, further calls on the same glossary must trigger 0 compiles."""
    import re
    from pathlib import Path

    from sarathi.shakti.translation.glossary import GlossaryStore
    from sarathi.shakti.translation.models import TranslationDirection
    from sarathi.shakti.translation.protector import TranslationProtector

    g = GlossaryStore(Path("data/translation"))
    terms = g.get_terms(TranslationDirection.HI_TO_EN)
    assert len(terms) > 1000

    protector = TranslationProtector()
    text = "माननीय न्यायालय ने आरोपी को जमानत दे दी।"

    # Warm-up call (first call compiles the matcher)
    protector.protect(text, glossary_mappings=terms)

    # Spy on re.compile during second call
    compile_count = 0
    orig_compile = re.compile

    def spy_compile(*args: Any, **kwargs: Any) -> Any:
        nonlocal compile_count
        compile_count += 1
        return orig_compile(*args, **kwargs)

    monkeypatch.setattr(re, "compile", spy_compile)

    # Second call with the same glossary
    protector.protect(text, glossary_mappings=terms)

    assert compile_count == 0, f"Expected 0 re.compile calls on subsequent protect() call, got {compile_count}"


def test_bug_T4_glossary_matching_equivalence() -> None:
    """T4: Equivalence test: for fixed sample text and real glossaries, new matcher equals old oracle logic."""
    import re
    from pathlib import Path

    from sarathi.shakti.translation.glossary import GlossaryStore
    from sarathi.shakti.translation.models import TranslationDirection
    from sarathi.shakti.translation.protector import TranslationProtector

    g = GlossaryStore(Path("data/translation"))
    terms = g.get_terms(TranslationDirection.HI_TO_EN)

    text = "माननीय न्यायालय ने आरोपी को जमानत दे दी। केन्द्रीय अन्वेषण ब्यूरो (CBI) ने याचिका दाखिल की।"

    # Oracle implementation (the unpatched O(N) regex approach)
    def oracle_compile_term_pattern(term: str) -> re.Pattern[str]:
        esc = re.escape(term)
        prefix = r"(?<!\w)" if term and term[0].isalnum() else ""
        suffix = r"(?!\w)" if term and term[-1].isalnum() else ""
        flags = re.IGNORECASE if any(ord(c) < 128 and c.isalpha() for c in term) else 0
        return re.compile(f"{prefix}{esc}{suffix}", flags)

    oracle_matches: list[tuple[int, int, str, str, int]] = []
    sorted_srcs = sorted([s for s in terms.keys() if s.strip()], key=len, reverse=True)
    for src in sorted_srcs:
        target_val = terms[src]
        for m in oracle_compile_term_pattern(src).finditer(text):
            oracle_matches.append((m.start(), m.end(), target_val, "glossary_term", 10))

    oracle_matches.sort(key=lambda x: (x[0], x[4], -(x[1] - x[0])))
    oracle_selected: list[tuple[int, int, str, str]] = []
    last_end = 0
    for start, end, orig_val, span_type, _ in oracle_matches:
        if start >= last_end:
            oracle_selected.append((start, end, orig_val, span_type))
            last_end = end

    # New implementation
    protector = TranslationProtector()
    _, new_spans = protector.protect(text, glossary_mappings=terms)

    assert len(new_spans) == len(oracle_selected)
    for span, oracle in zip(new_spans, oracle_selected):
        assert span.original_text == oracle[2]
        assert span.span_type == oracle[3]


@pytest.mark.performance
def test_bug_T4_glossary_matching_performance() -> None:
    """T4: 200 calls on the real HI->EN glossary in under 10 ms average per call."""
    import time
    from pathlib import Path

    from sarathi.shakti.translation.glossary import GlossaryStore
    from sarathi.shakti.translation.models import TranslationDirection
    from sarathi.shakti.translation.protector import TranslationProtector

    g = GlossaryStore(Path("data/translation"))
    terms = g.get_terms(TranslationDirection.HI_TO_EN)

    protector = TranslationProtector()
    text = "माननीय न्यायालय ने आरोपी को जमानत दे दी। केन्द्रीय अन्वेषण ब्यूरो (CBI) ने याचिका दाखिल की।"

    # Warmup
    protector.protect(text, glossary_mappings=terms)

    t0 = time.perf_counter()
    n_calls = 200
    for _ in range(n_calls):
        protector.protect(text, glossary_mappings=terms)
    elapsed_total_ms = (time.perf_counter() - t0) * 1000.0
    avg_ms = elapsed_total_ms / n_calls

    assert avg_ms < 10.0, f"Average protect() call took {avg_ms:.2f} ms (expected < 10.0 ms)"


def test_bug_T5_redundant_translation() -> None:
    """T5: For a 2-page doc where doc.text == '\\n\\n'.join(page.text), every unique sentence reaches backend exactly once."""
    from collections.abc import Sequence
    from pathlib import Path

    from sarathi.sankalpa import (
        CanonicalDocument,
        ExecutionContext,
        ExecutionProfile,
        InputRef,
        PageData,
        Request,
        Result,
        TextSpan,
    )
    from sarathi.shakti.translation.capability import TranslationCapability

    received_sentences: list[str] = []

    class CountingBackend:
        def translate_sentences(self, sentences: Sequence[str], direction: Any = None, **kwargs: Any) -> list[str]:
            for s in sentences:
                received_sentences.append(s)
            return [f"TRANS_{s}" for s in sentences]

    p1 = PageData(page_number=1, text="पहला वाक्य।", spans=(TextSpan(text="पहला वाक्य।"),))
    p2 = PageData(page_number=2, text="दूसरा वाक्य।", spans=(TextSpan(text="दूसरा वाक्य।"),))
    doc = CanonicalDocument(
        document_id="doc-t5",
        text=f"{p1.text}\n\n{p2.text}",
        pages=(p1, p2),
    )

    cap = TranslationCapability(backend=CountingBackend())
    req = Request(
        request_id="req-t5",
        requirement="translation",
        inputs=(InputRef(input_id="in-t5", source_path=Path("doc.txt"), display_name="doc.txt", size_bytes=10),),
        profile=ExecutionProfile.INSTANT,
    )
    ctx = ExecutionContext(request_id="req-t5", run_id="run-t5", trace_id="trace-t5", span_id="span-t5")

    res = cap.execute(req, context=ctx, prior_result=Result(data=doc))
    out_doc = res.data
    assert isinstance(out_doc, CanonicalDocument)

    # 1. Assert every unique sentence reaches the backend exactly once
    assert len(received_sentences) == 2, (
        f"Expected 2 sentence translations, got {len(received_sentences)}: {received_sentences}"
    )
    assert received_sentences == ["पहला वाक्य।", "दूसरा वाक्य।"]

    # 2. Assert translated doc.text, page.text and spans are consistent with each other
    assert out_doc.text == f"{out_doc.pages[0].text}\n\n{out_doc.pages[1].text}"
    assert out_doc.pages[0].text == out_doc.pages[0].spans[0].text
    assert out_doc.pages[1].text == out_doc.pages[1].spans[0].text
    assert out_doc.pages[0].text == "TRANS_पहला वाक्य।"
    assert out_doc.pages[1].text == "TRANS_दूसरा वाक्य।"


def test_bug_T6_silent_truncation_warning_and_params(monkeypatch: Any, tmp_path: Path) -> None:
    """T6: translate_batch must pass explicit beam_size and max_decoding_length, and warn on truncation."""
    from types import SimpleNamespace

    import ctranslate2
    import sentencepiece

    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
    from sarathi.shakti.translation.models import TranslationDirection

    captured_kwargs: dict[str, Any] = {}

    class FakeTranslator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def translate_batch(self, tokenized: Any, **kwargs: Any) -> Any:
            nonlocal captured_kwargs
            captured_kwargs.update(kwargs)
            max_len = kwargs.get("max_decoding_length", 256)
            # Simulate hypothesis reaching the max decoding limit
            return [SimpleNamespace(hypotheses=[["tok"] * max_len])]

    class FakeSPM:
        def load(self, path: str) -> None:
            pass

        def encode_as_pieces(self, text: str) -> list[str]:
            return ["tok1", "tok2"]

        def decode_pieces(self, pieces: list[str]) -> str:
            return "अनुवादित पाठ"

    monkeypatch.setattr(ctranslate2, "Translator", FakeTranslator)
    monkeypatch.setattr(sentencepiece, "SentencePieceProcessor", FakeSPM)

    engine = CTranslate2TranslationEngine(data_root=_fake_translation_data_root(tmp_path))
    result = engine.translate("परीक्षण वाक्य।", direction=TranslationDirection.HI_TO_EN)

    # 1. Assert kwargs include explicit beam_size and max_decoding_length
    assert "beam_size" in captured_kwargs, f"Expected explicit 'beam_size' in kwargs, got {captured_kwargs}"
    assert "max_decoding_length" in captured_kwargs, (
        f"Expected explicit 'max_decoding_length' in kwargs, got {captured_kwargs}"
    )

    # 2. Assert TRANSLATION_TRUNCATION_SUSPECTED is emitted in span_protection_issues or metadata
    span_issues = result.metadata.get("span_protection_issues", ())
    warnings = result.metadata.get("warnings", ())
    assert (
        "TRANSLATION_TRUNCATION_SUSPECTED" in span_issues
        or "TRANSLATION_TRUNCATION_SUSPECTED" in warnings
        or result.metadata.get("truncation_suspected") is True
    ), f"Expected TRANSLATION_TRUNCATION_SUSPECTED warning in metadata, got {result.metadata}"


def test_bug_T7_anubhava_word_boundary() -> None:
    """T7: Anubhava correction का->X must not alter कार्य, but must apply to standalone word का."""
    from collections.abc import Sequence

    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
    from sarathi.shakti.translation.models import TranslationDirection

    captured_sentences: list[str] = []

    class DummyBackend:
        def translate_sentences(self, sentences: Sequence[str], direction: Any = None, **kwargs: Any) -> list[str]:
            captured_sentences.extend(sentences)
            return list(sentences)

    engine = CTranslate2TranslationEngine(backend=DummyBackend())
    engine._anubhava_corrections = {"hi-en": {"का": "X"}}

    engine.translate("कार्य का परिणाम", direction=TranslationDirection.HI_TO_EN)

    assert len(captured_sentences) == 1
    assert "कार्य" in captured_sentences[0], f"Expected 'कार्य' to remain untouched, got {captured_sentences[0]}"
    assert captured_sentences[0] == "कार्य X परिणाम", f"Expected 'कार्य X परिणाम', got {captured_sentences[0]}"


def test_bug_T8_model_cache_deduplication(monkeypatch: Any, tmp_path: Path) -> None:
    """T8: Two translate_sentences calls with different approved_concurrency must construct one translator."""
    from types import SimpleNamespace

    import ctranslate2
    import sentencepiece

    from sarathi.sankalpa import DeviceType, ExecutionBinding
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
    from sarathi.shakti.translation.models import TranslationDirection

    translator_construct_count = 0

    class CountingTranslator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            nonlocal translator_construct_count
            translator_construct_count += 1

        def translate_batch(self, tokenized: Any, **kwargs: Any) -> Any:
            return [SimpleNamespace(hypotheses=[["tok"]])]

    class FakeSPM:
        def load(self, path: str) -> None:
            pass

        def encode_as_pieces(self, text: str) -> list[str]:
            return ["tok"]

        def decode_pieces(self, pieces: list[str]) -> str:
            return "out"

    monkeypatch.setattr(ctranslate2, "Translator", CountingTranslator)
    monkeypatch.setattr(sentencepiece, "SentencePieceProcessor", FakeSPM)

    engine = CTranslate2TranslationEngine(data_root=_fake_translation_data_root(tmp_path))
    backend = engine._ensure_backend()

    binding1 = ExecutionBinding(
        "cpu-0",
        DeviceType.CPU,
        "ctranslate2",
        "cpu",
        approved_concurrency=1,
    )
    backend.translate_sentences(["पहला वाक्य।"], direction=TranslationDirection.HI_TO_EN, execution_binding=binding1)

    binding2 = ExecutionBinding(
        "cpu-0",
        DeviceType.CPU,
        "ctranslate2",
        "cpu",
        approved_concurrency=4,
    )
    backend.translate_sentences(["दूसरा वाक्य।"], direction=TranslationDirection.HI_TO_EN, execution_binding=binding2)

    assert translator_construct_count == 1, (
        f"Expected exactly 1 Translator construction, got {translator_construct_count}"
    )


def test_number_protection_unformatted_and_decimal() -> None:
    """Verify unformatted 4+ digit numbers, decimal currency amounts, and percentages are protected."""
    protector = TranslationProtector()
    text = "Invoice 1234 amount Rs. 1250.00 rate 12345678 and ₹ 1,50,000.50 discount 25%."
    _, spans = protector.protect(text)

    protected_vals = [s.original_text for s in spans]
    assert "1234" in protected_vals
    assert "Rs. 1250.00" in protected_vals
    assert "12345678" in protected_vals
    assert "₹ 1,50,000.50" in protected_vals
    assert "25%" in protected_vals


def test_trailing_zero_absorption_prevents_leakage() -> None:
    """Verify restore_with_validation absorbs extra trailing zeroes hallucinated by NMT."""
    from dataclasses import dataclass

    @dataclass
    class DummySpan:
        placeholder: str
        original_text: str

    protector = TranslationProtector()
    spans = [
        DummySpan(placeholder="9990000", original_text="Prosecution"),
        DummySpan(placeholder="9990001", original_text="Complainant"),
        DummySpan(placeholder="9990002", original_text="07-10-2019"),
    ]

    # Model hallucinated extra zeroes at the end of numeric placeholders
    model_output = "The 99900000 was filed by 9990001000 on date 999000200."
    restored, _ = protector.restore_with_validation(model_output, spans)

    assert "Prosecution0" not in restored
    assert "Complainant0" not in restored
    assert "07-10-201900" not in restored
    assert restored == "The Prosecution was filed by Complainant on date 07-10-2019."
