Title: D8 — Implement embed manifest + diff + conditional re‑embed (skip unchanged)

Context (paste verbatim):
We’ve shipped D1/D2/D3/D4/D6/D7. Now implement D8 to avoid unnecessary re‑embeds. Add a per‑run embed manifest capturing provider/model/dimension, tokenizer & component versions, chunk config, ordered docFingerprints, and a chunkSetHash. Provide a diff command to detect content/config changes, and a reembed-if-changed command that uses preflight and skips work when unchanged (unless --force). Write artifacts under var/ only; do not touch DB schema. Before acting, open and follow prompts/000_shared_guardrails.md. The canonical operator flow and proofs live in the Trailblazer mindfile (plan files, preflight, monitor, provider/dimension SQL).

Guardrails (do first):

Postgres‑only ops; no schema edits in this PR.

No pagers: PAGER=cat, LESS=-RFX.

Scripts zsh/tmux‑safe; core logic in the CLI.

Deterministic hashing; pin tokenizer version and include it in the manifest.

Tasks:

Manifest writer

After a successful embed for <RID>, write var/runs/<RID>/embed/manifest.json with fields:
runId, timestamp, gitCommit, provider, model, dimension, tokenizer{name,version}, enricherVersion, chunkerVersion, chunkConfig{maxTokens,minTokens,preferHeadings}, docFingerprints[], chunkSetHash.

docFingerprints[] are taken from Enrich (fingerprint.doc) for docs actually embedded.

chunkSetHash = sha256 over ordered (chunk_id, token_count, content_hash).

Diff command

trailblazer embed diff --run <RID> \[--against last|<path>\] [--format json|md].

Compare current state (enrich + chunk artifacts + resolved config) to the chosen manifest.

Output JSON/MD to var/delta/<RID>/<TS>/.

Reasons: CONTENT_CHANGE, PROVIDER_CHANGE, MODEL_CHANGE, DIMENSION_CHANGE, TOKENIZER_CHANGE, CHUNKER_CHANGE, CHUNK_CONFIG_CHANGE.

Conditional re‑embed

trailblazer embed reembed-if-changed --run <RID> [--force].

Runs trailblazer embed preflight --run <RID> ….

Runs trailblazer embed diff --run <RID> ….

If changed=false and --force not set → skip with a single‑line log and exit 0.

If changed=true → proceed with embed and write a new manifest.

Preflight advisory (non‑blocking)

If a prior manifest exists, add a delta section to preflight/preflight.json with changed and reasons.

Tests

Unit tests for manifest formation and deterministic hashing.

Unit tests for each reason in diff.

Integration tests:

A → Embed → Manifest; B → re‑run with no changes → diff says unchanged → reembed‑if‑changed skips.

Change dimension → diff reasons include DIMENSION_CHANGE → reembed‑if‑changed proceeds.

Change a doc’s content → diff reasons include CONTENT_CHANGE → proceeds.

Acceptance:

Running embed twice with identical inputs produces the same manifest.json and a second run is skipped by reembed-if-changed.

Any material change produces changed=true with the correct reason(s) and proceeds to embed.

All outputs are written under var/, are tmux‑friendly, and deterministic.

Artifacts to return:

Diffs for CLI modules and any helpers.

One example manifest.json, a diff.json/diff.md, and a log snippet showing a skip.

Test outputs (brief) proving unchanged vs changed paths.
