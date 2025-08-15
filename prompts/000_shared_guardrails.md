# Shared Guardrails for N2S Trailblazer

## CLI Simplicity & Zero‑Scripts (Bespoke N2S)

**Zero‑scripts runtime**: No complex shell scripts for operations. Only minimal wrappers (≤20 LOC) that exec the CLI are allowed. Any script with loops/conditionals/pipes beyond trivial is disallowed in runtime.

**Config‑first, flags‑last**: The application must work with very few flags. Defaults come from a single config (.trailblazer.{yaml|yml|toml}) loaded automatically. Flags are for rare overrides.

**One Golden Path**: Provide one primary command to run the end‑to‑end N2S pipeline (install/configure/ingest→normalize→enrich→chunk→classify→embed→compose→playbook) with built‑in idempotence and a single reset switch (--reset) that safely reinitializes the selected scope (artifacts and/or DB facets) per config.

**Do not oversimplify**: Keep only what's needed to fulfill the N2S mission; remove unused flags/paths, but preserve necessary options (e.g., provider/model, safe concurrency).

**Postgres‑only**: No SQLite in runtime.

**Observability built‑in**: Pretty progress to stderr; typed NDJSON events to stdout; heartbeats; worker‑aware ETA; per‑phase assurance/quality gates; immutable artifacts under var/.

**CI enforcement**: Pre‑commit/CI must fail if non‑trivial scripts are introduced or if CLI exposes unsupported flag explosion.
