"""Mukha Presenter - Pure Presentation Logic and State Projection in Sarathi V2.

Transforms canonical Request, Result, Darpana records, and Kavacha policy
into typed presentation view models. Does not mutate runtime state, execute work,
or fabricate metrics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.kavacha import Kavacha
from sarathi.mukha.state import (
    ActivityLogView,
    ApplicationViewState,
    ArtifactOutcomeView,
    AvailableActionView,
    DeviceProgressView,
    DeviceSummaryView,
    FallbackImprovementView,
    FileRunView,
    InputSelectionView,
    InspectorViewState,
    OperationView,
    PageConfidenceView,
    PreflightView,
    ProgressState,
    RegionConfidenceView,
    ReviewItemView,
    RunSummaryView,
    RunViewState,
    StageTimingView,
    StartupViewState,
    WorkerPageView,
    WorkerPerformanceView,
)
from sarathi.sankalpa import ArtifactRef, InputRef, Request, Result

# Operations >= 5s promoted to long-running
_FIVE_SECONDS_NS = 5_000_000_000
_TERMINAL_STATUSES = {"SUCCESS", "COMPLETED", "FAILED", "CANCELLED", "QUARANTINED", "WARNING", "PARTIAL"}


def format_duration_ns(duration_ns: int | None) -> str:
    """Format an integer nanosecond duration into a concise human-readable time string."""
    if duration_ns is None or duration_ns < 0:
        return "-"
    seconds = duration_ns / 1_000_000_000.0
    if seconds < 1.0:
        return f"{seconds:.2f}s"
    if seconds < 60.0:
        return f"{seconds:04.1f}s" if seconds < 10.0 else f"{seconds:.1f}s"
    mins = int(seconds // 60)
    rem_secs = seconds % 60
    return f"{mins:02d}:{rem_secs:04.1f}"


def format_bytes(size_bytes: int | None) -> str:
    """Format integer byte count into a clean human-readable string (B, KB, MB, GB)."""
    if size_bytes is None or size_bytes < 0:
        return "-"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_confidence(confidence: float | None) -> str:
    """Format confidence score (0.0 to 1.0) as percentage string, or '-' if unavailable."""
    if confidence is None:
        return "-"
    pct = confidence * 100.0 if confidence <= 1.0 else confidence
    return f"{pct:.1f}%"


def status_badge(status: str) -> str:
    """Return normalized status badge label."""
    return status.upper().strip()


class MukhaPresenter:
    """Pure presenter projecting runtime facts into immutable presentation models."""

    @staticmethod
    def intake_from_paths(
        paths: Sequence[Path | str],
        kavacha: Kavacha | None = None,
        runtime_root: Path | None = None,
        output_root: Path | None = None,
        recursive: bool = False,
    ) -> tuple[tuple[InputRef, ...], InputSelectionView, PreflightView]:
        """Delegate input discovery to canonical intake module."""
        from sarathi.mukha.intake import intake_from_paths

        return intake_from_paths(
            paths,
            kavacha=kavacha,
            runtime_root=runtime_root,
            output_root=output_root,
            recursive=recursive,
        )

    @staticmethod
    def audit_capability_status(
        data_root: Path | None = None,
        kosh: Any | None = None,
        agni: Any | None = None,
        providers: Sequence[Any] | None = None,
    ) -> dict[str, tuple[bool, str]]:
        """Audit availability status of capabilities without false promises.

        When Agni or providers are supplied, availability is audited via their readiness probes.
        When Kosh is provided, availability is projected from canonical registry state.
        Returns dict mapping capability_id -> (is_available, status_or_reason).
        """
        # 1. Agni runtime audit (cached and thread-safe)
        if agni is not None and hasattr(agni, "audit_readiness"):
            readiness_map = agni.audit_readiness()
            return {cap_id: (r.ready, r.reason) for cap_id, r in readiness_map.items()}

        # 2. Projected from canonical Kosh registry state
        if kosh is not None and hasattr(kosh, "capabilities"):
            statuses: dict[str, tuple[bool, str]] = {}
            for decl in kosh.capabilities():
                if decl.capability_id == "identify":
                    continue
                statuses[decl.capability_id] = (True, f"Ready ({decl.plugin_id})")
            for cap_id in ("read_native", "ocr", "bank_statements", "font_conversion", "translation"):
                if cap_id not in statuses:
                    statuses[cap_id] = (False, "Not registered in Kosh")
            return statuses

        # 3. Direct provider evaluation (when explicitly supplied by caller)
        if providers is not None:
            from sarathi.sankalpa import PluginServices
            from sarathi.sutra import get_canonical_data_root

            base_data = data_root or get_canonical_data_root()
            services = PluginServices(data_root=base_data)

            statuses = {}
            for prov in providers:
                try:
                    for cap_id, r in prov.readiness(services).items():
                        statuses[cap_id] = (r.ready, r.reason)
                except Exception as exc:
                    for decl in getattr(prov, "declarations", ()):
                        statuses[decl.capability_id] = (False, f"Readiness probe error: {type(exc).__name__}")

            return statuses

        return {}

    @staticmethod
    def build_startup_view(
        is_initializing: bool,
        current_stage: str,
        elapsed_ns: int,
        maruti_records: Sequence[MarutiRecord] = (),
        is_failed: bool = False,
        failure_message: str | None = None,
    ) -> StartupViewState:
        """Build Screen 0 Overlay: Aarambha - Startup Progress presentation state."""
        stages: list[tuple[str, str, int | None]] = []
        for r in maruti_records:
            if r.component == "bootstrap" or "init" in r.phase_name or "bootstrap" in r.phase_name:
                st = "completed" if r.outcome == "success" else ("cancelled" if r.outcome == "cancelled" else "failed")
                stages.append((r.phase_name, st, r.duration_ns))
        return StartupViewState(
            is_initializing=is_initializing,
            current_stage=current_stage,
            elapsed_ns=elapsed_ns,
            stages=tuple(stages),
            is_failed=is_failed,
            failure_message=failure_message,
        )

    @staticmethod
    def build_review_view(
        items: Sequence[ReviewItemView],
    ) -> tuple[ReviewItemView, ...]:
        """Construct immutable review queue snapshot for Screen 3: Pariksha."""
        return tuple(items)

    @staticmethod
    def build_home_view(
        input_selection: InputSelectionView | None = None,
        requirement: str = "read_native",
        policy_label: str = "Local only",
        preflight: PreflightView | None = None,
        available_actions: Sequence[AvailableActionView] = (),
        review_queue: Sequence[ReviewItemView] = (),
        startup: StartupViewState | None = None,
    ) -> ApplicationViewState:
        """Build Screen 1: Griha - Home & Input Setup presentation state purely from supplied facts."""
        sel = (
            input_selection
            if input_selection is not None
            else InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)
        )
        return ApplicationViewState(
            current_screen="home",
            requirement=requirement,
            policy_label=policy_label,
            input_selection=sel,
            preflight=preflight,
            available_actions=tuple(available_actions),
            review_queue=tuple(review_queue),
            startup=startup,
        )

    @staticmethod
    def build_monitor_view(
        run_id: str,
        status: str,
        started_at_ns: int,
        now_ns: int,
        files: Sequence[FileRunView],
        maruti_records: Sequence[MarutiRecord] = (),
        pramana_records: Sequence[PramanaRecord] = (),
        active_workers: Sequence[WorkerPageView] = (),
        current_state: RunViewState | None = None,
    ) -> RunViewState:
        """Build Screen 2: Pravritti - Live Run Monitor presentation state."""
        effective_status = status
        if current_state is not None and current_state.status.upper() in _TERMINAL_STATUSES:
            effective_status = current_state.status

        elapsed_ns = max(0, now_ns - started_at_ns)

        # Factual device execution aggregation: prefer worker_execution records if present, else capability_execution
        worker_maruti = [r for r in maruti_records if r.phase_name == "worker_execution" and r.attributes.get("device_type")]
        target_maruti = worker_maruti if worker_maruti else [r for r in maruti_records if r.phase_name == "capability_execution" and r.attributes.get("device_type")]

        device_durations: dict[str, list[int]] = {}
        device_confidences: dict[str, list[float]] = {}
        span_to_device_mon: dict[str, str] = {}

        for rec in target_maruti:
            dev = rec.attributes.get("device_type")
            if dev:
                dev_key = str(dev).upper()
                device_durations.setdefault(dev_key, []).append(rec.duration_ns)
                if rec.span_id:
                    span_to_device_mon[rec.span_id] = dev_key

        for p_rec in pramana_records:
            dev = p_rec.attributes.get("device_type") or span_to_device_mon.get(p_rec.span_id)
            if dev and p_rec.confidence is not None:
                device_confidences.setdefault(str(dev).upper(), []).append(p_rec.confidence.score)

        device_progress: list[DeviceProgressView] = []
        for dev_type, durs in sorted(device_durations.items()):
            exec_count = len(durs)
            tot_dur = sum(durs)
            avg_dur = int(tot_dur / exec_count) if exec_count > 0 else None
            confs = device_confidences.get(dev_type, [])
            avg_conf = (sum(confs) / len(confs)) if confs else None

            device_progress.append(
                DeviceProgressView(
                    device_type=dev_type,
                    execution_count=exec_count,
                    total_duration_ns=tot_dur,
                    avg_duration_ns=avg_dur,
                    avg_confidence=avg_conf,
                )
            )

        if not device_progress and active_workers:
            for w in active_workers:
                if w.device_type:
                    device_progress.append(
                        DeviceProgressView(
                            device_type=w.device_type,
                            execution_count=1,
                            total_duration_ns=w.elapsed_ns,
                            avg_duration_ns=w.elapsed_ns,
                            avg_confidence=None,
                        )
                    )

        # 5-second rule: filter long running operations (elapsed_ns >= 5s)
        long_running: list[OperationView] = []
        current_focus: OperationView | None = None

        for w in active_workers:
            is_long = w.elapsed_ns >= _FIVE_SECONDS_NS
            page_part = f" (Page {w.page_number})" if w.page_number is not None else ""
            op = OperationView(
                operation_name=f"Worker {w.worker_id} - {w.file_display_name}{page_part}",
                stage=w.stage,
                device_type=w.device_type,
                elapsed_ns=w.elapsed_ns,
                is_long_running=is_long,
                last_activity=None,
            )
            if is_long:
                long_running.append(op)
            if current_focus is None:
                current_focus = op

        terminal_files = sum(
            1 for f in files if (f.status and f.status.upper() in _TERMINAL_STATUSES)
        )
        progress = ProgressState.known(terminal_files, len(files)) if files else ProgressState.indeterminate()

        return RunViewState(
            run_id=run_id,
            status=effective_status,
            elapsed_ns=elapsed_ns,
            terminal_files=terminal_files,
            total_files=len(files),
            current_focus=current_focus,
            files=tuple(files),
            active_workers=tuple(active_workers),
            device_progress=tuple(device_progress),
            long_running=tuple(long_running),
            progress=progress,
        )

    @staticmethod
    def build_summary_view(
        run_id: str,
        status: str,
        wall_time_ns: int,
        request: Request,
        result: Result | None = None,
        successful_files: int | None = None,
        warning_files: int | None = None,
        failed_files: int | None = None,
        quarantined_count: int | None = None,
        retry_count: int | None = None,
        failures: Sequence[str] = (),
        maruti_records: Sequence[MarutiRecord] = (),
        pramana_records: Sequence[PramanaRecord] = (),
    ) -> RunSummaryView:
        """Build Screen 4: Samapti - Run Summary presentation state purely from factual parameters."""
        # Stage timings aggregation from telemetry
        stage_map: dict[str, list[int]] = {}
        for r in maruti_records:
            stage_map.setdefault(r.phase_name, []).append(r.duration_ns)

        stage_timings = tuple(
            StageTimingView(
                stage_name=stage,
                duration_ns=sum(durs),
                call_count=len(durs),
            )
            for stage, durs in sorted(stage_map.items())
        )

        # Device execution summary: prefer worker_execution records if present, else capability_execution
        worker_maruti = [r for r in maruti_records if r.phase_name == "worker_execution" and r.attributes.get("device_type")]
        target_maruti = worker_maruti if worker_maruti else [r for r in maruti_records if r.phase_name == "capability_execution" and r.attributes.get("device_type")]

        device_map: dict[str, list[int]] = {}
        span_to_device: dict[str, str] = {}
        dev_confs: dict[str, list[float]] = {}
        for r in target_maruti:
            dev = r.attributes.get("device_type")
            if dev:
                dev_str = str(dev).upper()
                device_map.setdefault(dev_str, []).append(r.duration_ns)
                if r.span_id:
                    span_to_device[r.span_id] = dev_str

        for pr in pramana_records:
            dev = pr.attributes.get("device_type") or span_to_device.get(pr.span_id)
            if dev and pr.confidence is not None:
                dev_confs.setdefault(str(dev).upper(), []).append(pr.confidence.score)

        device_summaries: list[DeviceSummaryView] = []
        for dev_k, durs in sorted(device_map.items()):
            exec_c = len(durs)
            avg_d = int(sum(durs) / exec_c) if exec_c > 0 else None
            sorted_d = sorted(durs)
            p95_idx = int(0.95 * len(sorted_d))
            p95_d = sorted_d[min(p95_idx, len(sorted_d) - 1)] if sorted_d else None
            confs = dev_confs.get(dev_k, [])
            avg_c = (sum(confs) / len(confs)) if confs else None

            device_summaries.append(
                DeviceSummaryView(
                    device_type=dev_k,
                    execution_count=exec_c,
                    attempts=exec_c,
                    avg_duration_ns=avg_d,
                    p95_duration_ns=p95_d,
                    avg_confidence=avg_c,
                )
            )

        # Confirmed artifacts only: only include committed ArtifactRef
        confirmed_artifacts: list[ArtifactOutcomeView] = []
        if result is not None:
            for art in result.artifacts:
                if isinstance(art, ArtifactRef):
                    confirmed_artifacts.append(
                        ArtifactOutcomeView(
                            artifact_id=art.artifact_id,
                            role=art.role,
                            display_name=art.path.name if art.path else art.artifact_id,
                            size_bytes=art.size_bytes,
                            sha256_hex=art.checksum_sha256,
                        )
                    )

        # Confidence from result or pramana records
        all_confs = [pr.confidence.score for pr in pramana_records if pr.confidence is not None]
        if all_confs:
            avg_confidence = sum(all_confs) / len(all_confs)
        elif result is not None and result.confidence is not None:
            avg_confidence = result.confidence.score
        else:
            avg_confidence = None

        # Accuracy remains None unless verified ground truth exists in pramana or metadata
        all_accs = [pr.accuracy.score for pr in pramana_records if pr.accuracy is not None]
        if all_accs:
            verified_acc: float | None = sum(all_accs) / len(all_accs)
        elif result is not None:
            meta_acc = result.metadata.get("accuracy", result.metadata.get("verified_accuracy"))
            if hasattr(meta_acc, "score"):
                verified_acc = float(meta_acc.score)
            elif isinstance(meta_acc, (int, float)) and not isinstance(meta_acc, bool):
                verified_acc = float(meta_acc)
            else:
                verified_acc = None
        else:
            verified_acc = None

        avg_dur_per_input = int(wall_time_ns / max(1, len(request.inputs))) if wall_time_ns > 0 else None

        warnings = tuple(str(w.message) for w in result.warnings) if result is not None else ()

        return RunSummaryView(
            run_id=run_id,
            status=status,
            wall_time_ns=wall_time_ns,
            total_inputs=len(request.inputs),
            successful_files=successful_files,
            warning_files=warning_files,
            failed_files=failed_files,
            quarantined_count=quarantined_count,
            retry_count=retry_count,
            avg_duration_per_input_ns=avg_dur_per_input,
            avg_confidence=avg_confidence,
            accuracy=verified_acc,
            stage_timings=stage_timings,
            device_summaries=tuple(device_summaries),
            artifacts=tuple(confirmed_artifacts),
            warnings=warnings,
            failures=tuple(failures),
        )

    @staticmethod
    def build_inspector_view(
        run_id: str,
        status: str,
        elapsed_ns: int,
        maruti_records: Sequence[MarutiRecord] = (),
        pramana_records: Sequence[PramanaRecord] = (),
        system_facts: Sequence[tuple[str, str]] = (),
        live_workers: Mapping[str, Any] | None = None,
    ) -> InspectorViewState:
        """Build Screen 5: Nirikshana - Run Inspector presentation state."""
        logs: list[tuple[str, str, str, str]] = []
        stage_map: dict[str, list[int]] = {}
        device_map: dict[str, list[int]] = {}
        worker_stats: dict[str, dict[str, Any]] = {}

        for r in maruti_records:
            if r.outcome == "success":
                severity = "INFO"
            elif r.outcome == "cancelled":
                severity = "WARN"
            else:
                severity = "ERROR"
            logs.append(
                ActivityLogView(
                    timestamp=r.timestamp_utc,
                    severity=severity,
                    component=r.component,
                    message=f"Phase {r.phase_name} ({r.duration_ns / 1_000_000:.2f}ms)",
                )
            )
            stage_map.setdefault(r.phase_name, []).append(r.duration_ns)
            dev = r.attributes.get("device_type")
            if dev:
                device_map.setdefault(str(dev).upper(), []).append(r.duration_ns)

            # Extract per-worker telemetry if present
            w_id = r.attributes.get("worker_id")
            if not w_id and dev:
                w_id = f"{str(dev).lower()}-worker-{r.attributes.get('device_id', '0')}"

            if w_id:
                w_entry = worker_stats.setdefault(
                    str(w_id),
                    {
                        "worker_id": str(w_id),
                        "device_type": str(r.attributes.get("device_type") or "CPU").upper(),
                        "device_id": str(r.attributes.get("device_id") or "0"),
                        "tasks_completed": 0,
                        "pages_completed": 0,
                        "total_duration_ns": 0,
                        "status": "COMPLETED" if status in ("COMPLETED", "FAILED") else "IDLE",
                    },
                )
                w_entry["tasks_completed"] += 1
                w_entry["pages_completed"] += int(r.attributes.get("pages_processed", 1))
                w_entry["total_duration_ns"] += r.duration_ns

        # Incorporate active live workers if run is active
        if live_workers:
            for wid, winfo in live_workers.items():
                swid = str(wid)
                if swid not in worker_stats:
                    worker_stats[swid] = {
                        "worker_id": swid,
                        "device_type": str(winfo.get("device_type") or "CPU").upper(),
                        "device_id": str(winfo.get("device_id") or "0"),
                        "tasks_completed": 0,
                        "pages_completed": 0,
                        "total_duration_ns": 0,
                        "status": "ACTIVE",
                    }
                else:
                    if status == "RUNNING":
                        worker_stats[swid]["status"] = "ACTIVE"

        worker_performance_list: list[WorkerPerformanceView] = []
        for wid, wdata in sorted(worker_stats.items()):
            tot_ms = wdata["total_duration_ns"] / 1_000_000.0
            tasks = wdata["tasks_completed"]
            pages = wdata["pages_completed"]
            avg_ms = tot_ms / max(1, tasks)
            tput = pages / (tot_ms / 1000.0) if tot_ms > 0 else 0.0
            worker_performance_list.append(
                WorkerPerformanceView(
                    worker_id=wid,
                    device_type=wdata["device_type"],
                    device_id=wdata["device_id"],
                    tasks_completed=tasks,
                    pages_completed=pages,
                    total_duration_ms=round(tot_ms, 2),
                    avg_duration_ms=round(avg_ms, 2),
                    throughput_per_sec=round(tput, 2),
                    status=wdata["status"],
                )
            )

        stage_timings = tuple(
            StageTimingView(stage_name=k, duration_ns=sum(v), call_count=len(v)) for k, v in sorted(stage_map.items())
        )

        device_summaries = tuple(
            DeviceSummaryView(
                device_type=dev_k,
                execution_count=len(durs),
                attempts=len(durs),
                avg_duration_ns=int(sum(durs) / len(durs)),
                p95_duration_ns=sorted(durs)[int(0.95 * len(durs))] if durs else None,
                avg_confidence=None,
            )
            for dev_k, durs in sorted(device_map.items())
        )

        conf_brackets = {"90-100%": 0, "75-89%": 0, "50-74%": 0, "<50%": 0}
        page_conf_map: dict[tuple[str, int], dict[str, Any]] = {}
        region_conf_list: list[RegionConfidenceView] = []
        fallback_improvements: list[FallbackImprovementView] = []

        for pr in pramana_records:
            score = pr.confidence.score if pr.confidence is not None else None
            if score is not None:
                if score >= 0.90:
                    conf_brackets["90-100%"] += 1
                elif score >= 0.75:
                    conf_brackets["75-89%"] += 1
                elif score >= 0.50:
                    conf_brackets["50-74%"] += 1
                else:
                    conf_brackets["<50%"] += 1

            level = pr.attributes.get("level")
            file_name = pr.attributes.get("file_display_name") or pr.subject_id or "document"
            p_num = int(pr.attributes.get("page_number", 1))

            is_fallback = bool(
                pr.attributes.get("fallback_applied")
                or (pr.confidence is not None and getattr(pr.confidence, "evidence", None) and pr.confidence.evidence.get("fallback_applied"))
            )
            raw_eng = pr.attributes.get("fallback_engine") or "Tesseract 5"
            fallback_eng = "Tesseract 5" if raw_eng in ("tesseract5", "tesseract") else str(raw_eng)
            orig_conf = pr.attributes.get("original_confidence")
            conf_gain = pr.attributes.get("confidence_gain")

            if level == "page" or (pr.attributes.get("page_number") is not None and level != "region"):
                key = (file_name, p_num)
                eff_score = round(score, 4) if score is not None else None
                min_attr = pr.attributes.get("min_confidence")
                max_attr = pr.attributes.get("max_confidence")
                min_c = round(float(min_attr), 4) if min_attr is not None else eff_score
                max_c = round(float(max_attr), 4) if max_attr is not None else eff_score
                r_cnt = int(pr.attributes.get("region_count", 0))
                rev = bool(pr.attributes.get("review_recommended", False))
                if not rev and pr.confidence is not None and getattr(pr.confidence, "evidence", None):
                    rev = bool(pr.confidence.evidence.get("review_recommended", False))
                page_conf_map[key] = {
                    "file_display_name": file_name,
                    "page_number": p_num,
                    "confidence_score": eff_score,
                    "region_count": r_cnt,
                    "min_confidence": min_c,
                    "max_confidence": max_c,
                    "review_recommended": rev,
                }
            elif level == "region" or pr.attributes.get("region_id") is not None:
                eff_score = round(score, 4) if score is not None else None
                reg_id = str(pr.attributes.get("region_id") or pr.span_id)
                reg_type = str(pr.attributes.get("region_type", "text"))
                method = pr.confidence.method if pr.confidence is not None else "direct"
                rev = bool(pr.attributes.get("review_recommended", False))
                if not rev and pr.confidence is not None and getattr(pr.confidence, "evidence", None):
                    rev = bool(pr.confidence.evidence.get("review_recommended", False))

                orig_c_float = float(orig_conf) if orig_conf is not None else None
                gain_raw = pr.attributes.get("raw_confidence_score_delta", conf_gain)
                gain_float = float(gain_raw) if gain_raw is not None else None

                region_conf_list.append(
                    RegionConfidenceView(
                        region_id=reg_id,
                        file_display_name=file_name,
                        page_number=p_num,
                        confidence_score=eff_score,
                        region_type=reg_type,
                        method=method,
                        review_recommended=rev,
                        original_confidence=round(orig_c_float, 4) if orig_c_float is not None else None,
                        confidence_gain=round(gain_float, 4) if gain_float is not None else None,
                        raw_confidence_score_delta=round(gain_float, 4) if gain_float is not None else None,
                        fallback_engine=fallback_eng if is_fallback else None,
                    )
                )

                if is_fallback and orig_c_float is not None and eff_score is not None:
                    delta = gain_float if gain_float is not None else (eff_score - orig_c_float)
                    fallback_improvements.append(
                        FallbackImprovementView(
                            region_id=reg_id,
                            file_display_name=file_name,
                            page_number=p_num,
                            original_confidence=round(orig_c_float, 4),
                            improved_confidence=eff_score,
                            confidence_gain=round(delta, 4),
                            fallback_engine=fallback_eng,
                            raw_confidence_score_delta=round(delta, 4),
                        )
                    )

        conf_dist = tuple(conf_brackets.items())
        page_confidence = tuple(
            PageConfidenceView(**pdata)
            for _, pdata in sorted(page_conf_map.items(), key=lambda kv: (kv[0][0], kv[0][1]))
        )

        facts = list(system_facts)
        facts.extend(
            [
                ("Total Maruti Records", str(len(maruti_records))),
                ("Total Pramana Records", str(len(pramana_records))),
                ("Measured Stages", str(len(stage_map))),
            ]
        )
        if fallback_improvements:
            facts.append(("Tesseract Recoveries", f"{len(fallback_improvements)} regions improved"))

        return InspectorViewState(
            run_id=run_id,
            status=status,
            elapsed_ns=elapsed_ns,
            activity_logs=tuple(logs),
            stage_timings=stage_timings,
            device_summaries=device_summaries,
            confidence_distribution=conf_dist,
            system_facts=tuple(facts),
            worker_performance=tuple(worker_performance_list),
            page_confidence=page_confidence,
            region_confidence=tuple(region_conf_list),
            fallback_improvements=tuple(fallback_improvements),
        )
