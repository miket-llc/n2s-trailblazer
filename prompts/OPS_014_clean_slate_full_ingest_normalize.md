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

# PROMPT OPS-014 — Clean-Slate, Full End-to-End Ingest + Normalize (Confluence ADF + DITA) with Live Terminal Observability ≤9 to-dos

Save as: prompts/OPS_014_clean_slate_full_ingest_normalize.md
Work on: MAIN ONLY
Paste the entire prompts/000_shared_guardrails.md VERBATIM above this prompt. Do not modify it.
Your job: RUN the process so I can watch it live in the terminal (pretty progress). JSON logs go to files. Confluence must ingest in ADF. Ingest/normalize are DB-free. If anything fails: fix utterly (code + tests), then re-run.

To-Dos (max 9)

Sanity & green baseline (no code edits here)

git rev-parse --abbrev-ref HEAD
make setup && make fmt && make lint && make test && make check-md
trailblazer ingest confluence --help | grep -i 'body-format' # must show atlas_doc_format as default

Clean-slate: archive & nuke old runs/state/logs (non-interactive)

```bash
mkdir -p archive logs state/confluence
# Archive then clear runs (start from nothing)
[ -d runs ] && tar -czf "archive/runs_$(date -u +%Y%m%dT%H%M%SZ).tar.gz" runs || true
rm -rf runs
mkdir -p runs
# Backup & clear state so no autosince skips
[ -d state/confluence ] && mkdir -p state/confluence/_backup && \
  cp -a state/confluence/*_state.json state/confluence/_backup/ 2>/dev/null || true
rm -f state/confluence/*_state.json
# Clear old logs
find logs -maxdepth 1 -type f -name 'ingest-*' -delete 2>/dev/null || true
```

Discover ALL spaces and build manifest (no 20-space shortcuts)

```bash
RID_SPACES=$(date -u +'%Y%m%dT%H%M%SZ')_spaces
trailblazer confluence spaces --no-color \
  1> "logs/spaces-$RID_SPACES.jsonl" \
  2> "logs/spaces-$RID_SPACES.out"
jq -r '.[].key' "runs/$RID_SPACES/ingest/spaces.json" | sort -u > state/confluence/spaces.txt
SPC=$(wc -l < state/confluence/spaces.txt | tr -d ' ')
echo "[INFO] total spaces discovered: $SPC"
# Hard fail if suspiciously small (accidental sampling)
test "$SPC" -ge 200 || (echo "[ERROR] too few spaces ($SPC). investigate before proceeding."; exit 2)
```

Create a robust Confluence runner (ADF, verbose, resumable, ALL spaces)

```bash
cat > scripts/run_confluence_full.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
SPACES_FILE="state/confluence/spaces.txt"
[ -f "$SPACES_FILE" ] || { echo "Missing $SPACES_FILE"; exit 2; }
while IFS= read -r SPACE; do
  [ -z "$SPACE" ] && continue
  RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_full_adf"
  echo "[START] Confluence space=$SPACE run_id=$RID"
  # JSON logs (stdout) → file; Pretty progress (stderr) → terminal + file
  trailblazer ingest confluence \
    --space "$SPACE" \
    --body-format atlas_doc_format \
    --progress --progress-every 5 --no-color \
    1> "logs/ingest-$RID-$SPACE.jsonl" \
    2> >(tee -a "logs/ingest-$RID-$SPACE.out") || true
  echo "[DONE ] Confluence space=$SPACE run_id=$RID exit=$?"
  # quick roll-up
  test -f "runs/$RID/ingest/summary.json" && jq -c '{rid:"'"$RID"'",space:"'"$SPACE"'",pages,attachments,links_total,elapsed_seconds}' "runs/$RID/ingest/summary.json" || true
  sleep 2
done < "$SPACES_FILE"
SH
chmod +x scripts/run_confluence_full.sh
# Run in tmux so IDE crashes won't stop it
tmux new -s confluence_full -d 'bash scripts/run_confluence_full.sh'
tmux attach -t confluence_full     # detach with Ctrl-b then d
```

Normalize each Confluence run as it finishes (batch sweep)

```bash
# Sweep all *current* full ADF runs and normalize them
for D in $(ls -1t runs | grep "_full_adf$"); do
  echo "[NORMALIZE] Confluence run_id=$D"
  trailblazer normalize from-ingest --run-id "$D"
done
```

Run full DITA ingest (entire Oxygen tree), verbose & DB-free

```bash
DITA_ROOT="data/raw/dita/ellucian-documentation"
ls -la "$DITA_ROOT" | sed -n '1,120p'   # confirm presence
RID_DITA=$(date -u +'%Y%m%dT%H%M%SZ')_dita_full
trailblazer ingest dita \
  --root "$DITA_ROOT" \
  --progress --progress-every 5 --no-color \
  1> "logs/ingest-$RID_DITA-dita.jsonl" \
  2> >(tee -a "logs/ingest-$RID_DITA-dita.out")
```

Normalize the DITA run

```bash
echo "[NORMALIZE] DITA run_id=$RID_DITA"
trailblazer normalize from-ingest --run-id "$RID_DITA"
```

Spot-check artifacts & traceability (prove correctness for both sources)

```bash
# Confluence (latest)
RID_C=$(ls -1t runs | grep "_full_adf$" | head -n1); echo "[CHK] Confluence run_id=$RID_C"
test -f "runs/$RID_C/ingest/confluence.ndjson" || { echo "[ERR] missing confluence.ndjson"; exit 3; }
head -n1 "runs/$RID_C/ingest/confluence.ndjson" | jq '{source_system,id,title,url,body_repr,label_count,ancestor_count,attachment_count}'
jq -C '. | {pages,attachments,links_total}' "runs/$RID_C/ingest/summary.json"
head -n1 "runs/$RID_C/normalize/normalized.ndjson" | jq '{id,source_system,body_repr,url,text_md: (.text_md[:100]),links: (.links[0:3]),attachments: (.attachments[0:3]),labels: (.labels[0:5])}'

# DITA (full)
echo "[CHK] DITA run_id=$RID_DITA"
test -f "runs/$RID_DITA/ingest/dita.ndjson" || { echo "[ERR] missing dita.ndjson"; exit 3; }
head -n1 "runs/$RID_DITA/ingest/dita.ndjson" | jq '{source_system,id,source_path,doctype,label_count,attachment_count}'
jq -C '. | {pages,attachments,links_total}' "runs/$RID_DITA/ingest/summary.json"
head -n1 "runs/$RID_DITA/normalize/normalized.ndjson" | jq '{id,source_system,body_repr,url,text_md: (.text_md[:100]),links: (.links[0:3]),attachments: (.attachments[0:3]),labels: (.labels[0:5])}'
```

Proof-of-work (paste back)

The tmux attach session tail or the last ~30 lines of a Confluence `*.out` and DITA `*.out` showing [PROGRESS] & [DONE].

The jq snippets showing Confluence has body_repr:"adf" and normalized fields, and DITA has source_path/doctype and normalized fields.

Any errors encountered & the exact fix applied before resuming.
