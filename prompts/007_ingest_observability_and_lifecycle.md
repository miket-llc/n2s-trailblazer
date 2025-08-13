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

# PROMPT 007 — Confluence Ingest Observability + Auto-Since + Prune (CODE) ≤ 9 to-dos

Save as: prompts/007_ingest_observability_and_lifecycle.md
Work on: main only (no feature branches)
Before you start: paste prompts/000_shared_guardrails.md verbatim at the top. Do not modify guardrails here.
Non-regression: Do not remove/rename existing CLI, steps, or configs. Keep all 005/005B/006 behavior intact.

## To-Dos

### Spaces listing (CLI + artifact + logs)

Add trailblazer confluence spaces that calls the existing v2 client to list spaces.

Console (pretty): columns ID KEY NAME TYPE STATUS.

Structured log per space: event=confluence.space, fields=id,key,name,type,status,homepage_id.

Write runs/\<RUN_ID>/ingest/spaces.json (array of spaces).

### Per-page progress & attachment visibility (logs + optional pretty)

Enhance ingest confluence to accept --progress (bool) and --progress-every N (int, default 1).

For each page, log event=confluence.page with: space_key,space_id,page_id,title,version,updated_at,url,body_repr,attachments_count.

If attachments exist, also log event=confluence.attachments with page_id,count,filenames.

If --progress, pretty-print throttled lines like:
DEV | p=12345 | "Title" | att=3 | 2025-08-10T12:00:00Z.

### Ingest sidecars (CSV + JSON)

In runs/\<RUN_ID>/ingest/ export:

pages.csv: space_key,page_id,title,version,updated_at,attachments_count,url.

attachments.csv: page_id,filename,media_type,file_size,download_url.

summary.json: per-space totals (pages,attachments,empty_bodies,avg_chars) + run_id,started_at,completed_at.

### Auto-since via state (no duplication of code paths)

Add --auto-since to trailblazer ingest confluence.

If present, read state/confluence/<SPACE>\_state.json and use last_highwater for --since.

After successful run, update that file with last_highwater (max updated_at seen) and last_run_id.

If missing, warn and proceed without --since.

### Seen IDs + diff-deletions (no DB deletes yet)

During ingest, write runs/\<RUN_ID>/ingest/seen_page_ids.json (per space).
New CLI:
trailblazer ingest diff-deletions --space <KEY> --baseline-run \<RID_A> --current-run \<RID_B>
→ write deleted_ids.json (IDs in baseline not in current) under the current run's ingest dir and print a count.

### Prune old run artifacts (safe, opt-in)

New CLI: trailblazer ops prune-runs --keep N --min-age-days D [--dry-run].

Exclude newest N and any RIDs referenced by state/confluence/\*.json.

Default dry-run; require explicit flag to delete.

Emit prune_report.json under logs/ (or reports/).

### README — Observability & Ops

Add examples for: confluence spaces, observable ingest (--progress, sidecars), diff-deletions, and ops prune-runs.

### Tests (offline)

test_spaces_cli.py: fake client returns 2 spaces → JSON artifact written and rows printed.

test_ingest_sidecars.py: tiny NDJSON fixture → pages.csv, attachments.csv, summary.json written with correct counts.

test_auto_since_state.py: state file read & updated with max updated_at.

test_diff_deletions.py: two small seen_page_ids.json → correct deleted_ids.json.

test_prune_dry_run.py: creates fake run dirs → only expected candidates listed; no deletion without flag.

### Validate & commit (proof-of-work)

Run: make fmt && make lint && make test && make check-md.
Paste last ~10 lines of each command.
Commit:
git commit -m "feat(ingest): spaces listing, progress logs, sidecars, auto-since; ingest diff-deletions; ops prune-runs; docs+tests"
Push to main.

## Notes

Keep structured logging via our existing logger; don't add new frameworks.

Delta semantics remain: v1 CQL prefilter when --since present; then bodies/attachments via v2.

Don't rename existing CLI; only add commands/flags.

Ensure all CSV/JSON writes are deterministic (sorted keys; stable row ordering).
