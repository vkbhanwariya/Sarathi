"""Security, sanitization, and serialization utilities for Mukha web server.

Provides host and origin validation against loopback interfaces,
message sanitization to prevent leaking filesystem paths and secrets,
and recursive serialization of dataclasses and enums into JSON-serializable primitives.
"""

from __future__ import annotations

import re
import urllib.parse
from enum import Enum
from typing import Any

from sarathi.dosh import DoshError

# Path sanitization patterns: quoted paths, UNC paths, Windows drive paths, Unix paths
_QUOTED_PATH_PATTERN = re.compile(r"""(?P<q>['"])(?:[A-Za-z]:[\\/]|\\\\|/)[^'"]*(?P=q)""")
_UNC_PATH_PATTERN = re.compile(r"""\\\\[a-zA-Z0-9._-]+\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\s\\/:*?"<>|\r\n,;]*""")
_WIN_PATH_PATTERN = re.compile(r"""[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\s\\/:*?"<>|\r\n,;]*""")
_UNIX_PATH_PATTERN = re.compile(r"""(?:^|(?<=[\s(]))/(?:[^/\s'"()<>\r\n,;]+/+)*[^/\s'"()<>\r\n,;]+""")

_ALLOWED_LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})


def _sanitize_message(msg: str) -> str:
    """Sanitize error messages to eliminate raw filesystem paths, UNC paths, and quotes."""
    if not msg:
        return ""
    res = _QUOTED_PATH_PATTERN.sub("[path]", msg)
    res = _UNC_PATH_PATTERN.sub("[path]", res)
    res = _WIN_PATH_PATTERN.sub("[path]", res)
    res = _UNIX_PATH_PATTERN.sub("[path]", res)
    return " ".join(res.split())


def _format_public_error(dosh_err: DoshError) -> str:
    """Format public DoshError for web presentation without leaking paths or secrets."""
    sanitized = _sanitize_message(dosh_err.message)
    if sanitized:
        return f"{dosh_err.code.name}: {sanitized}"
    return dosh_err.code.name


def _is_authorized_loopback_host(host_header: str) -> bool:
    """Structurally validate Host header against approved loopback endpoints."""
    if not host_header or not isinstance(host_header, str):
        return False
    host_candidate = host_header.strip()
    if not host_candidate:
        return False

    if host_candidate.startswith("["):
        bracket_end = host_candidate.find("]")
        if bracket_end == -1:
            return False
        hostname = host_candidate[: bracket_end + 1]
        rest = host_candidate[bracket_end + 1 :]
        if rest:
            if not rest.startswith(":"):
                return False
            port_str = rest[1:]
            try:
                port = int(port_str)
                if not (1 <= port <= 65535):
                    return False
            except ValueError:
                return False
        return hostname.lower() in _ALLOWED_LOOPBACK_HOSTNAMES

    if ":" in host_candidate:
        parts = host_candidate.split(":", 1)
        hostname = parts[0]
        port_str = parts[1]
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                return False
        except ValueError:
            return False
    else:
        hostname = host_candidate

    return hostname.lower() in _ALLOWED_LOOPBACK_HOSTNAMES


def _is_authorized_loopback_origin(origin_header: str) -> bool:
    """Structurally validate Origin header against approved loopback endpoints."""
    if not origin_header or not isinstance(origin_header, str):
        return False
    try:
        parsed = urllib.parse.urlparse(origin_header)
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.hostname is None or parsed.hostname.lower() not in _ALLOWED_LOOPBACK_HOSTNAMES:
            return False
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return False
    except (ValueError, TypeError):
        return False
    return True


def _serialize_dataclass(obj: Any) -> Any:
    """Recursively convert dataclasses and enums into JSON-serializable primitives."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "__dataclass_fields__"):
        res = {}
        for k in obj.__dataclass_fields__:
            val = getattr(obj, k)
            res[k] = _serialize_dataclass(val)
        return res
    if isinstance(obj, (list, tuple)):
        return [_serialize_dataclass(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_dataclass(v) for k, v in obj.items()}
    return str(obj)
