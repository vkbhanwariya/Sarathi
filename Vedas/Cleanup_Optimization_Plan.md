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

### Phase 6 — Smriti and retained state — complete

Smriti has explicit deterministic cache keys, canonical cacheability rules, bounded L1/L2 retention, TTL validation, capability/key invalidation, lossless canonical serialization, and L2-to-L1 promotion that preserves the original creation time. Completed-run retained-state cleanup is covered by the Phase 6 migration and regression suite.

The completed-phase modernization sweep removed Smriti's mutation of Python's private process-global `copy._deepcopy_dispatch`. L1 isolation now uses a local structural defensive copy over the already constrained canonical cache tree, preserving nested mutable isolation without JSON round-tripping or global interpreter side effects. L2 retention now performs the upsert first and evicts only actual overflow, so refreshing an existing key at full capacity cannot evict an unrelated retained entry.

### Completed-phase modernization sweep — complete

Phases 0–6 were re-audited together after completion. Stable Mukha, Kosh/Manthan, Yantra, OCR scheduling, artifact, and quarantine ownership boundaries were intentionally left alone where a rewrite would only change style. Shared immutable-copy paths were simplified with `dataclasses.replace()` where manual reconstruction could lose future fields; canonical-document payload normalization was centralized only for strict consumers; loose fallback consumers retained their existing semantics.

The sweep also fixed two concrete state/fidelity defects: execution bindings are preserved through cancellation-token reconciliation and Pravaha retry contexts, and canonical document transformations no longer infer callback signatures by swallowing arbitrary `TypeError`. Regression tests lock those contracts. This modernization sweep is not a new numbered phase; remaining phases are modernized as part of their own implementation.

### Phase 7 — Darpana telemetry — complete

Darpana remains Sarathi's local telemetry boundary: bounded Maruti runtime records, Pramana quality observations, active timing scopes, and privacy-filtered terminal run history. The public telemetry contracts, `active_spans()`, persistence-failure state, JSONL history, SQLite history, confidence records, and evidence-backed accuracy records were retained after a functionality-first usage audit. No OpenTelemetry dependency or parallel observability subsystem was added because there is no current external exporter requirement.

`time_scope()` now has one outcome-recording path instead of duplicate success/failure record construction while preserving failure-code, cancellation, active-span, exception, and timing semantics. Run-history queries validate their limit and merge current-process summaries with persisted history by `run_id`, so a failed persistent save cannot cause an older persisted tail to hide a newer in-memory terminal run.

Headline confidence aggregation prefers page-level observations only inside capability/stage groups that actually emit page telemetry. This prevents region count from overweighting a page without discarding measured confidence from unrelated capabilities or legacy groups that have no page-level records. Run summaries, live device summaries, diagnostics, and historical comparison share that selection rule, while detailed region telemetry remains available to the inspector.

The shareable diagnostics boundary now exports only an explicit set of operational event attributes. Local Darpana/UI telemetry may retain detailed identities needed by the product, while diagnostics excludes document content, raw paths, filenames, input identifiers, and unknown attributes by default. No producer-side batching API or inner-loop rewrite was added because synchronization cost has not been demonstrated as a material bottleneck; that optimization remains subject to the repository's measure-first rule.

### Phase 8 — Kavacha and provider boundaries — complete

The outbound-provider audit found four Shakti REST transports: Azure, Bhashini, Gemini, and Mistral. In normal Sarathi execution, Pravaha validates the planned capability and authorizes its owning plugin's `SecurityDeclaration` through Kavacha before Yantra invokes the capability; retry execution uses the same authorization boundary. The existing cloud declarations already state PII access, network access, external processing, and required secret-policy names, and the existing Kavacha suite already covers cloud allow/deny behavior.

Provider/client credential lookup remains configuration discovery, not a second authorization subsystem. Direct client classes remain reusable lower-level transports and intentionally do not embed Kavacha policy logic; adding provider-local or client-local authorization would duplicate the existing runtime owner and complicate standalone use. No credential abstraction, lazy-secret layer, provider wrapper, Protocol, or new test module was added.

The audit removed absolute `zero-leak` / `privacy-safe` transport claims from cloud-client documentation. Concrete credential redaction and sanitized error handling remain unchanged, but the code no longer promises an unprovable universal property. No HTTP payload, credential fallback, provider registration, policy behavior, OCR/translation output, accuracy, or performance path changed in Phase 8. No new regression test was added because the existing Kavacha cloud-policy tests already cover the unchanged authorization boundary.

A subsequent end-to-end provider-flow revalidation found that Azure, Gemini, and Bhashini translation manually rebuilt canonical documents and discarded unchanged document/page state. Those three existing capabilities now use `dataclasses.replace()` to preserve upstream canonical fields while keeping their current remote-call, direction, artifact, and fallback behavior unchanged; their existing provider tests were strengthened in place.

### Phase 9 — Shared text/typography utilities — in progress

Consolidate helpers only when their semantic contract is identical across real consumers. Remove compatibility re-exports after callers migrate.

The first semantic audit confirmed that OCR and Translation use the same Devanagari-presence rule, Latin/Devanagari output fonts, positive-size validation, and 12 pt fallback. Those primitives now have one neutral owner in `shakti.text`; OCR retains its separate line-height/heading inference. Translation's historical zero-argument `normalize_size()` call contract is preserved through a narrow adapter instead of silently broadening or narrowing either capability API. Font Conversion remains separate because its size calibration and span protection have different evidence and conversion semantics.

The same audit confirmed an identical Markdown-table parser in Gemini, Mistral, and Bhashini OCR. That migration remains in Phase 9; Azure's structured Document Intelligence table parser and media-type inference helpers are different concerns and are not being conflated with the shared text contract.

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
