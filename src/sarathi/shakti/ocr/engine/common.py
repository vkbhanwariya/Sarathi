"""Shared constants, regexes, and language definitions for the OCR engine."""

from __future__ import annotations

import re
from pathlib import Path

from sarathi.sutra import get_canonical_data_root

STAGE_NAME = "ocr"
PLUGIN_ID = "shakti.ocr"
CAPABILITY_ID = "ocr"
CANONICAL_DATA_ROOT: Path = get_canonical_data_root() / "ocr"

REQUIRED_MODEL_KEYS = ("det", "rec", "cls")
HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")

DEV_LANGS = frozenset({"devanagari", "hi", "hindi"})
V6_LANGS = frozenset({"en_v6", "v6", "english_v6"})
EN_LANGS = frozenset({"en", "eng", "english", "latin", "ch", "chinese"})
ALL_SUPPORTED_LANGS = DEV_LANGS | V6_LANGS | EN_LANGS

_DEV_LANGS = DEV_LANGS
_V6_LANGS = V6_LANGS
_EN_LANGS = EN_LANGS
_ALL_SUPPORTED_LANGS = ALL_SUPPORTED_LANGS
