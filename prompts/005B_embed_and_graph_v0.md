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

# PROMPT 005B — Embed & Graph v0 (Chunk → Embed → Load DB) ≤9 to-dos

Save as: prompts/005B_embed_and_graph_v0.md
Branch policy: MAIN ONLY (no feature branches)
Before you start: paste the entire prompts/000_shared_guardrails.md verbatim at the very top of this prompt. Do not modify the guardrails in this task.
Non-regression: Do not weaken any existing lint/CI/README/normalize work.

Goal
Add the first retrieval substrate: chunk normalized docs, generate embeddings via a pluggable provider, and load them into a minimal graph/DB. All tests must be offline (no network). Default provider must be dummy (deterministic, zero-network) for testability.

To-Dos (max 9)
DB layer & schema (Postgres+pgvector, with SQLite fallback).

Add src/trailblazer/db/engine.py (SQLAlchemy): read DB_URL (default: sqlite:///./.trailblazer.db).

Create tables (use SQLAlchemy models; avoid migrations for now):

documents(doc_id TEXT PK, source TEXT, title TEXT, space_key TEXT, url TEXT, created_at TIMESTAMP, updated_at TIMESTAMP, body_repr TEXT, meta JSON)

chunks(chunk_id TEXT PK, doc_id TEXT FK, ord INTEGER, text_md TEXT, char_count INTEGER, token_count INTEGER)

chunk_embeddings(chunk_id TEXT PK, provider TEXT, dim INTEGER, embedding VECTOR or JSON, created_at TIMESTAMP)

For Postgres: use pgvector (VECTOR type). For SQLite fallback: store embeddings as JSON; the app computes similarity in Python (not in SQL) when we add retrieval later.

Chunker (deterministic, offline).

Add src/trailblazer/pipeline/steps/embed/chunker.py:

Input: a single normalized record (text_md, title, id).

Strategy: paragraph/heading aware; target ~800–1200 chars per chunk with 15% overlap; never split inside fenced code blocks.

Output: ordered chunks with stable chunk_id = f"{doc_id}:{ord:04d}".

Count char_count and a simple token proxy (len(text.split())) to keep dependencies light.

Embedding providers (pluggable, default dummy).

Add src/trailblazer/pipeline/steps/embed/provider.py:

DummyEmbedder(dim=384): deterministic vector from SHA256(text) → float32 array in \[0,1). No network.

Optional providers (wired but not used in tests): OpenAIEmbedder (read OPENAI_API_KEY), SentenceTransformerEmbedder (local model name from env).

Provider selection via env/config: EMBED_PROVIDER in ["dummy", "openai", "sentencetransformers"]; default "dummy".

Loader: normalized → DB (idempotent).

Add src/trailblazer/pipeline/steps/embed/loader.py:

Read var/runs/\<RUN_ID>/normalize/normalized.ndjson.

For each document: upsert documents, chunk with chunker, upsert chunks, embed each chunk, upsert chunk_embeddings.

Idempotency: on conflict, skip or replace only if provider/dim change; log counts.

Batch size option (default 128) at the function level.

CLI commands.

Add trailblazer db init → create tables (safe if exists).

Add trailblazer embed load --run-id <RID> [--provider dummy] [--batch 128] [--max-docs N] [--max-chunks N].

Echo summary metrics (docs, chunks, embeddings written; provider; dim; db url).

Runner wiring (optional now, required later).

Accept embed as a phase: trailblazer run --phases normalize embed.

For now, phase embed locates the latest run id or requires --run-id if you've already standardized run passing.

Tests (offline; SQLite).

test_chunker_determinism.py: same input produces same chunk_id sequence; no triple blank lines inside chunks; overlap maintained.

test_dummy_embedder.py: stable vector values given fixed text; correct dim.

test_loader_sqlite.py: create temp DB_URL=sqlite:///<tmp>, run db init, feed two simple docs (via a tiny normalized.ndjson fixture), assert counts and idempotency (second run doesn't double rows).

Docs (README).

Add "Embed & Graph v0" section:

.env variables: DB_URL, EMBED_PROVIDER (default dummy), optional OPENAI_API_KEY, optional local sentence-transformers model.

Example commands:

bash
Copy
Edit
trailblazer db init
trailblazer embed load --run-id <RID> --provider dummy --batch 128
Note that tests and default provider are offline; Postgres+pgvector recommended for real retrieval scale.

Validation & commit.

Run: make fmt && make lint && make test && make check-md.

Paste proof-of-work (commands + last ~10 lines).

Commit to main with: feat(embed): chunker, pluggable embedding, db schema, loader, CLI; tests & docs.

Implementation Notes (keep concise; don't exceed scope)
SQLAlchemy models: prefer explicit table names; add composite indexes you deem useful (chunks(doc_id, ord)).

pgvector: only used at runtime when DB_URL is Postgres; tests stay on SQLite JSON column.

Determinism: chunker must not depend on locale or OS newlines; normalize CRLF→LF first.

Idempotency: use ON CONFLICT DO NOTHING / SQLAlchemy upsert patterns; tests assert stable row counts on repeated runs.

No network in tests: default provider is dummy and must not import network-only deps during import.

Security: never print env keys; .env.example remains placeholders only.

Acceptance Criteria
trailblazer db init creates the schema (no crash if rerun).

trailblazer embed load --run-id <RID> (with default dummy provider) loads documents, chunks, and embeddings; printed metrics show nonzero counts.

Running the loader twice does not duplicate rows (idempotency).

make fmt && make lint && make test && make check-md pass locally with zero IDE linter errors.

README documents DB setup, provider selection, and example commands.

Prompt saved as prompts/005B_embed_and_graph_v0.md.
