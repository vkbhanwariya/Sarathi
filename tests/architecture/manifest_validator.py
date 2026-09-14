"""Validate Sarathi architecture manifest against schema and codebase reality."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def get_repo_root() -> Path:
    """Return repository root path."""
    return Path(__file__).resolve().parents[2]


def _direct_python_components(package_dir: Path) -> set[str]:
    """Return immediate production Python modules/packages owned by one package."""
    components: set[str] = set()
    for path in package_dir.iterdir():
        if path.name.startswith(".") or path.name == "__pycache__":
            continue
        if path.is_file() and path.suffix == ".py" and path.name != "__init__.py":
            components.add(path.stem)
        elif path.is_dir() and (path / "__init__.py").is_file():
            components.add(path.name)
    return components


def validate_manifest(
    manifest_path: Path | None = None,
    schema_path: Path | None = None,
) -> list[str]:
    """Validate architecture.manifest.json against schema and physical production topology."""
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

    try:
        import jsonschema

        try:
            jsonschema.validate(instance=manifest, schema=schema)
        except jsonschema.ValidationError as val_err:
            path = "/".join(str(part) for part in val_err.path)
            errors.append(f"Schema validation error: {val_err.message} at path {path}")
    except ImportError:
        required_keys = [
            "manifest_version",
            "system",
            "source_root",
            "root_package",
            "root_components",
            "dependency_policy",
            "modules",
            "groups",
            "exceptions",
        ]
        for key in required_keys:
            if key not in manifest:
                errors.append(f"Missing required top-level manifest key: {key}")

    src_root = repo_root / manifest.get("source_root", "src")
    if not src_root.exists():
        errors.append(f"Source root does not exist: {src_root}")
        return errors

    root_package_name = manifest.get("root_package", "sarathi")
    root_pkg = src_root / root_package_name
    if not root_pkg.exists():
        errors.append(f"Root package does not exist: {root_pkg}")
        return errors

    declared_root_components = set(manifest.get("root_components", []))
    physical_root_components = {
        path.stem
        for path in root_pkg.iterdir()
        if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
    }
    missing_root = sorted(physical_root_components - declared_root_components)
    stale_root = sorted(declared_root_components - physical_root_components)
    if missing_root:
        errors.append("Undeclared root Python components: " + ", ".join(missing_root))
    if stale_root:
        errors.append("Manifest root components missing on disk: " + ", ".join(stale_root))

    modules = manifest.get("modules", {})
    declared_packages: set[str] = set()
    for mod_name, mod_info in modules.items():
        pkg_dotted = mod_info.get("package", "")
        declared_packages.add(pkg_dotted)
        rel_path = pkg_dotted.replace(".", "/")
        disk_path = src_root / rel_path
        file_path = src_root / f"{rel_path}.py"
        if not disk_path.exists() and not file_path.exists():
            errors.append(f"Module '{mod_name}' declares package '{pkg_dotted}' which does not exist at {disk_path}")
            continue

        if disk_path.is_dir():
            declared_components = set(mod_info.get("components", []))
            physical_components = _direct_python_components(disk_path)
            missing = sorted(physical_components - declared_components)
            stale = sorted(declared_components - physical_components)
            if missing:
                errors.append(
                    f"Module '{mod_name}' has undeclared immediate components: " + ", ".join(missing)
                )
            if stale:
                errors.append(
                    f"Module '{mod_name}' declares components missing on disk: " + ", ".join(stale)
                )

    physical_packages = {
        path.name
        for path in root_pkg.iterdir()
        if path.is_dir() and not path.name.startswith((".", "_")) and (path / "__init__.py").exists()
    }
    for physical in physical_packages:
        expected_dotted = f"{root_package_name}.{physical}"
        if expected_dotted not in declared_packages:
            errors.append(f"Physical package '{physical}' in {root_pkg} is not declared in architecture manifest modules")

    for group_name, group_info in manifest.get("groups", {}).items():
        for member in group_info.get("members", []):
            rel_path = member.replace(".", "/")
            disk_path = src_root / rel_path
            if not disk_path.exists() and not (src_root / f"{rel_path}.py").exists():
                errors.append(f"Group '{group_name}' member '{member}' does not exist on disk at {disk_path}")

    for exception in manifest.get("exceptions", []):
        for side in ("from", "to"):
            endpoint = exception.get(side, "")
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
        for error in errors:
            print(f"  - {error}")
        return 1
    print("[PASS] Architecture manifest is strictly valid and matches production topology.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
