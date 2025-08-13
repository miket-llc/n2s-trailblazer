# Trailblazer Mindfile — 2025-08-13 13:08 (EDT)

## One-liner

Trailblazer is our AI-powered knowledge base builder: it ingests Navigate-to-SaaS and Ellucian documentation (Confluence + official docs), organizes everything into a typed graph with embeddings, and makes it easy to query and generate the docs we need.

## 0) Working agreements (read first)

**Main branch only.** No feature branches for routine work; commit atomically to main.

**Venv + toolchain required.** Always:

```bash
make setup        # creates .venv, installs dev deps, installs pre-commit
make fmt          # ruff --fix + black
make lint         # ruff check + mypy
make test         # pytest -q
```

Never hand-fix lint/format; use the tools. Only commit if all are green.

**Prompts:** Save each prompt under `prompts/` and include a short "proof-of-work" (last ~10 lines) from the Make targets in the model's reply.

**Cursor to-do limit:** Keep prompts to ≤ 9 checklist items. Chunk large work into 004A, 004B, etc.

**Secrets:** No real credentials in code, prompts, or examples. Use placeholders; real values only in local `.env`/CI secrets.

**Artifacts are immutable.** Every run writes under `runs/<run_id>/<phase>/…`; never mutate prior runs.

## 1) Mission & scope (v0)

**Mission.** Build an AI knowledge base that unifies Navigate-to-SaaS and Ellucian documentation, models it as a graph with embeddings, and supports fast retrieval plus on-demand document generation.

**Scope (v0).**

- **Sources:** Confluence Cloud (ellucian.atlassian.net/wiki) + (soon) Ellucian Documentation site.
- **Pipeline:** ingest → normalize (Storage & ADF) → enrich/classify → embed → retrieve → compose/create → audit.
- **Storage:** file artifacts under `runs/…`; Postgres + pgvector for embeddings (planned).
- **Interfaces:** CLI-first (`trailblazer …`); server optional later.

**Non-goals (v0).** Upstream editing, real-time streaming, replacing Confluence as primary authoring.

## 2) Architecture at a glance

- **CLI:** Typer app: `trailblazer` with subcommands (ingest, normalize, etc.).
- **Adapters:** `adapters/confluence_api.py` uses Confluence Cloud v2 with Basic auth (email + API token); v1 CQL only for delta prefiltering.
- **Models:** `Page`, `Attachment` for ingest contract; normalized records add `text_md`, `links`.
- **Phases:** Each phase has a function that writes NDJSON and `metrics.json`/`manifest.json`.
- **Logging:** Structured (JSON) to stdout; per-phase metrics for counting and timing.

## 3) Data sources & auth

**Confluence Cloud v2** (`/wiki/api/v2`) for spaces/pages/attachments.

**Basic auth:** `CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN` (store only in `.env` or CI).

**Delta (`--since`):** enumerate candidate IDs via v1 CQL, then fetch full bodies via v2.

**Body formats:**
- `storage` → Confluence Storage Format (XHTML-ish).
- `atlas_doc_format` → ADF JSON.

Ingest records should include `body_repr = storage|adf` plus `body_storage` (string) or `body_adf` (JSON).

## 4) Contracts & artifacts

### Ingest output (`runs/<run_id>/ingest/`)

**`confluence.ndjson`:** one Page per line, including:
- `id`, `title`, `space_key`, `space_id`, `version`, `created_at`, `updated_at`, `url`
- `attachments[]` (`id`, `filename`, `media_type`, `file_size`, `download_url`)
- **Body:** `body_repr` + `body_storage` or `body_adf` (keep `body_html` if already emitted)
- `metrics.json`, `manifest.json`

### Normalize output (`runs/<run_id>/normalize/`)

**`normalized.ndjson`:** per page, include `text_md` (deterministic), `links[]`, `attachments[]`, `body_repr`
- `metrics.json`, `manifest.json`

**Rule of thumb:** deterministic transforms (same input → same output). Never overwrite previous runs.

## 5) Tooling & repo hygiene

- **Pre-commit:** ruff, black, mypy; install via `make setup`.
- **`.gitignore` must include:** `data/`, `runs/`, `.venv/`, `.env`, `__pycache__/`, `.pytest_cache/`.
- **Makefile is the interface** for dev tasks; don't bypass it.
- **Conventional commits:** `feat(normalize): …`, `fix(ingest): …`, etc.

## 6) Current state (today)

- **Ingest (Confluence):** implemented with v2 bodies/attachments, optional v1 CQL deltas; CLI `trailblazer ingest confluence …`; writes NDJSON + metrics + manifest.
- **Normalize:** implemented to support both Storage (XHTML) and ADF JSON → Markdown, plus links/attachments.
- **Tests:** smoke tests for ingest & pagination; normalization tests implemented.
- **Docs:** README covers venv, Make targets, ingest usage, and normalize usage.

## 7) Next milestones (chunked; each ≤ 9 to-dos prompt)

### ~~004A — Normalize (Storage & ADF → Markdown)~~ ✅ COMPLETED

- ~~Implement `normalize_from_ingest` handling both storage and adf.~~
- ~~Add CLI `trailblazer normalize from-ingest`.~~
- ~~Tests: storage path, ADF path, whitespace determinism.~~
- ~~Docs: README section "Normalize (Storage & ADF → Markdown)".~~

### 005 — Embed & graph (initial)

- Chunker → passages; embed with chosen model; write to Postgres/pgvector.
- Minimal graph tables (nodes, edges, chunks, chunk_embeddings).
- Loader from normalized NDJSON → DB; tests for idempotency.

### 006 — Ask/Generate (MVP)

- `trailblazer ask "<question>"` → retrieval over vectors + (optionally) graph expansion.
- First generator template (e.g., Implementation Checklist) with budgeted compose.

*(If a milestone needs more than 9 actionable to-dos, split into 005A/005B, etc.)*

## 8) Quality & audit

- **Coverage:** % of expected documents normalized/embedded per run.
- **Quality:** normalization lint (e.g., empty bodies, excessive whitespace, missing titles).
- **Drift:** compare current metrics vs previous runs.

## 9) Risk & mitigation

- **Secrets exposure:** enforce pre-commit secret scanning (e.g., gitleaks); placeholders in examples.
- **Rate limits/timeouts:** exponential backoff (tenacity) around external I/O; per-item fail-soft logging.
- **Format drift:** Confluence format changes—keep both Storage & ADF paths healthy; favor v2 for bodies.

## 10) Quickstart

```bash
# 1) Setup
make setup

# 2) Format, lint, test
make fmt && make lint && make test

# 3) Ingest (small test; requires .env with Confluence email + API token)
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --max-pages 10

# 4) Normalize from that run
trailblazer normalize from-ingest --run-id <RUN_ID>
```

**`.env` keys (placeholders only):**

```ini
CONFLUENCE_BASE_URL=https://ellucian.atlassian.net/wiki
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=*** place token in local .env only ***
CONFLUENCE_BODY_FORMAT=storage   # or atlas_doc_format
```

## 11) Decision log (concise ADRs)

- **ADR-001:** CLI-first, Python monorepo; phases are nouns (no numeric module names).
- **ADR-002:** Confluence Cloud v2 for pages/attachments; Basic auth; v1 CQL only for deltas.
- **ADR-003:** Ingest artifact is NDJSON with embedded attachments; immutable per run.
- **ADR-004:** Normalize supports Storage & ADF; output is deterministic Markdown + links/attachments.
- **ADR-005:** Pre-commit + Makefile are mandatory; main-only workflow.

---

**Keep this mindfile authoritative.** When architecture/contracts change, update here first, then prompts, then code.
