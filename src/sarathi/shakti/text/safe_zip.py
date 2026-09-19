"""Safe ZIP Archive and XML Processing Engine.

Enforces strict decompression limits, member limits, ratio checks,
and safe defused XML parsing to mitigate zip bombs, entity expansions,
and billion-laughs / DTD attacks on untrusted office documents.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

import defusedxml.ElementTree as defused_ET
from defusedxml.common import DefusedXmlException, DTDForbidden, EntitiesForbidden

from sarathi.dosh import DoshError, FailureCode

DEFAULT_MAX_INPUT_BYTES: int = 500 * 1024 * 1024  # 500 MB
DEFAULT_MAX_UNCOMPRESSED_BYTES: int = 1024 * 1024 * 1024  # 1 GiB
DEFAULT_MAX_COMPRESSION_RATIO: float = 200.0
DEFAULT_MAX_ZIP_MEMBERS: int = 10000


def safe_fromstring(xml_data: str | bytes) -> ET.Element:
    """Parse untrusted XML safely using defusedxml, rejecting entity expansions and DTDs."""
    if isinstance(xml_data, str):
        xml_bytes = xml_data.encode("utf-8")
    elif isinstance(xml_data, (bytes, bytearray)):
        xml_bytes = bytes(xml_data)
    else:
        raise TypeError(f"xml_data must be str or bytes, got {type(xml_data).__name__}.")

    try:
        return defused_ET.fromstring(xml_bytes)
    except (DefusedXmlException, DTDForbidden, EntitiesForbidden) as exc:
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message=f"XML security validation rejected content: {exc}",
            context={"error_type": type(exc).__name__},
        ) from exc


class SafeZipFile:
    """Wrapper around ZipFile enforcing streaming decompression limits and pre-read ratio/member checks."""

    def __init__(
        self,
        zf: zipfile.ZipFile,
        max_uncompressed: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
        max_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
        max_members: int = DEFAULT_MAX_ZIP_MEMBERS,
    ) -> None:
        self._zf = zf
        self._max_uncompressed = max_uncompressed
        self._max_ratio = max_ratio
        self._max_members = max_members
        self._total_uncompressed_read = 0

        # Validate member count
        infolist = self._zf.infolist()
        if len(infolist) > self._max_members:
            self._zf.close()
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"ZIP member count ({len(infolist)}) exceeds limit ({self._max_members}).",
            )

        # Validate declared uncompressed size from central directory
        total_uncompressed = sum(info.file_size for info in infolist)
        total_compressed = sum(info.compress_size for info in infolist)

        if total_uncompressed > self._max_uncompressed:
            self._zf.close()
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=(
                    f"ZIP declared uncompressed size ({total_uncompressed} bytes) "
                    f"exceeds limit ({self._max_uncompressed} bytes)."
                ),
            )

        # Compression ratio check if substantial content
        if total_uncompressed > 1024:
            eff_compressed = max(total_compressed, 1)
            ratio = total_uncompressed / eff_compressed
            if ratio > self._max_ratio:
                self._zf.close()
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=(f"ZIP compression ratio ({ratio:.1f}) exceeds maximum allowed ({self._max_ratio:.1f})."),
                )

    def __enter__(self) -> SafeZipFile:
        self._zf.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self._zf.__exit__(exc_type, exc_val, exc_tb)

    def close(self) -> None:
        self._zf.close()

    def namelist(self) -> list[str]:
        return self._zf.namelist()

    def infolist(self) -> list[zipfile.ZipInfo]:
        return self._zf.infolist()

    def getinfo(self, name: str) -> zipfile.ZipInfo:
        return self._zf.getinfo(name)

    def open(self, name: Any, mode: str = "r", pwd: bytes | None = None) -> Any:
        return self._zf.open(name, mode=mode, pwd=pwd)

    def read(self, name: Any, pwd: bytes | None = None) -> bytes:
        """Read and decrypt/decompress a single archive member while enforcing byte quotas."""
        with self._zf.open(name, "r", pwd=pwd) as f:
            chunks: list[bytes] = []
            chunk_size = 64 * 1024
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                self._total_uncompressed_read += len(chunk)
                if self._total_uncompressed_read > self._max_uncompressed:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=(f"ZIP decompressed size exceeded limit of {self._max_uncompressed} bytes."),
                    )
                chunks.append(chunk)
            return b"".join(chunks)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._zf, name)


def open_zip_safely(
    data: bytes | io.BytesIO | Path | str | BinaryIO,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    max_uncompressed: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
    max_members: int = DEFAULT_MAX_ZIP_MEMBERS,
) -> SafeZipFile:
    """Safely open and validate a ZIP archive with strict quota enforcement."""
    if isinstance(data, (bytes, bytearray)):
        if len(data) > max_input_bytes:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"ZIP archive size ({len(data)} bytes) exceeds input limit ({max_input_bytes} bytes).",
            )
        file_obj: Any = io.BytesIO(data)
    elif isinstance(data, (str, Path)):
        p = Path(data)
        st_size = p.stat().st_size
        if st_size > max_input_bytes:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"ZIP archive size ({st_size} bytes) exceeds input limit ({max_input_bytes} bytes).",
            )
        file_obj = open(p, "rb")
    elif isinstance(data, io.BytesIO):
        buf_size = data.getbuffer().nbytes
        if buf_size > max_input_bytes:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"ZIP archive size ({buf_size} bytes) exceeds input limit ({max_input_bytes} bytes).",
            )
        file_obj = data
    else:
        file_obj = data

    zf = zipfile.ZipFile(file_obj, "r")
    return SafeZipFile(
        zf,
        max_uncompressed=max_uncompressed,
        max_ratio=max_ratio,
        max_members=max_members,
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
