/**
 * Pure formatting and sanitization utilities for Mukha presentation layer.
 */

export function formatBytes(bytes) {
    if (bytes === 0 || bytes === "0") return "0 B";
    if (!bytes || isNaN(bytes)) return "—";
    const num = Number(bytes);
    if (num < 0) return "—";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(num) / Math.log(k));
    return parseFloat((num / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

export function formatDuration(ns) {
    if (ns === undefined || ns === null || isNaN(ns)) return "—";
    const sec = ns / 1_000_000_000;
    if (sec < 1) return `${(ns / 1_000_000).toFixed(0)} ms`;
    if (sec < 60) return `${sec.toFixed(1)} s`;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}m ${s}s`;
}

export function formatConfidence(conf) {
    if (conf === undefined || conf === null || isNaN(conf)) return "—";
    const val = Number(conf);
    return `${(val * 100).toFixed(1)}%`;
}

export function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

export function truncate(str, maxLen = 40) {
    if (!str) return "";
    if (str.length <= maxLen) return str;
    return str.substring(0, maxLen - 3) + "...";
}
