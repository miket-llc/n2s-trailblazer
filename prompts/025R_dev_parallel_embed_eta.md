# Shared Guardrails (VERBATIM - DO NOT MODIFY)
# Branching: No feature branches. Work directly on main.
# Linting: All code must pass make fmt && make lint && make test && make check-md
# Markdown hygiene: All .md files must pass make check-md
# Secrets: Never commit secrets. Use .env files and environment variables.
# Prompt size: Keep prompts focused and actionable.
# Proof-of-work: Always provide concrete evidence of completion.
# Console UX: Use clear, informative output with progress indicators.
# Database: Use Postgres + pgvector only. No SQLite in runtime/ops.

# PROMPT DEV-025R — Parallel Embed ETA: Worker-Aware Monitor (+ safe defaults)

# Guardrails Addendum (append before you start)
One DB only: Postgres + pgvector (NO SQLite anywhere in runtime/ops).

No pagers: export PAGER=cat, export LESS=-RFX; pass pager-off flags (e.g., psql -P pager=off).

DB-free: Ingest/Normalize/Enrich are DB-free. Only embed/retrieval touch Postgres.

Observability: Pretty progress → stderr; NDJSON events → stdout (we redirect).

Be surgical: Read code first; refactor only if it reduces risk; zero test failures before push.

Context for a New Instance
We already added parallel embedding across runs (scripts/embed_dispatch.sh) and a monitor (scripts/monitor_embedding.sh). Now we'll make the monitor calculate a correct ETA that accounts for the number of workers running, and we'll store enough plan metadata so ETA is stable. We will also set WORKERS=2 as the safe default (good balance vs rate limits). Workspace is var/ only.

To-Dos (≤9)
1) Baseline (must be green) & paths
2) Re-embed script: write a plan into progress (docs_planned/run)
3) Re-embed script: ensure docs_embedded always increments (even 0)
4) Dispatcher: set a safe default worker count and pass through env
5) Monitor: worker-aware ETA (use plan + live PIDs + EWMA rate)
6) Default WORKERS=2 in docs & Makefile
7) Tests & shellcheck (keep green)
8) Docs
9) Commit & push

[Full implementation details preserved from original prompt]
