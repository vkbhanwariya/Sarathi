"""Locked CTranslate2 + IndicTrans2 + SentencePiece Translation Engine for Sarathi."""

from __future__ import annotations

import json
import os
import re
import threading
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import DeviceType, ExecutionBinding
from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.harmonizer import GlossaryHarmonizer
from sarathi.shakti.translation.models import (
    Language,
    TranslationDirection,
    TranslationResult,
)
from sarathi.shakti.translation.proper_noun_guard import ProperNounGuard
from sarathi.shakti.translation.protector import TranslationProtector
from sarathi.sutra import get_canonical_data_root

_CANONICAL_TRANSLATION_DATA_DIR = get_canonical_data_root() / "translation"

DEFAULT_BEAM_SIZE: int = 4
DEFAULT_MAX_DECODING_LENGTH: int = 512
MAX_SENTENCE_TOKENS: int = 256

_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sec",
        "no",
        "nos",
        "hon",
        "rs",
        "vs",
        "etc",
        "ltd",
        "pvt",
        "smt",
        "shri",
        "adv",
        "art",
        "cl",
        "ch",
        "vol",
        "ors",
        "anr",
        "i.e",
        "e.g",
        "approx",
        "al",
        "para",
        "viz",
        "ex",
        "dept",
        "govt",
        "dist",
        "st",
        "sq",
        "ft",
        "in",
        "yd",
        "corp",
        "inc",
        "co",
        "repr",
        "gen",
        "col",
        "maj",
        "capt",
        "lt",
        "mla",
        "mp",
        "cj",
        "acj",
        "j",
        "jj",
    }
)

_SPLIT_CHARS: frozenset[str] = frozenset({"।", "?", "!", "."})
_CLOSING_CHARS: frozenset[str] = frozenset({'"', "'", "”", "’", ")", "]", "}"})


def split_sentences(text: str) -> list[tuple[str, str]]:
    """Split text into sentence segments and trailing separators without breaking abbreviations.

    Returns a list of (segment, trailing_separator) tuples such that
    "".join(seg + sep for seg, sep in split_sentences(text)) == text.
    """
    if not text:
        return []

    n = len(text)
    splits: list[tuple[str, str]] = []
    seg_start = 0
    i = 0

    while i < n:
        ch = text[i]
        if ch in _SPLIT_CHARS:
            # Check 1: Inside decimal number? E.g. 5.50
            if ch == "." and i > 0 and text[i - 1].isdigit() and i + 1 < n and text[i + 1].isdigit():
                i += 1
                continue

            # Check 2: Abbreviation or single-letter initial?
            if ch == ".":
                w_end = i
                w_start = w_end - 1
                while w_start >= 0 and (text[w_start].isalpha() or text[w_start] == "."):
                    w_start -= 1
                word = text[w_start + 1 : w_end].lower().rstrip(".")
                if word in _ABBREVIATIONS:
                    i += 1
                    continue
                if len(word) == 1 and word.isalpha():
                    i += 1
                    continue

            # Scan any immediately following closing quotes/brackets
            punct_end = i + 1
            while punct_end < n and text[punct_end] in _CLOSING_CHARS:
                punct_end += 1

            if punct_end >= n:
                seg = text[seg_start:punct_end]
                splits.append((seg, ""))
                seg_start = punct_end
                i = punct_end
                break

            ws_end = punct_end
            while ws_end < n and text[ws_end].isspace():
                ws_end += 1

            if ws_end > punct_end:
                if ws_end >= n:
                    seg = text[seg_start:punct_end]
                    sep = text[punct_end:ws_end]
                    splits.append((seg, sep))
                    seg_start = ws_end
                    i = ws_end
                    break

                next_ch = text[ws_end]
                if next_ch.isupper() or ("\u0900" <= next_ch <= "\u097f") or next_ch.isdigit():
                    seg = text[seg_start:punct_end]
                    sep = text[punct_end:ws_end]
                    splits.append((seg, sep))
                    seg_start = ws_end
                    i = ws_end
                    continue

        i += 1

    if seg_start < n:
        splits.append((text[seg_start:], ""))

    return splits


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


@lru_cache(maxsize=1024)
def _compile_anubhava_pattern(src: str) -> re.Pattern[str]:
    """Compile boundary-aware pattern for Anubhava correction ensuring whole-word Devanagari matching."""
    return re.compile(rf"(?<![\u0900-\u097F\w]){re.escape(src)}(?![\u0900-\u097F\w])")


@dataclass(frozen=True, slots=True)
class BackendTranslationResult:
    """Typed result from local model translation backend."""

    sentences: list[str]
    device: str = "cpu"
    truncation_flags: tuple[bool, ...] = ()
    input_truncation_flags: tuple[bool, ...] = ()


class TranslatorBackend(Protocol):
    """Protocol for local model inference backend."""

    def translate_sentences(
        self,
        sentences: Sequence[str],
        direction: TranslationDirection,
        execution_binding: ExecutionBinding | None = None,
        **kwargs: Any,
    ) -> list[str] | tuple[list[str], str] | tuple[list[str], str, list[bool]] | BackendTranslationResult:
        """Translate a batch of sentences."""
        ...


def _chunk_long_sentence(
    s: str,
    spm_src: Any,
    max_tokens: int = MAX_SENTENCE_TOKENS,
) -> list[tuple[str, str]]:
    """Split a long sentence into sub-parts bounded by max_tokens."""
    sub_parts = re.split(r"([;,:])\s*", s)
    preliminary_parts: list[tuple[str, str]] = []
    for i in range(0, len(sub_parts), 2):
        sub_txt = sub_parts[i].strip()
        sub_sep = (sub_parts[i + 1] + " ") if i + 1 < len(sub_parts) else ""
        if sub_txt:
            preliminary_parts.append((sub_txt, sub_sep))
    if not preliminary_parts:
        preliminary_parts = [(s, "")]

    final_chunks: list[tuple[str, str]] = []
    for txt, sep in preliminary_parts:
        pieces = spm_src.encode_as_pieces(txt)
        if len(pieces) <= max_tokens:
            final_chunks.append((txt, sep))
            continue

        # Sub-chunk by whitespace words
        words = txt.split(" ")
        current_words: list[str] = []
        for w in words:
            candidate = " ".join(current_words + [w]) if current_words else w
            if current_words and len(spm_src.encode_as_pieces(candidate)) > max_tokens:
                final_chunks.append((" ".join(current_words), " "))
                current_words = [w]
            else:
                current_words.append(w)
        if current_words:
            remainder = " ".join(current_words)
            while len(spm_src.encode_as_pieces(remainder)) > max_tokens:
                cut_point = max(1, len(remainder) // 2)
                final_chunks.append((remainder[:cut_point], ""))
                remainder = remainder[cut_point:]
            if remainder:
                final_chunks.append((remainder, sep))

    return final_chunks or [(s, "")]


class CTranslate2NativeBackend:
    """Canonical CTranslate2 + SentencePiece neural translation backend."""

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
    ) -> BackendTranslationResult:
        import ctranslate2
        import sentencepiece

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
            model_info: dict[str, Any] = {}
        else:
            model_info = self._manifest.get("models", {}).get(dir_key) or {}
            if not model_info and dir_key not in ("hi-en", "en-hi"):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Model for direction '{dir_key}' not declared in manifest.",
                )
            # Check indictrans2 subdirectory first, then fallback to root models
            model_path = self._root / "models" / "indictrans2" / dir_key
            if not (
                model_path.exists() and any((model_path / f).exists() for f in ("model.bin", "model.SRC", "spm.model"))
            ):
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

        # Explicit compute type: int8_float32 for AVX2/AVX-VNNI neural acceleration on Core Ultra CPU
        compute_type = model_info.get("compute_type")
        if not compute_type:
            compute_type = "int8_float32" if device == "cpu" else "float16"

        trans_key = f"{norm_engine}:{model_path.resolve()}:{dir_key}:{device}:{device_index}:{compute_type}"
        spm_src_key = f"src:{spm_src_path.resolve()}"
        spm_tgt_key = f"tgt:{spm_tgt_path.resolve()}"
        with self._lock:
            if trans_key not in self._translators:
                cpu_fn = getattr(os, "process_cpu_count", None)
                cpu_count = cpu_fn() if callable(cpu_fn) else os.cpu_count() or 4
                default_concurrency = max(1, min(4, cpu_count // 4))

                approved = (
                    execution_binding.approved_concurrency
                    if execution_binding is not None and execution_binding.approved_concurrency > 0
                    else default_concurrency
                )
                if device == "cpu":
                    # On hybrid P+E architecture (e.g. Core Ultra 5 125H with 4 P-cores + 8 E-cores),
                    # pin intra-op parallelism to physical P-cores (4) with AVX2/AVX-VNNI acceleration
                    # to prevent barrier synchronization jitter across heterogeneous cores.
                    inter_threads = max(1, min(2, approved))
                    intra_threads = 4 if cpu_count >= 12 else max(2, min(4, (cpu_count + 1) // inter_threads))
                else:
                    inter_threads = approved
                    intra_threads = 0

                try:
                    self._translators[trans_key] = ctranslate2.Translator(
                        str(model_path),
                        device=device,
                        device_index=device_index,
                        compute_type=compute_type,
                        inter_threads=inter_threads,
                        intra_threads=intra_threads,
                    )
                except (TypeError, ValueError):
                    # Fallback for mock environments or models incompatible with int8_float32
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

        # Split sentences longer than MAX_SENTENCE_TOKENS tokens into token-bounded chunks
        sentence_chunks: list[list[tuple[str, str]]] = []
        flat_pieces: list[str] = []
        for s in sentences:
            raw_pieces = spm_src.encode_as_pieces(s)
            if len(raw_pieces) > MAX_SENTENCE_TOKENS:
                chunks = _chunk_long_sentence(s, spm_src, MAX_SENTENCE_TOKENS)
                sentence_chunks.append(chunks)
                for txt, _ in chunks:
                    flat_pieces.append(txt)
            else:
                sentence_chunks.append([(s, "")])
                flat_pieces.append(s)

        if norm_engine == "indictrans2":
            src_tag = model_info.get("source_lang", "hin_Deva" if dir_key == "hi-en" else "eng_Latn")
            tgt_tag = model_info.get("target_lang", "eng_Latn" if dir_key == "hi-en" else "hin_Deva")
            tokenized = [[src_tag, tgt_tag] + spm_src.encode_as_pieces(p) for p in flat_pieces]
        else:
            tokenized = [spm_src.encode_as_pieces(p) for p in flat_pieces]

        piece_input_truncations = [len(tok) >= 1024 for tok in tokenized]

        # Token-based batching bounds token count per forward pass, eliminating tail latency
        # on uneven sentence lengths while distributing work across worker threads.
        results = translator.translate_batch(
            tokenized,
            batch_type="tokens",
            max_batch_size=1024,
            beam_size=DEFAULT_BEAM_SIZE,
            max_decoding_length=DEFAULT_MAX_DECODING_LENGTH,
            max_input_length=1024,
        )

        decoded_pieces: list[str] = []
        piece_truncations: list[bool] = []
        for r in results:
            hyp = r.hypotheses[0] if getattr(r, "hypotheses", None) else []
            is_trunc = len(hyp) >= DEFAULT_MAX_DECODING_LENGTH
            piece_truncations.append(is_trunc)
            text = spm_tgt.decode_pieces(hyp)
            if norm_engine == "indictrans2":
                for tag in ("hin_Deva", "eng_Latn", "<s>", "</s>", "<unk>", "\u2047", "Â"):
                    text = text.replace(tag, "")
            text = text.replace("\u2581", " ")
            text = " ".join(text.split())
            decoded_pieces.append(text.strip())

        decoded_sentences: list[str] = []
        sentence_truncations: list[bool] = []
        sentence_input_truncations: list[bool] = []
        p_idx = 0
        for chunks in sentence_chunks:
            s_text_parts: list[str] = []
            s_has_trunc = False
            s_has_input_trunc = False
            for _, sep in chunks:
                s_text_parts.append(decoded_pieces[p_idx] + sep)
                if piece_truncations[p_idx]:
                    s_has_trunc = True
                if piece_input_truncations[p_idx]:
                    s_has_input_trunc = True
                p_idx += 1
            decoded_sentences.append("".join(s_text_parts).strip())
            sentence_truncations.append(s_has_trunc)
            sentence_input_truncations.append(s_has_input_trunc)

        return BackendTranslationResult(
            sentences=decoded_sentences,
            device=device,
            truncation_flags=tuple(sentence_truncations),
            input_truncation_flags=tuple(sentence_input_truncations),
        )

    def clear_cache(self) -> None:
        """Clear cached CTranslate2 Translator and SentencePiece instances."""
        with self._lock:
            self._translators.clear()
            self._spms.clear()


_CTranslate2NativeBackend = CTranslate2NativeBackend


class CTranslate2TranslationEngine:
    """Instance-owned CTranslate2 + IndicTrans2 engine adapter."""

    def __init__(
        self,
        data_root: Path | None = None,
        backend: TranslatorBackend | None = None,
        glossary: GlossaryStore | None = None,
        protector: TranslationProtector | None = None,
        proper_noun_guard: ProperNounGuard | None = None,
        harmonizer: GlossaryHarmonizer | None = None,
    ) -> None:
        self._data_root = (data_root or _CANONICAL_TRANSLATION_DATA_DIR).resolve()
        self._backend = backend
        self._glossary = glossary or GlossaryStore(glossary_dir=self._data_root)
        self._anubhava_corrections = _load_translation_anubhava(self._data_root)
        for dir_corrections in self._anubhava_corrections.values():
            for src in dir_corrections:
                _compile_anubhava_pattern(src)
        self._protector = protector or TranslationProtector()
        self._proper_noun_guard = proper_noun_guard or ProperNounGuard()
        self._harmonizer = harmonizer or GlossaryHarmonizer()
        self._initialized_backend: TranslatorBackend | None = None
        self._backend_lock: threading.Lock = threading.Lock()
        self._asset_version: str = self._compute_asset_version()

    def clear_cache(self) -> None:
        """Clear cached CTranslate2 Translator instances."""
        with self._backend_lock:
            if self._backend is not None and hasattr(self._backend, "clear_cache"):
                self._backend.clear_cache()
            if self._initialized_backend is not None and hasattr(self._initialized_backend, "clear_cache"):
                self._initialized_backend.clear_cache()

    def _compute_asset_version(self) -> str:
        import hashlib

        hasher = hashlib.sha256()
        manifest_path = self._data_root / "manifest.json"
        if manifest_path.is_file():
            try:
                st = manifest_path.stat()
                hasher.update(f"manifest:{st.st_size}:{st.st_mtime_ns}".encode())
                hasher.update(manifest_path.read_bytes())
            except OSError:
                pass
        anubhava_file = self._data_root / "anubhava.toml"
        if anubhava_file.is_file():
            try:
                st = anubhava_file.stat()
                hasher.update(f"anubhava:{st.st_size}:{st.st_mtime_ns}".encode())
                hasher.update(anubhava_file.read_bytes())
            except OSError:
                pass
        for g_name in ("glossary.yaml", "glossary.yml"):
            g_path = self._data_root / g_name
            if g_path.is_file():
                try:
                    st = g_path.stat()
                    hasher.update(f"{g_name}:{st.st_size}:{st.st_mtime_ns}".encode())
                    hasher.update(g_path.read_bytes())
                except OSError:
                    pass
        glossary_dir = self._data_root / "glossaries"
        if glossary_dir.is_dir():
            try:
                for p in sorted(glossary_dir.iterdir()):
                    if p.is_file() and p.suffix.lower() in (".json", ".yaml", ".yml"):
                        st = p.stat()
                        hasher.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode())
                        hasher.update(p.read_bytes())
            except OSError:
                pass
        return hasher.hexdigest()[:16]

    def _apply_anubhava(self, sentence: str, direction: str) -> str:
        """Apply approved Anubhava overrides with Devanagari-aware word boundaries."""
        for d in (direction, "both"):
            corrections = self._anubhava_corrections.get(d, {})
            if not corrections:
                continue
            for src_c, tgt_c in corrections.items():
                pattern = _compile_anubhava_pattern(src_c)
                sentence = pattern.sub(tgt_c, sentence)
        return sentence

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

                importlib.import_module("ctranslate2")
                importlib.import_module("sentencepiece")
            except ImportError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Translation dependencies (ctranslate2, sentencepiece) are not installed.",
                ) from exc

            self._initialized_backend = CTranslate2NativeBackend(self._data_root, manifest_dict)
            return self._initialized_backend

    def translate(
        self,
        text: str,
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
        execution_binding: ExecutionBinding | None = None,
        engine: str = "indictrans2",
        glossary_terms: Mapping[str, str] | None = None,
        custom_terms: Sequence[str] = (),
    ) -> TranslationResult:
        """Translate normalized Unicode text via CTranslate2 with span protection and glossary."""
        return self.translate_batch(
            texts=[text],
            direction=direction,
            execution_binding=execution_binding,
            engine=engine,
            glossary_terms=glossary_terms,
            custom_terms=custom_terms,
        )[0]

    def translate_batch(
        self,
        texts: Sequence[str],
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
        execution_binding: ExecutionBinding | None = None,
        engine: str = "indictrans2",
        glossary_terms: Mapping[str, str] | None = None,
        custom_terms: Sequence[str] = (),
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
        active_glossary = glossary_terms if glossary_terms is not None else self._glossary.get_terms(direction)
        dir_key = direction.value

        text_slices: list[tuple[int, int, list[tuple[str, str]], int, list[str], list[tuple[str, str]]]] = []
        all_prepared_sentences: list[str] = []

        for idx, text in enumerate(texts):
            if not text or not text.strip():
                text_slices.append((idx, 0, [], 0, [], []))
                continue

            guarded_text = text
            name_placeholders: list[tuple[str, str]] = []
            effective_custom_terms = list(custom_terms) if custom_terms else []
            if direction == TranslationDirection.HI_TO_EN and self._proper_noun_guard is not None:
                guarded_text, name_placeholders = self._proper_noun_guard.protect(text)
                if name_placeholders:
                    effective_custom_terms.extend(ph for ph, _ in name_placeholders)

            protected_text, spans = self._protector.protect(
                guarded_text,
                custom_terms=tuple(effective_custom_terms),
                glossary_mappings=active_glossary,
            )
            split_units = split_sentences(protected_text)
            if not split_units:
                split_units = [(protected_text, "")]

            raw_sentences = [seg for seg, _ in split_units]
            separators = [sep for _, sep in split_units]

            start_idx = len(all_prepared_sentences)
            for sent in raw_sentences:
                all_prepared_sentences.append(self._apply_anubhava(sent, dir_key))

            text_slices.append((idx, len(raw_sentences), spans, start_idx, separators, name_placeholders))

        factual_device = target_device
        all_translated_sentences: list[str] = []
        truncation_flags: list[bool] = []
        input_truncation_flags: list[bool] = []
        if all_prepared_sentences:
            # Batch-local sentence deduplication
            unique_sentences: list[str] = []
            sent_to_unique_idx: dict[str, int] = {}
            sentence_map: list[int] = []

            for sent in all_prepared_sentences:
                u_idx = sent_to_unique_idx.get(sent)
                if u_idx is None:
                    u_idx = len(unique_sentences)
                    sent_to_unique_idx[sent] = u_idx
                    unique_sentences.append(sent)
                sentence_map.append(u_idx)

            backend = self._ensure_backend()
            backend_res = backend.translate_sentences(
                unique_sentences, direction, execution_binding=execution_binding, engine=norm_engine
            )

            unique_translated: Sequence[str] = []
            unique_truncations: Sequence[bool] = []
            unique_input_truncations: Sequence[bool] = []
            if isinstance(backend_res, BackendTranslationResult):
                unique_translated = backend_res.sentences
                factual_device = backend_res.device
                unique_truncations = backend_res.truncation_flags
                unique_input_truncations = backend_res.input_truncation_flags
            elif isinstance(backend_res, tuple) and len(backend_res) >= 2:
                unique_translated = backend_res[0]
                factual_device = backend_res[1]
                if len(backend_res) > 2:
                    unique_truncations = backend_res[2]
            elif isinstance(backend_res, (list, tuple)):
                unique_translated = backend_res
            elif hasattr(backend, "translate") and not isinstance(backend_res, (list, tuple)):
                unique_translated = [
                    getattr(backend.translate(s, direction=direction), "translated_text", str(s))
                    for s in unique_sentences
                ]
            else:
                unique_translated = backend_res

            # Broadcast model outputs back to full sentence positions
            all_translated_sentences = [unique_translated[i] for i in sentence_map]
            if unique_truncations:
                truncation_flags = [unique_truncations[i] for i in sentence_map]
            if unique_input_truncations:
                input_truncation_flags = [unique_input_truncations[i] for i in sentence_map]

        results: list[TranslationResult] = []
        for idx, sent_count, spans, start_idx, separators, name_placeholders in text_slices:
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
            item_truncations = truncation_flags[start_idx : start_idx + sent_count] if truncation_flags else []
            item_input_truncations = (
                input_truncation_flags[start_idx : start_idx + sent_count] if input_truncation_flags else []
            )
            truncation_suspected = any(item_truncations)
            input_truncation_suspected = any(item_input_truncations)
            translated_body = "".join(ts + sep for ts, sep in zip(sents, separators))
            final_text, span_issues = self._protector.restore_with_validation(translated_body, spans)
            if name_placeholders and self._proper_noun_guard is not None:
                final_text = self._proper_noun_guard.restore(final_text, name_placeholders)
            if self._harmonizer is not None:
                final_text = self._harmonizer.harmonize(final_text, direction)

            metadata: dict[str, Any] = {
                "sentences_count": sent_count,
                "device": factual_device,
                "backend": "ctranslate2",
                "engine": norm_engine,
            }
            warnings_list: list[str] = []
            if truncation_suspected:
                span_issues.append("TRANSLATION_TRUNCATION_SUSPECTED")
                metadata["truncation_suspected"] = True
                warnings_list.append("TRANSLATION_TRUNCATION_SUSPECTED")
            if input_truncation_suspected:
                span_issues.append("TRANSLATION_INPUT_TRUNCATED")
                metadata["input_truncation_suspected"] = True
                warnings_list.append("TRANSLATION_INPUT_TRUNCATED")
            if warnings_list:
                metadata["warnings"] = tuple(warnings_list)
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
