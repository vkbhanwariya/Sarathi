"""Executable Capability for OCR Phase 1."""

from __future__ import annotations

import dataclasses
import json
import queue
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    CapabilityDeclaration,
    ConfidenceValue,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    WarningRecord,
)
from sarathi.sankalpa.cancellation import check_cancelled
from sarathi.shakti.artifact_naming import format_artifact_filename
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.ocr.engine import RapidOCREngine
from sarathi.shakti.ocr.engine.checkpoint import (
    compute_doc_hash,
    compute_params_hash,
    load_page_checkpoint,
    save_page_checkpoint,
)
from sarathi.shakti.ocr.engine.layout import group_paragraphs
from sarathi.shakti.ocr.engine.rasterize import (
    BoundedPageRasterizer,
    get_page_count_from_bytes,
    iter_images_from_bytes,
)
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.text import cell_text
from sarathi.shakti.text.typography import (
    classify_page_lines,
    contains_devanagari,
    detect_running_headers_footers,
    normalize_header_template,
    normalize_size,
    output_font,
)

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.yantra import Yantra


from sarathi.shakti.text.usability import is_usable_document as _is_usable_document
from sarathi.shakti.text.usability import is_usable_page as _is_usable_page


def _format_page_text_with_tables(page: PageData) -> str:
    """Format full page text preserving both narrative body and tabular data."""
    parts: list[str] = []
    if page.text and page.text.strip():
        parts.append(page.text.strip())
    if page.tables:
        for tbl in page.tables:
            tbl_lines: list[str] = []
            if tbl.name and not tbl.name.startswith("Page_") and not tbl.name.startswith("Table_"):
                tbl_lines.append(f"[{tbl.name}]")
            if tbl.headers:
                tbl_lines.append(" | ".join(cell_text(c) for c in tbl.headers))
                tbl_lines.append(" | ".join("---" for _ in tbl.headers))
            for row in tbl.rows:
                tbl_lines.append(" | ".join(cell_text(c) for c in row))
            if tbl_lines:
                tbl_str = "\n".join(tbl_lines)
                if not page.text or tbl_str not in page.text:
                    parts.append(tbl_str)
    return "\n\n".join(parts)


_FLOAT_CUSTOM_OPTIONS: frozenset[str] = frozenset(
    {
        "review_threshold",
        "critical_review_threshold",
    }
)
_SUPPORTED_CUSTOM_OPTIONS: frozenset[str] = frozenset(
    {
        "engine",
        "lang",
        "preprocess",
        "deskew",
        "clahe",
        "lightweight",
        "english_numbers_only",
        "remove_stamps",
        "inpaint_stamps",
        "stamp_mode",
        "review_threshold",
        "critical_review_threshold",
        "use_angle_cls",
        "use_cls",
        "preserve_layout",
        "validation_enabled",
        "progress_callback",
        "skip_header_footer",
        "dpi",
        "force_ocr",
        "export_json",
        "checkpoint_cache_enabled",
        "normalize_digits",
        "statutory",
        "convert_legacy_fonts",
    }
)
_BOOLEAN_CUSTOM_OPTIONS: frozenset[str] = _SUPPORTED_CUSTOM_OPTIONS - {
    "engine",
    "lang",
    "progress_callback",
    "review_threshold",
    "critical_review_threshold",
    "dpi",
}


class OCRCapability:
    """Instance-owned OCR capability implementing PP-OCR OpenVINO text extraction."""

    def __init__(
        self,
        declaration: CapabilityDeclaration = CAPABILITY_DECLARATION,
        engine: RapidOCREngine | None = None,
        data_root: Path | None = None,
        yantra: Yantra | None = None,
        darpana: Darpana | None = None,
        runtime_root: Path | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.declaration: CapabilityDeclaration = declaration
        self._engine: RapidOCREngine = engine if engine is not None else RapidOCREngine(data_root=data_root)
        self._yantra: Yantra | None = yantra
        self._darpana: Darpana | None = darpana
        self._runtime_root: Path | None = runtime_root
        self._cache_dir: Path | None = (
            cache_dir
            if cache_dir is not None
            else ((runtime_root / "Cache" / "ocr_checkpoints") if runtime_root is not None else None)
        )

    @property
    def asset_version(self) -> str:
        return getattr(self._engine, "asset_version", "")

    def warmup(self, execution_binding: ExecutionBinding | None = None) -> bool:
        """Pre-initialize RapidOCR engine and compile OpenVINO models for the target device."""
        if hasattr(self._engine, "warmup"):
            return bool(self._engine.warmup(execution_binding=execution_binding))
        return False

    def _record_page_telemetry(
        self,
        context: ExecutionContext,
        inp_ref: InputRef,
        page_idx: int,
        page_data: PageData,
        dur_ns: int,
        binding: Any,
        worker_id: str,
    ) -> None:
        """Record fine-grained worker performance and page/region quality telemetry in Darpana."""
        from sarathi.shakti.ocr.telemetry import record_ocr_page_telemetry

        record_ocr_page_telemetry(
            darpana=self._darpana,
            context=context,
            inp_ref=inp_ref,
            page_idx=page_idx,
            page_data=page_data,
            dur_ns=dur_ns,
            binding=binding,
            worker_id=worker_id,
        )

    def _process_page_image(
        self,
        img: Any,
        page_idx: int,
        inp_ref: InputRef,
        tot_pages: int,
        request: Request,
        context: ExecutionContext,
        worker_id: str,
        progress_cb: Any,
        use_checkpoints: bool,
        doc_hashes: dict[str, str],
        dpi: int,
        target_lang: str,
    ) -> tuple[PageData, ProvenanceRecord, list[WarningRecord]]:
        """Shared page processing routine used by both sequential and parallel OCR paths."""
        check_cancelled(context)
        if progress_cb is not None:
            dev_str = context.execution_binding.device_type.value.upper() if context.execution_binding else "CPU"
            progress_cb(
                file_display_name=inp_ref.display_name,
                page_number=page_idx,
                total_pages=tot_pages,
                worker_id=worker_id,
                stage="Optical Character Recognition (OCR)",
                device_type=dev_str,
                input_id=inp_ref.input_id,
            )

        ocr_kwargs: dict[str, Any] = {
            "profile": request.profile,
            "custom_options": request.custom_options,
            "execution_binding": context.execution_binding,
        }
        if context.cancellation_token is not None:
            ocr_kwargs["cancellation_token"] = context.cancellation_token

        t0 = time.perf_counter_ns()
        try:
            p_data, p_prov, _, p_warns = self._engine.ocr_page(
                img,
                page_idx,
                inp_ref.input_id,
                **ocr_kwargs,
            )
        finally:
            del img

        dur = max(0, time.perf_counter_ns() - t0)
        self._record_page_telemetry(
            context=context,
            inp_ref=inp_ref,
            page_idx=page_idx,
            page_data=p_data,
            dur_ns=dur,
            binding=context.execution_binding,
            worker_id=worker_id,
        )
        if use_checkpoints:
            p_hash = compute_params_hash(
                page_number=page_idx,
                profile=request.profile,
                dpi=dpi,
                lang=target_lang,
                custom_options=request.custom_options,
                model_version=getattr(self._engine, "model_version", "v5_v6"),
                asset_version=self.asset_version,
            )
            save_page_checkpoint(
                doc_hash=doc_hashes[inp_ref.input_id],
                page_number=page_idx,
                params_hash=p_hash,
                page_data=p_data,
                provenance=p_prov,
                warnings=p_warns,
                cache_dir=self._cache_dir,
            )
        warn_list = list(p_warns) if isinstance(p_warns, (list, tuple)) else ([p_warns] if p_warns else [])
        return p_data, p_prov, warn_list

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute OCR extraction on input documents."""
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")
        if prior_result is not None and not isinstance(prior_result, Result):
            raise TypeError(f"prior_result must be a Result instance or None, got {type(prior_result).__name__}.")

        # Validate that execution profile is supported
        if request.profile not in self.declaration.supported_profiles:
            raise DoshError(
                code=FailureCode.UNSUPPORTED,
                message=f"Profile '{request.profile.value}' is not supported by OCR capability.",
            )

        # Validate custom options
        if request.custom_options:
            if request.profile == ExecutionProfile.CUSTOM:
                unknown_opts = set(request.custom_options.keys()) - _SUPPORTED_CUSTOM_OPTIONS
                if unknown_opts:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Unsupported custom option(s): {', '.join(sorted(unknown_opts))}.",
                    )
                for bool_opt in _BOOLEAN_CUSTOM_OPTIONS:
                    val = request.custom_options.get(bool_opt)
                    if val is not None and not isinstance(val, bool):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message=f"Custom option '{bool_opt}' must be a boolean, got {type(val).__name__}.",
                        )
                for float_opt in _FLOAT_CUSTOM_OPTIONS:
                    val = request.custom_options.get(float_opt)
                    if val is not None:
                        if isinstance(val, bool) or not isinstance(val, (int, float)) or not (0.0 <= float(val) <= 1.0):
                            raise DoshError(
                                code=FailureCode.VALIDATION_FAILED,
                                message=f"Custom option '{float_opt}' must be a float in range [0.0, 1.0], got {val}.",
                            )
                opt_engine = request.custom_options.get("engine")
                if opt_engine is not None and str(opt_engine).lower().strip() != "rapidocr":
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Requested OCR engine '{opt_engine}' is not supported. Only 'rapidocr' is supported.",
                    )
                opt_dpi = request.custom_options.get("dpi")
                if opt_dpi is not None:
                    if isinstance(opt_dpi, bool) or not isinstance(opt_dpi, int) or not (72 <= opt_dpi <= 600):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message=f"Custom option 'dpi' must be an integer in range [72, 600], got {opt_dpi}.",
                        )
            opt_lang = request.custom_options.get("lang")
            if opt_lang is not None:
                clean_lang = str(opt_lang).lower().strip()
                from sarathi.shakti.ocr.engine import ALL_SUPPORTED_LANGS

                if clean_lang not in ALL_SUPPORTED_LANGS:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Requested OCR language '{opt_lang}' is not supported. Supported languages: 'devanagari', 'hi', 'en_v6', 'en'.",
                    )

        # Inspect prior_result for existing usable native documents using structural pattern matching
        prior_docs: dict[str, CanonicalDocument] = {}
        if prior_result is not None and prior_result.data is not None:
            match prior_result.data:
                case CanonicalDocument() as doc:
                    prior_docs[doc.source_input_id] = doc
                case tuple() | list() as items:
                    prior_docs.update(
                        {item.source_input_id: item for item in items if isinstance(item, CanonicalDocument)}
                    )

        final_docs: list[CanonicalDocument] = []
        all_provenance: list[ProvenanceRecord] = list(prior_result.provenance) if prior_result else []
        all_warnings: list[WarningRecord] = list(prior_result.warnings) if prior_result else []

        # 1. Preflight inputs: separate already-usable native documents, empty inputs, and OCR candidates
        ocr_inputs: list[tuple[InputRef, list[Any], list[int]]] = []
        empty_or_usable_docs: dict[str, CanonicalDocument] = {}
        existing_native_pages_by_input: dict[str, dict[int, PageData]] = {}
        input_passwords: dict[str, str | None] = {}

        for inp in request.inputs:
            check_cancelled(context)

            pw: str | None = None
            if request.custom_options:
                passwords = request.custom_options.get("passwords")
                if isinstance(passwords, dict):
                    pw = (
                        passwords.get(inp.input_id)
                        or passwords.get(inp.display_name)
                        or (passwords.get(inp.source_path.name) if inp.source_path else None)
                        or (passwords.get(str(inp.source_path)) if inp.source_path else None)
                    )
                if not pw and isinstance(request.custom_options.get("pdf_password"), str):
                    pw = request.custom_options["pdf_password"]
            input_passwords[inp.input_id] = pw

            if (usable_doc := prior_docs.get(inp.input_id)) and _is_usable_document(usable_doc):
                empty_or_usable_docs[inp.input_id] = usable_doc
                continue

            native_pages: dict[int, PageData] = {}
            if inp.input_id in prior_docs:
                prior_doc = prior_docs[inp.input_id]
                for p in prior_doc.pages:
                    if _is_usable_page(p):
                        native_pages[p.page_number] = p
            try:
                data = inp.source_path.read_bytes()
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to read source input file.",
                ) from exc

            check_cancelled(context)

            force_ocr = bool(request.custom_options and request.custom_options.get("force_ocr"))
            if (
                not force_ocr
                and inp.input_id not in prior_docs
                and (
                    inp.media_type == "application/pdf"
                    or (inp.source_path and str(inp.source_path).lower().endswith(".pdf"))
                )
            ):
                try:
                    from sarathi.shakti.native_extraction.readers.pdf import read_pdf

                    pdf_doc, pdf_prov, pdf_warns = read_pdf(data, inp.input_id, password=pw)
                    for p in pdf_doc.pages:
                        if _is_usable_page(p):
                            p_meta = dict(p.metadata)
                            p_meta["extraction_method"] = "native_fastpath"
                            native_pages[p.page_number] = PageData(
                                page_number=p.page_number,
                                text=p.text,
                                spans=p.spans,
                                tables=p.tables,
                                metadata=p_meta,
                            )
                    if pdf_warns and native_pages:
                        all_warnings.extend(
                            [w for w in pdf_warns if getattr(w, "page_number", None) in native_pages]
                            if any(getattr(w, "page_number", None) is not None for w in pdf_warns)
                            else pdf_warns
                        )
                    if pdf_prov and native_pages:
                        all_provenance.extend([pr for pr in pdf_prov if pr.page_number in native_pages])
                except Exception:
                    pass

            existing_native_pages_by_input[inp.input_id] = native_pages

            skip_pages = set(native_pages.keys())
            total_pages = get_page_count_from_bytes(data, password=pw)

            if total_pages == 0:
                if len(data) == 0:
                    all_warnings.append(
                        WarningRecord(
                            code="OCR_EMPTY_INPUT",
                            message="Input file is empty.",
                            stage="ocr",
                        )
                    )
                    empty_doc = CanonicalDocument(
                        document_id=f"doc-{inp.input_id}",
                        source_input_id=inp.input_id,
                        detected_type="ocr_document",
                    )
                    empty_or_usable_docs[inp.input_id] = empty_doc
                    continue

                raise DoshError(
                    code=FailureCode.UNSUPPORTED,
                    message="Unsupported content format for OCR.",
                )

            needed_page_indices = [idx for idx in range(1, total_pages + 1) if idx not in skip_pages]
            ocr_inputs.append((inp, data, total_pages, needed_page_indices, skip_pages))

        # Check for progress callback
        progress_cb = None
        if request.custom_options and callable(request.custom_options.get("progress_callback")):
            progress_cb = request.custom_options["progress_callback"]

        # Locked standard 200 DPI resolution for OCR across all profiles
        dpi = 200
        if request.custom_options and "dpi" in request.custom_options:
            try:
                dpi = int(request.custom_options["dpi"])
            except (ValueError, TypeError):
                dpi = 200

        # Checkpoint cache configuration
        checkpoint_cache_enabled = (
            bool(request.custom_options.get("checkpoint_cache_enabled", True))
            if request.custom_options and "checkpoint_cache_enabled" in request.custom_options
            else True
        )
        force_ocr = (
            bool(request.custom_options.get("force_ocr", False))
            if request.custom_options and "force_ocr" in request.custom_options
            else False
        )
        use_checkpoints = checkpoint_cache_enabled and not force_ocr

        target_lang = (
            str(request.custom_options.get("lang", self._engine.default_lang if self._engine else "hi"))
            if request.custom_options and "lang" in request.custom_options
            else (self._engine.default_lang if self._engine else "hi")
        )

        doc_page_results: dict[str, list[tuple[int, PageData, ProvenanceRecord | None, list[WarningRecord]]]] = {
            inp.input_id: [] for inp, _, _, _, _ in ocr_inputs
        }
        doc_hashes: dict[str, str] = {}
        for inp, data, tot_pages, needed_indices, skip_pages in ocr_inputs:
            d_hash = compute_doc_hash(data)
            doc_hashes[inp.input_id] = d_hash

            # Populate pre-extracted native pages
            native_p = existing_native_pages_by_input.get(inp.input_id, {})
            for p_num, p_data in sorted(native_p.items(), key=lambda x: x[0]):
                doc_page_results[inp.input_id].append((p_num, p_data, None, []))
                if progress_cb is not None:
                    dev_str = context.execution_binding.device_type.value if context.execution_binding else "CPU"
                    progress_cb(
                        file_display_name=inp.display_name,
                        page_number=p_num,
                        total_pages=tot_pages,
                        worker_id="native",
                        stage="Optical Character Recognition (OCR)",
                        device_type=dev_str,
                        input_id=inp.input_id,
                    )

            # Check and restore existing page checkpoints
            if use_checkpoints:
                still_needed: list[int] = []
                for p_idx in needed_indices:
                    p_hash = compute_params_hash(
                        page_number=p_idx,
                        profile=request.profile,
                        dpi=dpi,
                        lang=target_lang,
                        custom_options=request.custom_options,
                        model_version=getattr(self._engine, "model_version", "v5_v6"),
                        asset_version=self.asset_version,
                    )
                    cached = load_page_checkpoint(d_hash, p_idx, p_hash, cache_dir=self._cache_dir)
                    if cached is not None:
                        c_pdata, c_prov, c_warns = cached
                        if c_prov is not None and c_prov.source_input_id != inp.input_id:
                            c_prov = dataclasses.replace(c_prov, source_input_id=inp.input_id)
                        if (
                            "source_input_id" in c_pdata.metadata
                            and c_pdata.metadata["source_input_id"] != inp.input_id
                        ):
                            c_pdata_meta = dict(c_pdata.metadata)
                            c_pdata_meta["source_input_id"] = inp.input_id
                            c_pdata = dataclasses.replace(c_pdata, metadata=c_pdata_meta)
                        doc_page_results[inp.input_id].append((p_idx, c_pdata, c_prov, c_warns))
                        skip_pages.add(p_idx)
                        if progress_cb is not None:
                            dev_str = (
                                context.execution_binding.device_type.value if context.execution_binding else "CPU"
                            )
                            progress_cb(
                                file_display_name=inp.display_name,
                                page_number=p_idx,
                                total_pages=tot_pages,
                                worker_id="checkpoint",
                                stage="Optical Character Recognition (OCR)",
                                device_type=dev_str,
                                input_id=inp.input_id,
                            )
                    else:
                        still_needed.append(p_idx)
                needed_indices.clear()
                needed_indices.extend(still_needed)

        # 2. Perform OCR: decompose page work; Yantra owns device and concurrency policy.
        total_pages_needing_ocr = sum(len(needed) for _, _, _, needed, _ in ocr_inputs)
        is_parallelizable = self.declaration.device_requirement.parallelizable
        approved_concurrency = context.execution_binding.approved_concurrency if context.execution_binding else None
        can_parallelize = (
            total_pages_needing_ocr > 1
            and self._yantra is not None
            and is_parallelizable
            and (approved_concurrency is None or approved_concurrency > 1)
        )

        if can_parallelize:
            all_items: list[tuple[InputRef, int, int]] = []
            rasterizers: dict[str, BoundedPageRasterizer] = {}
            total_target_buffer = 8
            per_doc_buffered = max(1, min(4, total_target_buffer // max(1, len(ocr_inputs))))
            for inp, file_bytes, tot_pages, needed_indices, _ in ocr_inputs:
                if not needed_indices:
                    continue
                rasterizers[inp.input_id] = BoundedPageRasterizer(
                    file_bytes,
                    pages=needed_indices,
                    dpi=dpi,
                    max_buffered=per_doc_buffered,
                    cancellation_token=context.cancellation_token,
                    password=input_passwords.get(inp.input_id),
                )
                for p_idx in needed_indices:
                    all_items.append((inp, p_idx, tot_pages))

            # BoundedPageRasterizer lazily starts on first get_page() call,
            # avoiding thread storms and memory spikes across multi-doc batches.

            def _make_page_task(
                inp_ref: InputRef, p_idx: int, tot_pages: int
            ) -> Callable[[], tuple[PageData, ProvenanceRecord, list[WarningRecord]]]:
                def _task() -> tuple[PageData, ProvenanceRecord, list[WarningRecord]]:
                    check_cancelled(context)
                    p_img = rasterizers[inp_ref.input_id].get_page(p_idx)
                    if p_img is None:
                        raise DoshError(
                            code=FailureCode.EXECUTION_FAILED,
                            message=f"Failed to rasterize page {p_idx} for OCR.",
                        )
                    w_id = str(threading.get_ident() % 1000)
                    return self._process_page_image(
                        img=p_img,
                        page_idx=p_idx,
                        inp_ref=inp_ref,
                        tot_pages=tot_pages,
                        request=request,
                        context=context,
                        worker_id=w_id,
                        progress_cb=progress_cb,
                        use_checkpoints=use_checkpoints,
                        doc_hashes=doc_hashes,
                        dpi=dpi,
                        target_lang=target_lang,
                    )

                return _task

            try:
                subtasks = [_make_page_task(item[0], item[1], item[2]) for item in all_items]
                page_results = self._yantra.execute_subtasks(subtasks, context=context)
                for (inp_ref, p_idx, _), (p_data, p_prov, p_warns) in zip(all_items, page_results):
                    doc_page_results[inp_ref.input_id].append((p_idx, p_data, p_prov, p_warns))
            finally:
                for r in rasterizers.values():
                    r.close()
        else:
            for inp, file_bytes, tot_pages, needed_indices, skip_pages in ocr_inputs:
                page_iter = enumerate(
                    iter_images_from_bytes(
                        file_bytes,
                        dpi=dpi,
                        cancellation_token=context.cancellation_token,
                        skip_pages=skip_pages,
                        password=input_passwords.get(inp.input_id),
                    ),
                    start=1,
                )
                # Asynchronous CPU-GPU overlap: prefetch Page N+1 on CPU while iGPU infers Page N
                prefetch_q: queue.Queue[tuple[int, Any] | None] = queue.Queue(maxsize=1)
                producer_exc: list[Exception] = []

                def _prefetch_producer() -> None:
                    try:
                        for item in page_iter:
                            prefetch_q.put(item)
                    except Exception as e:
                        producer_exc.append(e)
                    finally:
                        prefetch_q.put(None)

                producer_th = threading.Thread(target=_prefetch_producer, daemon=True)
                producer_th.start()

                while True:
                    item = prefetch_q.get()
                    if item is None:
                        break
                    page_idx, img = item
                    if img is None or page_idx not in needed_indices:
                        continue
                    page_data, prov, page_warnings = self._process_page_image(
                        img=img,
                        page_idx=page_idx,
                        inp_ref=inp,
                        tot_pages=tot_pages,
                        request=request,
                        context=context,
                        worker_id="1",
                        progress_cb=progress_cb,
                        use_checkpoints=use_checkpoints,
                        doc_hashes=doc_hashes,
                        dpi=dpi,
                        target_lang=target_lang,
                    )
                    doc_page_results[inp.input_id].append((page_idx, page_data, prov, page_warnings))

                producer_th.join()
                if producer_exc:
                    raise producer_exc[0]

        # 3. Assemble CanonicalDocuments preserving exact request input order
        for inp in request.inputs:
            if inp.input_id in empty_or_usable_docs:
                final_docs.append(empty_or_usable_docs[inp.input_id])
                continue

            raw_results = doc_page_results.get(inp.input_id, [])
            raw_results.sort(key=lambda r: r[0])

            pages = []
            for _, page_data, prov, page_warnings in raw_results:
                pages.append(page_data)
                if prov is not None:
                    all_provenance.append(prov)
                all_warnings.extend(page_warnings)

            skip_header_footer = (
                bool(request.custom_options.get("skip_header_footer"))
                if (request.custom_options and "skip_header_footer" in request.custom_options)
                else True
            )

            if len(pages) > 1:
                ocr_pages_items: list[list[tuple[str, tuple[float, float, float, float]]]] = []
                page_heights: list[float] = []
                for p in pages:
                    p_items: list[tuple[str, tuple[float, float, float, float]]] = []
                    max_y = 100.0
                    for s in p.spans:
                        if s.text and s.bounding_box:
                            p_items.append((s.text, s.bounding_box))
                            max_y = max(max_y, float(s.bounding_box[3]))
                    ocr_pages_items.append(p_items)
                    true_h = p.metadata.get("page_height") if p.metadata else None
                    if true_h is not None and float(true_h) > 0:
                        page_heights.append(float(true_h))
                    else:
                        page_heights.append(max_y)

                header_templates, footer_templates = detect_running_headers_footers(
                    ocr_pages_items, page_heights, footer_margin_ratio=0.12
                )

                if header_templates or footer_templates:
                    clean_pages: list[PageData] = []
                    for p_idx, p in enumerate(pages):
                        p_items = ocr_pages_items[p_idx]
                        p_height = page_heights[p_idx]
                        body_lines, header_lines, footer_lines = classify_page_lines(
                            p_items, p_height, header_templates, footer_templates, footer_margin_ratio=0.12
                        )
                        p_meta = dict(p.metadata)
                        if header_lines:
                            p_meta["header"] = "\n".join(header_lines)
                        if footer_lines:
                            p_meta["footer"] = "\n".join(footer_lines)

                        if skip_header_footer and (header_lines or footer_lines):
                            eff_h = max(100.0, float(p_height))
                            hdr_cutoff = eff_h * 0.20
                            ftr_cutoff = eff_h * (1.0 - 0.12)
                            body_spans = []
                            for s in p.spans:
                                if not s.bounding_box or not s.text:
                                    body_spans.append(s)
                                    continue
                                tmpl = normalize_header_template(s.text.strip())
                                sy0, sy1 = s.bounding_box[1], s.bounding_box[3]
                                if (sy1 <= hdr_cutoff or sy0 <= hdr_cutoff * 0.75) and tmpl in header_templates:
                                    continue
                                if (sy0 >= ftr_cutoff or sy1 >= ftr_cutoff * 1.05) and tmpl in footer_templates:
                                    continue
                                body_spans.append(s)
                            p_text = group_paragraphs(body_spans) if body_spans else ""
                            p_spans = tuple(body_spans)
                        else:
                            p_text = p.text
                            p_spans = p.spans
                        clean_pages.append(
                            PageData(
                                page_number=p.page_number,
                                text=p_text,
                                spans=p_spans,
                                tables=p.tables,
                                metadata=p_meta,
                            )
                        )
                    pages = clean_pages

            if len(pages) > 1:
                page_sections = []
                for p in pages:
                    heading = f"--- Page {p.page_number} ---"
                    p_formatted = _format_page_text_with_tables(p)
                    if p_formatted:
                        page_sections.append(f"{heading}\n{p_formatted}")
                    else:
                        page_sections.append(heading)
                full_text = "\n\n".join(page_sections)
            else:
                full_text = "\n\n".join(
                    _format_page_text_with_tables(p) for p in pages if _format_page_text_with_tables(p)
                )

            all_tables = tuple(t for p in pages for t in p.tables)
            ocr_doc = CanonicalDocument(
                document_id=f"doc-{inp.input_id}",
                source_input_id=inp.input_id,
                pages=tuple(pages),
                tables=all_tables,
                text=full_text,
                detected_type="ocr_document",
            )
            final_docs.append(ocr_doc)

        result_data: Any = final_docs[0] if len(final_docs) == 1 else tuple(final_docs)

        # Aggregate overall measured confidence across OCR pages produced in this pass
        ocr_pages: list[PageData] = []
        for inp, doc in zip(request.inputs, final_docs):
            if inp.input_id not in prior_docs or not _is_usable_document(prior_docs[inp.input_id]):
                ocr_pages.extend(doc.pages)

        actual_ocr_pages = [p for p in ocr_pages if p.metadata.get("extraction_method") != "native_fastpath"]

        scores: list[float] = [
            float(p.metadata["confidence"])
            for p in actual_ocr_pages
            if isinstance(p.metadata.get("confidence"), (int, float))
        ]

        page_models = {
            prov.evidence.get("model")
            for prov in all_provenance
            if prov.stage == "ocr" and bool(prov.evidence) and prov.evidence.get("model")
        }
        evidence_dict: dict[str, Any] = {
            "score_kind": "raw_engine",
            "calibrated": False,
            "engine": "rapidocr",
            "backend": "openvino",
            "page_count": len(scores),
        }
        if len(page_models) == 1:
            evidence_dict["model"] = next(iter(page_models))
        elif page_models:
            evidence_dict["models"] = sorted(str(m) for m in page_models)

        if actual_ocr_pages:
            overall_confidence: ConfidenceValue | None = (
                ConfidenceValue(
                    score=round(sum(scores) / len(scores), 4),
                    method="rapidocr_mean",
                    evidence=evidence_dict,
                )
                if (scores and len(scores) == len(actual_ocr_pages))
                else None
            )
        elif ocr_pages:
            overall_confidence = ConfidenceValue(
                score=1.0,
                method="native_passthrough",
                evidence={
                    "score_kind": "deterministic",
                    "calibrated": True,
                    "engine": "native_extraction",
                    "page_count": len(ocr_pages),
                },
            )
        else:
            overall_confidence = None

        metadata: dict[str, Any] = {
            "ocr_coverage": {
                "total_pages": len(ocr_pages),
                "unaltered_rapidocr_pages": len(scores),
            }
        }

        export_json = bool(request.custom_options and request.custom_options.get("export_json"))

        # Construct confirmed artifact payloads for extracted text and structured JSON
        payloads: list[ArtifactPayload] = []
        for idx, (inp, doc) in enumerate(zip(request.inputs, final_docs)):
            txt_name = format_artifact_filename(inp, "ocr", "txt", all_inputs=request.inputs, index=idx)
            docx_name = format_artifact_filename(inp, "ocr", "docx", all_inputs=request.inputs, index=idx)

            # 1. Plain text extracted output (clean plain text without markdown heading hashes)
            clean_txt = "\n".join(re.sub(r"^(?:#{1,6}\s+)", "", line) for line in (doc.text or "").splitlines())
            payloads.append(
                ArtifactPayload(
                    intent=ArtifactIntent(
                        name=txt_name,
                        role="extracted_text",
                        media_type="text/plain",
                    ),
                    content=clean_txt.encode("utf-8"),
                )
            )

            # 2. Structured JSON output (optional, defaults to omitted for clean output)
            if export_json:
                json_name = format_artifact_filename(inp, "ocr", "json", all_inputs=request.inputs, index=idx)
                doc_dict: dict[str, Any] = {
                    "document_id": doc.document_id,
                    "source_input_id": doc.source_input_id,
                    "detected_type": doc.detected_type,
                    "text": doc.text,
                    "pages": [
                        {
                            "page_number": p.page_number,
                            "text": p.text,
                            "metadata": dict(p.metadata),
                            "tables": [
                                {
                                    "name": t.name,
                                    "headers": list(t.headers),
                                    "rows": [list(row) for row in t.rows],
                                    "metadata": dict(t.metadata) if t.metadata else {},
                                }
                                for t in p.tables
                            ],
                            "spans": [
                                {
                                    "text": s.text,
                                    "bounding_box": list(s.bounding_box) if s.bounding_box else None,
                                    "confidence": s.confidence,
                                    "language": s.language,
                                    "script": s.script,
                                    "metadata": dict(s.metadata) if s.metadata else {},
                                }
                                for s in p.spans
                            ],
                        }
                        for p in doc.pages
                    ],
                }
                payloads.append(
                    ArtifactPayload(
                        intent=ArtifactIntent(
                            name=json_name,
                            role="ocr_document",
                            media_type="application/json",
                        ),
                        content=json.dumps(doc_dict, ensure_ascii=False, indent=2).encode("utf-8"),
                    )
                )

            doc_has_dev = contains_devanagari(doc.text)
            doc_font = output_font(contains_devanagari=doc_has_dev)
            raw_size = doc.metadata.get("font_size_pt") if doc.metadata else None
            doc_size = normalize_size(raw_size)
            # 3. Formatted DOCX output
            payloads.append(
                build_docx_payload(
                    doc=doc,
                    filename=docx_name,
                    role="ocr_document",
                    default_font=doc_font,
                    default_size_pt=doc_size,
                    interpret_markdown_headings=False,
                )
            )

        return Result(
            data=result_data,
            artifact_payloads=tuple(payloads),
            confidence=overall_confidence,
            warnings=tuple(all_warnings),
            provenance=tuple(all_provenance),
            next_requirement=None,
            metadata=metadata,
        )
