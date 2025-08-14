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

## Additional Global Rules

**Tests:** No merges to main with any failing tests. If tests fail, fix tests or the code; do not comment out or delete tests unless replaced by better coverage in the same PR.

**DB policy:** Ingest & normalize must not require a DB. Postgres/pgvector is only for retrieval/indexing phases; CLI preflights for DB must not gate ingest/normalize.

**Body format:** Confluence default body_format is atlas_doc_format (ADF). Storage/XHTML handling stays for backward compatibility and normalization.

**Traceability:** Always persist id, url, space_id/key/name (if available), version, created_at, updated_at, labels, ancestors/breadcrumbs, attachments (with filenames + download URLs), links, and content_sha256 throughout ingest → normalize.

**Observability:** All long-running CLIs must stream clean, structured progress (banners, per-phase counters, ETA) and print the run_id at completion.

**Cursor limit:** Keep prompts ≤10 to-dos; chunk work if needed.

**No regression:** Before edits, read the module and associated tests; prefer minimal deltas. If complexity is high, refactor in tiny steps with passing tests after each step.

# PROMPT DEV-015 — Path Unification to var/ (runs/state/logs) + trailblazer paths CLI ≤9 to-dos

Save as: prompts/015_path_unification.md
Work on: MAIN ONLY
Paste prompts/000_shared_guardrails.md VERBATIM at the top (do not modify).
Goal: Make all workspace paths config-driven, defaulting to var/ for tool-managed artifacts and data/ for human-managed inputs; add a trailblazer paths CLI; keep ingest/normalize DB-free; do not regress behavior.

Mandatory review first (not counted): List files you'll touch, outline a tiny change plan, and confirm no regressions (CLI UX, ADF default, ingest/normalize behavior, tests). Surgical by default; small refactor only if it reduces risk.

To-Dos (max 9)

Config & helpers

In src/trailblazer/core/config.py add:

TRAILBLAZER_DATA_DIR (default "data"), TRAILBLAZER_WORKDIR (default "var").

Derived: RUNS_DIR, STATE_DIR, LOG_DIR, CACHE_DIR, TMP_DIR from WORKDIR.

Add src/trailblazer/core/paths.py exposing:

def data() -> Path; def workdir() -> Path
def runs() -> Path; def state() -> Path; def logs() -> Path
def cache() -> Path; def tmp() -> Path
def ensure_all() -> None

Respect env overrides; paths are repo-relative.

CLI: trailblazer paths

Add a sub-app paths with:

trailblazer paths → human table of resolved dirs.

trailblazer paths --json → machine JSON {"data": "...", "workdir":"...", "runs":"...", "state":"...", "logs":"...", "cache":"...", "tmp":"..."}.

trailblazer paths ensure → create all dirs.

Write-path migration (code)

Replace all writes to runs/, state/, logs/ with paths.runs()/paths.state()/paths.logs().

No DB imports in ingest/normalize code paths (re-assert).

Legacy read fallback (backcompat)

When reading legacy runs/state/logs, try new locations first (var/\*), then legacy (./runs, ./state, ./logs).

When writing, always target var/\*.

.gitignore update

Ensure var/ and data/ are ignored by default; keep !data/README.md allowed.

Do not ignore prompts/, scripts/, etc.

Scripts touchpoint

Update any internal scripts/ops helpers (if present in repo) to call paths.ensure() and to write under var/….

Do not change long-running ops prompts here; we'll update them in the OPS prompt.

Tests

Unit: paths resolve defaults + env overrides.

Smoke: ingest writes to var/runs/<RID>/ingest; state updates to var/state/….

Legacy read fallback: put a fake legacy run under ./runs/legacy_demo/… and confirm read queries find it.

Docs

README: add "Workspace layout" explaining data/ (human inputs) vs var/ (tool-managed workspace). Show trailblazer paths output and ensure.

Validation & commit (product-grade)

make fmt && make lint && make test && make check-md

All green, zero IDE linter errors. Commit to main:

feat(paths): config-driven workspace; default var/{runs,state,logs}; paths CLI; tests+docs

Paste proof-of-work (last ~10 lines of each command).

Acceptance

All new writes go to var/runs, var/state, var/logs; legacy reads still work.

trailblazer paths + paths --json + paths ensure exist.

Ingest/normalize remain DB-free; ADF default untouched; tests green.
