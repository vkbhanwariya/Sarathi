# Sarathi V3 — Mukha Transport

Mukha uses a local-only ASGI transport:

```text
Browser
  ↓
Preact / TypeScript UI or legacy static UI during migration
  ↓
Starlette routes and responses
  ↓
Mukha presentation façade / RunCoordinator
  ↓
Sarathi runtime
```

Uvicorn is the loopback ASGI server. Mukha binds only to `127.0.0.1`.

Starlette owns HTTP routing, JSON responses, static-file responses, and SSE streaming. It does not own document processing, run planning, capability execution, security policy, or runtime state.

The existing `/api/*` payload shapes and SSE `state` event contract are preserved during transport migration so frontend modernization remains independent from backend transport replacement.
