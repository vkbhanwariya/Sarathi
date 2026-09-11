"""Executable Capability for OCR Phase 1."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    CapabilityDeclaration,
    ConfidenceValue,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    WarningRecord,
)
from sarathi.shakti.artifact_naming import format_artifact_filename
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.ocr.engine import RapidOCREngine, extract_images_from_bytes
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.text.typography import (
    contains_devanagari,
    normalize_size,
    output_font,
)

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.yantra import Yantra


def _is_usable_page(page: PageData) -> bool:
    """Check whether a PageData contains usable text or table data."""
    p_text = bool(page.text and page.text.strip())
    p_tables = any(len(t.rows) > 0 or len(t.headers) > 0 for t in page.tables)
    return p_text or p_tables


def _is_usable_document(doc: CanonicalDocument) -> bool:
    """Check whether a CanonicalDocument contains usable text or table data across all pages."""
    if doc.pages:
        return all(_is_usable_page(p) for p in doc.pages)
    has_text = bool(doc.text and doc.text.strip())
    has_tables = any(len(t.rows) > 0 or len(t.headers) > 0 for t in doc.tables)
    return has_text or has_tables


_SUPPORTED_CUSTOM_OPTIONS: frozenset[str] = frozenset({
    "engine",
    "lang",
    "preprocess",
    "deskew",
    "clahe",
    "lightweight",
    "binarize",
    "english_numbers_only",
    "remove_stamps",
    "inpaint_stamps",
    "fallback_enabled",
    "validation_enabled",
    "progress_callback",
})
_BOOLEAN_CUSTOM_OPTIONS: frozenset[str] = _SUPPORTED_CUSTOM_OPTIONS - {
    "engine",
    "lang",
    "progress_callback",
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
    ) -> None:
        self.declaration: CapabilityDeclaration = declaration
        self._engine: RapidOCREngine = engine if engine is not None else RapidOCREngine(data_root=data_root)
        self._yantra: Yantra | None = yantra
        self._darpana: Darpana | None = darpana

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
                opt_engine = request.custom_options.get("engine")
                if opt_engine is not None and str(opt_engine).lower().strip() != "rapidocr":
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Requested OCR engine '{opt_engine}' is not supported. Only 'rapidocr' is supported.",
                    )
            opt_lang = request.custom_options.get("lang")
            if opt_lang is not None:
                clean_lang = str(opt_lang).lower().strip()
                from sarathi.shakti.ocr.engine import _ALL_SUPPORTED_LANGS

                if clean_lang not in _ALL_SUPPORTED_LANGS:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Requested OCR language '{opt_lang}' is not supported. Supported languages: 'devanagari', 'en_v6', 'en'.",
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

        for inp in request.inputs:
            if (usable_doc := prior_docs.get(inp.input_id)) and _is_usable_document(usable_doc):
                empty_or_usable_docs[inp.input_id] = usable_doc
                continue

            try:
                data = inp.source_path.read_bytes()
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to read source input file.",
                ) from exc

            images = extract_images_from_bytes(data)
            if not images:
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

            native_pages: dict[int, PageData] = {}
            if inp.input_id in prior_docs:
                prior_doc = prior_docs[inp.input_id]
                for p in prior_doc.pages:
                    if _is_usable_page(p):
                        native_pages[p.page_number] = p
            existing_native_pages_by_input[inp.input_id] = native_pages

            needed_page_indices = [
                idx for idx in range(1, len(images) + 1)
                if idx not in native_pages
            ]
            ocr_inputs.append((inp, images, needed_page_indices))

        # Check for progress callback
        progress_cb = None
        if request.custom_options and callable(request.custom_options.get("progress_callback")):
            progress_cb = request.custom_options["progress_callback"]

        # 2. Perform OCR: decompose page work; Yantra owns device and concurrency policy.
        total_pages_needing_ocr = sum(len(needed) for _, _, needed in ocr_inputs)
        is_parallelizable = self.declaration.device_requirement.parallelizable
        approved_concurrency = (
            context.execution_binding.approved_concurrency if context.execution_binding else None
        )
        can_parallelize = (
            total_pages_needing_ocr > 1
            and self._yantra is not None
            and is_parallelizable
            and (approved_concurrency is None or approved_concurrency > 1)
        )

        doc_page_results: dict[str, list[tuple[int, PageData, ProvenanceRecord | None, list[WarningRecord]]]] = {
            inp.input_id: [] for inp, _, _ in ocr_inputs
        }
        for inp, _, _ in ocr_inputs:
            for p_num, p_data in existing_native_pages_by_input.get(inp.input_id, {}).items():
                doc_page_results[inp.input_id].append((p_num, p_data, None, []))

        if can_parallelize:
            all_items: list[tuple[InputRef, int, int, Any]] = []
            for inp, images, needed_indices in ocr_inputs:
                tot = len(images)
                for p_idx in needed_indices:
                    img = images[p_idx - 1]
                    all_items.append((inp, p_idx, tot, img))

            def _make_page_task(
                inp_ref: InputRef, p_idx: int, tot_pages: int, p_img: Any
            ) -> Callable[[], tuple[PageData, ProvenanceRecord, list[WarningRecord]]]:
                def _task() -> tuple[PageData, ProvenanceRecord, list[WarningRecord]]:
                    if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                        context.cancellation_token.check_cancelled()

                    w_id = str(threading.get_ident() % 1000)
                    if progress_cb is not None:
                        dev_str = (
                            context.execution_binding.device_type.value.upper()
                            if context.execution_binding
                            else "CPU"
                        )
                        progress_cb(
                            file_display_name=inp_ref.display_name,
                            page_number=p_idx,
                            total_pages=tot_pages,
                            worker_id=w_id,
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
                    p_data, p_prov, _, p_warns = self._engine.ocr_page(
                        p_img,
                        p_idx,
                        inp_ref.input_id,
                        **ocr_kwargs,
                    )
                    dur = max(0, time.perf_counter_ns() - t0)
                    self._record_page_telemetry(
                        context=context,
                        inp_ref=inp_ref,
                        page_idx=p_idx,
                        page_data=p_data,
                        dur_ns=dur,
                        binding=context.execution_binding,
                        worker_id=w_id,
                    )
                    return p_data, p_prov, p_warns

                return _task

            subtasks = [_make_page_task(item[0], item[1], item[2], item[3]) for item in all_items]
            page_results = self._yantra.execute_subtasks(subtasks, context=context)
            for (inp_ref, p_idx, _, _), (p_data, p_prov, p_warns) in zip(all_items, page_results):
                doc_page_results[inp_ref.input_id].append((p_idx, p_data, p_prov, p_warns))
        else:
            for inp, images, needed_indices in ocr_inputs:
                tot = len(images)
                for page_idx in needed_indices:
                    img = images[page_idx - 1]
                    if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                        context.cancellation_token.check_cancelled()

                    if progress_cb is not None:
                        dev_str = (
                            context.execution_binding.device_type.value
                            if context.execution_binding
                            else "CPU"
                        )
                        progress_cb(
                            file_display_name=inp.display_name,
                            page_number=page_idx,
                            total_pages=tot,
                            worker_id="1",
                            stage="Optical Character Recognition (OCR)",
                            device_type=dev_str,
                            input_id=inp.input_id,
                        )

                    seq_kwargs: dict[str, Any] = {
                        "profile": request.profile,
                        "custom_options": request.custom_options,
                        "execution_binding": context.execution_binding,
                    }
                    if context.cancellation_token is not None:
                        seq_kwargs["cancellation_token"] = context.cancellation_token

                    t0 = time.perf_counter_ns()
                    page_data, prov, _, page_warnings = self._engine.ocr_page(
                        img,
                        page_idx,
                        inp.input_id,
                        **seq_kwargs,
                    )
                    dur = max(0, time.perf_counter_ns() - t0)
                    self._record_page_telemetry(
                        context=context,
                        inp_ref=inp,
                        page_idx=page_idx,
                        page_data=page_data,
                        dur_ns=dur,
                        binding=context.execution_binding,
                        worker_id="1",
                    )
                    doc_page_results[inp.input_id].append((page_idx, page_data, prov, page_warnings))

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

            if len(pages) > 1:
                page_sections = []
                for p in pages:
                    heading = f"--- Page {p.page_number} ---"
                    if p.text:
                        page_sections.append(f"{heading}\n{p.text}")
                    else:
                        page_sections.append(heading)
                full_text = "\n\n".join(page_sections)
            else:
                full_text = "\n\n".join(p.text for p in pages if p.text)

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

        scores: list[float] = [
            float(p.metadata["confidence"])
            for p in ocr_pages
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

        overall_confidence: ConfidenceValue | None = (
            ConfidenceValue(
                score=round(sum(scores) / len(scores), 4),
                method="rapidocr_mean",
                evidence=evidence_dict,
            )
            if (scores and ocr_pages and len(scores) == len(ocr_pages))
            else None
        )

        metadata: dict[str, Any] = {
            "ocr_coverage": {
                "total_pages": len(ocr_pages),
                "unaltered_rapidocr_pages": len(scores),
            }
        }

        # Construct confirmed artifact payloads for extracted text and structured JSON
        payloads: list[ArtifactPayload] = []
        for idx, (inp, doc) in enumerate(zip(request.inputs, final_docs)):
            txt_name = format_artifact_filename(inp, "ocr", "txt", all_inputs=request.inputs, index=idx)
            json_name = format_artifact_filename(inp, "ocr", "json", all_inputs=request.inputs, index=idx)
            docx_name = format_artifact_filename(inp, "ocr", "docx", all_inputs=request.inputs, index=idx)

            # 1. Plain text extracted output
            payloads.append(
                ArtifactPayload(
                    intent=ArtifactIntent(
                        name=txt_name,
                        role="extracted_text",
                        media_type="text/plain",
                    ),
                    content=(doc.text or "").encode("utf-8"),
                )
            )

            # 2. Structured JSON output
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
                        "spans": [
                            {
                                "text": s.text,
                                "bounding_box": list(s.bounding_box) if s.bounding_box else None,
                                "confidence": s.confidence,
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
