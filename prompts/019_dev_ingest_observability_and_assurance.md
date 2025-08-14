# PROMPT DEV-019 — Ingest Observability & Run-Assurance (Confluence + DITA)

Save as: prompts/019_dev_ingest_observability_and_assurance.md
Branch: main (no feature branches)

Context (read carefully, do not regress):

Repo already enforces zero IDE linter errors; use our pre-commit / Makefile tools first (don't hand-fix).

ADF is the default for Confluence body format pre-normalization.

Unified paths live under var/ (var/runs, var/data, var/state, var/logs). Ingest is file-based; no DB needed. Retrieval uses Postgres—do not drag DB into ingest.

Traceability exists (page IDs, URLs, attachments). Extend/verify, don't break.

Be surgical: read the code you'll touch; if it's getting complex, refactor in place with tests.

Goals: Make CLI runs visibly trustworthy: live progress, resumability evidence, error transparency, and a final "assurance report."

## To-Dos (max 9)

### 1. Read the code first, map the CLI

Open the current CLI entry points (trailblazer ingest confluence, trailblazer ingest dita, runner) and loggers. List where stdout/stderr, metrics, and NDJSON logs are produced today. Do not change CLI names/flags unless missing—then add minimal flags.

### 2. Rich console progress + heartbeats

Add a Rich (or equivalent) progress panel:

- Overall ingest bar per source (Confluence, DITA) with counts & ETA.
- Per-space (Confluence) and per-folder (DITA) sub-bars.
- A heartbeat line every 30s: {phase, processed, rate(x/s), elapsed, eta, last_api_status, retries}.

Flags: --progress/--no-progress, --no-color.

### 3. Resumability evidence line (delta mode)

At start, print exactly what will happen:
Resuming Confluence since={ISO or none} spaces={N} pages_known={K} estimated_to_fetch≈{M}

When skipping unchanged items, log counts: skipped_unchanged={n}; when re-fetching deltas, log why (updated, deleted, moved).

### 4. Structured NDJSON event log

Emit to var/logs/\<run_id>.ndjson: events space.begin, space.end, page.fetch, page.write, attachment.fetch, attachment.write, metrics.snapshot, heartbeat, warning, error.

Include keys that guarantee traceability: source, space_key, space_id, page_id, title, version, url, attachment_id, attachment_title, mime, sha256, bytes.

### 5. Assurance report (JSON + pretty MD)

At end of each source ingest, write:

var/runs/\<run_id>/<source>/assurance.json and assurance.md with: totals, per-space stats, zero-body pages, non-ADF bodies (Confluence), missing or failed attachments, top 10 largest items, retry stats, error summaries, and a repro command block.

Print path to both in console.

### 6. Attachment completeness checks

For every page with attachments, verify count written == count reported; if mismatch, retry with backoff then log error and continue. Surface a red counter in the progress panel.

### 7. Tests for observability & assurance

Add tests that run smoke ingests against fakes and assert:

- Progress/heartbeat lines appear.
- NDJSON contains expected events/keys.
- assurance.json has correct counters and non-empty sections.

Keep tests offline; no network.

### 8. Docs & guardrails

Update README (short "What you'll see" GIF or text block) and append to prompts/000_shared_guardrails.md a new Non-Negotiable: Observability & Assurance section (console progress, heartbeats, NDJSON, assurance report; zero test failures; no DB in ingest). Do not remove existing guardrails.

### 9. Validation & commit

Run make fmt lint test check-md. Only push when all green. Commit message:
feat(ingest): add live progress, heartbeats, NDJSON event log, and assurance reports for Confluence & DITA

## Acceptance Criteria

- Live progress + heartbeats on both Confluence and DITA ingests.
- NDJSON event log with traceability keys.
- Assurance reports produced with accurate counts & error summaries.
- Zero linter errors, zero test failures.
- No ingest-time DB dependency introduced.
