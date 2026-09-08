/**
 * Screen 4: Samapti (Terminal Summary & Artifacts) Controller for Mukha.
 */

import { apiGet, apiPost } from "../api.js";
import { elements, showError } from "../dom.js";
import { escapeHtml, formatBytes, formatDuration } from "../formatters.js";
import { openDocumentPreview } from "../preview.js";
import { state, switchScreen } from "../state.js";
import { toggleHistoryDrawer } from "./inspector.js";

export async function handleOpenOutputFolder() {
    const targetId = state.viewedRunId || state.activeRunId;
    if (!targetId) return;
    const res = await apiPost(`/api/runs/${encodeURIComponent(targetId)}/reveal`);
    if (!res.ok || res.revealed !== true) {
        showError(res.error || "Failed to reveal output folder or directory does not exist.");
    }
}

export async function loadRunSummary(runId) {
    if (!runId) return;
    const seq = ++state.summaryRequestSeq;
    state.viewedRunId = runId;
    if (runId !== state.activeRunId) {
        state.followLive = false;
    }
    const res = await apiGet(`/api/runs/${encodeURIComponent(runId)}/summary`);
    if (seq !== state.summaryRequestSeq) return;
    if (res.ok && res.summary) {
        renderSummary(res.summary);
        switchScreen("summary");
    } else {
        showError(res.error || `Failed to load summary for run ${runId}.`);
    }
}

export function renderSummary(summary) {
    if (!summary) return;
    state.viewedRunId = summary.run_id;

    const isSuccess = summary.status === "SUCCESS";
    const isWarning = summary.status === "WARNING" || summary.status === "PARTIAL" || summary.status === "CANCELLED";

    if (elements.summaryStatusBadge) {
        elements.summaryStatusBadge.textContent = summary.status;
        elements.summaryStatusBadge.className = `badge badge-hero ${
            isSuccess ? "badge-emerald" : isWarning ? "badge-amber" : "badge-crimson"
        }`;
    }

    if (elements.summaryHero) {
        elements.summaryHero.className = `summary-hero status-${(summary.status || "failed").toLowerCase()}`;
    }

    if (elements.summaryTitle) {
        if (summary.status === "SUCCESS") {
            elements.summaryTitle.textContent = "Run Completed Successfully";
        } else if (summary.status === "PARTIAL" || summary.status === "WARNING") {
            elements.summaryTitle.textContent = "Run Completed with Warnings";
        } else if (summary.status === "CANCELLED") {
            elements.summaryTitle.textContent = "Run Cancelled";
        } else if (summary.status === "QUARANTINED") {
            elements.summaryTitle.textContent = "Run Quarantined";
        } else {
            elements.summaryTitle.textContent = `Run Failed (${summary.status || "FAILED"})`;
        }
    }

    if (elements.summaryRunMeta) {
        const wallTime = summary.wall_time_ns !== undefined && summary.wall_time_ns !== null
            ? formatDuration(summary.wall_time_ns)
            : "—";
        elements.summaryRunMeta.textContent = `Run ID: ${summary.run_id} | Total Wall Time: ${wallTime}`;
    }

    const failures = summary.failures || [];
    const warnings = summary.warnings || [];

    if (elements.summaryFailureReason) {
        if (failures.length > 0) {
            elements.summaryFailureReason.textContent = typeof failures[0] === "string" ? failures[0] : (failures[0].message || JSON.stringify(failures[0]));
            elements.summaryFailureReason.classList.remove("hidden");
        } else {
            elements.summaryFailureReason.textContent = "";
            elements.summaryFailureReason.classList.add("hidden");
        }
    }

    if (elements.summaryAlertsContainer) {
        if (failures.length > 0 || warnings.length > 0) {
            elements.summaryAlertsContainer.classList.remove("hidden");
            let alertsHtml = "";
            if (failures.length > 0) {
                alertsHtml += `
                    <div style="background: rgba(239, 68, 68, 0.12); border: 1px solid var(--accent-crimson); border-radius: var(--radius-md); padding: 12px 16px; margin-bottom: 8px;">
                        <strong style="color: var(--accent-crimson); display: block; margin-bottom: 4px;">⚠️ Failures Detected:</strong>
                        <ul style="margin: 0; padding-left: 20px; font-size: 0.88rem; color: var(--text-primary);">
                            ${failures.map((f) => `<li>${escapeHtml(typeof f === "string" ? f : f.message || JSON.stringify(f))}</li>`).join("")}
                        </ul>
                    </div>
                `;
            }
            if (warnings.length > 0) {
                alertsHtml += `
                    <div style="background: rgba(245, 158, 11, 0.12); border: 1px solid var(--accent-amber); border-radius: var(--radius-md); padding: 12px 16px;">
                        <strong style="color: var(--accent-amber); display: block; margin-bottom: 4px;">⚠️ Execution Warnings:</strong>
                        <ul style="margin: 0; padding-left: 20px; font-size: 0.88rem; color: var(--text-primary);">
                            ${warnings.map((w) => `<li>${escapeHtml(typeof w === "string" ? w : w.message || JSON.stringify(w))}</li>`).join("")}
                        </ul>
                    </div>
                `;
            }
            elements.summaryAlertsContainer.innerHTML = alertsHtml;
        } else {
            elements.summaryAlertsContainer.classList.add("hidden");
            elements.summaryAlertsContainer.innerHTML = "";
        }
    }

    if (elements.statTotalFiles) elements.statTotalFiles.textContent = summary.total_inputs || 0;
    if (elements.statSuccessFiles) elements.statSuccessFiles.textContent = summary.successful_files ?? "—";
    if (elements.statWarningFiles) elements.statWarningFiles.textContent = summary.warning_files ?? "—";
    if (elements.statFailedFiles) elements.statFailedFiles.textContent = summary.failed_files ?? "—";

    if (elements.statConfidence) {
        if (typeof summary.avg_confidence === "number" && !isNaN(summary.avg_confidence)) {
            const pct = (summary.avg_confidence * 100).toFixed(1);
            elements.statConfidence.textContent = `${pct}%`;
            elements.statConfidence.className = `stat-value ${
                summary.avg_confidence >= 0.90
                    ? "text-emerald"
                    : summary.avg_confidence >= 0.75
                    ? "text-cyan"
                    : "text-amber"
            }`;
        } else {
            elements.statConfidence.textContent = "—";
            elements.statConfidence.className = "stat-value text-muted";
        }
    }

    if (elements.statAccuracy) {
        if (typeof summary.accuracy === "number" && !isNaN(summary.accuracy)) {
            const pct = (summary.accuracy * 100).toFixed(1);
            elements.statAccuracy.textContent = `${pct}%`;
            elements.statAccuracy.className = `stat-value ${
                summary.accuracy >= 0.90
                    ? "text-emerald"
                    : summary.accuracy >= 0.75
                    ? "text-cyan"
                    : "text-amber"
            }`;
        } else {
            elements.statAccuracy.textContent = "—";
            elements.statAccuracy.className = "stat-value text-muted";
        }
    }

    // Output Artifacts Grid with Preview & Download Actions
    if (elements.artifactsGrid) {
        if (summary.artifacts && summary.artifacts.length > 0) {
            elements.artifactsGrid.innerHTML = summary.artifacts
                .map((art) => `
                    <div class="artifact-card">
                        <div class="artifact-title">${escapeHtml(art.display_name)}</div>
                        <div class="artifact-meta">
                            <span>Role: <strong>${escapeHtml(art.role)}</strong></span>
                            <span>${formatBytes(art.size_bytes)}</span>
                        </div>
                        <div class="artifact-actions">
                            <button class="btn btn-primary btn-sm btn-preview-artifact" data-run-id="${escapeHtml(summary.run_id)}" data-art-id="${escapeHtml(art.artifact_id)}" data-name="${escapeHtml(art.display_name)}">👁️ Preview</button>
                            <a class="btn btn-outline btn-sm" href="/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(art.artifact_id)}" download="${escapeHtml(art.display_name)}">⬇ Download</a>
                        </div>
                    </div>
                `)
                .join("");
        } else {
            elements.artifactsGrid.innerHTML = '<div class="empty-card" style="grid-column: 1/-1; text-align: center; padding: 24px; color: var(--text-muted);">No output artifacts generated.</div>';
        }
    }

    // Hardware Performance (CPU / GPU Breakdown)
    if (elements.summaryDeviceTbody) {
        if (summary.device_summaries && summary.device_summaries.length > 0) {
            elements.summaryDeviceTbody.innerHTML = summary.device_summaries
                .map((d) => {
                    const isGpu = (d.device_type || "").toUpperCase().includes("GPU") || (d.device_type || "").toUpperCase().includes("CUDA");
                    const devBadge = isGpu
                        ? `<span class="badge badge-emerald">🟢 ${escapeHtml(d.device_type)}</span>`
                        : `<span class="badge badge-indigo">💻 ${escapeHtml(d.device_type)}</span>`;
                    const avgConfStr = typeof d.avg_confidence === "number" && !isNaN(d.avg_confidence)
                        ? `<span class="${d.avg_confidence >= 0.9 ? 'text-emerald' : d.avg_confidence >= 0.75 ? 'text-cyan' : 'text-amber'}">${(d.avg_confidence * 100).toFixed(1)}%</span>`
                        : "—";
                    return `<tr>
                        <td><strong>${devBadge}</strong></td>
                        <td>${d.execution_count} units</td>
                        <td>${formatDuration(d.avg_duration_ns)}</td>
                        <td>${formatDuration(d.p95_duration_ns)}</td>
                        <td><strong>${avgConfStr}</strong></td>
                    </tr>`;
                })
                .join("");
        } else {
            elements.summaryDeviceTbody.innerHTML = '<tr class="empty-row"><td colspan="5">No hardware execution records.</td></tr>';
        }
    }

    // Stage Breakdown Table
    if (elements.summaryStagesTbody) {
        if (summary.stage_timings && summary.stage_timings.length > 0) {
            elements.summaryStagesTbody.innerHTML = summary.stage_timings
                .map((st) => `<tr>
                    <td><strong>${escapeHtml(st.stage_name)}</strong></td>
                    <td>${st.call_count} calls</td>
                    <td>${formatDuration(st.duration_ns)}</td>
                    <td>${formatDuration(st.call_count > 0 ? Math.round(st.duration_ns / st.call_count) : 0)}</td>
                </tr>`)
                .join("");
        } else {
            elements.summaryStagesTbody.innerHTML = '<tr class="empty-row"><td colspan="4">No stage timings recorded.</td></tr>';
        }
    }
}

export function initSummaryScreen() {
    if (elements.btnOpenOutputFolder) {
        elements.btnOpenOutputFolder.addEventListener("click", handleOpenOutputFolder);
    }
    if (elements.btnReturnHome) {
        elements.btnReturnHome.addEventListener("click", () => switchScreen("home"));
    }
    if (elements.btnSummaryHistory) {
        elements.btnSummaryHistory.addEventListener("click", () => toggleHistoryDrawer(true));
    }
    if (elements.artifactsGrid) {
        elements.artifactsGrid.addEventListener("click", (e) => {
            const btnPreview = e.target.closest(".btn-preview-artifact");
            if (btnPreview) {
                const runId = btnPreview.dataset.runId;
                const artId = btnPreview.dataset.artId;
                const name = btnPreview.dataset.name;
                if (runId && artId) {
                    openDocumentPreview(`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artId)}/preview`, name);
                }
            }
        });
    }
}
