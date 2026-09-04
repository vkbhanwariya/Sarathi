# Security Policy for Sarathi V2

## Architectural Security Model

Sarathi V2 is designed as a local-first, privacy-preserving document intelligence runtime:

1. **Local-First & Offline Default**:
   - Sarathi processes documents locally without transmitting document contents, OCR text, or extracted financial data to third-party endpoints unless explicitly configured.
   - The Kavacha subsystem strictly regulates network policies. When network access is disallowed, outbound socket connections are blocked by policy.

2. **Web Interface Security (Mukha)**:
   - The Mukha HTTP server strictly parses and validates host addresses, binding by default to loopback interfaces (`127.0.0.1` or `::1`).
   - Standard security headers are enforced on all responses, including `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and strict referrer policies.

3. **Telemetry & Artifact Privacy (Darpana & Smriti)**:
   - Darpana telemetry records only structural metrics, execution durations, and outcome statuses. Document text and sensitive PII are never logged to telemetry buffers or serialized in trace events.
   - Smriti cache keys are derived from privacy-safe content fingerprints and length-delimited framed hashes without leaking local file paths or raw payload text.

## Reporting a Vulnerability

If you discover a security vulnerability in Sarathi, please report it responsibly:

- Do **not** open a public issue on GitHub.
- Submit a detailed report including reproduction steps, affected versions, and potential impact.
- Security reports will be acknowledged promptly and addressed in accordance with the project's maintenance lifecycle.
