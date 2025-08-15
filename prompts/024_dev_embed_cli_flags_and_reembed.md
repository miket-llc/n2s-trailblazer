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

______________________________________________________________________

## Guardrails Addendum (OPS-EMBED-ALL-FINAL)

DB Policy: There is ONE runtime DB: Postgres + pgvector. No SQLite anywhere in runtime or ops.

No Pagers: Set PAGER=cat and LESS=-RFX in the session; pass pager-off flags if tools support them. All output must stream; do not invoke interactive pagers.

---

# DEV-024 — Embed CLI Flags (--provider/--model/--dimensions) + Re-embed Controls

## Context for a New Instance
Pipeline: ingest → normalize → enrich → chunk→embed → retrieve.

Enrichment is complete across all runs (artifacts under var/runs/<RID>/enrich/).

We previously embedded with dummy vectors; now we need to re-embed with a real provider (e.g., OpenAI).

DB policy: Postgres + pgvector only (no SQLite).

Workspace: var/ only.

Goal (this patch): expose clean flags on embed load so ops can switch providers/models/dimensions, force full re-embed when needed, and (optionally) get a cost preview for API providers.

## To-Dos (≤9)

### 1) Read before changing (paste outputs)
```bash
trailblazer embed load --help (current flags)
```

### 2) Confirm schema: chunk_embeddings has uniqueness by (chunk_id, provider) (ideal). If it's only by chunk_id, note that and include a purge path in docs.

### 3) Add/confirm flags on embed load
- `--provider {openai,sentence_transformers,dummy}` (default stays dummy only in tests)
- `--model <STRING>` (e.g., text-embedding-3-small, BAAI/bge-small-en-v1.5)
- `--dimensions <INT>` (optional; e.g., 512/1024 for OpenAI/pgvector storage control)
- `--changed-only` (existing) and `--reembed-all` (force re-embed regardless of fingerprints/content hash)

### 4) Provider wiring
- **OpenAI**: read OPENAI_API_KEY; honor --model/--dimensions; batch safely; surface rate-limit retries.
- **Sentence-Transformers**: load by name (--model) and respect GPU/CPU env (no network in tests).
- **Dummy**: unchanged; tests only.

### 5) Re-embed behavior
- If `--reembed-all`: ignore fingerprints/content hash and overwrite provider rows (if uniqueness is (chunk_id, provider), this means re-write same provider rows; if uniqueness is chunk_id only, first DELETE rows for that provider/doc).
- If `--changed-only`: embed rows missing for the current provider or where fingerprints changed.

### 6) Assurance additions
Include `{"provider": "...", "model": "...", "dimensions": N, "reembed_all": bool, "docs_total", "docs_embedded", "docs_skipped", "chunks_total", "chunks_embedded", "chunks_skipped", "duration_seconds"}` in embed_assurance.json; print a one-line stderr summary.

### 7) Cost preview (optional but useful)
Add `--dry-run-cost` to estimate tokens ~ sum(len(text_md)//4) for the run; print per-run token total and estimated cost for OpenAI models. (Do not call the API in dry-run; this is a local estimate.)

### 8) Progress & logs
Keep stderr progress `[EMBED] docs=… chunks=… rate=…/s elapsed=… eta=… skipped=…`

NDJSON stdout events: `embed.begin`, `doc.upsert`, `chunk.write`, `embed.write`, `embed.skip`, `embed.end`, `error`.

### 9) Tests
- CLI help snapshots include new flags.
- Unit: provider configuration picks up --model/--dimensions.
- Idempotency: --changed-only skips stable docs; --reembed-all forces re-write.
- If schema uniqueness is (chunk_id, provider), confirm both dummy & openai can coexist; if not, test purge path.

## Docs & commit
README "Embedding" gets a table of providers/models/dim examples and the re-embed options (changed-only vs reembed-all).

`make fmt && make lint && make test && make check-md` → green.

Commit:
`feat(embed): add --provider/--model/--dimensions + --reembed-all + cost preview; assurance & docs`

## Acceptance
`embed load --help` shows the new flags; OpenAI/ST providers work; re-embed behaves as documented; tests green.
