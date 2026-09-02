"""Identification Facts contract for Darshana in Sarathi V2.

Defines:
- IdentificationFacts: Immutable typed facts measured from safe byte/content evidence.

Contains facts and metadata only; contains no document extraction, OCR, font conversion,
translation, or business classification logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class IdentificationFacts:
    """Typed factual identification evidence measured from content bytes."""

    media_type: str
    format_name: str
    is_binary: bool
    byte_signature: str | None = None
    encoding_hint: str | None = None
    extension_hint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.media_type, str):
            raise TypeError(f"media_type must be a string, got {type(self.media_type).__name__}.")
        clean_media = self.media_type.strip().lower()
        if not clean_media:
            raise ValueError("media_type must be a non-empty string.")
        object.__setattr__(self, "media_type", clean_media)

        if not isinstance(self.format_name, str):
            raise TypeError(f"format_name must be a string, got {type(self.format_name).__name__}.")
        clean_format = self.format_name.strip().lower()
        if not clean_format:
            raise ValueError("format_name must be a non-empty string.")
        object.__setattr__(self, "format_name", clean_format)

        if not isinstance(self.is_binary, bool):
            raise TypeError(f"is_binary must be a bool, got {type(self.is_binary).__name__}.")

        if self.byte_signature is not None:
            if not isinstance(self.byte_signature, str):
                raise TypeError(
                    f"byte_signature must be a string when provided, got {type(self.byte_signature).__name__}."
                )
            clean_sig = self.byte_signature.strip()
            if not clean_sig:
                raise ValueError("byte_signature must be a non-empty string when provided.")
            object.__setattr__(self, "byte_signature", clean_sig)

        if self.encoding_hint is not None:
            if not isinstance(self.encoding_hint, str):
                raise TypeError(
                    f"encoding_hint must be a string when provided, got {type(self.encoding_hint).__name__}."
                )
            clean_enc = self.encoding_hint.strip().lower()
            if not clean_enc:
                raise ValueError("encoding_hint must be a non-empty string when provided.")
            object.__setattr__(self, "encoding_hint", clean_enc)

        if self.extension_hint is not None:
            if not isinstance(self.extension_hint, str):
                raise TypeError(
                    f"extension_hint must be a string when provided, got {type(self.extension_hint).__name__}."
                )
            clean_ext = self.extension_hint.strip().lower()
            if clean_ext.startswith("."):
                clean_ext = clean_ext[1:]
            if not clean_ext:
                raise ValueError("extension_hint must be a non-empty string when provided.")
            object.__setattr__(self, "extension_hint", clean_ext)

        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata).__name__}.")
