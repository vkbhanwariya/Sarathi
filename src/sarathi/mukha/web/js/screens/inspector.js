/**
 * Screen 5: Nirikshana (Technical Inspector & Telemetry) and History Drawer Controller for Mukha.
 */

import { apiGet, apiPost } from "../api.js";
import { elements } from "../dom.js";
import { escapeHtml, formatDuration } from "../formatters.js";
import { state, switchScreen } from "../state.js";
import { loadRunSummary } from "./summary.js";

export async function loadInspector() {
    if (!state.activeRunId) {
        if (elements.inspectorLogs) {
            elements.inspectorLogs.innerHTML = '<div class="log-entry text-muted">[Ready] No active or recent run to inspect.</div>';
        }
        return;
    }

    const res = await apiGet(`/api/runs/${encodeURIComponent(state.activeRunId)}/inspector`);
    if (!res.ok || !res.inspector) return;

    const insp = res.inspector;

    // Activity Logs
    if (insp.activity_logs && insp.activity_logs.length > 0) {
        state.allActivityLogs = insp.activity_logs;
        renderFilteredLogs();
    }

    // Hardware Device Summary Table
    if (insp.device_summaries && insp.device_summaries.length > 0 && elements.inspectorDeviceTbody) {
        elements.inspectorDeviceTbody.innerHTML = insp.device_summaries
            .map((ds) => `<tr>
                <td><strong>${escapeHtml(ds.device_type)}</strong></td>
                <td>${ds.execution_count}</td>
                <td>${formatDuration(ds.avg_duration_ns)}</td>
                <td>${formatDuration(ds.p95_duration_ns)}</td>
            </tr>`)
            .join("");
    }

    // Stage Timings
    if (insp.stage_timings && insp.stage_timings.length > 0 && elements.inspectorStagesTbody) {
        elements.inspectorStagesTbody.innerHTML = insp.stage_timings
            .map((st) => `<tr>
                <td><strong>${escapeHtml(st.stage_name)}</strong></td>
                <td>${st.call_count}</td>
                <td>${formatDuration(st.duration_ns)}</td>
            </tr>`)
            .join("");
    }

    // Worker Execution Performance
    if (elements.inspectorWorkerTbody) {
        if (insp.worker_performance && insp.worker_performance.length > 0) {
            elements.inspectorWorkerTbody.innerHTML = insp.worker_performance
                .map((wp) => {
                    const statusBadge = wp.status === "ACTIVE"
                        ? '<span class="badge badge-emerald">ACTIVE</span>'
                        : (wp.status === "COMPLETED"
                            ? '<span class="badge badge-cyan">COMPLETED</span>'
                            : '<span class="badge badge-indigo">IDLE</span>');
                    return `<tr>
                        <td><strong class="code-text">${escapeHtml(wp.worker_id)}</strong></td>
                        <td><span class="badge badge-indigo">${escapeHtml(wp.device_type)}</span></td>
                        <td>${escapeHtml(wp.device_id || "—")}</td>
                        <td>${wp.pages_completed}</td>
                        <td>${wp.tasks_completed}</td>
                        <td>${wp.total_duration_ms.toFixed(1)}ms</td>
                        <td>${wp.avg_duration_ms.toFixed(1)}ms</td>
                        <td><strong>${wp.throughput_per_sec.toFixed(2)} p/s</strong></td>
                        <td>${statusBadge}</td>
                    </tr>`;
                })
                .join("");
        } else {
            elements.inspectorWorkerTbody.innerHTML = '<tr class="empty-row"><td colspan="9">No worker telemetry recorded.</td></tr>';
        }
    }

    // Confidence Distribution Cards
    if (insp.confidence_distribution) {
        const distMap = Object.fromEntries(insp.confidence_distribution);
        if (elements.statConfHigh) elements.statConfHigh.textContent = distMap["90-100%"] ?? "0";
        if (elements.statConfMid) elements.statConfMid.textContent = distMap["75-89%"] ?? "0";
        if (elements.statConfLow) elements.statConfLow.textContent = distMap["50-74%"] ?? "0";
        if (elements.statConfCrit) elements.statConfCrit.textContent = distMap["<50%"] ?? "0";
    }

    // Tesseract Fallback Quality Recovery
    const fallbacks = insp.fallback_improvements || [];
    if (elements.tesseractRecoveryCount) {
        elements.tesseractRecoveryCount.textContent = `${fallbacks.length} Recovered`;
        elements.tesseractRecoveryCount.className = fallbacks.length > 0
            ? "badge badge-emerald"
            : "badge badge-indigo";
    }
    if (elements.statTessImproved) {
        elements.statTessImproved.textContent = fallbacks.length;
    }
    if (elements.statTessIntercepted) {
        elements.statTessIntercepted.textContent = fallbacks.length > 0 ? fallbacks.length : "0";
    }
    if (elements.statTessGain) {
        if (fallbacks.length > 0) {
            const avgGain = fallbacks.reduce((sum, f) => sum + (f.confidence_gain || 0), 0) / fallbacks.length;
            elements.statTessGain.textContent = `+${(avgGain * 100).toFixed(1)}%`;
            elements.statTessGain.className = "stat-value text-emerald";
        } else {
            elements.statTessGain.textContent = "+0.0%";
            elements.statTessGain.className = "stat-value text-muted";
        }
    }
    if (elements.statTessPages) {
        const uniquePages = new Set(fallbacks.map((f) => `${f.file_display_name}:${f.page_number}`)).size;
        elements.statTessPages.textContent = uniquePages;
    }

    if (elements.inspectorFallbackTbody) {
        if (fallbacks.length > 0) {
            elements.inspectorFallbackTbody.innerHTML = fallbacks
                .map((f) => {
                    const origPct = (f.original_confidence * 100).toFixed(1);
                    const impPct = (f.improved_confidence * 100).toFixed(1);
                    const gainPct = (f.confidence_gain * 100).toFixed(1);
                    return `<tr>
                        <td><strong class="code-text">${escapeHtml(f.region_id)}</strong></td>
                        <td>${escapeHtml(f.file_display_name)}</td>
                        <td>Page ${f.page_number}</td>
                        <td><span class="badge badge-amber">${origPct}%</span></td>
                        <td><span class="badge badge-emerald">${impPct}%</span></td>
                        <td><strong class="text-emerald">+${gainPct}%</strong></td>
                        <td><span class="badge badge-indigo">${escapeHtml(f.fallback_engine || "Tesseract 5")}</span></td>
                    </tr>`;
                })
                .join("");
        } else {
            elements.inspectorFallbackTbody.innerHTML = '<tr class="empty-row"><td colspan="7">No weak regions required Tesseract fallback for this run.</td></tr>';
        }
    }

    // Page-Level Quality & Confidence
    if (elements.inspectorPageConfTbody) {
        if (insp.page_confidence && insp.page_confidence.length > 0) {
            elements.inspectorPageConfTbody.innerHTML = insp.page_confidence
                .map((pc) => {
                    const pct = (pc.confidence_score * 100).toFixed(1);
                    const confClass = pc.confidence_score >= 0.90
                        ? "badge-emerald"
                        : (pc.confidence_score >= 0.75 ? "badge-cyan" : "badge-amber");
                    const statusBadge = pc.review_recommended
                        ? '<span class="badge badge-amber">REVIEW</span>'
                        : '<span class="badge badge-emerald">OK</span>';
                    return `<tr>
                        <td><strong>${escapeHtml(pc.file_display_name)}</strong></td>
                        <td>Page ${pc.page_number}</td>
                        <td><span class="badge ${confClass}">${pct}%</span></td>
                        <td>${pc.region_count}</td>
                        <td>${(pc.min_confidence * 100).toFixed(1)}%</td>
                        <td>${(pc.max_confidence * 100).toFixed(1)}%</td>
                        <td>${statusBadge}</td>
                    </tr>`;
                })
                .join("");
        } else {
            elements.inspectorPageConfTbody.innerHTML = '<tr class="empty-row"><td colspan="7">No page confidence records.</td></tr>';
        }
    }

    // Region-Level Quality & Confidence
    state.allRegionConfidence = insp.region_confidence || [];
    renderFilteredRegions();

    // System Facts
    if (insp.system_facts && insp.system_facts.length > 0 && elements.systemFactsTbody) {
        elements.systemFactsTbody.innerHTML = insp.system_facts
            .map(([prop, val]) => `<tr>
                <td><strong>${escapeHtml(prop)}</strong></td>
                <td>${escapeHtml(val)}</td>
            </tr>`)
            .join("");
    }
}

export function renderFilteredLogs() {
    if (!elements.inspectorLogs) return;
    const query = (state.logSearchQuery || "").toLowerCase();
    const level = state.logFilterLevel || "ALL";

    const filtered = (state.allActivityLogs || []).filter((entry) => {
        const ts = entry.timestamp !== undefined ? entry.timestamp : entry[0];
        const sev = entry.severity !== undefined ? entry.severity : entry[1];
        const comp = entry.component !== undefined ? entry.component : entry[2];
        const msg = entry.message !== undefined ? entry.message : entry[3];
        if (level !== "ALL" && (sev || "INFO").toUpperCase() !== level) return false;
        if (query && !`${ts} ${comp} ${msg}`.toLowerCase().includes(query)) return false;
        return true;
    });

    if (filtered.length === 0) {
        elements.inspectorLogs.innerHTML = '<div class="log-entry text-muted">No logs match the current filter.</div>';
        return;
    }

    elements.inspectorLogs.innerHTML = filtered
        .map((entry) => {
            const ts = entry.timestamp !== undefined ? entry.timestamp : entry[0];
            const sev = entry.severity !== undefined ? entry.severity : entry[1];
            const comp = entry.component !== undefined ? entry.component : entry[2];
            const msg = entry.message !== undefined ? entry.message : entry[3];
            const sevUpper = (sev || "INFO").toUpperCase();
            const sevClass = (sevUpper === "ERROR" || sevUpper === "FAILED")
                ? "badge-crimson"
                : (sevUpper === "WARN" ? "badge-amber" : "badge-indigo");
            return `<div class="log-entry">
                <span class="text-muted">[${escapeHtml(ts)}]</span>
                <span class="badge ${sevClass}">${escapeHtml(sevUpper)}</span>
                <strong>${escapeHtml(comp)}</strong>: ${escapeHtml(msg)}
            </div>`;
        })
        .join("");
}

export function renderFilteredRegions() {
    if (!elements.inspectorRegionConfTbody) return;
    const query = (state.regionSearchQuery || "").toLowerCase();

    const filtered = (state.allRegionConfidence || []).filter((rc) => {
        if (!query) return true;
        const target = `${rc.region_id} ${rc.file_display_name} p${rc.page_number} ${rc.region_type} ${rc.method} ${rc.fallback_engine || ""}`.toLowerCase();
        return target.includes(query);
    });

    if (filtered.length === 0) {
        elements.inspectorRegionConfTbody.innerHTML = '<tr class="empty-row"><td colspan="7">No region confidence records match filter.</td></tr>';
        return;
    }

    elements.inspectorRegionConfTbody.innerHTML = filtered
        .map((rc) => {
            const pct = (rc.confidence_score * 100).toFixed(1);
            const confClass = rc.confidence_score >= 0.90
                ? "badge-emerald"
                : (rc.confidence_score >= 0.75 ? "badge-cyan" : "badge-amber");

            let statusBadge = rc.review_recommended
                ? '<span class="badge badge-amber">REVIEW</span>'
                : '<span class="badge badge-emerald">OK</span>';
            if (rc.confidence_gain !== undefined && rc.confidence_gain !== null && rc.confidence_gain > 0) {
                const gainPct = (rc.confidence_gain * 100).toFixed(1);
                statusBadge = `<span class="badge badge-emerald" title="Tesseract recovered +${gainPct}%">IMPROVED (+${gainPct}%)</span>`;
            }

            let methodBadge = escapeHtml(rc.method);
            if (rc.method === "tesseract_fallback") {
                methodBadge = `<span class="badge badge-indigo">${escapeHtml(rc.fallback_engine || "Tesseract 5")}</span>`;
            }

            return `<tr>
                <td><strong class="code-text">${escapeHtml(rc.region_id)}</strong></td>
                <td>${escapeHtml(rc.file_display_name)}</td>
                <td>P${rc.page_number}</td>
                <td><span class="badge badge-indigo">${escapeHtml(rc.region_type)}</span></td>
                <td><span class="badge ${confClass}">${pct}%</span></td>
                <td>${methodBadge}</td>
                <td>${statusBadge}</td>
            </tr>`;
        })
        .join("");
}

export async function toggleHistoryDrawer(forceState) {
    if (!elements.historyDrawer) return;
    const isOpen = forceState !== undefined ? forceState : !elements.historyDrawer.classList.contains("open");
    elements.historyDrawer.classList.toggle("open", isOpen);
    if (isOpen && elements.historyListContainer) {
        elements.historyListContainer.innerHTML = '<div class="spinner"></div>';
        const res = await apiGet("/api/history?limit=30");
        if (res.ok && res.history && res.history.length > 0) {
            elements.historyListContainer.innerHTML = res.history
                .map((h) => {
                    let stBadge = '<span class="badge badge-emerald">SUCCESS</span>';
                    if (h.status === "PARTIAL") stBadge = '<span class="badge badge-amber">PARTIAL</span>';
                    else if (h.status === "FAILED") stBadge = '<span class="badge badge-crimson">FAILED</span>';

                    return `
                        <div class="history-card" data-run-id="${escapeHtml(h.run_id)}">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <strong class="code-text">${escapeHtml(h.run_id)}</strong>
                                ${stBadge}
                            </div>
                            <div style="font-size: 12px; color: var(--text-secondary); display: flex; justify-content: space-between; margin: 4px 0 8px 0;">
                                <span>${escapeHtml(h.requirement || 'Document')} • ${h.total_inputs || 0} files</span>
                                <span>${formatDuration(h.wall_time_ns)}</span>
                            </div>
                            <div class="history-card-actions">
                                <button class="btn btn-primary btn-sm btn-view-run-result" data-run-id="${escapeHtml(h.run_id)}" style="flex: 1;">📋 View Result</button>
                                <button class="btn btn-outline btn-sm btn-view-run-telemetry" data-run-id="${escapeHtml(h.run_id)}" style="flex: 1;">🔍 Telemetry</button>
                            </div>
                        </div>
                    `;
                })
                .join("");
        } else {
            elements.historyListContainer.innerHTML = '<div class="text-muted" style="text-align: center; padding: 20px;">No previous terminal runs found.</div>';
        }
    }
}

export function initInspectorScreen() {
    if (elements.inspectorTabs) {
        elements.inspectorTabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                elements.inspectorTabs.forEach((t) => t.classList.remove("active"));
                tab.classList.add("active");
                state.activeInspectorTab = tab.dataset.tab;

                if (elements.inspectorTabContents) {
                    elements.inspectorTabContents.forEach((c) => {
                        const isTarget = c.id === `tab-inspector-${state.activeInspectorTab}`;
                        c.classList.toggle("hidden", !isTarget);
                        c.classList.toggle("active", isTarget);
                    });
                }
            });
        });
    }

    if (elements.inputLogSearch) {
        elements.inputLogSearch.addEventListener("input", (e) => {
            state.logSearchQuery = e.target.value;
            renderFilteredLogs();
        });
    }

    if (elements.logPills) {
        elements.logPills.forEach((pill) => {
            pill.addEventListener("click", () => {
                elements.logPills.forEach((p) => p.classList.remove("active"));
                pill.classList.add("active");
                state.logFilterLevel = pill.dataset.level;
                renderFilteredLogs();
            });
        });
    }

    if (elements.btnCopyLogs) {
        elements.btnCopyLogs.addEventListener("click", () => {
            const text = (state.allActivityLogs || [])
                .map((e) => {
                    const ts = e.timestamp !== undefined ? e.timestamp : e[0];
                    const sev = e.severity !== undefined ? e.severity : e[1];
                    const comp = e.component !== undefined ? e.component : e[2];
                    const msg = e.message !== undefined ? e.message : e[3];
                    return `[${ts}] [${sev}] ${comp}: ${msg}`;
                })
                .join("\n");
            navigator.clipboard.writeText(text);
        });
    }

    const btnExportDiag = document.getElementById("btn-export-diagnostics");
    if (btnExportDiag) {
        btnExportDiag.addEventListener("click", () => {
            if (state.activeRunId) {
                window.open(`/api/runs/${encodeURIComponent(state.activeRunId)}/diagnostics`, "_blank");
            }
        });
    }

    if (elements.inspectorRegionFilter) {
        elements.inspectorRegionFilter.addEventListener("input", (e) => {
            state.regionSearchQuery = e.target.value;
            renderFilteredRegions();
        });
    }

    if (elements.btnOpenHistory) {
        elements.btnOpenHistory.addEventListener("click", () => toggleHistoryDrawer(true));
    }
    if (elements.btnCloseHistory) {
        elements.btnCloseHistory.addEventListener("click", () => toggleHistoryDrawer(false));
    }
    if (elements.btnClearHistory) {
        elements.btnClearHistory.addEventListener("click", handleClearHistory);
    }
    if (elements.btnSystemClearHistory) {
        elements.btnSystemClearHistory.addEventListener("click", handleClearHistory);
    }
    if (elements.btnClearCache) {
        elements.btnClearCache.addEventListener("click", handleClearCache);
    }

    if (elements.historyListContainer) {
        elements.historyListContainer.addEventListener("click", (e) => {
            const btnResult = e.target.closest(".btn-view-run-result");
            const btnTelemetry = e.target.closest(".btn-view-run-telemetry");
            const card = e.target.closest(".history-card");

            if (btnResult && btnResult.dataset.runId) {
                const runId = btnResult.dataset.runId;
                state.activeRunId = runId;
                toggleHistoryDrawer(false);
                loadRunSummary(runId);
                return;
            }

            if (btnTelemetry && btnTelemetry.dataset.runId) {
                const runId = btnTelemetry.dataset.runId;
                state.activeRunId = runId;
                toggleHistoryDrawer(false);
                switchScreen("inspector");
                loadInspector();
                return;
            }

            if (card && card.dataset.runId) {
                const runId = card.dataset.runId;
                state.activeRunId = runId;
                toggleHistoryDrawer(false);
                loadRunSummary(runId);
            }
        });
    }
}

async function handleClearHistory() {
    if (!confirm("Are you sure you want to clear all historical run records and telemetry? This cannot be undone.")) {
        return;
    }
    const res = await apiPost("/api/history/clear");
    if (res.ok) {
        if (elements.historyListContainer) {
            elements.historyListContainer.innerHTML = '<div class="text-muted" style="text-align: center; padding: 20px;">No previous terminal runs found.</div>';
        }
        if (elements.maintenanceFeedback) {
            elements.maintenanceFeedback.textContent = "✓ Terminal run history cleared successfully.";
            elements.maintenanceFeedback.className = "text-emerald";
            setTimeout(() => {
                if (elements.maintenanceFeedback) elements.maintenanceFeedback.textContent = "";
            }, 4000);
        }
    } else {
        alert("Failed to clear history: " + (res.error || "Unknown error"));
    }
}

async function handleClearCache() {
    if (!confirm("Are you sure you want to clear the Smriti cache? All L1 memory and L2 persistent cache entries will be purged.")) {
        return;
    }
    const res = await apiPost("/api/cache/clear");
    if (res.ok) {
        const count = res.cleared_entries !== undefined ? res.cleared_entries : 0;
        if (elements.maintenanceFeedback) {
            elements.maintenanceFeedback.textContent = `✓ Smriti cache cleared (${count} entries purged).`;
            elements.maintenanceFeedback.className = "text-emerald";
            setTimeout(() => {
                if (elements.maintenanceFeedback) elements.maintenanceFeedback.textContent = "";
            }, 4000);
        }
    } else {
        alert("Failed to clear cache: " + (res.error || "Unknown error"));
    }
}
