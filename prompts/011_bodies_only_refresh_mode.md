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

# PROMPT DEV-011 — Bodies-Only Refresh Mode (reuse page IDs, new body-format)

**Branch policy:** MAIN ONLY (no feature branches)\
**Goal:** Add a fast path that, given a prior RUN_ID A, re-fetches page bodies with a different body-format in a new RUN_ID B—no DB use, no re-searching.

## Background

After the overnight ingest with storage format, we discovered we should have used ADF (atlas_doc_format) for better parsing and embedding. Rather than re-ingesting all 168K+ pages from scratch, we need a "bodies-only refresh" mode that reuses existing page IDs and just fetches the body content in a new format.

## To-Dos (max 9)

### 1. New CLI Command Implementation

**Add:** `trailblazer ingest refresh-bodies --from-run <RID_A> --space <KEY|ID> --body-format <storage|atlas_doc_format> [--max-pages N] [--progress]`

**Logic:**

- Read `runs/<RID_A>/ingest/confluence.ndjson` and extract page IDs (and URLs for fallback/space_key check)
- Validate `--space` parameter matches the target space in the source run
- For each page ID: call v2 `GET /api/v2/pages/{id}?body-format=...` (and attachments via v2 if not already present)
- Write new RUN_ID B under `runs/<RID_B>/ingest/...`
- Preserve space_key/space_id; do not mutate RUN_A

### 2. Artifact Contract

**confluence.ndjson lines include:**

- `body_repr` matching target format (storage or adf)
- Only overwrite body fields (`body_html`, `body_storage`, etc.), not title/ids/metadata unless server returns updated values
- Preserve all existing page metadata (title, space_key, created_at, etc.)

**summary.json includes:**

```json
{
  "mode": "bodies_refresh",
  "from_run": "<RID_A>",
  "target_body_format": "atlas_doc_format",
  "pages": 1234,
  "missing_pages": 5,
  "elapsed": "12.3s"
}
```

### 3. Safety & Error Handling

**Missing page handling:**

- If a page 404s in refresh, log `event=ingest.refresh_missing_page` and continue
- Track `missing_pages` count in summary
- Do not fail the entire operation for individual missing pages

**Validation:**

- Add `--max-pages` for smoke runs and testing
- Validate space_key for each record (map or URL fallback)
- Warn once per unknown space and increment a counter

### 4. Progress & Console Output

**Respect existing patterns:**

- Honor `--progress` and `--progress-every` flags
- Stage banner: `[STAGE] Re-fetching bodies for N pages from <RID_A> in <FORMAT>`
- Progress format: `page_id | "Title" | att=N | timestamp (rate/s)`
- JSON events to stdout, human progress to stderr

### 5. Space Key Correctness

**Space validation:**

- Validate space_key for each record using existing map or URL fallback logic
- Warn once per unknown space_key and increment a counter
- Ensure refresh only processes pages from the specified `--space` parameter
- Skip pages from other spaces with warning

### 6. Testing Requirements (Offline)

**Fixture tests:**

- Create fixture NDJSON with 3 page IDs in storage format
- Ensure refresh writes new RUN_ID with `body_repr` set correctly
- Verify non-body fields are preserved (title, space_key, created_at)
- Test missing page handling increments `missing_pages` count
- Mock Confluence API responses for different body formats

### 7. Documentation Updates

**README section:** "Bodies-only refresh"

- Use cases: format conversion, re-processing with different body types
- Example commands: `trailblazer ingest refresh-bodies --from-run 2025-08-14_050859_e742 --space AR --body-format atlas_doc_format`
- Expected outputs: new run directory structure, summary.json format
- Verification steps: checking body_repr, comparing content

### 8. No DB on Refresh Path

**Ensure DB-free operation:**

- Importing the new command must not touch DB
- Add/extend the "no DB on ingest import" test
- Verify refresh command works without DB_URL set
- Maintain existing ingest isolation guarantees

### 9. Validation & Commit

**Pre-commit workflow:**

```bash
make fmt && make lint && make test && make check-md
```

**Commit message:**

```
feat(ingest): bodies-only refresh mode for new body-format; tests & docs

- Add refresh-bodies CLI command to re-fetch with different body-format
- Reuse existing page IDs without re-searching spaces
- Support storage -> atlas_doc_format conversion
- Include safety for missing pages and space validation
- Maintain DB-free ingest guarantee
```

## Acceptance Criteria

1. **New command** reuses existing page IDs and outputs fresh run with new body format (e.g., atlas_doc_format)
1. **Summary shows** mode:"bodies_refresh", correct counts, and from_run reference
1. **Preserves metadata** while updating only body content fields
1. **Handles errors gracefully** with missing page tracking and continuation
1. **Maintains DB isolation** - no database dependencies in refresh path
1. **Complete test coverage** with offline fixtures and mocked API responses

## Example Usage

```bash
# Convert overnight storage ingest to ADF format
trailblazer ingest refresh-bodies \
  --from-run 2025-08-14_050859_e742 \
  --space AR \
  --body-format atlas_doc_format \
  --progress --progress-every 10

# Smoke test with limited pages  
trailblazer ingest refresh-bodies \
  --from-run 2025-08-14_050859_e742 \
  --space AR \
  --body-format atlas_doc_format \
  --max-pages 50
```
