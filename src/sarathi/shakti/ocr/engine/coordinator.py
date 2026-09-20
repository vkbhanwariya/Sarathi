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
    classify_span,
)
from sarathi.shakti.ocr.engine.factory import build_rapidocr_instance, resolve_engine_keys
from sarathi.shakti.ocr.engine.layout import detect_column_count, reconstruct_layout
from sarathi.shakti.ocr.engine.openvino import resolve_target_device
from sarathi.shakti.ocr.engine.parser import _parse_rapidocr_output
from sarathi.shakti.ocr.engine.preprocessing import (
    RotationCandidate,
    apply_clahe,
    choose_page_rotation,
    is_low_contrast_image,
)
from sarathi.shakti.ocr.engine.readiness import check_ocr_readiness
from sarathi.shakti.text.typography import normalize_devanagari_numerals


def _preprocess_page_image(
    img_arr: np.ndarray,
    profile: ExecutionProfile,
    custom_options: Mapping[str, Any] | None,
) -> tuple[np.ndarray, tuple[Any, ...], bool, float, Any, bool, str]:
    """Execute adaptive deskew, CLAHE, stamp detection/removal, and binarization."""
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
            from sarathi.shakti.ocr.engine.preprocessing import detect_stamps, remove_stamp_artifacts

            detection = detect_stamps(img_arr)
            stamps_detected_regions = detection.regions
            if detection.removed_ratio > 0.0:
                stamp_filled_arr = remove_stamp_artifacts(img_arr)
                if stamp_mode == "remove":
                    img_arr = stamp_filled_arr
                    stamp_removal_applied = True
                    stamp_removed_ratio = detection.removed_ratio

        img_arr = ocr_engine.preprocess_ocr_image(img_arr, deskew=deskew, clahe=clahe, remove_stamps=False)
    else:
        stamps_detected_regions = ()
        stamp_removal_applied = False
        stamp_removed_ratio = 0.0
        stamp_filled_arr = None

    is_binarized = False
    if profile == ExecutionProfile.CUSTOM and custom_options and custom_options.get("binarize"):
        is_binarized = True
        try:
            import cv2

            gray = cv2.cvtColor(img_arr, cv2.COLOR_RGB2GRAY) if len(img_arr.shape) == 3 else img_arr
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
            img_arr = cv2.cvtColor(thresh, cv2.COLOR_GRAY2RGB)
        except ImportError:
            from PIL import Image

            gray_pil = Image.fromarray(img_arr).convert("L")
            threshold_img = gray_pil.point(lambda p: 255 if p > 128 else 0)
            img_arr = np.array(threshold_img.convert("RGB"))

    return (
        img_arr,
        stamps_detected_regions,
        stamp_removal_applied,
        stamp_removed_ratio,
        stamp_filled_arr,
        is_binarized,
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
        candidate_angles = [90, 270] if median_ratio > 1.5 else [180, 90, 270]
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
            is_binarized,
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

            # Same-engine weak-crop retry for ACCURATE, LAYOUT_PRESERVING, or CUSTOM
            is_high_accuracy = profile in (ExecutionProfile.ACCURATE, ExecutionProfile.LAYOUT_PRESERVING) or bool(
                custom_options and (custom_options.get("preserve_layout") or custom_options.get("retry_enabled"))
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
            critical_retry_threshold = (
                float(custom_options.get("critical_retry_threshold", DEFAULT_CRITICAL_RETRY_THRESHOLD))
                if (custom_options and "critical_retry_threshold" in custom_options)
                else DEFAULT_CRITICAL_RETRY_THRESHOLD
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
                    if span.confidence is not None and span.bounding_box:
                        is_crit, _ = classify_span(span.text)
                        effective_retry_thresh = critical_retry_threshold if is_crit else retry_threshold
                        if span.confidence < effective_retry_thresh:
                            min_x, min_y, max_x, max_y = span.bounding_box
                            # Zero-copy crop slicing with 3px boundary padding
                            cy0 = max(0, int(min_y) - 3)
                            cy1 = min(h_img, int(max_y) + 3)
                            cx0 = max(0, int(min_x) - 3)
                            cx1 = min(w_img, int(max_x) + 3)

                            if cy1 <= cy0 or cx1 <= cx0:
                                continue

                            retry_count += 1
                            if stamp_mode == "auto" and stamp_filled_arr is not None:
                                overlap_stamp = any(
                                    not (cx1 < r.bbox[0] or cx0 > r.bbox[2] or cy1 < r.bbox[1] or cy0 > r.bbox[3])
                                    for r in stamps_detected_regions
                                )
                                source_crop_img = stamp_filled_arr if overlap_stamp else img_arr
                            else:
                                source_crop_img = img_arr
                            crop = source_crop_img[cy0:cy1, cx0:cx1]

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
                                    s = float(b_scores[i]) if b_scores[i] is not None else 0.0
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
                        if normalize_digits:
                            r_text = normalize_devanagari_numerals(r_text)

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
        is_layout_mode = profile == ExecutionProfile.LAYOUT_PRESERVING or bool(
            custom_options and custom_options.get("preserve_layout")
        )
        final_page_text, detected_tables = reconstruct_layout(
            img_arr,
            spans,
            preserve_layout=is_layout_mode,
        )

        # Ragged row and spanning cell guards for tabular fidelity
        if detected_tables:
            for tbl in detected_tables:
                is_ragged = any(len(r) != len(tbl.headers) for r in tbl.rows)
                has_spanning = bool(tbl.metadata.get("has_spanning_cells", False))
                if is_ragged or has_spanning:
                    warnings.append(
                        WarningRecord(
                            code="LAYOUT_TABLE_ROW_RAGGED",
                            message=f"Table '{tbl.name}' has irregular column counts or detected spanning cells.",
                            stage=STAGE_NAME,
                        )
                    )

        if not final_page_text.strip() and not detected_tables:
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
        elif retry_applied:
            validation_outcome = "retry_improved"
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
            "retry_applied": retry_applied,
            "retry_count": retry_count,
            "retry_improved_count": retry_improved_count,
            "retry_total_gain": round(retry_total_gain, 4),
            "fallback_applied": retry_applied,
            "fallback_engine": "same_engine_retry" if retry_applied else "none",
            "fallback_improved_count": retry_improved_count,
            "fallback_total_gain": round(retry_total_gain, 4),
            "column_count": detect_column_count(spans) if is_layout_mode else 1,
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
