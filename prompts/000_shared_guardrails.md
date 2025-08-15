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

______________________________________________________________________

## Guardrails Addendum (OPS-EMBED-NEXT)

Database Policy (Global, Non-Negotiable): There is ONE runtime database: Postgres with pgvector. No SQLite anywhere in non-test code or ops. Do not add SQLite fallbacks or light/"developer" DB modes.

No pagers in terminal: Set PAGER=cat and LESS=-RFX in every session. If a tool supports pager-off flags (e.g., psql -P pager=off), use them. All command output must stream cleanly (no interactive pagers like less).

______________________________________________________________________

## Guardrails Addendum (OPS-EMBED-ALL-FINAL)

DB Policy: There is ONE runtime DB: Postgres + pgvector. No SQLite anywhere in runtime or ops.

No Pagers: Set PAGER=cat and LESS=-RFX in the session; pass pager-off flags if tools support them. All output must stream; do not invoke interactive pagers.

______________________________________________________________________

## Embedding & DB Non-Negotiables

**PostgreSQL only in ops**: Runtime paths (embed, retrieval, ask) MUST connect to `postgresql://…`. SQLite is allowed ONLY in unit tests guarded by `TB_TESTING=1`. Use `make db.up` + `trailblazer db init` + `trailblazer db doctor` for setup.

**pgvector required**: `trailblazer db doctor` must show `pgvector: available`. If not, fail hard with a clear fixup message pointing to manual extension creation.

**Dimensions discipline**: The provider's configured dimension (e.g., `OPENAI_EMBED_DIM=1536`) MUST match what's persisted in the database. If mismatch detected, ABORT with a remediation hint (or require an explicit `--reembed-all`).

**No pagers**: All scripts/commands must export `PAGER=cat`, `LESS=-RFX` to prevent interactive pagers that break automation.

**No regressions**: Before merge, run `make fmt && make lint && make check-md && make test` and ensure ZERO failures/warnings in IDE.

______________________________________________________________________

## Ops Non-Negotiables

**One DB only**: TRAILBLAZER_DB_URL must be PostgreSQL. No SQLite fallbacks in operations.

**No pagers in scripts**: Always export `PAGER=cat` and `LESS=-RFX` to prevent interactive pagers in automation.

**No regressions**: If CLI flags changed, update scripts immediately to prevent unknown option errors.

**Kill before run**: Always kill old sessions before new embeds to prevent conflicts and resource contention.
