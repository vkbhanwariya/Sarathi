"""Offline conversion utility: export MWirelabs/ne-ocr (DocTR ViTSTR) to ONNX format.

This script runs in an ephemeral environment (e.g., via `uv run --with torch --with python-doctr`)
so that PyTorch and DocTR are NEVER added to Sarathi's production runtime dependencies.

Usage:
    uv run --with torch --with python-doctr --with huggingface_hub python tools/export_ne_ocr_onnx.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("export_ne_ocr")

DEFAULT_REPO_ID = "MWirelabs/ne-ocr"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "ocr" / "models"


def export_ne_ocr(
    output_dir: Path,
    repo_id: str = DEFAULT_REPO_ID,
    quantize: bool = False,
) -> Path:
    """Download weights from Hugging Face, instantiate ViTSTR, and export to ONNX."""
    try:
        import torch
        from doctr.models import vitstr_base
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        logger.error(
            "Missing conversion dependencies. Run via:\n"
            "  uv run --with torch --with python-doctr --with huggingface_hub python tools/export_ne_ocr_onnx.py\n"
            "Error: %s",
            exc,
        )
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / "ne_ocr.onnx"
    vocab_dest = output_dir / "ne_ocr_vocab.json"

    logger.info("Downloading model weights and vocabulary from '%s'...", repo_id)
    model_weight_path = hf_hub_download(repo_id=repo_id, filename="ne_ocr_best.pt")
    vocab_source_path = hf_hub_download(repo_id=repo_id, filename="ne_ocr_vocab.json")

    with open(vocab_source_path, "r", encoding="utf-8") as f:
        vocab_data = json.load(f)
    vocab_list = vocab_data.get("vocab", [])
    vocab_str = "".join(vocab_list[1:])  # Skip '<blank>' index 0

    # Save vocab to output directory
    with open(vocab_dest, "w", encoding="utf-8") as f:
        json.dump(vocab_data, f, ensure_ascii=False, indent=2)
    logger.info("Saved vocabulary to '%s' (size: %d tokens)", vocab_dest, len(vocab_list))

    logger.info("Instantiating DocTR ViTSTR-Base model...")
    model = vitstr_base(pretrained=False, vocab=vocab_str)
    state_dict = torch.load(model_weight_path, map_location="cpu")
    model.load_state_dict(state_dict)
    model.eval()

    class ViTSTRExportWrapper(torch.nn.Module):
        def __init__(self, m: torch.nn.Module) -> None:
            super().__init__()
            self.m = m
            self.m.exportable = True

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.m(x)["logits"]

    logger.info("Exporting model to ONNX: '%s'...", onnx_path)
    dummy_input = torch.randn(1, 3, 32, 128, dtype=torch.float32)

    torch.onnx.export(
        ViTSTRExportWrapper(model),
        dummy_input,
        str(onnx_path),
        dynamo=False,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={
            "input": {0: "batch_size"},
            "output": {0: "batch_size"},
        },
    )

    # Compute checksum
    hasher = hashlib.sha256()
    with open(onnx_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256 = hasher.hexdigest()
    size_bytes = onnx_path.stat().st_size

    logger.info("Successfully exported '%s':", onnx_path.name)
    logger.info("  Size: %d bytes (%.2f MB)", size_bytes, size_bytes / (1024 * 1024))
    logger.info("  SHA256: %s", sha256)

    if quantize:
        try:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            quant_path = output_dir / "ne_ocr_int8.onnx"
            logger.info("Quantizing ONNX model to INT8: '%s'...", quant_path)
            quantize_dynamic(
                model_input=str(onnx_path),
                model_output=str(quant_path),
                weight_type=QuantType.QInt8,
            )
            logger.info(
                "Quantized model saved to '%s' (%.2f MB)", quant_path.name, quant_path.stat().st_size / (1024 * 1024)
            )
        except ImportError:
            logger.warning("onnxruntime not available for dynamic quantization. Skipping.")

    return onnx_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export MWirelabs/ne-ocr to ONNX for Sarathi")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="Hugging Face repo ID")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Destination directory")
    parser.add_argument("--quantize", action="store_true", help="Generate dynamic INT8 quantized model")
    args = parser.parse_args()

    export_ne_ocr(
        output_dir=args.output_dir,
        repo_id=args.repo_id,
        quantize=args.quantize,
    )


if __name__ == "__main__":
    main()
