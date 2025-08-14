JSON: /Users/miket/dev/n2s-trailblazer/var/runs/2025-08-14_164029_9f04/ingest/assurance.json
Markdown: /Users/miket/dev/n2s-trailblazer/var/runs/2025-08-14_164029_9f04/ingest/assurance.md
2025-08-14T16:40:30.954728Z [info ] ingest.confluence.assurance_generated json_path=/Users/miket/dev/n2s-trailblazer/var/runs/2025-08-14_164029_9f04/ingest/assurance.json md_path=/Users/miket/dev/n2s-trailblazer/var/runs/2025-08-14_164029_9f04/ingest/assurance.md
2025-08-14T16:40:30.954808Z [info ] ingest.confluence.done attachments=0 body_format=atlas_doc_format out=/Users/miket/dev/n2s-trailblazer/var/runs/2025-08-14_164029_9f04/ingest/confluence.ndjson pages=3 since=None space_key_unknown_count=0 spaces=1
2025-08-14T16:40:30.954878Z [info ] cli.ingest.confluence.done attachments=0 body_format=atlas_doc_format pages=3 run_id=2025-08-14_164029_9f04 since=None space_key_unknown_count=0 spaces=1
2025-08-14_164029_9f04# Shared Guardrails

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

# PROMPT DEV-020S (rev) — Simplify CLI with Thin Wrappers, Remove Stale Scripts (No New Complexity)

Save as: prompts/020S_dev_cli_simplification.md
Branch: main (no feature branches)
Paste prompts/000_shared_guardrails.md verbatim at the top (don't modify).

Intent: Keep ingest/normalize DB-free, ADF for Confluence, workspace var/ only, and the existing subcommands intact. Add minimal wrappers that call those subcommands, so the common flow is simple without building a complicated orchestrator. Delete shell scripts that no longer match reality.

## To-Dos (≤9)

### 1. Read the current CLI (no code yet; paste outputs in your reply)

```bash
make setup && make fmt && make lint && make test && make check-md
trailblazer --help
trailblazer ingest --help || true
trailblazer ingest confluence --help || true
trailblazer ingest dita --help || true
trailblazer normalize --help || true
trailblazer confluence --help || true
trailblazer paths --help || true
```

Detect & note exact flag names:

- Confluence: --space or --spaces? --space-id present? --body-format choices include atlas_doc_format? --since, --auto-since? --progress, --progress-every, --no-color?
- DITA: confirm ingest dita --root PATH and progress flags exist.
- Normalize: confirm normalize from-ingest --run-id RID exists.

### 2. Add thin wrappers (match the detected flags)

- `trailblazer plan` → dry-run preview only (prints counts; no writes).
- `trailblazer ingest-all` → iterate all Confluence spaces (enforce --body-format atlas_doc_format) then DITA root, printing the exact commands it's calling; write to var/ only.
- `trailblazer normalize-all` → normalize every run missing normalized output.
- `trailblazer status` → quick last-run pointers and totals.

These wrappers must call the existing subcommands (no duplicate logic) using the actual flags detected in step 1.

### 3. Enforce workspace (var/ only)

All reads/writes via path helpers; no legacy fallbacks.
If a write resolves to ./runs|./state|./logs, raise a clear error.

### 4. Explicit ADF enforcement

ingest-all must pass --body-format atlas_doc_format to Confluence regardless of defaults, so we never regress.

### 5. Remove/replace stale scripts

Delete any scripts/\*.sh or helpers that still reference legacy paths or tmux workflows that wrappers replace.
Add a short scripts/examples.md that shows the new wrappers only (no shell gymnastics).

### 6. Observability is the wrappers' job too

ingest-all must forward the progress flags (detected in step 1) to underlying commands and echo a per-space start/end line, with where to find:

- stdout JSON logs var/logs/ingest-<RID>-<SPACE>.jsonl
- stderr pretty logs var/logs/ingest-<RID>-<SPACE>.out

Print a single index path per session, e.g., var/runs/INDEX-<ts>.md.

### 7. Tests (must stay green)

- Help snapshot tests for plan, ingest-all, normalize-all, status.
- Dry-run (plan) asserts no files are written.
- A tiny smoke test for ingest-all (with fakes) that asserts it calls underlying commands with the right flags and writes INDEX.
- A small test for normalize-all that skips already-normalized runs.

### 8. Docs

README → "Simple workflow" section that shows exactly:

```sql
trailblazer plan
trailblazer ingest-all --from-scratch
trailblazer normalize-all
trailblazer status
```

Remove old tmux/script guidance; one path only.

### 9. Validation & commit

```bash
make fmt && make lint && make test && make check-md
```

Commit:

```
feat(cli): add plan/ingest-all/normalize-all/status; var/ only; ADF enforced; remove stale scripts; tests+docs
```

## Acceptance

- The wrappers exist and only call existing subcommands with the detected flags (no new complexity).
- All outputs under var/; ADF enforced for Confluence; DB-free remains true; tests green.
- Old scripts removed.
