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

# PROMPT 013B (Amendment) — DITA Links & Normalize + Metadata/Context Capture ≤9 to-dos

Save as (update in place): prompts/013B_dita_links_and_normalize.md
Work on: MAIN ONLY
Before you start: paste prompts/000_shared_guardrails.md verbatim at the top (do not modify).
Safety: Review the code paths you'll touch; be surgical unless a tiny refactor reduces risk. ZERO test failures, ZERO IDE linter errors, DB-free ingest, ADF default for Confluence unchanged, no regressions to 013A outputs.

## To-Dos (max 9)

### Link extraction (no network; unchanged scope but stricter typing)

From each topic/map XML, extract outbound refs and classify:

<xref href>, <xref keyref>, <link href> → external or DITA internal.

conref, conkeyref → structural edges (write to edges.jsonl with type:"CONREFS").

Normalize URLs (strip tracking; keep #anchors). Resolve internal to our IDs (topic:<relpath>[#id], map:<relpath>).
Output: runs/<RID>/ingest/links.jsonl (one edge per line) with fields:
from_page_id, from_url:null, target_type:"external|dita|confluence", target_page_id|null, target_url, anchor|null, text|null, rel:"links_to".

### Aggregate labels and metadata from XML (prolog) and map context

For each DITA doc: capture and dedupe all applicable fields:

From <prolog><metadata>: keywords, audience, product, platform, otherprops, resourceid/@appname, critdates (created/modified), author/authorinformation (names only), and any <data> pairs (key/value).

From map context (edges/breadcrumbs produced in 013A): nearest map title(s) and keydefs in scope (names only).

Normalize to:

labels[] (strings) — include all tag-like values (keywords, audience, product, platform, otherprops, keydefs).

meta{} (object) — structured fields: {audience, product, platform, keywords, otherprops, resource_app, critdates:{created,modified}, authors:[...], map_titles:[...]}.

### Derive directory-based context (path clues)

From source_path under data/raw/dita/ellucian-documentation/...:

Compute collection = first subfolder under ellucian-documentation/ (e.g., gen_help, esm_release, stu_help, etc.).

Compute path_tags[] = unique path segments (lowercased, safe-slugged), excluding common stopwords (docs, images, assets, common, master).

Add collection to meta and append path_tags into labels (dedup).

Keep both fields alongside XML-derived labels (do not overwrite).

### Write metadata sidecar (compact, one line per doc)

New file runs/<RID>/ingest/meta.jsonl with:

```json
{"page_id":"topic:...","collection":"gen_help","path_tags":["gen","help","release"],"labels":["oxygen","dita","product-docs", "..."],"meta":{"audience":"implementer","product":"Navigate","platform":"SaaS","keywords":["..."],"otherprops":{"status":"approved"},"resource_app":"...", "critdates":{"created":"...","modified":"..."}, "authors":["..."], "map_titles":["Plan Map","..."]}}
```

Note: don't duplicate heavy values already present in dita.ndjson—this sidecar is the roll-up.

### Counters in summary.json (augment, don't break)

Update runs/<RID>/ingest/summary.json to include:

labels_total, meta_records (count of lines in meta.jsonl), and keep existing links\_\* counters.

Emit a final structured log event ingest.dita_meta_summary with counts and top 10 label terms.

### Normalize DITA → Markdown (deterministic; preserve traceability + context)

Converter rules (unchanged + additions):

Titles → ATX #, paragraphs, lists, fenced code, notes → blockquote, inline b/i/u/code → md equivalents.

Inline xrefs: when resolvable → markdown link; else keep text + URL in parentheses.

Media: ![alt](filename) if filename known, else placeholder ![image](#).

Newlines normalized (CRLF→LF); collapse ≥3 blanks to 2.
Normalized record (merged with your existing structure) must include:

```css
{ id, source_system:"dita", url:null, body_repr:"dita", text_md,
  links:[...], attachments:[{filename,url:null}], labels:[...],
  breadcrumbs:[...], collection:"...", path_tags:[...], meta:{...} }
```

Do not drop any of these fields.

### Tests (offline; add where missing)

Prolog metadata: fixture topic with audience/product/platform/keywords/otherprops/resourceid/critdates/authors → expect values in meta.jsonl and normalized record.

Directory clues: given source_path under ellucian-documentation/gen_help/... → collection:"gen_help" and expected path_tags[]; ensure dedupe with XML labels.

Map context: provide minimal map+topic fixtures → map_titles appear in meta and breadcrumbs unaffected.

Normalization determinism: headings/lists/code/notes and link/media behavior.

No regressions to existing link extraction tests and counters.

### Docs

README "DITA ingest (metadata & context)": document meta.jsonl, collection/path_tags derivation, and how labels are formed (XML + directory). Provide jq examples to list top labels and to filter by collection/path tag.

### Validation & commit (product-grade)

```bash
make fmt && make lint && make test && make check-md
```

All green, no warnings. Commit to main:
feat(ingest-dita): metadata/context capture (meta.jsonl), directory-derived labels, normalized meta fields; tests & docs
Paste proof-of-work (last ~10 lines of each Make step) in your reply.

## Acceptance (must all pass)

runs/<RID>/ingest/meta.jsonl exists with one compact line per DITA doc; values match XML prolog + directory hints + map context (titles).

runs/<RID>/ingest/summary.json includes labels_total, meta_records, and prior link counters.

runs/<RID>/normalize/normalized.ndjson for DITA preserves labels, meta{}, collection, and path_tags, in addition to links/attachments/breadcrumbs.

No regressions to 013A artifacts; Confluence ingest/normalize untouched; ingest stays DB-free; all tests pass.
