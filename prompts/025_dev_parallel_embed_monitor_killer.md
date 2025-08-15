# Shared Guardrails (VERBATIM - DO NOT MODIFY)
# Branching: No feature branches. Work directly on main.
# Linting: All code must pass make fmt && make lint && make test && make check-md
# Markdown hygiene: All .md files must pass make check-md
# Secrets: Never commit secrets. Use .env files and environment variables.
# Prompt size: Keep prompts focused and actionable.
# Proof-of-work: Always provide concrete evidence of completion.
# Console UX: Use clear, informative output with progress indicators.
# Database: Use Postgres + pgvector only. No SQLite in runtime/ops.

# PROMPT DEV-025 — Parallel Embed (+ Monitor & Killer) with World-Class Safety

# Guardrails Addendum (append these lines to the shared guardrails before you begin)
Database Policy (Global): There is ONE runtime database: Postgres + pgvector. No SQLite anywhere in runtime/ops.

No pagers: Set PAGER=cat and LESS=-RFX in scripts & sessions; pass pager-off flags (psql -P pager=off) whenever applicable.

Ingest/Normalize/Enrich are DB-free. Only embed/retrieval touch Postgres.

Observability: Pretty progress → stderr; NDJSON events → stdout (we redirect to files).

Be surgical: Read code first; refactor only to reduce risk; zero test failures before pushing.

Context for a New Instance
We have scripts/reembed_corpus_openai.sh that re-embeds runs serially (one run at a time).

We want safe parallelism across runs (e.g., 2–4 workers), a monitor that summarizes progress/ETA and tails hot logs, and a killer to stop all in-flight embed jobs cleanly.

Workspace is var/ only.

To-Dos (≤9)
1) Read before changing (paste outputs)
2) Patch reembed_corpus_openai.sh to support single-run mode (for the dispatcher)
3) Add a dispatcher script to run N runs in parallel
4) Add a monitor script (no pagers) that prints status/ETA and tails hot logs
5) Add a killer script to stop all in-flight embed jobs
6) Create Makefile targets for pilot/all/monitor/kill
7) Tests & lint (must be green)
8) Docs (brief)
9) Commit & push

[Full implementation details preserved from original prompt]
