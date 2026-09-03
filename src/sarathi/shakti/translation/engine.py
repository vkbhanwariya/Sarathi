"""Locked CTranslate2 + IndicTrans2 + SentencePiece Translation Engine for Sarathi."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, Protocol, Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.models import (
    Language,
    TranslationDirection,
    TranslationResult,
)
from sarathi.shakti.translation.protector import TranslationProtector
from sarathi.sutra import get_canonical_data_root

_CANONICAL_TRANSLATION_DATA_DIR = get_canonical_data_root() / "translation"
_SENTENCE_SPLIT_RE = re.compile(r"([^।\.\?\!\n]+[।\.\?\!]?)", re.UNICODE)


def _load_translation_anubhava(data_root: Path) -> dict[str, dict[str, str]]:
    """Load approved translation corrections directly from capability-owned anubhava.toml."""
    anubhava_file = data_root / "anubhava.toml"
    if not anubhava_file.exists():
        return {}
    try:
        data = tomllib.loads(anubhava_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    corrections: dict[str, dict[str, str]] = {}
    for item in data.get("corrections", []):
        if isinstance(item, dict) and (
            item.get("verified", False) or item.get("verified_on") or item.get("approved_by")
        ):
            dir_val = item.get("direction", "both")
            src = item.get("source", "")
            tgt = item.get("target", "")
            if src and tgt:
                corrections.setdefault(dir_val, {})[src] = tgt
    return corrections


class TranslatorBackend(Protocol):
    """Protocol for local model inference backend."""

    def translate_sentences(self, sentences: Sequence[str], direction: TranslationDirection) -> list[str]:
        """Translate a batch of sentences."""
        ...


class CTranslate2TranslationEngine:
    """Instance-owned CTranslate2 + IndicTrans2 engine adapter."""

    def __init__(
        self,
        data_root: Path | None = None,
        backend: TranslatorBackend | None = None,
        glossary: GlossaryStore | None = None,
        protector: TranslationProtector | None = None,
    ) -> None:
        self._data_root = (data_root or _CANONICAL_TRANSLATION_DATA_DIR).resolve()
        self._backend = backend
        self._glossary = glossary or GlossaryStore(glossary_dir=self._data_root)
        self._anubhava_corrections = _load_translation_anubhava(self._data_root)
        self._protector = protector or TranslationProtector()
        self._initialized_backend: TranslatorBackend | None = None

    def _ensure_backend(self) -> TranslatorBackend:
        """Validate local CTranslate2 model manifest/assets and initialize backend."""
        if self._backend is not None:
            return self._backend

        if self._initialized_backend is not None:
            return self._initialized_backend

        manifest_file = self._data_root / "manifest.json"
        models_dir = self._data_root / "models"

        if not manifest_file.exists():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Required local translation model manifest is missing.",
            )

        try:
            manifest_dict = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Failed to read or parse local translation model manifest.",
            ) from exc

        if not models_dir.exists() or not models_dir.is_dir():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Required local translation models directory is missing.",
            )

        try:
            import importlib

            ctranslate2 = importlib.import_module("ctranslate2")
            sentencepiece = importlib.import_module("sentencepiece")
        except ImportError as exc:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Translation dependencies (ctranslate2, sentencepiece) are not installed.",
            ) from exc

        # When model directory and packages exist, configure local CTranslate2 translator
        class _CTranslate2NativeBackend:
            def __init__(self, root: Path, manifest: dict[str, Any]) -> None:
                self._root = root
                self._manifest = manifest
                self._translators: dict[str, Any] = {}
                self._spms: dict[str, Any] = {}

            def translate_sentences(self, sentences: Sequence[str], direction: TranslationDirection) -> list[str]:
                # Native model inference using CTranslate2 and SentencePiece
                dir_key = direction.value
                model_info = self._manifest.get("models", {}).get(dir_key)
                if not model_info:
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message=f"Model for direction '{dir_key}' not declared in manifest.",
                    )
                model_path = self._root / "models" / dir_key
                spm_path = model_path / "spm.model"
                if not model_path.exists() or not spm_path.exists():
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message=f"Model assets for translation direction '{dir_key}' are missing or incomplete.",
                    )
                if dir_key not in self._translators:
                    self._translators[dir_key] = ctranslate2.Translator(str(model_path))
                    sp = sentencepiece.SentencePieceProcessor()
                    sp.load(str(spm_path))
                    self._spms[dir_key] = sp

                translator = self._translators[dir_key]
                spm = self._spms[dir_key]
                tokenized = [spm.encode_as_pieces(s) for s in sentences]
                results = translator.translate_batch(tokenized)
                return [spm.decode_pieces(r.hypotheses[0]) for r in results]

        self._initialized_backend = _CTranslate2NativeBackend(self._data_root, manifest_dict)
        return self._initialized_backend

    def translate(
        self,
        text: str,
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
    ) -> TranslationResult:
        """Translate normalized Unicode text via CTranslate2 with span protection and glossary."""
        src_lang = Language.HINDI if direction == TranslationDirection.HI_TO_EN else Language.ENGLISH
        tgt_lang = Language.ENGLISH if direction == TranslationDirection.HI_TO_EN else Language.HINDI

        if not text or not text.strip():
            return TranslationResult(
                translated_text=text,
                source_language=src_lang,
                target_language=tgt_lang,
                direction=direction,
                protected_spans_count=0,
                metadata={},
            )

        # 1. Retrieve domain glossary mappings for this direction
        glossary_terms = self._glossary.get_terms(direction)

        # 2. Protect factual spans and domain glossary terms (Finding 37)
        protected_text, spans = self._protector.protect(text, glossary_mappings=glossary_terms)

        # 3. Split into sentences
        raw_sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.findall(protected_text) if s.strip()]
        if not raw_sentences:
            raw_sentences = [protected_text]

        # 4. Pre-process sentences: apply approved Anubhava overrides
        prepared_sentences: list[str] = []
        for sent in raw_sentences:
            dir_key = direction.value
            for d in (dir_key, "both"):
                for src_c, tgt_c in self._anubhava_corrections.get(d, {}).items():
                    sent = sent.replace(src_c, tgt_c)
            prepared_sentences.append(sent)

        # 4. Neural translation via CTranslate2 backend (fails with DEPENDENCY_UNAVAILABLE if missing)
        backend = self._ensure_backend()
        translated_sentences = backend.translate_sentences(prepared_sentences, direction)

        translated_body = " ".join(translated_sentences)

        # 5. Restore protected spans byte-for-byte
        final_text = self._protector.restore(translated_body, spans)

        return TranslationResult(
            translated_text=final_text,
            source_language=src_lang,
            target_language=tgt_lang,
            direction=direction,
            protected_spans_count=len(spans),
            metadata={"sentences_count": len(raw_sentences)},
        )
