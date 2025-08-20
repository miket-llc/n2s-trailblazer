Trailblazer Mindfile (Copy-Paste Canonical)

Purpose — This document is the single source of truth for how Trailblazer runs end-to-end: contracts between stages, logging/telemetry standards, operational runbooks, and “don’t break this” invariants. Paste into your repo docs (e.g., docs/MINDFILE.md) and keep it authoritative.

0. Mission & Non-Negotiables

Canonical Pipeline:
Ingest → Normalize → Enrich → Chunk (materialized) → Preflight → Plan-Preflight → Dispatch → Embed (DB) → QA/Verify

No run-level gating for quality. Filter/skip at the document level only. A run is BLOCKED only if:
MISSING_ENRICH | MISSING_CHUNKS | TOKENIZER_MISSING | CONFIG_INVALID | EMBEDDABLE_DOCS=0.

Materialized Chunk precedes Embed. Embed must not chunk. It fails fast if chunk/chunks.ndjson is missing/empty.

Provider/Model/Dimension: OpenAI text-embedding-3-small, dimension=1536 (singular everywhere).

Postgres + pgvector only in ops. No SQLite.

Determinism: Same inputs → same chunk IDs (doc_id:NNNN), stable token counts, stable manifests.

Traceability mandatory: Every chunk and packed context carries title|url, source_system, labels, space{id,key}, media_refs (if present).

Python-first: All logic lives in src/trailblazer/\*\*. No shell workarounds; no subprocess/os.system/pexpect/pty/shlex.

1. Stage Contracts & Artifacts

Per run var/runs/<RID>/…

Normalize: normalize/normalized.ndjson (traceability present)

Enrich: enrich/enriched.jsonl (fingerprints, section_map, chunk_hints, quality[\_score])

Chunk (materialized):
chunk/chunks.ndjson + chunk/chunk_assurance.json

Preflight (per-run):
preflight/preflight.json + preflight/doc_skiplist.json

Embed:
embed/manifest.json + embed_assurance.json

Global reports

Plan: var/plan_preflight/<TS>/{plan_preflight.json,csv,md,ready.txt,blocked.txt,log.out}

Chunk Sweep: var/chunk_sweep/<TS>/…

Chunk Verify: var/chunk_verify/<TS>/…

Retrieval QA: var/retrieval_qc/<TS>/{ask\_\*.json,pack_stats.json,readiness.json,overview.md}

Dispatch logs: var/logs/dispatch/\<DISPATCH_TS>/{dispatch_manifest.json,plan_preflight/,dispatcher.out,embed_env.\*.json}

Events: var/logs/<RID>/events.ndjson (+ symlink var/logs/latest.ndjson)

2. Observability & Progress (one standard)

EventEmitter is the only logging path. No ad-hoc print() (CLI help exempt).

Event JSONL shape

{
"ts":"ISO8601", "level":"INFO|WARN|ERROR",
"stage":"ingest|normalize|enrich|chunk|preflight|plan_preflight|dispatch|embed|qa|verify|runner",
"rid":"\<run_id>", "op":"discover|run|audit|verify|assure|upsert|pack|…",
"status":"START|END|OK|FAIL|SKIP",
"duration_ms":123, "counts":{"docs":0,"chunks":0,"tokens":0},
"doc_id":null, "chunk_id":null,
"provider":"openai", "model":"text-embedding-3-small", "dimension":1536,
"reason": null
}

Progress files (atomic): var/progress/<stage>.json → {rid, started_at, updated_at, totals:{docs,chunks,tokens}, status}

3. Chunking v2.2 Contract

Location: src/trailblazer/pipeline/steps/chunk/\*

Hard cap: hard_max_tokens=800 — no chunk may exceed this cap.

Overlap: overlap_tokens=60 applied consistently on every split path.

Bottoms: soft_min_tokens=200 (glue target), hard_min_tokens=80 (floor; violate only for tiny_doc, fence_forced, table_forced).

Split order:
section_map + chunk_hints → paragraph → sentence → code fences (line blocks) → tables (row groups) → final token window.
Orphan headings merged; small final tail allowed (tail_small=true) if merge would break cap.

Coverage: Record char_start/end (and token offsets if cheap). Union coverage ≥ 99.5% (whitespace-normalized). Gaps are failures.

Traceability: Every chunk includes title|url, source_system, labels, space{id,key}, media_refs.

Assurance (chunk_assurance.json):
tokenCap (max/hardMax/overlap), token/char stats, splitStrategies dist, bottoms, coverage, traceability, status: PASS|FAIL.

Verify CLI:
trailblazer chunk verify --runs-glob 'var/runs/\*' --max-tokens 800 --soft-min 200 --hard-min 80 --require-traceability true
→ exit 1 on oversize, coverage gaps, or missing traceability.

Never block a run at chunking. Skip pathological documents only; log why.

4. Preflight & Plan-Preflight (advisory quality)

Per-run Preflight output (preflight.json):

{
"status":"READY|BLOCKED",
"reasons": [],
"docTotals":{"all":N,"embeddable":M,"skipped":N-M},
"quality":{"p50":0.0,"p90":0.0,"belowThresholdPct":0.0},
"advisory":{"quality":true},
"artifacts":{"enriched":true,"chunks":true,"tokenizer":true,"config":true}
}

Doc skiplist: preflight/doc_skiplist.json → {"skip":["doc_id_a","doc_id_b"],"reason":"quality_below_min"}

READY when embeddable ≥ 1 and artifacts OK.

BLOCKED only for structural or EMBEDDABLE_DOCS=0.

Plan-Preflight (builds bundle; invokes preflight per run)

Accepts both input formats: run_id[:chunk_count] and var/runs/\<run_id>.

Writes canonical bundle under var/plan_preflight/<TS>/…

Target: READY = 1,780, BLOCKED ≈ 25 (zero-embeddable or structural).

Cleaning bad bundles

trailblazer embed clean-preflight [--dry-run] — archives invalid/legacy bundles and stray plan .txt.

5. Embed (DB/pgvector)

Location: src/trailblazer/pipeline/steps/embed/\*

Hard guards

Embed must not chunk; importing/calling chunk code raises a clear error.

Missing/empty chunk/chunks.ndjson → fail fast.

Behavior

Resolve RIDs from plan; accept both formats; strip comments/blank lines.

Load materialized chunks.ndjson as the source of truth.

If preflight/doc_skiplist.json exists, exclude those doc_ids.

Document bootstrap: if enriched.jsonl metadata for a given chunk’s doc_id is missing/mismatched, synthesize a minimal Document from the chunk traceability (title|url|source_system, labels/space) with deterministic content_sha256 (sha256 of text_md); upsert Document first, then upsert Chunk.

Dimension runtime guard: assert provider dimension == 1536 before upserts.

Upsert & commit: batch embed remaining chunks; ON CONFLICT upsert embeddings; commit safely (batch or end-of-run), log batch OK/FAIL events, write embed_assurance.json with {embeddedDocs, skippedDocs, embeddedChunks, provider, model, dimension}.

6. Dispatcher & Monitor

Dispatcher

Consumes var/plan_preflight/<TS>/ready.txt (or --plan-preflight-dir), archives the plan bundle into var/logs/dispatch/\<DISPATCH_TS>/plan_preflight/, writes dispatch_manifest.json, and still runs per-RID preflight for safety.

Supports --skip-unchanged (delta manifest).

Monitor

Standard output: active_workers, EWMA, ETA, and provider/dimension table.

DB uniformity check during wave:

SELECT provider, dimension, COUNT(\*) AS n
FROM public.chunk_embeddings
GROUP BY 1,2
ORDER BY 1,2;
-- Expect a single row: (openai, 1536)

7. QA / Retrieval Readiness

trailblazer qa retrieval --queries-file prompts/qa/queries_n2s.yaml --budgets 1500,4000,6000 --top-k 12

Signals: doc diversity, tie rate, duplication, traceability.

Artifacts: per-query ask\_\*.json, pack_stats.json, readiness.json, overview.md.

Thresholds: minUniqueDocs, maxTieRate, requireTraceability=true.

8. CLI Quick Reference

# Sync & smoke

git fetch origin && git checkout main && git reset --hard origin/main
make fmt && make lint && make -k test

# Clean legacy/bad plans & scripts

trailblazer embed clean-preflight
trailblazer admin script-audit --dry-run # optional; --fix to auto-upgrade wrappers

# Build plan (invokes preflight per RID) — target READY=1780

LATEST_CHUNK_SWEEP="$(ls -dt var/chunk_sweep/\* | head -n1)"
trailblazer embed plan-preflight \
--plan-file "$LATEST_CHUNK_SWEEP/ready_for_preflight.txt" \
--provider openai --model text-embedding-3-small --dimension 1536 \
--min-embed-docs 1 --quality-advisory true \
--out-dir var/plan_preflight/

# Pilot embed (prove DB writes)

PLAN_DIR="$(ls -dt var/plan_preflight/\* | head -n1)"
for RID in $(head -n3 "$PLAN_DIR/ready.txt"); do
trailblazer embed run --run "$RID" \
--provider openai --model text-embedding-3-small --dimension 1536 \
--batch-size "${TB_EMBED_BATCH:-128}"
done

# DB sanity (expect a single (openai,1536) row growing)

psql "$TRAILBLAZER_DB_URL" -X -P pager=off -c "
SELECT provider, dimension, COUNT(\*) AS n
FROM public.chunk_embeddings
GROUP BY 1,2 ORDER BY 1,2;"

# Full dispatch wave (provenance + skip-unchanged)

scripts/embed_dispatch.sh \
--plan-preflight-dir "$PLAN_DIR" \
--skip-unchanged \
--notes "embed-wave $(date -u +%Y%m%dT%H%M%SZ)"
scripts/monitor_embedding.sh

9. Troubleshooting (fast map)

0 inserts, many READY runs: likely FK rollback from missing Document → ensure Document bootstrap is active in embed loader. Check events.ndjson for IntegrityError.

Thousands of oversize chunks: re-run chunk verify; then chunk audit → chunk rechunk (targets only) → verify again.

Run wrongly BLOCKED for quality: preflight must be advisory; ensure QUALITY_GATE not used as run reason; only EMBEDDABLE_DOCS=0 is valid data-driven block.

Dimension drift or DB type mismatch: strict runtime check (dimension==1536) + DB query above; fix env and re-run.

Legacy scripts re-introduced behavior: run trailblazer admin script-audit --fix.

10. Policy & CI (what must always pass)

No subprocess/shell workarounds in CLI or pipeline steps.

No embed-time chunking (forbid import/calls to chunk from embed modules).

EventEmitter required in preflight and embed; no stray print in stage code.

Singular --dimension in CLI, docs, wrappers.

Plan/Preflight reasons must never include QUALITY_GATE at run level.

Scripts/ wrappers (if any) must be thin delegates to the Python CLI and use current flags.

11. Acceptance Checklist (for each wave)

Chunk verify passes: 0 oversize; coverage ≥ 99.5%; 0 missing traceability.

Plan-Preflight READY = 1,780; BLOCKED ≈ 25 (structural/zero-embeddable).

Pilot embed (2–3 runs) inserts rows; DB query shows a single (openai,1536) row growing.

Dispatcher run archives plan, logs are standard JSONL, embed_assurance.json shows {embeddedDocs, skippedDocs}.

Monitor stable; EWMA/ETA reasonable; provider/dimension table uniform.

12. Glossary (short)

RID — Run ID (directory under var/runs/).

Embeddable doc — Document that passes per-doc quality and is not listed in skiplist.

Skiplist — preflight/doc_skiplist.json, per-run list of doc IDs to skip during embed.

Assurance — Machine-readable per-stage report (chunk_assurance.json, embed_assurance.json).

READY target — Count of runs expected to embed in a wave (here 1,780).

13. Standard SQL (pgvector sanity)
    -- Vector schema sanity (provider/dimension uniformity)
    SELECT provider, dimension, COUNT(\*) AS n
    FROM public.chunk_embeddings
    GROUP BY 1,2
    ORDER BY 1,2;

-- Example per-run inserted rows (optional)
SELECT SUBSTRING(chunk_id,1,64) AS chunk_id_prefix, COUNT(\*)
FROM public.chunk_embeddings
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;

Ops Guardrails (set these every shell)
export PAGER=cat LESS=-RFX GIT_PAGER=cat

# Keep scripts zsh/tmux-safe, `set -euo pipefail`
