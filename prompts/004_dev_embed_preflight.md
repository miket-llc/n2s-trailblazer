itle: Integrate embed preflight into dispatcher + add env capture and provider/dimension health to monitor (D4)

Context (paste verbatim):
We just landed trailblazer embed preflight and chunk/embed assurance. Chunk is a materialized step that writes var/runs/<RID>/chunk/chunks.ndjson, and preflight blocks embed unless the run is healthy. We need the dispatcher to call preflight for each RID and skip failures, and we want the monitor to surface provider/dimension drift alongside EWMA/ETA. All ops guardrails live in prompts/000_shared_guardrails.md. The canonical flow and operator proofs (preflight JSON, assurance files, SQL check) are defined in the Trailblazer mindfile—follow these exactly.

Guardrails (DO FIRST):
Open and follow prompts/000_shared_guardrails.md. Constraints: Postgres only, no pagers (PAGER=cat, LESS=-RFX), no destructive ops, deterministic output. Keep shell scripts set -euo pipefail and zsh‑safe.

Tasks:

Dispatcher gate

Edit scripts/embed_dispatch.sh:

Before enqueuing a run <RID>, execute:
trailblazer embed preflight --run "$RID" --provider openai --model text-embedding-3-small --dim 1536

If preflight fails, skip the RID and append a red, single‑line log to var/logs/dispatcher.out explaining why (include the path to preflight.json if it exists).

On success, enqueue as before.

Worker env capture

On worker start (wherever we spawn the embed process), write var/logs/embed_env.$PID.json containing:

{
"pid": <PID>,
"provider": "openai",
"model": "text-embedding-3-small",
"dimension": 1536,
"batch_size": <resolvedBatch>,
"workers": <resolvedWorkers>,
"timestamp": "<iso8601>",
"rid": "<RID or null if pooled>"
}

Monitor health

Edit scripts/monitor_embedding.sh:

Keep the existing active_workers / EWMA / ETA display.

Add a compact table produced by:

SELECT provider, dimension, COUNT(\*) AS n
FROM public.chunk_embeddings
GROUP BY 1,2
ORDER BY 1,2;

If more than one (provider, dimension) row exists, print a visible ⚠️ “dimension drift detected” line.

Acceptance:

Dispatcher skips RIDs that fail preflight and logs the reason to var/logs/dispatcher.out.

Successful dispatch writes per‑worker embed_env.<PID>.json files.

Monitor shows progress and the (provider, dimension, n) table; drift triggers a ⚠️ warning.

All outputs are tmux‑friendly (no paging), zsh‑safe, idempotent.

Artifacts to return:

Diffs for scripts/embed_dispatch.sh and scripts/monitor_embedding.sh.

A captured var/logs/dispatcher.out snippet showing one skipped RID and one enqueued RID.

A sample var/logs/embed_env.<PID>.json.

A screenshot or copied output of the monitor showing the new provider/dimension table.

Reminders:

Keep changes small and self‑contained.

Do not touch database schema or embedding logic in this PR.

Adhere to the proofs bundle defined in the mindfile for validation.
