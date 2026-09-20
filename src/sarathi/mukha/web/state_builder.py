"""Mukha Web Presentation State Builder for Sarathi.

Projects canonical runtime facts, telemetry records, and runner progress into
typed view contracts for the interactive Web UI.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import (
    ActionParameterView,
    ApplicationViewState,
    AvailableActionView,
    FileRunView,
    InputItemView,
    InputSelectionView,
    InspectorViewState,
    ReviewItemView,
    WorkerPageView,
)
from sarathi.sankalpa import ExecutionProfile, Result

if TYPE_CHECKING:
    from sarathi.agni import Agni
    from sarathi.darpana import MarutiRecord, PramanaRecord
    from sarathi.mukha.web.runner import RunCoordinator


def get_run_telemetry(
    agni: Agni,
    run_id: str,
) -> tuple[tuple[MarutiRecord, ...], tuple[PramanaRecord, ...]]:
    """Fetch telemetry records filtered strictly to the active run ID."""
    if not hasattr(agni, "darpana") or not agni.darpana:
        return (), ()
    maruti = tuple(r for r in agni.darpana.maruti_records() if r.run_id == run_id or r.request_id == run_id)
    pramana = tuple(r for r in agni.darpana.pramana_records() if r.run_id == run_id or r.request_id == run_id)
    return maruti, pramana


def query_run_history(agni: Agni, limit: int = 50) -> tuple[Any, ...]:
    """Retrieve recent terminal run summaries from Darpana telemetry history, mapped to canonical view schema."""
    if hasattr(agni, "darpana") and agni.darpana is not None:
        records = agni.darpana.query_run_history(limit=limit)
        projected = []
        for h in records:
            stat = getattr(h, "status", "completed")
            stat_upper = stat.upper() if isinstance(stat, str) else "COMPLETED"
            stat_mapped = "SUCCESS" if stat_upper == "COMPLETED" else stat_upper
            dur_ms = getattr(h, "duration_ms", 0) or 0
            art_cnt = getattr(h, "artifact_count", 0) or 0
            t_inputs = getattr(h, "input_count", None)
            if t_inputs is None:
                out_dir = getattr(h, "output_dir", None)
                if out_dir and hasattr(agni, "output_root"):
                    manifest_path = agni.output_root / out_dir / "run-manifest.json"
                    if manifest_path.is_file():
                        try:
                            with open(manifest_path, "r", encoding="utf-8") as f:
                                mdata = json.load(f)
                            prov = mdata.get("provenance", [])
                            distinct = {
                                p.get("source_input_id")
                                for p in prov
                                if isinstance(p, dict) and p.get("source_input_id")
                            }
                            if distinct:
                                t_inputs = len(distinct)
                            elif mdata.get("total_inputs"):
                                t_inputs = int(mdata["total_inputs"])
                        except Exception:
                            pass
            if t_inputs is None:
                t_inputs = art_cnt or 1
            projected.append(
                {
                    "run_id": getattr(h, "run_id", ""),
                    "request_id": getattr(h, "request_id", ""),
                    "requirement": getattr(h, "requirement", ""),
                    "profile": getattr(h, "profile", ""),
                    "status": stat_mapped,
                    "start_time_utc": getattr(h, "start_time_utc", ""),
                    "completed_at_utc": getattr(h, "completed_at_utc", ""),
                    "duration_ms": dur_ms,
                    "wall_time_ns": dur_ms * 1_000_000,
                    "artifact_count": art_cnt,
                    "total_inputs": t_inputs,
                    "warning_count": getattr(h, "warning_count", 0) or 0,
                    "output_dir": getattr(h, "output_dir", None),
                }
            )
        return tuple(projected)
    return ()


NON_REVIEWABLE_WARNING_CODES: frozenset[str] = frozenset(
    {
        # OCR engine & fallback infrastructure
        "OCR_FALLBACK_UNAVAILABLE",
        "OCR_FALLBACK_FAILED",
        "OCR_FALLBACK_CONFIDENCE_UNAVAILABLE",
        "OCR_METADATA_LENGTH_MISMATCH",
        "OCR_INVALID_CONFIDENCE",
        "OCR_INVALID_GEOMETRY",
        "OCR_EMPTY_INPUT",
        "OCR_EMPTY_PAGE",
        # Native extraction & layout pipeline infrastructure
        "CALAMINE_FALLBACK",
        "CALAMINE_XLS_FALLBACK",
        "LAYOUT_PACKAGE_UNAVAILABLE",
        "LAYOUT_ANALYSIS_FAILED",
        "LAYOUT_ANALYSIS_DEGRADED",
        "PDF_RICH_SPAN_EXTRACTION_DEGRADED",
        "PDF_TABLE_DETECTION_SKIPPED",
        "DOCX_PART_CONVERSION_FAILED",
        "EXCEL_FILTER_CHECK_SKIPPED",
        "EXCEL_FILTER_APPLIED",
        "EXPERIMENTAL_STAMP_REMOVAL",
        "NATIVE_EXTRACTION_EMPTY",
        "NATIVE_PARSE_ERROR",
        # Font & lifecycle transitions
        "LEGACY_FONT_DETECTED",
        "NO_LEGACY_FONT_DETECTED",
        "EMPTY_DOCUMENT_SKIPPED",
        "EMPTY_INPUT",
        # Hardware & execution state
        "DEVICE_FALLBACK",
        "DEVICES_UNAVAILABLE",
        "HARDWARE_ALLOCATION_FAILED",
        "CANCELLED",
        "RUN_CANCELLED",
    }
)


def is_reviewable_warning(w: Any) -> bool:
    """Determine whether a WarningRecord represents a human review item rather than an operational notice."""
    if not hasattr(w, "code"):
        return False
    code = str(w.code).upper().strip()
    if code in NON_REVIEWABLE_WARNING_CODES:
        return False
    if any(
        code.endswith(suffix)
        for suffix in (
            "_UNAVAILABLE",
            "_FAILED",
            "_DEGRADED",
            "_SKIPPED",
            "_MISMATCH",
            "_ALLOCATION_FAILED",
        )
    ):
        return False
    ctx = getattr(w, "context", None)
    if isinstance(ctx, (dict, Mapping)):
        if ctx.get("is_operational") is True:
            return False
        if ctx.get("is_review_item") is True or ctx.get("review") is True:
            return True
    return True


def get_reviewable_warnings(res: Result | None) -> list[tuple[int, Any]]:
    """Return filtered (original_1_based_index, WarningRecord) pairs that represent actionable human review items."""
    if res is None or not getattr(res, "warnings", None):
        return []
    return [(idx, w) for idx, w in enumerate(res.warnings, start=1) if is_reviewable_warning(w)]


def extract_review_items(runner: RunCoordinator, run_id: str | None = None) -> tuple[dict[str, Any], ...]:
    """Retrieve pending review/exception items from run result warnings enriched with applied decisions."""
    active_or_last_run_id = getattr(runner, "_last_result_run_id", None)
    if not active_or_last_run_id and runner.terminal_summary:
        active_or_last_run_id = runner.terminal_summary.run_id
    if not active_or_last_run_id and hasattr(runner, "_active_run_id"):
        active_or_last_run_id = runner._active_run_id

    if run_id and active_or_last_run_id and run_id != active_or_last_run_id:
        return ()

    res = runner.last_result
    if res is None or not res.warnings:
        return ()
    reviewable = get_reviewable_warnings(res)
    if not reviewable:
        return ()

    intents = runner.get_review_intents() if hasattr(runner, "get_review_intents") else {}
    items = []
    for r_idx, (orig_idx, w) in enumerate(reviewable, start=1):
        item_id = f"rev-{r_idx}"
        intent = intents.get(item_id) or intents.get(f"rev-{orig_idx}")
        if (
            intent is not None
            and getattr(intent, "run_id", None)
            and active_or_last_run_id
            and intent.run_id != active_or_last_run_id
        ):
            intent = None
        ctx = dict(w.context) if w.context else {}
        status = "pending"
        applied_action = None
        draft_proposal = None
        if intent is not None:
            applied_action = intent.action_id
            if intent.action_id == "accept":
                status = "accepted"
            elif intent.action_id == "unresolved":
                status = "unresolved"
            else:
                status = "pending"
            if intent.proposed_value:
                draft_proposal = intent.proposed_value

        attempt_id = (
            getattr(w, "span_id", "")
            or (ctx.get("attempt_id", "") if ctx else "")
            or f"att-{active_or_last_run_id or 'run'}-{r_idx}"
        )

        items.append(
            {
                "item_id": item_id,
                "attempt_id": attempt_id,
                "code": w.code,
                "message": w.message,
                "stage": w.stage,
                "status": status,
                "applied_action": applied_action,
                "draft_proposal": draft_proposal,
                "context": ctx,
                "available_actions": ("accept", "unresolved"),
            }
        )
    return tuple(items)


def build_inspector_view(
    agni: Agni,
    runner: RunCoordinator,
    run_id: str,
    host: str,
    port: int,
) -> InspectorViewState | None:
    """Build InspectorViewState for the requested run ID from recorded facts."""
    snapshot = runner.get_active_snapshot()
    is_active = snapshot.run_id == run_id
    term_status = snapshot.terminal_status
    is_alive = snapshot.is_alive
    start_ns = snapshot.start_ns if is_active else 0

    hist_summary = runner.get_run_summary(run_id)
    if hist_summary is None and hasattr(agni, "darpana") and agni.darpana is not None:
        hist_summary = agni.darpana.get_run_summary(run_id)

    maruti_recs, pramana_recs = get_run_telemetry(agni, run_id)
    if not maruti_recs and not pramana_recs and not is_active and hist_summary is None:
        return None

    if is_active:
        status = "RUNNING" if is_alive else (term_status or "COMPLETED")
        now_ns = time.perf_counter_ns()
        elapsed_ns = max(0, now_ns - start_ns) if start_ns > 0 else 0
    else:
        if hist_summary is not None:
            raw_s = getattr(hist_summary, "status", "COMPLETED")
            status = raw_s.upper() if isinstance(raw_s, str) else "COMPLETED"
            if status == "COMPLETED":
                status = "SUCCESS"
            dur_ms = getattr(hist_summary, "duration_ms", 0)
            wall_ns = getattr(hist_summary, "wall_time_ns", 0)
            if wall_ns and wall_ns > 0:
                elapsed_ns = int(wall_ns)
            elif dur_ms and dur_ms > 0:
                elapsed_ns = int(dur_ms) * 1_000_000
            else:
                elapsed_ns = 0
        else:
            status = "COMPLETED"
            elapsed_ns = 0

    system_facts = (
        ("Loopback Host", host),
        ("Port", str(port)),
        ("Runtime Root", str(agni.runtime_root)),
        ("Output Root", str(agni.output_root)),
    )

    return MukhaPresenter.build_inspector_view(
        run_id=run_id,
        status=status,
        elapsed_ns=elapsed_ns,
        maruti_records=maruti_recs,
        pramana_records=pramana_recs,
        system_facts=system_facts,
        live_workers=snapshot.live_workers if is_active else None,
    )


def _build_action_parameters(act_id: str, decl: Any = None) -> tuple[ActionParameterView, ...]:
    """Provide declarative configuration parameters for each capability derived from contracts."""
    if act_id == "ocr":
        if decl is not None and hasattr(decl, "supported_profiles") and decl.supported_profiles:
            prof_labels = {
                ExecutionProfile.INSTANT: "Instant (Highest Throughput)",
                ExecutionProfile.ACCURATE: "Accurate (Quality Verification)",
                ExecutionProfile.LAYOUT_PRESERVING: "Layout Preserving (Spatial Coordinates)",
                ExecutionProfile.CUSTOM: "Custom Configuration",
            }
            prof_opts = tuple(
                (p.value, prof_labels.get(p, p.value.replace("_", " ").title())) for p in decl.supported_profiles
            )
        else:
            prof_opts = (
                ("instant", "Instant (Highest Throughput)"),
                ("accurate", "Accurate (Quality Verification)"),
                ("layout_preserving", "Layout Preserving (Spatial Coordinates)"),
                ("custom", "Custom Configuration"),
            )
        return (
            ActionParameterView(
                parameter_id="profile",
                display_name="Execution Profile",
                kind="select",
                default_value="instant",
                options=prof_opts,
            ),
            ActionParameterView(
                parameter_id="lang",
                display_name="OCR Model & Language",
                kind="select",
                default_value="devanagari",
                options=(
                    ("devanagari", "Hindi / Devanagari + English (PP-OCRv5 Mobile)"),
                    ("en_v6", "English / Latin (PP-OCRv6 Small)"),
                    ("en", "English / Latin (PP-OCRv5 Mobile)"),
                ),
            ),
            ActionParameterView(
                parameter_id="preprocess",
                display_name="Preprocessing",
                kind="toggle",
                default_value=True,
                description="Adaptive grayscale and deskew preparation",
            ),
            ActionParameterView(
                parameter_id="deskew",
                display_name="Auto-Deskew",
                kind="toggle",
                default_value=True,
                description="Orientation and skew correction",
            ),
            ActionParameterView(
                parameter_id="clahe",
                display_name="CLAHE Contrast",
                kind="toggle",
                default_value=False,
                description="Adaptive histogram equalization",
            ),
            ActionParameterView(
                parameter_id="binarize",
                display_name="Binarization",
                kind="toggle",
                default_value=False,
                description="Otsu binarization filter",
            ),
            ActionParameterView(
                parameter_id="fallback_enabled",
                display_name="Fallback (NE-OCR)",
                kind="toggle",
                default_value=True,
                description="ONNX secondary fallback engine",
            ),
            ActionParameterView(
                parameter_id="validation_enabled",
                display_name="Validation Gate",
                kind="toggle",
                default_value=True,
                description="Pramana confidence verification",
            ),
            ActionParameterView(
                parameter_id="export_json",
                display_name="Export Structured JSON",
                kind="toggle",
                default_value=False,
                description="Emit machine-readable coordinate JSON (ocr.json)",
            ),
        )
    if act_id == "font_conversion":
        supported_fonts = (
            decl.metadata.get("supported_fonts") if decl is not None and getattr(decl, "metadata", None) else None
        )
        if supported_fonts:
            source_font_options = (("", "Auto-Detect Source Font"),) + tuple(supported_fonts)
        else:
            source_font_options = (
                ("", "Auto-Detect Source Font"),
                ("krutidev010", "KrutiDev 010 / DevLys"),
                ("chanakya010", "Chanakya"),
                ("shusha010", "Shusha"),
                ("shivaji010", "Shivaji"),
            )
        return (
            ActionParameterView(
                parameter_id="source_font",
                display_name="Source Font Hint",
                kind="select",
                default_value="",
                options=source_font_options,
            ),
            ActionParameterView(
                parameter_id="font_mode",
                display_name="Conversion Target",
                kind="select",
                default_value="auto_unicode",
                options=(
                    ("auto_unicode", "Auto-Detect & Convert to Unicode"),
                    ("to_krutidev", "Convert to KrutiDev"),
                    ("to_devlys", "Convert to DevLys"),
                ),
            ),
        )
    if act_id == "read_native":
        return (
            ActionParameterView(
                parameter_id="statutory",
                display_name="Statutory & Legal Extraction",
                kind="toggle",
                default_value=True,
                description="Automatically extract and verify GSTIN, PAN, TAN, CIN, and CNR identifiers",
            ),
        )
    if act_id == "translation":
        return (
            ActionParameterView(
                parameter_id="direction",
                display_name="Translation Direction",
                kind="select",
                default_value="",
                options=(
                    ("", "Auto-Detect Language Direction"),
                    ("hi_en", "Hindi → English"),
                    ("en_hi", "English → Hindi"),
                ),
            ),
            ActionParameterView(
                parameter_id="engine",
                display_name="Translation Engine",
                kind="select",
                default_value="indictrans2",
                options=(
                    ("indictrans2", "IndicTrans2 (Local CTranslate2)"),
                    ("opus_mt", "OPUS-MT (Local Marian CTranslate2)"),
                ),
                description="Local neural translation engine",
            ),
        )
    return ()


def build_application_view_state(
    agni: Agni,
    runner: RunCoordinator,
    host: str,
    port: int,
) -> ApplicationViewState:
    """Build canonical typed ApplicationViewState projected from live facts."""
    snapshot = runner.get_active_snapshot()
    active_run_id = snapshot.run_id
    active_req = snapshot.request
    start_ns = snapshot.start_ns
    last_summary = snapshot.terminal_summary
    term_status = snapshot.terminal_status
    is_alive = snapshot.is_alive

    active_run_view = None
    if active_run_id is not None:
        now_ns = time.perf_counter_ns()
        status = "RUNNING" if is_alive else (term_status or "SUCCESS")
        maruti_recs, pramana_recs = get_run_telemetry(agni, active_run_id)

        if active_req:
            req_decl = agni.kosh.get_capability(active_req.requirement)
            active_stage = req_decl.display_name if req_decl is not None else active_req.requirement
        else:
            active_stage = "Processing"

        live_prog = snapshot.live_progress
        live_workers = snapshot.live_workers
        file_prog_map = snapshot.file_progress

        curr_page = live_prog.get("page_number")
        tot_pages = live_prog.get("total_pages")
        curr_file = live_prog.get("file_display_name")
        curr_input_id = live_prog.get("input_id")

        inputs = active_req.inputs if active_req else ()
        files_list = []
        for idx, inp in enumerate(inputs):
            f_prog = file_prog_map.get(inp.input_id) or file_prog_map.get(inp.display_name)
            is_curr = bool(
                (curr_input_id and inp.input_id == curr_input_id)
                or (curr_file and (inp.display_name == curr_file or inp.input_id == curr_file))
            )
            f_warn_count = f_prog.get("warning_count", 0) if f_prog else 0

            if is_alive:
                if is_curr:
                    f_status = "RUNNING"
                    f_start = f_prog.get("started_ns", start_ns) if f_prog else start_ns
                    f_elapsed: int | None = max(0, now_ns - f_start)
                    if curr_page and tot_pages:
                        f_stage = f"{active_stage} (Page {curr_page}/{tot_pages})"
                    elif curr_page:
                        f_stage = f"{active_stage} (Page {curr_page})"
                    else:
                        f_stage = active_stage
                elif f_prog:
                    f_status = f_prog.get("status", "SUCCESS")
                    f_stage = f_prog.get("stage", "Completed")
                    f_dur = f_prog.get("duration_ns")
                    if f_dur is not None:
                        f_elapsed = f_dur
                    else:
                        f_start = f_prog.get("started_ns", start_ns)
                        f_elapsed = max(0, f_prog.get("updated_ns", now_ns) - f_start)
                else:
                    f_status = "PENDING"
                    f_stage = "Pending"
                    f_elapsed = None
            else:
                f_prog_status = f_prog.get("status") if f_prog else None
                if f_prog_status in ("SUCCESS", "WARNING", "FAILED", "CANCELLED"):
                    f_status = f_prog_status
                    f_stage = f_prog.get("stage", "Completed")
                    f_elapsed = f_prog.get("duration_ns")
                elif status in ("SUCCESS", "WARNING"):
                    f_status = "WARNING" if f_warn_count > 0 else "SUCCESS"
                    f_stage = "Completed"
                    f_elapsed = f_prog.get("duration_ns") if f_prog else None
                elif status == "CANCELLED":
                    f_status = "CANCELLED"
                    f_stage = "Cancelled"
                    f_elapsed = f_prog.get("duration_ns") if f_prog else None
                else:
                    f_status = "FAILED"
                    f_stage = "Failed"
                    f_elapsed = f_prog.get("duration_ns") if f_prog else None

            f_cached = bool(f_prog.get("cached")) if f_prog else False
            if not f_cached and maruti_recs:
                f_cached = any(
                    r.phase_name == "cache.lookup" and r.attributes.get("outcome") == "hit" for r in maruti_recs
                )

            files_list.append(
                FileRunView(
                    input_id=inp.input_id,
                    display_name=inp.display_name,
                    ordinal=idx + 1,
                    status=f_status,
                    elapsed_ns=f_elapsed,
                    current_stage=f_stage,
                    warning_count=f_warn_count,
                    cached=f_cached,
                )
            )
        files = tuple(files_list)

        if is_alive and inputs and live_workers:
            workers_list = []
            for wid, winfo in sorted(live_workers.items(), key=lambda kv: kv[0]):
                w_start = winfo.get("started_ns", start_ns)
                w_upd = winfo.get("updated_ns", start_ns)
                workers_list.append(
                    WorkerPageView(
                        worker_id=str(wid),
                        file_display_name=winfo.get("file_display_name") or inputs[0].display_name,
                        page_number=winfo.get("page_number"),
                        stage=winfo.get("stage", active_stage),
                        device_type=winfo.get("device_type") or "",
                        elapsed_ns=max(0, now_ns - w_start),
                        idle_ns=max(0, now_ns - w_upd),
                        status="active",
                    )
                )
            active_workers = tuple(workers_list)
        else:
            active_workers = ()

        active_run_view = MukhaPresenter.build_monitor_view(
            run_id=active_run_id,
            status=status,
            started_at_ns=start_ns,
            now_ns=now_ns,
            files=files,
            maruti_records=maruti_recs,
            pramana_records=pramana_recs,
            active_workers=active_workers,
        )

    # Capability availability facts
    caps_status = MukhaPresenter.audit_capability_status(agni=agni)
    registered_caps = set(c.capability_id for c in agni.kosh.capabilities())

    _ACTION_DESCS = {
        "read_native": "Fast text & spreadsheet extraction",
        "bank_statements": "Financial table & transaction normalization",
        "ocr": "Local rapid image/PDF text recognition",
        "font_conversion": "Legacy Hindi font mapping & Unicode",
        "translation": "Protected local Hindi↔English translation",
        "statutory": "Statutory and legal document metadata extraction",
    }

    available_actions = []
    for decl in agni.kosh.capabilities():
        act_id = decl.capability_id
        if act_id == "identify":
            continue  # internal classification stage, not an operator-triggered requirement
        act_label = decl.display_name

        is_avail, reason = caps_status.get(act_id, (False, "Unavailable"))
        enabled = is_avail and (act_id in registered_caps)
        disabled_reason = None if enabled else reason
        params = _build_action_parameters(act_id, decl=decl)
        available_actions.append(
            AvailableActionView(
                action_id=act_id,
                label=act_label,
                is_enabled=enabled,
                disabled_reason=disabled_reason,
                description=_ACTION_DESCS.get(act_id) or getattr(decl, "description", "") or "",
                parameters=params,
            )
        )

    # Defense-in-depth: Expose indictrans2_translation action matching translation readiness
    trans_action = next((a for a in available_actions if a.action_id == "translation"), None)
    if trans_action is not None and not any(a.action_id == "indictrans2_translation" for a in available_actions):
        available_actions.append(
            AvailableActionView(
                action_id="indictrans2_translation",
                label="IndicTrans2 Translation",
                is_enabled=trans_action.is_enabled,
                disabled_reason=trans_action.disabled_reason,
                description="Local AI4Bharat IndicTrans2 neural translation engine",
                parameters=trans_action.parameters,
            )
        )

    cached_sel = getattr(runner, "get_intake_selection", lambda: None)()
    cached_preflight = getattr(runner, "get_intake_preflight", lambda: None)()

    if cached_sel is not None:
        input_sel = cached_sel
    elif active_req and is_alive:
        input_sel = InputSelectionView(
            total_files=len(active_req.inputs),
            total_size_bytes=sum(getattr(inp, "size_bytes", 0) or 0 for inp in active_req.inputs),
            is_grouped=False,
            items=tuple(
                InputItemView(
                    input_id=inp.input_id,
                    display_name=inp.display_name,
                    size_bytes=getattr(inp, "size_bytes", 0) or 0,
                    media_type=inp.media_type,
                    source_path=str(inp.source_path) if inp.source_path else None,
                )
                for inp in active_req.inputs
            ),
        )
    else:
        input_sel = InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)

    current_screen = "monitor" if active_run_id and is_alive else ("summary" if last_summary else "home")
    inspector_view = build_inspector_view(agni, runner, active_run_id, host, port) if active_run_id else None

    review_queue: tuple[ReviewItemView, ...] = ()
    review_items = extract_review_items(runner, run_id=active_run_id)
    if review_items:
        review_queue = tuple(
            ReviewItemView(
                item_id=it["item_id"],
                attempt_id=it["attempt_id"],
                file_display_name=it.get("context", {}).get("source_file", "Document"),
                stage=it.get("stage", "Review"),
                source_text=it.get("context", {}).get("source_text", "") or it.get("context", {}).get("source", ""),
                output_text=it.get("draft_proposal")
                or it.get("context", {}).get("output_text", "")
                or it.get("context", {}).get("output", ""),
                issue_reason=it.get("message", "Validation issue"),
                page_number=it.get("context", {}).get("page_number"),
                source_input_id=it.get("context", {}).get("input_id"),
                status=it.get("status", "pending"),
                draft_proposal=it.get("draft_proposal"),
                available_actions=it.get("available_actions", ("accept", "unresolved")),
            )
            for it in review_items
        )

    policy_label = "Local only"
    if hasattr(agni, "kavacha") and agni.kavacha is not None:
        pol = getattr(agni.kavacha, "policy", None)
        if pol is not None and getattr(pol, "allow_external_processing", False):
            policy_label = "Cloud enabled"

    return ApplicationViewState(
        current_screen=current_screen,
        requirement=active_req.requirement if active_req else "read_native",
        policy_label=policy_label,
        input_selection=input_sel,
        active_run=active_run_view,
        review_queue=review_queue,
        terminal_summary=last_summary,
        inspector=inspector_view,
        available_actions=tuple(available_actions),
        preflight=cached_preflight,
        schema_version=1,
        state_revision=getattr(runner, "state_revision", 0),
    )
