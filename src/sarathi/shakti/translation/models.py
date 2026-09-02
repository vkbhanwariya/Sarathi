"""Domain Models and Types for Shakti Translation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class Language(str, Enum):
    """Supported language codes."""

    HINDI = "hi"
    ENGLISH = "en"
    UNKNOWN = "unknown"


class TranslationDirection(str, Enum):
    """Supported translation direction pairs."""

    HI_TO_EN = "hi-en"
    EN_TO_HI = "en-hi"


@dataclass(frozen=True, slots=True)
class TranslationSpan:
    """Protected span within translation source text."""

    placeholder: str
    original_text: str
    span_type: str


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    """Domain terminology translation mapping."""

    source: str
    target: str
    direction: TranslationDirection
    domain: str = "general"


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Result of a translation operation."""

    translated_text: str
    source_language: Language
    target_language: Language
    direction: TranslationDirection
    protected_spans_count: int
    metadata: Mapping[str, object]
