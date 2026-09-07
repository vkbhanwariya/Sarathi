/**
 * Screen 4: Samapti (Terminal Summary & Artifacts) Controller for Mukha.
 */

import { apiPost } from "../api.js";
import { elements, showError } from "../dom.js";
import { escapeHtml, formatBytes, formatDuration } from "../formatters.js";
import { openDocumentPreview } from "../preview.js";
import { state, switchScreen } from "../state.js";

export async function handleOpenOutputFolder() {
    if (!state.activeRunId) return;
    const res = await apiPost(`/api/runs/${encodeURIComponent(state.activeRunId)}/reveal`);
    if (!res.ok) {
        showError(res.error || "Failed to reveal output folder.");
    }
}

export function renderSummary(summary) {
    if (!summary) return;
    state.activeRunId = summary.run_id;

    if (elements.summaryStatusBadge) {
        elements.summaryStatusBadge.textContent = summary.status;
        elements.summaryStatusBadge.className = `badge badge-hero ${
            summary.status === "SUCCESS"
                ? "badge-emerald"
                : summary.status === "PARTIAL"
                ? "badge-amber"
                : "badge-crimson"
        }`;
    }

    if (elements.summaryHero) {
        elements.summaryHero.className = `summary-hero status-${summary.status.toLowerCase()}`;
    }

    if (elements.summaryTitle) {
        elements.summaryTitle.textContent =
            summary.status === "SUCCESS"
                ? "Run Completed Successfully"
                : summary.status === "PARTIAL"
                ? "Run Completed with Warnings / Partial Extraction"
                : `Run Failed (${summary.status})`;
    }

    if (elements.summaryRunMeta) {
        elements.summaryRunMeta.textContent = `Run ID: ${summary.run_id} | Total Wall Time: ${formatDuration(summary.wall_time_ns)}`;
    }

    if (elements.statTotalFiles) elements.statTotalFiles.textContent = summary.total_inputs || 0;
    if (elements.statSuccessFiles) elements.statSuccessFiles.textContent = summary.successful_files ?? "—";
    if (elements.statWarningFiles) elements.statWarningFiles.textContent = summary.warning_files ?? "—";
    if (elements.statFailedFiles) elements.statFailedFiles.textContent = summary.failed_files ?? "—";

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
