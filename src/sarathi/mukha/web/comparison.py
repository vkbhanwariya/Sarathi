"""Mukha Historical Run Comparator for Sarathi V2.

Computes comparative metrics, stage duration deltas, worker throughput,
and accuracy differences between two terminal runs from Darpana telemetry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sarathi.mukha.web.state_builder import get_run_telemetry

if TYPE_CHECKING:
    from sarathi.agni import Agni


def compare_runs(
    agni: Agni,
    run_id_a: str,
    run_id_b: str,
) -> dict[str, Any]:
    """Compare performance and quality metrics between two execution runs."""
    maruti_a, pramana_a = get_run_telemetry(agni, run_id_a)
    maruti_b, pramana_b = get_run_telemetry(agni, run_id_b)

    def _analyze_run(m_recs: tuple[Any, ...], p_recs: tuple[Any, ...]) -> dict[str, Any]:
        stages: dict[str, dict[str, Any]] = {}
        total_dur_ns = 0
        for m in m_recs:
            dur = max(0, int(m.duration_ns or 0))
            total_dur_ns += dur
            p_name = m.phase_name or "unknown"
            if p_name not in stages:
                stages[p_name] = {"calls": 0, "total_ms": 0.0}
            stages[p_name]["calls"] += 1
            stages[p_name]["total_ms"] = round(stages[p_name]["total_ms"] + (dur / 1_000_000), 2)

        confidences = [
            float(p.confidence.score if hasattr(p.confidence, "score") else p.confidence)
            for p in p_recs
            if p.confidence is not None
        ]
        avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else None

        return {
            "total_duration_ms": round(total_dur_ns / 1_000_000, 2),
            "stages": stages,
            "sample_count": len(confidences),
            "avg_confidence": avg_conf,
        }

    stats_a = _analyze_run(maruti_a, pramana_a)
    stats_b = _analyze_run(maruti_b, pramana_b)

    all_stages = sorted(set(stats_a["stages"].keys()) | set(stats_b["stages"].keys()))
    stage_diffs: list[dict[str, Any]] = []
    for s in all_stages:
        ms_a = stats_a["stages"].get(s, {}).get("total_ms", 0.0)
        ms_b = stats_b["stages"].get(s, {}).get("total_ms", 0.0)
        stage_diffs.append(
            {
                "stage": s,
                "run_a_ms": ms_a,
                "run_b_ms": ms_b,
                "diff_ms": round(ms_b - ms_a, 2),
            }
        )

    dur_diff = round(stats_b["total_duration_ms"] - stats_a["total_duration_ms"], 2)
    conf_diff = (
        round(stats_b["avg_confidence"] - stats_a["avg_confidence"], 4)
        if stats_a["avg_confidence"] is not None and stats_b["avg_confidence"] is not None
        else None
    )

    return {
        "ok": True,
        "run_id_a": run_id_a,
        "run_id_b": run_id_b,
        "summary": {
            "duration_ms_a": stats_a["total_duration_ms"],
            "duration_ms_b": stats_b["total_duration_ms"],
            "duration_diff_ms": dur_diff,
            "confidence_a": stats_a["avg_confidence"],
            "confidence_b": stats_b["avg_confidence"],
            "confidence_diff": conf_diff,
        },
        "stages": stage_diffs,
    }
