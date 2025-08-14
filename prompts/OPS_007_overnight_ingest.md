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

# PROMPT OPS-007 — Overnight Confluence Ingest (Observable, Resumable, DB-free)

**Branch policy:** MAIN ONLY (no code changes; ops only)

**Note:** Ingest uses no DB. Postgres is only for embed/retrieve later.

## To-Dos (max 9)

### 1. Sanity & env (no DB needed for ingest)

```bash
git rev-parse --abbrev-ref HEAD
make setup && make fmt && make lint && make test && make check-md
# Confluence creds must be present:
grep -E 'CONFLUENCE_(BASE_URL|EMAIL|API_TOKEN)' .env configs/dev.env.example
```

### 2. List spaces & select targets

```bash
RID=$(date -u +'%Y%m%dT%H%M%SZ')_spaces
trailblazer confluence spaces --no-color \
  1> "logs/spaces-$RID.jsonl" \
  2> "logs/spaces-$RID.out"
# build/curate the space list
mkdir -p state/confluence
jq -r '.[].key' "runs/$RID/ingest/spaces.json" | sort -u > state/confluence/spaces.txt
sed -n '1,20p' state/confluence/spaces.txt   # edit this file to the spaces you want tonight
```

### 3. Plan the run (separate logs, resumable)

- **JSON (machine logs)** → stdout file
- **Pretty/Progress (human)** → stderr file
- **Checkpoints** every ~150 pages or 60s, whichever first.

### 4. Create the overnight runner script

```bash
mkdir -p scripts logs
cat > scripts/overnight_ingest.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
SPACES_FILE="state/confluence/spaces.txt"
[ -f "$SPACES_FILE" ] || { echo "Missing $SPACES_FILE"; exit 2; }
while IFS= read -r SPACE; do
  [ -z "$SPACE" ] && continue
  RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_backfill"
  echo "[START] $SPACE run_id=$RID"
  # JSON → stdout log; Pretty → stderr log
  trailblazer ingest confluence \
    --space "$SPACE" \
    --progress --progress-every 5 \
    --checkpoint-every 150 --checkpoint-secs 60 \
    --no-color \
    1> "logs/ingest-$RID-$SPACE.jsonl" \
    2> "logs/ingest-$RID-$SPACE.out" || true
  echo "[DONE ] $SPACE run_id=$RID exit=$?"
  # quick sanity: show summary line if present
  test -f "runs/$RID/ingest/summary.json" && jq -c '{space: "'$SPACE'", pages, attachments, elapsed}' "runs/$RID/ingest/summary.json" || true
  # be polite to the API between spaces
  sleep 3
done < "$SPACES_FILE"
SH
chmod +x scripts/overnight_ingest.sh
```

### 5. Kick it off in the background (choose one)

**tmux (recommended):**

```bash
tmux new -s trailblazer -d 'bash scripts/overnight_ingest.sh'
tmux ls
```

**nohup:**

```bash
nohup bash scripts/overnight_ingest.sh > logs/overnight.console 2>&1 & disown
tail -f logs/overnight.console
```

### 6. Observe live progress (human)

```bash
tail -f logs/*-$(date -u +'%Y%m%dT').*-*.out
# The .out files should show STAGE banners, periodic [PROGRESS] lines, and a [DONE] summary per space.
```

### 7. Observe machine logs (JSON)

```bash
tail -f logs/*-$(date -u +'%Y%m%dT').*-*.jsonl | jq '.event? // "line"'
# You should see confluence.page / confluence.attachments events streaming.
```

### 8. Resume if interrupted

For any space that got interrupted, find the last run id and re-run with `--resume-from`:

```bash
SPACE=PM
LAST_RID=$(ls -1t logs/ingest-*-$SPACE.jsonl | head -n1 | sed -E 's#logs/ingest-(.*)-'"$SPACE"'\.jsonl#\1#')
NEW_RID=$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_resume
trailblazer ingest confluence --space "$SPACE" --resume-from "$LAST_RID" --progress --no-color \
  1> "logs/ingest-$NEW_RID-$SPACE.jsonl" \
  2> "logs/ingest-$NEW_RID-$SPACE.out"
```

### 9. Morning verification

```bash
for RID in $(ls -1t runs | head -n10); do
  test -f runs/$RID/ingest/summary.json && jq -c '{rid:"'$RID'", pages, attachments, elapsed}' runs/$RID/ingest/summary.json
done
# spot-check NDJSON & sidecars
RID=$(ls -1t runs | head -n1)
wc -l "runs/$RID/ingest/confluence.ndjson"
head -n3 "runs/$RID/ingest/pages.csv"
jq -C '. | {pages, attachments, total_estimate, checkpoints_written, resume_from}' "runs/$RID/ingest/summary.json"
```
