"""Roopa Font Conversion Executable Capability for Sarathi V2."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ExecutionContext,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    TextSpan,
    WarningRecord,
)
from sarathi.sankalpa.document import transform_canonical_document
from sarathi.shakti.docx_exporter import build_docx_payload, transform_docx_artifact
from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import (
    LegacyFontDetector,
    decide_run_profile,
    rank_profiles_from_text,
    resolve_profile_from_font_name,
)
from sarathi.shakti.font_conversion.models import (
    ConversionMetrics,
)
from sarathi.shakti.font_conversion.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.font_conversion.protector import TextProtector
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
                stitched[-1] = TextSpan(
                    text=merged_text,
                    confidence=min(prev.confidence or 1.0, s.confidence or 1.0),
                    bounding_box=prev.bounding_box,
                    language=prev.language,
                    script=prev.script,
                    metadata=merged_meta,
                )
                continue
        stitched.append(s)
    return tuple(stitched)


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
        self._detector = LegacyFontDetector(fonts_dir=self._fonts_dir)
        self._protector = TextProtector()
        self._converter = FontConverter(fonts_dir=self._fonts_dir, anubhava_path=anubhava_path)
        self._validator = FontConversionValidator()

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute font conversion on the request inputs or prior CanonicalDocument(s)."""
        if prior_result is None or prior_result.data is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="FontConversionCapability requires a prior Result containing a CanonicalDocument or tuple of documents.",
            )

        docs: list[CanonicalDocument]
        is_batch = False
        if isinstance(prior_result.data, CanonicalDocument):
            docs = [prior_result.data]
        elif isinstance(prior_result.data, (tuple, list)) and all(
            isinstance(d, CanonicalDocument) for d in prior_result.data
        ):
            docs = list(prior_result.data)
            is_batch = True
        else:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="FontConversionCapability requires a prior Result containing a CanonicalDocument or tuple of documents.",
            )

        if not docs:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="No CanonicalDocument provided to FontConversionCapability.",
            )

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

        for idx, doc in enumerate(docs):
            if _is_doc_empty(doc):
                # Preserve empty document and record classified warning without failing entire batch
                converted_docs.append(doc)
                all_warnings.append(
                    WarningRecord(
                        code="EMPTY_DOCUMENT_SKIPPED",
                        message=f"Document '{doc.document_id}' is empty; skipped font conversion.",
                        stage="font_conversion",
                    )
                )
                continue

            full_text = doc.text
            if not full_text.strip() and doc.tables:
                table_lines = []
                for t in doc.tables:
                    if t.headers:
                        table_lines.append(" ".join(str(c) for c in t.headers))
                    for r in t.rows:
                        table_lines.append(" ".join(str(c) for c in r))
                full_text = "\n".join(table_lines)
            if not full_text.strip() and doc.pages:
                full_text = "\n".join(p.text for p in doc.pages if p.text)

            scope = (
                self._darpana.time_scope(
                    context=context, phase_name="font_conversion", component="shakti.font_conversion"
                )
                if self._darpana
                else nullcontext()
            )
            with scope:
                # 1. Detect legacy font profile
                font_hint = request.metadata.get("font") if request.metadata else None
                detected_profile, conf = self._detector.detect(
                    full_text, font_hint=str(font_hint) if font_hint else None
                )

                target_mode = (
                    request.custom_options.get("font_mode", "auto_unicode")
                    if request.custom_options
                    else "auto_unicode"
                )

                valid_modes = frozenset({"auto_unicode", "auto", "to_krutidev", "to_devlys"})
                if target_mode not in valid_modes:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Unsupported or invalid font_mode '{target_mode}'. Allowed modes: {sorted(valid_modes)}.",
                    )

                is_to_legacy = target_mode in ("to_krutidev", "to_devlys")
                target_profile = (
                    ("krutidev010" if target_mode == "to_krutidev" else "devlys010")
                    if is_to_legacy
                    else (detected_profile or "krutidev010")
                )

                # Legacy-to-legacy validation: only reject if neither explicit font alias nor text margin >= 1.0
                if is_to_legacy and self._detector.is_legacy_text(full_text):
                    if not detected_profile:
                        candidates = rank_profiles_from_text(full_text, self._detector._profiles)
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
                    # Check if any span or table has legacy font hint
                    has_any_legacy_span = any(
                        s.metadata.get("font_name") and resolve_profile_from_font_name(s.metadata.get("font_name"), self._detector._profiles)[0]
                        for p in doc.pages for s in p.spans
                    )
                    if not has_any_legacy_span:
                        converted_docs.append(doc)
                        all_warnings.append(
                            WarningRecord(
                                code="NO_LEGACY_FONT_DETECTED",
                                message=f"No legacy font encoding detected in document '{doc.document_id}'.",
                                stage="font_conversion",
                            )
                        )
                        continue

                total_spans_count = 0
                metrics = ConversionMetrics()
                profiles_used: set[str] = set()

                def _conv_text(raw: str, font_name: str | None = None) -> str:
                    nonlocal total_spans_count
                    if not raw or not raw.strip():
                        return raw

                    # If multiple paragraphs/lines exist in raw unlabelled text, convert line by line
                    if font_name is None and "\n" in raw:
                        return "\n".join(_conv_text(line, font_name=None) for line in raw.split("\n"))

                    if is_to_legacy:
                        active_profile = target_profile
                        metrics.runs_scanned += 1
                        metrics.runs_converted += 1
                        profiles_used.add(active_profile)
                        if detected_profile and detected_profile != target_profile:
                            inter = self._converter.convert(raw, profile_id=detected_profile)
                        else:
                            inter = raw
                        return self._converter.convert_to_legacy(inter, target_profile_id=active_profile)

                    # Eliminate document-level profile leakage
                    decision = decide_run_profile(
                        run_font=font_name,
                        run_text=raw,
                        doc_profile=detected_profile,
                        profiles=self._detector._profiles,
                    )
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
                        is_struct_valid, defects = self._validator.validate_devanagari_structure(restored)
                        if not is_struct_valid:
                            metrics.structural_failures += 1
                            raise DoshError(
                                code=FailureCode.VALIDATION_FAILED,
                                message=f"Converted text has structural Devanagari defect(s): {', '.join(defects)}",
                            )
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
                converted_docs.append(converted_doc)
                final_text = converted_doc.text

                prov = ProvenanceRecord(
                    source_input_id=doc.source_input_id,
                    capability_id="font_conversion",
                    stage="font_conversion",
                    evidence={
                        "profile_id": detected_profile,
                        "profiles_used": sorted(profiles_used),
                        "confidence": conf,
                        "protected_spans_count": total_spans_count,
                        "runs_scanned": metrics.runs_scanned,
                        "runs_converted": metrics.runs_converted,
                        "runs_preserved": metrics.runs_preserved,
                        "runs_ambiguous": metrics.runs_ambiguous,
                    },
                )
                all_provs.append(prov)

                txt_artifact_name = (
                    "Converted_Document.txt"
                    if len(docs) == 1
                    else f"Converted_{doc.source_input_id or doc.document_id}.txt"
                )
                payloads.append(
                    ArtifactPayload(
                        intent=ArtifactIntent(name=txt_artifact_name, role="converted_text", media_type="text/plain"),
                        content=final_text.encode("utf-8"),
                    )
                )

                docx_artifact_name = (
                    "Converted_Document.docx"
                    if len(docs) == 1
                    else f"Converted_{doc.source_input_id or doc.document_id}.docx"
                )

                # Deterministic source association (no positional fallback!)
                docx_payload: ArtifactPayload | None = None
                matching_inp = next((i for i in request.inputs if i.input_id == doc.source_input_id), None)

                if (
                    matching_inp is not None
                    and matching_inp.source_path is not None
                    and matching_inp.source_path.suffix.lower() == ".docx"
                    and matching_inp.source_path.is_file()
                ):
                    raw_docx_bytes = matching_inp.source_path.read_bytes()
                    docx_payload = transform_docx_artifact(
                        input_bytes=raw_docx_bytes,
                        converter_fn=_conv_text,
                        filename=docx_artifact_name,
                        role="converted_document",
                        warnings=all_warnings,
                        preserve_typography=True,
                    )
                else:
                    docx_payload = build_docx_payload(
                        doc=converted_doc,
                        filename=docx_artifact_name,
                        role="converted_document",
                    )

                payloads.append(docx_payload)

        final_data = tuple(converted_docs) if is_batch else converted_docs[0]
        return Result(
            data=final_data,
            artifact_payloads=tuple(payloads),
            provenance=tuple(all_provs),
            warnings=tuple(all_warnings),
        )
