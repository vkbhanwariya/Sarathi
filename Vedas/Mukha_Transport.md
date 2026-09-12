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

- **Loopback Enforcement**: The web server binds exclusively to `127.0.0.1`. Inbound requests with non-loopback Host or Origin headers are rejected with `403 Forbidden`.
- **Response Headers**: Enforces Content Security Policy (`CSP`), `X-Content-Type-Options: nosniff`, frame restrictions (`DENY`), and strict caching policies on API routes. Header names are evaluated case-insensitively.
- **Filesystem Containment**: Download and preview endpoints (`/api/inputs/<id>/preview`, `/api/artifacts/<run_id>/<filename>`) resolve only through verified run workspaces. Arbitrary filesystem path traversal is blocked fail-closed.

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

The production Preact frontend (`ui/src/App.tsx`) is structured into 5 dedicated screens:

### Screen 1: Home (`home`)
- **Run Setup**: Ingests document inputs via native file/folder picker, drag-and-drop, or path entry.
- **Requirement & Action Selection**: Dynamically renders available capabilities based on runtime readiness and Kavacha security policy.
- **Profile Selector**: Selects execution profile (`INSTANT`, `ACCURATE`, `CUSTOM`).
- **Plan Preview**: Invokes `/api/plan/preview` to display planned stages and assigned execution devices before launching.

### Screen 2: Monitor (`monitor`)
- **Live Execution Tracking**: Subscribes to `/api/events` SSE stream for low-latency progress updates.
- **Active Context**: Displays currently executing file, active stage, and assigned worker device (`CPU`, `GPU`, `NPU`).
- **Time Semantics**: Continuously renders elapsed file time, stage time, and overall run duration.
- **Cooperative Cancellation**: Provides an immediate cancel button triggering `/api/runs/<id>/cancel`.

### Screen 3: Review (`review`)
- **Human-in-the-Loop Review Queue**: Gathers extraction exceptions, ambiguous bank transactions, and low-confidence OCR spans.
- **Visual Inspection**: Renders original image region crops side-by-side with candidate text and confidence metrics.
- **Correction Submission**: Accepts operator corrections and commits updated records back to the result model.

### Screen 4: Summary (`summary`)
- **Terminal Run Overview**: Displays terminal execution outcome (`SUCCESS`, `PARTIAL`, `FAILURE`, `CANCELLED`).
- **Committed Artifacts**: Lists verified output files with format badges, file sizes, and download links.
- **Explorer Integration**: "Reveal in Explorer" button opens the local output directory via native desktop hooks.
- **Validation Warnings**: Surfaces non-fatal warnings (e.g. balance reconciliation discrepancies, font ambiguation).

### Screen 5: Inspector (`inspector`)
- **Deep Telemetry Breakdown**: Detailed timeline of all nested Maruti operational timing spans.
- **Quality Observations**: Full listing of page-level and region-level Pramana confidence records and evidence.
- **Hardware Allocation Facts**: Factual reporting of accelerator devices used during the run.

---

## 5. The 5-Second Progress Visibility Rule

Any operation that remains active for more than 5 seconds must expose visible progress to the user. The SSE stream emits periodic progress ticks containing current item index, total items, stage name, and elapsed duration, ensuring the UI remains responsive and transparent during long OCR or translation workloads.
