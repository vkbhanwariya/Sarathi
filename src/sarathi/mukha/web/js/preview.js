/**
 * Safe scoped document preview controller for Mukha.
 */

import { apiGet } from "./api.js";
import { elements } from "./dom.js";
import { escapeHtml, formatBytes } from "./formatters.js";
import { state } from "./state.js";

export function closeDocumentPreview() {
    if (elements.docPreviewDialog && typeof elements.docPreviewDialog.close === "function") {
        elements.docPreviewDialog.close();
    }
}

export function initPreviewDialog() {
    if (elements.btnClosePreview) {
        elements.btnClosePreview.addEventListener("click", closeDocumentPreview);
    }
    if (elements.docPreviewDialog) {
        elements.docPreviewDialog.addEventListener("click", (e) => {
            const rect = elements.docPreviewDialog.getBoundingClientRect();
            const isInDialog = (
                rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
                rect.left <= e.clientX && e.clientX <= rect.left + rect.width
            );
            if (!isInDialog) {
                closeDocumentPreview();
            }
        });
    }
}

export async function openDocumentPreview(pathOrUrl, displayName, fallbackPath = null) {
    if (!elements.docPreviewDialog || !elements.previewModalContent) return;
    elements.previewModalTitle.textContent = displayName || "Document Preview";
    elements.previewModalContent.innerHTML = '<div class="spinner"></div>';
    state.imageZoomLevel = 1.0;

    if (typeof elements.docPreviewDialog.showModal === "function") {
        elements.docPreviewDialog.showModal();
    }

    let endpoint = pathOrUrl.startsWith("/api/")
        ? pathOrUrl
        : `/api/preview?path=${encodeURIComponent(pathOrUrl)}`;
    let res = await apiGet(endpoint);
    if (!res.ok && fallbackPath) {
        const fallbackEndpoint = `/api/preview?path=${encodeURIComponent(fallbackPath)}`;
        const fbRes = await apiGet(fallbackEndpoint);
        if (fbRes.ok) {
            res = fbRes;
        }
    }
    if (!res.ok) {
        elements.previewModalContent.innerHTML = `
            <div class="alert-box alert-amber">${escapeHtml(res.error || "Failed to load document preview.")}</div>
            <div style="text-align: right; margin-top: 12px;">
                <button class="btn btn-outline btn-sm" id="btn-modal-dismiss-err">✕ Close</button>
            </div>
        `;
        const btnErrClose = document.getElementById("btn-modal-dismiss-err");
        if (btnErrClose) btnErrClose.addEventListener("click", closeDocumentPreview);
        return;
    }

    if (res.type === "tabular") {
        const thead = (res.headers || []).map((h) => `<th>${escapeHtml(h)}</th>`).join("");
        const tbody = (res.rows || [])
            .map((row) => `<tr>${row.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`)
            .join("");
        elements.previewModalContent.innerHTML = `
            <div style="margin-bottom: 10px; font-size: 12px; color: var(--text-secondary);">
                Showing ${res.rows ? res.rows.length : 0} rows (${formatBytes(res.size)})
            </div>
            <div class="table-container" style="max-height: 500px;">
                <table class="data-table">
                    <thead><tr>${thead}</tr></thead>
                    <tbody>${tbody}</tbody>
                </table>
            </div>
        `;
    } else if (res.type === "image") {
        elements.previewModalContent.innerHTML = `
            <div class="preview-canvas-container">
                <img id="preview-img" src="${res.data_url}" alt="Preview" style="transform: scale(1.0);">
                <div class="preview-zoom-bar">
                    <button id="btn-zoom-in" class="btn btn-secondary btn-sm">➕</button>
                    <button id="btn-zoom-out" class="btn btn-secondary btn-sm">➖</button>
                    <button id="btn-zoom-reset" class="btn btn-secondary btn-sm">Reset</button>
                </div>
            </div>
        `;
        const img = document.getElementById("preview-img");
        const btnIn = document.getElementById("btn-zoom-in");
        const btnOut = document.getElementById("btn-zoom-out");
        const btnReset = document.getElementById("btn-zoom-reset");
        if (btnIn && img) {
            btnIn.addEventListener("click", () => {
                state.imageZoomLevel = Math.min(3.0, state.imageZoomLevel + 0.25);
                img.style.transform = `scale(${state.imageZoomLevel})`;
            });
        }
        if (btnOut && img) {
            btnOut.addEventListener("click", () => {
                state.imageZoomLevel = Math.max(0.5, state.imageZoomLevel - 0.25);
                img.style.transform = `scale(${state.imageZoomLevel})`;
            });
        }
        if (btnReset && img) {
            btnReset.addEventListener("click", () => {
                state.imageZoomLevel = 1.0;
                img.style.transform = "scale(1.0)";
            });
        }
    } else if (res.type === "text") {
        const lineCount = (res.content || "").split("\n").length;
        elements.previewModalContent.innerHTML = `
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 12px; color: var(--text-secondary);">
                <span>${lineCount} lines (${formatBytes(res.size)}) ${res.truncated ? "• Preview truncated to 256KB" : ""}</span>
                <button id="btn-copy-preview-text" class="btn btn-outline btn-sm">📋 Copy Content</button>
            </div>
            <pre style="font-family: var(--font-mono); font-size: 12px; line-height: 1.5; color: #e2e8f0; white-space: pre-wrap; word-break: break-all; background: #04070d; padding: 14px; border-radius: var(--radius-sm); max-height: 500px; overflow-y: auto;"><code>${escapeHtml(res.content)}</code></pre>
        `;
        const btnCopy = document.getElementById("btn-copy-preview-text");
        if (btnCopy) {
            btnCopy.addEventListener("click", () => {
                navigator.clipboard.writeText(res.content);
            });
        }
    } else if (res.type === "pdf") {
        elements.previewModalContent.innerHTML = `
            <div style="text-align: center; padding: 40px;">
                <div style="font-size: 48px; margin-bottom: 12px;">📄</div>
                <h3>${escapeHtml(res.name)}</h3>
                <p class="text-muted" style="margin-top: 6px;">Portable Document Format (${formatBytes(res.size)})</p>
            </div>
        `;
    } else {
        elements.previewModalContent.innerHTML = `
            <div style="text-align: center; padding: 40px;">
                <div style="font-size: 48px; margin-bottom: 12px;">📦</div>
                <h3>${escapeHtml(res.name)}</h3>
                <p class="text-muted" style="margin-top: 6px;">Binary file (${formatBytes(res.size)})</p>
            </div>
        `;
    }
}
