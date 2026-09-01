"""TOML Configuration Loader for Sutra in Sarathi V2.

Loads an explicit TOML configuration file into immutable Settings.
Raises DoshError with FailureCode.INVALID_CONFIGURATION on missing, unreadable,
or malformed files.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Union

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import ExecutionContext
from sarathi.sutra.settings import Settings

if TYPE_CHECKING:
    from sarathi.darpana import Darpana


def load_settings(
    path: Union[str, Path],
    darpana: Darpana | None = None,
    context: ExecutionContext | None = None,
) -> Settings:
    """Load and parse an explicit TOML configuration file into immutable Settings.

    Args:
        path: Explicit file path to a .toml configuration file.
        darpana: Optional injected Darpana telemetry service.
        context: Optional ExecutionContext for telemetry correlation.

    Returns:
        Settings: Immutable settings object.

    Raises:
        DoshError(FailureCode.INVALID_CONFIGURATION): On missing, unreadable, or malformed TOML.
        TypeError: If path is not a str or Path, or darpana/context are of invalid types.
    """
    if not isinstance(path, (str, Path)):
        raise TypeError(f"path must be a str or Path, got {type(path).__name__}.")
    if darpana is not None:
        from sarathi.darpana import Darpana as DarpanaService

        if not isinstance(darpana, DarpanaService):
            raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")
    if context is not None and not isinstance(context, ExecutionContext):
        raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

    scope = (
        darpana.time_scope(
            context=context,
            phase_name="configuration",
            component="sutra.loader",
            attributes={"config_file": Path(path).name},
        )
        if darpana is not None and context is not None
        else nullcontext()
    )
    with scope:
        return _load_settings_internal(path)


def _load_settings_internal(path: Union[str, Path]) -> Settings:
    file_path = Path(path)

    if file_path.suffix.lower() != ".toml":
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Configuration file must have a .toml extension, got {file_path.name!r}.",
        )

    try:
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file does not exist: {file_path.name}")
        if not file_path.is_file():
            raise IsADirectoryError(f"Configuration path is not a regular file: {file_path.name}")

        with file_path.open("rb") as f:
            raw_data = tomllib.load(f)

    except (FileNotFoundError, IsADirectoryError) as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Configuration file could not be opened: {file_path.name}.",
        ) from err
    except tomllib.TOMLDecodeError as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to parse TOML configuration in {file_path.name}.",
        ) from err
    except OSError as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"I/O error reading configuration file: {file_path.name}.",
        ) from err

    if not isinstance(raw_data, dict):
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Configuration root in {file_path.name} must be a TOML table.",
        )

    return Settings(raw_data)
