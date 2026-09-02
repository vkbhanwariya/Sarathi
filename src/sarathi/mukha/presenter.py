"""Mukha Presenter - Pure Presentation Logic and State Projection in Sarathi V2.

Transforms canonical Request, Result, Darpana records, and Kavacha policy
into typed presentation view models. Does not mutate runtime state, execute work,
or fabricate metrics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
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
from sarathi.sankalpa import ArtifactRef, InputRef, Request, Result

# Operations running for 5 or more seconds are promoted to the long-running section
_FIVE_SECONDS_NS = 5_000_000_000
_TERMINAL_STATUSES = {"SUCCESS", "FAILED", "CANCELLED", "QUARANTINED"}
_IGNORE_FILE_SUFFIXES = frozenset({".tmp", ".crdownload", ".part", ".swp", ".bak", ".lock"})


def _is_hidden_or_temporary(path: Path) -> bool:
    """Return True if path is a hidden or temporary file."""
    name = path.name
    if name.startswith(".") or name.startswith("~$"):
        return True
    if path.suffix.lower() in _IGNORE_FILE_SUFFIXES:
        return True
    return False


def _is_subpath(child: Path, parent: Path | None) -> bool:
    """Check if child is equal to or located within parent directory."""
    if parent is None:
        return False
    try:
        child_res = child.resolve()
        parent_res = parent.resolve()
        return child_res == parent_res or parent_res in child_res.parents
    except OSError:
        return False


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
        """Convert selected filesystem paths, pasted strings, or folders into canonical InputRefs.

        Enforces T6 canonical validation rules:
        - Path normalization & pasted multiline path string expansion;
        - Directory discovery (recursive only when explicitly enabled);
        - Dynamic exclusion of active Runtime and Output roots;
        - Automatic filtering of hidden (.*) and temporary (~$*, *.tmp) files;
        - Requires regular file;
        - Factual stat().st_size (never zero fallback);
        - Deduplication by canonical resolved path;
        - Kavacha source-destination overlap validation when configured;
        - Media/format type remains None / unavailable until factual Darshana detection (no extension-as-truth).
        """
        seen_paths: set[Path] = set()
        valid_refs: list[InputRef] = []
        input_items: list[InputItemView] = []
        format_groups: dict[str, list[int]] = {}
        issues: list[tuple[str, str]] = []
        total_size = 0

        # 1. Expand input elements (supporting pasted multiline strings and quoted tokens)
        expanded_candidates: list[Path] = []
        for raw in paths:
            if isinstance(raw, Path):
                expanded_candidates.append(raw)
            elif isinstance(raw, str):
                for line in raw.splitlines():
                    cleaned = line.strip().strip('"\'')
                    if cleaned:
                        expanded_candidates.append(Path(cleaned))
            else:
                issues.append(("<invalid>", f"invalid path type {type(raw).__name__}"))

        # 2. Validate path overlap via Kavacha if supplied
        if kavacha is not None and expanded_candidates:
            dest_roots: list[Path] = []
            if runtime_root is not None:
                dest_roots.append(runtime_root)
            if output_root is not None:
                dest_roots.append(output_root)
            if dest_roots:
                kavacha.validate_source_destination_overlap(expanded_candidates, dest_roots)

        # 3. Discover files from candidates
        for p in expanded_candidates:
            try:
                resolved = p.resolve()
            except OSError:
                issues.append((p.name or str(p), "cannot resolve path"))
                continue

            if not resolved.exists():
                issues.append((p.name or str(p), "does not exist"))
                continue

            # Check if candidate is within active Output or Runtime root
            if _is_subpath(resolved, runtime_root):
                issues.append((p.name or str(p), "path is inside runtime root"))
                continue
            if _is_subpath(resolved, output_root):
                issues.append((p.name or str(p), "path is inside output root"))
                continue

            if resolved.is_dir():
                # Discover files inside selected directory
                try:
                    dir_iterator = resolved.rglob("*") if recursive else resolved.iterdir()
                    found_files = sorted(dir_iterator, key=lambda x: str(x))
                except OSError:
                    issues.append((p.name or str(p), "failed to read directory contents"))
                    continue

                folder_added = 0
                for child in found_files:
                    try:
                        child_res = child.resolve()
                    except OSError:
                        continue

                    # Exclude active roots inside scanned folders
                    if _is_subpath(child_res, runtime_root) or _is_subpath(child_res, output_root):
                        continue

                    # Ignore hidden / temporary files
                    if _is_hidden_or_temporary(child_res):
                        continue

                    if not child_res.is_file():
                        continue

                    if child_res in seen_paths:
                        continue

                    try:
                        st = child_res.stat()
                        size = st.st_size
                    except OSError:
                        issues.append((child_res.name, "failed to inspect file size"))
                        continue

                    seen_paths.add(child_res)
                    total_size += size
                    folder_added += 1
                    inp_id = f"inp-{len(valid_refs) + 1}"
                    ref = InputRef(
                        input_id=inp_id,
                        source_path=child_res,
                        display_name=child_res.name,
                        size_bytes=size,
                        media_type=None,
                    )
                    valid_refs.append(ref)
                    input_items.append(
                        InputItemView(
                            input_id=inp_id,
                            display_name=child_res.name,
                            size_bytes=size,
                            media_type=None,
                            is_eligible=True,
                        )
                    )

                if folder_added == 0:
                    issues.append((p.name or str(p), "not a regular file"))
                continue

            # Candidate is a direct file
            if not resolved.is_file():
                issues.append((p.name, "not a regular file"))
                continue

            if _is_hidden_or_temporary(resolved):
                issues.append((p.name, "hidden or temporary file ignored"))
                continue

            if resolved in seen_paths:
                issues.append((p.name, "duplicate input path"))
                continue

            try:
                st = resolved.stat()
                size = st.st_size
            except OSError:
                issues.append((p.name, "failed to inspect file size"))
                continue

            seen_paths.add(resolved)
            total_size += size

            inp_id = f"inp-{len(valid_refs) + 1}"
            ref = InputRef(
                input_id=inp_id,
                source_path=resolved,
                display_name=p.name,
                size_bytes=size,
                media_type=None,
            )
            valid_refs.append(ref)
            input_items.append(
                InputItemView(
                    input_id=inp_id,
                    display_name=p.name,
                    size_bytes=size,
                    media_type=None,
                    is_eligible=True,
                )
            )

        total_files = len(valid_refs) + len(issues)

        groups = tuple(
            InputGroupView(format_name=fmt, file_count=len(sizes), total_size_bytes=sum(sizes))
            for fmt, sizes in sorted(format_groups.items())
        )
        is_grouped = len(groups) > 0 and total_files > 10

        preflight = PreflightView(
            eligible_count=len(valid_refs),
            issue_count=len(issues),
            issues=tuple(issues),
        )

        selection = InputSelectionView(
            total_files=total_files,
            total_size_bytes=total_size,
            is_grouped=is_grouped,
            groups=groups,
            items=tuple(input_items),
        )

        return tuple(valid_refs), selection, preflight

    @staticmethod
    def build_home_view(
        input_selection: InputSelectionView,
        requirement: str = "read_native",
        policy_label: str = "Local only",
        preflight: PreflightView | None = None,
        available_actions: Sequence[AvailableActionView] = (),
    ) -> ApplicationViewState:
        """Build Screen 1: Griha - Home & Input Setup presentation state purely from supplied facts."""
        return ApplicationViewState(
            current_screen="home",
            requirement=requirement,
            policy_label=policy_label,
            input_selection=input_selection,
            preflight=preflight,
            available_actions=tuple(available_actions),
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

        # 5-second rule: filter long running operations (elapsed_ns >= 5s)
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
                last_activity=None,
            )
            if is_long:
                long_running.append(op)
            if current_focus is None:
                current_focus = op

        terminal_files = sum(1 for f in files if f.status in ("success", "failed", "quarantined", "cancelled"))

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
                        role=art.role,
                        display_name=art.path.name,
                        size_bytes=art.size_bytes,
                        sha256_hex=art.checksum_sha256,
                    )
                )

        # Confidence from result or pramana records
        all_confs = [pr.confidence.score for pr in pramana_records if pr.confidence is not None]
        avg_confidence = (sum(all_confs) / len(all_confs)) if all_confs else (result.confidence.score if result.confidence else None)

        # Accuracy remains None unless verified ground truth exists in metadata
        verified_acc = result.metadata.get("verified_accuracy") if isinstance(result.metadata.get("verified_accuracy"), float) else None

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
            StageTimingView(stage_name=k, duration_ns=sum(v), call_count=len(v))
            for k, v in sorted(stage_map.items())
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
        facts.extend([
            ("Total Maruti Records", str(len(maruti_records))),
            ("Total Pramana Records", str(len(pramana_records))),
            ("Measured Stages", str(len(stage_map))),
        ])

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
