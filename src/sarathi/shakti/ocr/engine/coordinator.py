"""RapidOCR + OpenVINO engine coordinator for Sarathi.

Coordinates multi-language OCR engine instances, adaptive preprocessing, same-engine
weak-crop retry, and canonical PageData and TableData synthesis.
"""

from __future__ import annotations

import queue
import re
import threading
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from sarathi.sankalpa import (
    CancellationToken,
    ConfidenceValue,
    ExecutionBinding,
    ExecutionProfile,
    PageData,
    ProvenanceRecord,
    TextSpan,
    WarningRecord,
)
from sarathi.shakti.ocr.engine.common import (
    CANONICAL_DATA_ROOT,
    DEV_LANGS,
    EN_LANGS,
    STAGE_NAME,
    V6_LANGS,
)
from sarathi.shakti.ocr.engine.factory import build_rapidocr_instance, resolve_engine_keys
from sarathi.shakti.ocr.engine.layout import reconstruct_layout
from sarathi.shakti.ocr.engine.openvino import resolve_target_device
from sarathi.shakti.ocr.engine.parser import _parse_rapidocr_output
from sarathi.shakti.ocr.engine.preprocessing import (
    apply_clahe,
    is_low_contrast_image,
)
from sarathi.shakti.ocr.engine.readiness import check_ocr_readiness


class RapidOCREngine:
    """Instance-owned RapidOCR + OpenVINO engine adapter."""

    _infer_lock: threading.RLock = threading.RLock()
    _gpu_pools: dict[str, queue.Queue[int]] = {}
    _gpu_engines: dict[str, list[Any]] = {}

    def __init__(
        self,
        data_root: Path | None = None,
        default_lang: str = "devanagari",
    ) -> None:
        self._data_root: Path = data_root.resolve() if data_root is not None else CANONICAL_DATA_ROOT
        self._engine: Any = None
        self._engines: dict[str, Any] = {}
        self._model_labels: dict[str, str] = {}
        self._default_lang: str = default_lang
        self._init_lock: threading.Lock = threading.Lock()
        self._infer_lock: threading.RLock = threading.RLock()
        self._gpu_pools: dict[str, queue.Queue[int]] = {}
        self._gpu_engines: dict[str, list[Any]] = {}
        self._verified_model_paths: dict[str, str] = {}
        self._asset_version: str = self._compute_asset_version()

    def _compute_asset_version(self) -> str:
        import hashlib

        hasher = hashlib.sha256()
        manifest_path = self._data_root / "manifest.json"
        if manifest_path.is_file():
            try:
                st = manifest_path.stat()
                hasher.update(f"manifest:{st.st_size}:{st.st_mtime_ns}".encode("utf-8"))
            except OSError:
                pass
        return hasher.hexdigest()[:16]

    @property
    def asset_version(self) -> str:
        return self._asset_version

    @property
    def default_lang(self) -> str:
        return self._default_lang

    def _get_engine(
        self,
        lang: str = "devanagari",
        execution_binding: ExecutionBinding | None = None,
    ) -> Any:
        """Lazily initialize the underlying RapidOCR engine instance for the requested language."""
        if self._engine is not None:
            return self._engine

        engine_key, _ = resolve_engine_keys(lang, default_lang=self._default_lang)
        target_device = resolve_target_device(execution_binding)
        cache_key = f"{engine_key}:{target_device}"

        if cache_key in self._engines:
            return self._engines[cache_key]

        with self._init_lock:
            if cache_key in self._engines:
                return self._engines[cache_key]

            engine_inst, cache_key, _eng_key, label = build_rapidocr_instance(
                data_root=self._data_root,
                lang=lang,
                target_device=target_device,
                verified_model_paths=self._verified_model_paths,
                default_lang=self._default_lang,
            )

            self._engines[cache_key] = engine_inst
            self._model_labels[cache_key] = label

            if (target_device == "GPU" or "GPU" in target_device) and cache_key not in self._gpu_pools:
                try:
                    engine_inst_1, _, _, _ = build_rapidocr_instance(
                        data_root=self._data_root,
                        lang=lang,
                        target_device=target_device,
                        verified_model_paths=self._verified_model_paths,
                        default_lang=self._default_lang,
                    )
                    q: queue.Queue[int] = queue.Queue()
                    q.put(0)
                    q.put(1)
                    self._gpu_pools[cache_key] = q
                    self._gpu_engines[cache_key] = [engine_inst, engine_inst_1]
                except Exception:
                    pass

            return engine_inst

    @contextmanager
    def _acquire_infer_engine(self, cache_key: str, fallback_engine: Any):
        """Acquire an inference engine slot; uses dual-stream pool on GPU or serialized lock on fallback."""
        gpu_pools = getattr(self, "_gpu_pools", None)
        gpu_engines = getattr(self, "_gpu_engines", None)
        if gpu_pools is not None and gpu_engines is not None and cache_key in gpu_pools:
            slot_idx = gpu_pools[cache_key].get()
            try:
                yield gpu_engines[cache_key][slot_idx]
            finally:
                gpu_pools[cache_key].put(slot_idx)
        else:
            with self._infer_lock:
                yield fallback_engine

    def ocr_page(
        self,
        image: Any,
        page_number: int,
        input_id: str,
        profile: ExecutionProfile = ExecutionProfile.INSTANT,
        custom_options: Mapping[str, Any] | None = None,
        execution_binding: ExecutionBinding | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[PageData, ProvenanceRecord, ConfidenceValue | None, tuple[WarningRecord, ...]]:
        """Run PP-OCR OpenVINO on a single image and return factual PageData, Provenance, and Warnings."""
        if cancellation_token is not None and cancellation_token.is_cancelled:
            cancellation_token.check_cancelled()

        target_device = resolve_target_device(execution_binding)
        lang_opt = custom_options.get("lang") if custom_options else None
        target_lang = str(lang_opt).lower().strip() if lang_opt else self._default_lang
        engine = self._get_engine(target_lang, execution_binding=execution_binding)

        img_arr = np.array(image)
        orig_h = getattr(image, "height", None) or (
            img_arr.shape[0] if hasattr(img_arr, "shape") and len(img_arr.shape) >= 2 else 0
        )
        orig_w = getattr(image, "width", None) or (
            img_arr.shape[1] if hasattr(img_arr, "shape") and len(img_arr.shape) >= 2 else 0
        )

        # Preprocessing resolution per mode
        is_lightweight = bool(custom_options.get("lightweight", False)) if custom_options else False
        preprocess_requested = custom_options.get("preprocess") if custom_options else None
        should_preprocess = (preprocess_requested is not False) and not is_lightweight
        applied_stamp_removal = False

        is_instant = profile == ExecutionProfile.INSTANT and not (
            custom_options and custom_options.get("preserve_layout")
        )

        if should_preprocess:
            import sarathi.shakti.ocr.engine as ocr_engine

            if is_instant:
                deskew = custom_options.get("deskew", True) if custom_options else True
                clahe = custom_options.get("clahe", False) if custom_options else False
            else:
                deskew = custom_options.get("deskew", True) if custom_options else True
                if custom_options and "clahe" in custom_options:
                    clahe = bool(custom_options["clahe"])
                else:
                    clahe = is_low_contrast_image(img_arr)

            remove_stamps = bool(
                custom_options.get("remove_stamps", False) or custom_options.get("inpaint_stamps", False)
            ) if custom_options else False

            if remove_stamps:
                applied_stamp_removal = True

            img_arr = ocr_engine.preprocess_ocr_image(
                img_arr, deskew=deskew, clahe=clahe, remove_stamps=remove_stamps
            )

        is_binarized = False
        if profile == ExecutionProfile.CUSTOM and custom_options and custom_options.get("binarize"):
            from PIL import Image

            is_binarized = True
            gray_pil = Image.fromarray(img_arr).convert("L")
            threshold_img = gray_pil.point(lambda p: 255 if p > 128 else 0)
            img_arr = np.array(threshold_img.convert("RGB"))

        if cancellation_token is not None and cancellation_token.is_cancelled:
            cancellation_token.check_cancelled()

        # Angle classification flag
        if custom_options and "use_angle_cls" in custom_options:
            use_cls_flag = bool(custom_options["use_angle_cls"])
        elif custom_options and "use_cls" in custom_options:
            use_cls_flag = bool(custom_options["use_cls"])
        elif is_instant:
            use_cls_flag = False
        else:
            use_cls_flag = True

        engine_key, _ = resolve_engine_keys(target_lang, default_lang=self._default_lang)
        cache_key = f"{engine_key}:{target_device}"

        with self._acquire_infer_engine(cache_key, fallback_engine=engine) as active_engine:
            try:
                output = active_engine(img_arr, use_det=True, use_cls=use_cls_flag)
            except TypeError:
                try:
                    output = active_engine(img_arr, use_cls=use_cls_flag)
                except TypeError:
                    output = active_engine(img_arr)

        if cancellation_token is not None and cancellation_token.is_cancelled:
            cancellation_token.check_cancelled()

        if target_lang in DEV_LANGS and (custom_options is None or "english_numbers_only" not in custom_options):
            filter_opt = False
        elif (target_lang in V6_LANGS) or (target_lang in EN_LANGS and custom_options and custom_options.get("english_numbers_only")):
            filter_opt = True
        else:
            filter_opt = custom_options.get("english_numbers_only", False) if custom_options else False

        lines, spans, conf_scores, parse_warnings, has_invalid_confidence, has_invalid_geometry = (
            _parse_rapidocr_output(output, filter_opt=filter_opt)
        )
        warnings: list[WarningRecord] = list(parse_warnings)
        if applied_stamp_removal:
            warnings.append(
                WarningRecord(
                    code="EXPERIMENTAL_STAMP_REMOVAL",
                    message="Experimental stamp inpainting applied; visual fidelity altered.",
                    stage=STAGE_NAME,
                )
            )

        # Same-engine weak-crop retry for ACCURATE, LAYOUT_PRESERVING, or CUSTOM
        is_high_accuracy = (
            profile in (ExecutionProfile.ACCURATE, ExecutionProfile.LAYOUT_PRESERVING)
            or bool(custom_options and (custom_options.get("preserve_layout") or custom_options.get("retry_enabled")))
        )
        retry_enabled = (
            (custom_options.get("retry_enabled", True) if custom_options else True)
            if is_high_accuracy
            else bool(custom_options and custom_options.get("retry_enabled", False))
        )
        # Support legacy fallback_enabled custom option
        if custom_options and "fallback_enabled" in custom_options:
            retry_enabled = bool(custom_options["fallback_enabled"])

        retry_threshold = (
            float(custom_options.get("retry_threshold", custom_options.get("fallback_threshold", 0.65)))
            if (custom_options and ("retry_threshold" in custom_options or "fallback_threshold" in custom_options))
            else 0.65
        )

        retry_applied = False
        retry_count = 0
        retry_improved_count = 0
        retry_total_gain = 0.0

        if retry_enabled and spans and profile != ExecutionProfile.INSTANT:
            h_img, w_img = img_arr.shape[:2]
            deva_to_ascii = str.maketrans("०१२३४५६७८९", "0123456789")

            candidates: list[tuple[int, TextSpan, Any]] = []
            for idx, span in enumerate(spans):
                if span.confidence is not None and span.confidence < retry_threshold and span.bounding_box:
                    min_x, min_y, max_x, max_y = span.bounding_box
                    # Zero-copy crop slicing with 3px boundary padding
                    cy0 = max(0, int(min_y) - 3)
                    cy1 = min(h_img, int(max_y) + 3)
                    cx0 = max(0, int(min_x) - 3)
                    cx1 = min(w_img, int(max_x) + 3)

                    if cy1 <= cy0 or cx1 <= cx0:
                        continue

                    retry_count += 1
                    crop = img_arr[cy0:cy1, cx0:cx1]

                    # Adaptive enhancement on crop: contrast boost / CLAHE if low contrast
                    if is_low_contrast_image(crop, std_threshold=45.0):
                        crop = apply_clahe(crop, clip_limit=2.5)

                    candidates.append((idx, span, crop))

            if candidates:
                recognized_results: list[tuple[str, float] | None] = []
                crops_batch = [c for _, _, c in candidates]

                # Native RapidOCR batch recognition fast path
                if hasattr(active_engine, "recognize_txt"):
                    try:
                        batch_out = active_engine.recognize_txt(crops_batch)
                        if (
                            batch_out
                            and getattr(batch_out, "txts", None) is not None
                            and getattr(batch_out, "scores", None) is not None
                            and len(batch_out.txts) == len(candidates)
                            and len(batch_out.scores) == len(candidates)
                        ):
                            b_txts = list(batch_out.txts)
                            b_scores = list(batch_out.scores)
                            for i in range(len(candidates)):
                                t = (
                                    unicodedata.normalize("NFC", str(b_txts[i]).strip())
                                    if b_txts[i] is not None
                                    else ""
                                )
                                s = (
                                    float(b_scores[i])
                                    if b_scores[i] is not None
                                    else 0.0
                                )
                                recognized_results.append((t, s))
                    except Exception:
                        recognized_results.clear()

                # Fallback path: per-crop recognition for test mocks or batch failures
                if not recognized_results:
                    for _, _, crop in candidates:
                        try:
                            retry_out = active_engine(crop, use_det=False, use_cls=False)
                            if (
                                retry_out
                                and getattr(retry_out, "txts", None)
                                and getattr(retry_out, "scores", None)
                            ):
                                r_txts = list(retry_out.txts)
                                r_scores = list(retry_out.scores)
                                if r_txts and r_scores and r_scores[0] is not None:
                                    r_text = unicodedata.normalize("NFC", str(r_txts[0]).strip())
                                    r_conf = float(r_scores[0])
                                    recognized_results.append((r_text, r_conf))
                                else:
                                    recognized_results.append(None)
                            else:
                                recognized_results.append(None)
                        except Exception:
                            recognized_results.append(None)

                # Process results against candidate spans
                for (idx, span, _), res in zip(candidates, recognized_results):
                    if not res:
                        continue
                    r_text, r_conf = res
                    if not r_text:
                        continue

                    # Numeric & token preservation check: digits must not be corrupted
                    orig_digits = re.findall(r"\d+", span.text.translate(deva_to_ascii))
                    if orig_digits:
                        r_digits = re.findall(r"\d+", r_text.translate(deva_to_ascii))
                        if orig_digits != r_digits:
                            continue

                    if r_conf > span.confidence:
                        gain = round(r_conf - span.confidence, 4)
                        spans[idx] = TextSpan(
                            text=r_text,
                            confidence=r_conf,
                            bounding_box=span.bounding_box,
                            language=span.language,
                            script=span.script,
                            metadata={
                                "retry_applied": True,
                                "fallback_applied": True,
                                "fallback_engine": "same_engine_retry",
                                "original_confidence": span.confidence,
                                "replacement_confidence": r_conf,
                                "confidence_gain": gain,
                                "raw_confidence_score_delta": gain,
                            },
                        )
                        if idx < len(lines):
                            lines[idx] = r_text
                        retry_applied = True
                        retry_improved_count += 1
                        retry_total_gain += gain

        # Layout and table reconstruction
        is_layout_mode = (
            profile == ExecutionProfile.LAYOUT_PRESERVING
            or bool(custom_options and custom_options.get("preserve_layout"))
        )
        final_page_text, detected_tables = reconstruct_layout(
            img_arr,
            spans,
            preserve_layout=is_layout_mode,
        )

        if not final_page_text.strip() and not detected_tables:
            warnings.append(
                WarningRecord(
                    code="OCR_EMPTY_PAGE",
                    message="No text detected on page.",
                    stage=STAGE_NAME,
                )
            )

        # Emit actionable human review items for text spans remaining below review threshold (< 0.80)
        review_threshold = (
            float(custom_options.get("review_threshold", 0.80))
            if custom_options and "review_threshold" in custom_options
            else 0.80
        )
        if spans:
            for s_idx, span in enumerate(spans, start=1):
                if span.confidence is not None and span.confidence < review_threshold and span.text.strip():
                    warnings.append(
                        WarningRecord(
                            code="OCR_LOW_CONFIDENCE",
                            message=f"Low confidence text span ({span.confidence:.1%}): '{span.text}'",
                            stage=STAGE_NAME,
                            context={
                                "source": span.text,
                                "source_text": span.text,
                                "output": span.text,
                                "output_text": span.text,
                                "confidence": span.confidence,
                                "span_id": span.metadata.get("span_id", f"span-p{page_number}-{s_idx}"),
                                "attempt_id": span.metadata.get("attempt_id", f"span-p{page_number}-{s_idx}"),
                                "page_number": page_number,
                                "is_review_item": True,
                            },
                        )
                    )

        cache_key = f"{target_lang}:{target_device}"
        if target_lang in DEV_LANGS:
            model_label = "PP-OCRv5-Devanagari"
        else:
            model_label = self._model_labels.get(cache_key) or self._model_labels.get(f"v6_en:{target_device}") or "PP-OCRv6"

        page_confidence: ConfidenceValue | None = None
        final_confs = [s.confidence for s in spans if s.confidence is not None]
        if final_confs and not has_invalid_confidence and len(final_confs) == len(spans):
            avg_score = sum(final_confs) / len(final_confs)
            page_confidence = ConfidenceValue(
                score=round(float(avg_score), 4),
                method="rapidocr_mean",
                evidence={
                    "engine": "rapidocr",
                    "backend": "openvino",
                    "device": target_device,
                    "model": model_label,
                    "box_count": len(final_confs),
                },
            )

        val_enabled = custom_options.get("validation_enabled", True) if custom_options else True
        validation_outcome: str
        if not val_enabled:
            validation_outcome = "skipped"
        elif not final_page_text.strip():
            validation_outcome = "empty"
        elif has_invalid_confidence:
            validation_outcome = "invalid_confidence"
        elif has_invalid_geometry:
            validation_outcome = "invalid_geometry"
        elif retry_applied:
            validation_outcome = "retry_improved"
        else:
            validation_outcome = "usable"

        scope = "full_devanagari" if target_lang in DEV_LANGS else ("english_and_numbers" if filter_opt else "english")

        metadata: dict[str, Any] = {
            "profile": profile.value,
            "page_height": float(orig_h),
            "page_width": float(orig_w),
            "validation_outcome": validation_outcome,
            "model": model_label,
            "scope": scope,
            "retry_applied": retry_applied,
            "retry_count": retry_count,
            "retry_improved_count": retry_improved_count,
            "retry_total_gain": round(retry_total_gain, 4),
            "fallback_applied": retry_applied,
            "fallback_engine": "same_engine_retry" if retry_applied else "none",
            "fallback_improved_count": retry_improved_count,
            "fallback_total_gain": round(retry_total_gain, 4),
        }
        if page_confidence is not None:
            metadata["confidence"] = page_confidence.score

        evidence_dict: dict[str, Any] = {
            "score_kind": "raw_engine",
            "calibrated": False,
            "engine": "rapidocr",
            "backend": "openvino",
            "device": target_device,
            "model": model_label,
            "scope": scope,
            "profile": profile.value,
            "use_angle_cls": use_cls_flag,
            "box_count": len(spans),
            "validation_outcome": validation_outcome,
        }
        if is_binarized:
            evidence_dict["binarized"] = True
        if retry_applied:
            evidence_dict["retry_applied"] = True
            evidence_dict["retry_count"] = retry_count
            evidence_dict["retry_improved_count"] = retry_improved_count
            evidence_dict["retry_total_gain"] = round(retry_total_gain, 4)
            evidence_dict["fallback_applied"] = True
            evidence_dict["fallback_improved_count"] = retry_improved_count
            evidence_dict["fallback_total_gain"] = round(retry_total_gain, 4)

        provenance = ProvenanceRecord(
            source_input_id=input_id,
            stage=STAGE_NAME,
            plugin_id="shakti.ocr",
            capability_id="ocr",
            page_number=page_number,
            evidence=evidence_dict,
        )

        page_data = PageData(
            page_number=page_number,
            text=final_page_text,
            spans=tuple(spans),
            tables=detected_tables,
            metadata=metadata,
        )

        return page_data, provenance, page_confidence, tuple(warnings)


__all__ = [
    "RapidOCREngine",
    "_parse_rapidocr_output",
    "check_ocr_readiness",
]
