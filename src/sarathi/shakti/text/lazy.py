"""Lazy export helper for packages to defer module imports."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any


def lazy_exports(package_globals: dict[str, Any], export_map: Mapping[str, str]) -> None:
    """Install __getattr__ and __dir__ into package_globals for lazy exports.

    export_map maps attribute name to target import specifier, e.g.:
    "OCRCapability": ".capability:OCRCapability"
    """
    package_name = package_globals.get("__name__", "")
    package_globals["_LAZY_EXPORTS"] = export_map

    def __getattr__(name: str) -> Any:
        if name not in export_map:
            raise AttributeError(f"module {package_name!r} has no attribute {name!r}")

        target = export_map[name]
        if ":" in target:
            mod_part, attr_name = target.split(":", 1)
        else:
            mod_part, attr_name = target, name

        if mod_part.startswith("."):
            mod = importlib.import_module(mod_part, package=package_name)
        else:
            mod = importlib.import_module(mod_part)

        val = getattr(mod, attr_name) if attr_name else mod
        package_globals[name] = val
        return val

    def __dir__() -> list[str]:
        return sorted(set(package_globals.keys()) | set(export_map.keys()))

    package_globals["__getattr__"] = __getattr__
    package_globals["__dir__"] = __dir__
