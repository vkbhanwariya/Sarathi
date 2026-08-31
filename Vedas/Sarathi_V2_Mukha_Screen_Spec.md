# Sarathi V2 — Mukha Screen Specification

**Document Updated:** 31-08-2026, 09:17 PM IST (Asia/Kolkata)  
**Status:** Canonical detailed specification referenced by the main
[Sarathi V2 README](../README.md).

All values shown inside wireframes are illustrative layout fixtures only. They
must never become production defaults or fallback metrics; production screens
render measured canonical state or `—`.

## 1. Purpose

This document defines the minimal but information-rich interactive console for **Mukha — Console & Presentation**.

The design guarantees that:

- every meaningful operation that remains active for more than five seconds is visibly represented;
- the user can see which file is being read, processed, extracted, converted, translated, consolidated, validated, or written;
- current stage, file time, stage time, overall run time, progress and terminal outcome remain visible;
- every successful, partially successful, failed, cancelled, retried, or quarantined run ends on a factual run summary;
- unavailable values remain unavailable rather than becoming fake metrics;
- the console remains compact by default and reveals deeper detail only when requested or operationally important.

## 2. Locked Presentation Boundary

**Mukha — Console & Presentation** presents canonical state. It does not execute capabilities, calculate telemetry, fabricate confidence, approve corrections, select backends, retry work, or decide quarantine.

``` text
Pravaha / Yantra / capability owners execute and decide
                         ↓
Darpana — Telemetry & Tracing records canonical facts
├── Maruti — Runtime, Logging & Performance Telemetry
└── Pramana — Confidence & Accuracy Telemetry
                         ↓
Mukha presenter builds typed presentation state
                         ↓
Textual screens render state and emit typed user intents
                         ↓
Canonical runtime owner accepts or rejects the requested action
```

There is one interactive UI generation:

- **Textual** owns application, screens, widgets, navigation and reactive updates.
- Rich `Text`, tables and other renderables may be displayed inside Textual widgets.
- There is no parallel `ConsoleManager`, `RichConsolePlugin`, profiler UI, capability-local console, or telemetry bridge.
- TOML may describe static labels, default visibility, layout choice and theme references only. Python owns typed state, behavior, callbacks, conditions, navigation and wiring.

### 2.1 Option and logic synchronization

Screen options are not maintained as hard-coded parallel lists. A capability
declares its supported actions/options through **Sankalpa — Canonical
Contracts**; runtime availability and **Kavacha — Security & Privacy** policy
produce the current `available_actions`; Mukha renders that typed snapshot.

``` text
Capability support
      ↓
Current runtime/dependency/security state
      ↓
available_actions[]
      ↓
Mukha renders enabled/disabled options with factual reasons
      ↓
User submits action_id
      ↓
Canonical runtime owner revalidates before execution
```

TOML may reorder or relabel a known `action_id`, but cannot create behavior.
An unknown action ID is a validation error. Revalidation at submission prevents
a stale screen from executing an option that became unavailable after render.

## 3. V1 Screen Audit and V2 Disposition

V1 contains two parallel presentation generations: Textual screens and a large Rich console renderer. The useful behavior is consolidated below rather than migrated class-for-class.

| V1 surface | Useful behavior | V2 destination |
|---|---|---|
| Textual Dashboard + Rich Main Menu | run entry, readiness, current job, quick navigation | **Screen 1: Griha — Home & Run Setup** |
| Textual Workflow + Rich consolidation/font/OCR/translation/batch progress | file list, stage status, duration, live progress | **Screen 2: Pravritti — Live Run Monitor** |
| Rich live OCR progress | multi-file progress, active file/page and measured throughput | **Screen 2**, capability-neutral form |
| Textual OCR Review + Rich page-health/review/post-OCR screens | source/output comparison, quality evidence, targeted action | **Screen 3: Pariksha — Review & Exceptions** |
| Rich run summaries + universal telemetry summary + post-completion menu | terminal result, timings, output files, warnings and next actions | **Screen 4: Samapti — Run Summary** |
| Textual Performance + Logs + Plugins; Rich Doctor + Compute Monitor | performance, activity logs, quality, runtime and component health | **Screen 5: Nirikshana — Run Inspector** with tabs |
| V1 command palette | keyboard-first navigation | one Textual command-palette overlay |
| V1 capability-specific menus | capability launch choices | Home requirement/profile selection; capability logic remains outside Mukha |

The V1 review is based on the repository at commit [`032baf3`](https://github.com/vkbhanwariya/Sarathi/tree/032baf30305116bc1d613041191a3eefe1d6643c/Chakra/Darshana), including its [Textual screens](https://github.com/vkbhanwariya/Sarathi/tree/032baf30305116bc1d613041191a3eefe1d6643c/Chakra/Darshana/Screens), [Rich console renderer](https://github.com/vkbhanwariya/Sarathi/blob/032baf30305116bc1d613041191a3eefe1d6643c/Chakra/Darshana/Rich_Console_Plugin.py), and [typed UI state/events](https://github.com/vkbhanwariya/Sarathi/tree/032baf30305116bc1d613041191a3eefe1d6643c/Chakra/Darshana/Contracts).

### V1 behavior explicitly rejected

- hard-coded plugin counts, worker counts, cache rates, success rates, latency, memory, confidence or sample logs;
- fallback values such as assumed OCR accuracy, assumed speed or default successful summaries;
- UI imports of profiler globals, raw telemetry buffers, plugin managers or execution internals;
- capability-specific duplicated progress tables and summary renderers;
- a performance advisor making execution recommendations inside telemetry/presentation;
- UI buttons directly initiating backend selection, retry, cloud processing or cache policy without the canonical request path;
- a separate screen merely because a V1 class existed.

## 4. Global Screen Shell

All five screens share one compact shell.

``` text
┌ SARATHI ─ <screen> ─ <run status> ─ <run elapsed> ─ <local/offline policy> ┐
│ Breadcrumb / selected run / selected file                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ Screen content                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ F1 Home  F2 Run  F3 Review  F4 Summary  F5 Inspector  Ctrl+P  ? Help  Q    │
└─────────────────────────────────────────────────────────────────────────────┘
```

Shell rules:

- Header shows only factual status: `STARTING`, `READY`, `RUNNING`, `REVIEW`, `SUCCESS`, `PARTIAL`, `FAILED`, `CANCELLED`, or `QUARANTINED`.
- Run elapsed is sourced from Maruti's monotonic run span.
- Security indicator shows the effective Kavacha policy, not a generic “secure” claim.
- Footer displays currently available bindings; unavailable actions are omitted or disabled with a reason.
- Critical warning/failure information is expressed with text and glyphs as well as color.
- Selected file and stage survive screen changes because they are presentation state, not widget-local state.

## 5. Progress Visibility Contract

### 5.1 Five-second rule

Every meaningful operation follows this visibility policy:

| Operation state | Required presentation |
|---|---|
| Started and under 5 seconds | Current stage line is visible on the Live Run screen; no large card is added. |
| Still running at 5 seconds | Automatically promote it to the **Long-running operations** area. |
| Units are known | Show completed/total units, determinate progress bar and ETA only when enough measured evidence exists. |
| Units are unknown | Show an indeterminate activity indicator, elapsed time, current file/stage and last factual activity. |
| No update received recently | Keep elapsed time visible and show `Waiting for activity`; do not invent progress or mark failure. |
| Completed | Freeze factual duration and collapse the row unless warning/failure/review attention exists. |
| Failed/cancelled/quarantined | Keep the row expanded with terminal status, Dosh classification and next available canonical action. |

Operations covered include bootstrap, system initialization, model/backend loading, warm-up, file discovery, file reading, queue wait, preprocessing, OCR, extraction, mapping, conversion, translation, consolidation, analysis, validation, persistence, export, retry, fallback, quarantine and shutdown.

### 5.2 Progress hierarchy

``` text
Run
└── File
    └── Capability / Stage
        └── Operation / Backend span
```

The UI always presents the highest reliable progress level and lets the user drill down. It never averages unrelated percentages into a fake overall number.

### 5.3 Time semantics

- **Run time:** terminal run end minus run start using Maruti's monotonic timestamps.
- **File time:** first file-related span start through that file's terminal outcome.
- **Stage time:** exact stage span duration.
- **Queue/wait time:** shown separately from execution time where measured.
- **Total measured work:** optional sum of spans, explicitly labelled; it may exceed wall-clock run time when work is parallel.
- Missing measurement renders as `—`, not `0.00s`.

## 6. Screen 0 Overlay: Aarambha — Startup Progress

This is a temporary overlay, not a sixth primary screen. It appears only when interactive startup has not reached `READY` within five seconds.

``` text
┌ Aarambha — Starting Sarathi                                      00:08.4 ┐
│ ✓ Configuration loaded                                             0.12s │
│ ✓ Darpana recording active                                        0.04s │
│ ● Discovering capabilities…                                       6.91s │
│ ○ Detect execution devices                                             — │
│ ○ Warm required backends                                               — │
│                                                                            │
│ Current: validating OCR capability metadata                               │
└────────────────────────────────────────────────────────────────────────────┘
```

Requirements:

- Mukha replays already-recorded Maruti bootstrap events when it mounts, so early initialization time is not lost.
- Only actual initialization stages are shown; no fixed list is fabricated.
- If startup fails, the overlay becomes a terminal failure view with the Dosh classification and safe diagnostic action.

## 7. Screen 1: Griha — Home & Run Setup

Purpose: select inputs and requirements, inspect factual readiness, and start one canonical request.

``` text
┌ SARATHI ─ Griha — Home ─ READY ─ Local policy: active ┐
│ Requirement: Bank Statement Consolidation            │
├──────────────────── Inputs ────────────────────────────┤
│ 248 files selected • 1.82 GB                         │
│ PDF 176 • XLSX 38 • CSV 34                           │
│ [Add Files] [Add Folder] [Paste Paths] [View All]    │
├──────────────────── Preflight ─────────────────────────┤
│ 240 eligible • 5 protected • 2 unreadable • 1 unsupported│
│ [View Issues] [Remove Blocked]                       │
├──────────────────── Request ───────────────────────────┤
│ Output: …/Output/Bank-Consolidation/Run-20260831-… │
│ Policy: Local only                                   │
│                               [Start Eligible Files] │
├────────────────── Recent Runs ─────────────────────────┤
│ PARTIAL  14:31  248 files  02:18.4  Consolidation   │
└───────────────────────────────────────────────────────┘
```

### 7.1 Multiple-file selection and scale

- `Add Files` uses the native Windows multi-select file dialog.
- `Add Folder` adds supported candidates from a selected folder; recursive
  scanning is an explicit option.
- `Paste Paths` accepts multiple copied paths.
- `Input/` is an optional convenience inbox; selection may use any permitted
  file or folder and never depends on `Input/Documents`-style subfolders.
- Canonical request-input construction normalizes paths, removes duplicates
  and verifies existence. **Darshana — Identify** validates actual content.
- Ten or fewer inputs are shown individually. More than ten are grouped by
  detected/declared type with count and measured total size; `View All` opens
  the searchable individual table.
- Blocked or problematic files remain inspectable with a factual reason.

### 7.2 Requirement-driven controls

Only controls supported by the chosen capability are rendered. Bank Statement
Consolidation has no processing-profile selector. Selecting OCR exposes the
four OCR profiles below. Changing requirement refreshes controls from the
canonical `available_actions` snapshot rather than screen-local conditionals.

### 7.3 OCR profile selection

Mukha renders the four profiles owned by the
[OCR Specification](Sarathi_V2_OCR_Spec.md): Instant, Accurate, Layout
Preserving, and Custom. There is no Auto option.

``` text
OCR Profile

● Instant
○ Accurate
○ Layout Preserving
○ Custom
Average: — confidence • — time/page
```

The default view shows measured comparable average confidence and time per page
when available, otherwise `—`. Standard engine bindings are read-only. Custom
shows only supplied tested engine/profile combinations; unavailable combinations
are disabled with their supplied reason. Mukha does not infer compatibility or
select an engine.

### Always visible

- selected input count and measured total size;
- requirement and only the controls that requirement supports;
- effective local/external policy;
- output destination;
- start availability and validation errors;
- small recent-run list sourced from real persisted run history when available.

### On demand

- individual input file table;
- resolved plan preview after **Manthan — Capability Resolver** provides it;
- capability/backend details without allowing Mukha to override resolution;
- tested Custom OCR engine/profile combinations.

### Not shown

- generic “all systems healthy” cards;
- plugin counts without a user need;
- sample throughput, expected accuracy or estimated completion based on defaults;
- buttons for capabilities that are not registered and usable;
- a profile selector for Bank Statement Consolidation.

## 8. Screen 2: Pravritti — Live Run Monitor

Purpose: make the entire active run understandable without forcing the user into logs.

``` text
┌ SARATHI ─ Pravritti — Live Run ─ RUNNING ─ 01:42.8 ─ Run 8F2A ┐
│ Overall: 218/420 pages • 6 active • 196 queued                │
│ [█████████████░░░░░░░░░] 51.9% • ETA 02:31 (measured)        │
│ Current run: 0.39s/page • average confidence 95.2%            │
├──────────────── Active Workers / Pages ────────────────────────┤
│ Worker File                    Page   Stage         Page Time │
│ W-1    HDFC_April_2026.pdf     14/42  Recognize         1.21s│
│ W-2    SBI_March.pdf            8/31  Preprocess        0.42s│
│ W-3    ICICI_May.pdf           21/48  Validate          2.84s│
├──────────────── Selected Page / Stage ─────────────────────────┤
│ HDFC_April_2026.pdf • Page 14 • engine/model                  │
│ runtime/GPU • Queue 0.08s • Raster 0.21s • Prep 0.16s        │
│ Inference 0.63s • Validate 0.13s • Total 1.21s               │
│ Confidence: calculating • Accuracy: —                         │
├──────────────── Long-running Operations (>5s) ─────────────────┤
│ ● Model warm-up • GPU • 08.3s • activity 0.4s ago            │
│ ● Page 17 fallback • engine/CPU • 06.1s • waiting 3.2s       │
├──────────────── Device Progress ────────────────────────────────┤
│ GPU 176 pages • 0.34s/page • conf 95.8%                       │
│ NPU  24 pages • 0.52s/page • conf 94.1%                       │
│ CPU  18 pages • 1.18s/page • conf 89.7%                       │
│ [All Files/Pages] [Activity] [Performance]                     │
└────────────────────────────────────────────────────────────────┘
```

### Required fields

| Area | Factual fields |
|---|---|
| Run | run ID, terminal/active file counts, elapsed, overall progress when derivable, ETA provenance |
| Current file | ordinal, safe display name, file elapsed, current capability and stage |
| Active workers/pages | worker ID, file, page/unit, engine, backend/device, stage, page elapsed and status |
| Current operation | backend/device when known, completed/total units, measured throughput, stage elapsed and last factual activity |
| File pipeline | every input file, current stage, status, progress, file time, warning/failure marker |
| Stage timeline | completed/current/pending stages and measured durations |
| Long-running area | every active operation crossing five seconds, including initialization and warm-up |
| Device progress | current-run pages/units, average time and average confidence by GPU/NPU/CPU when measured |
| Activity | bounded Maruti diagnostic events relevant to the selected run/file |

### Interaction

- Arrow/Enter selects a file and expands its stage timeline.
- `L` opens the selected run's activity log in Inspector.
- `P` opens performance details for the selected file/stage.
- `Q` requests cancellation through the canonical runtime path; a modal explains what can be safely stopped or preserved.
- Failed and review-required files remain pinned above completed files.
- Selecting a worker/backend view is an inspection action only; Mukha cannot reassign work.
- If a worker/page has no recent event, its elapsed time continues and the row
  shows the last activity plus `Waiting for activity`; Mukha does not infer a
  failure or initiate retry.

### Minimalism rules

- Default view shows active workers/pages, one selected-page/stage breakdown,
  long-running work and a compact device summary.
- For large batches, all active, warning and failed items remain visible; only
  the latest completed items are shown. The complete searchable file/page
  table and worker history live in Inspector.
- Resource gauges and full logs remain in Inspector.
- Completed fast stages collapse to one line.
- A progress bar is used only where a reliable denominator exists.

## 9. Screen 3: Pariksha — Review & Exceptions

Purpose: review only items requiring human attention. The screen is unavailable
when no review item exists, and the same compact layout serves OCR, mapping,
consolidation, font conversion and translation.

``` text
┌ Review ─ 3 pending ──────────────────────────────┐
│ 1/3 • HDFC_April.pdf • Page 17 • OCR Low Conf  │
├───────────────────────────────────────────────────┤
│ Source : कुल जमा 1,25,750.50                    │
│ Output : कुल जमा 1,25,150.50                    │
│                                                   │
│ Confidence 71.2% • Validation: Amount mismatch   │
│ Accurate • Tesseract/CPU • Attempt 2 • 6.14s     │
├───────────────────────────────────────────────────┤
│ Correction: [1,25,750.50                       ] │
│                                                   │
│ [Accept] [Validate Edit] [Retry] [Unresolved]    │
│                                Previous  Next     │
└───────────────────────────────────────────────────┘
```

### Review rules

- Default view shows source, output, the decisive quality/validation evidence,
  execution binding, correction field and currently valid actions only.
- Additional evidence, provenance and source-page opening remain on demand.
- With more than ten items, the queue first groups by issue type and severity;
  critical financial/legal validation failures remain individually pinned.
- `Validate Edit` sends the proposal through capability validation before it
  can update the current result.
- Retry is a typed intent; Pravaha, Yantra and Kavacha retain their authority.
- Approved reusable knowledge is not written automatically. After separate validation/approval, it may be explicitly curated into the owning capability's `data/<capability>/anubhava.toml` for future runs.
- Raw secrets or unnecessary PII are not displayed or copied into review history.

## 10. Screen 4: Samapti — Run Summary

Purpose: always show a complete terminal summary after success, partial success, failure, cancellation or quarantine.

``` text
┌ SARATHI ─ Samapti — Run Summary ─ PARTIAL ─ Run 8F2A ┐
│ Started 14:40:29 • Ended 14:43:17 • Wall time 02:48.2│
│ Files: 412 success • 6 warning • 2 failed            │
├──────────────────── Outcome ──────────────────────────┤
│ Input 420 • Output 418 • Quarantined 1 • Retried 14  │
│ Final average: 0.61s/page • confidence 94.8%          │
├──────────────────── File Results ─────────────────────┤
│ PDF 390 • 384 success • 5 warning • 1 failed         │
│ TIFF 30 • 28 success • 1 warning • 1 failed          │
│ [View All Files/Pages]                                │
├──────────────── Device Execution Summary ─────────────┤
│ Device Pages Attempts Avg/Page p95/Page Avg Confidence│
│ GPU     310   318       0.32s    0.51s       95.6%   │
│ NPU      64    64       0.49s    0.72s       93.8%   │
│ CPU      46    53       1.26s    2.04s       89.4%   │
├──────────────────── Stage Time ───────────────────────┤
│ Initialization 1.2s • Warm-up 3.8s • Read 9.6s       │
│ Raster 41.2s • OCR 201.4s • Validate 18.1s • Write 4s │
├──────────────────── Quality ──────────────────────────┤
│ Confidence available: 418/420 pages • Review items: 3│
│ Accuracy: unavailable (no verified reference corpus)  │
├──────────────── Warnings / Failures ──────────────────┤
│ Axis_June.pdf • Page 9 • OCR_FAILURE • quarantined    │
├──────────────── Outputs & Actions ────────────────────┤
│ Output/OCR/Run-20260831-8F2A                          │
│ [Open output] [Review 3] [Inspect run] [New run]      │
└────────────────────────────────────────────────────────┘
```

### Mandatory summary content

- terminal run status and run identity;
- start, end and wall-clock run time;
- file counts by terminal status;
- every input file's terminal outcome and total processing time;
- capability/stage counts and measured timing breakdown;
- page/unit and attempt counts plus GPU/NPU/CPU breakdown when those devices
  participated in the run;
- retries, fallbacks, warnings, failures and quarantine outcome;
- output artifacts that actually exist;
- confidence coverage and review counts;
- accuracy only when a verified reference exists;
- safe next actions appropriate to the terminal state.

### Summary correctness

- A failed run still receives a summary.
- A cancelled run shows completed and preserved partial outputs.
- Parallel stage durations are not presented as wall-clock time.
- Device `measured work` is not presented as wall time when device spans ran in
  parallel.
- Output paths are confirmed artifacts, not planned filenames.
- The displayed destination comes from the canonical request/result artifact
  state; Mukha never constructs capability output paths itself.
- Summary data is a typed projection of canonical Result, Maruti and Pramana records—not a second report store.
- With more than ten files/pages, the default result area groups by type and
  outcome; warnings, failures and quarantined items remain individually visible.
- Terminal summaries persist through Darpana's canonical history and can be
  reopened from Home → Recent Runs after the UI closes. No separate report
  manager or summary database is created.

## 11. Screen 5: Nirikshana — Run Inspector

Purpose: expose detailed factual run data without creating separate Logs,
Performance, Plugin or Hardware screens.

``` text
┌ Run Inspector ─ Run 8F2A ─ PARTIAL ─ 05:49.2 ┐
│ [Activity] [Performance] [Quality] [System]   │
├────────────────────────────────────────────────┤
│ Selected: HDFC_April.pdf • Page 17            │
│                                                │
│ Stage          Device   Time    Status         │
│ Read           CPU      0.42s   Done           │
│ Rasterize      CPU      0.31s   Done           │
│ Preprocess     GPU      0.18s   Done           │
│ OCR Primary    GPU      0.63s   Low confidence │
│ OCR Fallback   CPU      6.14s   Review         │
│ Validate       CPU      0.13s   Warning        │
│                                                │
│ [All Files] [All Pages] [Filter] [Details]    │
└────────────────────────────────────────────────┘
```

The four tabs remain compact:

- **Activity:** time, level, file/page and safe event; filters and bounded
  auto-scrolling presentation.
- **Performance:** per-file/page/stage timing plus GPU/NPU/CPU counts, average,
  percentiles and throughput when measured.
- **Quality:** confidence coverage/distribution, validation outcomes, review
  items and verified accuracy only when reference truth exists.
- **System:** dependency/backend readiness, actual bindings, queue state,
  measured resources and telemetry/security degradation.

Full tables are searchable/filterable. Missing values remain `—`. Historical
profile evidence always includes comparable filters, sample count and
last-tested date. Inspector observes; it never recommends or changes execution.

Textual's official [TabbedContent](https://textual.textualize.io/widgets/tabbed_content/),
[DataTable](https://textual.textualize.io/widgets/data_table/) and
[RichLog](https://textual.textualize.io/widgets/rich_log/) provide the required
tabs, dynamic rows and bounded activity view without another UI system.

## 12. Reusable Overlays and Components

These are not additional full screens.

| Component | Purpose |
|---|---|
| Command palette | Searches navigation and currently allowed canonical actions from `available_actions`. |
| Cancellation modal | Explains preserved/completing work and sends a typed cancellation request; Pravaha controls the stop. |
| Failure modal | Shows file/page, Dosh classification, attempt, quarantine state and currently valid detail/retry/return actions. |

Together with **Aarambha — Startup Progress** in Section 6, these are the only
four overlays. Textual supports screen stacks, modal screens and a command
provider API: [screens](https://textual.textualize.io/guide/screens/),
[events and messages](https://textual.textualize.io/guide/events/),
[command API](https://textual.textualize.io/api/command/).

## 13. Typed Presentation State

Mukha owns presentation projections, not execution contracts.

``` text
ApplicationViewState
├── startup: StartupViewState
├── input_selection: InputSelectionView
├── preflight: PreflightView | None
├── available_actions: tuple[AvailableActionView, ...]
├── active_run: RunViewState | None
├── selected_file_id: FileId | None
├── review_queue: tuple[ReviewItemView, ...]
├── terminal_summary: RunSummaryView | None
└── inspector: InspectorViewState

RunViewState
├── run_id / status / started_at / elapsed_ns
├── terminal_files / total_files
├── overall_progress: KnownProgress | IndeterminateProgress
├── current_focus: OperationView | None
├── files: tuple[FileRunView, ...]
├── active_workers: tuple[WorkerPageView, ...]
├── device_progress: tuple[DeviceProgressView, ...]
└── long_running: tuple[OperationView, ...]

FileRunView
├── safe_name / ordinal / status / elapsed_ns
├── current_stage / current_operation
├── progress
├── warning_count / review_count
└── terminal_output_refs

OCRProfileEvidenceView
├── profile_id / fixed_engine_binding
├── comparable_sample_count / last_tested_at
├── average_page_duration_ns / p95_page_duration_ns
├── average_confidence / confidence_method
└── verified_accuracy: VerifiedMetricView | None
```

Rules:

- immutable snapshots are preferred at the screen boundary;
- every view item carries stable run/file/stage identity;
- duration uses integer nanoseconds internally and is formatted only for display;
- progress explicitly distinguishes known, indeterminate and unavailable;
- UI state never stores raw document content beyond the minimum selected review context;
- screen widgets subscribe to the presenter, not to Darpana exporters or internal buffers.
- `AvailableActionView` references canonical action IDs and never contains an
  executable callback from TOML or a capability implementation.
- Page, attempt, worker and device projections use stable canonical identities
  so dynamic row updates cannot overwrite a different page or retry.

## 14. Update and Concurrency Model

- Canonical runtime events arrive through one in-process typed Darpana consumer boundary.
- OCR page/pass facts share one `page_execution_id`: Maruti supplies performance
  timing and execution binding; Pramana supplies confidence, validation and
  verified accuracy when reference truth exists. Mukha joins their typed
  presentation projections without creating an OCR telemetry store.
- A Mukha presenter reduces those events into screen snapshots.
- Textual custom messages/reactive state update widgets on the UI thread.
- Runtime work remains outside the UI event loop. Textual workers are used only for UI-owned asynchronous work; threaded work must return to the main thread before changing widgets, consistent with Textual's [worker guidance](https://textual.textualize.io/guide/workers/).
- Presentation refresh may be coalesced to remain responsive, but telemetry recording is never dropped merely because a screen is not visible.
- Navigation away from the Live Run screen does not stop or detach the run.
- Before a run, profile evidence is labelled `Historical`; during execution it
  becomes a rolling `Current run` aggregate; after terminal state it freezes as
  `Final`. The three contexts are never mixed under one unlabeled number.

## 15. Adaptive Layout

| Terminal width | Layout behavior |
|---|---|
| 120+ columns | two-pane detail where useful; file table and selected timeline can coexist |
| 80–119 columns | stacked panels; essential columns remain visible |
| below 80 columns | compact table, abbreviated safe filename, drawers for secondary detail |

Long values truncate in tables but remain available in the detail drawer. Vertical overflow scrolls; information is not silently removed. Textual supports screen/container layouts and scrolling, while Rich renderables can be embedded inside Textual content: [Textual layout](https://textual.textualize.io/guide/layout/), [Rich renderables in Textual](https://textual.textualize.io/guide/content/).

## 16. Visual Language

- Default density is compact: one-row facts, narrow separators and no decorative empty panels.
- Cyan/blue identifies active information, green success, yellow warning/waiting, red failure, and muted text unavailable/pending.
- Status always includes a word or glyph; color is supplementary.
- Animations are limited to active indeterminate work and do not run after terminal state.
- Tables are preferred for repeated exact mappings; prose panels are used only for warnings and explanations.
- Emojis are optional theme assets, never the sole semantic indicator.

## 17. Acceptance Tests

### Progress and time

- an operation still active at five seconds appears in Long-running operations;
- initialization, warm-up, read, execution, validation and persistence spans can all appear;
- current file, current stage, file elapsed and stage elapsed update from canonical events;
- indeterminate work never receives a fabricated percentage or ETA;
- every input file receives a terminal status and measured time when available;
- success, partial, failure, cancellation and quarantine all open Run Summary;
- parallel span totals are not mislabeled as wall-clock run time.
- active OCR workers/pages update independently by stable page/attempt identity;
- final GPU/NPU/CPU counts and timing aggregates reconcile with recorded page
  attempts without being labelled as parallel wall time;
- a silent long-running worker shows its last factual activity and waiting
  state without Mukha declaring failure.

### Data integrity

- missing metrics render as unavailable;
- confidence requires method/evidence provenance;
- accuracy is unavailable without verified truth;
- no production screen contains sample/default runtime rows;
- Mukha does not import Darpana exporter, database, recorder buffer, profiler global, Yantra internals or capability implementation modules;
- review approval does not auto-write Anubhava TOML.
- historical OCR averages require comparable filters, sample count and
  last-tested date; absent evidence renders `Not benchmarked`;
- confidence is never relabelled as accuracy, and verified accuracy identifies
  its metric, reference and sample count;
- Bank Statement Consolidation renders no profile selector;
- Instant, Accurate and Layout Preserving retain their tested fixed engine
  bindings; only Custom exposes compatible engine/profile selection.

### Interaction

- keyboard-only navigation reaches every action;
- narrow, normal and wide terminal layouts remain usable;
- cancellation and retry requests travel through canonical owners;
- log filtering does not mutate persisted telemetry;
- leaving a screen does not alter execution state;
- stale or out-of-order events cannot regress a terminal file/run state.
- native multi-file, folder and pasted-path inputs normalize and deduplicate
  into the same canonical request selection;
- more than ten inputs/results collapse into a grouped default view while the
  complete searchable table remains reachable;
- an action removed after screen render is rejected on runtime revalidation and
  the available-action snapshot refreshes;
- persisted terminal summaries reopen from Recent Runs without a separate
  report store.

### Visual regression

- headless interaction tests cover screen navigation and state changes;
- snapshot tests cover startup >5s, active multi-file run, indeterminate stage, partial summary, review item, failure and narrow terminal layout;
- tests use typed fixtures explicitly marked as test data—never production fallback values.

Textual officially supports headless `run_test`/Pilot testing and SVG snapshot testing, making both interaction and layout regressions testable: [Textual testing guide](https://textual.textualize.io/guide/testing/).

## 18. Minimal Physical Ownership

This is a responsibility map, not an instruction to create every file immediately.

``` text
mukha/
├── app.py            # one Textual application and navigation
├── state.py          # typed presentation projections
├── presenter.py      # canonical event → presentation state
├── screens.py        # five screens; split only when this file becomes crowded
├── components.py     # shared progress, file table, timeline and summary widgets
└── theme.tcss        # visual styling and adaptive layout
```

Screen TOML is not initially required. Add it only if static labels/default visibility/theme configuration demonstrates value. No YAML/TOML behavior language is introduced.

## 19. Final Screen Set

| Key | Sanskrit name + English functional name | Availability |
|---|---|---|
| F1 | **Griha — Home & Run Setup** | always |
| F2 | **Pravritti — Live Run Monitor** | active or recently terminal run |
| F3 | **Pariksha — Review & Exceptions** | only when review items exist |
| F4 | **Samapti — Run Summary** | after every terminal run |
| F5 | **Nirikshana — Run Inspector** | when telemetry/state is available |

Temporary surfaces: **Aarambha — Startup Progress**, command palette, detail drawers, cancellation/failure modal and contextual help.

This five-screen structure preserves V1's useful visibility while eliminating its parallel console generations, capability-specific presentation duplication, fake data and direct telemetry coupling.
