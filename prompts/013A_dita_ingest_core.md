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

Artifacts immutable: write to runs/run-id/phase/…; never mutate previous runs.

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

# PROMPT DEV-013A — DITA Ingest Core (topics/maps, media, hierarchy, labels) ≤9 to-dos

Save as: prompts/013A_dita_ingest_core.md
Work on: MAIN ONLY
Before you start: paste the entire prompts/000_shared_guardrails.md verbatim at the top (do not modify).
Context: You are adding a DITA/Oxygen Content Fusion ingest adapter that reads from data/raw/dita/ellucian-documentation/… and writes graph-ready artifacts under runs/<RID>/ingest/. Ingest remains DB-free.

MANDATORY review & plan (not counted): List files you'll touch, outline a tiny change plan, and confirm no regressions (Confluence ingest/normalize untouched; ADF default intact).

To-Dos (max 9)
Scanner & config (data roots)

Add a DITA ingest entry point: trailblazer ingest dita --root data/raw/dita/ellucian-documentation \[--include <glob>\] \[--exclude <glob>\].

Default include: `**/*.dita`, `**/*.xml` with DITA doctype, `**/*.ditamap`.

Skip archives (\*.zip) by default (print a warning with count). Do not unzip automatically.

Topic/Map parser (no network)

Implement src/trailblazer/adapters/dita.py with helpers using lxml (or stdlib xml.etree if you prefer):

parse_topic(path) -> TopicDoc (id, title, doctype, body xml, prolog metadata, images, xrefs, keyrefs, conrefs).

parse_map(path) -> MapDoc (map title, keydefs, hierarchy of refs).

Stable IDs & source fields

topic id: topic:\<relpath_without_ext>\[#<element-id-if-present>\] (always lowercased path separators as /).

map id: map:\<relpath_without_ext>.

Include source_path (relative under data/raw/dita/ellucian-documentation), source_file_sha256, and doctype (topic|concept|task|reference|map) in records.

Write dita.ndjson (one record/topic or map)

Use the canonical record shape we defined (from my last message): source_system:"dita", id, title, source_path, source_file_sha256, doctype, timestamps (from filesystem), body_repr:"dita", body_dita_xml (optionally truncated if huge), labels (from <prolog><metadata> & keywords), ancestors (if in a map), attachments (images), counts, content_sha256.

Keep the record compact; large XML can be truncated or omitted if you include source_path+sha.

Media & attachments

Extract inline media positions (order) from <image href>, <object>, etc.

Write ingest_media.jsonl with:
{"page_id":"topic:…","order":N,"type":"image|file|media","filename":"...","attachment_id":null,"download_url":null,"context":{"xml_path":"/topic/body/p[2]/image[1]","alt":"..."}}.

Write attachments_manifest.jsonl with: {"page_id":"topic:…","filename":"…","media_type":"…|null","file_size":\<int|null>,"download_url":null,"sha256":null}. (No bytes downloading in ingest.)

Hierarchy edges & breadcrumbs

For each \*.ditamap, write edges.jsonl entries:
{"type":"PARENT_OF","src":"map:…","dst":"topic:…"} for each included topic; nested maps create a chain.

Write breadcrumbs.jsonl: {"page_id":"topic:…","breadcrumbs":\["<Map title>","…","<Topic title>"\]}.

Labels/tags

From <prolog><metadata>, <keywords>, and common attributes (@audience, @product, @platform, otherprops), compute a labels[] set on the record.

Also write labels.jsonl per label: {"page_id":"topic:…","label":"…"}

Add edges.jsonl typed label edges: {"type":"LABELED_AS","src":"topic:…","dst":"label:<label>"}.

Summary & progress

Extend per-run summary.json with: pages, attachments, media_refs_total, labels_total, ancestors_total, sources:["dita"].

Print stage banners to stderr and write structured JSON progress to stdout (don't intermix).

Tests & commit

Unit tests for XML parsing (topic + map), media extraction, labels, hierarchy edges, and NDJSON record integrity (including source_path & sha).

make fmt && make lint && make test && make check-md → all green.

Commit to main:
feat(ingest-dita): topics/maps → dita.ndjson + media/attachments + hierarchy/labels + summary

Acceptance

runs/<RID>/ingest/dita.ndjson exists with one line per topic/map (fields as specified).

Sidecars present: attachments_manifest.jsonl, ingest_media.jsonl, edges.jsonl, labels.jsonl, breadcrumbs.jsonl, summary.json.

Ingest remains DB-free; Confluence ingest unaffected.
