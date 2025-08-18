Objective
Add a CLI‑driven retrieval QA that runs a curated set of N2S domain queries, captures packed contexts at multiple budgets (e.g., 1500/4000/6000 chars), computes health metrics (recall proxies, diversity, duplication, tie‑rates), and emits a readiness report for operators. Results become part of our standard proofs bundle.

Inputs

Query set file (default): prompts/qa/queries_n2s.yaml containing the mindfile’s canonical questions (e.g., “What are the stages of the Navigate to SaaS methodology?”, etc.) plus space for client‑specific queries.

Budgets (default): 1500,4000,6000.

Retriever config (provider/model/dimension) sourced from env or flags.

Outputs (under timestamped dir)
var/retrieval_qc/<TS>/:

ask\_<slug>\_<budget>.json — query, hits (with doc_id, chunk_id, source metadata), scores, pack.

pack_stats.json — per‑budget stats: average score, tie‑rate, doc diversity, unique doc coverage.

readiness.json — summary health: queries run, failures, pass rate, thresholds, aggregates.

overview.md — human summary with READY/BLOCKED table per query & remediation tips.
(Matches artifacts the mindfile expects in spirit and location.)

Scoring / Health signals (no gold labels required)

Doc diversity (entropy / unique docs per pack).

Duplication (percent of repeated chunk_id/doc_id per pack).

Tie‑rate (frequency of identical top scores; flags ranking instability).

Source completeness (presence of title, url, source_system, etc.—traceability guard).

Optional weak heuristics per query (keyword/phrase presence; configurable).

Gates (defaults, configurable)

Fail a query if: top‑K unique docs < threshold; tie‑rate > threshold; missing required traceability fields; or weak‑signal check fails (when enabled).

Fail the run if: >X% queries fail, or average diversity below threshold.

Integration points

Reads provider/model/dimension from env (keeps alignment with D1/D4).

Records the most recent embed manifest info (from D8) in readiness.json for provenance.

Can be hooked into CI or invoked after a large embed dispatch.

Updated POR (what’s left after D9)

⭕ D10 — Dispatcher consumes plan‑preflight/ready.txt and archives the report alongside dispatch logs (if not already merged).

⭕ D5 (optional) — DB dimension guard if monitor reveals recurring drift.

▶️ The Very Next Prompt (copy‑paste to a fresh coding chat)

Title: D9 — Implement Retrieval QA Harness (trailblazer qa retrieval) with artifacts & readiness report

Context (paste verbatim):
We’ve completed D1/D2/D3/D4/D6/D7/D8. Now we need D9: a retrieval QA harness that runs a curated set of domain questions, captures multi‑budget packs, computes health metrics, and emits a readiness bundle under var/retrieval_qc/<TS>/. Use the N2S domain questions from our mindfile as the baseline query set and produce artifacts the mindfile expects (ask JSONs, multi‑budget packs, readiness report). Before acting, open and follow prompts/000_shared_guardrails.md. Use Postgres‑only ops, no pagers, deterministic output. Reference the mindfile’s Retrieval QA section for canonical queries and artifact expectations.

Guardrails (do first):

Postgres only; no schema changes.

No pagers: export PAGER=cat, LESS=-RFX.

zsh/tmux‑safe scripts; core logic in CLI; scripts only orchestrate.

Deterministic ordering: sort by score DESC, tie‑break by (doc_id ASC, chunk_id ASC) when presenting results.

Tasks:

CLI command
Add trailblazer qa retrieval with flags:

--queries-file prompts/qa/queries_n2s.yaml (default), YAML list of {id, text, notes?, expectations?}

--budgets 1500,4000,6000 (default)

--top-k 12 (default)

--provider/--model/--dimension (defaults from env)

--out-dir var/retrieval_qc/ (default; create var/retrieval_qc/<TS>/)
Behavior per query × budget: run retriever/packer, serialize results.

Artifacts

ask\_<slug>\_<budget>.json → include query, retrieved hits (ids, scores), packed text, and source metadata (title, url, source_system, labels) to satisfy traceability.

pack_stats.json → per budget: averages (score, tie‑rate), unique doc counts, doc entropy.

readiness.json → {timestamp, provider, model, dimension, manifestInfo?, totals, failures[], thresholds, metrics}.

overview.md → two tables (PASS / FAIL) with reasons and quick fixes.

Health checks & thresholds (tunable defaults)

minUniqueDocs (default 3) in top‑K per budget.

maxTieRate (default 0.35) in top‑K per budget.

requireTraceability (true): each hit must include title, url, source_system.

Optional weak‑signal check: simple phrase match for the main topic phrase in the packed text.

Comparison utility (optional in this PR if small)

trailblazer qa compare --baseline <TS1> --candidate <TS2> --out var/retrieval_qc/compare\_<TS1>_vs_<TS2>/

Produce diff.json and diff.md highlighting improvements/regressions (fail counts, diversity, tie‑rate deltas).

Tests

Unit: packer stats (diversity, tie‑rate), traceability checks, thresholds logic.

Integration: small fixture corpus; ensure PASS/FAIL classification is deterministic; multi‑budget outputs present.

Doc test: ensure overview.md renders tables and links to key JSON artifacts.

Docs

Add prompts/qa/queries_n2s.yaml populated with the mindfile’s example questions (N2S stages, Sprint 0 vs Prepare, Banner integrations, SA responsibilities, Curriculum Management runbooks).

Mindfile/README: short section “Running Retrieval QA” showing:

trailblazer qa retrieval \
--queries-file prompts/qa/queries_n2s.yaml \
--budgets 1500,4000,6000 \
--provider openai --model text-embedding-3-small --dimension 1536

Acceptance:

Running the command produces var/retrieval_qc/<TS>/ with: ask\_\*.json per query/budget, pack_stats.json, readiness.json, and overview.md.

readiness.json reports counts and PASS/FAIL per query with reasons; thresholds configurable.

Traceability fields are present in all hits; missing metadata causes a clear FAIL reason.

Deterministic ordering/ties; outputs are tmux‑friendly; no paged output.

Artifacts to return:

Diffs for CLI modules and helpers.

One overview.md snippet showing PASS/FAIL tables.

A sample readiness.json and one ask\_<slug>\_<budget>.json including traceability metadata.
