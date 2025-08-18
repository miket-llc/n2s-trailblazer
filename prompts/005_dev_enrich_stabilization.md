Title: D3 Enrich Stabilization — schema signals, quality gating, chunker integration

Context (paste verbatim):
We’ve hardened Chunk and Embed (preflight + assurance) and gated dispatch. Now we must stabilize Enrich so the chunker produces consistent, heading‑aware, token‑bounded chunks and so preflight can gate on quality. Enrich will augment enriched.jsonl with fingerprint, section_map, chunk_hints, quality metrics, and a quality_score. The chunker will use these to split. The preflight should surface the quality distribution and fail if too many docs are below threshold. Before acting, open and follow prompts/000_shared_guardrails.md. Ops and canonical flow are defined in the Trailblazer mindfile; reflect the materialized Chunk and proofs bundle.

Guardrails (do first):

Postgres only; do not touch schema in this PR.

No pagers: PAGER=cat, LESS=-RFX.

Zsh/tmux‑safe scripts; set -euo pipefail.

Keep changes small, self‑contained, and well‑tested.

Tasks:

Enricher schema & scoring

Extend the Enricher to emit (per‑doc) fields: fingerprint {doc, version}, section_map with {heading, level, startChar, endChar, tokenStart, tokenEnd}, chunk_hints {maxTokens, minTokens, preferHeadings, softBoundaries[]}, quality{…}, quality_score.

Add flag --min-quality (default 0.60) and --max-below-threshold-pct (default 0.20). Compute distribution stats and write them into the enricher run log.

Unit test: schema present; scoring stable on a golden sample; fingerprint unchanged if only whitespace changes.

Chunker integration

Update chunker to require tokenizer, prefer heading‑aligned splits, and respect chunk_hints (maxTokens=800, minTokens=120 defaults).

On overflow segments, split at nearest softBoundaries or heading; else token‑count cut.

Record per‑chunk token counts.

Assurance & preflight wiring

Extend chunk_assurance.json with quality distribution: {p50, p90, belowThresholdPct, minQuality, maxBelowThresholdPct}.

Update embed preflight to parse quality distribution (from assurance if available; else compute from enriched) and fail if belowThresholdPct > maxBelowThresholdPct.

CLI surface

trailblazer enrich run --run <RID> [--min-quality 0.60 --max-below-threshold-pct 0.20]

trailblazer chunk run --run <RID> [--max-tokens 800 --min-tokens 120] (if not already present; ensure defaults match hints).

Ensure help text explains gating logic.

Tests

Unit tests for enricher schema + scorer and chunker split behavior (heading‑aligned).

Integration test that:
a) enrich → chunk → preflight passes on a healthy sample;
b) raising --min-quality forces preflight fail with a clear message.

Acceptance:

A real RID completes enrich → chunk → preflight with artifacts:

var/runs/<RID>/enrich/enriched.jsonl containing the new fields.

var/runs/<RID>/chunk/chunks.ndjson with heading‑aligned chunks.

var/runs/<RID>/chunk/chunk_assurance.json including quality distribution.

trailblazer embed preflight --run <RID> fails if belowThresholdPct exceeds threshold and succeeds otherwise.

All outputs are tmux‑friendly and deterministic (token counts stable across runs given pinned tokenizer).

Artifacts to return:

Diffs for enricher, chunker, and CLI wiring.

One enriched.jsonl sample entry showing the new fields.

A chunk_assurance.json sample with quality distribution.

Preflight output for: (1) a passing case, (2) a failing case.

Notes:
Do not modify DB schema or embedding logic in this PR. Once this lands, we’ll update the mindfile (D6) and decide whether to apply the optional DB dimension guard (D5) based on monitor observations.
