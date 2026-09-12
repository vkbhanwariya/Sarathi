"""RapidOCR + PP-OCRv5/v6 + OpenVINO engine coordinator for Sarathi.

Coordinates multi-language OCR engine instances, preprocessing, inference execution,
targeted Tesseract fallback, and canonical PageData synthesis.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Mapping

from sarathi.dosh import DoshError
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
    STAGE_NAME,
    V6_LANGS,
)
from sarathi.shakti.ocr.engine.factory import build_rapidocr_instance
from sarathi.shakti.ocr.engine.openvino import resolve_target_device
from sarathi.shakti.ocr.engine.parser import _parse_rapidocr_output
from sarathi.shakti.ocr.engine.preprocessing import is_low_contrast_image
from sarathi.shakti.ocr.engine.readiness import check_ocr_readiness
from sarathi.shakti.ocr.engine.tesseract import TesseractFallbackAdapter


class RapidOCREngine:
    """Instance-owned RapidOCR + PP-OCRv5/v6 + OpenVINO engine adapter."""

    def __init__(
        self,
        data_root: Path | None = None,
        tesseract_adapter: TesseractFallbackAdapter | None = None,
        default_lang: str = "en",
    ) -> None:
        self._data_root: Path = data_root.resolve() if data_root is not None else CANONICAL_DATA_ROOT
        self._engine: Any = None
        self._engines: dict[str, Any] = {}
        self._model_labels: dict[str, str] = {}
        self._default_lang: str = default_lang
        self._tesseract: TesseractFallbackAdapter = tesseract_adapter or TesseractFallbackAdapter()
        self._init_lock: threading.Lock = threading.Lock()
        self._local: threading.local = threading.local()
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

    @property
    def tesseract(self) -> TesseractFallbackAdapter:
        return self._tesseract

    def _get_engine(self, lang: str = "en", execution_binding: ExecutionBinding | None = None) -> Any:
        """Lazily initialize the underlying RapidOCR engine instance for the requested language after verifying assets against manifest.json."""
        if self._engine is not None:
            return self._engine

        if not hasattr(self._local, "engines"):
            self._local.engines = {}

        clean_lang = str(lang).lower().strip() if lang else self._default_lang
        if clean_lang in V6_LANGS:
            engine_key = "v6_en"
        elif clean_lang in DEV_LANGS:
            engine_key = "devanagari"
        else:
            engine_key = "en"

        target_device = resolve_target_device(execution_binding)
        cache_key = f"{engine_key}:{target_device}"

        if cache_key in self._local.engines:
            return self._local.engines[cache_key]

        if cache_key in self._engines:
            cand = self._engines[cache_key]
            try:
                from rapidocr import RapidOCR

                if not isinstance(cand, RapidOCR):
                    return cand
            except ImportError:
                return cand
            if getattr(cand, "_owner_thread", None) == threading.get_ident():
                return cand

        with self._init_lock:
            if cache_key in self._local.engines:
                return self._local.engines[cache_key]
            return self._get_engine_unlocked(lang=lang, execution_binding=execution_binding)

    def _get_engine_unlocked(self, lang: str = "en", execution_binding: ExecutionBinding | None = None) -> Any:
        target_device = resolve_target_device(execution_binding)
        clean_lang = str(lang).lower().strip() if lang else self._default_lang
        if clean_lang in V6_LANGS:
            engine_key = "v6_en"
        elif clean_lang in DEV_LANGS:
            engine_key = "devanagari"
        else:
            engine_key = "en"

        cache_key = f"{engine_key}:{target_device}"
        if hasattr(self._local, "engines") and cache_key in self._local.engines:
            return self._local.engines[cache_key]
        if cache_key in self._engines:
            cand = self._engines[cache_key]
            try:
                from rapidocr import RapidOCR

                if not isinstance(cand, RapidOCR):
                    return cand
            except ImportError:
                return cand
            if getattr(cand, "_owner_thread", None) == threading.get_ident():
                return cand

        engine_inst, cache_key, eng_key, label = build_rapidocr_instance(
            data_root=self._data_root,
            lang=lang,
            target_device=target_device,
            verified_model_paths=self._verified_model_paths,
            default_lang=self._default_lang,
        )

        if not hasattr(self._local, "engines"):
            self._local.engines = {}
        self._local.engines[cache_key] = engine_inst
        self._engines[cache_key] = engine_inst
        self._engines[eng_key] = engine_inst
        self._model_labels[cache_key] = label
        self._model_labels[eng_key] = label
        return engine_inst

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

        import numpy as np

        target_device = resolve_target_device(execution_binding)
        lang_opt = custom_options.get("lang") if custom_options else None
        target_lang = str(lang_opt).lower().strip() if lang_opt else self._default_lang
        engine = self._get_engine(target_lang, execution_binding=execution_binding)
        img_arr = np.array(image)

        # Resolve preprocessing flags per execution profile and options
        is_lightweight = custom_options.get("lightweight", False) if custom_options else False
        preprocess_requested = custom_options.get("preprocess") if custom_options else None
        should_preprocess = (preprocess_requested is not False) and not is_lightweight
        applied_stamp_removal = False

        if should_preprocess:
            if profile == ExecutionProfile.INSTANT:
                # Minimum beneficial preprocessing per OCR Veda: deskew only when beneficial, no destructive filters
                deskew = custom_options.get("deskew", True) if custom_options else True
                clahe = custom_options.get("clahe", False) if custom_options else False
            else:
                # Accurate / Custom: adaptive preprocessing where evidence supports it
                deskew = custom_options.get("deskew", True) if custom_options else True
                if custom_options and "clahe" in custom_options:
                    clahe = bool(custom_options["clahe"])
                else:
                    clahe = is_low_contrast_image(img_arr)

            # Stamp removal is destructive and strictly opt-in per Veda safety rules
            remove_stamps = bool(
                custom_options.get("remove_stamps", False) or custom_options.get("inpaint_stamps", False)
            ) if custom_options else False

            if remove_stamps:
                applied_stamp_removal = True

            import sarathi.shakti.ocr.engine as ocr_engine

            img_arr = ocr_engine.preprocess_ocr_image(img_arr, deskew=deskew, clahe=clahe, remove_stamps=remove_stamps)

        # Keep a PIL image only when a later operation actually needs one.
        # Instant OCR never uses fallback crops, so eagerly rebuilding PIL from the
        # NumPy inference array is pure per-page allocation/copy overhead.
        processed_img: Any | None = None
        is_binarized = False
        if profile == ExecutionProfile.CUSTOM and custom_options and custom_options.get("binarize"):
            from PIL import Image

            is_binarized = True
            if isinstance(img_arr, np.ndarray):
                gray_pil = Image.fromarray(img_arr).convert("L")
            elif hasattr(image, "convert"):
                gray_pil = image.convert("L")
            else:
                gray_pil = Image.fromarray(np.array(image)).convert("L")
            threshold_img = gray_pil.point(lambda p: 255 if p > 128 else 0)
            processed_img = threshold_img
            img_arr = np.array(threshold_img.convert("RGB"))

        if cancellation_token is not None and cancellation_token.is_cancelled:
            cancellation_token.check_cancelled()

        output = engine(img_arr)

        if cancellation_token is not None and cancellation_token.is_cancelled:
            cancellation_token.check_cancelled()

        if target_lang in DEV_LANGS and (custom_options is None or "english_numbers_only" not in custom_options):
            filter_opt = False
        elif target_lang in V6_LANGS:
            filter_opt = custom_options.get("english_numbers_only", True) if custom_options else True
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
                    stage="ocr",
                )
            )

        # Advanced profile processing
        fallback_applied = False
        fallback_required = False
        fallback_unavailable = False
        fallback_failed = False
        fallback_intercepted_count = 0
        fallback_improved_count = 0
        fallback_total_gain = 0.0

        # Accurate mode or Custom with fallback_enabled: targeted Tesseract fallback only for weak spans (< 0.65)
        fallback_enabled = (
            (custom_options.get("fallback_enabled", True) if custom_options else True)
            if profile == ExecutionProfile.ACCURATE
            else (bool(custom_options.get("fallback_enabled", False)) if custom_options else False)
        )
        if (profile in (ExecutionProfile.ACCURATE, ExecutionProfile.CUSTOM)) and fallback_enabled and spans:
            tess_lang = "hin" if target_lang in DEV_LANGS else "eng"
            for idx, span in enumerate(spans):
                if span.confidence is not None and span.confidence < 0.65 and span.bounding_box:
                    fallback_required = True
                    fallback_intercepted_count += 1
                    if not self._tesseract.is_available():
                        fallback_unavailable = True
                        warnings.append(
                            WarningRecord(
                                code="OCR_FALLBACK_UNAVAILABLE",
                                message="Tesseract 5 fallback engine is not available on this host.",
                                stage=STAGE_NAME,
                            )
                        )
                        break

                    if processed_img is None:
                        if not should_preprocess and hasattr(image, "crop"):
                            processed_img = image
                        else:
                            from PIL import Image

                            processed_img = Image.fromarray(img_arr) if isinstance(img_arr, np.ndarray) else image

                    min_x, min_y, max_x, max_y = span.bounding_box
                    w, h = processed_img.size if hasattr(processed_img, "size") else (int(max_x), int(max_y))
                    box_crop = (
                        max(0, int(min_x) - 2),
                        max(0, int(min_y) - 2),
                        min(w, int(max_x) + 2),
                        min(h, int(max_y) + 2),
                    )

                    if box_crop[2] > box_crop[0] and box_crop[3] > box_crop[1] and hasattr(processed_img, "crop"):
                        cropped = processed_img.crop(box_crop)
                        try:
                            tess_res = self._tesseract.recognize_crop(cropped, language=tess_lang)
                            if tess_res is not None:
                                tess_text, tess_conf = tess_res
                                if tess_conf is None:
                                    warnings.append(
                                        WarningRecord(
                                            code="OCR_FALLBACK_CONFIDENCE_UNAVAILABLE",
                                            message="Tesseract fallback confidence score is unavailable.",
                                            stage=STAGE_NAME,
                                        )
                                    )
                                if tess_conf is not None and tess_conf > span.confidence:
                                    gain = round(tess_conf - span.confidence, 4)
                                    spans[idx] = TextSpan(
                                        text=tess_text,
                                        confidence=tess_conf,
                                        bounding_box=span.bounding_box,
                                        language=span.language,
                                        script=span.script,
                                        metadata={
                                            "fallback_applied": True,
                                            "fallback_engine": "tesseract5",
                                            "original_confidence": span.confidence,
                                            "replacement_confidence": tess_conf,
                                            "raw_confidence_score_delta": gain,
                                            "confidence_gain": gain,
                                        },
                                    )
                                    if idx < len(lines):
                                        lines[idx] = tess_text
                                    fallback_applied = True
                                    fallback_improved_count += 1
                                    fallback_total_gain += gain
                        except DoshError:
                            fallback_failed = True
                            warnings.append(
                                WarningRecord(
                                    code="OCR_FALLBACK_FAILED",
                                    message="Tesseract 5 fallback execution failed.",
                                    stage=STAGE_NAME,
                                )
                            )

        final_page_text = "\n".join(lines)
        if not final_page_text.strip():
            warnings.append(
                WarningRecord(
                    code="OCR_EMPTY_PAGE",
                    message="No text detected on page.",
                    stage=STAGE_NAME,
                )
            )

        cache_key = f"{target_lang}:{target_device}"
        if target_lang in DEV_LANGS:
            model_label = "PP-OCRv5-Devanagari"
        elif target_lang in V6_LANGS:
            model_label = "PP-OCRv6"
        else:
            model_label = self._model_labels.get(cache_key) or self._model_labels.get(f"en:{target_device}") or "unknown"

        page_confidence: ConfidenceValue | None = None
        if conf_scores and not has_invalid_confidence and len(conf_scores) == len(spans):
            avg_score = sum(conf_scores) / len(conf_scores)
            page_confidence = ConfidenceValue(
                score=round(float(avg_score), 4),
                method="rapidocr_mean",
                evidence={
                    "engine": "rapidocr",
                    "backend": "openvino",
                    "device": target_device,
                    "model": model_label,
                    "box_count": len(conf_scores),
                },
            )

        if fallback_applied:
            # If Tesseract text replaces a RapidOCR span, do not retain page/run confidence labelled rapidocr_mean
            page_confidence = None

        # Determine deterministic validation outcome
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
        elif fallback_applied:
            validation_outcome = "fallback_improved"
        elif fallback_failed:
            validation_outcome = "fallback_failed"
        elif fallback_unavailable:
            validation_outcome = "fallback_unavailable"
        elif fallback_required:
            validation_outcome = "weak_confidence"
        else:
            validation_outcome = "usable"

        if target_lang in DEV_LANGS:
            scope = "full_devanagari"
        elif filter_opt:
            scope = "english_and_numbers"
        else:
            scope = "multilingual"

        metadata: dict[str, Any] = {
            "profile": profile.value,
            "validation_outcome": validation_outcome,
            "model": model_label,
            "scope": scope,
            "fallback_intercepted_count": fallback_intercepted_count,
            "fallback_improved_count": fallback_improved_count,
            "fallback_applied": fallback_applied,
            "fallback_total_gain": round(fallback_total_gain, 4),
            "raw_confidence_score_delta": round(fallback_total_gain, 4),
        }
        if fallback_applied or fallback_required:
            metadata["fallback_engine"] = "tesseract5"
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
            "box_count": len(spans),
            "validation_outcome": validation_outcome,
        }
        if is_binarized:
            evidence_dict["binarized"] = True
        if fallback_applied:
            evidence_dict["fallback_engine"] = "tesseract5"
            evidence_dict["fallback_applied"] = True
            evidence_dict["fallback_improved_count"] = fallback_improved_count
            evidence_dict["fallback_intercepted_count"] = fallback_intercepted_count
            evidence_dict["fallback_total_gain"] = round(fallback_total_gain, 4)
            evidence_dict["raw_confidence_score_delta"] = round(fallback_total_gain, 4)
        elif fallback_required:
            evidence_dict["fallback_engine"] = "tesseract5"
            evidence_dict["fallback_intercepted_count"] = fallback_intercepted_count
            evidence_dict["fallback_status"] = (
                "unavailable" if fallback_unavailable else ("failed" if fallback_failed else "unimproved")
            )

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
            tables=(),
            metadata=metadata,
        )

        return page_data, provenance, page_confidence, tuple(warnings)


__all__ = [
    "RapidOCREngine",
    "_parse_rapidocr_output",
    "check_ocr_readiness",
]
