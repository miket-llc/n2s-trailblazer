# PROMPT FOR CLAUDE — Quality Hotfix: 100% Enrich Coverage, Orphan Chunk = 0, Traceability Chain Repaired (Bespoke N2S, Config‑First, Postgres‑Only)

Execute now. Do not draft a plan. Paste the guardrails verbatim first, then perform each numbered step and paste the proofs (commands + outputs).
No assumptions: discover CLI flags, schema, table/column names from the actual codebase (ripgrep) and database (psql) at run time and use those values.
Zero complex shell: any logic belongs in the app/CLI; use only small shell invocations to call the CLI and introspection.

## 000 — Paste guardrails (verbatim, unchanged)

Open prompts/000_shared_guardrails.md.

Paste its full contents at the very top of your reply, unchanged. (Mandatory.)

## 📁 Prompts directory conventions (enforce before work)

Name: prompts/NNN_slug.md (three‑digit NNN).

Split: only if necessary; use A/B suffixes.

Index: maintain prompts/README.md sorted ascending.

Non‑conforming prompts: delete (preferred) or archive to var/archive/prompts/<ts>/.

## ✅ To‑Do Checklist (≤9 items)

1. Save this prompt properly (numbered) and commit
1. Pre‑flight: env, Postgres‑only, no pagers, kill stale workers; discover real CLI
1. Load the latest failing assurance as ground truth & identify targets
1. Enrich coverage → 100% (repair missing only; no rework on completed)
1. Orphan chunk = 0 (detect via FK introspection; relink or rebuild, never lose)
1. Traceability: 0 issues (audit end‑to‑end keys; backfill from source; proof)
1. Re‑run assurance gates and assert PASS (all three failures fixed)
1. Observability proofs (live status + NDJSON + samples)
1. Proof‑of‑work & Definition of Done (commit)

[Full detailed steps as provided in original prompt...]
