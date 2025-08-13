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

# PROMPT DEV-008 — Ingest Execution & Isolation Fix + Observability (CODE) ≤9 to-dos

Work on: main only.

## Why we're changing this (context for you, Claude)

Ingest must be filesystem-only (NDJSON + metrics). It must not import or initialize any DB (SQLite/Postgres) anywhere on the ingest codepath.

The current behavior sometimes logs debug and exits as if complete. That's not acceptable. We need explicit run states, exit codes, and observable progress.

We also need "only updated" incrementals via --since/auto-since, but a first backfill must fetch everything (no silent no-op).

## To-Dos (max 9)

### 1. Hard isolation: no DB on ingest path

Search for any imports/initialization of trailblazer.db.\* or engines within: CLI ingest command, ingest step module, runner phase for ingest.

If present, move those imports into the code paths that actually use them (embed, ask) or guard them behind lazy functions so importing the ingest CLI does not touch DB.

Add a unit test test_ingest_import_no_db.py that imports the ingest CLI module (and calls --help) and asserts no DB engine logs are emitted.

### 2. Run semantics + exit codes

Define explicit exit codes for the ingest CLI:

- 0 = success, pages >= 1
- 2 = configuration/auth failure
- 3 = remote/API failure
- 4 = empty result when not allowed

Add --allow-empty flag: if not set, and pages processed == 0 → log error and exit 4. If set → log a warning and continue.

### 3. Progress & page-level logging (observable)

Add --progress (bool) and --progress-every N (default 1).

For each page, log JSON: event=confluence.page, fields: space_key,space_id,page_id,title,version,updated_at,url,body_repr,attachments_count.

If attachments exist, also log event=confluence.attachments with page_id,count,filenames.

Pretty line (gated by --progress):
DEV | p=12345 | "Title" | att=3 | 2025-08-10T12:00:00Z (throttle via --progress-every).

### 4. Spaces listing CLI + artifact

New command: trailblazer confluence spaces.

Print table: ID KEY NAME TYPE STATUS.

Emit runs/\<RUN_ID>/ingest/spaces.json (array with id,key,name,type,status,homepage_id) and structured logs event=confluence.space.

### 5. Sidecars for observability

Write in runs/\<RUN_ID>/ingest/:

- pages.csv: space_key,page_id,title,version,updated_at,attachments_count,url
- attachments.csv: page_id,filename,media_type,file_size,download_url
- summary.json: per-space totals and overall: pages,attachments,empty_bodies,avg_chars,run_id,started_at,completed_at

### 6. Auto-since via state (no duplicate logic)

Add --auto-since: read state/confluence/<SPACE>\_state.json and use last_highwater as --since.

After a successful run, update that file (last_highwater = max updated_at seen, last_run_id).

### 7. Seen IDs + diff deletions (no DB deletes yet)

During ingest, write runs/\<RUN_ID>/ingest/seen_page_ids.json (per space).

New CLI: trailblazer ingest diff-deletions --space <KEY> --baseline-run \<RID_A> --current-run \<RID_B> → write deleted_ids.json and print the count.

### 8. Tests (offline)

- test_ingest_import_no_db.py: importing ingest CLI and calling --help doesn't create a DB engine (spy logger or monkeypatch engine factory).
- test_ingest_sidecars.py: tiny fixture → pages.csv, attachments.csv, summary.json correct.
- test_auto_since_state.py: state read/updated correctly.
- test_diff_deletions.py: baseline/current IDs → expected deletions.

### 9. README: Observability & Exit codes

Document --progress, --progress-every, sidecars, --auto-since, diff-deletions, and the exit codes.

Add examples (don't remove existing docs).

## Acceptance

- Running ingest does not touch DB.
- Progress and attachment info visible in logs and sidecars.
- Empty runs fail unless --allow-empty.
- Spaces list and deletion diff CLIs work.
- Tests + lint + md checks green.
