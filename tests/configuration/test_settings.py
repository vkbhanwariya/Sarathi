"""Unit tests for Sutra — Configuration."""

from pathlib import Path
import tomllib
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sutra import Settings, load_settings
import sarathi.sutra as sutra_module


class TestSettings:
    def test_empty_settings(self) -> None:
        s = Settings()
        assert s.data == {}
        assert s.sections == ()
        assert s.get_section("telemetry") is None
        assert s.section("telemetry") is None
        assert s.get("input_root") is None
        assert s.get("input_root", "default_val") == "default_val"
        assert "input_root" not in s

    def test_valid_settings_and_recursive_immutability(self) -> None:
        raw = {
            "version": "2.0.0",
            "telemetry": {
                "enabled": True,
                "retention_days": 30,
                "exporters": ["console", "file"],
                "nested_map": {"k1": "v1"},
            },
            "runtime": {
                "max_workers": 4,
            },
        }
        s = Settings(raw)
        assert s["version"] == "2.0.0"
        assert "telemetry" in s
        assert set(s.sections) == {"telemetry", "runtime"}

        # Section access
        telem = s.get_section("telemetry")
        assert telem is not None
        assert telem["enabled"] is True
        assert telem["retention_days"] == 30
        assert telem["exporters"] == ("console", "file")
        assert isinstance(telem["exporters"], tuple)

        # Immutability of root
        with pytest.raises(TypeError):
            s.data["version"] = "3.0.0"  # type: ignore

        # Immutability of section
        with pytest.raises(TypeError):
            telem["enabled"] = False  # type: ignore

        # Immutability of nested map
        with pytest.raises(TypeError):
            telem["nested_map"]["k1"] = "v2"  # type: ignore

    def test_section_absent_returns_none_without_inventing_defaults(self) -> None:
        s = Settings({"version": "2.0.0"})
        assert s.get_section("non_existent_section") is None
        assert s.section("non_existent_section") is None

    def test_section_on_scalar_returns_none(self) -> None:
        s = Settings({"scalar_key": "scalar_value"})
        assert s.get_section("scalar_key") is None

    def test_invalid_settings_init_type(self) -> None:
        with pytest.raises(TypeError, match="Settings data must be a Mapping"):
            Settings("not a mapping")  # type: ignore

    def test_invalid_section_name_type(self) -> None:
        s = Settings({"a": {"b": 1}})
        with pytest.raises(TypeError, match="Section name must be a string"):
            s.get_section(123)  # type: ignore


class TestLoadSettings:
    def test_load_valid_toml_file(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            """
[telemetry]
enabled = true
level = "INFO"
exporters = ["console", "jsonl"]

[storage]
input_root = "Input"
output_root = "Output"
""",
            encoding="utf-8",
        )

        settings = load_settings(toml_file)
        assert isinstance(settings, Settings)
        assert "telemetry" in settings
        assert "storage" in settings

        telem = settings.get_section("telemetry")
        assert telem is not None
        assert telem["enabled"] is True
        assert telem["level"] == "INFO"
        assert telem["exporters"] == ("console", "jsonl")

        storage = settings.section("storage")
        assert storage is not None
        assert storage["input_root"] == "Input"

    def test_load_accepts_str_path(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "simple.toml"
        toml_file.write_text('key = "value"\n', encoding="utf-8")

        settings = load_settings(str(toml_file))
        assert settings["key"] == "value"

    def test_missing_file_raises_dosh_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing_config.toml"
        with pytest.raises(DoshError) as exc_info:
            load_settings(missing)

        err = exc_info.value
        assert err.code is FailureCode.INVALID_CONFIGURATION
        assert "could not be opened" in err.message
        assert isinstance(err.__cause__, FileNotFoundError)

    def test_wrong_extension_raises_dosh_error(self, tmp_path: Path) -> None:
        json_file = tmp_path / "config.json"
        json_file.write_text('{"key": "value"}', encoding="utf-8")

        with pytest.raises(DoshError) as exc_info:
            load_settings(json_file)

        err = exc_info.value
        assert err.code is FailureCode.INVALID_CONFIGURATION
        assert "must have a .toml extension" in err.message

    def test_directory_path_raises_dosh_error(self, tmp_path: Path) -> None:
        dir_path = tmp_path / "fake.toml"
        dir_path.mkdir()

        with pytest.raises(DoshError) as exc_info:
            load_settings(dir_path)

        err = exc_info.value
        assert err.code is FailureCode.INVALID_CONFIGURATION
        assert isinstance(err.__cause__, IsADirectoryError)

    def test_malformed_toml_raises_dosh_error_with_chaining(self, tmp_path: Path) -> None:
        bad_toml = tmp_path / "bad.toml"
        bad_toml.write_text("invalid = [ unclosed_array\n", encoding="utf-8")

        with pytest.raises(DoshError) as exc_info:
            load_settings(bad_toml)

        err = exc_info.value
        assert err.code is FailureCode.INVALID_CONFIGURATION
        assert "Failed to parse TOML configuration" in err.message
        assert isinstance(err.__cause__, tomllib.TOMLDecodeError)

    def test_invalid_path_argument_type(self) -> None:
        with pytest.raises(TypeError, match="path must be a str or Path"):
            load_settings(12345)  # type: ignore

    def test_error_context_contains_no_raw_file_content(self, tmp_path: Path) -> None:
        bad_toml = tmp_path / "secret.toml"
        bad_toml.write_text("secret_password = unclosed", encoding="utf-8")

        with pytest.raises(DoshError) as exc_info:
            load_settings(bad_toml)

        err = exc_info.value
        assert "secret_password" not in str(err)
        assert "unclosed" not in str(err)
        for val in err.context.values():
            assert "secret_password" not in str(val)

    def test_sutra_exports(self) -> None:
        expected = {"Settings", "load_settings"}
        assert set(sutra_module.__all__) == expected
        for name in expected:
            assert hasattr(sutra_module, name)
