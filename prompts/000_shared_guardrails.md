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
