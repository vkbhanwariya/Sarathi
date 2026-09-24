"""RapidOCR + OpenVINO engine coordinator for Sarathi.

Coordinates multi-language OCR engine instances, adaptive preprocessing, same-engine
weak-crop retry, and canonical PageData and TableData synthesis.
"""

from __future__ import annotations

import math
import queue
import threading
import unicodedata
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from sarathi.sankalpa import (
    CancellationToken,
    ConfidenceValue,
    ExecutionBinding,
    ExecutionProfile,
    PageData,
    ProvenanceRecord,
    TableData,
    TextSpan,
    WarningRecord,
)
from sarathi.sankalpa.cancellation import check_cancelled
from sarathi.shakti.ocr.engine.common import (
    CANONICAL_DATA_ROOT,
    DEV_LANGS,
    EN_LANGS,
    STAGE_NAME,
    V6_LANGS,
)
from sarathi.shakti.ocr.engine.critical import (
    DEFAULT_CRITICAL_RETRY_THRESHOLD,
    DEFAULT_CRITICAL_REVIEW_THRESHOLD,
    CriticalityType,
    classify_label_anchor,
    classify_span,
    repair_critical_token,
    validate_critical_token,
)
from sarathi.shakti.ocr.engine.factory import build_rapidocr_instance, resolve_engine_keys
from sarathi.shakti.ocr.engine.layout import reconstruct_layout
from sarathi.shakti.ocr.engine.openvino import resolve_target_device
from sarathi.shakti.ocr.engine.parser import _parse_rapidocr_output, filter_english_and_numbers
from sarathi.shakti.ocr.engine.preprocessing import (
    RotationCandidate,
    choose_page_rotation,
    is_low_contrast_image,
)
from sarathi.shakti.ocr.engine.readiness import check_ocr_readiness
from sarathi.shakti.text.typography import (
    contains_devanagari,
    normalize_devanagari_numerals,
    synthesize_akshara_unicode,
)


def _preprocess_page_image(
    img_arr: np.ndarray,
    profile: ExecutionProfile,
    custom_options: Mapping[str, Any] | None,
) -> tuple[np.ndarray, tuple[Any, ...], bool, float, Any, str]:
    """Execute adaptive deskew, CLAHE, and stamp detection/removal."""
    is_lightweight = bool(custom_options.get("lightweight", False)) if custom_options else False
    preprocess_requested = custom_options.get("preprocess") if custom_options else None
    should_preprocess = (preprocess_requested is not False) and not is_lightweight

    is_instant = profile == ExecutionProfile.INSTANT and not (custom_options and custom_options.get("preserve_layout"))

    raw_stamp_mode = custom_options.get("stamp_mode") if custom_options else None
    if raw_stamp_mode is not None:
        stamp_mode = str(raw_stamp_mode).lower().strip()
    elif custom_options and (custom_options.get("remove_stamps") or custom_options.get("inpaint_stamps")):
        stamp_mode = "remove"
    else:
        stamp_mode = "off"

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

        stamps_detected_regions: tuple[Any, ...] = ()
        stamp_removal_applied = False
        stamp_removed_ratio = 0.0
        stamp_filled_arr: Any = None

        if stamp_mode in ("tag", "remove", "auto"):
            from sarathi.shakti.ocr.engine.preprocessing import detect_stamps, remove_stamps_using_detection

            detection = detect_stamps(img_arr)
            stamps_detected_regions = detection.regions
            if stamp_mode == "remove" and detection.removed_ratio > 0.0:
                stamp_filled_arr = remove_stamps_using_detection(img_arr, detection)
                img_arr = stamp_filled_arr
                stamp_removal_applied = True
                stamp_removed_ratio = detection.removed_ratio

        img_arr = ocr_engine.preprocess_ocr_image(img_arr, deskew=deskew, clahe=clahe, remove_stamps=False)
    else:
        stamps_detected_regions = ()
        stamp_removal_applied = False
        stamp_removed_ratio = 0.0
        stamp_filled_arr = None

    return (
        img_arr,
        stamps_detected_regions,
        stamp_removal_applied,
        stamp_removed_ratio,
        stamp_filled_arr,
        stamp_mode,
    )


def _evaluate_page_orientation(
    img_arr: np.ndarray,
    output: Any,
    lines: list[Any],
    spans: list[TextSpan],
    conf_scores: list[float],
    parse_warnings: tuple[WarningRecord, ...],
    custom_options: Mapping[str, Any] | None,
    active_engine: Any,
    use_cls_flag: bool,
    filter_opt: bool,
    normalize_digits: bool = True,
    cancellation_token: CancellationToken | None = None,
) -> tuple[np.ndarray, Any, list[Any], list[TextSpan], list[float], tuple[WarningRecord, ...], int]:
    """Detect inverted or rotated page orientation, test candidate rotations, and adopt best orientation."""
    mean_conf = float(np.mean(conf_scores)) if conf_scores else 0.0
    ratios: list[float] = []
    for s in spans:
        if s.bounding_box:
            w_box = max(1e-6, float(s.bounding_box[2] - s.bounding_box[0]))
            h_box = max(1e-6, float(s.bounding_box[3] - s.bounding_box[1]))
            ratios.append(h_box / w_box)
    median_ratio = float(np.median(ratios)) if ratios else 0.0

    rotation_applied = 0
    orientation_enabled = bool(custom_options.get("orientation_detection", True)) if custom_options else True
    conf_thresh = float(custom_options.get("orientation_confidence_threshold", 0.6)) if custom_options else 0.6

    if orientation_enabled and (mean_conf < conf_thresh or median_ratio > 1.5):
        candidate_angles = [90, 270] if median_ratio > 1.5 else [180]
        candidates = [
            RotationCandidate(
                rotation=0,
                mean_confidence=mean_conf,
                char_count=sum(len(s.text) for s in spans),
                output=output,
                spans=tuple(spans),
                lines=tuple(lines),
                conf_scores=tuple(conf_scores),
                warnings=tuple(parse_warnings),
            )
        ]

        rot_cv_map = {}
        try:
            import cv2

            rot_cv_map = {
                90: cv2.ROTATE_90_CLOCKWISE,
                180: cv2.ROTATE_180,
                270: cv2.ROTATE_90_COUNTERCLOCKWISE,
            }
        except ImportError:
            cv2 = None

        for deg in candidate_angles:
            check_cancelled(cancellation_token)

            if cv2 is not None and deg in rot_cv_map:
                rotated_arr = cv2.rotate(img_arr, rot_cv_map[deg])
            else:
                k = deg // 90
                rotated_arr = np.ascontiguousarray(np.rot90(img_arr, -k))

            rot_output = active_engine(rotated_arr, use_det=True, use_cls=use_cls_flag)
            r_lines, r_spans, r_confs, r_warns, _, _ = _parse_rapidocr_output(
                rot_output, filter_opt=filter_opt, normalize_digits=normalize_digits
            )
            r_mean = float(np.mean(r_confs)) if r_confs else 0.0
            r_chars = sum(len(s.text) for s in r_spans)
            candidates.append(
                RotationCandidate(
                    rotation=deg,
                    mean_confidence=r_mean,
                    char_count=r_chars,
                    output=rot_output,
                    spans=tuple(r_spans),
                    lines=tuple(r_lines),
                    conf_scores=tuple(r_confs),
                    warnings=tuple(r_warns),
                )
            )

        best_deg = choose_page_rotation(candidates)
        if best_deg != 0:
            best_cand = next(c for c in candidates if c.rotation == best_deg)
            rotation_applied = best_deg
            spans = list(best_cand.spans)
            lines = list(best_cand.lines)
            conf_scores = list(best_cand.conf_scores)
            parse_warnings = best_cand.warnings
            output = best_cand.output
            if cv2 is not None and best_deg in rot_cv_map:
                img_arr = cv2.rotate(img_arr, rot_cv_map[best_deg])
            else:
                k = best_deg // 90
                img_arr = np.ascontiguousarray(np.rot90(img_arr, -k))

    return img_arr, output, lines, spans, conf_scores, parse_warnings, rotation_applied


def _recover_critical_spans(
    img_arr: Any,
    spans: list[TextSpan],
    active_engine: Any,
    custom_options: Mapping[str, Any] | None,
    stamps_detected_regions: Sequence[tuple[float, float, float, float]] = (),
    filter_opt: bool = False,
    normalize_digits: bool = True,
    max_crops: int = 3,
) -> list[TextSpan]:
    """Perform bounded recognition recovery on low-confidence critical entities.

    Invariants:
      - Only spans classified as critical (currency, statutory IDs, dates, accounts) are eligible.
      - Never re-runs full-page detection or re-crops general prose.
      - Hard upper bound on retries (max_crops, default 3, capped at 5).
      - Applies localized CLAHE enhancement when occluded by stamps or faint ink.
    """
    if not spans or not isinstance(img_arr, np.ndarray) or img_arr.size == 0:
        return spans

    crit_retry_thresh = (
        float(custom_options.get("critical_retry_threshold", DEFAULT_CRITICAL_RETRY_THRESHOLD))
        if custom_options and "critical_retry_threshold" in custom_options
        else DEFAULT_CRITICAL_RETRY_THRESHOLD
    )
    user_max_crops = (
        int(custom_options.get("max_critical_crops", max_crops))
        if custom_options and "max_critical_crops" in custom_options
        else max_crops
    )
    eff_max_crops = max(1, min(5, user_max_crops))

    candidates: list[tuple[int, TextSpan, CriticalityType, float]] = []
    prev_label_type: CriticalityType | None = None

    for idx, span in enumerate(spans):
        text = span.text.strip()
        if not text or span.bounding_box is None:
            prev_label_type = None
            continue

        # 1. Check if current span itself acts as a label anchor for the next span
        anchor_type = classify_label_anchor(text)
        if anchor_type is not None:
            prev_label_type = anchor_type
            continue

        # 2. Check if span is critical directly or context-anchored by preceding label
        is_crit, crit_type = classify_span(text)
        if not is_crit and prev_label_type is not None:
            is_crit = True
            crit_type = prev_label_type

        prev_label_type = None

        if not is_crit or crit_type is None:
            continue

        conf = span.confidence if span.confidence is not None else 0.0
        is_valid, _ = validate_critical_token(text, crit_type)
        if conf < crit_retry_thresh or not is_valid:
            candidates.append((idx, span, crit_type, conf))

    if not candidates:
        return spans

    candidates.sort(key=lambda c: c[3])
    to_recover = candidates[:eff_max_crops]

    from sarathi.shakti.ocr.engine.preprocessing import enhance_crop_contrast

    img_h, img_w = img_arr.shape[:2]
    recovered_spans = list(spans)

    for idx, span, crit_type, orig_conf in to_recover:
        bbox = span.bounding_box
        if bbox is None:
            continue

        x0, y0, x1, y1 = bbox
        pad = 3
        cx0 = max(0, int(math.floor(x0)) - pad)
        cy0 = max(0, int(math.floor(y0)) - pad)
        cx1 = min(img_w, int(math.ceil(x1)) + pad)
        cy1 = min(img_h, int(math.ceil(y1)) + pad)

        if cx1 <= cx0 or cy1 <= cy0:
            continue

        crop = img_arr[cy0:cy1, cx0:cx1]
        if crop.size == 0:
            continue

        overlaps_stamp = any(
            not (cx1 < sx0 or cx0 > sx1 or cy1 < sy0 or cy0 > sy1)
            for sx0, sy0, sx1, sy1 in stamps_detected_regions
        )

        enhanced_crop = enhance_crop_contrast(crop) if overlaps_stamp else crop

        try:
            rec_output = active_engine(enhanced_crop, use_det=False, use_cls=False)
        except Exception:
            continue

        if not rec_output or not getattr(rec_output, "txts", None) or not rec_output.txts:
            continue

        rec_text = str(rec_output.txts[0] or "").strip()
        rec_score = float(rec_output.scores[0]) if getattr(rec_output, "scores", None) and rec_output.scores else 0.0

        if not rec_text:
            continue

        norm_rec = unicodedata.normalize("NFC", rec_text)
        if normalize_digits:
            norm_rec = normalize_devanagari_numerals(norm_rec)
        if contains_devanagari(norm_rec):
            norm_rec = synthesize_akshara_unicode(norm_rec)
        if filter_opt:
            norm_rec = filter_english_and_numbers(norm_rec)

        rep_rec, was_rep = repair_critical_token(norm_rec, crit_type)
        candidate_text = rep_rec if was_rep else norm_rec

        orig_valid, _ = validate_critical_token(span.text, crit_type)
        cand_valid, _ = validate_critical_token(candidate_text, crit_type)

        should_replace = False
        if cand_valid and not orig_valid:
            should_replace = True
        elif rec_score > orig_conf:
            should_replace = True

        if should_replace:
            meta = dict(span.metadata)
            meta["critical_recovered"] = True
            meta["original_text"] = span.text
            meta["original_confidence"] = orig_conf
            recovered_spans[idx] = TextSpan(
                text=candidate_text,
                bounding_box=span.bounding_box,
                confidence=rec_score,
                metadata=meta,
            )

    return recovered_spans


class RapidOCREngine:
    """Instance-owned RapidOCR + OpenVINO engine adapter."""

    def __init__(
        self,
        data_root: Path | None = None,
        default_lang: str = "devanagari",
        engine: Any = None,
        engines: dict[str, Any] | None = None,
    ) -> None:
        self._data_root: Path = data_root.resolve() if data_root is not None else CANONICAL_DATA_ROOT
        self._engine: Any = engine
        self._engines: dict[str, Any] = dict(engines) if engines is not None else {}
        self._model_labels: dict[str, str] = {}
        self._default_lang: str = default_lang
        self._init_lock: threading.Lock = threading.Lock()
        self._infer_lock: threading.RLock = threading.RLock()
        self._gpu_pools: dict[str, queue.Queue[int]] = {}
        self._gpu_engines: dict[str, list[Any]] = {}
        self._engine_pools: dict[str, queue.LifoQueue[Any]] = {}
        self._engine_counts: dict[str, int] = {}
        self._verified_model_paths: dict[str, str] = {}
        self._asset_version: str = self._compute_asset_version()

    def _compute_asset_version(self) -> str:
        import hashlib

        hasher = hashlib.sha256()
        manifest_path = self._data_root / "manifest.json"
        if manifest_path.is_file():
            try:
                content = manifest_path.read_text(encoding="utf-8")
                hasher.update(content.encode("utf-8"))
            except OSError:
                pass
        return hasher.hexdigest()[:16]

    @property
    def asset_version(self) -> str:
        return self._asset_version

    @property
    def default_lang(self) -> str:
        return self._default_lang

    def warmup(self, execution_binding: ExecutionBinding | None = None) -> bool:
        """Pre-initialize RapidOCR engine and compile OpenVINO models for the target device."""
        try:
            self._get_engine(self._default_lang, execution_binding=execution_binding)
            return True
        except Exception:
            return False

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
            return engine_inst

    @contextmanager
    def _acquire_infer_engine(
        self,
        cache_key: str,
        fallback_engine: Any,
        target_lang: str = "devanagari",
        target_device: str = "CPU",
        max_capacity: int = 1,
    ):
        """Acquire an elastic inference engine slot bounded by capacity without global locks."""
        # 1. Honor manually injected test gpu_pools if present
        if cache_key in self._gpu_pools and cache_key in self._gpu_engines:
            slot_idx = self._gpu_pools[cache_key].get()
            try:
                yield self._gpu_engines[cache_key][slot_idx]
            finally:
                self._gpu_pools[cache_key].put(slot_idx)
            return

        # 2. Sequential execution or single-engine path (protects single InferRequest from concurrent corruption)
        if max_capacity <= 1:
            with self._infer_lock:
                yield fallback_engine
            return

        # 3. Elastic engine pool matching capacity
        if cache_key not in self._engine_pools:
            with self._init_lock:
                if cache_key not in self._engine_pools:
                    q: queue.LifoQueue[Any] = queue.LifoQueue()
                    q.put(fallback_engine)
                    self._engine_pools[cache_key] = q
                    self._engine_counts[cache_key] = 1

        pool = self._engine_pools[cache_key]
        active_engine = None
        try:
            active_engine = pool.get_nowait()
        except queue.Empty:
            pass

        if active_engine is None:
            with self._init_lock:
                if self._engine_counts.get(cache_key, 0) < max_capacity:
                    try:
                        active_engine, _, _, label = build_rapidocr_instance(
                            data_root=self._data_root,
                            lang=target_lang,
                            target_device=target_device,
                            verified_model_paths=self._verified_model_paths,
                            default_lang=self._default_lang,
                        )
                        self._engine_counts[cache_key] = self._engine_counts.get(cache_key, 0) + 1
                        self._model_labels[cache_key] = label
                    except Exception:
                        pass

        if active_engine is None:
            active_engine = pool.get()

        try:
            yield active_engine
        finally:
            pool.put(active_engine)

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
        check_cancelled(cancellation_token)

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

        (
            img_arr,
            stamps_detected_regions,
            stamp_removal_applied,
            stamp_removed_ratio,
            stamp_filled_arr,
            stamp_mode,
        ) = _preprocess_page_image(img_arr, profile, custom_options)

        is_instant = profile == ExecutionProfile.INSTANT and not (
            custom_options and custom_options.get("preserve_layout")
        )
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

        max_cap = (
            execution_binding.approved_concurrency
            if execution_binding is not None and execution_binding.approved_concurrency > 0
            else 1
        )
        with self._acquire_infer_engine(
            cache_key,
            fallback_engine=engine,
            target_lang=target_lang,
            target_device=target_device,
            max_capacity=max_cap,
        ) as active_engine:
            output = active_engine(img_arr, use_det=True, use_cls=use_cls_flag)
            check_cancelled(cancellation_token)

            if target_lang in DEV_LANGS and (custom_options is None or "english_numbers_only" not in custom_options):
                filter_opt = False
            elif (target_lang in V6_LANGS) or (
                target_lang in EN_LANGS and custom_options and custom_options.get("english_numbers_only")
            ):
                filter_opt = True
            else:
                filter_opt = custom_options.get("english_numbers_only", False) if custom_options else False

            normalize_digits = (
                bool(custom_options.get("normalize_digits", True))
                if custom_options and "normalize_digits" in custom_options
                else True
            )

            lines, spans, conf_scores, parse_warnings, has_invalid_confidence, has_invalid_geometry = (
                _parse_rapidocr_output(output, filter_opt=filter_opt, normalize_digits=normalize_digits)
            )

            (
                img_arr,
                output,
                lines,
                spans,
                conf_scores,
                parse_warnings,
                rotation_applied,
            ) = _evaluate_page_orientation(
                img_arr=img_arr,
                output=output,
                lines=lines,
                spans=spans,
                conf_scores=conf_scores,
                parse_warnings=parse_warnings,
                custom_options=custom_options,
                active_engine=active_engine,
                use_cls_flag=use_cls_flag,
                filter_opt=filter_opt,
                normalize_digits=normalize_digits,
                cancellation_token=cancellation_token,
            )

            warnings: list[WarningRecord] = list(parse_warnings)
            if rotation_applied > 0:
                warnings.append(
                    WarningRecord(
                        code="OCR_PAGE_ROTATED",
                        message=f"Page orientation corrected by {rotation_applied} degrees.",
                        stage=STAGE_NAME,
                        context={"rotation_applied": rotation_applied},
                    )
                )
            if stamp_removal_applied:
                warnings.append(
                    WarningRecord(
                        code="STAMP_REMOVAL_APPLIED",
                        message=f"Removed official stamp artifacts (coverage: {stamp_removed_ratio * 100:.2f}%).",
                        stage=STAGE_NAME,
                        context={
                            "stamp_count": len(stamps_detected_regions),
                            "removed_ratio": round(stamp_removed_ratio, 4),
                        },
                    )
                )

            # Bounded critical span recognition recovery (max 3 crops per page)
            spans = _recover_critical_spans(
                img_arr=img_arr,
                spans=spans,
                active_engine=active_engine,
                custom_options=custom_options,
                stamps_detected_regions=stamps_detected_regions,
                filter_opt=filter_opt,
                normalize_digits=normalize_digits,
            )

        # Apply deterministic critical token repairs (financial amounts, dates, statutory checksums)
        final_spans: list[TextSpan] = []
        for s in spans:
            rep_text, was_rep = repair_critical_token(s.text)
            if was_rep:
                s_meta = dict(s.metadata)
                s_meta["critical_repaired"] = True
                s_meta["pre_repair_text"] = s.text
                final_spans.append(
                    TextSpan(
                        text=rep_text,
                        bounding_box=s.bounding_box,
                        confidence=s.confidence,
                        metadata=s_meta,
                    )
                )
            else:
                final_spans.append(s)
        spans = final_spans

        # Continuous reading-order paragraph reconstruction for scanned pages
        # Note: Table extraction and layout preservation are reserved exclusively for native digital documents.
        final_page_text, _ = reconstruct_layout(
            None,
            spans,
            preserve_layout=False,
        )
        detected_tables: tuple[TableData, ...] = ()

        if not final_page_text.strip():
            warnings.append(
                WarningRecord(
                    code="OCR_EMPTY_PAGE",
                    message="No text detected on page.",
                    stage=STAGE_NAME,
                )
            )

        # Emit actionable human review items for text spans remaining below review threshold (< 0.80 standard, < 0.90 critical)
        review_threshold = (
            float(custom_options.get("review_threshold", 0.80))
            if custom_options and "review_threshold" in custom_options
            else 0.80
        )
        critical_review_threshold = (
            float(custom_options.get("critical_review_threshold", DEFAULT_CRITICAL_REVIEW_THRESHOLD))
            if custom_options and "critical_review_threshold" in custom_options
            else DEFAULT_CRITICAL_REVIEW_THRESHOLD
        )
        if spans:
            for s_idx, span in enumerate(spans, start=1):
                if span.confidence is not None and span.text.strip():
                    is_crit, crit_type = classify_span(span.text)
                    eff_threshold = critical_review_threshold if is_crit else review_threshold
                    if span.confidence < eff_threshold:
                        code = "OCR_CRITICAL_SPAN_LOW_CONFIDENCE" if is_crit else "OCR_LOW_CONFIDENCE"
                        crit_label = f" [{crit_type.value}]" if is_crit and crit_type else ""
                        warnings.append(
                            WarningRecord(
                                code=code,
                                message=f"Low confidence{crit_label} text span ({span.confidence:.1%}): '{span.text}'",
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
                                    "input_id": input_id,
                                    "bbox": list(span.bounding_box) if span.bounding_box else None,
                                    "is_review_item": True,
                                    "is_critical": is_crit,
                                    "criticality_type": crit_type.value if crit_type else None,
                                },
                            )
                        )

        cache_key = f"{target_lang}:{target_device}"
        if target_lang in DEV_LANGS:
            model_label = "PP-OCRv5-Devanagari"
        else:
            model_label = (
                self._model_labels.get(cache_key) or self._model_labels.get(f"v6_en:{target_device}") or "PP-OCRv6"
            )

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
        else:
            validation_outcome = "usable"

        scope = "full_devanagari" if target_lang in DEV_LANGS else ("english_and_numbers" if filter_opt else "english")

        metadata: dict[str, Any] = {
            "profile": profile.value,
            "page_height": float(orig_h),
            "page_width": float(orig_w),
            "rotation_applied": rotation_applied,
            "validation_outcome": validation_outcome,
            "model": model_label,
            "scope": scope,
            "retry_applied": False,
            "retry_count": 0,
            "retry_improved_count": 0,
            "retry_total_gain": 0.0,
            "fallback_applied": False,
            "fallback_engine": "none",
            "fallback_improved_count": 0,
            "fallback_total_gain": 0.0,
            "column_count": 1,
        }
        if page_confidence is not None:
            metadata["confidence"] = page_confidence.score
        if stamp_mode != "off":
            metadata["stamps"] = [
                {"bbox": list(r.bbox), "dominant_rgb": list(r.dominant_rgb)} for r in stamps_detected_regions
            ]

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
            "rotation_applied": rotation_applied,
            "validation_outcome": validation_outcome,
        }

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
