"""Roopa Font Conversion Executable Capability for Sarathi."""

from __future__ import annotations

import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ConfidenceValue,
    ExecutionContext,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    TextSpan,
    WarningRecord,
)
from sarathi.sankalpa.document import normalize_canonical_documents, transform_canonical_document
from sarathi.shakti.artifact_naming import format_artifact_filename
from sarathi.shakti.docx_exporter import build_docx_payload, transform_docx_artifact
from sarathi.shakti.font_conversion.converter import _CANONICAL_ANUBHAVA_PATH, FontConverter
from sarathi.shakti.font_conversion.detector import (
    LegacyFontDetector,
    decide_run_profile,
    load_font_profiles,
    rank_profiles_from_text,
    resolve_profile_from_font_name,
)
from sarathi.shakti.font_conversion.models import (
    ConversionDecision,
    ConversionMetrics,
    ConversionPlan,
    ConvertedDocumentResult,
)
from sarathi.shakti.font_conversion.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.font_conversion.protector import TextProtector
from sarathi.shakti.font_conversion.telemetry import emit_conversion_telemetry
from sarathi.shakti.font_conversion.validator import FontConversionValidator
from sarathi.sutra import get_canonical_data_root

_CANONICAL_FONTS_DIR = get_canonical_data_root() / "fonts"


def _stitch_compatible_page_spans(spans: tuple[TextSpan, ...] | list[TextSpan]) -> tuple[TextSpan, ...]:
    """Merge adjacent compatible runs within each paragraph to resolve cross-run split Aksharas."""
    if not spans:
        return ()
    stitched: list[TextSpan] = []
    for s in spans:
        if not isinstance(s, TextSpan) or not s.text:
            continue
        s_font = s.metadata.get("font_name") if s.metadata else None
        s_p_idx = s.metadata.get("paragraph_index") if s.metadata else None
        if stitched:
            prev = stitched[-1]
            prev_font = prev.metadata.get("font_name") if prev.metadata else None
            prev_p_idx = prev.metadata.get("paragraph_index") if prev.metadata else None
            if s_font == prev_font and (s_p_idx is None or s_p_idx == prev_p_idx):
                merged_text = prev.text + s.text
                merged_meta = dict(prev.metadata) if prev.metadata else {}
                c_prev = prev.confidence
                c_s = s.confidence
                merged_conf = None if (c_prev is None or c_s is None) else min(c_prev, c_s)
                stitched[-1] = TextSpan(
                    text=merged_text,
                    confidence=merged_conf,
                    bounding_box=prev.bounding_box,
                    language=prev.language,
                    script=prev.script,
                    metadata=merged_meta,
                )
                continue
        stitched.append(s)
    return tuple(stitched)


def _extract_doc_text(d: CanonicalDocument) -> str:
    if d.text.strip():
        return d.text
    if d.tables:
        lines = [" ".join(str(c) for c in t.headers) for t in d.tables if t.headers]
        lines.extend(" ".join(str(c) for c in r) for t in d.tables for r in t.rows)
        return "\n".join(lines)
    return "\n".join(p.text for p in d.pages if p.text) if d.pages else ""


class FontConversionCapability:
    """Executable capability for legacy font to Unicode conversion."""

    def __init__(
        self,
        darpana: Darpana | None = None,
        fonts_dir: Path | None = None,
        anubhava_path: Path | None = None,
    ) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._fonts_dir = fonts_dir.resolve() if fonts_dir is not None else _CANONICAL_FONTS_DIR
        self._profiles = load_font_profiles(self._fonts_dir)
        self._detector = LegacyFontDetector(fonts_dir=self._fonts_dir, profiles=self._profiles)
        self._protector = TextProtector()
        self._converter = FontConverter(fonts_dir=self._fonts_dir, anubhava_path=anubhava_path, profiles=self._profiles)
        self._validator = FontConversionValidator()
        self._anubhava_path = (anubhava_path or _CANONICAL_ANUBHAVA_PATH).resolve()
        self._asset_version = self._compute_asset_version()

    def _compute_asset_version(self) -> str:
        import hashlib

        hasher = hashlib.sha256()
        if self._fonts_dir.is_dir():
            try:
                for p in sorted(self._fonts_dir.glob("*.json")):
                    st = p.stat()
                    hasher.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode("utf-8"))
                    hasher.update(p.read_bytes())
            except OSError:
                pass
        if self._anubhava_path and self._anubhava_path.is_file():
            try:
                st = self._anubhava_path.stat()
                hasher.update(f"anubhava:{st.st_size}:{st.st_mtime_ns}".encode("utf-8"))
                hasher.update(self._anubhava_path.read_bytes())
            except OSError:
                pass
        return hasher.hexdigest()[:16]

    @property
    def asset_version(self) -> str:
        return self._asset_version

    def convert_document(
        self,
        doc: CanonicalDocument,
        font_hint: str | None = None,
        target_mode: str = "auto_unicode",
    ) -> ConvertedDocumentResult:
        """Convert a single CanonicalDocument preserving formatting, tables, and protected spans."""
        full_text = _extract_doc_text(doc)

        # 1. Detect legacy font profile
        detected_profile, conf = self._detector.detect(
            full_text, font_hint=str(font_hint) if font_hint else None
        )

        valid_modes = frozenset({"auto_unicode", "auto", "to_krutidev", "to_devlys"})
        if target_mode not in valid_modes:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Unsupported or invalid font_mode '{target_mode}'. Allowed modes: {sorted(valid_modes)}.",
            )

        is_to_legacy = target_mode in ("to_krutidev", "to_devlys")
        if not is_to_legacy and detected_profile is None and self._detector.is_legacy_text(full_text):
            cands = rank_profiles_from_text(full_text, self._profiles)
            if cands and cands[0].score >= 2.0:
                p0 = self._profiles.get(cands[0].profile_id)
                if p0 and p0.family in ("krutidev", "devlys"):
                    detected_profile = "krutidev010"
                    conf = min(1.0, 0.5 + len(cands[0].positive_signatures) * 0.1)

        target_profile = (
            ("krutidev010" if target_mode == "to_krutidev" else "devlys010")
            if is_to_legacy
            else (detected_profile or "krutidev010")
        )

        # Legacy-to-legacy validation: only reject if neither explicit font alias nor text margin >= 1.0
        if is_to_legacy and self._detector.is_legacy_text(full_text):
            if not detected_profile:
                candidates = rank_profiles_from_text(full_text, self._profiles)
                if not candidates or candidates[0].score < 2.0:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message="Ambiguous source legacy encoding for legacy-to-legacy conversion.",
                    )
                if len(candidates) > 1 and (candidates[0].score - candidates[1].score) < 1.0:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message="Ambiguous source legacy encoding for legacy-to-legacy conversion.",
                    )

        # If auto_unicode and no legacy detected, preserve original doc
        if not is_to_legacy and detected_profile is None:
            has_any_legacy_span = any(
                s.metadata.get("font_name") and resolve_profile_from_font_name(s.metadata.get("font_name"), self._profiles)[0]
                for p in doc.pages for s in p.spans
            )
            is_legacy_content = self._detector.is_legacy_text(full_text)
            if not has_any_legacy_span and not is_legacy_content:
                empty_plan = ConversionPlan(
                    document_id=doc.document_id,
                    source_input_id=doc.source_input_id,
                    profile_decisions=(),
                    overall_metrics=ConversionMetrics(),
                    accepted=True,
                )
                return ConvertedDocumentResult(
                    document=doc,
                    metrics=ConversionMetrics(),
                    plan=empty_plan,
                    detected_profile=None,
                    profiles_used=(),
                    confidence=None,
                    protected_spans_count=0,
                    warnings=(
                        WarningRecord(
                            code="NO_LEGACY_FONT_DETECTED",
                            message=f"No legacy font encoding detected in document '{doc.document_id}'.",
                            stage="font_conversion",
                        ),
                    ),
                )

        # Execute conversion across all pages and tables
        metrics = ConversionMetrics()
        decisions: list[ConversionDecision] = []
        profiles_used: set[str] = set()
        total_spans_count = 0
        text_conv_cache: dict[tuple[str, str | None], str] = {}
        doc_warnings: list[WarningRecord] = []

        def _conv_text(raw: str, font_name: str | None = None) -> str:
            nonlocal total_spans_count
            if not raw or not raw.strip():
                return raw

            cache_key = (raw, font_name)
            if cache_key in text_conv_cache:
                return text_conv_cache[cache_key]

            # If multiple paragraphs/lines exist in raw unlabelled text, convert line by line
            if font_name is None and "\n" in raw:
                res = "\n".join(_conv_text(line, font_name=None) for line in raw.split("\n"))
                text_conv_cache[cache_key] = res
                return res

            # If target is legacy and text contains Devanagari, convert directly from Unicode
            if is_to_legacy:
                has_dev = any("\u0900" <= c <= "\u097f" for c in raw)
                if has_dev:
                    active_profile = target_profile
                    metrics.runs_converted += 1
                    profiles_used.add(active_profile)
                    prot, c_spans = self._protector.protect(
                        raw,
                        protect_devanagari=False,
                        is_explicit_legacy=False,
                    )
                    total_spans_count += len(c_spans)
                    c_raw = self._converter.convert_to_legacy(prot, target_profile_id=active_profile)
                    restored = self._protector.restore(c_raw, c_spans)
                    text_conv_cache[cache_key] = restored
                    return restored

            # Eliminate document-level profile leakage
            decision = decide_run_profile(
                run_font=font_name,
                run_text=raw,
                doc_profile=detected_profile,
                profiles=self._profiles,
            )
            decisions.append(decision)
            metrics.runs_scanned += 1

            if decision.decision == "preserve":
                metrics.runs_preserved += 1
                return raw
            if decision.decision == "ambiguous":
                metrics.runs_ambiguous += 1
                return raw
            if decision.decision != "convert" or not decision.profile:
                metrics.runs_preserved += 1
                return raw

            active_profile = decision.profile
            metrics.runs_converted += 1
            profiles_used.add(active_profile)

            is_explicit_legacy = bool(font_name and decision.reason == "exact_source_font_alias")
            prot, c_spans = self._protector.protect(
                raw,
                protect_devanagari=not is_to_legacy,
                is_explicit_legacy=is_explicit_legacy,
            )
            total_spans_count += len(c_spans)

            if is_to_legacy:
                if active_profile is not None and active_profile != target_profile:
                    inter = self._converter.convert(prot, profile_id=active_profile)
                else:
                    inter = prot
                c_raw = self._converter.convert_to_legacy(inter, target_profile_id=target_profile)
            else:
                c_raw = self._converter.convert(prot, profile_id=active_profile)

            restored = self._protector.restore(c_raw, c_spans)
            if not is_to_legacy:
                if not self._validator.validate_protection_integrity(restored, c_spans):
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Protected span integrity validation failed during font conversion.",
                    )
                if is_explicit_legacy:
                    is_clean, _ = self._validator.validate_residual_legacy(restored, is_explicit_legacy=True)
                    if not is_clean:
                        metrics.residual_legacy_runs += 1
            text_conv_cache[cache_key] = restored
            return restored

        stitched_pages = []
        has_any_spans = any(bool(p.spans) for p in doc.pages)
        for p in doc.pages:
            if p.spans:
                stitched_spans = _stitch_compatible_page_spans(p.spans)
                stitched_pages.append(
                    PageData(
                        page_number=p.page_number,
                        text=p.text,
                        spans=stitched_spans,
                        tables=p.tables,
                        metadata=p.metadata,
                    )
                )
            else:
                stitched_pages.append(p)
        doc_to_transform = (
            CanonicalDocument(
                document_id=doc.document_id,
                source_input_id=doc.source_input_id,
                text=doc.text,
                pages=tuple(stitched_pages),
                tables=doc.tables,
                detected_type=doc.detected_type,
                metadata=doc.metadata,
            )
            if has_any_spans
            else doc
        )

        def _span_transform(span: TextSpan | str) -> TextSpan | str:
            if isinstance(span, TextSpan):
                f_name = span.metadata.get("font_name") if span.metadata else None
                conv_t = _conv_text(span.text, font_name=f_name)
                return TextSpan(
                    text=conv_t,
                    confidence=span.confidence,
                    bounding_box=span.bounding_box,
                    language="hi" if not is_to_legacy else doc.metadata.get("language"),
                    script="Deva" if not is_to_legacy else "Latn",
                    metadata=dict(span.metadata),
                )
            return _conv_text(span)

        target_doc_type = "legacy_font_document" if is_to_legacy else "unicode_document"
        converted_doc = transform_canonical_document(
            doc_to_transform,
            _conv_text,
            detected_type=target_doc_type,
            target_lang="hi" if not is_to_legacy else doc.metadata.get("language"),
            target_script="Deva" if not is_to_legacy else "Latn",
            span_transform_fn=_span_transform,
            reconstruct_text_from_spans=has_any_spans,
        )

        final_text = _extract_doc_text(converted_doc)

        # Document-level structural Devanagari validation
        if not is_to_legacy and metrics.runs_converted > 0 and final_text and final_text.strip():
            is_struct_valid, defects = self._validator.validate_devanagari_structure(final_text)
            if metrics.runs_ambiguous > 0:
                defects = [
                    d for d in defects
                    if not d.startswith("RESIDUAL_LEGACY_GLYPHS") and not d.startswith("RESIDUAL_UNMAPPED_DIGRAPH")
                ]
            if defects:
                metrics.structural_failures += 1
                doc_warnings.append(
                    WarningRecord(
                        code="DEVANAGARI_STRUCTURAL_DEFECT",
                        message=f"Converted text has structural Devanagari defect(s): {', '.join(defects)}",
                        stage="font_conversion",
                        context={"defects": tuple(defects), "document_id": doc.document_id},
                    )
                )

        if metrics.residual_legacy_runs > 0:
            doc_warnings.append(
                WarningRecord(
                    code="RESIDUAL_LEGACY_TEXT_DETECTED",
                    message=f"Detected {metrics.residual_legacy_runs} run(s) with residual legacy font signatures after conversion.",
                    stage="font_conversion",
                )
            )

        if metrics.runs_ambiguous > 0:
            doc_warnings.append(
                WarningRecord(
                    code="FONT_CONVERSION_AMBIGUOUS_PROFILE",
                    message=f"Detected {metrics.runs_ambiguous} ambiguous run(s) where legacy font encoding could not be distinguished with certainty; text preserved.",
                    stage="font_conversion",
                )
            )

        plan = ConversionPlan(
            document_id=doc.document_id,
            source_input_id=doc.source_input_id,
            profile_decisions=tuple(decisions),
            overall_metrics=metrics,
            accepted=True,
        )

        return ConvertedDocumentResult(
            document=converted_doc,
            metrics=metrics,
            plan=plan,
            detected_profile=detected_profile,
            profiles_used=tuple(sorted(profiles_used)),
            confidence=conf,
            protected_spans_count=total_spans_count,
            warnings=tuple(doc_warnings),
            converter_fn=_conv_text,
        )

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute font conversion on the request inputs or prior CanonicalDocument(s)."""
        msg_req = "FontConversionCapability requires a prior Result containing a CanonicalDocument or tuple of documents."
        if prior_result is None or prior_result.data is None:
            raise DoshError(code=FailureCode.VALIDATION_FAILED, message=msg_req)

        normalized_docs = normalize_canonical_documents(prior_result.data)
        if normalized_docs is None:
            raise DoshError(code=FailureCode.VALIDATION_FAILED, message=msg_req)
        docs = list(normalized_docs)
        is_batch = not isinstance(prior_result.data, CanonicalDocument)

        if not docs:
            raise DoshError(code=FailureCode.VALIDATION_FAILED, message="No CanonicalDocument provided to FontConversionCapability.")

        def _is_doc_empty(d: CanonicalDocument) -> bool:
            return (
                not d.text.strip()
                and not d.tables
                and not any(p.text.strip() or p.tables for p in d.pages)
            )

        # Item-scoped batch escalation: if all documents are completely empty, request OCR handoff
        if all(_is_doc_empty(d) for d in docs):
            return Result(data=prior_result.data, next_requirement="ocr", resume_self=True)

        converted_docs: list[CanonicalDocument] = []
        payloads: list[ArtifactPayload] = []
        all_provs: list[ProvenanceRecord] = list(prior_result.provenance)
        all_warnings: list[WarningRecord] = list(prior_result.warnings) if prior_result and prior_result.warnings else []

        progress_cb = None
        if request.custom_options and callable(request.custom_options.get("progress_callback")):
            progress_cb = request.custom_options["progress_callback"]

        for idx, doc in enumerate(docs):
            if _is_doc_empty(doc):
                converted_docs.append(doc)
                all_warnings.append(
                    WarningRecord(
                        code="EMPTY_DOCUMENT_SKIPPED",
                        message=f"Document '{doc.document_id}' is empty; skipped font conversion.",
                        stage="font_conversion",
                    )
                )
                continue

            if progress_cb is not None:
                dev_str = context.execution_binding.device_type.value.upper() if context.execution_binding else "CPU"
                tot_pages = len(doc.pages) if doc.pages else 1
                progress_cb(
                    file_display_name=doc.document_id,
                    page_number=1,
                    total_pages=tot_pages,
                    worker_id="1",
                    stage="Legacy Font Conversion",
                    device_type=dev_str,
                    input_id=doc.document_id,
                )

            try:
                scope = (
                    self._darpana.time_scope(
                        context=context, phase_name="font_conversion", component="shakti.font_conversion"
                    )
                    if self._darpana
                    else nullcontext()
                )
                with scope:
                    t_conv_start = time.perf_counter_ns()
                    opts, meta = request.custom_options or {}, request.metadata or {}
                    font_hint = opts.get("source_font") or opts.get("font") or meta.get("font")
                    target_mode = (
                        request.custom_options.get("font_mode", "auto_unicode")
                        if request.custom_options
                        else "auto_unicode"
                    )
                    is_to_legacy = target_mode in ("to_krutidev", "to_devlys")

                    res = self.convert_document(
                        doc=doc,
                        font_hint=str(font_hint) if font_hint else None,
                        target_mode=target_mode,
                    )
                    converted_doc = res.document
                    converted_docs.append(converted_doc)
                    all_warnings.extend(res.warnings)

                    prov = ProvenanceRecord(
                        source_input_id=doc.source_input_id,
                        capability_id="font_conversion",
                        stage="font_conversion",
                        evidence={
                            "profile_id": res.detected_profile,
                            "profiles_used": list(res.profiles_used),
                            "confidence": res.confidence,
                            "protected_spans_count": res.protected_spans_count,
                            "runs_scanned": res.metrics.runs_scanned,
                            "runs_converted": res.metrics.runs_converted,
                            "runs_preserved": res.metrics.runs_preserved,
                            "runs_ambiguous": res.metrics.runs_ambiguous,
                            "residual_legacy_runs": res.metrics.residual_legacy_runs,
                            "conversion_plan_accepted": res.plan.accepted,
                            "profile_decisions_count": len(res.plan.profile_decisions),
                        },
                    )
                    all_provs.append(prov)

                    # Deterministic source association (no positional fallback!)
                    matching_inp = next((i for i in request.inputs if i.input_id == doc.source_input_id), None)
                    naming_inp = matching_inp or InputRef(
                        input_id=doc.source_input_id or doc.document_id,
                        source_path=Path(f"{doc.document_id}.txt"),
                        display_name=doc.document_id,
                        size_bytes=0,
                    )

                    conv_dur_ns = max(0, time.perf_counter_ns() - t_conv_start)
                    emit_conversion_telemetry(self._darpana, context, converted_doc, naming_inp, res.confidence, dur_ns=conv_dur_ns)

                    txt_artifact_name = format_artifact_filename(
                        naming_inp,
                        "converted",
                        "txt",
                        all_inputs=request.inputs,
                        index=idx,
                    )
                    txt_content: str
                    if converted_doc.pages and len(converted_doc.pages) > 1:
                        page_texts = [
                            f"--- Page {p.page_number} ---\n{p.text}"
                            for p in converted_doc.pages
                        ]
                        txt_content = "\n\n".join(page_texts)
                    else:
                        txt_content = _extract_doc_text(converted_doc)

                    payloads.append(
                        ArtifactPayload(
                            intent=ArtifactIntent(name=txt_artifact_name, role="converted_text", media_type="text/plain"),
                            content=txt_content.encode("utf-8"),
                        )
                    )

                    docx_artifact_name = format_artifact_filename(
                        naming_inp,
                        "converted",
                        "docx",
                        all_inputs=request.inputs,
                        index=idx,
                    )

                    docx_payload: ArtifactPayload | None = None

                    legacy_target_font = (
                        ("Kruti Dev 010" if target_mode == "to_krutidev" else "DevLys 010")
                        if is_to_legacy
                        else None
                    )

                    if (
                        matching_inp is not None
                        and matching_inp.source_path is not None
                        and matching_inp.source_path.suffix.lower() == ".docx"
                        and matching_inp.source_path.is_file()
                    ):
                        raw_docx_bytes = matching_inp.source_path.read_bytes()
                        docx_payload = transform_docx_artifact(
                            input_bytes=raw_docx_bytes,
                            converter_fn=res.converter_fn or (lambda raw, font=None: raw),
                            filename=docx_artifact_name,
                            role="converted_document",
                            warnings=all_warnings,
                            preserve_typography=True,
                            legacy_target_font=legacy_target_font,
                            profiles=self._profiles,
                        )
                    else:
                        docx_payload = build_docx_payload(
                            doc=converted_doc,
                            filename=docx_artifact_name,
                            role="converted_document",
                            legacy_target_font=legacy_target_font,
                        )

                    payloads.append(docx_payload)

            except DoshError as doc_err:
                if not is_batch:
                    raise
                all_warnings.append(
                    WarningRecord(
                        code=f"FONT_CONVERSION_{doc_err.code.name}",
                        message=f"Document '{doc.document_id}' failed font conversion: {doc_err.message}",
                        stage="font_conversion",
                        context={"document_id": doc.document_id, "failure_code": doc_err.code.name},
                    )
                )
                new_meta = dict(doc.metadata) if doc.metadata else {}
                new_meta["conversion_status"] = "failed"
                new_meta["failure_code"] = doc_err.code.name
                failed_doc = replace(doc, metadata=new_meta)
                converted_docs.append(failed_doc)
                continue

        if is_batch and not payloads and converted_docs:
            first_fail = next((w for w in all_warnings if w.code.startswith("FONT_CONVERSION_")), None)
            if first_fail is not None:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=first_fail.message,
                )

        final_data = tuple(converted_docs) if is_batch else converted_docs[0]
        final_conf: ConfidenceValue | None = None
        if len(all_provs) == 1 and all_provs[0].evidence.get("confidence") is not None:
            c_score = float(all_provs[0].evidence["confidence"])
            if 0.0 < c_score <= 1.0 and all_provs[0].evidence.get("profile_id"):
                final_conf = ConfidenceValue(
                    score=round(c_score, 4),
                    method="legacy_font_heuristic",
                    evidence={
                        "score_kind": "heuristic",
                        "calibrated": False,
                        "profile_id": str(all_provs[0].evidence["profile_id"]),
                        "runs_converted": all_provs[0].evidence.get("runs_converted", 0),
                        "runs_scanned": all_provs[0].evidence.get("runs_scanned", 0),
                        "residual_legacy_runs": all_provs[0].evidence.get("residual_legacy_runs", 0),
                    },
                )

        return Result(
            data=final_data,
            artifact_payloads=tuple(payloads),
            provenance=tuple(all_provs),
            warnings=tuple(all_warnings),
            confidence=final_conf,
        )
