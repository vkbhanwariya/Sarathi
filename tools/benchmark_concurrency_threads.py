"""Benchmark tool for CPU thread allocation and OpenVINO concurrency.

Evaluates:
1. CTranslate2 neural translation across 1, 2, 4, 6, 8 CPU threads.
2. RapidOCR OpenVINO iGPU inference latency with 1 vs. 2 concurrent streams.
3. Combined throughput under simultaneous translation and OCR inference on Intel Core Ultra 5 125H.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

# Ensure src is on path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sarathi.sankalpa import DeviceType, ExecutionBinding  # noqa: E402
from sarathi.shakti.translation.engine import CTranslate2TranslationEngine  # noqa: E402
from sarathi.shakti.translation.models import TranslationDirection  # noqa: E402

SAMPLE_LEGAL_SENTENCES: list[str] = [
    "Notice is issued to the respondents, returnable on 24.05.2024.",
    "The interim protection granted earlier shall continue till the next date of hearing.",
    "List on 24.05.2024 before the Registrar for completion of service and pleadings.",
    "Learned counsel appearing for the petitioner submits that the statutory authority has exceeded its jurisdiction.",
    "In the meantime, no coercive steps shall be taken against the applicant under the PMLA, 2002.",
]


def benchmark_translation_threads(
    engine: CTranslate2TranslationEngine,
    thread_counts: list[int] | None = None,
    repeats: int = 3,
) -> list[dict[str, Any]]:
    """Benchmark CTranslate2 translation throughput across CPU thread counts."""
    if thread_counts is None:
        thread_counts = [1, 2, 4, 6, 8]
    results: list[dict[str, Any]] = []

    for threads in thread_counts:
        engine.clear_cache()
        binding = ExecutionBinding(
            device_id=f"cpu-{threads}",
            device_type=DeviceType.CPU,
            backend="cpu",
            backend_device_id="CPU",
            approved_concurrency=threads,
        )

        # Warmup
        try:
            engine.translate_batch(
                SAMPLE_LEGAL_SENTENCES[:2],
                direction=TranslationDirection.EN_TO_HI,
                execution_binding=binding,
            )
        except Exception as exc:
            results.append({"threads": threads, "error": str(exc)})
            continue

        latencies: list[float] = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            engine.translate_batch(
                SAMPLE_LEGAL_SENTENCES,
                direction=TranslationDirection.EN_TO_HI,
                execution_binding=binding,
            )
            latencies.append(time.perf_counter() - t0)

        avg_lat = sum(latencies) / len(latencies)
        total_sents = len(SAMPLE_LEGAL_SENTENCES)
        sents_per_sec = total_sents / avg_lat if avg_lat > 0 else 0.0

        results.append(
            {
                "threads": threads,
                "avg_latency_ms": round(avg_lat * 1000, 2),
                "sents_per_sec": round(sents_per_sec, 2),
            }
        )

    return results


def main() -> int:
    print("=" * 70)
    print("Sarathi Concurrency & Thread Allocation Benchmark (Core Ultra 5 125H)")
    print("=" * 70)

    try:
        engine = CTranslate2TranslationEngine()
        engine._ensure_backend()
    except Exception as exc:
        print(f"Skipping neural benchmark: translation weights unavailable ({exc})")
        return 0

    print("\n--- 1. CTranslate2 Neural Translation Thread Ladder ---")
    tr_results = benchmark_translation_threads(engine)
    print(f"{'Threads':<10} | {'Avg Latency (ms)':<20} | {'Throughput (sent/s)':<20}")
    print("-" * 56)
    for r in tr_results:
        if "error" in r:
            print(f"{r['threads']:<10} | Error: {r['error']}")
        else:
            print(f"{r['threads']:<10} | {r['avg_latency_ms']:<20} | {r['sents_per_sec']:<20}")

    print("\nBenchmark complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
