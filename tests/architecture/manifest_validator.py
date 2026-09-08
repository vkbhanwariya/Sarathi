"""Validate Sarathi architecture manifest against schema and codebase reality."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def get_repo_root() -> Path:
    """Return repository root path."""
    return Path(__file__).resolve().parents[2]


def validate_manifest(
    manifest_path: Path | None = None,
    schema_path: Path | None = None,
) -> list[str]:
    """Validate architecture.manifest.json against schema and physical filesystem.

    Returns a list of error strings. Empty list indicates complete validation success.
    """
    repo_root = get_repo_root()
    if manifest_path is None:
        manifest_path = repo_root / "Vedas" / "architecture.manifest.json"
    if schema_path is None:
        schema_path = repo_root / "Vedas" / "architecture.manifest.schema.json"

    errors: list[str] = []

    if not manifest_path.exists():
        return [f"Manifest file not found: {manifest_path}"]
    if not schema_path.exists():
        return [f"Schema file not found: {schema_path}"]

    try:
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Failed to parse manifest JSON: {exc}"]

    try:
        schema: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Failed to parse schema JSON: {exc}"]

    # 1. Schema validation via jsonschema if available
    try:
        import jsonschema

        try:
            jsonschema.validate(instance=manifest, schema=schema)
        except jsonschema.ValidationError as val_err:
            errors.append(f"Schema validation error: {val_err.message} at path {'/'.join(str(p) for p in val_err.path)}")
    except ImportError:
        # Fallback structural checks if jsonschema not yet installed
        required_keys = [
            "manifest_version",
            "system",
            "source_root",
            "root_package",
            "dependency_policy",
            "modules",
            "groups",
            "exceptions",
        ]
        for key in required_keys:
            if key not in manifest:
                errors.append(f"Missing required top-level manifest key: {key}")

    # 2. Source root existence
    src_root = repo_root / manifest.get("source_root", "src")
    if not src_root.exists():
        errors.append(f"Source root does not exist: {src_root}")
        return errors

    root_pkg = src_root / manifest.get("root_package", "sarathi")
    if not root_pkg.exists():
        errors.append(f"Root package does not exist: {root_pkg}")
        return errors

    # 3. Verify all declared modules exist on disk
    modules = manifest.get("modules", {})
    declared_packages: set[str] = set()
    for mod_name, mod_info in modules.items():
        pkg_dotted = mod_info.get("package", "")
        declared_packages.add(pkg_dotted)
        rel_path = pkg_dotted.replace(".", "/")
        disk_path = src_root / rel_path
        if not disk_path.exists() and not (src_root / f"{rel_path}.py").exists():
            errors.append(f"Module '{mod_name}' declares package '{pkg_dotted}' which does not exist at {disk_path}")

    # 4. Verify all physical top-level packages in root_pkg are declared in modules
    physical_packages = {
        p.name
        for p in root_pkg.iterdir()
        if p.is_dir() and not p.name.startswith((".", "_")) and (p / "__init__.py").exists()
    }
    for phys in physical_packages:
        expected_dotted = f"{manifest.get('root_package', 'sarathi')}.{phys}"
        if expected_dotted not in declared_packages:
            errors.append(f"Physical package '{phys}' in {root_pkg} is not declared in architecture manifest modules")

    # 5. Verify groups and members
    groups = manifest.get("groups", {})
    for grp_name, grp_info in groups.items():
        members = grp_info.get("members", [])
        for member in members:
            rel_path = member.replace(".", "/")
            disk_path = src_root / rel_path
            if not disk_path.exists() and not (src_root / f"{rel_path}.py").exists():
                errors.append(f"Group '{grp_name}' member '{member}' does not exist on disk at {disk_path}")

    # 6. Verify exceptions
    exceptions = manifest.get("exceptions", [])
    for exc in exceptions:
        for side in ("from", "to"):
            endpoint = exc.get(side, "")
            rel_path = endpoint.replace(".", "/")
            disk_path = src_root / rel_path
            if not disk_path.exists() and not (src_root / f"{rel_path}.py").exists():
                errors.append(f"Exception '{side}' target '{endpoint}' does not exist on disk at {disk_path}")

    return errors


def main() -> int:
    """CLI entrypoint."""
    errors = validate_manifest()
    if errors:
        print("[FAIL] Architecture manifest validation failed:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("[PASS] Architecture manifest is strictly valid and matches disk topology.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
