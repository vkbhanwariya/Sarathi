/**
 * Safe scoped document preview controller for Mukha.
 */

import { apiGet } from "./api.js";
import { elements } from "./dom.js";
import { escapeHtml, formatBytes } from "./formatters.js";
import { state } from "./state.js";

export function closeDocumentPreview() {
    const dlg = elements.docPreviewDialog || document.getElementById("doc-preview-dialog");
    if (dlg) {
        if (typeof dlg.close === "function" && dlg.open) {
            dlg.close();
        }
        dlg.removeAttribute("open");
    }
}

export function initPreviewDialog() {
    const btnClose = elements.btnClosePreview || document.getElementById("btn-close-preview");
    if (btnClose) {
        btnClose.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            closeDocumentPreview();
        });
    }
    const dlg = elements.docPreviewDialog || document.getElementById("doc-preview-dialog");
    if (dlg) {
        dlg.addEventListener("click", (e) => {
            const rect = dlg.getBoundingClientRect();
            const isInDialog = (
                rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
                rect.left <= e.clientX && e.clientX <= rect.left + rect.width
            );
            if (!isInDialog) {
                closeDocumentPreview();
            }
        });
        dlg.addEventListener("cancel", (e) => {
            e.preventDefault();
            closeDocumentPreview();
        });
    }
}

export async function openDocumentPreview(pathOrUrl, displayName, fallbackPath = null) {
    const dlg = elements.docPreviewDialog || document.getElementById("doc-preview-dialog");
    if (!dlg || !elements.previewModalContent) return;
    elements.previewModalTitle.textContent = displayName || "Document Preview";
    elements.previewModalContent.innerHTML = '<div class="spinner"></div>';
    state.imageZoomLevel = 1.0;

    if (typeof dlg.showModal === "function" && !dlg.open) {
        dlg.showModal();
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
                <button type="button" class="btn btn-outline btn-sm" id="btn-modal-dismiss-err">✕ Close</button>
            </div>
        `;
        const btnErrClose = document.getElementById("btn-modal-dismiss-err");
        if (btnErrClose) {
            btnErrClose.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                closeDocumentPreview();
            });
        }
        return;
    }

    // Determine streaming raw URL and page endpoint
    let rawUrl = "";
    let pageEndpoint = null;
    if (endpoint.includes("/api/inputs/")) {
        rawUrl = endpoint.replace("/preview", "/raw");
        pageEndpoint = (p) => endpoint.replace("/preview", `/pdf_page?page=${p}`);
    } else if (endpoint.includes("/api/runs/") && endpoint.includes("/artifacts/")) {
        rawUrl = endpoint.replace("/preview", "/raw");
        pageEndpoint = (p) => `/api/preview/pdf_page?path=${encodeURIComponent(res.raw_path || "")}&page=${p}`;
    } else {
        const targetPath = res.raw_path || pathOrUrl;
        rawUrl = `/api/preview/raw?path=${encodeURIComponent(targetPath)}`;
        pageEndpoint = (p) => `/api/preview/pdf_page?path=${encodeURIComponent(targetPath)}&page=${p}`;
    }

    if (res.type === "pdf") {
        renderPdfPreview(res, rawUrl, pageEndpoint);
    } else if (res.type === "word") {
        renderWordPreview(res, rawUrl);
    } else if (res.type === "text") {
        renderTextPreview(res, rawUrl);
    } else if (res.type === "tabular") {
        renderTabularPreview(res, rawUrl);
    } else if (res.type === "image") {
        renderImagePreview(res, rawUrl);
    } else {
        elements.previewModalContent.innerHTML = `
            <div style="text-align: center; padding: 40px;">
                <div style="font-size: 48px; margin-bottom: 12px;">📦</div>
                <h3>${escapeHtml(res.name)}</h3>
                <p class="text-muted" style="margin: 8px 0 16px 0;">Binary file (${formatBytes(res.size)})</p>
                <a href="${rawUrl}?download=1" download class="btn btn-primary btn-sm">⤓ Download File</a>
            </div>
        `;
    }
}

function renderPdfPreview(res, rawUrl, pageEndpoint) {
    let currentPage = res.current_page || 1;
    const totalPages = res.page_count || 1;
    let zoomLevel = 1.0;

    if (!res.page_data_url && res.error) {
        elements.previewModalContent.innerHTML = `
            <div class="alert-box alert-amber" style="margin-bottom: 16px;">
                ${escapeHtml(res.error)}
            </div>
            <div style="text-align: center; padding: 20px;">
                <p class="text-muted">You can open the document directly in a browser tab or download it:</p>
                <div style="display: flex; gap: 8px; justify-content: center; margin-top: 12px;">
                    <a href="${rawUrl}" target="_blank" class="btn btn-primary btn-sm">↗ Open in Browser Tab</a>
                    <a href="${rawUrl}?download=1" download class="btn btn-outline btn-sm">⤓ Download PDF</a>
                </div>
            </div>
        `;
        return;
    }

    elements.previewModalContent.innerHTML = `
        <div class="doc-preview-toolbar">
            <div class="doc-page-indicator">
                <button id="btn-pdf-prev" class="btn btn-outline btn-sm" ${currentPage <= 1 ? "disabled" : ""}>◀ Prev</button>
                <span>Page <strong id="pdf-curr-page-text">${currentPage}</strong> of <strong>${totalPages}</strong></span>
                <button id="btn-pdf-next" class="btn btn-outline btn-sm" ${currentPage >= totalPages ? "disabled" : ""}>Next ▶</button>
            </div>
            <div class="doc-preview-tabs">
                <button id="tab-btn-pdf-canvas" class="doc-preview-tab-btn active">🖼️ Rendered Page</button>
                <button id="tab-btn-pdf-native" class="doc-preview-tab-btn">🌐 Browser Viewer</button>
                <button id="tab-btn-pdf-text" class="doc-preview-tab-btn">📝 Page Text</button>
            </div>
            <div style="display: flex; gap: 6px; align-items: center;">
                <button id="btn-pdf-zoom-in" class="btn btn-secondary btn-sm" title="Zoom In">➕</button>
                <button id="btn-pdf-zoom-out" class="btn btn-secondary btn-sm" title="Zoom Out">➖</button>
                <button id="btn-pdf-zoom-reset" class="btn btn-secondary btn-sm" title="Reset Zoom">Reset</button>
                <a href="${rawUrl}" target="_blank" class="btn btn-outline btn-sm" title="Open in dedicated browser tab">↗ Open Tab</a>
                <a href="${rawUrl}?download=1" download class="btn btn-outline btn-sm" title="Download file">⤓ Download</a>
            </div>
        </div>
        <div id="pdf-pane-canvas" class="preview-canvas-container" style="background: #18202f; padding: 20px; border-radius: var(--radius-sm); min-height: 480px; max-height: 600px; overflow: auto; display: flex; align-items: center; justify-content: center;">
            <img id="pdf-page-image" src="${res.page_data_url || ""}" alt="Page ${currentPage}" style="max-width: 100%; border-radius: 2px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); transform: scale(1.0); transition: transform 0.15s ease;">
        </div>
        <div id="pdf-pane-native" class="hidden" style="width: 100%;">
            <iframe src="${rawUrl}" style="width: 100%; height: 580px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: #ffffff;" title="Native PDF Viewer"></iframe>
        </div>
        <div id="pdf-pane-text" class="hidden" style="width: 100%;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span class="text-muted" style="font-size: 12px;">Extracted text layer for current page</span>
                <button id="btn-copy-pdf-page-text" class="btn btn-outline btn-sm">📋 Copy Page Text</button>
            </div>
            <pre id="pdf-page-text-content" style="font-family: var(--font-mono); font-size: 12px; line-height: 1.6; color: #e2e8f0; white-space: pre-wrap; word-break: break-word; background: #04070d; padding: 16px; border-radius: var(--radius-sm); max-height: 520px; overflow-y: auto;">${escapeHtml(res.page_text || "(No text detected on this page)")}</pre>
        </div>
    `;

    const img = document.getElementById("pdf-page-image");
    const paneCanvas = document.getElementById("pdf-pane-canvas");
    const paneNative = document.getElementById("pdf-pane-native");
    const paneText = document.getElementById("pdf-pane-text");
    const btnPrev = document.getElementById("btn-pdf-prev");
    const btnNext = document.getElementById("btn-pdf-next");
    const currPageText = document.getElementById("pdf-curr-page-text");
    const pageTextContent = document.getElementById("pdf-page-text-content");

    const tabCanvas = document.getElementById("tab-btn-pdf-canvas");
    const tabNative = document.getElementById("tab-btn-pdf-native");
    const tabText = document.getElementById("tab-btn-pdf-text");

    function setTab(activeTab) {
        [tabCanvas, tabNative, tabText].forEach((b) => b && b.classList.remove("active"));
        if (paneCanvas) paneCanvas.classList.add("hidden");
        if (paneNative) paneNative.classList.add("hidden");
        if (paneText) paneText.classList.add("hidden");

        if (activeTab === "canvas") {
            if (tabCanvas) tabCanvas.classList.add("active");
            if (paneCanvas) paneCanvas.classList.remove("hidden");
        } else if (activeTab === "native") {
            if (tabNative) tabNative.classList.add("active");
            if (paneNative) paneNative.classList.remove("hidden");
        } else if (activeTab === "text") {
            if (tabText) tabText.classList.add("active");
            if (paneText) paneText.classList.remove("hidden");
        }
    }

    if (tabCanvas) tabCanvas.addEventListener("click", () => setTab("canvas"));
    if (tabNative) tabNative.addEventListener("click", () => setTab("native"));
    if (tabText) tabText.addEventListener("click", () => setTab("text"));

    const btnZoomIn = document.getElementById("btn-pdf-zoom-in");
    const btnZoomOut = document.getElementById("btn-pdf-zoom-out");
    const btnZoomReset = document.getElementById("btn-pdf-zoom-reset");
    if (btnZoomIn && img) {
        btnZoomIn.addEventListener("click", () => {
            zoomLevel = Math.min(3.0, zoomLevel + 0.25);
            img.style.transform = `scale(${zoomLevel})`;
        });
    }
    if (btnZoomOut && img) {
        btnZoomOut.addEventListener("click", () => {
            zoomLevel = Math.max(0.5, zoomLevel - 0.25);
            img.style.transform = `scale(${zoomLevel})`;
        });
    }
    if (btnZoomReset && img) {
        btnZoomReset.addEventListener("click", () => {
            zoomLevel = 1.0;
            img.style.transform = "scale(1.0)";
        });
    }

    async function loadPage(newPage) {
        if (newPage < 1 || newPage > totalPages) return;
        if (btnPrev) btnPrev.disabled = true;
        if (btnNext) btnNext.disabled = true;
        if (currPageText) currPageText.textContent = `${newPage} (Loading...)`;

        const pageRes = await apiGet(pageEndpoint(newPage));
        if (pageRes.ok && pageRes.page_data_url) {
            currentPage = newPage;
            if (img) img.src = pageRes.page_data_url;
            if (currPageText) currPageText.textContent = `${currentPage}`;
            if (pageTextContent) pageTextContent.textContent = pageRes.page_text || "(No text detected on this page)";
        }
        if (btnPrev) btnPrev.disabled = currentPage <= 1;
        if (btnNext) btnNext.disabled = currentPage >= totalPages;
    }

    if (btnPrev) btnPrev.addEventListener("click", () => loadPage(currentPage - 1));
    if (btnNext) btnNext.addEventListener("click", () => loadPage(currentPage + 1));

    const btnCopyText = document.getElementById("btn-copy-pdf-page-text");
    if (btnCopyText && pageTextContent) {
        btnCopyText.addEventListener("click", () => {
            navigator.clipboard.writeText(pageTextContent.textContent || "");
            const orig = btnCopyText.textContent;
            btnCopyText.textContent = "✓ Copied!";
            setTimeout(() => { btnCopyText.textContent = orig; }, 2000);
        });
    }
}

function renderWordPreview(res, rawUrl) {
    const pCount = res.total_paragraphs || (res.paragraphs ? res.paragraphs.length : 0);
    const paragraphsHtml = (res.paragraphs || [])
        .map((p) => `<p style="margin-bottom: 12px; text-align: justify;">${escapeHtml(p)}</p>`)
        .join("");

    let tablesHtml = "";
    if (res.tables && res.tables.length > 0) {
        tablesHtml = res.tables
            .map((tbl, idx) => {
                const thead = (tbl.headers || [])
                    .map((h) => `<th style="background: #f1f5f9; padding: 8px 10px; border: 1px solid #cbd5e1; font-weight: 600;">${escapeHtml(h)}</th>`)
                    .join("");
                const tbody = (tbl.rows || [])
                    .map((row) => `<tr>${(row || []).map((c) => `<td style="padding: 8px 10px; border: 1px solid #cbd5e1;">${escapeHtml(c)}</td>`).join("")}</tr>`)
                    .join("");
                return `
                    <div style="margin: 20px 0;">
                        <div style="font-size: 11px; color: #64748b; margin-bottom: 6px;">Table ${idx + 1}</div>
                        <table style="width: 100%; border-collapse: collapse; margin-bottom: 12px;">
                            ${thead ? `<thead><tr>${thead}</tr></thead>` : ""}
                            <tbody>${tbody}</tbody>
                        </table>
                    </div>
                `;
            })
            .join("");
    }

    elements.previewModalContent.innerHTML = `
        <div class="doc-preview-toolbar">
            <div class="doc-page-indicator">
                <span>Word Document • <strong>${pCount}</strong> paragraphs${res.tables && res.tables.length ? ` • <strong>${res.tables.length}</strong> tables` : ""} (${formatBytes(res.size)})</span>
            </div>
            <div style="display: flex; gap: 8px;">
                <button id="btn-copy-word-text" class="btn btn-outline btn-sm">📋 Copy Text</button>
                <a href="${rawUrl}?download=1" download class="btn btn-primary btn-sm">⤓ Download (.docx)</a>
            </div>
        </div>
        <div class="word-doc-sheet">
            ${paragraphsHtml || '<p class="text-muted">(Empty document or no readable paragraphs)</p>'}
            ${tablesHtml}
        </div>
    `;

    const btnCopy = document.getElementById("btn-copy-word-text");
    if (btnCopy) {
        btnCopy.addEventListener("click", () => {
            const allText = (res.paragraphs || []).join("\n\n");
            navigator.clipboard.writeText(allText);
            const orig = btnCopy.textContent;
            btnCopy.textContent = "✓ Copied!";
            setTimeout(() => { btnCopy.textContent = orig; }, 2000);
        });
    }
}

function renderTextPreview(res, rawUrl) {
    const rawContent = res.content || "";
    const lines = rawContent.split("\n");
    const lineCount = lines.length;

    elements.previewModalContent.innerHTML = `
        <div class="doc-preview-toolbar">
            <div class="doc-page-indicator">
                <span>Text File • <strong>${lineCount}</strong> lines (${formatBytes(res.size)}) ${res.truncated ? "• (Truncated to 256KB)" : ""}</span>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
                <input type="text" id="txt-search-input" placeholder="Find in text..." class="input-sm" style="width: 140px; padding: 4px 8px; font-size: 12px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: var(--radius-sm); color: var(--text-primary);">
                <button id="btn-toggle-wrap" class="btn btn-outline btn-sm">↔ Wrap: Off</button>
                <button id="btn-copy-text" class="btn btn-outline btn-sm">📋 Copy Content</button>
                <a href="${rawUrl}?download=1" download class="btn btn-outline btn-sm">⤓ Download</a>
            </div>
        </div>
        <pre id="txt-code-block" style="font-family: var(--font-mono); font-size: 12px; line-height: 1.6; color: #e2e8f0; white-space: pre; word-break: normal; background: #04070d; padding: 16px; border-radius: var(--radius-sm); max-height: 540px; overflow: auto; border: 1px solid var(--border-color);"><code id="txt-code-content">${escapeHtml(rawContent)}</code></pre>
    `;

    const codeBlock = document.getElementById("txt-code-block");
    const codeContent = document.getElementById("txt-code-content");
    const btnWrap = document.getElementById("btn-toggle-wrap");
    const searchInput = document.getElementById("txt-search-input");
    const btnCopy = document.getElementById("btn-copy-text");

    let isWrapped = false;
    if (btnWrap && codeBlock) {
        btnWrap.addEventListener("click", () => {
            isWrapped = !isWrapped;
            codeBlock.style.whiteSpace = isWrapped ? "pre-wrap" : "pre";
            codeBlock.style.wordBreak = isWrapped ? "break-word" : "normal";
            btnWrap.textContent = isWrapped ? "↔ Wrap: On" : "↔ Wrap: Off";
        });
    }

    if (btnCopy) {
        btnCopy.addEventListener("click", () => {
            navigator.clipboard.writeText(rawContent);
            const orig = btnCopy.textContent;
            btnCopy.textContent = "✓ Copied!";
            setTimeout(() => { btnCopy.textContent = orig; }, 2000);
        });
    }

    if (searchInput && codeContent) {
        searchInput.addEventListener("input", (e) => {
            const query = e.target.value.trim();
            if (!query) {
                codeContent.innerHTML = escapeHtml(rawContent);
                return;
            }
            const escapedQ = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            const re = new RegExp(`(${escapedQ})`, "gi");
            const marked = escapeHtml(rawContent).replace(re, '<mark style="background: #f59e0b; color: #000; border-radius: 2px;">$1</mark>');
            codeContent.innerHTML = marked;
        });
    }
}

function renderTabularPreview(res, rawUrl) {
    const thead = (res.headers || []).map((h) => `<th>${escapeHtml(h)}</th>`).join("");
    const tbody = (res.rows || [])
        .map((row) => `<tr>${row.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`)
        .join("");
    elements.previewModalContent.innerHTML = `
        <div class="doc-preview-toolbar">
            <div class="doc-page-indicator">
                <span>Tabular Data • Showing ${res.rows ? res.rows.length : 0} rows (${formatBytes(res.size)})</span>
            </div>
            <div>
                <a href="${rawUrl}?download=1" download class="btn btn-outline btn-sm">⤓ Download Table</a>
            </div>
        </div>
        <div class="table-container" style="max-height: 520px;">
            <table class="data-table">
                <thead><tr>${thead}</tr></thead>
                <tbody>${tbody}</tbody>
            </table>
        </div>
    `;
}

function renderImagePreview(res, rawUrl) {
    elements.previewModalContent.innerHTML = `
        <div class="doc-preview-toolbar">
            <div class="doc-page-indicator">
                <span>Image (${formatBytes(res.size)})</span>
            </div>
            <div style="display: flex; gap: 6px;">
                <button id="btn-zoom-in" class="btn btn-secondary btn-sm">➕</button>
                <button id="btn-zoom-out" class="btn btn-secondary btn-sm">➖</button>
                <button id="btn-zoom-reset" class="btn btn-secondary btn-sm">Reset</button>
                <a href="${rawUrl}?download=1" download class="btn btn-outline btn-sm">⤓ Download</a>
            </div>
        </div>
        <div class="preview-canvas-container" style="background: #18202f; padding: 20px; border-radius: var(--radius-sm); min-height: 450px; max-height: 560px; overflow: auto; display: flex; align-items: center; justify-content: center;">
            <img id="preview-img" src="${res.data_url}" alt="Preview" style="transform: scale(1.0); max-width: 100%; border-radius: 4px; box-shadow: 0 4px 16px rgba(0,0,0,0.5); transition: transform 0.15s ease;">
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
}
