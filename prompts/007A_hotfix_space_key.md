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

# PROMPT DEV-007A — Hotfix space_key Resolution & Artifact Correctness (CODE) ≤9 to-dos

Work on: main only (no feature branches)
Do not introduce any DB usage on the ingest path.

## To-Dos (max 9)

### 1. Resolve space_key reliably for every page

In the Confluence ingest step:

- Build a memoized space map {space_id -> space_key}. On first encounter of an unknown space_id, call v2 GET /wiki/api/v2/spaces/{id} to obtain key and cache it.
- Fallback if API key not found: parse from page.url using regex /spaces/([A-Z0-9]+)/pages/.
- If neither works, set space_key="**unknown**" and log a warning once per id.

### 2. Populate space_key in all outputs

Ensure space_key is included in:

- NDJSON records written to var/runs/<RID>/ingest/confluence.ndjson
- Structured logs (event="confluence.page")
- pages.csv (first column)
- Never emit "space_key":"unknown"; use "**unknown**" only as a last-resort and increment a counter.

### 3. Counters & summary

Track space_key_unknown_count per run and per space in summary.json.
If > 0, add "warnings":["space_key_unknown_detected"] and print a single console warning at end of run.

### 4. Pretty progress line includes real key

Format: \<SPACE_KEY> | p=\<page_id> | "<title>" | att=<n> | \<updated_at>.
Throttle with --progress-every N (existing flag if present; otherwise add it).

### 5. Unit tests

test_space_key_map_and_fallback.py:

- Given space_id="27787275" and URL /spaces/PM/pages/... → space_key=="PM" even if map is empty.
- Given mocked v2 response for {id:27787275,key:"PM"} → uses map, not regex.
- If both fail → **unknown** and counter increments.

### 6. Determinism

Sorting/ordering unaffected by key resolution.
Ensure CRLF→LF normalization remains in downstream normalize pipeline.

### 7. Zero DB on ingest path

Verify no trailblazer.db.\* imports execute on ingest import/CLI --help. If needed, make DB imports lazy in embed/ask only.
Add test_ingest_import_no_db.py that imports the ingest CLI module and asserts no DB engine creation calls/logs.

### 8. Docs

README > Ingest section: note that space_key is populated from the spaces API with URL fallback; summary warns if any pages could not be mapped.

### 9. Validation & commit

Run make fmt && make lint && make test && make check-md (green, zero IDE errors).
Commit to main: fix(ingest): resolve Confluence space_key via id map with URL fallback; add counters, tests, docs
Push and paste proof-of-work (last 10 lines of each Make step).

## Acceptance

- NDJSON/var/logs/CSVs show real space_key (e.g., PM) for your sample pages.
- space_key_unknown_count == 0 for the tested space (or explicit warning if not resolvable).
- Ingest stays DB-free.
