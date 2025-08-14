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

# PROMPT OPS-018 — Full Fresh Run (CLI-Verified, ADF default, var/ only)

**Context (read carefully; new instance!):**
Trailblazer ingests (1) Confluence Cloud (email + API token; v2 endpoints) and (2) DITA XML (Oxygen), then normalizes both to a unified format downstream uses. All runtime artifacts live under var/ (var/runs, var/state, var/logs). We want a fresh, full ingest: Confluence in ADF (aka atlas_doc_format) before normalization, and DITA. Delete stale runs/state to avoid partials. Do not proceed if any tests fail or the CLI surface doesn't match what we detect below. Output must be observable in the terminal (progress + summaries) and as JSONL logs on disk.

## To-Dos (keep order; ≤9)

1. **Sanity & guardrails checks (must be green):**

   ```bash
   set -euo pipefail
   python --version
   make setup
   make fmt && make lint && make test && make check-md
   ```

   If anything fails: STOP and report the failure summary; do not continue.

1. **Detect the actual CLI surface (no assumptions):**

   ```bash
   trailblazer --help || { echo "[ERROR] trailblazer CLI unavailable"; exit 2; }
   trailblazer ingest --help || true
   trailblazer ingest confluence --help || true
   trailblazer ingest dita --help || true
   trailblazer normalize --help || true
   ```

1. **Set shell vars based on what you see (export them in this shell):**

   - SPACE_FLAG → either --space or --spaces
   - SPACE_ID_FLAG → --space-id if present, else empty
   - BODY_FLAG → --body-format (required)
   - ADF_VALUE → atlas_doc_format (verify it appears in help; if not offered, STOP and report)
   - SINCE_FLAG → --since if present; AUTO_SINCE_FLAG → --auto-since if present
   - PROGRESS_FLAG → --progress if present; PROGRESS_EVERY_FLAG → --progress-every if present
   - NOCOLOR_FLAG → --no-color if present

1. **Spaces lister: Detect one of:**

   - trailblazer confluence spaces (preferred), else
   - trailblazer ingest confluence --list-spaces (or similarly named), else
   - if neither exists but var/state/spaces.txt already exists, we can use it; otherwise STOP and report "no way to enumerate spaces".

1. **Unify workspace, clean slate (archive old stuff, then start fresh):**

   ```bash
   mkdir -p var/{runs,logs,state} archive
   # Move any legacy top-level runs/data/state logs into archive (if they exist)
   for d in runs data state logs; do [ -d "$d" ] && mv "$d" "archive/${d}-$(date -u +'%Y%m%dT%H%M%SZ')"; done
   # Hard-clean old run/state to avoid mixing formats
   rm -rf var/runs/* 
   rm -rf var/state/confluence/* || true
   ```

1. **Ensure Confluence credentials exist in environment** (CONFLUENCE_BASE_URL=https://ellucian.atlassian.net/wiki, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN).

1. **Enumerate ALL spaces, persist, and show me counts:**

   ```bash
   RID_SPACES="$(date -u +'%Y%m%dT%H%M%SZ')_spaces"
   if trailblazer confluence spaces 1> "var/logs/spaces-$RID_SPACES.jsonl" 2> "var/logs/spaces-$RID_SPACES.out"; then
     :
   elif trailblazer ingest confluence --help | grep -qi "list-spaces"; then
     trailblazer ingest confluence --list-spaces \
       1> "var/logs/spaces-$RID_SPACES.jsonl" \
       2> "var/logs/spaces-$RID_SPACES.out"
   elif [ -s var/state/spaces.txt ]; then
     echo "[INFO] Using existing var/state/spaces.txt"
   else
     echo "[ERROR] No CLI support to enumerate spaces and no var/state/spaces.txt present"; exit 3
   fi

   # Derive a unique list into state if we produced a JSONL; otherwise keep existing spaces.txt
   if [ -f "var/logs/spaces-$RID_SPACES.jsonl" ]; then
     # Expect the spaces JSON/JSONL to have .key fields; adjust jq path if needed
     jq -r '.[]?.key // .key // empty' "var/logs/spaces-$RID_SPACES.jsonl" | sort -u > var/state/spaces.txt
   fi

   echo "[INFO] Spaces to process: $(wc -l < var/state/spaces.txt | tr -d ' ')"
   head -n 20 var/state/spaces.txt || true
   ```

1. **Run full Confluence ingest for every space in ADF with readable progress (tmux + logs):**

   ```bash
   # Resolve flags (defaults if missing)
   : "${PROGRESS_FLAG:=}"; : "${PROGRESS_EVERY_FLAG:=}"; : "${NOCOLOR_FLAG:=}"
   : "${SPACE_FLAG:=--space}"; : "${BODY_FLAG:=--body-format}"; : "${ADF_VALUE:=atlas_doc_format}"

   cat > scripts/run_confluence_full.sh <<'SH'
   #!/usr/bin/env bash
   set -euo pipefail
   SPACE_FLAG="${SPACE_FLAG:---space}"
   BODY_FLAG="${BODY_FLAG:---body-format}"
   ADF_VALUE="${ADF_VALUE:-atlas_doc_format}"
   PROGRESS_FLAG="${PROGRESS_FLAG:-}"
   PROGRESS_EVERY_FLAG="${PROGRESS_EVERY_FLAG:-}"
   NOCOLOR_FLAG="${NOCOLOR_FLAG:-}"

   while IFS= read -r SPACE; do
     [ -z "$SPACE" ] && continue
     RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_full_adf"
     echo "[START] space=$SPACE rid=$RID"
     # stdout: JSONL events; stderr: human progress
     trailblazer ingest confluence \
       "$SPACE_FLAG" "$SPACE" \
       "$BODY_FLAG" "$ADF_VALUE" \
       ${PROGRESS_FLAG:+$PROGRESS_FLAG} \
       ${PROGRESS_EVERY_FLAG:+$PROGRESS_EVERY_FLAG 5} \
       ${NOCOLOR_FLAG:+$NOCOLOR_FLAG} \
       1> "var/logs/ingest-$RID-$SPACE.jsonl" \
       2> >(tee -a "var/logs/ingest-$RID-$SPACE.out")
     echo "[DONE ] space=$SPACE rid=$RID exit=$?"
   done < var/state/spaces.txt
   SH
   chmod +x scripts/run_confluence_full.sh

   tmux new -s confluence_full -d 'bash scripts/run_confluence_full.sh'
   tmux set -g mouse on
   tmux attach -t confluence_full
   ```

1. **Normalize each Confluence run and emit summaries:**

   ```bash
   for RID in $(ls -1 var/runs | grep "_full_adf$" || true); do
     echo "[NORM] $RID"
     trailblazer normalize from-ingest --run-id "$RID" \
       1> "var/logs/normalize-$RID.jsonl" \
       2> >(tee -a "var/logs/normalize-$RID.out")
   done
   ```

1. **Run full DITA ingest (from your provided root) → normalize, with progress:**

   ```bash
   DITA_ROOT="data/raw/dita/ellucian-documentation"
   : "${PROGRESS_FLAG:=}"; : "${PROGRESS_EVERY_FLAG:=}"; : "${NOCOLOR_FLAG:=}"
   RID_DITA="$(date -u +'%Y%m%dT%H%M%SZ')_dita_full"
   trailblazer ingest dita --root "$DITA_ROOT" \
     ${PROGRESS_FLAG:+$PROGRESS_FLAG} \
     ${PROGRESS_EVERY_FLAG:+$PROGRESS_EVERY_FLAG 5} \
     ${NOCOLOR_FLAG:+$NOCOLOR_FLAG} \
     1> "var/logs/ingest-$RID_DITA-dita.jsonl" \
     2> >(tee -a "var/logs/ingest-$RID_DITA-dita.out")

   trailblazer normalize from-ingest --run-id "$RID_DITA" \
     1> "var/logs/normalize-$RID_DITA.jsonl" \
     2> >(tee -a "var/logs/normalize-$RID_DITA.out")
   ```

1. **Spot-check traceability & output contracts (paste results back):**

   ```bash
   # Pick a recent Confluence run
   RID_C=$(ls -1t var/runs | grep "_full_adf$" | head -n1 || true)
   if [ -n "${RID_C:-}" ]; then
     echo "[CHECK] Confluence raw:"
     head -n1 "var/runs/$RID_C/ingest/confluence.ndjson" | jq '{source_system,space_key,space_id,page_id,url,body_repr,labels,ancestors,attachments}'
     echo "[CHECK] Confluence normalized:"
     head -n1 "var/runs/$RID_C/normalize/normalized.ndjson" | jq '{id,source_system,url,links: (.links[0:3]),attachments: (.attachments[0:3])}'
   fi

   echo "[CHECK] DITA raw:"
   head -n1 "var/runs/$RID_DITA/ingest/dita.ndjson" | jq '{source_system,source_path,doctype,labels,attachments}'

   echo "[CHECK] DITA normalized:"
   head -n1 "var/runs/$RID_DITA/normalize/normalized.ndjson" | jq '{id,source_system,url,links: (.links[0:3]),attachments: (.attachments[0:3])}'
   ```

## Proof-of-work (return these artifacts / snippets)

- The first and last 30 lines from one var/logs/ingest-<RID>-<SPACE>.out and from var/logs/ingest-\<RID_DITA>-dita.out.
- The four jq samples above.
- If anything failed, state the failure, the fix you applied, and re-run evidence.
