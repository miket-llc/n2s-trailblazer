# PROMPT 009 — Postgres-First DB Policy (No silent SQLite fallback)

Preamble — update shared guardrails first

Edit prompts/000_shared_guardrails.md and append:

DB policy:

PostgreSQL + pgvector is the required default for any embed/retrieve/ask.

SQLite is tests-only (unit/integration) and must be explicit in tests.

Ingest/normalize must not require a DB.

No silent fallback to SQLite in runtime code paths. Fail fast with an actionable message if Postgres isn't configured.

Provide a single place to diagnose: trailblazer db doctor.

Save this prompt as: prompts/009_postgres_first.md.

To-dos (≤9):

## Fail-fast DB URL

In db/engine.py, remove the implicit SQLite default for runtime. Require DB_URL or TRAILBLAZER_DB_URL to be Postgres except when TB_TESTING=1. Keep SQLite scaffolding behind a clear if testing: branch.

## db doctor command

Add trailblazer db doctor: prints parsed DB URL, attempts connection, verifies pgvector extension and embedding dimension, and exits non-zero with a clean error if anything's missing.

Reuse existing session helpers.

## make db.up (Compose) & make db.wait

Provide a minimal docker-compose.db.yml (Postgres 16 + pgvector).

make db.up (idempotent), make db.down, and make db.wait (poll for readiness).

## Embed & ask hardening

trailblazer embed load and trailblazer ask must error early if DB is not Postgres. Print "Use make db.up then trailblazer db doctor".

## Ingest independence

Double-check that ingest/normalize import no DB modules on code import (only within DB commands). Keep them runnable offline.

## Deterministic vector behavior

Ensure pgvector path remains the default for similarity; retain the Python cosine fallback only in tests. Document tie-break ordering (score DESC, ids ASC).

## Tests

Add unit tests for db doctor (mocked connection/ext check).

Mark SQLite tests with TB_TESTING=1 and verify the runtime raises without that flag.

## Docs

README "Embed & Graph v0": replace "SQLite default" with "Postgres required" for production runs; show make db.up && trailblazer db init && trailblazer db doctor. Update the note that SQLite is for tests only.

## Validation & commit

Run make fmt && make lint && make test && make check-md.

Commit to main. Include one short "Proof of work" block in the prompt with the successful db doctor output.
