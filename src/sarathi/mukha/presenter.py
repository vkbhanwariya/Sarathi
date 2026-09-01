"""Mukha Presenter - Pure Presentation Logic and State Projection in Sarathi V2.

Transforms canonical Request, Result, Darpana records, and Kavacha policy
into typed presentation view models. Does not mutate runtime state or execute work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.kavacha import SecurityPolicy
from sarathi.mukha.state import (
    ApplicationViewState,
    ArtifactOutcomeView,
    AvailableActionView,
    DeviceProgressView,
    DeviceSummaryView,
    FileRunView,
    InputGroupView,
    InputItemView,
    InputSelectionView,
    InspectorViewState,
    OCRProfileEvidenceView,
    OperationView,
    PreflightView,
    ProgressKind,
    ProgressState,
    RunSummaryView,
    RunViewState,
    StageTimingView,
    WorkerPageView,
)
from sarathi.nabhi.quarantine import QuarantineRecord, QuarantineStatus
from sarathi.sankalpa import ArtifactIntent, ArtifactRef, InputRef, Request, Result

# Operations running for 5 or more seconds are promoted to the long-running section
_FIVE_SECONDS_NS = 5_000_000_000


class MukhaPresenter:
    """Pure presenter projecting runtime facts into immutable presentation models."""

    @staticmethod
    def build_home_view(
        inputs: Sequence[InputRef | Path | str],
        requirement: str = "read_native",
        policy: SecurityPolicy | None = None,
        ocr_evidence: Mapping[str, OCRProfileEvidenceView] | None = None,
        available_actions: Sequence[AvailableActionView] | None = None,
    ) -> ApplicationViewState:
        """Build Screen 1: Griha - Home & Input Setup presentation state."""
        input_items: list[InputItemView] = []
        format_groups: dict[str, list[int]] = {}  # format -> [sizes]
        total_size = 0

        for i, raw_inp in enumerate(inputs):
            if isinstance(raw_inp, InputRef):
                path = raw_inp.source_path
                display = raw_inp.display_name
                size = raw_inp.size_bytes
                media = raw_inp.media_type
                inp_id = raw_inp.input_id
            else:
                path = Path(raw_inp)
                display = path.name
                inp_id = f"inp-{i+1}"
                media = None
                try:
                    size = path.stat().st_size if path.exists() else 0
                except OSError:
                    size = 0

            # Preflight inspection
            exists = path.exists() if isinstance(path, Path) else True
            is_file = path.is_file() if isinstance(path, Path) and exists else True
            eligible = exists and is_file
            issue = None
            if not exists:
                issue = "unreadable (does not exist)"
            elif not is_file:
                issue = "unsupported (not a regular file)"

            fmt = (path.suffix.upper().lstrip(".") if isinstance(path, Path) and path.suffix else "UNKNOWN")
            format_groups.setdefault(fmt, []).append(size)
            total_size += size

            input_items.append(
                InputItemView(
                    input_id=inp_id,
                    display_name=display,
                    size_bytes=size,
                    media_type=media,
                    is_eligible=eligible,
                    issue_reason=issue,
                )
            )

        total_files = len(input_items)
        is_grouped = total_files > 10

        groups = tuple(
            InputGroupView(
                format_name=fmt,
                file_count=len(sizes),
                total_size_bytes=sum(sizes),
            )
            for fmt, sizes in sorted(format_groups.items())
        )

        ineligible = [item for item in input_items if not item.is_eligible]
        preflight = PreflightView(
            eligible_count=total_files - len(ineligible),
            issue_count=len(ineligible),
            issues=tuple((item.display_name, item.issue_reason or "unknown issue") for item in ineligible),
        )

        selection = InputSelectionView(
            total_files=total_files,
            total_size_bytes=total_size,
            is_grouped=is_grouped,
            groups=groups,
            items=tuple(input_items),
        )

        policy_label = "Local only"
        if policy is not None and (policy.allow_network_access or policy.allow_external_processing):
            policy_label = "Network / External enabled"

        actions = available_actions or (
            AvailableActionView(action_id="start_run", label="Start Eligible Files", is_enabled=preflight.eligible_count > 0),
            AvailableActionView(action_id="view_all", label="View All Files", is_enabled=total_files > 0),
        )

        return ApplicationViewState(
            current_screen="home",
            requirement=requirement,
            policy_label=policy_label,
            input_selection=selection,
            preflight=preflight,
            available_actions=tuple(actions),
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
    ) -> RunViewState:
        """Build Screen 2: Pravritti - Live Run Monitor presentation state."""
        elapsed_ns = max(0, now_ns - started_at_ns)

        # Factual device progress aggregation from recorded records
        device_durations: dict[str, list[int]] = {}
        device_confidences: dict[str, list[float]] = {}

        for rec in maruti_records:
            dev = rec.attributes.get("device_type")
            if dev:
                dev_key = str(dev).upper()
                device_durations.setdefault(dev_key, []).append(rec.duration_ns)

        for p_rec in pramana_records:
            dev = p_rec.attributes.get("device_type", "CPU")
            if p_rec.confidence is not None:
                device_confidences.setdefault(str(dev).upper(), []).append(p_rec.confidence.score)

        device_progress: list[DeviceProgressView] = []
        for dev_type, durs in sorted(device_durations.items()):
            unit_count = len(durs)
            tot_dur = sum(durs)
            avg_dur = int(tot_dur / unit_count) if unit_count > 0 else None
            confs = device_confidences.get(dev_type, [])
            avg_conf = (sum(confs) / len(confs)) if confs else None

            device_progress.append(
                DeviceProgressView(
                    device_type=dev_type,
                    units_processed=unit_count,
                    total_duration_ns=tot_dur,
                    avg_duration_ns=avg_dur,
                    avg_confidence=avg_conf,
                )
            )

        # 5-second rule: filter long running operations
        long_running: list[OperationView] = []
        current_focus: OperationView | None = None

        for w in active_workers:
            is_long = w.elapsed_ns >= _FIVE_SECONDS_NS
            op = OperationView(
                operation_name=f"Worker {w.worker_id} - {w.file_display_name}",
                stage=w.stage,
                device_type=w.device_type,
                elapsed_ns=w.elapsed_ns,
                is_long_running=is_long,
                last_activity=f"Processing {w.stage}",
            )
            if is_long:
                long_running.append(op)
            if current_focus is None:
                current_focus = op

        terminal_files = sum(1 for f in files if f.status in ("success", "failed", "quarantined"))

        return RunViewState(
            run_id=run_id,
            status=status,
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
        request: Request,
        result: Result,
        maruti_records: Sequence[MarutiRecord] = (),
        pramana_records: Sequence[PramanaRecord] = (),
        quarantine_records: Sequence[QuarantineRecord] = (),
    ) -> RunSummaryView:
        """Build Screen 4: Samapti - Run Summary presentation state."""
        # Calculate wall time from actual maruti records
        if maruti_records:
            tot_dur = sum(r.duration_ns for r in maruti_records if r.duration_ns >= 0)
        else:
            tot_dur = 0

        # Stage timings aggregation
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

        # Device execution summary (factual GPU/NPU/CPU facts only when measured)
        device_map: dict[str, list[int]] = {}
        dev_confs: dict[str, list[float]] = {}
        for r in maruti_records:
            dev = r.attributes.get("device_type")
            if dev:
                dev_str = str(dev).upper()
                device_map.setdefault(dev_str, []).append(r.duration_ns)

        for pr in pramana_records:
            dev = pr.attributes.get("device_type", "CPU")
            if pr.confidence is not None:
                dev_confs.setdefault(str(dev).upper(), []).append(pr.confidence.score)

        device_summaries: list[DeviceSummaryView] = []
        for dev_k, durs in sorted(device_map.items()):
            unit_c = len(durs)
            avg_d = int(sum(durs) / unit_c) if unit_c > 0 else None
            sorted_d = sorted(durs)
            p95_idx = int(0.95 * len(sorted_d))
            p95_d = sorted_d[min(p95_idx, len(sorted_d) - 1)] if sorted_d else None
            confs = dev_confs.get(dev_k, [])
            avg_c = (sum(confs) / len(confs)) if confs else None

            device_summaries.append(
                DeviceSummaryView(
                    device_type=dev_k,
                    unit_count=unit_c,
                    attempts=unit_c,
                    avg_duration_ns=avg_d,
                    p95_duration_ns=p95_d,
                    avg_confidence=avg_c,
                )
            )

        # Artifacts from Result
        artifacts: list[ArtifactOutcomeView] = []
        for art in result.artifacts:
            if isinstance(art, ArtifactRef):
                artifacts.append(
                    ArtifactOutcomeView(
                        artifact_type=art.role,
                        display_name=art.path.name,
                        size_bytes=art.size_bytes,
                        sha256_hex=art.checksum_sha256 or "",
                    )
                )
            elif isinstance(art, ArtifactIntent):
                artifacts.append(
                    ArtifactOutcomeView(
                        artifact_type=art.role,
                        display_name=art.name,
                        size_bytes=int(art.metadata.get("size_bytes", 0)),
                        sha256_hex=str(art.metadata.get("sha256", "")),
                    )
                )

        # Confidence & Accuracy
        all_confs = [pr.confidence.score for pr in pramana_records if pr.confidence is not None]
        avg_confidence = (sum(all_confs) / len(all_confs)) if all_confs else (result.confidence.score if result.confidence else None)

        # Accuracy remains None unless verified in result metadata
        verified_acc = result.metadata.get("verified_accuracy") if isinstance(result.metadata.get("verified_accuracy"), float) else None

        quarantined_count = sum(1 for q in quarantine_records if q.status == QuarantineStatus.QUARANTINED)
        retry_count = sum(q.attempt_count for q in quarantine_records)

        failed_records = [r for r in maruti_records if r.outcome == "failure"]
        status = "SUCCESS" if not failed_records else ("PARTIAL" if len(failed_records) < len(maruti_records) else "FAILED")

        warnings = tuple(str(w.message) for w in result.warnings)

        return RunSummaryView(
            run_id=run_id,
            status=status,
            wall_time_ns=tot_dur,
            total_inputs=len(request.inputs),
            successful_files=len(request.inputs) - len(failed_records),
            warning_files=len(result.warnings),
            failed_files=len(failed_records),
            quarantined_count=quarantined_count,
            retry_count=retry_count,
            avg_page_time_ns=int(tot_dur / max(1, len(request.inputs))),
            avg_confidence=avg_confidence,
            accuracy=verified_acc,
            stage_timings=stage_timings,
            device_summaries=tuple(device_summaries),
            artifacts=tuple(artifacts),
            warnings=warnings,
            failures=tuple(r.attributes.get("error_message", "execution failure") for r in failed_records),
        )

    @staticmethod
    def build_inspector_view(
        run_id: str,
        status: str,
        elapsed_ns: int,
        maruti_records: Sequence[MarutiRecord] = (),
        pramana_records: Sequence[PramanaRecord] = (),
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
            dev = r.attributes.get("device_type")
            if dev:
                device_map.setdefault(str(dev).upper(), []).append(r.duration_ns)

        stage_timings = tuple(
            StageTimingView(stage_name=k, duration_ns=sum(v), call_count=len(v))
            for k, v in sorted(stage_map.items())
        )

        device_summaries = tuple(
            DeviceSummaryView(
                device_type=dev_k,
                unit_count=len(durs),
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

        system_facts = (
            ("Total Maruti Records", str(len(maruti_records))),
            ("Total Pramana Records", str(len(pramana_records))),
            ("Measured Stages", str(len(stage_map))),
        )

        return InspectorViewState(
            run_id=run_id,
            status=status,
            elapsed_ns=elapsed_ns,
            activity_logs=tuple(logs),
            stage_timings=stage_timings,
            device_summaries=device_summaries,
            confidence_distribution=conf_dist,
            system_facts=system_facts,
        )
