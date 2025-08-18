Title: D6 Mindfile & Guardrails Update + D6.1 Terminology Alignment (dimension, chunk config)

Context (paste verbatim):
We've landed D1/D2/D3/D4: embed preflight, chunk & embed assurance, dispatcher gating, provider/dimension health in monitor, and enrich stabilization (heading‑aware chunking + quality distribution). The mindfile still claims "Chunk handled within embed load path," which is stale. We must update it to Chunk (materialize), document the new artifacts & proofs, and embed the preflight/quality gate into the operator flow. Also standardize on the term dimension (singular) across CLI output, JSON artifacts, scripts, and SQL; and align chunk config naming across chunk_hints and chunk_assurance. Before acting, open and follow prompts/000_shared_guardrails.md. Use Postgres only; no pagers (PAGER=cat, LESS=-RFX); deterministic output. The current mindfile is the source of truth for ops flow and queries—update it and the shared guardrails precisely.

Guardrails (do first):

Read prompts/000_shared_guardrails.md; keep the “No SQLite in ops,” “No destructive ops without backups,” and “No pagers” rules intact.

Keep changes small, self‑contained, diff‑friendly; run make check-md if available.

Tasks:

Mindfile edits (2025-08-18-0839_trailblazer-mindfile.md)

Canonical Pipeline: switch step 4/5 to Chunk (materialize) → preflight‑gated Embed, with artifact paths.

Directory Conventions: add

var/runs/<RID>/chunk/chunks.ndjson

var/runs/<RID>/chunk/chunk_assurance.json

var/runs/<RID>/preflight/preflight.json

Clarify that embed_assurance.json references chunk assurance.

Reset & Re‑Embed: add explicit preflight step & acceptance (docs/chunks > 0 via assurance).

Known Pitfalls: add Zero‑work embeds → always preflight.

One‑Glance Checklist: add preflight passed; assurance present.
Use concise diffs and examples; keep the style consistent with current sections.

Shared guardrails (prompts/000_shared_guardrails.md)

Add: “Run trailblazer embed preflight --run <RID> --provider openai --model text-embedding-3-small --dimension 1536 before dispatch.”

Add: tokenizer pinning & version echoing requirement; quality distribution gate defaults (minQuality=0.60, maxBelowThresholdPct=0.20).

Add: canonical SQL for provider/dimension sanity:
SELECT provider, dimension, COUNT(\*) AS n FROM public.chunk_embeddings GROUP BY 1,2 ORDER BY 1,2;

Add: operator proofs bundle list (preflight JSON, chunk assurance, embed assurance, monitor snapshot, provider/dimension SQL output).

Terminology alignment (D6.1)

JSON/CLI/scripts: standardize “dimension” (singular) everywhere. If your current preflight JSON uses dimensions, either:

Switch to dimension now and keep a transitional alias so old tools don’t break; or

Keep dimension as the primary field and mirror dimensions for one release (deprecated).

Chunk config naming:

Decide on canonical names (e.g., maxTokens, minTokens, targetTokens).

In chunk_assurance.json, surface both canonical names and the legacy fields for one release; log a deprecation note.

Update CLI help strings and monitor output to use dimension consistently.

Acceptance:

Mindfile clearly shows Chunk (materialize) and preflight‑gated Embed; includes the new artifact paths and proofs.

Guardrails mention preflight, quality defaults, tokenizer versioning, and provider/dimension SQL.

Running trailblazer embed preflight prints dimension: 1536 in output (and the JSON uses dimension as the primary field).

Monitor’s provider/dimension table and dispatcher logs use dimension.

grep -R "\\bdimensions\\b" src scripts returns no policy‑breaking uses (except transitional alias handling you explicitly documented).

Artifacts to return:

Diffs for 2025-08-18-0839_trailblazer-mindfile.md and prompts/000_shared_guardrails.md.

Example of updated preflight/preflight.json with dimension.

Screenshot/snippet of monitor output showing the (provider, dimension, n) table.

Notes:

Keep the doc edits surgical; do not rewrite unrelated sections.
