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

# PROMPT 011A — Make ADF the Default Body Format (Product-Grade, Zero Test Failures, No Regressions)

**Branch policy:** MAIN ONLY (no feature branches)\
**Goal:** Set ADF (atlas_doc_format) as the default body format everywhere without breaking storage support.

## Context (read me first — you're likely a fresh instance)

Trailblazer = our AI-powered knowledge base builder for Ellucian/Navigate to SaaS. It ingests Confluence, normalizes content, later embeds into Postgres+pgvector, supports retrieval and doc generation, with immutable artifacts under runs/\<RUN_ID>/….

**Separation of concerns (non-negotiable):**

- Ingest/Normalize are DB-free (filesystem artifacts only).
- Embed/Retrieve/Ask use Postgres+pgvector (SQLite is tests/CI only).

**What we're doing:** Prompt 011 adds a bodies-only refresh mode. This prompt (011A) sets ADF (atlas_doc_format) as the default body format everywhere without breaking storage support.

**Standards:** product-grade code, ZERO test failures, ZERO IDE linter errors, no shortcuts, use Makefile toolchain only.

## Change Plan (Review First)

**Files to modify:**

1. `src/trailblazer/core/config.py` - Set CONFLUENCE_BODY_FORMAT default
1. `src/trailblazer/pipeline/steps/ingest/confluence.py` - Update CLI default
1. `src/trailblazer/pipeline/steps/normalize/html_to_md.py` - ADF preference logic
1. `configs/dev.env.example` - Update example config
1. `README.md` - Update documentation
1. Tests - Update expected defaults, maintain storage coverage

**Defaulting logic:**

- Config: `CONFLUENCE_BODY_FORMAT = "atlas_doc_format"` with env override
- CLI: `--body-format` defaults to config value
- Normalize: Prefer ADF when both formats present

**Side-effects confirmed safe:**

- Storage format remains fully functional
- No breaking changes to existing workflows
- All API pass-through maintains compatibility

## To-Dos (max 9)

### 1. Config Default → ADF

Set `CONFLUENCE_BODY_FORMAT = "atlas_doc_format"` in `core/config.py`. Still honor env overrides.

### 2. Ingest CLI Default → ADF

In `trailblazer ingest confluence`, default `--body-format` to "atlas_doc_format" and ensure `--help` shows it.

### 3. Client Pass-through (No Hardcoding)

Ensure `ConfluenceClient.get_pages/get_page_by_id` always pass the resolved body format (CLI arg → env → default). No hidden "storage" hardcodes.

### 4. Normalize Prefers ADF Automatically

If both storage & ADF are present, use ADF and set `body_repr:"adf"` in normalized output. Keep the storage path functional.

### 5. Tests: Update & Keep Storage Coverage

Update tests that assumed storage by default to expect ADF. Keep at least one storage ingest+normalize test to prevent regressions. ALL tests must pass. ZERO failures.

### 6. Docs & Examples

- In `configs/dev.env.example`, set `CONFLUENCE_BODY_FORMAT=atlas_doc_format` (note that storage is still supported).
- README "Ingest/Normalize": state ADF is default; storage supported.

### 7. No DB on Ingest Path

Re-check that ingest imports do not pull DB modules. (011/011A must remain DB-free.)

### 8. Validation & Commit (Product-Grade)

Run: `make fmt && make lint && make test && make check-md`\
All green. No warnings.

### 9. Commit Message

```
chore(ingest): set ADF (atlas_doc_format) as default; tests/docs updated; storage path intact
```

## Acceptance Criteria (Must Meet All)

1. `trailblazer ingest confluence --help` shows `atlas_doc_format` as the default
1. A run with no explicit `--body-format` writes NDJSON lines with `"body_repr":"adf"`
1. Normalize consumes ADF by default, and storage still passes tests
1. ZERO test failures, ZERO IDE linter errors, and no DB calls from ingest paths
1. Storage format path remains functional for backward compatibility
