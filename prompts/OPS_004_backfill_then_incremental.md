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

# PROMPT OPS-004 — Run a Real Backfill + Incremental (No DB during ingest) ≤9 to-dos

Scope: operations only. No code edits beyond DEV-008 changes.

## To-Dos (max 9)

### 1. Sanity: toolchain & env

```bash
git rev-parse --abbrev-ref HEAD
make setup && make fmt && make lint && make test && make check-md
```

Confirm .env has only Confluence vars for ingest (no DB needed):

```ini
CONFLUENCE_BASE_URL=...
CONFLUENCE_EMAIL=...
CONFLUENCE_API_TOKEN=...
CONFLUENCE_BODY_FORMAT=storage   # or atlas_doc_format
```

### 2. List spaces (artifact & visibility)

```bash
RID=$(date -u +'%Y%m%dT%H%M%SZ')_spaces
trailblazer confluence spaces | tee logs/spaces-$RID.out
test -f runs/$RID/ingest/spaces.json && head -n 3 runs/$RID/ingest/spaces.json
```

### 3. Prepare space manifest + state dir (untracked)

```bash
mkdir -p state/confluence logs
printf "DEV\nDOC\n" > state/confluence/spaces.txt
```

### 4. FULL BACKFILL (no debug, no max limit)

Pick one space to prove it actually downloads pages & attachments:

```bash
SPACE=DEV
RID=$(date -u +'%Y%m%dT%H%M%SZ')_backfill
trailblazer ingest confluence --space "$SPACE" --progress --progress-every 10 2>&1 | tee logs/ingest-$RID-$SPACE.log
```

Do not pass --since for backfill.

Verify artifacts exist:

```bash
ls -l runs/$RID/ingest/{confluence.ndjson,pages.csv,attachments.csv,summary.json}
```

### 5. Enforce "empty run = error"

If the run produced 0 pages, the CLI must have exited with non-zero unless --allow-empty was set. Paste the last 30 log lines and the exit code. If it didn't, fail the task and fix per DEV-008.

### 6. Write/update high-watermark (auto-since)

After backfill, ensure state/confluence/${SPACE}\_state.json contains last_highwater and last_run_id. Print it.

### 7. INCREMENTAL RUN (only updated)

```bash
RID=$(date -u +'%Y%m%dT%H%M%SZ')_delta
trailblazer ingest confluence --space "$SPACE" --auto-since --progress --progress-every 10 2>&1 | tee logs/ingest-$RID-$SPACE.log
```

Confirm (via pages.csv row count and logs) that fewer items are fetched than in backfill (unless there were many updates).

Confirm state file updated to a newer last_highwater.

### 8. (Later) Load embeddings + smoke ask

This is not part of ingest and can use DB.

```bash
export DB_URL=postgresql+psycopg2://...   # if you're ready; otherwise uses sqlite fallback
trailblazer db init
trailblazer embed load --run-id "$RID" --provider dummy --batch 256
trailblazer ask "What is Navigate to SaaS?" --top-k 8 --max-chunks-per-doc 2 --provider dummy --format text
```

### 9. Proof-of-work

Paste: last ~30 lines from logs/ingest-$RID-$SPACE.log (showing page progress + attachment counts).

Head of runs/$RID/ingest/pages.csv and summary.json.

Contents of state/confluence/${SPACE}\_state.json.

Incremental run pages.csv row count vs backfill.
