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

# PROMPT OPS-BIG-001 — Clean-Slate, Full Ingest & Normalize (Confluence ADF → DITA), Serial & Observable

**Branch:** main (no feature branches)

## READ ME FIRST (tell the user up front)

This is a full, from-scratch harvest: all Confluence spaces (ADF), then all DITA (Oxygen) — serially.

It will take a long time (hours) and produce a lot of artifacts. That's intentional.

We will archive then delete all prior runs/logs/state before starting.

The run is observable: clean banners, progress, heartbeats in the terminal; NDJSON logs to disk; assurance & index at the end.

Ingest/Normalize are DB-free. Do not touch Postgres here.

## To-Dos (≤ 9) — run in order, paste outputs as proof

### 1) Baseline & CLI surface (must be green)

```bash
set -euo pipefail
make setup
make fmt && make lint && make test && make check-md
trailblazer paths ensure && trailblazer paths doctor
trailblazer ingest confluence --help | sed -n '1,200p'
trailblazer ingest dita --help     | sed -n '1,120p'  
trailblazer normalize --help       | sed -n '1,120p'
```

Extract flag names you will use in the next steps (export them if needed):

- **Confluence:** `--space` (or `--spaces`), `--body-format` (must accept `atlas_doc_format`), `--progress`, `--progress-every`, `--no-color`.
- **DITA:** `--root`, progress flags.

**If ADF (`atlas_doc_format`) isn't supported → STOP and open a tiny DEV patch before continuing.**

### 2) NUKE prior runs/state/logs (archive then delete — explicit)

```bash
mkdir -p archive var/{runs,logs,state}
# Archive any old var content for safety (skip if empty)
tar -czf "archive/var_runs_$(date -u +%Y%m%dT%H%M%SZ).tgz"   -C var runs   || true
tar -czf "archive/var_logs_$(date -u +%Y%m%dT%H%M%SZ).tgz"   -C var logs   || true  
tar -czf "archive/var_state_$(date -u +%Y%m%dT%H%M%SZ).tgz"  -C var state  || true
# **Delete** everything so we start from nothing:
rm -rf var/runs/* var/logs/* var/state/*
trailblazer paths ensure
```

**Proof:** paste `ls -la var/runs var/state var/logs` (should be empty dirs).

### 3) Enumerate ALL Confluence spaces (no sampling) & sanity check

```bash
RID_SPACES="$(date -u +'%Y%m%dT%H%M%SZ')_spaces"
trailblazer confluence spaces \
  1> "var/logs/spaces-$RID_SPACES.jsonl" \
  2> "var/logs/spaces-$RID_SPACES.out"

jq -r '.[]?.key // .key // empty' "var/logs/spaces-$RID_SPACES.jsonl" | sort -u > var/state/spaces.txt
SPC=$(wc -l < var/state/spaces.txt | tr -d ' ')
echo "[INFO] discovered spaces: $SPC"
# sanity (we expect hundreds+); fail fast if suspiciously small  
test "$SPC" -ge 200 || { echo "[ERROR] too few spaces ($SPC). STOP."; exit 2; }
head -n 25 var/state/spaces.txt
```

### 4) Full Confluence (ADF) ingest — serial & observable (create + run)

```bash
cat > scripts/run_confluence_full.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
SPACE_FLAG="--space"            # adjust if your CLI shows a different flag
BODY_FLAG="--body-format"       # must accept atlas_doc_format
PROG="--progress"
EVERY="--progress-every"
NOCOLOR="--no-color"

while IFS= read -r SPACE; do
  [ -z "$SPACE" ] && continue
  RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_full_adf"
  echo "[START] Confluence space=$SPACE rid=$RID"
  trailblazer ingest confluence \
    "$SPACE_FLAG" "$SPACE" \
    "$BODY_FLAG" atlas_doc_format \
    "$PROG" "$EVERY" 5 "$NOCOLOR" \
    1> "var/logs/ingest-$RID-$SPACE.jsonl" \
    2> >(tee -a "var/logs/ingest-$RID-$SPACE.out")
  echo "[DONE ] Confluence space=$SPACE rid=$RID exit=$?"
done < var/state/spaces.txt
SH
chmod +x scripts/run_confluence_full.sh

# Run in tmux so IDE crashes don't kill the job; stay attached to see live progress
tmux new -s confluence_full -d 'bash scripts/run_confluence_full.sh'
tmux set -g mouse on
tmux attach -t confluence_full   # detach any time: Ctrl-b then d
```

**What you'll see:** per-space start/end lines, steady [PROGRESS] heartbeats, page titles with att=<count>, retries/errors when they happen.

**Proof:** paste last ~50 lines from one `var/logs/ingest-*-<SPACE>.out`.

### 5) Normalize all Confluence runs produced (batch sweep)

```bash
for RID in $(ls -1 var/runs | grep "_full_adf$" || true); do
  echo "[NORM] Confluence: $RID"
  trailblazer normalize from-ingest --run-id "$RID" \
    1> "var/logs/normalize-$RID.jsonl" \
    2> >(tee -a "var/logs/normalize-$RID.out")
done
```

**Proof:** paste counts via `wc -l var/runs/*_full_adf/normalize/normalized.ndjson | tail`.

### 6) Full DITA ingest (entire Oxygen tree) — then normalize

```bash
DITA_ROOT="data/raw/dita/ellucian-documentation"
RID_DITA="$(date -u +'%Y%m%dT%H%M%SZ')_dita_full"
echo "[START] DITA root=$DITA_ROOT rid=$RID_DITA"
trailblazer ingest dita --root "$DITA_ROOT" --progress --progress-every 5 --no-color \
  1> "var/logs/ingest-$RID_DITA-dita.jsonl" \
  2> >(tee -a "var/logs/ingest-$RID_DITA-dita.out")
echo "[NORM] DITA: $RID_DITA"
trailblazer normalize from-ingest --run-id "$RID_DITA" \
  1> "var/logs/normalize-$RID_DITA.jsonl" \
  2> >(tee -a "var/logs/normalize-$RID_DITA.out")
```

**Proof:** paste last ~50 lines from `var/logs/ingest-$RID_DITA-dita.out`.

### 7) Hard proofs (ADF only; parity; traceability samples)

```bash
# latest Confluence run
RID_C=$(ls -1t var/runs | grep "_full_adf$" | head -n1 || true)

# ADF only (no storage)
jq -r '.body_repr' "var/runs/$RID_C/ingest/confluence.ndjson" | sort -u
# raw vs normalized line counts
echo "[CHECK] raw=$(wc -l < var/runs/$RID_C/ingest/confluence.ndjson)  norm=$(wc -l < var/runs/$RID_C/normalize/normalized.ndjson)"
# traceability sample
head -n1 "var/runs/$RID_C/normalize/normalized.ndjson" | jq '{id,source_system,url,links: (.links[0:3]),attachments: (.attachments[0:3]),labels: (.labels[0:5])}'

# DITA parity + sample
echo "[CHECK] DITA raw=$(wc -l < var/runs/$RID_DITA/ingest/dita.ndjson)  norm=$(wc -l < var/runs/$RID_DITA/normalize/normalized.ndjson)"
head -n1 "var/runs/$RID_DITA/normalize/normalized.ndjson" | jq '{id,source_system,url,links: (.links[0:3]),attachments: (.attachments[0:3]),labels: (.labels[0:5])}'
```

**If any check fails (storage appears, zeros, or missing fields) — STOP, fix tests+code, re-run the failing piece, and re-paste these proofs.**

### 8) Index & pointers (one place to look)

```bash
IDX="var/runs/INDEX-$(date -u +'%Y%m%dT%H%M%SZ').md"
{
  echo "# Run Index"
  echo "## Confluence (latest: $RID_C)"
  echo "- Raw: var/runs/$RID_C/ingest/confluence.ndjson"
  echo "- Normalized: var/runs/$RID_C/normalize/normalized.ndjson"
  echo "- Logs: var/logs/ingest-$RID_C-*.{out,jsonl}  var/logs/normalize-$RID_C.{out,jsonl}"
  echo "## DITA (run: $RID_DITA)"
  echo "- Raw: var/runs/$RID_DITA/ingest/dita.ndjson"
  echo "- Normalized: var/runs/$RID_DITA/normalize/normalized.ndjson"
  echo "- Logs: var/logs/ingest-$RID_DITA-dita.{out,jsonl}  var/logs/normalize-$RID_DITA.{out,jsonl}"
} > "$IDX"
echo "[INDEX] $IDX"
```

**Paste first 10 lines of the index.**

### 9) Final proof-of-work (paste back)

- Last ~50 lines from one `ingest-*-<SPACE>.out` and from `ingest-$RID_DITA-dita.out`.
- Outputs from step 7 (ADF only + parity + traceability samples).
- First 10 lines of the INDEX path.
- Any errors encountered and the exact fix applied (code + tests) before resuming.
