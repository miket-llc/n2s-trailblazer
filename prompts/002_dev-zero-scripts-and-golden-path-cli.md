# PROMPT FOR CLAUDE — DEV: Zero‑Scripts Non‑Negotiable + Golden Path CLI (Config‑First, Idempotent/Reset, Bespoke N2S)

Execute now. Don't draft a plan. Paste the guardrails verbatim first, then perform each numbered step and paste proofs (commands + outputs).
No assumptions: discover CLI and code structure from the repo at run time (ripgrep), and use those actual names/flags. Keep observability from prior prompts intact.

## 000 — Paste guardrails (verbatim, unchanged)

Open prompts/000_shared_guardrails.md.

Paste its full contents at the very top of your reply, unchanged. (Mandatory.)

## 📁 Prompts directory conventions (enforce before work)

Name: prompts/NNN_slug.md (three‑digit NNN).

Split: only if necessary, use A/B suffixes.

Index: keep prompts/README.md sorted ascending.

Non‑conforming prompts: delete (preferred) or archive under var/archive/prompts/<ts>/.

## ✅ To‑Do Checklist (≤9)

1. Save this prompt properly (numbered), then commit
1. Update the Non‑Negotiables (edit guardrails file + enforce)
1. Discover the current CLI & flags from the repo (no guessing)
1. Design the Golden Path from your code and create a config loader
1. Consolidate flags → config; deprecate/retire unused flags
1. Internalize remaining scripts (delete or shrink to ≤20 LOC wrappers)
1. Idempotence & Reset semantics (don't oversimplify; make it correct)
1. Smoke run with config‑first (no complex flags) + proofs
1. Proof‑of‑work & Definition of Done

[Full detailed steps content follows as provided in original prompt...]
