"""Tests for CourtTemplateMatcher and profile-driven beam size in translation."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.translation.court_templates import CourtTemplateMatcher
from sarathi.shakti.translation.engine import (
    BackendTranslationResult,
    CTranslate2TranslationEngine,
)
from sarathi.shakti.translation.models import TranslationDirection


def test_court_template_matcher_en_to_hi_boilerplate() -> None:
    matcher = CourtTemplateMatcher()

    # Exact sentence with terminal punctuation
    res = matcher.match_sentence(
        "Heard learned counsel for the petitioner and learned counsel for the respondent.",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res == "याचिकाकर्ता के विद्वान अधिवक्ता एवं प्रतिवादी के विद्वान अधिवक्ता को सुना गया।"

    # Case-insensitive without terminal punctuation
    res2 = matcher.match_sentence(
        "heard learned counsel for the parties",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res2 == "पक्षकारों के विद्वान अधिवक्ताओं को सुना गया"

    # Bail order
    res3 = matcher.match_sentence(
        "The bail application is allowed.",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res3 == "जमानत आवेदन स्वीकार किया जाता है।"


def test_court_template_matcher_hi_to_en_boilerplate() -> None:
    matcher = CourtTemplateMatcher()

    res = matcher.match_sentence(
        "अभिलेख का अवलोकन किया गया।",
        direction=TranslationDirection.HI_TO_EN,
    )
    assert res == "Perused the record."

    res2 = matcher.match_sentence(
        "लागत/खर्चे के संबंध में कोई आदेश नहीं।",
        direction=TranslationDirection.HI_TO_EN,
    )
    assert res2 == "No order as to costs."


def test_court_template_matcher_statutory_patterns() -> None:
    matcher = CourtTemplateMatcher()

    # IPC
    res_ipc = matcher.match_sentence(
        "Under Section 302 of the Indian Penal Code.",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res_ipc == "भारतीय दंड संहिता की धारा 302।"

    # NI Act
    res_ni = matcher.match_sentence(
        "Section 138 of the Negotiable Instruments Act.",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res_ni == "परक्राम्य लिखत अधिनियम की धारा 138।"

    # Constitution
    res_const = matcher.match_sentence(
        "Article 226 of the Constitution of India.",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res_const == "भारत के संविधान का अनुच्छेद 226।"

    # CrPC
    res_crpc = matcher.match_sentence(
        "Section 438 Cr.P.C.",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res_crpc == "दंड प्रक्रिया संहिता की धारा 438।"

    # BNS
    res_bns = matcher.match_sentence(
        "Section 103 BNS.",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res_bns == "भारतीय न्याय संहिता की धारा 103।"


def test_court_template_matcher_unmatched() -> None:
    matcher = CourtTemplateMatcher()
    res = matcher.match_sentence(
        "The defendant was walking along the highway on Monday morning.",
        direction=TranslationDirection.EN_TO_HI,
    )
    assert res is None


def test_court_template_zero_latency_microsecond_performance() -> None:
    matcher = CourtTemplateMatcher()
    test_sentence = "Heard learned counsel for the petitioner and learned counsel for the respondent."

    t0 = time.perf_counter()
    for _ in range(500):
        _ = matcher.match_sentence(test_sentence, direction=TranslationDirection.EN_TO_HI)
    t1 = time.perf_counter()

    avg_time_ms = ((t1 - t0) / 500) * 1000
    # Must execute well under 0.05 ms per sentence (pure hash/string lookup)
    assert avg_time_ms < 0.05, f"Lookup took {avg_time_ms:.4f} ms, expected < 0.05 ms"


def test_engine_court_template_shortcircuit() -> None:
    mock_backend = MagicMock()
    mock_backend.translate_sentences.return_value = BackendTranslationResult(
        sentences=["यह एक कस्टम वाक्य है।"],
        device="cpu",
    )

    engine = CTranslate2TranslationEngine(backend=mock_backend)

    mixed_texts = [
        "Perused the record.",
        "This is an arbitrary custom sentence.",
    ]

    results = engine.translate_batch(
        texts=mixed_texts,
        direction=TranslationDirection.EN_TO_HI,
    )

    assert len(results) == 2
    # Template matched sentence should be exact
    assert results[0].translated_text == "अभिलेख का अवलोकन किया गया।"
    # Custom sentence should go through backend
    assert results[1].translated_text == "यह एक कस्टम वाक्य है।"

    # Only 1 sentence should have been sent to mock_backend
    mock_backend.translate_sentences.assert_called_once()
    called_sents = mock_backend.translate_sentences.call_args[0][0]
    assert len(called_sents) == 1
    assert "Perused the record." not in called_sents


def test_engine_profile_beam_size_propagation() -> None:
    mock_backend = MagicMock()
    mock_backend.translate_sentences.return_value = BackendTranslationResult(
        sentences=["अनुवाद"],
        device="cpu",
    )

    engine = CTranslate2TranslationEngine(backend=mock_backend)

    # 1. Instant profile
    engine.translate(
        "Custom sentence one.",
        direction=TranslationDirection.EN_TO_HI,
        execution_profile=ExecutionProfile.INSTANT,
    )
    assert mock_backend.translate_sentences.call_args.kwargs.get("execution_profile") == ExecutionProfile.INSTANT

    # 2. Accurate profile
    engine.translate(
        "Custom sentence two.",
        direction=TranslationDirection.EN_TO_HI,
        execution_profile=ExecutionProfile.ACCURATE,
    )
    assert mock_backend.translate_sentences.call_args.kwargs.get("execution_profile") == ExecutionProfile.ACCURATE


def test_backend_length_bucketing_and_beam_size(tmp_path: Any, monkeypatch: Any) -> None:
    from types import SimpleNamespace

    from sarathi.shakti.translation.engine import CTranslate2NativeBackend

    captured_calls: list[dict[str, Any]] = []

    class FakeTranslator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def translate_batch(self, tokenized: Any, **kwargs: Any) -> Any:
            captured_calls.append({"tokenized": tokenized, "kwargs": kwargs})
            # Return hypotheses matching length of input tokens to verify order restoration
            return [SimpleNamespace(hypotheses=[tok]) for tok in tokenized]

    class FakeSPM:
        def encode_as_pieces(self, text: str) -> list[str]:
            # Returns pieces whose length matches the word count
            return text.split()

        def decode_pieces(self, pieces: list[str]) -> str:
            return " ".join(pieces)

    import ctranslate2

    monkeypatch.setattr(ctranslate2, "Translator", FakeTranslator)

    model_dir = tmp_path / "models" / "indictrans2" / "hi-en"
    model_dir.mkdir(parents=True)
    (model_dir / "spm.model").write_bytes(b"dummy")
    (model_dir / "model.bin").write_bytes(b"dummy")

    backend = CTranslate2NativeBackend(root=tmp_path, manifest={})
    backend._spms[f"src:{(model_dir / 'spm.model').resolve()}"] = FakeSPM()
    backend._spms[f"tgt:{(model_dir / 'spm.model').resolve()}"] = FakeSPM()

    # Pass 3 sentences with varying lengths: 4 words, 1 word, 3 words
    sents = ["four words sentence here", "one", "three words now"]

    # 1. Test Instant profile (beam_size=1)
    res_instant = backend.translate_sentences(
        sents,
        direction=TranslationDirection.HI_TO_EN,
        execution_profile=ExecutionProfile.INSTANT,
    )

    call_instant = captured_calls[-1]
    assert call_instant["kwargs"]["beam_size"] == 1

    # Verify input to translator was sorted by token count
    tokenized_lengths = [len(tok) for tok in call_instant["tokenized"]]
    assert tokenized_lengths == sorted(tokenized_lengths)

    # Verify output was restored to original 1-to-1 order
    assert len(res_instant.sentences) == 3
    assert "four words sentence here" in res_instant.sentences[0]
    assert "one" in res_instant.sentences[1]
    assert "three words now" in res_instant.sentences[2]

    # 2. Test Accurate profile (beam_size=4)
    res_acc = backend.translate_sentences(
        sents,
        direction=TranslationDirection.HI_TO_EN,
        execution_profile=ExecutionProfile.ACCURATE,
    )
    call_acc = captured_calls[-1]
    assert call_acc["kwargs"]["beam_size"] == 4
    assert len(res_acc.sentences) == 3

