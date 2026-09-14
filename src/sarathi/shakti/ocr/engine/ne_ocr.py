"""NE-OCR (86M ViTSTR) Devanagari fallback adapter using ONNX / OpenVINO runtime.

Provides high-accuracy (~97.7% ChA) selective fallback for low-confidence Devanagari
text spans in Sarathi's ACCURATE OCR profile, without requiring PyTorch in production.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import unicodedata
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from sarathi.dosh import DoshError, FailureCode

logger = logging.getLogger(__name__)

CANONICAL_DATA_ROOT = Path(__file__).resolve().parents[5] / "data" / "ocr"
INPUT_WIDTH = 128
INPUT_HEIGHT = 32
MAX_SEQ_LENGTH = 32


class NEOCRFallbackAdapter:
    """Selective Devanagari OCR fallback adapter powered by NE-OCR via ONNX or OpenVINO."""

    def __init__(
        self,
        model_path: Path | str | None = None,
        vocab_path: Path | str | None = None,
        data_root: Path | str | None = None,
        device: str = "CPU",
    ) -> None:
        self._data_root = Path(data_root).resolve() if data_root is not None else CANONICAL_DATA_ROOT
        self._model_path: Path | None = self._resolve_model_path(model_path)
        self._vocab_path: Path | None = self._resolve_vocab_path(vocab_path)
        self._device = device
        self._session: Any = None
        self._backend: str | None = None
        self._vocab: list[str] | None = None
        self._init_lock = threading.Lock()
        self._local = threading.local()

    def _resolve_model_path(self, override: Path | str | None) -> Path | None:
        if override is not None:
            p = Path(override).resolve()
            return p if p.is_file() else None

        candidates = [
            self._data_root / "models" / "ne_ocr.onnx",
            self._data_root / "ne_ocr.onnx",
            self._data_root / "models" / "ne_ocr.xml",
        ]
        for c in candidates:
            if c.is_file():
                return c.resolve()
        return None

    def _resolve_vocab_path(self, override: Path | str | None) -> Path | None:
        if override is not None:
            p = Path(override).resolve()
            return p if p.is_file() else None

        candidates = [
            self._data_root / "models" / "ne_ocr_vocab.json",
            self._data_root / "ne_ocr_vocab.json",
        ]
        for c in candidates:
            if c.is_file():
                return c.resolve()
        return None

    @property
    def model_path(self) -> Path | None:
        return self._model_path

    @property
    def vocab_path(self) -> Path | None:
        return self._vocab_path

    def is_available(self) -> bool:
        """Return True only when model weights and vocab JSON are present and runtime is importable."""
        if self._model_path is None or not self._model_path.is_file():
            return False
        if self._vocab_path is None or not self._vocab_path.is_file():
            return False

        # Verify that either OpenVINO or ONNXRuntime is available
        try:
            try:
                from openvino import Core  # noqa: F401
            except ImportError:
                import openvino.runtime  # noqa: F401

            return True
        except ImportError:
            pass

        try:
            import onnxruntime  # noqa: F401

            return True
        except ImportError:
            return False

    def _load_vocab(self) -> list[str]:
        if self._vocab is not None:
            return self._vocab

        if self._vocab_path is None or not self._vocab_path.is_file():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="NE-OCR vocabulary file is missing.",
            )

        try:
            with open(self._vocab_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            vocab_list = data.get("vocab", [])
            if not vocab_list:
                raise ValueError("Vocabulary list is empty.")
            if vocab_list[0] == "<blank>" and "<eos>" not in vocab_list:
                # MWirelabs/ne-ocr (DocTR ViTSTR) output vocabulary:
                # Output classes correspond to vocab[1:], with <eos> at the end
                self._vocab = list(vocab_list[1:]) + ["<eos>"]
            else:
                self._vocab = vocab_list
            return self._vocab
        except Exception as e:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message=f"Failed to load NE-OCR vocabulary: {e}",
            ) from e

    def _init_session(self) -> tuple[Any, str]:
        if self._session is not None and self._backend is not None:
            return self._session, self._backend

        with self._init_lock:
            if self._session is not None and self._backend is not None:
                return self._session, self._backend

            if not self.is_available() or self._model_path is None:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="NE-OCR engine is not available on this host.",
                )

            # Try OpenVINO first
            try:
                try:
                    from openvino import Core
                except ImportError:
                    from openvino.runtime import Core

                core = Core()
                model = core.read_model(str(self._model_path))
                compiled_model = core.compile_model(model, self._device)
                self._session = compiled_model
                self._backend = "openvino"
                logger.debug("NE-OCR compiled successfully with OpenVINO (%s).", self._device)
                return self._session, self._backend
            except Exception as ov_err:
                logger.debug("OpenVINO unavailable for NE-OCR, attempting ONNXRuntime: %s", ov_err)

            # Fall back to ONNXRuntime
            try:
                import onnxruntime as ort

                sess_opts = ort.SessionOptions()
                sess_opts.inter_op_num_threads = 1
                sess_opts.intra_op_num_threads = min(4, max(1, os.cpu_count() or 1))
                session = ort.InferenceSession(str(self._model_path), sess_options=sess_opts)
                self._session = session
                self._backend = "onnxruntime"
                logger.debug("NE-OCR initialized successfully with ONNXRuntime.")
                return self._session, self._backend
            except Exception as ort_err:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Failed to initialize NE-OCR session with OpenVINO or ONNXRuntime: {ort_err}",
                ) from ort_err

    def preprocess_crop(self, crop_image: Any) -> np.ndarray:
        """Preprocess a single image crop to (1, 3, 32, 128) float32 array normalized to [0, 1]."""
        from PIL import Image

        if isinstance(crop_image, np.ndarray):
            pil_img = Image.fromarray(crop_image)
        elif hasattr(crop_image, "convert"):
            pil_img = crop_image
        else:
            raise DoshError(
                code=FailureCode.INVALID_INPUT,
                message="Unsupported image format for NE-OCR crop.",
            )

        rgb_img = pil_img.convert("RGB")
        resized_img = rgb_img.resize((INPUT_WIDTH, INPUT_HEIGHT), Image.Resampling.BILINEAR)
        arr = np.asarray(resized_img, dtype=np.float32) / 255.0
        # Transpose from (H, W, C) to (C, H, W) and expand batch dimension
        tensor = np.transpose(arr, (2, 0, 1))
        return np.expand_dims(tensor, axis=0)

    def decode_predictions(self, logits: np.ndarray, vocab: Sequence[str]) -> tuple[str, float | None]:
        """Decode logits tensor of shape (1, seq_len, vocab_size) to recognized text and confidence."""
        if logits.ndim == 3:
            step_logits = logits[0]
        elif logits.ndim == 2:
            step_logits = logits
        else:
            return "", None

        # Compute softmax along vocab dimension
        exp_logits = np.exp(step_logits - np.max(step_logits, axis=-1, keepdims=True))
        probs = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)

        pred_ids = np.argmax(probs, axis=-1)
        pred_confs = np.max(probs, axis=-1)

        chars: list[str] = []
        confs: list[float] = []

        for idx, p_id in enumerate(pred_ids):
            if p_id >= len(vocab):
                break
            char = vocab[p_id]
            if char in ("<eos>", "<pad>", "</s>", "<s>"):
                break
            if char == "<blank>":
                continue
            chars.append(char)
            confs.append(float(pred_confs[idx]))

        if not chars:
            return "", None

        text = unicodedata.normalize("NFC", "".join(chars).strip())
        avg_conf = sum(confs) / len(confs) if confs else None
        return text, avg_conf

    def recognize_crop(self, crop_image: Any) -> tuple[str, float | None] | None:
        """Run NE-OCR on a cropped sub-image and return (text, confidence) or None if empty."""
        if not self.is_available():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="NE-OCR fallback engine is not available at configured model path.",
            )

        session, backend = self._init_session()
        vocab = self._load_vocab()
        input_tensor = self.preprocess_crop(crop_image)

        try:
            if backend == "openvino":
                # OpenVINO compiled model call using thread-local InferRequest for safe concurrency
                infer_req = getattr(self._local, "infer_req", None)
                if infer_req is None:
                    infer_req = session.create_infer_request()
                    self._local.infer_req = infer_req
                output_layer = session.output(0)
                res = infer_req.infer([input_tensor])[output_layer]
            else:
                # ONNXRuntime inference
                input_name = session.get_inputs()[0].name
                res = session.run(None, {input_name: input_tensor})[0]

            text, conf = self.decode_predictions(res, vocab)
            if not text:
                return None

            # Validate confidence bounds
            if conf is not None:
                if math.isnan(conf) or math.isinf(conf):
                    conf = None
                else:
                    conf = max(0.0, min(1.0, round(conf, 4)))

            return text, conf
        except Exception as e:
            logger.warning("NE-OCR execution failed on crop: %s", e)
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message=f"NE-OCR fallback execution failed: {e}",
            ) from e
