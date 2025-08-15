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
make check-md  # markdownlint
```

**No DB in Ingest:** Event logging and assurance generation MUST NOT require database connectivity - all observability is file-based under var/.

---

## Guardrails Addendum (OPS-EMBED-ALL-FINAL)

DB Policy: There is ONE runtime DB: Postgres + pgvector. No SQLite anywhere in runtime or ops.

No Pagers: Set PAGER=cat and LESS=-RFX in the session; pass pager-off flags if tools support them. All output must stream; do not invoke interactive pagers.

---

# PROMPT OPS-EMBED-ALL-FINAL — Embed All Runs (pgvector), Serial & Observable (Gated on Enrichment)

**Context for a New Instance**

Pipeline: ingest → normalize → enrich → chunk→embed → retrieve.

Ingest/normalize/enrich are DB-free and write under var/ only.

This prompt embeds all normalized+enriched runs into Postgres+pgvector, serially and visibly, with assurance and a quick ask smoke. If enrichment artifacts are missing for a run, we enrich first, then embed.

## To-Dos (≤ 9) — run in order; paste proofs back

### 1) Baseline & workspace (no pagers; must be green)

```bash
set -euo pipefail
export PAGER=cat
export LESS=-RFX

make setup
make fmt && make lint && make test && make check-md
trailblazer paths ensure && trailblazer paths doctor
```

### 2) Enumerate runs & verify enrichment exists (DB-free)

```bash
RUNS=$(ls -1 var/runs | grep -E '_full_adf$|_dita_full$' | sort) || true
echo "$RUNS" | sed -n '1,100p'
test -n "$RUNS" || { echo "[ERROR] no runs found to process"; exit 2; }

NEEDS_ENRICH=0
for RID in $RUNS; do
  if [ ! -f "var/runs/$RID/enrich/enriched.jsonl" ] || [ ! -f "var/runs/$RID/enrich/fingerprints.jsonl" ]; then
    echo "[WARN] missing enrichment for $RID → will ENRICH now"
    NEEDS_ENRICH=1
  fi
done

if [ "$NEEDS_ENRICH" -eq 1 ]; then
  for RID in $RUNS; do
    if [ ! -f "var/runs/$RID/enrich/enriched.jsonl" ] || [ ! -f "var/runs/$RID/enrich/fingerprints.jsonl" ]; then
      echo "[ENRICH] $RID"
      trailblazer enrich --run-id "$RID" --llm off --progress \
        1> "var/logs/enrich-$RID.jsonl" \
        2> "var/logs/enrich-$RID.out"
    fi
  done
fi
```

### 3) Bring up Postgres + pgvector (NO SQLite), doctor & init

```bash
docker compose -f docker-compose.db.yml up -d
export DB_URL='postgresql+psycopg2://trailblazer:trailblazer@localhost:5432/trailblazer'
trailblazer db check
trailblazer db init
```

If db check fails, STOP and fix infra.

### 4) Embed all runs — serial, observable, changed-only, idempotent

```bash
for RID in $RUNS; do
  echo "[EMBED] $RID"
  trailblazer embed load --run-id "$RID" --provider dummy --batch 256 --changed-only \
    1> "var/logs/embed-$RID.jsonl" \
    2> "var/logs/embed-$RID.out"
done
```

Expect: steady [EMBED] … progress, skips vs inserted, and var/runs/<RID>/embed_assurance.json.

### 5) Assurance proofs (one Confluence + one DITA)

```bash
RID_C=$(ls -1t var/runs | grep '_full_adf$'  | head -n1 || true)
RID_D=$(ls -1t var/runs | grep '_dita_full$' | head -n1 || true)

echo "[ASSURE] Confluence ($RID_C)"
jq -C '{docs_total,docs_embedded,docs_skipped,chunks_total,chunks_embedded,chunks_skipped,provider,dim}' \
  "var/runs/$RID_C/embed_assurance.json" | sed -n '1,120p'

echo "[ASSURE] DITA ($RID_D)"
jq -C '{docs_total,docs_embedded,docs_skipped,chunks_total,chunks_embedded,chunks_skipped,provider,dim}' \
  "var/runs/$RID_D/embed_assurance.json" | sed -n '1,120p'
```

### 6) Retrieval smoke (prove end-to-end)

```bash
trailblazer ask "What is Navigate to SaaS?" --top-k 8 --max-chunks-per-doc 3 --provider dummy --format text \
  1> "var/logs/ask1.jsonl" \
  2> "var/logs/ask1.out"
tail -n 30 var/logs/ask1.out
```

### 7) Hard checks (quick sanity)

```bash
jq -r '.chunks_embedded' "var/runs/$RID_C/embed_assurance.json"
jq -r '.chunks_embedded' "var/runs/$RID_D/embed_assurance.json"

# Enrichment artifacts do exist (spot one record)
test -f "var/runs/$RID_C/enrich/enriched.jsonl" && head -n1 "var/runs/$RID_C/enrich/enriched.jsonl" | jq '{id,collection,quality_flags}'
test -f "var/runs/$RID_D/enrich/enriched.jsonl" && head -n1 "var/runs/$RID_D/enrich/enriched.jsonl" | jq '{id,collection,quality_flags}'
```

### 8) If anything fails

STOP; open a tiny DEV patch targeted to the failure (tests + code), then re-run only the failing run (enrich or embed) and re-paste proofs from 5–7.

### 9) Proof-of-work (paste back)

- Last 30 lines of one var/logs/embed-<RID>.out.
- The two embed_assurance.json summaries (Confluence + DITA).
- Last 30 lines of var/logs/ask1.out.
- If enrichment had to run: last 20 lines of one enrich-<RID>.out.
