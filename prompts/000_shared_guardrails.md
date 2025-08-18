# Shared Guardrails

## Context (read once, then execute)

Trailblazer builds a bespoke knowledge base from Confluence and Oxygen/DITA; pipeline is Normalize → Enrich → Chunk → Embed into Postgres + pgvector for retrieval.

Embeddings: OpenAI text-embedding-3-small (1536 dims) for production.

Past incident: vectors were mistakenly stored as JSON; a new schema was created; vectors were converted and missing rows patched.

SQLite is removed. Postgres‑only in runtime; fail fast otherwise.

Golden Path & Config‑First: There's one primary orchestrator (e.g., trailblazer run) and a single config file (.trailblazer.yaml|yml|toml) that drives defaults. Keep flags minimal.

Current blocker: Embedding hit token limits—likely from Confluence pages with giant tables, code blocks, or macro bloat. DITA is usually fine; Confluence needs token‑budgeted, type‑aware chunking (code/table policies), plus junk filtration that keeps legit small pages.

Observability: Pretty status → stderr; typed NDJSON events → stdout; heartbeats, worker‑aware ETA, assurance reports, and sampling during long runs.

Prompts safety: Never delete non‑conforming prompts; archive only.

## Logging Non‑Negotiables (Standard Convention & Smart Management)

File naming (canonical): For each run, write NDJSON events to var/logs/\<run_id>/events.ndjson and pretty/TTY status to var/logs/\<run_id>/stderr.log. Maintain symlinks: var/logs/\<run_id>.ndjson → var/logs/\<run_id>/events.ndjson, and latest symlinks: var/logs/latest.ndjson, var/logs/latest.stderr.log. Each event line MUST include ts, run_id, phase, component, level, and worker_id (if any).

Streams rule: NDJSON → stdout only; pretty/status → stderr only. Never mix on the same stream.

Rotation: When events.ndjson exceeds logs.rotation_mb (default: 512 MiB), continue in events.ndjson.N (N=1,2,…) and update symlinks.

Compression: Compress segments older than logs.compress_after_days (default: 2) to .gz.

Retention: Prune logs older than logs.retention_days (default: 14) via trailblazer logs prune (dry‑run by default; requires --yes to delete). Never prune active runs.

Status JSON: Write an atomic snapshot to var/status/\<run_id>.json and update var/status/latest.json symlink on each heartbeat.

Reports: Assurance artifacts live in var/reports/\<run_id>/ and are never auto‑deleted.

## macOS Virtualenv Non‑Negotiable

On macOS (Darwin), all runtime commands must run inside a virtual environment. If not detected (VIRTUAL_ENV, Poetry/Conda, or sys.prefix != sys.base_prefix), fail fast with clear guidance: "Activate your venv: source .venv/bin/activate or run make setup."

CI/automation may bypass with TB_ALLOW_SYSTEM_PYTHON=1 only if explicitly set in CI config.

## Production Operations Non-Negotiables

### Database Safety

- **Postgres-only in ops**: Runtime must use `TRAILBLAZER_DB_URL=postgresql://…`. SQLite allowed **only** in unit tests behind `TB_TESTING=1`.
- **No destructive ops without backup**: Any task that *could* impact embeddings must refuse to run unless a **fresh backup** exists from today.
- **Embedding tables protected**: Never drop or clear `documents`, `chunks`, or `chunk_embeddings` tables.

### Script Safety

- **No pagers ever**: Export `PAGER=cat` and `LESS=-RFX` in all scripts and CLI entrypoints.
- **zsh-safe commands**: Prefer **single quotes** and heredocs; avoid smart quotes; show both bash/zsh forms when needed.
- **Zero IDE linter errors**: Use existing tooling first (`make fmt`, `make lint`, `make check-md`, `pre-commit`).

### Backup Requirements

- **Daily backups mandatory**: Run `scripts/backup_pg_embeddings.sh` before any destructive operations.
- **Backup verification**: Confirm backup contains `schema.sql`, `embeddings.dump`, and `manifest.json`.
- **Restore documentation**: Use `scripts/restore_pg_embeddings.sh` for emergency restore procedures.

### Embedding Operations

- **Preflight mandatory**: Run `trailblazer embed preflight --run <RID> --provider openai --model text-embedding-3-small --dimension 1536` before dispatch.
- **Tokenizer pinning**: Log tiktoken version in preflight; echo version in embedding operations for reproducibility.
- **Quality distribution gates**: Default thresholds `minQuality=0.60`, `maxBelowThresholdPct=0.20` (configurable via enrich command).
- **Provider/dimension sanity**: Use canonical SQL: `SELECT provider, dimension, COUNT(*) AS n FROM public.chunk_embeddings GROUP BY 1,2 ORDER BY 1,2;`
- **Operator proofs bundle**: Maintain preflight JSON, chunk assurance, embed assurance, monitor snapshot, provider/dimension SQL output.

### No Regressions

- **Read code before edits**: Be **surgical** unless a tiny refactor reduces risk.
- **Script/CLI alignment**: Scripts must use existing CLI options; no phantom flags.
- **Zero destructive changes**: Only add, never remove or modify existing functionality.
