/**
 * Pure formatting and sanitization utilities for Mukha presentation layer.
 */

export function formatStatus(status) {
    if (!status) {
        return { label: "Unavailable", className: "badge badge-neutral", dotClass: "status-dot offline" };
    }
    const s = String(status).toUpperCase().trim();
    switch (s) {
        case "STARTING":
            return { label: "Starting", className: "badge badge-indigo", dotClass: "status-dot running" };
        case "READY":
        case "ONLINE":
        case "IDLE":
            return { label: "Ready", className: "badge badge-emerald", dotClass: "status-dot online" };
        case "RUNNING":
            return { label: "Processing...", className: "badge badge-indigo", dotClass: "status-dot running" };
        case "REVIEW":
            return { label: "Review Needed", className: "badge badge-amber", dotClass: "status-dot warning" };
        case "SUCCESS":
            return { label: "Success", className: "badge badge-emerald", dotClass: "status-dot online" };
        case "PARTIAL":
        case "WARNING":
            return { label: "Partial / Warnings", className: "badge badge-amber", dotClass: "status-dot warning" };
        case "CANCELLED":
            return { label: "Run Cancelled", className: "badge badge-amber", dotClass: "status-dot warning" };
        case "CANCELLING":
            return { label: "Cancellation requested", className: "badge badge-amber", dotClass: "status-dot warning" };
        case "QUARANTINED":
            return { label: "Quarantined", className: "badge badge-crimson", dotClass: "status-dot error" };
        case "FAILED":
            return { label: "Failed", className: "badge badge-crimson", dotClass: "status-dot error" };
        case "PENDING":
            return { label: "Pending", className: "badge badge-indigo", dotClass: "status-dot running" };
        case "UNAVAILABLE":
            return { label: "Unavailable", className: "badge badge-neutral", dotClass: "status-dot offline" };
        default:
            return { label: `Unknown (${status})`, className: "badge badge-neutral", dotClass: "status-dot offline" };
    }
}

export function formatValueOrUnavailable(val, unit = "", fallback = "—") {
    if (val === 0 || val === "0" || val === 0.0) {
        return unit ? `0 ${unit}` : "0";
    }
    if (val === null || val === undefined || val === "" || Number.isNaN(val)) {
        return fallback;
    }
    return unit ? `${val} ${unit}` : String(val);
}

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
    if (ns === 0 || ns === "0") return "0.0 s";
    const sec = ns / 1_000_000_000;
    if (sec < 1) return `${(ns / 1_000_000).toFixed(0)} ms`;
    if (sec < 60) return `${sec.toFixed(1)} s`;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}m ${s}s`;
}

export function formatConfidence(conf) {
    if (conf === 0 || conf === "0") return "0.0%";
    if (conf === undefined || conf === null || isNaN(conf) || conf === "") return "—";
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
