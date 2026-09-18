"""Locked CTranslate2 + IndicTrans2 + SentencePiece Translation Engine for Sarathi."""

from __future__ import annotations

import json
import os
import re
import threading
import tomllib
from pathlib import Path
from typing import Any, Protocol, Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import DeviceType, ExecutionBinding
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
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to parse translation Anubhava TOML: {anubhava_file.name}",
        ) from exc
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

    def translate_sentences(
        self,
        sentences: Sequence[str],
        direction: TranslationDirection,
        execution_binding: ExecutionBinding | None = None,
        **kwargs: Any,
    ) -> list[str] | tuple[list[str], str]:
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
        self._backend_lock: threading.Lock = threading.Lock()
        self._asset_version: str = self._compute_asset_version()

    def _compute_asset_version(self) -> str:
        import hashlib

        hasher = hashlib.sha256()
        manifest_path = self._data_root / "manifest.json"
        if manifest_path.is_file():
            try:
                st = manifest_path.stat()
                hasher.update(f"manifest:{st.st_size}:{st.st_mtime_ns}".encode("utf-8"))
                hasher.update(manifest_path.read_bytes())
            except OSError:
                pass
        anubhava_file = self._data_root / "anubhava.toml"
        if anubhava_file.is_file():
            try:
                st = anubhava_file.stat()
                hasher.update(f"anubhava:{st.st_size}:{st.st_mtime_ns}".encode("utf-8"))
                hasher.update(anubhava_file.read_bytes())
            except OSError:
                pass
        for g_name in ("glossary.yaml", "glossary.yml"):
            g_path = self._data_root / g_name
            if g_path.is_file():
                try:
                    st = g_path.stat()
                    hasher.update(f"{g_name}:{st.st_size}:{st.st_mtime_ns}".encode("utf-8"))
                    hasher.update(g_path.read_bytes())
                except OSError:
                    pass
        glossary_dir = self._data_root / "glossaries"
        if glossary_dir.is_dir():
            try:
                for p in sorted(glossary_dir.iterdir()):
                    if p.is_file() and p.suffix.lower() in (".json", ".yaml", ".yml"):
                        st = p.stat()
                        hasher.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode("utf-8"))
                        hasher.update(p.read_bytes())
            except OSError:
                pass
        return hasher.hexdigest()[:16]

    @property
    def asset_version(self) -> str:
        return self._asset_version

    def warmup(self, execution_binding: ExecutionBinding | None = None) -> bool:
        """Pre-initialize CTranslate2 engine and load neural weights."""
        try:
            self._ensure_backend()
            return True
        except Exception:
            return False

    def _ensure_backend(self) -> TranslatorBackend:
        """Validate local CTranslate2 model manifest/assets and initialize backend."""
        if self._backend is not None:
            return self._backend

        if self._initialized_backend is not None:
            return self._initialized_backend

        with self._backend_lock:
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
                    self._lock: threading.Lock = threading.Lock()

                def translate_sentences(
                    self,
                    sentences: Sequence[str],
                    direction: TranslationDirection,
                    execution_binding: ExecutionBinding | None = None,
                    engine: str = "indictrans2",
                    **kwargs: Any,
                ) -> tuple[list[str], str]:
                    # Native model inference using CTranslate2 and SentencePiece
                    dir_key = direction.value
                    norm_engine = str(engine or "indictrans2").lower().strip()
                    if norm_engine == "opus_mt":
                        model_path = self._root / "models" / "opus_mt" / dir_key
                        if not model_path.exists():
                            model_path = self._root / "models" / f"opus_{dir_key}"
                        if not model_path.exists():
                            model_path = self._root / "models" / dir_key
                        spm_src_path = model_path / "spm.model"
                        spm_tgt_path = spm_src_path
                        if not model_path.exists() or not spm_src_path.exists():
                            raise DoshError(
                                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                                message=f"Model assets for OPUS-MT translation direction '{dir_key}' are missing or incomplete.",
                            )
                        model_info = {}
                    else:
                        model_info = self._manifest.get("models", {}).get(dir_key) or {}
                        if not model_info and dir_key not in ("hi-en", "en-hi"):
                            raise DoshError(
                                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                                message=f"Model for direction '{dir_key}' not declared in manifest.",
                            )
                        # Check indictrans2 subdirectory first, then fallback to root models
                        model_path = self._root / "models" / "indictrans2" / dir_key
                        if not (model_path.exists() and any((model_path / f).exists() for f in ("model.bin", "model.SRC", "spm.model"))):
                            model_path = self._root / "models" / dir_key

                        # Resolve source SentencePiece model
                        if (model_path / "model.SRC").is_file():
                            spm_src_path = model_path / "model.SRC"
                        elif (model_path / "src_spm.model").is_file():
                            spm_src_path = model_path / "src_spm.model"
                        else:
                            spm_src_path = model_path / "spm.model"

                        # Resolve target SentencePiece model
                        if (model_path / "model.TGT").is_file():
                            spm_tgt_path = model_path / "model.TGT"
                        elif (model_path / "tgt_spm.model").is_file():
                            spm_tgt_path = model_path / "tgt_spm.model"
                        else:
                            spm_tgt_path = spm_src_path

                        if not model_path.exists() or not spm_src_path.exists():
                            raise DoshError(
                                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                                message=f"Model assets for translation direction '{dir_key}' are missing or incomplete.",
                            )

                    device = "cpu"
                    device_index = 0
                    if execution_binding is not None and execution_binding.device_type == DeviceType.GPU:
                        try:
                            if hasattr(ctranslate2, "get_cuda_device_count") and ctranslate2.get_cuda_device_count() > 0:
                                device = "cuda"
                                dev_str = str(execution_binding.backend_device_id).strip()
                                if ":" in dev_str:
                                    dev_str = dev_str.split(":")[-1]
                                try:
                                    device_index = int(dev_str)
                                except ValueError:
                                    device_index = 0
                        except Exception:
                            device = "cpu"

                    cpu_fn = getattr(os, "process_cpu_count", None)
                    cpu_count = cpu_fn() if callable(cpu_fn) else os.cpu_count() or 4
                    default_concurrency = max(1, min(4, cpu_count // 4))

                    approved = (
                        execution_binding.approved_concurrency
                        if execution_binding is not None and execution_binding.approved_concurrency > 0
                        else default_concurrency
                    )
                    if device == "cpu":
                        # Thread budget invariant: scale worker processes and intra-threads to saturate CPU
                        # without thrashing: inter_threads * intra_threads <= host logical capacity
                        inter_threads = max(1, min(4, approved))
                        intra_threads = max(2, min(6, (cpu_count + 1) // inter_threads))
                    else:
                        inter_threads = approved
                        intra_threads = 0

                    trans_key = f"{norm_engine}:{model_path.resolve()}:{dir_key}:{device}:{device_index}:{inter_threads}:{intra_threads}"
                    spm_src_key = f"src:{spm_src_path.resolve()}"
                    spm_tgt_key = f"tgt:{spm_tgt_path.resolve()}"
                    with self._lock:
                        if trans_key not in self._translators:
                            try:
                                self._translators[trans_key] = ctranslate2.Translator(
                                    str(model_path),
                                    device=device,
                                    device_index=device_index,
                                    inter_threads=inter_threads,
                                    intra_threads=intra_threads,
                                )
                            except Exception as exc:
                                raise DoshError(
                                    code=FailureCode.EXECUTION_FAILED,
                                    message=(
                                        f"Failed to initialize translation model for direction '{dir_key}' "
                                        f"on device '{device}:{device_index}': {exc}"
                                    ),
                                ) from exc

                        if spm_src_key not in self._spms:
                            sp_src = sentencepiece.SentencePieceProcessor()
                            sp_src.load(str(spm_src_path))
                            self._spms[spm_src_key] = sp_src

                        if spm_tgt_key not in self._spms:
                            sp_tgt = sentencepiece.SentencePieceProcessor()
                            sp_tgt.load(str(spm_tgt_path))
                            self._spms[spm_tgt_key] = sp_tgt

                        translator = self._translators[trans_key]
                        spm_src = self._spms[spm_src_key]
                        spm_tgt = self._spms[spm_tgt_key]

                    if norm_engine == "indictrans2":
                        src_tag = model_info.get("source_lang", "hin_Deva" if dir_key == "hi-en" else "eng_Latn")
                        tgt_tag = model_info.get("target_lang", "eng_Latn" if dir_key == "hi-en" else "hin_Deva")
                        tokenized = [[src_tag, tgt_tag] + spm_src.encode_as_pieces(s) for s in sentences]
                    else:
                        tokenized = [spm_src.encode_as_pieces(s) for s in sentences]

                    # Token-based batching bounds token count per forward pass, eliminating tail latency
                    # on uneven sentence lengths while distributing work across worker threads.
                    results = translator.translate_batch(
                        tokenized,
                        batch_type="tokens",
                        max_batch_size=1024,
                    )

                    decoded_sentences: list[str] = []
                    for r in results:
                        text = spm_tgt.decode_pieces(r.hypotheses[0])
                        if norm_engine == "indictrans2":
                            for tag in ("hin_Deva", "eng_Latn", "<s>", "</s>", "<unk>", "\u2047", "Â"):
                                text = text.replace(tag, "")
                        text = text.replace("\u2581", " ")
                        text = " ".join(text.split())
                        decoded_sentences.append(text.strip())

                    return decoded_sentences, device

            self._initialized_backend = _CTranslate2NativeBackend(self._data_root, manifest_dict)
            return self._initialized_backend

    def translate(
        self,
        text: str,
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
        execution_binding: ExecutionBinding | None = None,
        engine: str = "indictrans2",
    ) -> TranslationResult:
        """Translate normalized Unicode text via CTranslate2 with span protection and glossary."""
        src_lang = Language.HINDI if direction == TranslationDirection.HI_TO_EN else Language.ENGLISH
        tgt_lang = Language.ENGLISH if direction == TranslationDirection.HI_TO_EN else Language.HINDI

        target_device = "cpu"
        if execution_binding is not None and execution_binding.device_type == DeviceType.GPU:
            target_device = execution_binding.backend_device_id or "cuda"

        norm_engine = str(engine or "indictrans2").lower().strip()

        if not text or not text.strip():
            return TranslationResult(
                translated_text=text,
                source_language=src_lang,
                target_language=tgt_lang,
                direction=direction,
                protected_spans_count=0,
                metadata={"device": target_device, "backend": "ctranslate2", "engine": norm_engine},
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
        try:
            backend_res = backend.translate_sentences(
                prepared_sentences, direction, execution_binding=execution_binding, engine=norm_engine
            )
        except TypeError:
            backend_res = backend.translate_sentences(
                prepared_sentences, direction, execution_binding=execution_binding
            )

        if isinstance(backend_res, tuple) and len(backend_res) == 2:
            translated_sentences, factual_device = backend_res
        else:
            translated_sentences = backend_res
            factual_device = target_device

        translated_body = " ".join(translated_sentences)

        # 5. Restore protected spans byte-for-byte with integrity verification
        final_text, span_issues = self._protector.restore_with_validation(translated_body, spans)

        metadata: dict[str, Any] = {
            "sentences_count": len(raw_sentences),
            "device": factual_device,
            "backend": "ctranslate2",
            "engine": norm_engine,
        }
        if span_issues:
            metadata["span_protection_issues"] = tuple(span_issues)

        return TranslationResult(
            translated_text=final_text,
            source_language=src_lang,
            target_language=tgt_lang,
            direction=direction,
            protected_spans_count=len(spans),
            metadata=metadata,
        )

    def translate_batch(
        self,
        texts: Sequence[str],
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
        execution_binding: ExecutionBinding | None = None,
        engine: str = "indictrans2",
    ) -> list[TranslationResult]:
        """Translate a batch of normalized texts via CTranslate2 with multi-core batch decoder."""
        if not texts:
            return []

        src_lang = Language.HINDI if direction == TranslationDirection.HI_TO_EN else Language.ENGLISH
        tgt_lang = Language.ENGLISH if direction == TranslationDirection.HI_TO_EN else Language.HINDI
        target_device = "cpu"
        if execution_binding is not None and execution_binding.device_type == DeviceType.GPU:
            target_device = execution_binding.backend_device_id or "cuda"

        norm_engine = str(engine or "indictrans2").lower().strip()
        glossary_terms = self._glossary.get_terms(direction)
        dir_key = direction.value

        text_slices: list[tuple[int, int, list[tuple[str, str]], int]] = []
        all_prepared_sentences: list[str] = []

        for idx, text in enumerate(texts):
            if not text or not text.strip():
                text_slices.append((idx, 0, [], 0))
                continue

            protected_text, spans = self._protector.protect(text, glossary_mappings=glossary_terms)
            raw_sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.findall(protected_text) if s.strip()]
            if not raw_sentences:
                raw_sentences = [protected_text]

            start_idx = len(all_prepared_sentences)
            for sent in raw_sentences:
                for d in (dir_key, "both"):
                    for src_c, tgt_c in self._anubhava_corrections.get(d, {}).items():
                        sent = sent.replace(src_c, tgt_c)
                all_prepared_sentences.append(sent)

            text_slices.append((idx, len(raw_sentences), spans, start_idx))

        factual_device = target_device
        all_translated_sentences: list[str] = []
        if all_prepared_sentences:
            backend = self._ensure_backend()
            try:
                backend_res = backend.translate_sentences(
                    all_prepared_sentences, direction, execution_binding=execution_binding, engine=norm_engine
                )
            except TypeError:
                backend_res = backend.translate_sentences(
                    all_prepared_sentences, direction, execution_binding=execution_binding
                )

            if isinstance(backend_res, tuple) and len(backend_res) == 2:
                all_translated_sentences, factual_device = backend_res
            else:
                all_translated_sentences = backend_res

        results: list[TranslationResult] = []
        for idx, sent_count, spans, start_idx in text_slices:
            orig_text = texts[idx]
            if sent_count == 0 or not orig_text or not orig_text.strip():
                results.append(
                    TranslationResult(
                        translated_text=orig_text,
                        source_language=src_lang,
                        target_language=tgt_lang,
                        direction=direction,
                        protected_spans_count=0,
                        metadata={"device": target_device, "backend": "ctranslate2", "engine": norm_engine},
                    )
                )
                continue

            sents = all_translated_sentences[start_idx : start_idx + sent_count]
            translated_body = " ".join(sents)
            final_text, span_issues = self._protector.restore_with_validation(translated_body, spans)

            metadata: dict[str, Any] = {
                "sentences_count": sent_count,
                "device": factual_device,
                "backend": "ctranslate2",
                "engine": norm_engine,
            }
            if span_issues:
                metadata["span_protection_issues"] = tuple(span_issues)

            results.append(
                TranslationResult(
                    translated_text=final_text,
                    source_language=src_lang,
                    target_language=tgt_lang,
                    direction=direction,
                    protected_spans_count=len(spans),
                    metadata=metadata,
                )
            )

        return results
