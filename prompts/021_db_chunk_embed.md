# Shared Guardrails

PREAMBLE — Shared Guardrails (paste at the top of every prompt)
Save once as prompts/000_shared_guardrails.md and also paste at the top when
you run this prompt.

**Trailblazer Prompt Guardrails (read first)**

**Main only.** Do all work on main. No feature branches/PRs for routine work.

**Zero IDE linter errors across all file types.** If an IDE warns and our tools don't, update tool configs so the warning disappears permanently (don't hand-tweak files ad-hoc).

**Automate fixes first.** Always use the toolchain; never hand-fix format/lint.

```bash
make setup     # venv + dev deps + pre-commit
make fmt       # ruff --fix, black, mdformat for .md
make lint      # ruff check, mypy, markdownlint
make test      # pytest -q
```

**Markdown hygiene:** all .md must pass mdformat and markdownlint (e.g., fixes MD032 blanks-around-lists via formatter).

**Secrets hygiene:** placeholders only in repo/prompts; real values only in .env/CI. Secret scanning (e.g., gitleaks) is required in pre-commit.

**Pre-push gate:** tests must pass before pushing to main. Add/keep a pre-push pytest hook.

**Prompt size rule:** keep checklists to ≤9 to-dos (Cursor limit). Split into 004A/004B, etc., when needed.

**Proof-of-work:** in every prompt response, paste the exact commands run and the last ~10 lines of output for make fmt, make lint, and make test.

**Non-regression:** Never relax guardrails or remove stricter lint rules without explicit approval. Future prompts must start by pasting this file unchanged.

Confluence: Cloud v2 + Basic auth. Use v1 CQL only to prefilter when --since is set. Bodies/attachments fetched via v2.

Artifacts immutable: write to var/runs/run-id/phase/…; never mutate previous runs.

## Console UX Policy

Default to pretty, human-readable progress when attached to a TTY; default to JSON only in CI or when stdout is redirected.

Never intermix pretty output and JSON on the same stream. JSON → stdout; pretty/status/progress → stderr.

Always print the run_id at start/end of every command and write a final one-line summary.

Throttle progress updates; no more than 1 line per --progress-every N pages.

Keep the structured event names stable: confluence.space, confluence.page, confluence.attachments.

## Database Non-Negotiables (Global)

- Ingest is DB-free: importing or running any ingest CLI/step MUST NOT connect to, import, or initialize the DB.
- Postgres-first for runtime: Any command that persists or queries embeddings (e.g., `embed load`, `ask`, future retrieval services) MUST require Postgres + pgvector in non-test environments. SQLite is allowed ONLY for unit tests/CI and must be explicitly opted-in.
- Single source of truth: DB_URL MUST be provided in `.env` and used by a single engine factory. No hardcoded defaults that silently fall back to SQLite in dev/prod.
- Preflight required: `trailblazer db check` MUST pass (connectivity + pgvector present) before `embed load` or `ask` run (unless tests explicitly opt-in to SQLite).
- Secrets hygiene: Never print DB credentials in logs; log the host/database name only.

## DB policy

PostgreSQL + pgvector is the required default for any embed/retrieve/ask.

SQLite is tests-only (unit/integration) and must be explicit in tests.

Ingest/normalize must not require a DB.

No silent fallback to SQLite in runtime code paths. Fail fast with an actionable message if Postgres isn't configured.

Provide a single place to diagnose: trailblazer db doctor.

## Additional Global Rules

**Tests:** No merges to main with any failing tests. If tests fail, fix tests or the code; do not comment out or delete tests unless replaced by better coverage in the same PR.

**DB policy:** Ingest & normalize must not require a DB. Postgres/pgvector is only for retrieval/indexing phases; CLI preflights for DB must not gate ingest/normalize.

**Body format:** Confluence default body_format is atlas_doc_format (ADF). Storage/XHTML handling stays for backward compatibility and normalization.

**Traceability:** Always persist id, url, space_id/key/name (if available), version, created_at, updated_at, labels, ancestors/breadcrumbs, attachments (with filenames + download URLs), links, and content_sha256 throughout ingest → normalize.

**Observability:** All long-running CLIs must stream clean, structured progress (banners, per-phase counters, ETA) and print the run_id at completion.

**Cursor limit:** Keep prompts ≤10 to-dos; chunk work if needed.

**No regression:** Before edits, read the module and associated tests; prefer minimal deltas. If complexity is high, refactor in tiny steps with passing tests after each step.

## Non-Negotiable: Observability & Assurance

**Rich Console Progress:** All ingest commands MUST provide Rich-formatted progress with overall/per-space bars, heartbeats every 30s, and colored status indicators. Use `--no-color` to disable.

**Structured Event Logging:** Every ingest run MUST emit structured NDJSON events to `var/logs/<run_id>.ndjson` including: space.begin/end, page.fetch/write, attachment.fetch/write, heartbeat, warning, error with full traceability keys (source, space_key, space_id, page_id, title, version, url, attachment_id, sha256, bytes).

**Assurance Reports:** Every ingest MUST generate `assurance.json` and `assurance.md` with totals, per-space stats, zero-body pages, non-ADF bodies, missing/failed attachments, top 10 largest items, retry stats, error summaries, and reproduction command.

**Attachment Verification:** For every page with attachments, verify count written == count reported; retry with exponential backoff on mismatch; surface red counter in progress panel.

**Resumability Evidence:** When using `--since` or `--auto-since`, display what will happen: pages_known, estimated_to_fetch, skipped_unchanged counts with reasons (updated, deleted, moved).

**Zero Test Failures:** All observability features MUST have offline smoke tests that verify progress/heartbeat output, NDJSON event structure, and assurance report generation without network calls.

**No DB in Ingest:** Event logging and assurance generation MUST NOT require database connectivity - all observability is file-based under var/.

# PROMPT DEV-021 — Postgres Schema + Chunker + Embedding Loader (Idempotent, Media-Aware)

Save as: prompts/021_db_chunk_embed.md
Branch: main
PASTE prompts/000_shared_guardrails.md VERBATIM ABOVE THIS PROMPT. DO NOT MODIFY IT.

## Context for a New Instance (read me first)

Trailblazer: our AI-powered knowledge base builder. It ingests Confluence (Cloud v2) and Oxygen/DITA, normalizes both to Markdown + traceable JSON, then embeds into Postgres + pgvector for retrieval.

What's already done: full Confluence+DITA ingest and normalize finished. Artifacts live under var/ only:

Raw ingest per run: var/runs/<RID>/ingest/… (e.g., confluence.ndjson, dita.ndjson, links.jsonl, edges.jsonl, attachments_manifest.jsonl, summary.json).

Normalized: var/runs/<RID>/normalize/normalized.ndjson (keeps url, links, attachments, labels, breadcrumbs, etc.).

Hard rules:

Ingest/normalize are DB-free. Only this prompt (embedding) uses Postgres.

Workspace is var/ only (no legacy ./runs|state|logs).

Confluence must be ADF (atlas_doc_format) before normalization (already enforced upstream).

Observability: human-readable progress → stderr; NDJSON events → stdout → files; assurance reports emitted at end.

Zero test failures / zero IDE linter errors before pushing.

Expected CLI already present (if anything missing, stop and patch first):

trailblazer paths [ensure|doctor|--json]

trailblazer db [check|init] (Postgres + pgvector)

trailblazer embed load --run-id <RID> [--provider dummy] [--batch N] (we will (re)implement/fortify this)

Goal (this prompt): finalize DB schema, chunker (media-aware), and embedding loader with idempotency & assurance (Postgres-first; dummy provider for tests).

## To-Dos (≤ 9)

### 1. DB schema (SQLAlchemy)

Create/confirm tables + indexes:

documents(doc_id PK, source_system, title, space_key, url, created_at, updated_at, content_sha256 UNIQUE, meta JSONB)

chunks(chunk_id PK, doc_id FK, ord INT, text_md TEXT, char_count INT, token_count INT, meta JSONB, UNIQUE(doc_id,ord))

chunk_embeddings(chunk_id PK FK, provider, dim INT, embedding VECTOR, created_at TIMESTAMP, UNIQUE(chunk_id,provider))

trailblazer db check/init must verify pgvector is installed; fail with a clear message if not.

### 2. Chunker (deterministic, media-aware)

Input: one normalized record (text_md, links, attachments, labels, …).

Rules: normalize CRLF→LF; chunk by semantic blocks (title/para/list/code), target ~800–1200 chars, ~15% overlap, never split inside fenced code.

Media placeholders: when media markers are present, inject !\[media: <filename>\] to make media chunk-addressable.

Output: chunk_id = f"{doc_id}:{ord:04d}", plus char_count, token_count (cheap approx OK), stable across runs.

### 3. Embed providers (pluggable)

DummyEmbedder(dim=384): deterministic hash→vector; no network (tests/CI default).

Optional provider stubs (OpenAI/SentenceTransformers) behind env flags; not used in tests.

### 4. Embedding loader (idempotent)

CLI: trailblazer embed load --run-id <RID> [--provider dummy] [--batch 256] [--max-docs N] [--max-chunks N].

Flow: read var/runs/<RID>/normalize/normalized.ndjson → upsert documents by doc_id/content_sha256 → chunk → upsert chunks by (doc_id, ord) → embed → upsert chunk_embeddings by (chunk_id, provider).

Skip unchanged docs/chunks via content_sha256; track skipped vs inserted.

### 5. Assurance report

Write var/runs/<RID>/embed_assurance.json and .md with: {docs_total, docs_skipped, docs_embedded, chunks_total, chunks_skipped, chunks_embedded, provider, dim, duration, errors[]}.

Print one-line summary at end.

### 6. Observability

Progress every N batches: [EMBED] docs=… chunks=… rate=…/s elapsed=… eta=… skipped=….

NDJSON events (doc.upsert, chunk.write, chunk.skip, embed.write, error) to stdout (we redirect to files).

### 7. Tests

Chunker determinism (IDs, overlap, no triple blanks, media placeholder present).

Dummy embedder stable outputs.

Loader idempotency (SQLite only with explicit test env flag) + upsert behavior.

Do not require a live Postgres in tests—mock engine; rely on db check in OPS prompts.

### 8. Docs

README "Embedding & Indexing": DB_URL, db check/init, running loader, assurance, idempotency via hashes.

### 9. Validation & commit

```bash
make fmt && make lint && make test && make check-md
```

Commit: feat(embed): Postgres schema + media-aware chunker + idempotent embedding loader + assurance

## Acceptance

Schema present; chunker outputs stable chunks; loader is idempotent; assurance emitted; tests green; ingest/normalize remain DB-free.
