"""Architecture manifest sanity tests.

The manifest is an inventory and documentation aid, not a second dependency compiler.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from tests.architecture.manifest_validator import get_repo_root, validate_manifest


@pytest.mark.architecture
class TestArchitectureManifest:
    def test_manifest_matches_schema(self) -> None:
        repo_root = get_repo_root()
        manifest = json.loads((repo_root / "Vedas" / "architecture.manifest.json").read_text(encoding="utf-8"))
        schema = json.loads((repo_root / "Vedas" / "architecture.manifest.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(instance=manifest, schema=schema)

    def test_manifest_matches_current_packages(self) -> None:
        errors = validate_manifest()
        assert not errors, "Manifest validation errors:\n" + "\n".join(errors)

    def test_internal_dependency_policy_is_pragmatic(self) -> None:
        repo_root = get_repo_root()
        manifest = json.loads((repo_root / "Vedas" / "architecture.manifest.json").read_text(encoding="utf-8"))
        assert manifest["dependency_policy"]["default_internal_policy"] == "allow"

    def test_single_application_composition_root(self) -> None:
        repo_root = get_repo_root()
        manifest = json.loads((repo_root / "Vedas" / "architecture.manifest.json").read_text(encoding="utf-8"))
        roots = [
            info["package"]
            for info in manifest["modules"].values()
            if info.get("composition_root") is True
        ]
        assert roots == ["sarathi.agni"]
