/**
 * Command Palette (Ctrl+P / Command button) for fast keyboard navigation in Mukha.
 */

import { elements } from "./dom.js";
import { switchScreen, state } from "./state.js";

const COMMANDS = [
    { id: "nav-home", label: "Navigate: Griha (F1 - Intake / Setup)", action: () => switchScreen("home") },
    { id: "nav-monitor", label: "Navigate: Pravritti (F2 - Live Execution)", action: () => switchScreen("monitor") },
    { id: "nav-review", label: "Navigate: Pariksha (F3 - Review Queue)", action: () => switchScreen("review") },
    { id: "nav-summary", label: "Navigate: Samapti (F4 - Run Summary)", action: () => switchScreen("summary") },
    { id: "nav-inspector", label: "Navigate: Nirikshana (F5 - Telemetry)", action: () => switchScreen("inspector") },
    { id: "act-add-files", label: "Action: Add Input Files...", action: () => elements.btnBrowseFiles && elements.btnBrowseFiles.click() },
    { id: "act-add-folder", label: "Action: Add Folder...", action: () => elements.btnBrowseFolder && elements.btnBrowseFolder.click() },
    { id: "act-start-run", label: "Action: Start Document Processing", action: () => elements.btnStartRun && elements.btnStartRun.click() },
    { id: "act-cancel-run", label: "Action: Cancel Active Run", action: () => elements.btnCancelRun && elements.btnCancelRun.click() },
    { id: "act-history", label: "Action: Open Run History (Ctrl+H)", action: () => elements.btnOpenHistory && elements.btnOpenHistory.click() },
    { id: "act-clear-history", label: "Action: Clear Terminal Run History", action: () => elements.btnClearHistory && elements.btnClearHistory.click() },
    { id: "act-clear-cache", label: "Action: Clear Smriti Cache", action: () => elements.btnClearCache && elements.btnClearCache.click() },
    { id: "act-copy-logs", label: "Action: Copy Activity Logs to Clipboard", action: () => elements.btnCopyLogs && elements.btnCopyLogs.click() },
    {
        id: "act-export-diag",
        label: "Action: Export Run Diagnostics (JSON)",
        action: () => {
            const runId = state.viewedRunId || state.activeRunId;
            if (runId) {
                window.open(`/api/runs/${encodeURIComponent(runId)}/diagnostics`, "_blank");
            }
        },
    },
];

let selectedIndex = 0;
let filteredCommands = [...COMMANDS];

export function openCommandPalette() {
    const dialog = document.getElementById("command-palette-dialog");
    const input = document.getElementById("palette-search-input");
    if (!dialog || !input) return;

    input.value = "";
    filteredCommands = [...COMMANDS];
    selectedIndex = 0;
    renderPaletteList();

    if (typeof dialog.showModal === "function") {
        dialog.showModal();
    } else {
        dialog.classList.remove("hidden");
    }
    input.focus();
}

export function closeCommandPalette() {
    const dialog = document.getElementById("command-palette-dialog");
    if (!dialog) return;
    if (typeof dialog.close === "function") {
        dialog.close();
    } else {
        dialog.classList.add("hidden");
    }
}

function renderPaletteList() {
    const listContainer = document.getElementById("palette-command-list");
    if (!listContainer) return;

    if (filteredCommands.length === 0) {
        listContainer.innerHTML = '<div class="palette-item empty">No matching commands found.</div>';
        return;
    }

    listContainer.innerHTML = filteredCommands
        .map((cmd, idx) => `
            <div class="palette-item ${idx === selectedIndex ? "active" : ""}" data-index="${idx}">
                <span>${cmd.label}</span>
            </div>
        `)
        .join("");
}

export function initCommandPalette() {
    const input = document.getElementById("palette-search-input");
    const dialog = document.getElementById("command-palette-dialog");
    const listContainer = document.getElementById("palette-command-list");

    if (elements.btnCommandPalette) {
        elements.btnCommandPalette.addEventListener("click", openCommandPalette);
    }

    if (input) {
        input.addEventListener("input", (e) => {
            const query = e.target.value.toLowerCase().trim();
            filteredCommands = query
                ? COMMANDS.filter((c) => c.label.toLowerCase().includes(query))
                : [...COMMANDS];
            selectedIndex = 0;
            renderPaletteList();
        });

        input.addEventListener("keydown", (e) => {
            if (e.key === "ArrowDown") {
                e.preventDefault();
                selectedIndex = (selectedIndex + 1) % Math.max(1, filteredCommands.length);
                renderPaletteList();
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                selectedIndex = (selectedIndex - 1 + filteredCommands.length) % Math.max(1, filteredCommands.length);
                renderPaletteList();
            } else if (e.key === "Enter") {
                e.preventDefault();
                const cmd = filteredCommands[selectedIndex];
                if (cmd) {
                    closeCommandPalette();
                    cmd.action();
                }
            } else if (e.key === "Escape") {
                closeCommandPalette();
            }
        });
    }

    if (listContainer) {
        listContainer.addEventListener("click", (e) => {
            const item = e.target.closest(".palette-item");
            if (item && item.dataset.index) {
                const idx = parseInt(item.dataset.index, 10);
                const cmd = filteredCommands[idx];
                if (cmd) {
                    closeCommandPalette();
                    cmd.action();
                }
            }
        });
    }

    if (dialog) {
        dialog.addEventListener("click", (e) => {
            if (e.target === dialog) {
                closeCommandPalette();
            }
        });
    }
}
