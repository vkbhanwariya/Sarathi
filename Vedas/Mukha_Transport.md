# Mukha Local Web Transport & UI Screen Architecture

Mukha exposes Sarathi through a local-only ASGI application backed by Uvicorn, Starlette, and a production Preact/TypeScript single-page application.

---

## 1. Transport Flow

```text
Browser (Preact/TypeScript SPA)
         |
         v
Starlette Routes, Middleware, Responses & SSE
         |
         v
Mukha Presentation State + RunCoordinator
         |
         v
Sarathi Runtime (Agni / Manthan / Pravaha)
```

- **Uvicorn** owns ASGI serving, strictly bound to loopback (`127.0.0.1`).
- **Starlette** owns HTTP routing, JSON and file streaming responses, security middleware, and Server-Sent Events (SSE).
- **Mukha** translates HTTP/SSE transport payloads to and from canonical runtime operations; it does not own planning, capability execution, device policy, or document processing decisions.

---

## 2. Security & Boundaries

- **Session Token Authentication**: At server bootstrap, a 256-bit cryptographically secure session token is generated (`secrets.token_urlsafe(32)`). The initial browser shell URL launched via desktop integration contains `/?t=<token>`. Accessing this sets an `HttpOnly; SameSite=Strict; Path=/` session cookie and redirects to `/`. All `/api/**` endpoints strictly validate this cookie using constant-time comparison (`hmac.compare_digest`), rejecting unauthenticated requests with `401 Unauthorized` or `403 Forbidden`.
- **Loopback Enforcement**: The web server binds exclusively to `127.0.0.1`. Inbound requests with non-loopback Host or Origin headers are rejected with `403 Forbidden`.
- **Response Headers**: Enforces Content Security Policy (`CSP`), `X-Content-Type-Options: nosniff`, frame restrictions (`DENY`), and strict caching policies on API routes. Header names are evaluated case-insensitively.
- **Filesystem Containment & Preview Security**: Download and preview endpoints (`/api/inputs/<id>/preview`, `/api/preview/*`, `/api/artifacts/<run_id>/<filename>`) resolve strictly through Kavacha's path containment service. Paths must reside within configured storage roots (`input_root`, `output_root`, `runtime_root`) or registered intake directories. Symlink escapes pointing outside allowed roots are rejected fail-closed.
- **Run-Level Warning Aggregation**: Non-fatal system warnings lacking an explicit `input_id` association are accounted strictly at the run level, preventing duplicate warning inflation across multiple input items.

---

## 3. Protocol Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/` | `GET` | Serves the production Preact SPA shell (`index.html`). |
| `/ui/*` | `GET` | Serves compiled static assets (`app.js`, `app.css`). |
| `/api/state` | `GET` | Returns the full typed `ApplicationViewState` JSON snapshot. |
| `/api/events` | `GET` | Server-Sent Events (SSE) text stream for real-time reactive UI updates. |
| `/api/runs` | `POST` | Dispatches a new pipeline run with validated inputs, profile, and requirements. |
| `/api/runs/<id>/cancel` | `POST` | Requests cooperative cancellation of an active run via `CancellationToken`. |
| `/api/plan/preview` | `POST` | Previews planned execution stages and hardware devices before run execution. |
| `/api/browse/files` | `POST` | Opens controlled native OS file picker dialog (`native_picker.py`). |
| `/api/browse/folder` | `POST` | Opens controlled native OS folder picker dialog (`native_picker.py`). |
| `/api/intake` | `POST` | Ingests and inspects input paths, verifies boundary security, and stages intake items. |
| `/api/inputs/<id>/preview` | `GET` | Delivers rendered preview stream for an input document. |
| `/api/runs/<id>/reveal` | `POST` | Opens the run's committed artifact directory in the native file explorer. |
| `/api/review/submit` | `POST` | Submits human corrections for review queue items. |

---

## 4. UI Screen Architecture

The production Preact frontend (`ui/src/App.tsx`) is structured into 5 dedicated primary screens:

### Screen 1: Home (`home`)
- **Run Setup**: Ingests document inputs via native file/folder picker, drag-and-drop, or path entry.
- **Requirement & Action Selection**: Dynamically renders available capabilities based on runtime readiness and Kavacha security policy.
- **Profile Selector**: Selects execution profile (`INSTANT`, `ACCURATE`, `LAYOUT_PRESERVING`, `CUSTOM`).
- **Plan Preview**: Invokes `/api/plan/preview` to display planned stages and assigned execution devices before launching.

### Screen 2: Monitor (`monitor`)
- **Live Execution Tracking**: Subscribes to `/api/events` SSE stream for low-latency progress updates, active worker concurrency, elapsed timings, and pipeline document progress.
- **Active Context**: Displays currently executing file, active stage, and assigned hardware accelerator (`CPU`, `GPU`, `NPU`).
- **Cooperative Cancellation**: Provides an immediate cancel button triggering `/api/runs/<id>/cancel` with cooperative stage draining.
- **Automatic Summary Morphing**: Upon terminal task completion (`SUCCESS`, `COMPLETED`, `FAILED`, `CANCELLED`, `WARNING`, `PARTIAL`), Monitor automatically morphs in-place into the full **Summary View**, displaying confirmed output deliverables with 1-click preview and download, hardware/stage timings, metrics, and explorer folder reveal.
- **Bi-directional Navigation**: Allows manual toggle between live pipeline telemetry and run summary via the `⚡ Live Pipeline` action.

### Screen 3: Review (`review`)
- **Human-in-the-Loop Review Queue**: Gathers extraction exceptions, ambiguous bank transactions, and low-confidence OCR spans.
- **Visual Inspection**: Renders original image region crops side-by-side with candidate text and confidence metrics.
- **Correction Submission**: Accepts operator corrections and commits updated records back to the result model.

### Screen 4: History (`history`)
- **Audit & Execution Ledger**: Dedicated chronological log of all historical document processing runs reconstructed from Darpana.
- **KPI Metrics Strip**: At-a-glance summary cards showing Total Runs, Success Rate %, Deliverables Produced, and Total Execution Duration.
- **Search & Filter Controls**: Instant client-side search by run ID, workflow, or profile, with status pills (`All`, `Completed`, `Failed`, `Cancelled`).
- **Actionable Run Cards**: Immediate 1-click actions to view complete summary in Monitor (`📊 View Summary`), inspect diagnostics (`🔍 Inspect`), or reveal outputs in Windows File Explorer (`📁 Open Folder`).

### Screen 5: Inspector (`inspector`)
- **Deep Telemetry Breakdown**: Detailed timeline of all nested Maruti operational timing spans.
- **Quality Observations**: Graphical confidence distribution bar charts and full listing of page/region confidence records.
- **Activity Logs**: Color-coded log severity chips (`INFO`, `WARNING`, `ERROR`) with monospace timestamps and copy diagnostics action.
- **Hardware Allocation Facts**: Factual reporting of accelerator devices used during the run (Intel Core Ultra 5 125H & Arc iGPU OpenVINO FP16).

---

## 5. The 5-Second Progress Visibility Rule

Any operation that remains active for more than 5 seconds must expose visible progress to the user. The SSE stream emits periodic progress ticks containing current item index, total items, stage name, and elapsed duration, ensuring the UI remains responsive and transparent during long OCR or translation workloads.
