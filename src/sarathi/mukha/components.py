"""Reusable Presentation Components and Formatters for Mukha.

Provides pure functional formatters for durations, byte sizes, and confidence metrics.
"""

from __future__ import annotations


def format_duration_ns(duration_ns: int | None) -> str:
    """Format an integer nanosecond duration into a concise human-readable time string.

    Rules:
    - None -> "-"
    - < 1 second -> "0.XXs"
    - 1s to < 60s -> "X.Xs" (or "0X.Xs")
    - >= 60s -> "MM:SS.s"
    """
    if duration_ns is None or duration_ns < 0:
        return "-"

    seconds = duration_ns / 1_000_000_000.0

    if seconds < 1.0:
        return f"{seconds:.2f}s"
    if seconds < 60.0:
        return f"{seconds:04.1f}s" if seconds < 10.0 else f"{seconds:.1f}s"

    mins = int(seconds // 60)
    rem_secs = seconds % 60
    return f"{mins:02d}:{rem_secs:04.1f}"


def format_bytes(size_bytes: int | None) -> str:
    """Format integer byte count into a clean human-readable string (B, KB, MB, GB)."""
    if size_bytes is None or size_bytes < 0:
        return "-"

    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_confidence(confidence: float | None) -> str:
    """Format confidence score (0.0 to 1.0) as percentage string, or '-' if unavailable."""
    if confidence is None:
        return "-"
    pct = confidence * 100.0 if confidence <= 1.0 else confidence
    return f"{pct:.1f}%"


def status_badge(status: str) -> str:
    """Return normalized status badge label."""
    return status.upper().strip()
