/**
 * Screen 2: Pravritti (Live Execution Monitor) Controller for Mukha.
 */

import { apiPost } from "../api.js";
import { elements, hideError, renderProgressBar, showError } from "../dom.js";
import { escapeHtml, formatDuration, formatStatus } from "../formatters.js";
import { state } from "../state.js";

export function handleCancelRun() {
    if (!state.activeRunId || !elements.cancelRunDialog) return;
    if (typeof elements.cancelRunDialog.showModal === "function") {
        elements.cancelRunDialog.showModal();
    } else {
        confirmCancelRun();
    }
}

export async function confirmCancelRun() {
    if (elements.cancelRunDialog && typeof elements.cancelRunDialog.close === "function") {
        elements.cancelRunDialog.close();
    }
    if (!state.activeRunId) return;
    if (elements.btnCancelRun) elements.btnCancelRun.disabled = true;
    if (elements.monitorStatusBadge) {
        elements.monitorStatusBadge.textContent = "Cancellation requested";
        elements.monitorStatusBadge.className = "badge badge-amber";
    }
    hideError();

    const res = await apiPost(`/api/runs/${encodeURIComponent(state.activeRunId)}/cancel`);
    if (!res.ok) {
        showError(res.error || "Failed to cancel run.");
        if (elements.btnCancelRun) elements.btnCancelRun.disabled = false;
    }
}

let previousRunStatus = "IDLE";

export function requestNotificationPermission() {
    if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
    }
}

export function renderMonitor(activeRun) {
    if (!activeRun) return;

    if (previousRunStatus === "RUNNING" && (activeRun.status === "SUCCESS" || activeRun.status === "FAILED")) {
        if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
            try {
                new Notification(`Sarathi Processing ${activeRun.status}`, {
                    body: `Run ${activeRun.run_id || ""} finished in ${formatDuration(activeRun.elapsed_ns)}.`,
                });
            } catch (e) {
                // Ignore browser notification dispatch errors
            }
        }
    }
    previousRunStatus = activeRun.status;

    state.activeRunId = activeRun.run_id;
    state.activeRunStatus = activeRun.status;
    if (elements.monitorRunId) elements.monitorRunId.textContent = activeRun.run_id;
    if (elements.monitorStatusBadge) {
        if (activeRun.status === "CANCELLED") {
            elements.monitorStatusBadge.textContent = "Run cancelled";
            elements.monitorStatusBadge.className = "badge badge-amber";
        } else {
            const st = formatStatus(activeRun.status);
            elements.monitorStatusBadge.textContent = st.label;
            elements.monitorStatusBadge.className = st.className;
        }
    }
    if (elements.monitorElapsedTime) elements.monitorElapsedTime.textContent = formatDuration(activeRun.elapsed_ns);
    if (elements.btnCancelRun) elements.btnCancelRun.disabled = activeRun.status !== "RUNNING";

    // Factual Progress Bar from Server State
    const progState = activeRun.progress || {
        kind: "known",
        completed: activeRun.terminal_files || 0,
        total: activeRun.total_files || 0,
        percentage: (activeRun.total_files > 0 ? ((activeRun.terminal_files || 0) / activeRun.total_files) * 100 : 0)
    };
    renderProgressBar(elements.monitorProgressContainer, elements.monitorProgressBar, null, null, progState);

    // Focus Stage
    if (activeRun.current_focus) {
        if (elements.focusStageName) elements.focusStageName.textContent = activeRun.current_focus.stage || "—";
        if (elements.focusFileName) elements.focusFileName.textContent = activeRun.current_focus.operation_name || "—";
        if (elements.focusDeviceType) elements.focusDeviceType.textContent = activeRun.current_focus.device_type || "—";
        if (elements.focusDuration) elements.focusDuration.textContent = formatDuration(activeRun.current_focus.elapsed_ns);
    } else {
        if (elements.focusStageName) elements.focusStageName.textContent = "—";
        if (elements.focusFileName) elements.focusFileName.textContent = "—";
        if (elements.focusDeviceType) elements.focusDeviceType.textContent = "—";
        if (elements.focusDuration) elements.focusDuration.textContent = "0.0s";
    }

    // Long-running Alert (>5s)
    if (elements.longRunningAlert && elements.longRunningDesc) {
        if (activeRun.long_running && activeRun.long_running.length > 0) {
            elements.longRunningAlert.classList.remove("hidden");
            elements.longRunningDesc.textContent = activeRun.long_running
                .map((lr) => `${lr.operation_name} (${formatDuration(lr.elapsed_ns)})`)
                .join(", ");
        } else {
            elements.longRunningAlert.classList.add("hidden");
        }
    }

    // Device Throughput Table
    if (elements.deviceThroughputTbody && activeRun.device_progress && activeRun.device_progress.length > 0) {
        elements.deviceThroughputTbody.innerHTML = activeRun.device_progress
            .map((dp) => `<tr>
                <td><strong>${escapeHtml(dp.device_type || "—")}</strong></td>
                <td>${dp.execution_count} units</td>
                <td>${formatDuration(dp.total_duration_ns)}</td>
                <td>${formatDuration(dp.avg_duration_ns)}</td>
            </tr>`)
            .join("");
    }

    // Active Parallel Workers
    if (elements.activeWorkersTbody && elements.activeWorkersCount) {
        if (activeRun.active_workers && activeRun.active_workers.length > 0) {
            elements.activeWorkersCount.textContent = `${activeRun.active_workers.length} Active`;
            elements.activeWorkersTbody.innerHTML = activeRun.active_workers
                .map((w) => {
                    const devBadge = (w.device_type === "GPU" || w.device_type === "NPU")
                        ? `<span class="badge badge-emerald">${escapeHtml(w.device_type)}</span>`
                        : `<span class="badge">${escapeHtml(w.device_type || "—")}</span>`;
                    const pageText = w.page_number ? `<span class="badge badge-indigo">Page ${w.page_number}</span>` : "—";
                    return `<tr>
                        <td><strong>Worker ${escapeHtml(w.worker_id)}</strong></td>
                        <td>${escapeHtml(w.file_display_name || "—")}</td>
                        <td>${pageText}</td>
                        <td>${escapeHtml(w.stage || "—")}</td>
                        <td>${devBadge}</td>
                        <td><span class="badge badge-indigo">${escapeHtml(w.status || "active")}</span></td>
                    </tr>`;
                })
                .join("");
        } else {
            elements.activeWorkersCount.textContent = "0 Active";
            elements.activeWorkersTbody.innerHTML = '<tr class="empty-row"><td colspan="6">No active workers.</td></tr>';
        }
    }

    // Document Execution Pipeline Table
    if (elements.filePipelineTbody && elements.pipelineCounts && activeRun.files && activeRun.files.length > 0) {
        elements.pipelineCounts.textContent = `${activeRun.terminal_files || 0} / ${activeRun.total_files || activeRun.files.length} completed`;
        elements.filePipelineTbody.innerHTML = activeRun.files
            .map((f) => {
                let stBadge = `<span class="badge">${escapeHtml(f.status)}</span>`;
                if (f.status === "SUCCESS") stBadge = '<span class="badge badge-emerald">SUCCESS</span>';
                else if (f.status === "RUNNING") stBadge = '<span class="badge badge-indigo">RUNNING</span>';
                else if (f.status === "FAILED") stBadge = '<span class="badge badge-crimson">FAILED</span>';

                const warns = f.warning_count > 0 ? `<span class="badge badge-amber">${f.warning_count} warns</span>` : "—";
                return `<tr>
                    <td>${f.ordinal}</td>
                    <td><strong>${escapeHtml(f.display_name)}</strong></td>
                    <td>${escapeHtml(f.current_stage || "—")}</td>
                    <td>${stBadge}</td>
                    <td>${formatDuration(f.elapsed_ns)}</td>
                    <td>${warns}</td>
                </tr>`;
            })
            .join("");
    }
}

export function initMonitorScreen() {
    if (elements.btnCancelRun) {
        elements.btnCancelRun.addEventListener("click", handleCancelRun);
    }
    if (elements.btnCancelDialogConfirm) {
        elements.btnCancelDialogConfirm.addEventListener("click", confirmCancelRun);
    }
    if (elements.btnCancelDialogDismiss) {
        elements.btnCancelDialogDismiss.addEventListener("click", () => {
            if (elements.cancelRunDialog && typeof elements.cancelRunDialog.close === "function") {
                elements.cancelRunDialog.close();
            }
        });
    }
}
