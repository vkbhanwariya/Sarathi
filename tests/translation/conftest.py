"""Shared test fixtures and deterministic backend for translation tests."""

import json
import re
from pathlib import Path
from typing import Any, Sequence

import pytest

from sarathi.shakti.translation.models import TranslationDirection

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "bilingual_corpus.json"
_PLACEHOLDER_RE = re.compile(r"[\uE000-\uE001\uE100-\uE1FF]+|999\d{4}")
_DATE_RE = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_NUM_RE = re.compile(r"(?:Rs\.?|₹|\$|€|£)?\s*\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\b")
_ID_RE = re.compile(
    r"\b(?=[A-Za-z0-9_-]{4,}\b)(?:[A-Za-z]+[0-9]|[0-9]+[A-Za-z])[A-Za-z0-9_-]*\b"
    r"|\b[A-Za-z0-9]{2,}(?:[-_][A-Za-z0-9]+)+\b"
)


def _slotize(text: str) -> str:
    s = _DATE_RE.sub("__SLOT__", text)
    s = _NUM_RE.sub("__SLOT__", s)
    s = _ID_RE.sub("__SLOT__", s)
    s = _PLACEHOLDER_RE.sub("__SLOT__", s)
    return s


class DeterministicTestBackend:
    """Test-local deterministic translator adapter matching verified bilingual corpus."""

    def __init__(self, corpus_path: Path = _FIXTURE_PATH) -> None:
        from sarathi.shakti.translation.glossary import GlossaryStore
        from sarathi.shakti.translation.protector import TranslationProtector

        self._corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        self._glossary = GlossaryStore()
        self._protector = TranslationProtector()

        self._precomputed: dict[str, list[dict[str, Any]]] = {}
        for direction in (TranslationDirection.HI_TO_EN, TranslationDirection.EN_TO_HI):
            terms = self._glossary.get_terms(direction)
            items = []
            for raw_item in self._corpus:
                if raw_item["direction"] != direction.value:
                    continue
                src = raw_item["source"].strip()
                tgt = raw_item["target"].strip()
                p_src, p_spans = self._protector.protect(src, glossary_mappings=terms)
                norm_p_src = _PLACEHOLDER_RE.sub("__SLOT__", p_src.strip())
                norm_src = _slotize(src)
                glossary_applied = self._glossary.apply_glossary(src, direction)
                glossary_src = _slotize(glossary_applied)
                norm_tgt = _slotize(tgt)
                items.append(
                    {
                        "src": src,
                        "tgt": tgt,
                        "p_spans": p_spans,
                        "norm_p_src": norm_p_src,
                        "norm_src": norm_src,
                        "glossary_src": glossary_src,
                        "glossary_applied_str": glossary_applied.strip(),
                        "norm_tgt": norm_tgt,
                    }
                )
            self._precomputed[direction.value] = items

    def translate_sentences(
        self,
        sentences: Sequence[str],
        direction: TranslationDirection,
        execution_binding: Any = None,
        **kwargs: Any,
    ) -> list[str]:
        results = []
        precomputed_items = self._precomputed.get(direction.value, [])
        for s in sentences:
            s_stripped = s.strip()
            placeholders = _PLACEHOLDER_RE.findall(s)
            norm_s = _PLACEHOLDER_RE.sub("__SLOT__", s_stripped)
            matched = False

            for item in precomputed_items:
                if (
                    norm_s == item["norm_p_src"]
                    or norm_s == item["norm_src"]
                    or s_stripped == item["src"]
                    or norm_s == item["glossary_src"]
                    or s_stripped == item["glossary_applied_str"]
                ):
                    out_sent = item["tgt"]
                    for span in item["p_spans"]:
                        if span.original_text in out_sent:
                            out_sent = out_sent.replace(span.original_text, span.placeholder, 1)
                    if out_sent == item["tgt"] and placeholders:
                        out_sent = item["norm_tgt"]
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
