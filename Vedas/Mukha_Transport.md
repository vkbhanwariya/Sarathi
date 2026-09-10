# Mukha Local Web Transport

Mukha exposes Sarathi through a local-only ASGI application.

```text
Browser
  |
  v
TypeScript/Preact UI and current static assets
  |
  v
Starlette routes, middleware, responses, SSE
  |
  v
Mukha presentation state + RunCoordinator
  |
  v
Sarathi runtime
```

Uvicorn owns ASGI serving and binds to `127.0.0.1`. Starlette owns HTTP routing, JSON/file responses, middleware, and SSE streaming. Mukha translates transport payloads to/from runtime operations; it does not own planning, capability execution, device policy, or document-processing decisions.

## Security

Loopback binding, Host/Origin validation, content security policy, frame restrictions, `nosniff`, cache policy, public-error sanitization, and path-containment checks are part of the web boundary. HTTP header names are treated case-insensitively.

Artifact downloads and previews must resolve through confirmed run/artifact/input identity and authorized paths. Cross-run or unknown identifiers return an error rather than exposing an arbitrary filesystem path.

## State and events

`/api/state` projects current application state. `/api/events` uses server-sent events for state updates. SSE is the current transport; a different realtime mechanism is justified only by measured product need.

## Server façade

`MukhaWebServer` owns lifecycle/facade behavior such as start, stop, resolved port, and the canonical loopback `local_url`. Run execution and run-owned mutable state belong to `RunCoordinator`/runner code rather than private HTTP-handler compatibility properties.
