"""Mukha Presenter - Pure Presentation Logic and State Projection in Sarathi V2.

Transforms canonical Request, Result, Darpana records, and Kavacha policy
into typed presentation view models. Does not mutate runtime state, execute work,
or fabricate metrics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.kavacha import Kavacha
from sarathi.mukha.state import (
    ApplicationViewState,
    ArtifactOutcomeView,
    AvailableActionView,
    DeviceProgressView,
    DeviceSummaryView,
    FileRunView,
    InputSelectionView,
    InspectorViewState,
    OperationView,
    PreflightView,
    ReviewItemView,
    RunSummaryView,
    RunViewState,
    StageTimingView,
    StartupViewState,
    WorkerPageView,
)
from sarathi.sankalpa import ArtifactRef, InputRef, Request, Result

# Operations running for 5 or more seconds are promoted to the long-running section
_FIVE_SECONDS_NS = 5_000_000_000
_TERMINAL_STATUSES = {"SUCCESS", "COMPLETED", "FAILED", "CANCELLED", "QUARANTINED"}


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
    ) -> dict[str, tuple[bool, str]]:
        """Audit availability status of capabilities without false promises.

        When Kosh is provided, availability is projected from canonical registry state.
        Returns dict mapping capability_id -> (is_available, status_or_reason).
        """
        from sarathi.sutra import get_canonical_data_root

        if kosh is not None and hasattr(kosh, "has_capability"):
            statuses: dict[str, tuple[bool, str]] = {}
            for cap_id in ("read_native", "ocr", "bank_statements", "font_conversion", "translation"):
                decl = kosh.get_capability(cap_id)
                if decl is not None:
                    statuses[cap_id] = (True, f"Ready ({decl.plugin_id})")
                else:
                    statuses[cap_id] = (False, "Not registered in Kosh")
            return statuses

        import importlib.util

        base_data = data_root or get_canonical_data_root()
        statuses = {}

        # 1. Native Extraction
        statuses["read_native"] = (True, "Ready (Standard Extraction)")

        # 2. Base OCR
        ocr_installed = (
            importlib.util.find_spec("rapidocr") is not None
            and importlib.util.find_spec("openvino") is not None
            and importlib.util.find_spec("PIL") is not None
            and importlib.util.find_spec("numpy") is not None
        )
        ocr_manifest = base_data / "ocr" / "manifest.json"
        if ocr_installed and ocr_manifest.exists():
            statuses["ocr"] = (True, "Ready (RapidOCR + OpenVINO)")
        else:
            statuses["ocr"] = (False, "Unavailable (Missing OCR extra dependencies or models)")

        # 3. Bank Statements (dynamic profiles detection)
        from sarathi.shakti.bank_statements.detector import load_bank_profiles

        bank_profs = load_bank_profiles(base_data / "banks")
        if bank_profs:
            prof_ids = [str(p.get("profile_id", "")).upper() for p in bank_profs if p.get("profile_id")]
            statuses["bank_statements"] = (True, f"Ready ({', '.join(prof_ids)} profiles)")
        else:
            statuses["bank_statements"] = (False, "Unavailable (No bank profiles loaded)")

        # 4. Font Conversion (dynamic font packs detection)
        font_files = list((base_data / "fonts").glob("*.json")) if (base_data / "fonts").exists() else []
        if font_files:
            names = [f.stem for f in font_files]
            statuses["font_conversion"] = (True, f"Ready ({len(names)} mapping packs: {', '.join(names)})")
        else:
            statuses["font_conversion"] = (False, "Unavailable (Missing font mapping packs)")

        # 5. Translation (dynamic dependency and model check)
        trans_installed = importlib.util.find_spec("ctranslate2") is not None
        trans_models = base_data / "translation" / "models"
        hi_en_model = trans_models / "hi-en"
        en_hi_model = trans_models / "en-hi"
        if trans_installed and trans_models.exists() and hi_en_model.exists() and en_hi_model.exists():
            statuses["translation"] = (True, "Ready (IndicTrans2 CTranslate2)")
        else:
            missing_parts = []
            if not trans_installed:
                missing_parts.append("ctranslate2 extra")
            if not (trans_models.exists() and hi_en_model.exists() and en_hi_model.exists()):
                missing_parts.append("model assets")
            statuses["translation"] = (False, f"Unavailable (Missing: {', '.join(missing_parts)})")

        return statuses

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
                st = "completed" if r.outcome == "success" else "failed"
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

        # Factual device execution aggregation: ONLY count phase_name == "capability_execution" records
        device_durations: dict[str, list[int]] = {}
        device_confidences: dict[str, list[float]] = {}

        for rec in maruti_records:
            if rec.phase_name == "capability_execution":
                dev = rec.attributes.get("device_type")
                if dev:
                    dev_key = str(dev).upper()
                    device_durations.setdefault(dev_key, []).append(rec.duration_ns)

        for p_rec in pramana_records:
            dev = p_rec.attributes.get("device_type")
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
        )

    @staticmethod
    def build_summary_view(
        run_id: str,
        status: str,
        wall_time_ns: int,
        request: Request,
        result: Result,
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

        # Device execution summary: strictly phase_name == "capability_execution" with device_type attribute
        device_map: dict[str, list[int]] = {}
        dev_confs: dict[str, list[float]] = {}
        for r in maruti_records:
            if r.phase_name == "capability_execution":
                dev = r.attributes.get("device_type")
                if dev:
                    dev_str = str(dev).upper()
                    device_map.setdefault(dev_str, []).append(r.duration_ns)

        for pr in pramana_records:
            dev = pr.attributes.get("device_type")
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
        avg_confidence = (
            (sum(all_confs) / len(all_confs)) if all_confs else (result.confidence.score if result.confidence else None)
        )

        # Accuracy remains None unless verified ground truth exists in metadata
        verified_acc = (
            result.metadata.get("verified_accuracy")
            if isinstance(result.metadata.get("verified_accuracy"), float)
            else None
        )

        avg_dur_per_input = int(wall_time_ns / max(1, len(request.inputs))) if wall_time_ns > 0 else None

        warnings = tuple(str(w.message) for w in result.warnings)

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
    ) -> InspectorViewState:
        """Build Screen 5: Nirikshana - Run Inspector presentation state."""
        logs: list[tuple[str, str, str, str]] = []
        stage_map: dict[str, list[int]] = {}
        device_map: dict[str, list[int]] = {}

        for r in maruti_records:
            logs.append(
                (
                    r.timestamp_utc,
                    "INFO" if r.outcome == "success" else "ERROR",
                    r.component,
                    f"Phase {r.phase_name} ({r.duration_ns / 1_000_000:.2f}ms)",
                )
            )
            stage_map.setdefault(r.phase_name, []).append(r.duration_ns)
            if r.phase_name == "capability_execution":
                dev = r.attributes.get("device_type")
                if dev:
                    device_map.setdefault(str(dev).upper(), []).append(r.duration_ns)

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
        for pr in pramana_records:
            if pr.confidence is not None:
                score = pr.confidence.score
                if score >= 0.90:
                    conf_brackets["90-100%"] += 1
                elif score >= 0.75:
                    conf_brackets["75-89%"] += 1
                elif score >= 0.50:
                    conf_brackets["50-74%"] += 1
                else:
                    conf_brackets["<50%"] += 1

        conf_dist = tuple(conf_brackets.items())

        facts = list(system_facts)
        facts.extend(
            [
                ("Total Maruti Records", str(len(maruti_records))),
                ("Total Pramana Records", str(len(pramana_records))),
                ("Measured Stages", str(len(stage_map))),
            ]
        )

        return InspectorViewState(
            run_id=run_id,
            status=status,
            elapsed_ns=elapsed_ns,
            activity_logs=tuple(logs),
            stage_timings=stage_timings,
            device_summaries=device_summaries,
            confidence_distribution=conf_dist,
            system_facts=tuple(facts),
        )
