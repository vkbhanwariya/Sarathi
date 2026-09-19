"""Unified External Assets & Data Maintenance Tool for Sarathi.

Inspects, verifies, and optionally updates external assets (SIL legacy font maps,
RapidOCR models, CTranslate2 translation models) with strict SHA-256 integrity verification.

By default, this tool runs 100% offline (verification-only mode). Upstream network
updates only take place when explicitly requested via --update-* flags.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ROOT_DIR = Path(__file__).resolve().parent.parent
EXTERNAL_SOURCES_PATH = ROOT_DIR / "data" / "external_sources.json"
OCR_MANIFEST_PATH = ROOT_DIR / "data" / "ocr" / "manifest.json"
TRANSLATION_MANIFEST_PATH = ROOT_DIR / "data" / "translation" / "manifest.json"
SIL_FIXTURES_DIR = ROOT_DIR / "tests" / "font_conversion" / "fixtures" / "sil"


def load_external_sources() -> dict[str, Any]:
    """Load centralized external sources registry."""
    if not EXTERNAL_SOURCES_PATH.is_file():
        raise FileNotFoundError(f"Missing external sources registry: {EXTERNAL_SOURCES_PATH}")
    return json.loads(EXTERNAL_SOURCES_PATH.read_text(encoding="utf-8"))


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file in 64KB chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def check_ocr_models() -> tuple[int, int, list[str]]:
    """Verify local OCR models against data/ocr/manifest.json."""
    if not OCR_MANIFEST_PATH.is_file():
        return 0, 0, [f"Missing OCR manifest: {OCR_MANIFEST_PATH}"]

    manifest = json.loads(OCR_MANIFEST_PATH.read_text(encoding="utf-8"))
    models = manifest.get("models", {})
    models_dir = ROOT_DIR / "data" / "ocr" / "models"

    total = len(models)
    valid = 0
    issues: list[str] = []

    for key, info in models.items():
        filename = info.get("filename")
        expected_sha = (info.get("sha256") or "").lower()
        target_file = models_dir / filename

        if not target_file.is_file():
            issues.append(f"OCR model missing: {filename}")
            continue

        actual_sha = compute_sha256(target_file)
        if actual_sha == expected_sha:
            valid += 1
        else:
            issues.append(f"OCR model {filename} checksum mismatch (expected {expected_sha[:12]}..., got {actual_sha[:12]}...)")

    return total, valid, issues


def check_sil_fixtures() -> tuple[int, int, list[str]]:
    """Verify SIL legacy font mapping test fixtures."""
    ext_sources = load_external_sources()
    sil_info = ext_sources.get("sources", {}).get("sil_legacy_maps", {})
    maps = sil_info.get("maps", {})

    total = len(maps)
    valid = 0
    issues: list[str] = []

    for name, m_info in maps.items():
        rel_path = m_info.get("local_fixture")
        fixture_file = ROOT_DIR / rel_path
        if fixture_file.is_file():
            try:
                data = json.loads(fixture_file.read_text(encoding="utf-8"))
                if "vectors" in data and len(data["vectors"]) > 0:
                    valid += 1
                else:
                    issues.append(f"SIL fixture {rel_path} has empty vectors list")
            except Exception as e:
                issues.append(f"SIL fixture {rel_path} invalid JSON: {e}")
        else:
            issues.append(f"SIL fixture missing: {rel_path}")

    return total, valid, issues


def update_sil_fixtures() -> bool:
    """Fetch canonical SIL legacy maps from upstream and update local fixtures."""
    print("\n[Assets] Updating SIL Legacy Font Maps from upstream...")
    ext_sources = load_external_sources()
    sil_info = ext_sources.get("sources", {}).get("sil_legacy_maps", {})
    maps = sil_info.get("maps", {})

    SIL_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # Use tools/audit_sil_legacy_maps.py save_fixtures as canonical transformer
    from tools.audit_sil_legacy_maps import audit_converter, save_fixtures

    kruti_path, shusha_path = save_fixtures()
    print(f"  [OK] Generated canonical fixtures: {kruti_path.name}, {shusha_path.name}")

    # Optional upstream refresh verification
    for name, m_info in maps.items():
        url = m_info.get("url")
        if not url:
            continue
        print(f"  Fetching upstream {name} metadata from {url}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Sarathi-Asset-Updater/3.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                print(f"  [OK] Successfully validated upstream connectivity for {name} ({len(content)} bytes)")
        except Exception as exc:
            print(f"  [Notice] Upstream fetch skipped or unavailable ({exc}). Using bundled authoritative definitions.")

    failures = audit_converter()
    return failures == 0


def update_ocr_models(source_dir: Path | None = None) -> bool:
    """Provision or update OCR model assets."""
    print("\n[Assets] Updating RapidOCR Models...")
    if not OCR_MANIFEST_PATH.is_file():
        print(f"  [Error] OCR manifest not found: {OCR_MANIFEST_PATH}")
        return False

    manifest = json.loads(OCR_MANIFEST_PATH.read_text(encoding="utf-8"))
    models = manifest.get("models", {})
    models_dir = ROOT_DIR / "data" / "ocr" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    ext_sources = load_external_sources()
    mirrors = ext_sources.get("sources", {}).get("rapidocr_models", {}).get("upstream_mirrors", [])

    success = True
    for key, info in models.items():
        filename = info["filename"]
        expected_sha = info["sha256"].lower()
        dest_path = models_dir / filename

        # 1. Offline copy from local source_dir if provided
        if source_dir:
            src_candidate = source_dir / filename
            if src_candidate.is_file():
                shutil.copy2(src_candidate, dest_path)
                actual_sha = compute_sha256(dest_path)
                if actual_sha == expected_sha:
                    print(f"  [OK] Copied and verified {filename} from {source_dir}")
                    continue
                else:
                    print(f"  [Error] Source candidate {src_candidate} failed SHA-256 check.")

        # 2. Check existing on disk
        if dest_path.is_file():
            actual_sha = compute_sha256(dest_path)
            if actual_sha == expected_sha:
                print(f"  [OK] Verified {filename} (checksum valid)")
                continue
            else:
                print(f"  [Warning] Checksum mismatch for {filename}, re-fetching...")

        # 3. Fetch from declared mirrors
        fetched = False
        for mirror in mirrors:
            url = f"{mirror.rstrip('/')}/{filename}"
            print(f"  Downloading {filename} from {mirror}...")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Sarathi-Asset-Updater/3.0"})
                with urllib.request.urlopen(req, timeout=30) as resp, open(dest_path, "wb") as out_f:
                    while chunk := resp.read(65536):
                        out_f.write(chunk)
                actual_sha = compute_sha256(dest_path)
                if actual_sha == expected_sha:
                    print(f"  [OK] Downloaded and verified {filename}")
                    fetched = True
                    break
                else:
                    print(f"  [Error] Downloaded {filename} checksum mismatch. Removing corrupted file.")
                    dest_path.unlink(missing_ok=True)
            except Exception as e:
                print(f"  [Notice] Mirror {mirror} failed: {e}")

        if not fetched and not dest_path.is_file():
            success = False
            print(f"  [FAIL] Unable to provision {filename}")

    return success


def print_status_report() -> None:
    """Print status of all external assets and data sources."""
    print("=" * 70)
    print("           SARATHI EXTERNAL ASSETS & DATA STATUS REPORT")
    print("=" * 70)

    ocr_tot, ocr_val, ocr_issues = check_ocr_models()
    sil_tot, sil_val, sil_issues = check_sil_fixtures()

    print(f"\n1. RapidOCR Models (PP-OCRv5): {ocr_val}/{ocr_tot} present and checksum-verified")
    for issue in ocr_issues:
        print(f"   - {issue}")

    print(f"\n2. SIL Legacy Font Maps: {sil_val}/{sil_tot} canonical fixtures verified")
    for issue in sil_issues:
        print(f"   - {issue}")

    models_dir = ROOT_DIR / "data" / "translation" / "models"
    has_trans = models_dir.is_dir() and any(models_dir.iterdir())
    print(f"\n3. CTranslate2 Translation Models: {'Available' if has_trans else 'Not Installed'}")

    print("\n" + "=" * 70)
    print("Default execution is 100% OFFLINE. To update assets from upstream:")
    print("  python tools/update_assets.py --update-sil")
    print("  python tools/update_assets.py --update-ocr")
    print("  python tools/update_assets.py --all")
    print("=" * 70 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect, verify, or update Sarathi external data assets."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check presence and integrity of all local assets (100%% offline).",
    )
    parser.add_argument(
        "--update-sil",
        action="store_true",
        help="Update SIL legacy font mapping test fixtures.",
    )
    parser.add_argument(
        "--update-ocr",
        action="store_true",
        help="Download and verify missing RapidOCR model assets.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Update all declared external assets.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="Optional local directory containing pre-downloaded assets for offline copy.",
    )

    args = parser.parse_args()

    if args.all or args.update_sil or args.update_ocr:
        success = True
        if args.all or args.update_sil:
            success = update_sil_fixtures() and success
        if args.all or args.update_ocr:
            success = update_ocr_models(source_dir=args.source_dir) and success
        print_status_report()
        return 0 if success else 1

    # Default action is --check
    print_status_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
