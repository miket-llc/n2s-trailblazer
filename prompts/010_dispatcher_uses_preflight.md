rompt: D10 — Dispatcher uses plan-preflight + archives provenance

Title: Wire dispatcher to consume var/plan_preflight/<TS>/ready.txt, archive the plan‑preflight bundle alongside dispatch logs, and emit a dispatch_manifest.json (with optional link to latest Retrieval QA)

Context (paste verbatim):
We have: embed preflight, chunk/embed assurance, enrich stabilization, dispatcher preflight gate, embed plan-preflight (ready/blocked + estimates), delta re‑embed (embed manifest|diff|reembed-if-changed), and Retrieval QA. Now implement D10 so the dispatcher:

Consumes a chosen plan‑preflight bundle’s ready.txt (or auto‑selects the latest bundle),

Archives that entire plan‑preflight folder into the new dispatch log folder, and

Writes a dispatch_manifest.json capturing provenance (plan TS, env, model/provider/dimension, workers, batch size, git commit, and optional QA run).
Keep the per‑RID preflight safety in the dispatcher. Support an optional flag to run via reembed-if-changed (D8) to auto‑skip unchanged runs.
Before acting, open and follow prompts/000_shared_guardrails.md. Use Postgres‑only ops; no pagers; zsh/tmux‑safe; keep logic in the CLI where possible and scripts as thin orchestrators.

Guardrails (do first):

Export PAGER=cat, LESS=-RFX; ensure scripts use set -euo pipefail.

No schema/database changes.

Do not delete or modify plan‑preflight outputs; copy or symlink into dispatch logs.

Deterministic ordering by RID; stable, single‑line status logs.

Tasks

1. Plan source resolution & flags

File: scripts/embed_dispatch.sh (or equivalent wrapper)

Add flags:

--plan-preflight-dir <DIR> → expects <DIR>/ready.txt

--plan-file <FILE> → fallback; default remains var/temp_runs_to_embed.txt

--qa-dir <DIR> → optional path to latest Retrieval QA folder (var/retrieval_qc/<TS>/)

--skip-unchanged → optional; if set, invoke trailblazer embed reembed-if-changed per RID (else current behavior); always keep per‑RID preflight in place for safety

--notes "<free text>" → optional operator note recorded in the manifest

Selection order:

If --plan-preflight-dir present → use <DIR>/ready.txt.

Else if --plan-file present → use it.

Else → auto‑pick the latest var/plan_preflight/<TS>/ready.txt if available; otherwise fall back to var/temp_runs_to_embed.txt.

Validate that the chosen plan file exists and has ≥1 RID. Print a green single‑line confirmation showing the source.

2. Provenance & archival

On start, create var/logs/dispatch/\<DISPATCH_TS>/.

Copy (or symlink) the entire selected plan‑preflight folder (if used) into
var/logs/dispatch/\<DISPATCH_TS>/plan_preflight/ (include JSON, CSV, MD, ready.txt, blocked.txt, log.out).

If --qa-dir is provided (and exists), copy/symlink that folder into
var/logs/dispatch/\<DISPATCH_TS>/retrieval_qc/.

Write var/logs/dispatch/\<DISPATCH_TS>/dispatch_manifest.json with:

{
"dispatchTs": "<iso8601>",
"planPreflightDir": "var/plan_preflight/<TS>/", // or null if not used
"planFileUsed": "<path to ready.txt or plan file>",
"runsPlanned": <int>,
"provider": "<resolved>",
"model": "<resolved>",
"dimension": <int>,
"workers": <int>,
"batchSize": <int>,
"gitCommit": "<short-sha or null>",
"qaDir": "var/retrieval_qc/<TS>/" , // if provided, else null
"notes": "<operator note or empty>",
"mode": "reembed-if-changed" // or "embed" if skip flag not set
}

Continue to write per‑worker env snapshots as var/logs/embed_env.<PID>.json (already in place from D4).

3. Dispatch loop behavior (keep safety gates)

For each RID in the plan:

Always run per‑RID trailblazer embed preflight --run "$RID" …. On failure, skip with a red single‑line reason to var/logs/dispatcher.out.

If --skip-unchanged set, call:

trailblazer embed reembed-if-changed --run "$RID" --provider ... --model ... --dimension ...

(This command performs preflight internally and skips when unchanged unless --force.)

Else, enqueue as you do today (existing embed path).

At start, print:

“Using plan: <source> (planned: N; provider/model/dimension/workers/batch)”

If plan‑preflight JSON exists, print the plan’s totals (ready/blocked, estTokens, estCostUSD if present).

At end, print a summary:

Queued: X, Skipped (preflight): Y, Skipped (unchanged): Z, Errors: 0/…

Path to dispatch_manifest.json and archived plan‑preflight (and QA, if any).

4. Tests

Unit (shell or bats): plan resolution order; non‑existent/empty plan handling; archival path creation.

Integration (dry run with fakes):

Create a fake var/plan_preflight/<TS>/ready.txt with two RIDs and a minimal plan_preflight.json; run dispatcher with --plan-preflight-dir.

Verify:

The plan bundle is copied/symlinked under var/logs/dispatch/\<DISPATCH_TS>/plan_preflight/.

dispatch_manifest.json exists and fields are correct.

var/logs/dispatcher.out shows green source line, per‑RID status, and final summary.

Repeat with --skip-unchanged and mock one RID to be unchanged (via reembed-if-changed exit path); confirm “skipped (unchanged)”.

5. Docs (short addendum)

README / Ops:

# Create/confirm a plan

trailblazer embed plan-preflight --provider openai --model text-embedding-3-small --dimension 1536

# Dispatch from that plan (and link Retrieval QA if desired)

scripts/embed_dispatch.sh --plan-preflight-dir var/plan_preflight/<TS>/ \
--qa-dir var/retrieval_qc/<TS>/ \
--skip-unchanged
scripts/monitor_embedding.sh

Note: Dispatcher still runs per‑RID preflight; with --skip-unchanged, it uses reembed-if-changed to avoid unnecessary work.

Acceptance

Dispatcher uses the specified plan-preflight bundle’s ready.txt (or auto‑selects the latest) and prints a green confirmation with its TS.

The full plan‑preflight bundle is archived under var/logs/dispatch/\<DISPATCH_TS>/plan_preflight/; optional QA bundle archived under .../retrieval_qc/.

dispatch_manifest.json captures provider/model/dimension, workers, batch size, plan provenance, git commit, optional QA dir, and mode (reembed-if-changed vs embed).

Per‑RID preflight remains enforced; bad RIDs are skipped with clear reasons.

With --skip-unchanged, unchanged RIDs are skipped via reembed-if-changed.

All outputs are tmux‑friendly; deterministic ordering by RID; no pagers; scripts remain zsh‑safe.

Artifacts to return:

Diffs for scripts/embed_dispatch.sh (and any helper touched).

Tree of var/logs/dispatch/\<DISPATCH_TS>/plan_preflight/ showing the archived report.

Example dispatch_manifest.json.

Snippet from var/logs/dispatcher.out showing source selection, a queued RID, a preflight‑skipped RID, and (if --skip-unchanged) an unchanged‑skipped RID.
