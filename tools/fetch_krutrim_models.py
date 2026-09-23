"""Krutrim-Translate Model Provisioning & Integration Tool for Sarathi.

Downloads or copies Krutrim-Translate (4096 context CTranslate2) weights into
Sarathi's canonical translation model storage under:
    data/translation/models/krutrim/hi-en/
    data/translation/models/krutrim/en-hi/
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DEST_DIR = ROOT_DIR / "data" / "translation" / "models" / "krutrim"
MANIFEST_PATH = ROOT_DIR / "data" / "translation" / "manifest.json"

HF_BASE_URL = "https://huggingface.co/krutrim-ai-labs/Krutrim-Translate/resolve/main"

KRUTRIM_FILE_MAP: dict[str, list[tuple[str, str]]] = {
    "hi-en": [
        ("ct_model_indic_english/config.json", "config.json"),
        ("ct_model_indic_english/model.bin", "model.bin"),
        ("ct_model_indic_english/source_vocabulary.json", "source_vocabulary.json"),
        ("ct_model_indic_english/target_vocabulary.json", "target_vocabulary.json"),
        ("ct_model_indic_english/vocab/model.SRC", "model.SRC"),
        ("ct_model_indic_english/vocab/model.TGT", "model.TGT"),
    ],
    "en-hi": [
        ("ct_model_english_indic/config.json", "config.json"),
        ("ct_model_english_indic/model.bin", "model.bin"),
        ("ct_model_english_indic/source_vocabulary.json", "source_vocabulary.json"),
        ("ct_model_english_indic/target_vocabulary.json", "target_vocabulary.json"),
        ("ct_model_english_indic/vocab/model.SRC", "model.SRC"),
        ("ct_model_english_indic/vocab/model.TGT", "model.TGT"),
    ],
}


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file in 64KB chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def install_from_local_folder(source_dir: Path, dest_root: Path = DEFAULT_DEST_DIR) -> bool:
    """Import Krutrim CTranslate2 models from a local folder (e.g. from static_data/)."""
    print(f"[Krutrim Provisioning] Scanning local source directory: {source_dir}")

    hi_en_candidates = [
        source_dir / "ct_model_indic_english",
        source_dir / "hi-en",
        source_dir / "indic_english",
    ]
    en_hi_candidates = [
        source_dir / "ct_model_english_indic",
        source_dir / "en-hi",
        source_dir / "english_indic",
    ]

    hi_en_src = next((p for p in hi_en_candidates if p.is_dir() and (p / "model.bin").is_file()), None)
    en_hi_src = next((p for p in en_hi_candidates if p.is_dir() and (p / "model.bin").is_file()), None)

    if not hi_en_src and not en_hi_src:
        print("  [Error] No valid CTranslate2 model directories found in source directory.")
        print("  Expected 'ct_model_indic_english' and/or 'ct_model_english_indic' with 'model.bin'.")
        return False

    dest_root.mkdir(parents=True, exist_ok=True)

    def _copy_dir(src: Path, dest: Path, label: str) -> bool:
        print(f"  Copying {label} from {src} to {dest}...")
        dest.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.is_file():
                dest_file = dest / item.name
                shutil.copy2(item, dest_file)
                print(f"    [OK] {item.name} ({item.stat().st_size:,} bytes)")
        # If model.SRC is in vocab/
        if (src / "vocab" / "model.SRC").is_file():
            shutil.copy2(src / "vocab" / "model.SRC", dest / "model.SRC")
            shutil.copy2(src / "vocab" / "model.TGT", dest / "model.TGT")
        if (dest / "model.SRC").is_file() and not (dest / "spm.model").is_file():
            shutil.copy2(dest / "model.SRC", dest / "spm.model")
        return (dest / "model.bin").is_file()

    ok = True
    if hi_en_src:
        ok = _copy_dir(hi_en_src, dest_root / "hi-en", "Hindi -> English (hi-en)") and ok
    if en_hi_src:
        ok = _copy_dir(en_hi_src, dest_root / "en-hi", "English -> Hindi (en-hi)") and ok

    print("[Krutrim Provisioning] Local installation completed successfully.")
    return ok


def download_file_with_progress(url: str, dest_path: Path, token: str) -> bool:
    """Download a single file over HTTPS with bearer auth and streaming progress."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Sarathi-Krutrim-Downloader",
            "Authorization": f"Bearer {token}",
        },
    )
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(".downloading")

    try:
        with urllib.request.urlopen(req) as resp, open(temp_path, "wb") as f:
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            while chunk := resp.read(1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100.0
                    print(
                        f"\r    {dest_path.name}: {downloaded / 1024 / 1024:.1f} MB / "
                        f"{total_size / 1024 / 1024:.1f} MB ({pct:.1f}%)",
                        end="",
                        flush=True,
                    )
                else:
                    print(f"\r    {dest_path.name}: {downloaded / 1024 / 1024:.1f} MB", end="", flush=True)
        print()
        temp_path.replace(dest_path)
        return True
    except urllib.error.HTTPError as exc:
        print()
        if exc.code == 401:
            print("  [Error 401: Unauthorized] Token invalid or expired. Check your token at https://huggingface.co/settings/tokens")
        elif exc.code == 403:
            print("  [Error 403: Forbidden] Access not granted. Please accept license at https://huggingface.co/krutrim-ai-labs/Krutrim-Translate")
        else:
            print(f"  [Error {exc.code}] Download failed for {url}: {exc.reason}")
        if temp_path.exists():
            temp_path.unlink()
        return False
    except Exception as exc:
        print(f"\n  [Error] Failed to download {dest_path.name}: {exc}")
        if temp_path.exists():
            temp_path.unlink()
        return False


def download_from_huggingface(token: str, dest_root: Path = DEFAULT_DEST_DIR) -> bool:
    """Download Krutrim-Translate model files directly using HTTPS and user token."""
    clean_token = token.strip()
    if not clean_token:
        print("  [Error] HuggingFace token is required for downloading gated Krutrim weights.")
        print("  Usage: uv run python tools/fetch_krutrim_models.py --download-hf --token <YOUR_HF_TOKEN>")
        return False

    print(f"\n[Krutrim Provisioning] Starting download to {dest_root}...")
    dest_root.mkdir(parents=True, exist_ok=True)

    overall_ok = True
    for direction, files in KRUTRIM_FILE_MAP.items():
        dir_path = dest_root / direction
        print(f"\n[Direction: {direction}]")
        for remote_subpath, local_filename in files:
            dest_file = dir_path / local_filename
            if dest_file.is_file() and dest_file.stat().st_size > 0:
                print(f"  [OK] Already present: {local_filename} ({dest_file.stat().st_size:,} bytes)")
                continue

            url = f"{HF_BASE_URL}/{remote_subpath}"
            print(f"  Downloading {local_filename}...")
            ok = download_file_with_progress(url, dest_file, token=clean_token)
            if not ok:
                overall_ok = False
                break

        # Generate spm.model duplicate for seamless SentencePiece fallback
        if (dir_path / "model.SRC").is_file() and not (dir_path / "spm.model").is_file():
            shutil.copy2(dir_path / "model.SRC", dir_path / "spm.model")

    return overall_ok


def verify_installed_models(dest_root: Path = DEFAULT_DEST_DIR) -> bool:
    """Verify that Krutrim models in dest_root are complete and ready for execution."""
    print(f"\n[Verification] Verifying Krutrim models under {dest_root}:")
    all_ok = True
    for direction in ("hi-en", "en-hi"):
        d_path = dest_root / direction
        if not d_path.is_dir():
            print(f"  [-] {direction}: Directory missing.")
            all_ok = False
            continue

        has_model = (d_path / "model.bin").is_file()
        has_spm = (d_path / "spm.model").is_file() or (d_path / "model.SRC").is_file()
        if has_model and has_spm:
            model_size = (d_path / "model.bin").stat().st_size
            print(f"  [+] {direction}: Valid CTranslate2 model ({model_size:,} bytes).")
        else:
            print(f"  [-] {direction}: Incomplete (has_model={has_model}, has_spm={has_spm}).")
            all_ok = False
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Krutrim-Translate Model Provisioning Tool for Sarathi")
    parser.add_argument("--source-dir", type=Path, help="Local directory containing Krutrim ct_model folders")
    parser.add_argument("--download-hf", action="store_true", help="Download directly from HuggingFace via HTTPS")
    parser.add_argument("--token", type=str, help="HuggingFace User Access Token")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DEST_DIR, help="Destination directory")
    parser.add_argument("--verify-only", action="store_true", help="Verify existing Krutrim models on disk")

    args = parser.parse_args()

    if args.verify_only:
        ok = verify_installed_models(args.destination)
        return 0 if ok else 1

    if args.source_dir:
        ok = install_from_local_folder(args.source_dir, dest_root=args.destination)
        if ok:
            verify_installed_models(args.destination)
        return 0 if ok else 1

    if args.download_hf:
        token = args.token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if not token:
            print("[Error] HuggingFace token is required.")
            print("Please pass --token hf_xxx or set $env:HF_TOKEN='hf_xxx'.")
            return 1
        ok = download_from_huggingface(token=token, dest_root=args.destination)
        if ok:
            verify_installed_models(args.destination)
        return 0 if ok else 1

    # Default action: verify
    verify_installed_models(args.destination)
    print("\nUsage:")
    print("  1. Download directly from HuggingFace:")
    print("     uv run python tools/fetch_krutrim_models.py --download-hf --token <YOUR_HF_TOKEN>")
    print("  2. Import from a local download folder:")
    print("     uv run python tools/fetch_krutrim_models.py --source-dir /path/to/downloaded/models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
