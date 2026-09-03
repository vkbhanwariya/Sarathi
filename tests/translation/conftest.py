"""Shared test fixtures and deterministic backend for translation tests."""

import json
import re
from pathlib import Path
from typing import Sequence

import pytest

from sarathi.shakti.translation.models import TranslationDirection

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "bilingual_corpus.json"
_PUA_RE = re.compile(r"[\uE000-\uE001\uE100-\uE1FF]+")
_DATE_RE = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_NUM_RE = re.compile(r"(?:Rs\.?|₹|\$|€|£)?\s*\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\b")
_ID_RE = re.compile(r"\b[A-Z0-9_-]{4,}\b")


def _slotize(text: str) -> str:
    s = _DATE_RE.sub("__SLOT__", text)
    s = _NUM_RE.sub("__SLOT__", s)
    s = _ID_RE.sub("__SLOT__", s)
    return s


class DeterministicTestBackend:
    """Test-local deterministic translator adapter matching verified bilingual corpus."""

    def __init__(self, corpus_path: Path = _FIXTURE_PATH) -> None:
        self._corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    def translate_sentences(self, sentences: Sequence[str], direction: TranslationDirection) -> list[str]:
        results = []
        for s in sentences:
            placeholders = _PUA_RE.findall(s)
            norm_s = _PUA_RE.sub("__SLOT__", s.strip())
            matched = False

            for item in self._corpus:
                if item["direction"] != direction.value:
                    continue
                src = item["source"].strip()
                tgt = item["target"].strip()

                from sarathi.shakti.translation.glossary import GlossaryStore
                from sarathi.shakti.translation.protector import TranslationProtector

                glossary = GlossaryStore()
                protector = TranslationProtector()
                p_src, p_spans = protector.protect(src, glossary_mappings=glossary.get_terms(direction))
                norm_p_src = _PUA_RE.sub("__SLOT__", p_src.strip())

                norm_src = _slotize(src)
                glossary_src = _slotize(glossary.apply_glossary(src, direction))

                if (
                    norm_s == norm_p_src
                    or norm_s == norm_src
                    or s.strip() == src
                    or norm_s == glossary_src
                    or s.strip() == glossary.apply_glossary(src, direction).strip()
                ):
                    out_sent = tgt
                    for span in p_spans:
                        if span.original_text in out_sent:
                            out_sent = out_sent.replace(span.original_text, span.placeholder, 1)
                    if out_sent == tgt and placeholders:
                        norm_tgt = _slotize(tgt)
                        out_sent = norm_tgt
                        for p in placeholders:
                            out_sent = out_sent.replace("__SLOT__", p, 1)
                    results.append(out_sent)
                    matched = True
                    break

            if not matched:
                results.append(s)

        return results


@pytest.fixture
def test_backend() -> DeterministicTestBackend:
    return DeterministicTestBackend()
