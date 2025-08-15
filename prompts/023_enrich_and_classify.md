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
```

**Markdown hygiene:** all .md must pass mdformat and markdownlint (e.g., fixes MD032 blanks-around-lists via formatter).

**Secrets hygiene:** placeholders only in repo/prompts; real values only in .env/CI. Secret scanning (e.g., gitleaks) is required in pre-commit.

**Pre-push gate:** tests must pass before pushing to main. Add/keep a pre-push pytest hook.

**Prompt size rule:** keep checklists to ≤9 to-dos (Cursor limit). Split into 004A/004B, etc., when needed.

**Proof-of-work:** in every prompt response, paste the exact commands run and the last ~10 lines of output for make fmt, make lint, and make test.

**Non-regression:** Never relax guardrails or remove stricter lint rules without explicit approval. Future prompts must start by pasting this file unchanged.

Confluence: Cloud v2 + Basic auth. Use v1 CQL only to prefilter when --since is set. Bodies/attachments fetched via v2.

Artifacts immutable: write to var/runs/run-id/phase/…; never mutate previous runs.

## Console UX Policy

Default to pretty, human-readable progress when attached to a TTY; default to JSON only in CI or when stdout is redirected.

Never intermix pretty output and JSON on the same stream. JSON → stdout; pretty/status/progress → stderr.

Always print the run_id at start/end of every command and write a final one-line summary.

Throttle progress updates; no more than 1 line per --progress-every N pages.

Keep the structured event names stable: confluence.space, confluence.page, confluence.attachments.

## Database Non-Negotiables (Global)

- Ingest is DB-free: importing or running any ingest CLI/step MUST NOT connect to, import, or initialize the DB.
- Postgres-first for runtime: Any command that persists or queries embeddings (e.g., `embed load`, `ask`, future retrieval services) MUST require Postgres + pgvector in non-test environments. SQLite is allowed ONLY for unit tests/CI and must be explicitly opted-in.
- Single source of truth: DB_URL MUST be provided in `.env` and used by a single engine factory. No hardcoded defaults that silently fall back to SQLite in dev/prod.
- Preflight required: `trailblazer db check` MUST pass (connectivity + pgvector present) before `embed load` or `ask` run (unless tests explicitly opt-in to SQLite).
- Secrets hygiene: Never print DB credentials in logs; log the host/database name only.

## DB policy

PostgreSQL + pgvector is the required default for any embed/retrieve/ask.

SQLite is tests-only (unit/integration) and must be explicit in tests.

Ingest/normalize must not require a DB.

No silent fallback to SQLite in runtime code paths. Fail fast with an actionable message if Postgres isn't configured.

Provide a single place to diagnose: trailblazer db doctor.

## Additional Global Rules

**Tests:** No merges to main with any failing tests. If tests fail, fix tests or the code; do not comment out or delete tests unless replaced by better coverage in the same PR.

**DB policy:** Ingest & normalize must not require a DB. Postgres/pgvector is only for retrieval/indexing phases; CLI preflights for DB must not gate ingest/normalize.

**Body format:** Confluence default body_format is atlas_doc_format (ADF). Storage/XHTML handling stays for backward compatibility and normalization.

**Traceability:** Always persist id, url, space_id/key/name (if available), version, created_at, updated_at, labels, ancestors/breadcrumbs, attachments (with filenames + download URLs), links, and content_sha256 throughout ingest → normalize.

**Observability:** All long-running CLIs must stream clean, structured progress (banners, per-phase counters, ETA) and print the run_id at completion.

**Cursor limit:** Keep prompts ≤10 to-dos; chunk work if needed.

**No regression:** Before edits, read the module and associated tests; prefer minimal deltas. If complexity is high, refactor in tiny steps with passing tests after each step.

## Non-Negotiable: Observability & Assurance

**Rich Console Progress:** All ingest commands MUST provide Rich-formatted progress with overall/per-space bars, heartbeats every 30s, and colored status indicators. Use `--no-color` to disable.

**Structured Event Logging:** Every ingest run MUST emit structured NDJSON events to `var/logs/<run_id>.ndjson` including: space.begin/end, page.fetch/write, attachment.fetch/write, heartbeat, warning, error with full traceability keys (source, space_key, space_id, page_id, title, version, url, attachment_id, sha256, bytes).

**Assurance Reports:** Every ingest MUST generate `assurance.json` and `assurance.md` with totals, per-space stats, zero-body pages, non-ADF bodies, missing/failed attachments, top 10 largest items, retry stats, error summaries, and reproduction command.

**Attachment Verification:** For every page with attachments, verify count written == count reported; retry with exponential backoff on mismatch; surface red counter in progress panel.

**Resumability Evidence:** When using `--since` or `--auto-since`, display what will happen: pages_known, estimated_to_fetch, skipped_unchanged counts with reasons (updated, deleted, moved).

**Zero Test Failures:** All observability features MUST have offline smoke tests that verify progress/heartbeat output, NDJSON event structure, and assurance report generation without network calls.

**No DB in Ingest:** Event logging and assurance generation MUST NOT require database connectivity - all observability is file-based under var/.

______________________________________________________________________

# PROMPT DEV-023 — Enrichment & Classification (DB-free, pre-embed, graph-ready)

Save as: prompts/023_enrich_and_classify.md
Branch: main
PASTE prompts/000_shared_guardrails.md VERBATIM ABOVE THIS PROMPT. DO NOT MODIFY IT.

## Context for a New Instance (read me first)

Trailblazer: we ingested Confluence (ADF) and DITA (Oxygen) and normalized to Markdown + traceable JSON. All artifacts live under var/ only. Ingest/normalize are DB-free.

Now we add a DB-free enrichment pass that produces classifications, summaries, quality signals, and (optionally) LLM-suggested edges, before embedding.

Downstream (next prompt) we embed into Postgres+pgvector; we will re-embed only docs whose enrichment fingerprint changed.

Non-negotiables: var/ only; zero test failures; ADF stays default upstream; no DB calls here.

## Goals

Enrich normalized docs with:

Rule-based fields (fast, deterministic): path-tags, collections, heuristics, readability, media density.

LLM-optional fields (guarded + budgeted): short summary, keywords, taxonomy labels, suggested edges (+ confidence).

Write new sidecars under var/runs/<RID>/enrich/.

Compute and persist an enrichment_fingerprint per doc so embedding can decide what to re-embed.

## To-Dos (≤9)

### Plan (read first; paste your plan)

List files you'll touch (enricher module, CLI, tests, docs).

Confirm where normalized lives: var/runs/<RID>/normalize/normalized.ndjson.

Confirm outputs will be written to: var/runs/<RID>/enrich/.

### CLI: trailblazer enrich --run-id <RID> (DB-free)

Flags: --llm on|off (default off), --max-docs N, --budget \<tokens|$> (soft), --progress, --no-color.

Reads normalized NDJSON; writes only to var/runs/<RID>/enrich/.

### Rule-based enrichment (fast)

Compute:

collection + path_tags (we already do some in DITA—unify across sources).

readability (chars/word, words/para), heading_ratio, media_density, link_density.

quality_flags: empty_body, too_short, too_long, image_only, etc.

Write one line per doc to enriched.jsonl:

```json
{"id":"…","source_system":"…","collection":"…","path_tags":["…"],"readability":{"wpm":…},"quality_flags":["…"]}
```

### LLM-optional enrichment (guarded)

If --llm on and keys present: produce short summary (≤300 chars), keywords (≤8), taxonomy_labels (your controlled vocab stub), and suggested_edges:

```json
{"from":"<doc_id>","to":"<doc_id|url>","type":"RELATES_TO|REFERENCES|SUPPORTS","confidence":0.0–1.0,"evidence":"…"}
```

Stream suggested edges into suggested_edges.jsonl. Keep confidence and evidence.

### Enrichment fingerprint

Compute a stable enrichment_fingerprint per doc (SHA256 of a canonical JSON that includes: selected enrichment fields + an enrichment_version string).

Write fingerprints.jsonl:

```json
{"id":"…","enrichment_version":"v1","fingerprint_sha256":"…"}
```

This drives selective re-embed later.

### Assurance & observability

Progress (stderr) every N docs: [ENRICH] docs=… rate=…/s elapsed=… eta=… llm_used=….

NDJSON events (stdout): enrich.begin, enrich.doc, enrich.suggested_edge, enrich.end.

assurance.json with counts: {docs_total, docs_llm, quality_flags_counts, suggested_edges_total, duration}; also a .md summary.

### Tests (DB-free)

Rule-based enrichment: collections/path_tags/quality flags deterministic.

Fingerprint determinism (doesn't change if enrichment input unchanged).

LLM path mocked; confidence captured; suggested edges file created.

No DB import allowed.

### Docs

README: "Enrichment" section: when to run (pre-embed), what it writes, fingerprint behavior, and how re-embed decides.

### Validation & commit

```bash
make fmt && make lint && make test && make check-md
```

Commit: feat(enrich): DB-free enrichment + fingerprints + suggested edges (optional)

## Acceptance

trailblazer enrich --run-id <RID> writes enriched.jsonl, fingerprints.jsonl, optional suggested_edges.jsonl, and assurance.json|.md under var/runs/<RID>/enrich/.

No DB calls; tests green.
