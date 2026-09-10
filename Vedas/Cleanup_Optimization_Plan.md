# Sarathi Cleanup and Optimization Plan

**Status:** active roadmap  
**Rule:** complete one phase, migrate tests/docs, and pass permanent CI before starting the next.

## Objective

Reduce dead code, duplicated ownership, compatibility machinery, avoidable runtime cost, and documentation drift while preserving user-visible behavior.

```text
delete obsolete code
      -> simplify ownership
      -> consolidate duplicate logic
      -> measure runtime
      -> optimize proven hot paths
      -> keep regression gates
```

## Non-negotiable rules

1. Preserve public behavior unless a separate product change explicitly changes it.
2. Delete before abstracting.
3. Keep one authority for decisions that must not conflict.
4. Prefer mature libraries to custom generic infrastructure.
5. Measure before performance optimization.
6. Do not silently change profile, engine, device, language, provider, or security behavior.
7. Keep security fail-closed.
8. Tests protect behavior and meaningful boundaries, not arbitrary architecture metrics.
9. Documentation and production code are migrated together.
10. Permanent CI is the phase-completion gate.

## Phase status

### Phase 0 — Mukha transport migration — complete

Starlette/Uvicorn own the local web transport. Obsolete stdlib HTTP handler/static-handler machinery is removed and architecture tests prevent it from returning.

### Phase 1 — Mukha ownership cleanup — complete

Goal: keep `server.py` as lifecycle/facade, `app.py` as HTTP translation/routing, runner code as run-state owner, and focused helpers only where they have substantive responsibility. Remove private compatibility seams, migrate tests to public/focused owners, keep API/browser behavior stable, and finish with a current-only documentation tree.

Phase 1 is complete only when lint/compilation, architecture sanity, TypeScript build, deterministic Python tests, and Playwright browser tests pass on the exact final tree.

### Phase 2 — Kosh / Manthan / Pravaha ownership — complete

Kosh owns declaration registration and lookup; provider batches are fully validated before one direct atomic commit instead of being re-validated through the single-item registration API. Manthan is the sole planning authority for requirements, prerequisites, execution-profile compatibility, and continuation plans. Pravaha consumes resolved plans and owns execution, cancellation, retry, quarantine, and hand-off mechanics without constructing plans or selecting supported profiles. Architecture tests keep that ownership boundary explicit.

### Phase 3 — Yantra simplification and resource measurement — complete

Repository-wide usage auditing confirmed that Yantra's bounded subtask execution is used by OCR and translation, while queueing, cancellation cleanup, allocation integrity, backend compatibility, and concurrency binding protect active correctness paths. Those mechanisms remain. Unused `DeviceInventory` aliases/type-search helpers were deleted, the allocator now consumes concrete `DeviceInfo` records instead of generic duck-typed objects, and the concurrency hardening test now enforces the actual two-task bound it configures. Accelerator `capacity` remains an explicit scheduler concurrency budget rather than a claim about physical compute cores; no throughput tuning was made without a reproducible benchmark. Capability-specific workload strategy remains with the capability.

### Phase 4 — OCR profiling and optimization — complete

The OCR page path was profiled before modification with a model-free orchestration benchmark using a 1240×1754 RGB page (approximately A4 at 150 DPI), a no-op inference callable, and the real `RapidOCREngine.ocr_page()` orchestration. Instant OCR with preprocessing disabled measured **7.746 ms median/page**; default Instant preprocessing measured **19.417 ms median/page**, a measured preprocessing delta of **11.671 ms/page**. Eager NumPy-to-PIL reconstruction alone measured **0.991 ms median/page**.

The optimization removes that eager fallback-crop image reconstruction from paths that cannot use it. `processed_img` is now materialized only when Custom binarization or a weak-span Tesseract fallback actually needs a PIL image; when preprocessing is disabled, fallback can reuse the original PIL image. The same no-preprocessing benchmark measured **7.270 ms median/page** after the change, about **6.1% lower orchestration overhead** on that workload.

No deskew, CLAHE, recognition model, language routing, fallback threshold, confidence, geometry, concurrency, rasterization DPI, or artifact behavior was changed. Default preprocessing was deliberately left untouched despite its measurable cost because changing it without a recognition-quality corpus would trade correctness for an unproven speed benefit. Existing Accurate fallback crop-alignment coverage remains, and `test_instant_page_does_not_materialize_unused_fallback_image` prevents the unused Instant-path allocation from returning.

These timings measure Python/image-orchestration overhead only, not end-to-end neural inference throughput, and must not be presented as real-model OCR latency.

### Phase 5 — Artifact and quarantine cleanup — complete

The artifact and quarantine boundary was audited globally before removal. The safety-bearing behavior remains unchanged: Kavacha source/destination overlap authorization, runtime/output root separation, symlink-containment checks, staged streaming promotion with checksum generation and rollback, manifest-last finalization, committed-artifact retention on failure, explicit partial-artifact policy, quarantine identifier validation, retry identity binding, and atomic persistence.

Cleanup removed only duplicated or unused machinery. `RunWorkspace` now calls the canonical path-resolution and normalization helpers directly instead of forwarding through two state-free private methods. The unused `partial_artifacts` parameter was removed from failure cleanup and every caller. The dead `_compute_sha256` helper and export were removed because staged promotion already computes the authoritative checksum while streaming. Quarantine manifests now reuse Nabhi's existing atomic byte writer rather than maintaining a second temp-file implementation, while preserving the quarantine-specific outer failure message. Immutable quarantine status and retry-failure records now use `dataclasses.replace()` instead of manually reconstructing every unchanged field.

No artifact destination, checksum, manifest, rollback, staging, partial retention, quarantine transition, retry count, failure code, run/request/trace identity, or user-visible output behavior was changed. The existing `RunWorkspace._write_bytes_atomically` injection seam remains because current failure-path tests use it to verify manifest and artifact rollback behavior; removing a useful verification seam solely to reduce method count would not improve the architecture.

### Phase 6 — Smriti and retained state

Make cache keys/invalidation/lifetime explicit, measure hit benefit, bound retained session state, and verify completed runs release large objects/callbacks.

### Phase 7 — Darpana telemetry

Keep operationally useful timing/error/history facts, remove unconsumed schemas, and avoid high-frequency synchronous telemetry work in processing inner loops.

### Phase 8 — Kavacha and provider boundaries

Map every outbound HTTP client, credential read, and document payload that can leave the machine to the actual authorization boundary. Remove security claims that are not implemented.

### Phase 9 — Shared text/typography utilities

Consolidate helpers only when their semantic contract is identical across real consumers. Remove compatibility re-exports after callers migrate.

### Phase 10 — Dependency/import cost

Audit optional dependency boundaries and startup/import cost. Remove unused direct dependencies and defer heavy imports only when profiling shows material benefit.

### Phase 11 — Frontend production convergence

Finish the TypeScript/Preact migration, remove legacy frontend assets after parity, and keep one browser state contract and one production frontend implementation.

### Phase 12 — Test acceleration

Measure suite runtime, remove duplicate obsolete-architecture tests, share expensive immutable fixtures where safe, and keep security/data-loss/cancellation/planning/artifact/browser coverage strong.

### Phase 13 — Final documentation reconciliation

Ensure README, AGENTS, Vedas, manifest, CI, configuration, and production code describe the same current system. A new maintainer should be able to determine ownership and operating workflow without reading Git history.

## Performance change protocol

Every performance-focused change should record:

| Field | Requirement |
| --- | --- |
| Baseline | Reproducible workload and pre-change measurement |
| Change | Exact implementation difference |
| Result | Same workload measured after the change |
| Behavioral risk | Output/security/determinism risks considered |
| Regression gate | Test or benchmark that prevents accidental reversal |

Faster is not automatically better: reject changes that materially worsen correctness, security, determinism, or maintainability.
