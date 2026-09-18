export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === 0) return "0 B";
  if (!Number.isFinite(bytes) || !bytes || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB"] as const;
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatDuration(ns: number | null | undefined): string {
  if (ns === 0) return "0.0 s";
  if (!Number.isFinite(ns) || !ns || ns < 0) return "—";
  const seconds = ns / 1_000_000_000;
  if (seconds < 1) return `${Math.round(ns / 1_000_000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function formatConfidence(value: number | null | undefined): string {
  if (value === 0) return "0.0%";
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

export function formatStatus(status: string | null | undefined): { label: string; badgeClass: string } {
  if (!status) return { label: "—", badgeClass: "badge-slate" };
  const upper = status.toUpperCase();
  switch (upper) {
    case "SUCCESS":
      return { label: "Run Completed Successfully", badgeClass: "badge-emerald" };
    case "RUNNING":
      return { label: "Running", badgeClass: "badge-indigo" };
    case "CANCELLED":
      return { label: "Run Cancelled", badgeClass: "badge-crimson" };
    case "FAILED":
      return { label: "Run Failed (FAILED)", badgeClass: "badge-crimson" };
    case "WARNING":
    case "PARTIAL":
      return { label: "Completed with Warnings", badgeClass: "badge-amber" };
    case "QUARANTINED":
      return { label: "Run Quarantined", badgeClass: "badge-crimson" };
    default:
      return { label: `Unknown (${upper})`, badgeClass: "badge-slate" };
  }
}

export function formatSummaryTitle(status: string): string {
  switch (status) {
    case "SUCCESS":
      return "Run Completed Successfully";
    case "WARNING":
    case "PARTIAL":
      return "Run Completed with Warnings";
    case "CANCELLED":
      return "Run Cancelled";
    case "QUARANTINED":
      return "Run Quarantined";
    default:
      return `Run Failed (${status})`;
  }
}

if (typeof window !== "undefined") {
  (window as any).__formatters = {
    formatDuration,
    formatConfidence,
    formatBytes,
    formatStatus,
  };
  (window as any).__formatSummaryTitle = formatSummaryTitle;
}
