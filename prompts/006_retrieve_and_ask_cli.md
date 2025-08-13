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

______________________________________________________________________

# PROMPT 006 — Retrieval & `ask` CLI (dense first, offline-safe) ≤9 to-dos

**Save as:** `prompts/006_retrieve_and_ask_cli.md`
**Branch policy:** **MAIN ONLY**
**Before you start:** paste the entire content of `prompts/000_shared_guardrails.md` **verbatim at the top** of this prompt. **Do not modify** the guardrails in this task.
**Non-regression:** Do **not** weaken existing lint/CI/README/normalize/embed work. Keep zero IDE linter errors.

______________________________________________________________________

## Goal

Provide a deterministic, offline-safe **dense retrieval** over the `chunk_embeddings` created in 005B and expose it via:

- A small retrieval module (query → embedding → top-k chunks).
- A **CLI** command: `trailblazer ask "<question>"` with options.
- Artifacts (JSON/JSONL) under `runs/<run_id>/ask/…` for traceability.
- Tests that run **without network** (default **dummy** embedder).

Hybrid (keyword) and rerankers can be layered later (006B).

______________________________________________________________________

## To-Dos (max 9)

- [ ] **Retrieval core (dense).**
  Create `src/trailblazer/retrieval/dense.py` with:

  - `embed_query(text: str, provider) -> np.ndarray` using the **same provider** selection as 005B (default `"dummy"`; no network).

  - `cosine_sim(a, b) -> float` and `top_k(query_vec, candidates, k)` helpers.

  - `fetch_candidates(db, provider, limit=N)` that returns `(chunk_id, doc_id, text_md, embedding, title, url)` rows.

    - **Postgres + pgvector** path: push cosine search into SQL (`embedding <=> :qvec`), fallback to Python if pgvector not available.
    - **SQLite** path: read JSON embeddings, compute cosine in Python.

  - Deterministic ordering ties by `(similarity DESC, doc_id, chunk_id)`.

- [ ] **Aggregator & packing.**
  Create `src/trailblazer/retrieval/pack.py`:

  - `group_by_doc(hits, max_chunks_per_doc: int)` → stable grouping.
  - `pack_context(hits, max_chars: int)` → join with separators until budget; never cut inside fenced code blocks.
  - Return both a **hits list** (with scores + metadata) and a **context string**.

- [ ] **Ask CLI.**
  Add `trailblazer ask "<question>"`:

  - Options: `--top-k 8`, `--max-chunks-per-doc 3`, `--provider dummy`, `--max-chars 6000`, `--format text|json`, `--out <dir>` (default `runs/<run_id>/ask/`), `--db-url` (optional override).

  - Behavior:

    - Resolves provider, embeds query, performs retrieval, groups & packs.
    - Writes `hits.jsonl` (one hit per line), `summary.json` (query, provider, counts, timings), and `context.txt`.
    - If `--format=text`, print a short console view (top N with titles/urls + the packed context header). If `json`, print a JSON summary to stdout.

- [ ] **DB util (reuse 005B).**
  Expose a simple session factory in `src/trailblazer/db/engine.py` if not already present: `get_session(DB_URL)` and metadata import for tables. Do **not** change existing table names or schemas.

- [ ] **Runner (optional wiring).**
  You may add a phase alias `retrieve` that calls the same code and drops artifacts into `runs/<run_id>/ask/`. Keep `ask` as the primary entrypoint.

- [ ] **Tests (offline; SQLite).**

  - `test_dense_retrieval_order.py`: build a tiny SQLite DB with two docs, three chunks each, and **dummy** embeddings; assert deterministic ranking and tie-break rules.
  - `test_pack_context.py`: verify grouping per doc and `max_chars` budget, and that code blocks are not split.
  - `test_ask_cli_smoke.py`: run CLI against the temp DB; assert files `hits.jsonl`, `summary.json`, `context.txt` are produced; check counts and a known top hit.

- [ ] **README: Ask usage.**
  Add a "**Ask (dense retrieval)**" section with examples:

  ```bash
  # DB initialized and embeddings loaded from 005B
  trailblazer ask "How do I configure SSO in Navigate to SaaS?" --top-k 8 --max-chunks-per-doc 3 --provider dummy
  # artifacts → runs/<RUN_ID>/ask/
  ```

  Note: default provider is **dummy** for offline safety; configure `EMBED_PROVIDER` and `DB_URL` for production.

- [ ] **Validation & commit.**
  Run: `make fmt && make lint && make test && make check-md`.
  Paste proof-of-work (commands + last ~10 lines).
  Commit to **main** with: `feat(retrieval): dense retrieval core, ask CLI, artifacts, tests, docs`.

______________________________________________________________________

## Interfaces (concise)

```python
# src/trailblazer/retrieval/dense.py
class DenseRetriever:
    def __init__(self, db_url: str, provider_name: str = "dummy", dim: int | None = None): ...
    def embed_query(self, text: str) -> "np.ndarray": ...
    def search(self, query: str, top_k: int = 8) -> list[dict]:
        """Returns [{chunk_id, doc_id, title, url, text_md, score}, ...]"""

# src/trailblazer/retrieval/pack.py
def group_by_doc(hits: list[dict], max_chunks_per_doc: int) -> list[dict]: ...
def pack_context(hits: list[dict], max_chars: int = 6000) -> str: ...

# CLI (Typer)
trailblazer ask "<question>" [--top-k 8] [--max-chunks-per-doc 3] [--provider dummy] [--max-chars 6000] [--format text|json] [--out DIR]
```

______________________________________________________________________

## Notes (keep it lean; no regressions)

- **Determinism:** normalize CRLF→LF before tokenization; break ties by `(score DESC, doc_id ASC, chunk_id ASC)`.
- **Safety:** do not log secrets; print provider name but never keys.
- **Performance:** SQLite path loads embeddings into memory for cosine; keep `top_k` small by default.
- **Extensibility:** 006B can add **keyword** (FTS5 / trigram) and **cross-encoder rerank**; keep current design pluggable.

______________________________________________________________________

## Acceptance Criteria

- `trailblazer ask "<question>"` runs end-to-end on a small DB produced by 005B (or a test fixture), writes artifacts under `runs/<run_id>/ask/`, and prints a useful summary.
- Ranking is deterministic and stable across runs (with dummy provider).
- Tests pass offline on SQLite.
- `make fmt && make lint && make test && make check-md` are green with **zero IDE linter errors**.
- README includes the Ask section with working examples.
- Prompt saved as `prompts/006_retrieve_and_ask_cli.md`.
