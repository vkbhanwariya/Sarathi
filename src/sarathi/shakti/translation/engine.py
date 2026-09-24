"""Locked CTranslate2 + Krutrim-Translate + SentencePiece Translation Engine for Sarathi."""

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
from sarathi.sankalpa import DeviceType, ExecutionBinding, ExecutionProfile
from sarathi.shakti.text.typography import normalize_devanagari_numerals
from sarathi.shakti.translation.court_templates import CourtTemplateMatcher
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


def split_legal_clauses(text: str, max_chars: int = 3500) -> list[tuple[str, str]]:
    """Split text into paragraph and legal-clause level units for long-context models.

    Preserves whole paragraphs and multi-sentence legal clauses within max_chars,
    ensuring discourse context, pronoun antecedents, and provisos remain unified.
    Maintains "".join(seg + sep for seg, sep in split_legal_clauses(text)) == text.
    """
    if not text:
        return []

    # Match paragraph breaks (double newlines)
    para_re = re.compile(r"(\n\s*\n+|\r\n\s*\r\n+)")
    parts = para_re.split(text)

    clauses: list[tuple[str, str]] = []
    i = 0
    while i < len(parts):
        seg = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if len(seg) <= max_chars:
            if seg or sep:
                clauses.append((seg, sep))
        else:
            # Segment long paragraph on sentence boundaries
            sub_sents = split_sentences(seg)
            cur_text = ""
            cur_sep = ""
            for s_seg, s_sep in sub_sents:
                if len(cur_text) + len(cur_sep) + len(s_seg) <= max_chars:
                    cur_text = (cur_text + cur_sep + s_seg) if cur_text else s_seg
                    cur_sep = s_sep
                else:
                    if cur_text:
                        clauses.append((cur_text, cur_sep))
                    cur_text = s_seg
                    cur_sep = s_sep
            if cur_text or sep:
                clauses.append((cur_text, cur_sep + sep))
        i += 2

    return clauses


def clean_krutrim_legal_text(text: str, is_hindi: bool = False) -> str:
    """Post-process and detokenize Krutrim legal NMT output with correct typography."""
    if not text:
        return text

    t = text
    # Clean redundant whitespace around punctuation
    t = re.sub(r"\s+([,.:;!?])", r"\1", t)
    t = re.sub(r"([,;!?])(?=[^\s\d])", r"\1 ", t)
    t = re.sub(r"\s+([।॥])", r"\1", t)

    # Brackets & quotes padding
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    t = re.sub(r"\[\s+", "[", t)
    t = re.sub(r"\s+\]", "]", t)

    # Slashing in statutory references (e.g. 302 / 34 -> 302/34)
    t = re.sub(r"(\d+)\s*/\s*(\d+)", r"\1/\2", t)

    if is_hindi:
        t = re.sub(r"\bयू\s*/\s*एस\b", "धारा", t)
        t = re.sub(r"\bआर\s*/\s*डब्लू\b", "पठित", t)
        t = re.sub(r"\bसी\s*\.\s*आर\s*\.\s*पी\s*\.\s*सी\s*\.\s*", "दंड प्रक्रिया संहिता ", t)
        t = re.sub(r"\bआई\s*\.\s*पी\s*\.\s*सी\s*\.\s*", "भा.दं.सं. ", t)
    else:
        # Legal honorifics and terms
        t = re.sub(r"\bHon\s*[''’]\s*ble\b", "Hon'ble", t, flags=re.IGNORECASE)
        t = re.sub(r"\bu\s*/\s*s\b", "u/s", t, flags=re.IGNORECASE)
        t = re.sub(r"\br\s*/\s*w\b", "r/w", t, flags=re.IGNORECASE)
        t = re.sub(
            r"\b(Sec|No|Art|Ltd|Pvt|Govt|Dept|Co|Inc|Dist|App|Para|Cl)\s*\.\s*",
            r"\1. ",
            t,
        )
        # Contractions
        t = re.sub(r"\s*[''’]\s*(s|t|re|ve|ll|d|m)\b", r"'\1", t)
        # Acronyms with periods (C . P . C . -> C.P.C.)
        t = re.sub(r"\b([A-Za-z])\s*\.\s*([A-Za-z])\s*\.\s*([A-Za-z])\s*\.\s*", r"\1.\2.\3. ", t)
        t = re.sub(r"\b([A-Za-z])\s*\.\s*([A-Za-z])\s*\.\s*", r"\1.\2. ", t)

    # Collapse internal spaces
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


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
        self._verified_models: set[str] = set()
        self._lock: threading.Lock = threading.Lock()
        self._cuda_device_count: int | None = None

    def _get_cuda_device_count(self) -> int:
        """Cache and return the available CUDA device count for CTranslate2."""
        if self._cuda_device_count is None:
            try:
                import ctranslate2

                if hasattr(ctranslate2, "get_cuda_device_count"):
                    self._cuda_device_count = int(ctranslate2.get_cuda_device_count())
                else:
                    self._cuda_device_count = 0
            except Exception:
                self._cuda_device_count = 0
        return self._cuda_device_count

    def _verify_model_integrity(self, model_path: Path, expected_files: dict[str, Any] | None) -> None:
        """Verify checksums and regular file attributes of translation model assets."""
        import hashlib
        import stat

        try:
            m_stat = model_path.lstat()
        except OSError as exc:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message=f"Translation model path cannot be accessed: {model_path.name}",
            ) from exc

        if stat.S_ISLNK(m_stat.st_mode) or not stat.S_ISDIR(m_stat.st_mode):
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message=f"Translation model directory '{model_path.name}' is invalid or a symlink.",
            )

        if not expected_files or not isinstance(expected_files, dict):
            return

        for fname, entry in expected_files.items():
            expected_sha = entry.get("sha256") if isinstance(entry, dict) else entry
            if not expected_sha:
                continue
            fpath = model_path / str(fname)
            try:
                fstat = fpath.lstat()
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Required translation model asset '{fname}' is missing.",
                ) from exc

            if stat.S_ISLNK(fstat.st_mode) or not stat.S_ISREG(fstat.st_mode):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Translation model asset '{fname}' is not a regular file.",
                )

            h = hashlib.sha256()
            try:
                with open(fpath, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Failed to read translation model asset '{fname}'.",
                ) from exc

            actual_sha = h.hexdigest().lower()
            if actual_sha != expected_sha.lower():
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Translation model asset '{fname}' checksum mismatch (expected {expected_sha[:8]}..., got {actual_sha[:8]}...).",
                )

    def translate_sentences(
        self,
        sentences: Sequence[str],
        direction: TranslationDirection,
        execution_binding: ExecutionBinding | None = None,
        engine: str = "krutrim",
        execution_profile: ExecutionProfile | None = None,
        beam_size: int | None = None,
        **kwargs: Any,
    ) -> BackendTranslationResult:
        import ctranslate2
        import sentencepiece

        # Native model inference using CTranslate2 and SentencePiece
        dir_key = direction.value
        norm_engine = str(engine or "krutrim").lower().strip()
        if norm_engine not in ("krutrim", "krutrim_translate", "default", "ctranslate2"):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Unsupported translation engine '{engine}'. Sarathi canonical engine is 'krutrim'.",
            )

        model_info = (
            self._manifest.get("engines", {}).get("krutrim", {}).get(dir_key)
            or self._manifest.get("models", {}).get(dir_key)
            or {}
        )
        krutrim_dir = self._root / "models" / "krutrim" / dir_key
        root_dir = self._root / "models" / dir_key
        if krutrim_dir.is_dir() and (krutrim_dir / "model.bin").is_file():
            model_path = krutrim_dir
        elif root_dir.is_dir() and (root_dir / "model.bin").is_file():
            model_path = root_dir
        else:
            model_path = krutrim_dir

        if not model_path.is_dir() or not (model_path / "model.bin").is_file():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message=f"Model assets for Krutrim-Translate translation direction '{dir_key}' are missing or incomplete.",
            )

        # Resolve source SentencePiece model
        if (model_path / "model.SRC").is_file():
            spm_src_path = model_path / "model.SRC"
        elif (model_path / "src_spm.model").is_file():
            spm_src_path = model_path / "src_spm.model"
        elif (model_path / "spm.model").is_file():
            spm_src_path = model_path / "spm.model"
        else:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message=f"Model assets for Krutrim-Translate translation direction '{dir_key}' are missing or incomplete.",
            )

        # Resolve target SentencePiece model
        if (model_path / "model.TGT").is_file():
            spm_tgt_path = model_path / "model.TGT"
        elif (model_path / "tgt_spm.model").is_file():
            spm_tgt_path = model_path / "tgt_spm.model"
        else:
            spm_tgt_path = spm_src_path

        device = "cpu"
        device_index = 0
        if execution_binding is not None and execution_binding.device_type == DeviceType.GPU:
            if self._get_cuda_device_count() > 0:
                device = "cuda"
                dev_str = str(execution_binding.backend_device_id).strip()
                if ":" in dev_str:
                    dev_str = dev_str.split(":")[-1]
                try:
                    device_index = int(dev_str)
                except ValueError:
                    device_index = 0

        # Explicit compute type: int8_float32 for AVX2/AVX-VNNI neural acceleration on Core Ultra CPU
        compute_type = model_info.get("compute_type")
        if not compute_type:
            compute_type = "int8_float32" if device == "cpu" else "float16"

        trans_key = f"{norm_engine}:{model_path.resolve()}:{dir_key}:{device}:{device_index}:{compute_type}"
        spm_src_key = f"src:{spm_src_path.resolve()}"
        spm_tgt_key = f"tgt:{spm_tgt_path.resolve()}"
        with self._lock:
            model_verified_key = f"{norm_engine}:{dir_key}:{model_path.resolve()}"
            if model_verified_key not in self._verified_models:
                self._verify_model_integrity(model_path, model_info.get("files"))
                self._verified_models.add(model_verified_key)

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
                    # pin intra-op parallelism to physical P-cores (4) with AVX2/AVX-VNNI acceleration.
                    # Bound inter_threads to 2 when intra_threads is 4 to prevent oversubscribing
                    # the 4 physical P-cores (8 threads) with 24+ thrashing threads.
                    intra_threads = 4 if cpu_count >= 12 else max(2, min(4, (cpu_count + 1) // max(1, approved)))
                    inter_threads = max(1, min(2 if intra_threads >= 4 else 4, approved))
                    os.environ.setdefault("KMP_BLOCKTIME", "0")
                    os.environ.setdefault("OMP_PROC_BIND", "close")
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

        is_krutrim = norm_engine in ("krutrim", "krutrim_translate") or "krutrim" in str(model_path).lower()
        eff_max_tokens = 4096 if is_krutrim else MAX_SENTENCE_TOKENS
        eff_max_input_len = 4096 if is_krutrim else 1024

        # Split sentences longer than eff_max_tokens tokens into token-bounded chunks
        sentence_chunks: list[list[tuple[str, str]]] = []
        flat_pieces: list[str] = []
        for s in sentences:
            raw_pieces = spm_src.encode_as_pieces(s)
            if len(raw_pieces) > eff_max_tokens:
                chunks = _chunk_long_sentence(s, spm_src, eff_max_tokens)
                sentence_chunks.append(chunks)
                for txt, _ in chunks:
                    flat_pieces.append(txt)
            else:
                sentence_chunks.append([(s, "")])
                flat_pieces.append(s)

        src_tag = model_info.get("source_lang", "hin_Deva" if dir_key == "hi-en" else "eng_Latn")
        tgt_tag = model_info.get("target_lang", "eng_Latn" if dir_key == "hi-en" else "hin_Deva")
        tokenized = [[src_tag, tgt_tag] + spm_src.encode_as_pieces(p) for p in flat_pieces]

        # Dynamic decoding length: scale with input token length to eliminate runaway decoding latency
        max_in_tokens = max((len(tok) for tok in tokenized), default=100)
        eff_max_decoding_len = min(4096 if is_krutrim else DEFAULT_MAX_DECODING_LENGTH, max(256, int(max_in_tokens * 2.0)))
        piece_input_truncations = [len(tok) >= eff_max_input_len for tok in tokenized]

        # Determine effective beam size: instant profile uses greedy beam_size=1 (~2.5x speedup)
        if beam_size is not None and beam_size > 0:
            eff_beam_size = int(beam_size)
        elif kwargs.get("beam_size") is not None and int(kwargs["beam_size"]) > 0:
            eff_beam_size = int(kwargs["beam_size"])
        elif execution_profile is not None and (
            execution_profile == ExecutionProfile.INSTANT or str(execution_profile).lower() == "instant"
        ):
            eff_beam_size = 1
        elif is_krutrim:
            eff_beam_size = 3
        else:
            eff_beam_size = DEFAULT_BEAM_SIZE

        # Repetition penalty tuning: mild penalty for Krutrim to avoid penalizing recurring statutory phrasing
        rep_penalty = 1.05 if is_krutrim else 1.15
        no_repeat_ngram = 0 if is_krutrim else 4

        # Deduplicate identical tokenized sequences to eliminate redundant neural model execution
        unique_tokenized: list[list[str]] = []
        token_to_idx: dict[tuple[str, ...], int] = {}
        piece_to_unique_idx: list[int] = []

        for tok in tokenized:
            key = tuple(tok)
            if key not in token_to_idx:
                token_to_idx[key] = len(unique_tokenized)
                unique_tokenized.append(tok)
            piece_to_unique_idx.append(token_to_idx[key])

        # Length-based bucketing: sort unique tokenized sequences by length to minimize padding overhead in CTranslate2
        if len(unique_tokenized) > 1:
            sorted_order = sorted(range(len(unique_tokenized)), key=lambda i: len(unique_tokenized[i]))
            reordered_tokenized = [unique_tokenized[i] for i in sorted_order]
        else:
            sorted_order = list(range(len(unique_tokenized)))
            reordered_tokenized = unique_tokenized

        translate_kwargs: dict[str, Any] = {
            "batch_type": "tokens",
            "max_batch_size": 8192 if is_krutrim else 1024,
            "beam_size": eff_beam_size,
            "max_decoding_length": eff_max_decoding_len,
            "max_input_length": eff_max_input_len,
            "repetition_penalty": rep_penalty,
            "no_repeat_ngram_size": no_repeat_ngram,
            "length_penalty": 0.6 if eff_beam_size > 1 else 0.0,
            "return_scores": False,
        }
        if is_krutrim:
            translate_kwargs["replace_unknowns"] = True

        try:
            raw_results = translator.translate_batch(
                reordered_tokenized,
                **translate_kwargs,
            )
        except TypeError:
            translate_kwargs.pop("replace_unknowns", None)
            translate_kwargs.pop("return_scores", None)
            raw_results = translator.translate_batch(
                reordered_tokenized,
                **translate_kwargs,
            )

        # Restore unique results to original unique order
        if len(unique_tokenized) > 1:
            unique_results = [None] * len(unique_tokenized)
            for orig_pos, r in zip(sorted_order, raw_results):
                unique_results[orig_pos] = r
        else:
            unique_results = raw_results

        # Map unique results back to original piece positions
        results = [unique_results[u_idx] for u_idx in piece_to_unique_idx]

        decoded_pieces: list[str] = []
        piece_truncations: list[bool] = []
        for r in results:
            hyp = r.hypotheses[0] if getattr(r, "hypotheses", None) else []
            is_trunc = len(hyp) >= eff_max_decoding_len
            piece_truncations.append(is_trunc)
            text = spm_tgt.decode_pieces(hyp)
            for tag in ("hin_Deva", "eng_Latn", "<s>", "</s>", "<unk>", "\u2047", "Â"):
                text = text.replace(tag, "")
            text = text.replace("\u2581", " ")
            text = " ".join(text.split())
            clean_p = clean_krutrim_legal_text(text.strip(), is_hindi=(dir_key == "en-hi")) if is_krutrim else text.strip()
            decoded_pieces.append(clean_p)

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

    def prewarm_direction(
        self,
        direction: TranslationDirection,
        execution_binding: ExecutionBinding | None = None,
        engine: str = "krutrim",
    ) -> bool:
        """Preload model weights and tokenizers for direction into RAM dictionary."""
        try:
            warm_word = "नमस्ते" if direction == TranslationDirection.HI_TO_EN else "Hello"
            self.translate_sentences(
                [warm_word],
                direction=direction,
                execution_binding=execution_binding,
                engine=engine,
                beam_size=1,
            )
            return True
        except Exception:
            return False

    def clear_cache(self) -> None:
        """Clear cached CTranslate2 Translator and SentencePiece instances."""
        with self._lock:
            self._translators.clear()
            self._spms.clear()
            self._verified_models.clear()


_CTranslate2NativeBackend = CTranslate2NativeBackend


class CTranslate2TranslationEngine:
    """Instance-owned CTranslate2 + Krutrim-Translate engine adapter."""

    def __init__(
        self,
        data_root: Path | None = None,
        backend: TranslatorBackend | None = None,
        glossary: GlossaryStore | None = None,
        protector: TranslationProtector | None = None,
        proper_noun_guard: ProperNounGuard | None = None,
        harmonizer: GlossaryHarmonizer | None = None,
        court_templates: CourtTemplateMatcher | None = None,
    ) -> None:
        self._data_root = (data_root or _CANONICAL_TRANSLATION_DATA_DIR).resolve()
        self._backend = backend
        self._glossary = glossary or GlossaryStore(glossary_dir=self._data_root)
        self._court_templates = court_templates or CourtTemplateMatcher(data_root=self._data_root)
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

    def warmup(
        self,
        execution_binding: ExecutionBinding | None = None,
        directions: Sequence[TranslationDirection] = (TranslationDirection.HI_TO_EN, TranslationDirection.EN_TO_HI),
        engine: str = "krutrim",
        async_second: bool = True,
    ) -> bool:
        """Pre-initialize CTranslate2 engine and preload neural weights for both directions into RAM."""
        try:
            backend = self._ensure_backend()
            if hasattr(backend, "prewarm_direction"):
                if directions:
                    backend.prewarm_direction(directions[0], execution_binding=execution_binding, engine=engine)
                if len(directions) > 1:
                    def _warm_rest() -> None:
                        for d in directions[1:]:
                            try:
                                backend.prewarm_direction(d, execution_binding=execution_binding, engine=engine)
                            except Exception:
                                pass

                    if async_second:
                        t = threading.Thread(target=_warm_rest, name="sarathi-translation-prewarm", daemon=True)
                        t.start()
                    else:
                        _warm_rest()
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
        engine: str = "krutrim",
        glossary_terms: Mapping[str, str] | None = None,
        custom_terms: Sequence[str] = (),
        execution_profile: ExecutionProfile | None = None,
    ) -> TranslationResult:
        """Translate normalized Unicode text via CTranslate2 with span protection and glossary."""
        kwargs: dict[str, Any] = {
            "texts": [text],
            "direction": direction,
            "execution_binding": execution_binding,
            "engine": engine,
            "glossary_terms": glossary_terms,
            "custom_terms": custom_terms,
        }
        if execution_profile is not None:
            kwargs["execution_profile"] = execution_profile
        return self.translate_batch(**kwargs)[0]

    def translate_batch(
        self,
        texts: Sequence[str],
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
        execution_binding: ExecutionBinding | None = None,
        engine: str = "krutrim",
        glossary_terms: Mapping[str, str] | None = None,
        custom_terms: Sequence[str] = (),
        execution_profile: ExecutionProfile | None = None,
    ) -> list[TranslationResult]:
        """Translate a batch of normalized texts via CTranslate2 with multi-core batch decoder."""
        if not texts:
            return []

        src_lang = Language.HINDI if direction == TranslationDirection.HI_TO_EN else Language.ENGLISH
        tgt_lang = Language.ENGLISH if direction == TranslationDirection.HI_TO_EN else Language.HINDI
        target_device = "cpu"
        if execution_binding is not None and execution_binding.device_type == DeviceType.GPU:
            target_device = execution_binding.backend_device_id or "cuda"

        norm_engine = str(engine or "krutrim").lower().strip()
        active_glossary = glossary_terms if glossary_terms is not None else self._glossary.get_terms(direction)
        dir_key = direction.value

        text_slices: list[
            tuple[
                int,
                list[tuple[bool, str | int, list[tuple[str, str]], str]],
                list[tuple[str, str]],
            ]
        ] = []
        all_prepared_sentences: list[str] = []

        for idx, text in enumerate(texts):
            if not text or not text.strip():
                text_slices.append((idx, [], []))
                continue

            guarded_text = text
            name_placeholders: list[tuple[str, str]] = []
            effective_custom_terms = list(custom_terms) if custom_terms else []
            if direction == TranslationDirection.HI_TO_EN and self._proper_noun_guard is not None:
                guarded_text, name_placeholders = self._proper_noun_guard.protect(text)
                if name_placeholders:
                    effective_custom_terms.extend(ph for ph, _ in name_placeholders)

            if norm_engine in ("krutrim", "krutrim_translate"):
                split_units = split_legal_clauses(guarded_text)
            else:
                split_units = split_sentences(guarded_text)
            if not split_units:
                split_units = [(guarded_text, "")]

            sent_records: list[tuple[bool, str | int, list[tuple[str, str]], str]] = []
            for seg, sep in split_units:
                # 1. Zero-latency match against standard court boilerplate & statutory formulas
                tmpl_match = (
                    self._court_templates.match_sentence(seg, direction)
                    if self._court_templates is not None
                    else None
                )
                if tmpl_match is not None:
                    sent_records.append((True, tmpl_match, [], sep))
                else:
                    # 2. Sentences requiring neural translation go through protection and anubhava
                    prot_seg, spans = self._protector.protect(
                        seg,
                        custom_terms=tuple(effective_custom_terms),
                        glossary_mappings=active_glossary,
                    )
                    neural_idx = len(all_prepared_sentences)
                    all_prepared_sentences.append(self._apply_anubhava(prot_seg, dir_key))
                    sent_records.append((False, neural_idx, spans, sep))

            text_slices.append((idx, sent_records, name_placeholders))

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
                unique_sentences,
                direction,
                execution_binding=execution_binding,
                engine=norm_engine,
                execution_profile=execution_profile,
            )

            # Lazy dual-model RAM pre-warming: asynchronously warm opposite direction so both models reside in memory
            opposite_dir = (
                TranslationDirection.EN_TO_HI
                if direction == TranslationDirection.HI_TO_EN
                else TranslationDirection.HI_TO_EN
            )
            translators_map = getattr(backend, "_translators", {})
            if isinstance(translators_map, dict) and not any(f":{opposite_dir.value}:" in k for k in translators_map):
                def _warm_opp() -> None:
                    try:
                        if hasattr(backend, "prewarm_direction"):
                            backend.prewarm_direction(
                                opposite_dir,
                                execution_binding=execution_binding,
                                engine=norm_engine,
                            )
                    except Exception:
                        pass

                threading.Thread(target=_warm_opp, name="sarathi-opposite-direction-warmup", daemon=True).start()

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
            if any(unique_truncations):
                truncation_flags = [unique_truncations[i] for i in sentence_map]
            if any(unique_input_truncations):
                input_truncation_flags = [unique_input_truncations[i] for i in sentence_map]

        results: list[TranslationResult] = []
        for idx, sent_records, name_placeholders in text_slices:
            orig_text = texts[idx]
            if not sent_records or not orig_text or not orig_text.strip():
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

            translated_parts: list[str] = []
            all_spans_count = 0
            all_span_issues: list[str] = []
            truncation_suspected = False
            input_truncation_suspected = False

            for is_tmpl, val, spans, sep in sent_records:
                if is_tmpl:
                    translated_parts.append(str(val) + sep)
                else:
                    neural_idx = int(val)
                    raw_trans = (
                        all_translated_sentences[neural_idx]
                        if neural_idx < len(all_translated_sentences)
                        else ""
                    )
                    if truncation_flags and neural_idx < len(truncation_flags) and truncation_flags[neural_idx]:
                        truncation_suspected = True
                    if (
                        input_truncation_flags
                        and neural_idx < len(input_truncation_flags)
                        and input_truncation_flags[neural_idx]
                    ):
                        input_truncation_suspected = True
                    restored_seg, issues = self._protector.restore_with_validation(raw_trans, spans)
                    all_spans_count += len(spans)
                    if issues:
                        all_span_issues.extend(issues)
                    translated_parts.append(restored_seg + sep)

            translated_body = "".join(translated_parts).strip()
            final_text = translated_body
            if name_placeholders and self._proper_noun_guard is not None:
                final_text = self._proper_noun_guard.restore(final_text, name_placeholders)
            if self._harmonizer is not None:
                final_text = self._harmonizer.harmonize(final_text, direction)
            if norm_engine in ("krutrim", "krutrim_translate"):
                final_text = clean_krutrim_legal_text(
                    final_text, is_hindi=(direction == TranslationDirection.EN_TO_HI)
                )
            if direction == TranslationDirection.HI_TO_EN:
                final_text = normalize_devanagari_numerals(final_text)
                final_text = re.sub(r"\b(?:रु|रू)\.?\s*", "Rs. ", final_text)

            metadata: dict[str, Any] = {
                "sentences_count": len(sent_records),
                "device": factual_device,
                "backend": "ctranslate2",
                "engine": norm_engine,
            }
            warnings_list: list[str] = []
            if truncation_suspected:
                all_span_issues.append("TRANSLATION_TRUNCATION_SUSPECTED")
                metadata["truncation_suspected"] = True
                warnings_list.append("TRANSLATION_TRUNCATION_SUSPECTED")
            if input_truncation_suspected:
                all_span_issues.append("TRANSLATION_INPUT_TRUNCATED")
                metadata["input_truncation_suspected"] = True
                warnings_list.append("TRANSLATION_INPUT_TRUNCATED")
            if warnings_list:
                metadata["warnings"] = tuple(warnings_list)
            if all_span_issues:
                metadata["span_protection_issues"] = tuple(all_span_issues)

            results.append(
                TranslationResult(
                    translated_text=final_text,
                    source_language=src_lang,
                    target_language=tgt_lang,
                    direction=direction,
                    protected_spans_count=all_spans_count,
                    metadata=metadata,
                )
            )

        return results
