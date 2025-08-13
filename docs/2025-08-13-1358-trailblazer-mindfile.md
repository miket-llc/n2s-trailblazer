# Trailblazer Mindfile — 2025-08-13 13:58 (EDT)

**One-liner**\
Trailblazer is our AI-powered knowledge base builder: it ingests Navigate-to-SaaS and Ellucian documentation (Confluence + official docs), organizes everything into a typed graph with embeddings, and makes it easy to query and generate the docs we need.

______________________________________________________________________

## 0) Working Agreements — Shared Guardrails (Global, Non-Negotiable)

These apply to **every** past and future prompt and all work in this repo.

- **Main only.** No feature branches for routine work; commit atomically to `main`.

- **Zero IDE linter errors across all file types.** If the IDE warns and our tools don't, **update tool configs** so the warning disappears permanently. Do **not** waive per-file unless approved.

- **Automate fixes first. Never hand-fix format/lint.** Use the toolchain:

  ```bash
  make setup        # .venv + dev deps + pre-commit
  make fmt          # ruff --fix, black, mdformat for .md
  make lint         # ruff check, mypy, markdownlint
  make test         # pytest -q
  ```

- **Markdown hygiene:** All .md must pass mdformat and markdownlint (e.g., MD032 requires blank lines before/after lists).

- **Secrets hygiene:** Placeholders only in repo & prompts; real values live only in local .env/CI secrets. Secret scanning (e.g., gitleaks) runs via pre-commit.

- **Pre-push gate:** Tests must pass before pushing to main (pre-push pytest hook).

- **Cursor checklist limit:** Keep prompt to-do lists ≤ 9 items. Split into 004A/004B when needed.

- **Proof-of-work:** In every prompt reply, paste the exact commands run and the last ~10 lines of output for make fmt, make lint, and make test.

- **Non-regression:** Do not weaken guardrails, re-enable feature branches, or relax lint rules without explicit approval.

## 1) Mission & Scope (v0)

**Mission.** Build an AI knowledge base that unifies Navigate-to-SaaS and Ellucian documentation, models it as a graph with embeddings, and supports fast retrieval plus on-demand document generation.

**Scope (v0).**

- **Sources:** Confluence Cloud (ellucian.atlassian.net/wiki) now; Ellucian documentation site next.

- **Pipeline:** ingest → normalize → enrich/classify → embed → graph → retrieve → compose/create → audit.

- **Storage:** file artifacts under runs/\<run_id>/<phase>/…; Postgres + pgvector planned.

- **Interface:** CLI-first (trailblazer); service endpoint optional later.

- **Non-goals (v0).** Upstream content editing; real-time streaming; replacing Confluence as the primary authoring tool.

## 2) Current State (as of 2025-08-13 13:58 EDT)

**CLI & Runner**

- `trailblazer ingest confluence` exists and calls the real ingest implementation.

- Runner executes phase list; ingest is wired; normalize is in progress or being finalized (004 series).

**Adapters**

- Confluence Cloud v2 with Basic auth (email + API token).

- Cursor pagination supported; \_links.next/Link header handling; absolute URL normalization.

- v1 CQL used only for delta prefilter (--since), then bodies/attachments fetched via v2.

**Models**

- Page with ids/titles/space ids, timestamps, absolute page URL, attachments.

- Attachment with id, filename, media_type, file_size, download_url.

**Ingest Artifacts (runs/\<run_id>/ingest/)**

- confluence.ndjson: one Page per line.

- metrics.json, manifest.json.

- Body fields currently include body format output from v2. (If both Storage & ADF are present, downstream must branch by representation.)

**Normalize Phase (004 series)**

- Goal: deterministic Markdown from Storage (XHTML/HTML) and ADF JSON, preserving links and attachment references.

- Outputs (runs/\<run_id>/normalize/): normalized.ndjson (with text_md, links[], attachments[], body_repr) + metrics/manifest.

- Determinism rules: CRLF→LF, collapse ≥3 blank lines to 2, ATX headings.

**Tooling (local)**

- `make setup`, `make fmt`, `make lint`, `make test` are the single source of truth.

- Pre-commit: ruff/black/mypy; Markdown formatter/linter (mdformat/markdownlint) should be enabled; secret scanner (gitleaks) required.

- Zero-warnings policy in IDE and CI.

**CI**

- Minimal workflow planned/being added: run `make fmt && make lint && make test` and a no-fix markdown pass on push to main.

**Repo hygiene**

- .gitignore should ignore: runs/, data/, .venv/, .env, caches, .DS_Store.

- configs/dev.env.example must contain placeholders only (no real emails/tokens).

- Any leaked tokens must be revoked & scrubbed from history.

## 3) Data Contracts (Canonical)

### 3.1 Ingest — Confluence NDJSON (one record per line)

```json
{
  "id": "12345",
  "title": "Page Title",
  "space_key": "DEV",
  "space_id": "111",
  "version": 3,
  "created_at": "2025-08-01T00:00:00Z",
  "updated_at": "2025-08-10T12:00:00Z",
  "url": "https://ellucian.atlassian.net/wiki/spaces/DEV/pages/12345/Page+Title",
  "attachments": [{"id":"a1","filename":"file.png","media_type":"image/png","file_size":12345,"download_url":"https://.../download"}],
  "body_repr": "storage | adf | unknown",
  "body_storage": "<p>…</p>",
  "body_adf": { "type": "doc", "content": [ ] }
}
```

### 3.2 Normalize — NDJSON

```json
{
  "id": "12345",
  "title": "Page Title",
  "space_key": "DEV",
  "space_id": "111",
  "url": "https://…",
  "version": 3,
  "created_at": "2025-08-01T00:00:00Z",
  "updated_at": "2025-08-10T12:00:00Z",
  "body_repr": "storage | adf",
  "text_md": "# Page Title\n\nBody in Markdown…",
  "links": ["https://link1", "https://link2"],
  "attachments": [{"filename":"file.png","url":"https://…"}],
  "source": "confluence"
}
```

**Determinism:** identical input → identical output; no environment-dependent formatting.

## 4) Quality Gates & Linters

- **Python:** ruff (lint/fix), black (format), mypy (type check).

- **Markdown:** mdformat (format, e.g., fixes MD032 "blanks-around-lists"), markdownlint (lint).

- **MD032 Quick rule:** a list must be surrounded by blank lines:

  ```md
  Text above

  - item 1
  - item 2

  Text below
  ```

- **Secrets:** gitleaks pre-commit; CI may also run a read-only scan.

- **Pre-push:** runs pytest -q and must succeed.

- **CI:** mirrors local make steps and must be green.

## 5) Immediate Priorities (Short List)

- **Finalize Normalize v1** (Storage first; add ADF support if not already in branch): wire into runner+CLI; add determinism tests.

- **Repo hardening (Prompt 005):** unify markdown config, ensure mdformat/markdownlint/gitleaks in pre-commit, add CI, sanitize dev.env.example, confirm .gitignore.

- **Small live ingest** (safe space, --max-pages 5) to validate NDJSON against real pages.

- **Secret history check:** verify no tokens remain in git history; revoke any that leaked.

- **Mindfile discipline:** keep this doc authoritative; update when contracts/flows change.

## 6) Near-Term Roadmap

- **004A/004B — Normalize (Storage & ADF → Markdown):** complete both paths; golden tests.

- **005 — Embed & Graph:** chunker → pgvector; minimal graph tables (nodes, edges, chunks, chunk_embeddings) + loader.

- **006 — Ask/Generate MVP:** trailblazer ask "<q>" + first generator template (e.g., Implementation Checklist).

- **007 — Delta/Resume:** per-space high-watermarks; --resume flag; idempotent ingest.

- **008 — Attachment mode:** --attachments=download|reference and local cache.

## 7) Decision Log (Concise ADRs)

- **ADR-001:** CLI-first, Python monorepo; phases named by function (not numeric prefixes).

- **ADR-002:** Confluence Cloud v2 for pages/attachments; Basic auth; v1 CQL only for deltas.

- **ADR-003:** Ingest artifact is NDJSON with embedded attachments; outputs are immutable per run.

- **ADR-004:** Normalize produces deterministic Markdown and preserves links/attachments; supports Storage & ADF.

- **ADR-005:** Guardrails enforce main-only, zero IDE errors, automated fixes first, secrets scanning, ≤9 to-dos, and proof-of-work.

## 8) How to Run (Developer Quickstart)

```bash
# 1) Setup
make setup

# 2) Format, lint, test
make fmt && make lint && make test

# 3) Ingest a small sample (requires .env with Confluence credentials)
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --max-pages 10

# 4) Normalize from that run
trailblazer normalize from-ingest --run-id <RUN_ID>
```

**.env (placeholders only):**

```ini
CONFLUENCE_BASE_URL=https://ellucian.atlassian.net/wiki
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=__REPLACE_WITH_LOCAL_ENV__
CONFLUENCE_BODY_FORMAT=storage   # or atlas_doc_format
```

## 9) Appendix — Troubleshooting Notes

- **MD032 (blanks-around-lists):** run `make fmt` (mdformat fixes), or ensure a blank line before/after lists.

- **Auth 401/403:** confirm email/token; verify token permissions; check .env loaded.

- **Pagination stalls:** the v2 client follows \_links.next; check network and backoff logs.

- **Normalization edge cases:** macro blocks/code tabs may need special handlers—collect examples and add incremental converters.
