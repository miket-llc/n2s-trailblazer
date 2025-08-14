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

Artifacts immutable: write to runs/run-id/phase/…; never mutate previous runs.

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

______________________________________________________________________

# PROMPT 011B — Traceability & Link Graph Preservation (CODE)

**Branch policy:** MAIN ONLY (no feature branches)
**Goal:** Preserve traceability end-to-end: exact source URL, internal cross-refs (page↔page), external refs, and attachments/media references — all reconstructable downstream.

## Context (for a fresh Claude)

Trailblazer ingests Confluence (ADF default), normalizes to Markdown, later embeds to Postgres+pgvector. Ingest/normalize are DB-free. We must preserve traceability end-to-end: exact source URL, internal cross-refs (page↔page), external refs, and attachments/media references — all reconstructable downstream.

**MANDATORY:** Review impacted files before coding. Be surgical unless a tiny refactor reduces risk. ZERO test failures, ZERO IDE linter errors.

## To-Dos (max 9)

### 1. Enrich Ingest NDJSON with Canonical Traceability Fields

For each page record (no DB): ensure these keys exist and are populated:

- `source_system:"confluence"`
- `space_id`, `space_key`, `page_id` (string)
- `url` (absolute), `version`, `created_at`, `updated_at`
- `attachments:[{id, filename, media_type, file_size, download_url}]` (already present; keep)

Do not emit `"space_key":"unknown"`; use the hotfixed mapping/URL fallback (we already implemented).

### 2. Extract Outbound Links During Ingest (Lightweight, No Downloads)

Parse outbound links from the body representation you already fetched (ADF or Storage), producing a list per page with:

- `raw_url`, `normalized_url`, `anchor` (fragment or ADF mark), `text` (if available)
- `target_type:"confluence"|"external"|"attachment"`

For Confluence links, parse `/spaces/<KEY>/pages/<ID>/...` → `target_page_id`. For unresolved, leave null and set `target_type:"external"`.

Store this page-level list temporarily (don't bloat the page object).

### 3. Write Traceability Sidecars (Deterministic) in `runs/<RID>/ingest/`

**links.jsonl** — one edge per line:

```json
{ "from_page_id": "...", "from_url": "...",
  "target_type": "confluence|external|attachment",
  "target_page_id": "...|null", "target_url": "...", "anchor": "...|null",
  "rel": "links_to" }
```

**attachments_manifest.jsonl** — one per attachment:

```json
{ "page_id": "...", "filename": "...", "media_type": "...", "file_size": ..., "download_url": "..." }
```

Keep existing `pages.csv`, `attachments.csv`, `summary.json`. Extend `summary.json` with:
`links_total`, `links_internal`, `links_external`, `links_unresolved`, `attachment_refs`.

### 4. Normalize Must Preserve Traceability

Ensure `normalized.ndjson` includes: `source_system`, `space_key`, `space_id`, `id` (page_id), `url`, `version`, `created_at`, `updated_at`, `body_repr`, `attachments:[{filename,url}]`, `links:[...]` (strings or objects as already implemented).

If currently only strings, preserve at least the full `normalized_url` strings; do not drop external links.

### 5. Resolver Helpers (Pure Functions, No Network)

Implement small helpers to:

- Classify link as `confluence|external|attachment`
- Parse `target_page_id` from a Confluence URL
- Normalize URL (strip tracking params; preserve anchors)

Unit-test these helpers.

### 6. Unit/Integration Tests (Offline)

- `test_trace_links_storage_and_adf.py`: given minimal Storage/ADF bodies, assert extraction produces expected `links.jsonl` lines, with internal `target_page_id` parsed and externals preserved.
- `test_trace_attachments_manifest.py`: attachments sidecar lines match NDJSON attachments.
- `test_normalize_traceability.py`: normalized records retain `url`, `space_key`, `links`, and `attachments` (references intact).

All tests green.

### 7. Console & JSON Logs (Do Not Over-Print)

Keep pretty progress on stderr; do not dump every link to console.

For structured logs on stdout, add roll-up events per N pages: `ingest.links_rollup` with internal/external counts; and a final `ingest.traceability_summary`.

### 8. Docs

README "Traceability": document fields in ingest NDJSON, `links.jsonl`, `attachments_manifest.jsonl`, and normalized NDJSON; show how to reconstruct a link graph (from→to) and how attachments are referenced. Include 1–2 jq examples.

### 9. Validation & Commit

Run: `make fmt && make lint && make test && make check-md` — all green.

Commit (main):

```
feat(ingest): traceability sidecars (links, attachments_manifest); preserve refs in normalized NDJSON; tests & docs
```

Paste proof-of-work outputs (last ~10 lines of each Make step).

## Acceptance

- Ingest produces `links.jsonl` + `attachments_manifest.jsonl`, `summary.json` has link counters.
- Normalized records retain `url`, `links`, and `attachments` (reference-only) — all reconstructable downstream.
- No regressions; ingest remains DB-free.
