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

______________________________________________________________________

# PROMPT OPS-013 — Full End-to-End Ingest & Normalize (Confluence ADF + DITA) From Scratch

**Work on**: MAIN ONLY (no feature branches)

**Your job**: RUN it (not just describe it) so we can watch live in the terminal. Confluence must ingest in ADF before normalization. Ingest/normalize are DB-free. If anything fails, stop, fix tests/code utterly, and re-run (as in OPS-012).

## To-Dos (max 9)

### 1. Sanity & guardrails (NO code changes; ensure green baseline)

```bash
git rev-parse --abbrev-ref HEAD           # must be main
make setup && make fmt && make lint && make test && make check-md
trailblazer ingest confluence --help | grep -i 'body-format'   # confirm default shows atlas_doc_format
```

### 2. Start from "nothing" state (don't delete runs; reset state & prepare logs)

```bash
mkdir -p logs state/confluence
# Backup & clear Confluence state so we do a true backfill (no autosince reuse)
[ -d state/confluence ] && mkdir -p state/confluence/_backup && \
  cp -a state/confluence/*_state.json state/confluence/_backup/ 2>/dev/null || true
rm -f state/confluence/*_state.json
# Clean log staging area
find logs -maxdepth 1 -type f -name 'ingest-*' -delete 2>/dev/null || true
```

### 3. List Confluence spaces & build a manifest

```bash
RID_SPACES=$(date -u +'%Y%m%dT%H%M%SZ')_spaces
trailblazer confluence spaces --no-color \
  1> "logs/spaces-$RID_SPACES.jsonl" \
  2> "logs/spaces-$RID_SPACES.out"
jq -r '.[].key' "runs/$RID_SPACES/ingest/spaces.json" | sort -u > state/confluence/spaces.txt
sed -n '1,200p' state/confluence/spaces.txt    # edit down if needed; otherwise we'll do all spaces
```

### 4. Full Confluence backfill (ADF), space-by-space, observable & resumable

```bash
cat > scripts/run_confluence_full.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
SPACES_FILE="state/confluence/spaces.txt"
[ -f "$SPACES_FILE" ] || { echo "Missing $SPACES_FILE"; exit 2; }
while IFS= read -r SPACE; do
  [ -z "$SPACE" ] && continue
  RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_full_adf"
  echo "[START] Confluence: space=$SPACE run_id=$RID"
  trailblazer ingest confluence \
    --space "$SPACE" \
    --body-format atlas_doc_format \
    --progress --progress-every 5 --no-color \
    1> "logs/ingest-$RID-$SPACE.jsonl" \
    2> >(tee -a "logs/ingest-$RID-$SPACE.out") || true
  echo "[DONE ] Confluence: space=$SPACE run_id=$RID exit=$?"
  # Quick roll-up echo (if summary exists)
  test -f "runs/$RID/ingest/summary.json" && jq -c '{rid:"'"$RID"'",space:"'"$SPACE"'",pages,attachments,links_total}' "runs/$RID/ingest/summary.json" || true
  sleep 2
done < "$SPACES_FILE"
SH
chmod +x scripts/run_confluence_full.sh

# Run in a tmux so you (and we) can watch live progress
tmux new -s confluence_full -d 'bash scripts/run_confluence_full.sh'
tmux attach -t confluence_full   # detach with Ctrl-b then d
```

### 5. Normalize ALL Confluence runs created above

```bash
# Normalize each confluence run we just produced (based on today's timestamp)
for D in $(ls -1t runs | grep "_full_adf$" | head -n 200); do
  echo "[NORMALIZE] $D (Confluence)"
  trailblazer normalize from-ingest --run-id "$D"
done
```

### 6. Full DITA ingest from your Oxygen drop (observable; entire tree)

```bash
DITA_ROOT="data/raw/dita/ellucian-documentation"
ls -la "$DITA_ROOT" | sed -n '1,120p'   # confirm it's there
RID_DITA=$(date -u +'%Y%m%dT%H%M%SZ')_dita_full
trailblazer ingest dita \
  --root "$DITA_ROOT" \
  --progress --progress-every 5 --no-color \
  1> "logs/ingest-$RID_DITA-dita.jsonl" \
  2> >(tee -a "logs/ingest-$RID_DITA-dita.out")
```

### 7. Normalize the DITA run

```bash
echo "[NORMALIZE] $RID_DITA (DITA)"
trailblazer normalize from-ingest --run-id "$RID_DITA"
```

### 8. Spot-check artifacts & traceability (both sources)

```bash
# Pick the most recent Confluence run and the DITA run
RID_C=$(ls -1t runs | grep "_full_adf$" | head -n1); echo "$RID_C"
test -f "runs/$RID_C/ingest/confluence.ndjson"
test -f "runs/$RID_C/ingest/links.jsonl" "runs/$RID_C/ingest/edges.jsonl" "runs/$RID_C/ingest/attachments_manifest.jsonl" "runs/$RID_C/ingest/ingest_media.jsonl" "runs/$RID_C/ingest/labels.jsonl" "runs/$RID_C/ingest/breadcrumbs.jsonl" "runs/$RID_C/ingest/summary.json"
head -n1 "runs/$RID_C/ingest/confluence.ndjson" | jq '{source_system,id,title,url,body_repr,label_count,ancestor_count,attachment_count}'
jq -C '. | {pages,attachments,links_total}' "runs/$RID_C/ingest/summary.json"
head -n1 "runs/$RID_C/normalize/normalized.ndjson" | jq '{id,source_system,body_repr,url,text_md: (.text_md[:100]),links: (.links[0:3]),attachments: (.attachments[0:3]),labels: (.labels[0:5])}'

RID_D="$RID_DITA"
test -f "runs/$RID_D/ingest/dita.ndjson"
test -f "runs/$RID_D/ingest/links.jsonl" "runs/$RID_D/ingest/edges.jsonl" "runs/$RID_D/ingest/attachments_manifest.jsonl" "runs/$RID_D/ingest/ingest_media.jsonl" "runs/$RID_D/ingest/labels.jsonl" "runs/$RID_D/ingest/breadcrumbs.jsonl" "runs/$RID_D/ingest/summary.json"
head -n1 "runs/$RID_D/ingest/dita.ndjson" | jq '{source_system,id,source_path,doctype,label_count,attachment_count}'
jq -C '. | {pages,attachments,links_total}' "runs/$RID_D/ingest/summary.json"
head -n1 "runs/$RID_D/normalize/normalized.ndjson" | jq '{id,source_system,body_repr,url,text_md: (.text_md[:100]),links: (.links[0:3]),attachments: (.attachments[0:3]),labels: (.labels[0:5])}'
```

### 9. Proof-of-work (paste back)

- The tmux attach screenshot/log tail or the last ~30 lines of one Confluence \*.out and the DITA \*.out showing [PROGRESS] and [DONE].
- The jq snippets above proving:
  - Confluence NDJSON body_repr:"adf" plus summary counts, and normalized record preserves links/attachments/labels.
  - DITA NDJSON source_path/doctype plus summary counts, and normalized record preserves links/attachments/labels.
- Any errors encountered and how you resolved them before proceeding.

## Notes

- Ingest/normalize are DB-free; do not set or touch DB_URL here.
- Confluence is explicitly ADF at ingest (--body-format atlas_doc_format) to ensure normalization sees ADF.
- We run Confluence space-by-space sequentially to respect API limits and keep logs clear; DITA ingests the entire Oxygen tree in one go.
- If anything fails or looks off, stop and follow the "fix utterly & re-run" pattern from OPS-012 before we move on to embedding/retrieval.
