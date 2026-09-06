"""Architecture manifest and schema validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from tools.architecture.validate_manifest import get_repo_root, validate_manifest


@pytest.mark.architecture
class TestArchitectureManifest:
    """Verify architectural manifest integrity, schema adherence, and topology match."""

    def test_manifest_matches_schema(self) -> None:
        """Manifest must strictly validate against the architecture schema."""
        repo_root = get_repo_root()
        manifest_path = repo_root / "Vedas" / "architecture.manifest.json"
        schema_path = repo_root / "Vedas" / "architecture.manifest.schema.json"

        assert manifest_path.exists(), f"Manifest not found: {manifest_path}"
        assert schema_path.exists(), f"Schema not found: {schema_path}"

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        # Strict JSON Schema validation
        jsonschema.validate(instance=manifest, schema=schema)

    def test_manifest_matches_filesystem_and_packages(self) -> None:
        """Validator utility must find zero topological or declaration errors."""
        errors = validate_manifest()
        assert not errors, "Manifest validation errors:\n" + "\n".join(errors)

    def test_manifest_enforces_default_deny(self) -> None:
        """Manifest must declare a default-deny policy for internal dependencies."""
        repo_root = get_repo_root()
        manifest = json.loads((repo_root / "Vedas" / "architecture.manifest.json").read_text(encoding="utf-8"))
        policy = manifest.get("dependency_policy", {}).get("default_internal_policy")
        assert policy == "deny", f"Expected default_internal_policy='deny', got '{policy}'"

    def test_agni_is_the_sole_composition_root(self) -> None:
        """Only sarathi.agni is permitted to declare composition_root: True."""
        repo_root = get_repo_root()
        manifest = json.loads((repo_root / "Vedas" / "architecture.manifest.json").read_text(encoding="utf-8"))
        modules = manifest.get("modules", {})

        composition_roots = [
            mod_info.get("package")
            for mod_info in modules.values()
            if mod_info.get("composition_root") is True
        ]
        assert composition_roots == ["sarathi.agni"], (
            f"Expected only ['sarathi.agni'] as composition root, found: {composition_roots}"
        )
