"""TOML Configuration Loader for Sutra in Sarathi V2.

Loads an explicit TOML configuration file into immutable Settings.
Raises DoshError with FailureCode.INVALID_CONFIGURATION on missing, unreadable,
or malformed files.
"""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Union

from sarathi.dosh import DoshError, FailureCode
from sarathi.sutra.settings import Settings


def load_settings(path: Union[str, Path]) -> Settings:
    """Load and parse an explicit TOML configuration file into immutable Settings.

    Args:
        path: Explicit file path to a .toml configuration file.

    Returns:
        Settings: Immutable settings object.

    Raises:
        DoshError(FailureCode.INVALID_CONFIGURATION): On missing, unreadable, or malformed TOML.
        TypeError: If path is not a str or Path.
    """
    if not isinstance(path, (str, Path)):
        raise TypeError(f"path must be a str or Path, got {type(path).__name__}.")

    file_path = Path(path)

    if file_path.suffix.lower() != ".toml":
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Configuration file must have a .toml extension, got {file_path.name!r}.",
            context={"path": str(file_path)},
        )

    try:
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file does not exist: {file_path}")
        if not file_path.is_file():
            raise IsADirectoryError(f"Configuration path is not a regular file: {file_path}")

        with file_path.open("rb") as f:
            raw_data = tomllib.load(f)

    except (FileNotFoundError, IsADirectoryError) as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Configuration file could not be opened: {file_path.name}.",
            context={"path": str(file_path)},
        ) from err
    except tomllib.TOMLDecodeError as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to parse TOML configuration in {file_path.name}.",
            context={"path": str(file_path)},
        ) from err
    except OSError as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"I/O error reading configuration file: {file_path.name}.",
            context={"path": str(file_path)},
        ) from err

    if not isinstance(raw_data, dict):
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Configuration root in {file_path.name} must be a TOML table.",
            context={"path": str(file_path)},
        )

    return Settings(raw_data)
