"""Safe ZIP Archive and XML Processing Engine for Native Extraction.

Re-exports core safe zip and XML parsing primitives from sarathi.shakti.text.safe_zip.
"""

from __future__ import annotations

from sarathi.shakti.text.safe_zip import (
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_MAX_UNCOMPRESSED_BYTES,
    DEFAULT_MAX_ZIP_MEMBERS,
    SafeZipFile,
    open_zip_safely,
    safe_fromstring,
)

__all__ = [
    "DEFAULT_MAX_COMPRESSION_RATIO",
    "DEFAULT_MAX_INPUT_BYTES",
    "DEFAULT_MAX_UNCOMPRESSED_BYTES",
    "DEFAULT_MAX_ZIP_MEMBERS",
    "SafeZipFile",
    "open_zip_safely",
    "safe_fromstring",
]
