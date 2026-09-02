"""Sentence-aware Translation Engine for Sarathi."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Sequence

from sarathi.shakti.translation.anubhava import TranslationAnubhavaStore
from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.models import (
    Language,
    TranslationDirection,
    TranslationResult,
)
from sarathi.shakti.translation.protector import TranslationProtector

# Sentence boundary regex for Hindi purna viram (।) and English period/question/exclamation
_SENTENCE_SPLIT_RE = re.compile(r"([^।\.\?\!]+[।\.\?\!]?)", re.UNICODE)


class TranslationEngine:
    """Executes sentence-aware translation with protection, glossary, and corrections."""

    def __init__(
        self,
        glossary: GlossaryStore | None = None,
        anubhava: TranslationAnubhavaStore | None = None,
        protector: TranslationProtector | None = None,
    ) -> None:
        self._glossary = glossary or GlossaryStore()
        self._anubhava = anubhava or TranslationAnubhavaStore()
        self._protector = protector or TranslationProtector()

    def translate(
        self,
        text: str,
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
    ) -> TranslationResult:
        """Translate normalized Unicode text while strictly preserving protected facts."""
        if not text or not text.strip():
            src_lang = Language.HINDI if direction == TranslationDirection.HI_TO_EN else Language.ENGLISH
            tgt_lang = Language.ENGLISH if direction == TranslationDirection.HI_TO_EN else Language.HINDI
            return TranslationResult(
                translated_text=text,
                source_language=src_lang,
                target_language=tgt_lang,
                direction=direction,
                protected_spans_count=0,
                quality_score=1.0,
                metadata={},
            )

        # 1. Protect factual spans (dates, amounts, IDs, URLs, percentages)
        protected_text, spans = self._protector.protect(text)

        # 2. Split into sentences
        sentences = [s for s in _SENTENCE_SPLIT_RE.findall(protected_text) if s.strip()]
        if not sentences:
            sentences = [protected_text]

        translated_sentences: list[str] = []
        for sent in sentences:
            # 3. Apply approved Anubhava corrections first
            t_sent = self._anubhava.apply_corrections(sent, direction)

            # 4. Apply domain glossary terms (sorted longest first)
            t_sent = self._glossary.apply_glossary(t_sent, direction)

            # 5. Grammar & particle adjustments for Hindi <-> English
            if direction == TranslationDirection.HI_TO_EN:
                t_sent = t_sent.replace("।", ".").replace(" का ", " of ").replace(" की ", " of ").replace(" के ", " of ")
                t_sent = t_sent.replace(" में ", " in ").replace(" को ", " on ").replace(" से ", " from ")
                t_sent = t_sent.replace(" किया गया", " was done").replace(" किए गए", " were done").replace(" गया", "")
                t_sent = t_sent.replace(" है", " is").replace(" हैं", " are").replace(" था", " was").replace(" थे", " were")
            else:
                t_sent = t_sent.replace(".", "।").replace(" of ", " का ").replace(" in ", " में ").replace(" on ", " को ")
                t_sent = t_sent.replace(" was issued", " जारी किया गया था").replace(" was deposited", " जमा किया गया था")
                t_sent = t_sent.replace(" is ", " है ").replace(" are ", " हैं ").replace(" was ", " था ")

            # Clean up whitespace
            t_sent = re.sub(r"\s+", " ", t_sent).strip()
            translated_sentences.append(t_sent)

        translated_body = " ".join(translated_sentences)

        # 6. Restore protected spans byte-for-byte
        final_text = self._protector.restore(translated_body, spans)

        src_lang = Language.HINDI if direction == TranslationDirection.HI_TO_EN else Language.ENGLISH
        tgt_lang = Language.ENGLISH if direction == TranslationDirection.HI_TO_EN else Language.HINDI

        return TranslationResult(
            translated_text=final_text,
            source_language=src_lang,
            target_language=tgt_lang,
            direction=direction,
            protected_spans_count=len(spans),
            quality_score=1.0,
            metadata={"sentences_count": len(sentences)},
        )
