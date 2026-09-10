# Sarathi V3 — Cleanup and Optimization Plan

**Status:** Active roadmap  
**Applies to:** Sarathi V3 after the Mukha Starlette/Uvicorn transport migration  
**Updated:** 10-09-2026

## 1. Objective

Sarathi V3 cleanup is not a redesign. The objective is to reduce code, ownership ambiguity, compatibility machinery, duplicated work, and avoidable runtime cost while preserving user-visible behavior.

The order is deliberate:

```text
remove dead code
    ↓
simplify ownership
    ↓
consolidate duplicate logic
    ↓
measure runtime
    ↓
optimize proven hot paths
    ↓
harden regression gates
```

Optimization work must be evidence-driven. A faster implementation is not an improvement if it adds architectural machinery, weakens correctness, changes output semantics, or makes the code harder to reason about.

## 2. Non-negotiable rules

1. **Behavior first.** Existing API payloads, document outputs, warnings, security checks, cancellation, retries, artifact safety, and browser behavior remain stable unless a separate product change explicitly approves otherwise.
2. **One subsystem at a time.** Finish cleanup, tests, documentation, and CI for one phase before starting the next.
3. **Delete before abstracting.** Remove obsolete compatibility code, dead modules, unused wrappers, duplicate helpers, and stale tests before introducing any replacement abstraction.
4. **One decision authority.** A concern such as planning, device selection, artifact promotion, or security policy must have one clear owner.
5. **No speculative framework layers.** Prefer functions, dataclasses, focused services, and mature libraries over manager/factory/coordinator layers created only for symmetry.
6. **Measure before optimization.** CPU, memory, I/O, startup time, request latency, OCR throughput, and artifact write cost must be measured before performance changes are accepted.
7. **Do not optimize test-only numbers.** Benchmarks must represent real Sarathi workloads.
8. **No hidden fallbacks.** Performance work must not silently change execution profile, OCR engine, device, language, or document-processing semantics.
9. **Security remains fail-closed.** Path containment, loopback-only web access, Host/Origin validation, secret handling, and outbound-provider policy may not be weakened for speed.
10. **CI is the phase gate.** Lint, architecture sanity, TypeScript build, deterministic Python tests, and Playwright browser tests must be green before a cleanup phase is considered complete.

## 3. Target end state

The desired V3 shape is a small number of clear runtime responsibilities:

```text
Agni
  composition + lifecycle

Nabhi
  registry + planning + pipeline execution

Shakti
  document capabilities

Yantra
  small execution/device helpers only

Kavacha
  real security/privacy policy at actual I/O boundaries

Smriti
  optional cache with explicit ownership

Darpana
  lightweight runtime/event history

Mukha
  Starlette transport + presentation state + TypeScript UI
```

Names are not the cleanup target. Responsibility count, coupling, duplicate state, and unnecessary indirection are.

---

# Phase 0 — Complete the Mukha Starlette migration

## Scope

Finish the current transport migration before broader cleanup starts.

## Remove

- `BaseHTTPRequestHandler`-era request dispatch code.
- `ThreadingHTTPServer` compatibility code.
- handler-oriented static serving helpers.
- handler-oriented file streaming helpers using `send_response`, `send_header`, `wfile`, or equivalent stdlib server APIs.
- compatibility imports that exist only because `http_handler.py` used to own unrelated contracts.

## Consolidate

- Starlette routes own HTTP routing.
- Starlette `Response` / `JSONResponse` / `FileResponse` own responses.
- Starlette `StreamingResponse` owns SSE.
- Uvicorn owns ASGI serving.
- `RunCoordinator` owns run-start result/status contracts.
- `security.py` owns Host/Origin validation and public error sanitization.

## Regression gates

- no production import from `http.server` inside Mukha.
- no `send_response`, `send_header`, `end_headers`, or `wfile` transport path remains.
- loopback-only binding remains enforced.
- Host and Origin rejection tests remain.
- CSP, `nosniff`, frame policy, Referrer-Policy, and Cache-Control tests remain.
- SSE state events remain compatible with the browser client.
- artifact and preview file containment tests remain.
- deterministic tests and Playwright browser tests green.

## Done when

The old HTTP transport can be deleted completely with no compatibility shell.

---

# Phase 1 — Mukha module cleanup

## Goal

After Starlette stabilizes transport, reduce Mukha to presentation responsibilities only.

## Work

- remove dead web helpers made obsolete by Starlette.
- collapse one-function or pass-through web modules when they do not create a meaningful ownership boundary.
- remove duplicated request parsing and response formatting.
- keep document preview extraction separate only where it contains substantial document-format logic.
- move run-state contracts and worker-state logic to `runner.py`, not HTTP modules.
- ensure `server.py` contains server lifecycle/facade behavior only.
- ensure `app.py` contains routes, request translation, response translation, and middleware only.
- remove private compatibility properties that tests no longer require.
- eliminate web-layer access to internal mutable dictionaries where a focused coordinator method can provide the same behavior.

## Optimization checks

Measure:

- server startup time.
- `/api/state` latency when idle.
- `/api/state` latency during an active OCR run.
- SSE CPU usage while idle.
- SSE update frequency during active work.
- memory retained after multiple completed runs.

Do not introduce WebSockets unless SSE is proven to be a material bottleneck.

## Done when

Mukha transport and presentation code can be understood without knowing the internals of OCR, planning, caching, or artifact promotion.

---

# Phase 2 — Planning and execution ownership cleanup

## Goal

Guarantee one planning authority and one execution authority.

## Required ownership

- **Kosh:** declaration/registry storage and validation.
- **Manthan:** requirement resolution, dependency resolution, profile compatibility, continuation/handoff planning.
- **Pravaha:** execute the plan returned by Manthan; retries/quarantine are execution concerns, not alternate planning authority.

## Cleanup

- remove any remaining capability/profile selection logic from Pravaha that duplicates Manthan.
- remove plan splicing logic from execution code if Manthan can return the continuation plan directly.
- remove redundant validation performed identically in both registry and planner.
- retain recursive prerequisite resolution, cycle detection, unsupported-profile errors, continuation requests, OCR handoffs, warning accumulation, and cancellation.

## Optimization checks

Measure:

- plan-resolution time for single-stage requests.
- plan-resolution time for multi-stage dependency chains.
- number of registry lookups per request.
- repeated resolution work during continuation/handoff.

Possible optimization only if measured:

- immutable lookup maps inside Kosh.
- request-local plan memoization.
- cached dependency graph validation when registry generation has not changed.

Avoid a global planning cache unless invalidation is trivial and proven useful.

## Done when

Pravaha never independently chooses a different capability/profile route from the route selected by Manthan.

---

# Phase 3 — Yantra and execution-resource simplification

## Goal

Reduce hardware/executor machinery to what real workloads require.

## Cleanup

- inventory leases, slots, pools, allocation records, and hybrid scheduling structures.
- identify which structures affect actual concurrency/correctness and which exist only as framework policy.
- remove duplicated device-selection decisions from OCR capability code or Yantra; retain exactly one selection path.
- keep capability-specific workload knowledge in the capability.
- keep generic CPU/GPU/concurrency execution helpers in Yantra.

## Optimization checks

Measure real OCR workloads:

- single-page latency.
- 10-page throughput.
- 100-page throughput.
- peak resident memory.
- CPU utilization.
- GPU/OpenVINO utilization where available.
- worker startup/model warm-up cost.
- queue wait time versus compute time.

Tune only after those measurements exist.

Likely optimization candidates:

- reuse loaded OCR models instead of repeated initialization.
- bounded worker pools.
- avoid unnecessary image copies/conversions.
- batch work only where the selected engine benefits from batching.
- avoid oversubscribing CPU/OpenVINO threads.

## Done when

Yantra is a small execution utility rather than a second runtime kernel.

---

# Phase 4 — OCR pipeline optimization

## Goal

Optimize the highest-cost document path without changing OCR semantics.

## Cleanup first

- consolidate duplicate OCR preprocessing helpers.
- consolidate typography/font-size normalization with shared document typography utilities where behavior is equivalent.
- delete obsolete engine adapters and fallback branches that cannot be reached by supported configurations.
- keep engine-specific behavior inside engine adapters, not generic coordinators.

## Benchmark corpus

Maintain a small checked-in or reproducibly generated benchmark set covering:

- clean English scan.
- Hindi/Devanagari scan.
- mixed Hindi-English page.
- low-resolution scan.
- rotated page.
- multi-page PDF.
- text-native PDF that should avoid unnecessary OCR.

## Metrics

Track:

- pages/second.
- p50 and p95 page latency.
- peak memory.
- model initialization time.
- preprocessing time.
- inference time.
- postprocessing time.
- artifact generation time.
- character/word accuracy proxies where labelled samples exist.

## Optimization candidates

Only after profiling:

- skip OCR for pages proven text-native and sufficient for the requested capability.
- cache immutable model/session objects.
- reuse rendered page buffers where multiple downstream stages need them.
- avoid repeated decode/encode cycles.
- minimize PIL/OpenCV/NumPy format conversions.
- limit DPI to the quality point beyond which OCR accuracy no longer improves materially.
- batch recognition where RapidOCR/OpenVINO shows real benefit.

## Rejection rule

Reject an optimization if it improves speed but materially worsens extraction accuracy, ordering, language handling, or deterministic behavior.

---

# Phase 5 — Artifact and quarantine cleanup

## Goal

Keep strong filesystem safety while removing ceremonial artifact machinery.

## Preserve

- authorized output roots.
- temporary write followed by atomic promotion/replacement.
- no partial final artifact on failure.
- run/artifact identity.
- containment validation before download/preview.

## Review for deletion/consolidation

- workspace wrappers.
- promotion/finalization layers that only forward calls.
- duplicate manifest representations.
- separate atomic-I/O helpers that perform the same operation.
- persistent quarantine structures that have no real replay/batch workflow.

## Optimization checks

Measure:

- duplicate filesystem scans.
- file copy count.
- bytes copied versus bytes written once.
- manifest serialization cost.
- artifact promotion latency for large PDF/DOCX outputs.

Prefer rename/atomic replace on the same filesystem instead of copy + delete where safe.

## Done when

Artifact safety is obvious from one short code path.

---

# Phase 6 — Cache and state cleanup

## Goal

Make caching optional, observable, and cheaper than recomputation.

## Smriti review

For every cache entry type document:

- cache key.
- source of truth.
- invalidation rule.
- maximum lifetime.
- approximate size.
- hit-rate benefit.

Delete cache entries without a clear invalidation rule or measurable benefit.

## Optimization checks

Track:

- L1 hit/miss ratio.
- L2 hit/miss ratio.
- serialization/deserialization time.
- SQLite read/write latency.
- cache size growth.
- startup cleanup cost.

Avoid caching large canonical documents merely because they are available; compare serialization/I/O cost with recomputation cost.

## Mukha state

- avoid storing duplicate copies of terminal summaries when Darpana already has the authoritative history unless the in-memory copy materially improves active-session behavior.
- bound historical in-memory maps.
- verify completed runs release request callbacks, large documents, page buffers, and worker references.

## Done when

Long-running local sessions do not show unbounded memory/cache growth.

---

# Phase 7 — Darpana telemetry simplification

## Goal

Keep useful diagnostics without maintaining an internal observability framework.

## Cleanup

- consolidate event/history records where multiple schemas describe the same runtime fact.
- keep timing/error fields needed by UI diagnostics and performance analysis.
- remove telemetry records that are never queried, shown, tested, or used operationally.
- avoid synchronous high-frequency persistence in OCR inner loops.

## Optimization checks

Measure telemetry overhead with telemetry enabled versus disabled for:

- one small document.
- 100-page OCR run.

Telemetry overhead should remain small relative to processing time and must not become the dominant cost for lightweight native extraction.

Batch or sample only high-frequency progress events; do not sample errors or terminal run facts.

---

# Phase 8 — Kavacha and cloud boundary cleanup

## Goal

Make security documentation match actual I/O ownership.

## Cleanup

- identify every outbound HTTP client.
- identify every environment/API-key read.
- identify every user-document payload that can leave the machine.
- route policy checks through one real boundary before outbound transfer.
- remove documentation claims for controls that are not actually implemented.

## Performance constraint

Security checks should be cheap, but correctness wins over micro-optimization. Cache only immutable policy decisions whose inputs are explicit and safe to key.

## Done when

A code search for network clients and secret access maps cleanly to the documented security model.

---

# Phase 9 — Shared text, typography, and document utilities

## Goal

Remove capability-level duplicate transformations.

## Candidates

- span protection.
- font-size normalization.
- Unicode/script classification.
- punctuation/whitespace normalization.
- document traversal helpers.
- page/span text replacement utilities.

## Rule

Do not merge helpers merely because they look similar. Consolidate only when their semantic contract is the same and shared tests can express that contract.

Compatibility re-exports should be removed after all call sites migrate.

---

# Phase 10 — Dependency and import optimization

## Goal

Reduce startup cost and installation weight without creating lazy-import complexity everywhere.

## Work

- audit optional dependencies against actual capability boundaries.
- keep OCR, translation, cloud, and similar heavy stacks optional where product behavior permits.
- remove unused direct dependencies.
- avoid importing OCR/model libraries during architecture tests, CLI help, or lightweight native-only workflows.
- move expensive imports inside the owning capability only when startup profiling proves material benefit.

## Metrics

- clean environment install size.
- base import time: `python -c "import sarathi"`.
- CLI help startup time.
- Agni bootstrap time.
- peak memory immediately after bootstrap.

---

# Phase 11 — Frontend production cleanup

## Goal

Complete the TypeScript/Preact frontend migration after backend transport is stable.

## Cleanup

- remove legacy JS screen files once feature parity exists in the TypeScript application.
- remove legacy HTML/CSS assets once no runtime route or browser test depends on them.
- keep one state contract, not parallel legacy and V3 browser state models.
- keep direct API/SSE client code small and typed.

## Optimization checks

Measure:

- production bundle size.
- first render time on localhost.
- `/api/state` request count.
- unnecessary re-renders during SSE updates.
- memory usage during long active runs.

Use component memoization or selector optimization only after render profiling shows benefit.

## Done when

Mukha serves one production frontend implementation.

---

# Phase 12 — Test-suite cleanup and acceleration

## Goal

Keep strong behavioral coverage with less duplicated setup and less CI time.

## Cleanup

- delete tests for removed compatibility layers.
- merge tests that assert the same behavior through obsolete architecture names.
- keep security, data-loss, cancellation, planning, OCR handoff, artifact atomicity, and browser acceptance tests strong.
- separate real-model/performance suites from deterministic CI without weakening deterministic coverage.

## Optimization

Measure per-test-file runtime and attack the slowest deterministic fixtures first.

Possible improvements:

- session-scoped immutable model fixtures where isolation permits.
- shared generated document fixtures.
- avoid repeatedly provisioning the same expensive resource inside one job.
- parallelize only suites proven independent and deterministic.

Do not mock away the behavior a test exists to validate.

---

# Phase 13 — Documentation and architecture reconciliation

## Goal

End with one truthful architecture description.

## Work

- mark superseded V2 architecture sections as historical where necessary.
- remove stale module inventories.
- ensure README, AGENTS, Vedas, pyproject, CI, and production code agree on runtime ownership.
- delete documentation for removed abstractions rather than preserving them as current concepts.
- keep historical changelog entries historical; do not treat them as current requirements.

## Done when

A new maintainer can determine current ownership without reading git history.

---

# 4. Performance baseline protocol

Before Phase 3 onward, capture one reproducible baseline on a representative machine.

Record:

| Workload | Primary metric | Secondary metrics |
|---|---|---|
| CLI/bootstrap | startup ms | RSS, import time |
| Native text document | end-to-end ms | CPU, artifact write ms |
| 1-page OCR | end-to-end ms | preprocess/inference/postprocess |
| 10-page OCR | pages/s | p95 page latency, peak RSS |
| 100-page OCR | pages/s | peak RSS, queue time |
| Translation | chars/s or tokens/s | peak RSS, model init |
| Bank statement extraction | end-to-end ms | OCR share, parsing share |
| `/api/state` idle | p50/p95 latency | allocations/RSS |
| SSE idle 5 min | CPU time | bytes/events sent |
| artifact download | throughput | CPU/RSS |

Every optimization PR must state:

```text
baseline
change
new measurement
behavioral risk
regression test
```

A performance claim without before/after measurement is not accepted as an optimization.

# 5. Repository cleanup checklist

Run this checklist after every phase:

- no deleted module remains in imports, `__all__`, tests, docs, or manifest files.
- no compatibility shim remains without a named consumer and removal condition.
- no duplicate owner exists for the concern changed in the phase.
- no new manager/factory/coordinator is added unless it owns real state or policy.
- no stale feature flag remains permanently enabled/disabled.
- no dead environment variable remains documented.
- no test is changed merely to hide a regression.
- no security assertion is weakened for framework compatibility.
- `uv.lock` and frontend lockfiles match their manifests.
- lint, architecture, TypeScript, deterministic Python, and browser CI are green.

# 6. Priority order

The implementation priority is:

```text
P0  Finish Starlette migration and delete old HTTP transport
P1  Mukha module cleanup
P2  Planning/execution ownership cleanup
P3  Yantra simplification
P4  OCR profiling and optimization
P5  Artifact/quarantine simplification
P6  Cache/state boundedness
P7  Telemetry simplification
P8  Kavacha/cloud I/O boundary reconciliation
P9  Shared text/typography consolidation
P10 Dependency/import optimization
P11 Finish TypeScript frontend migration and delete legacy UI
P12 Test-suite acceleration
P13 Documentation reconciliation
```

This order may change only when a measured production bottleneck, correctness issue, or security defect justifies moving a phase earlier.

# 7. Definition of V3 cleanup complete

V3 cleanup is complete when all of the following are true:

- custom HTTP server infrastructure is gone.
- no known compatibility shell exists without a removal deadline/consumer.
- registry, planning, execution, hardware selection, artifacts, security, cache, telemetry, and presentation each have one clear authority.
- duplicate document/text/typography helpers have been reconciled where their contracts are genuinely identical.
- performance baselines exist and major hot paths have been profiled.
- accepted optimizations show measured improvement without output regressions.
- memory/cache/history growth is bounded for long-running local sessions.
- legacy frontend assets are removed after TypeScript parity.
- current Vedas and README describe the code that actually runs.
- complete CI remains green.

The intended result is not the smallest possible codebase. It is the smallest codebase that clearly preserves Sarathi's real product behavior, safety, and performance requirements.
