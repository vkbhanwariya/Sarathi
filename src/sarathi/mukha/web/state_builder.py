"""Mukha Web Presentation State Builder for Sarathi V2.

Projects canonical runtime facts, telemetry records, and runner progress into
typed view contracts for the interactive Web UI.
"""

from __future__ import annotations

import time
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
    WorkerPageView,
)

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
    """Retrieve recent terminal run summaries from Darpana telemetry history."""
    if hasattr(agni, "darpana") and agni.darpana is not None:
        return agni.darpana.query_run_history(limit=limit)
    return ()


def extract_review_items(runner: RunCoordinator, run_id: str | None = None) -> tuple[dict[str, Any], ...]:
    """Retrieve pending review/exception items from run result warnings enriched with applied decisions."""
    res = runner.last_result
    if res is None or not res.warnings:
        return ()
    intents = runner.get_review_intents() if hasattr(runner, "get_review_intents") else {}
    items = []
    for idx, w in enumerate(res.warnings, start=1):
        item_id = f"rev-{idx}"
        intent = intents.get(item_id)
        ctx = dict(w.context) if w.context else {}
        status = "pending"
        applied_action = None
        if intent is not None:
            applied_action = intent.action_id
            status = "resolved" if intent.action_id in ("accept", "unresolved", "dismiss") else "edited"
            if intent.proposed_value:
                ctx["output"] = intent.proposed_value

        items.append(
            {
                "item_id": item_id,
                "attempt_id": getattr(w, "span_id", "") or "att-1",
                "code": w.code,
                "message": w.message,
                "stage": w.stage,
                "status": status,
                "applied_action": applied_action,
                "context": ctx,
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

    maruti_recs, pramana_recs = get_run_telemetry(agni, run_id)
    if not maruti_recs and not pramana_recs and not is_active:
        return None

    status = "RUNNING" if (is_active and is_alive) else (term_status or "COMPLETED")
    now_ns = time.perf_counter_ns()
    elapsed_ns = max(0, now_ns - start_ns) if start_ns > 0 else 0

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


def _build_action_parameters(act_id: str) -> tuple[ActionParameterView, ...]:
    """Provide declarative configuration parameters for each capability."""
    if act_id == "ocr":
        return (
            ActionParameterView(
                parameter_id="profile",
                display_name="Execution Profile",
                kind="select",
                default_value="instant",
                options=(
                    ("instant", "Instant (Highest Throughput)"),
                    ("accurate", "Accurate (Quality Verification)"),
                    ("custom", "Custom Configuration"),
                ),
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
                display_name="Fallback (Tesseract)",
                kind="toggle",
                default_value=True,
                description="CPU secondary fallback engine",
            ),
            ActionParameterView(
                parameter_id="validation_enabled",
                display_name="Validation Gate",
                kind="toggle",
                default_value=True,
                description="Pramana confidence verification",
            ),
        )
    if act_id == "font_conversion":
        return (
            ActionParameterView(
                parameter_id="source_font",
                display_name="Source Font Hint",
                kind="select",
                default_value="",
                options=(
                    ("", "Auto-Detect Source Font"),
                    ("krutidev010", "KrutiDev 010 / DevLys"),
                    ("chanakya010", "Chanakya"),
                    ("shusha010", "Shusha"),
                    ("shivaji010", "Shivaji"),
                ),
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
                if f_prog and f_prog.get("status"):
                    f_status = f_prog.get("status")
                    f_stage = f_prog.get("stage", "Completed")
                    f_elapsed = f_prog.get("duration_ns")
                elif status in ("SUCCESS", "WARNING"):
                    f_status = "WARNING" if f_warn_count > 0 else "SUCCESS"
                    f_stage = "Completed"
                    f_elapsed = f_prog.get("duration_ns") if f_prog else None
                elif status == "CANCELLED":
                    if f_prog and f_prog.get("status") in ("SUCCESS", "WARNING"):
                        f_status = f_prog.get("status")
                        f_stage = "Completed"
                        f_elapsed = f_prog.get("duration_ns")
                    else:
                        f_status = "CANCELLED"
                        f_stage = "Cancelled"
                        f_elapsed = None
                else:
                    if f_prog and f_prog.get("status") in ("SUCCESS", "WARNING"):
                        f_status = f_prog.get("status")
                        f_stage = "Completed"
                        f_elapsed = f_prog.get("duration_ns")
                    else:
                        f_status = "FAILED"
                        f_stage = "Failed"
                        f_elapsed = None

            files_list.append(
                FileRunView(
                    input_id=inp.input_id,
                    display_name=inp.display_name,
                    ordinal=idx + 1,
                    status=f_status,
                    elapsed_ns=f_elapsed,
                    current_stage=f_stage,
                    warning_count=f_warn_count,
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
        params = _build_action_parameters(act_id)
        available_actions.append(
            AvailableActionView(
                action_id=act_id,
                label=act_label,
                is_enabled=enabled,
                disabled_reason=disabled_reason,
                description=_ACTION_DESCS.get(act_id, ""),
                parameters=params,
            )
        )

    if active_req:
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
        cached_sel = getattr(runner, "get_intake_selection", lambda: None)()
        if cached_sel is not None:
            input_sel = cached_sel
        else:
            input_sel = InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)

    current_screen = "monitor" if active_run_id and is_alive else ("summary" if last_summary else "home")
    inspector_view = build_inspector_view(agni, runner, active_run_id, host, port) if active_run_id else None

    return ApplicationViewState(
        current_screen=current_screen,
        requirement=active_req.requirement if active_req else "read_native",
        policy_label="Local only",
        input_selection=input_sel,
        active_run=active_run_view,
        terminal_summary=last_summary,
        inspector=inspector_view,
        available_actions=tuple(available_actions),
        schema_version=1,
        state_revision=getattr(runner, "state_revision", 0),
    )
