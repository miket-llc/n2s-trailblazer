## 📦 PROMPT: `prompts/027_dev_embed_final_polish.md`

**Preamble / Context (save this file verbatim in `prompts/027_dev_embed_final_polish.md`):**

> **Trailblazer context (short):**
> We have successfully ingested and normalized Confluence (ADF bodies preserved) and DITA (XML → MD with full traceability) into `var/runs/<RUN_ID>/...`. We've enriched everything (rule‑based + optional LLM), producing `enriched.jsonl` and `fingerprints.jsonl`. We are now finalizing the **embed** phase so it's production‑grade: **PostgreSQL+pgvector only**, robust, observable, and aligned with the scripts already in `scripts/`.
>
> **Strict process discipline:**
>
> - **Zero IDE linter errors** allowed. Use the **existing** automation first (`make fmt`, `make lint`, `make check‑md`, `pre-commit`)—never hand "fix" lint unless tools can't be configured to enforce it.
> - **No regressions.** Read the code you are changing. If complexity creeps, **refactor**; otherwise be **surgical**.
> - **Postgres only at runtime** (SQLite only in unit tests where explicitly gated).
> - **Do not trigger pagers** in terminal output (`PAGER=cat`, `LESS=-RFX`).
> - Every prompt **must be saved** in `prompts/` as a `.md` file.

______________________________________________________________________

### 1) Update **shared guardrails** first (non‑negotiables)

Edit `prompts/000_shared_guardrails.md` (append a new **"Embedding & DB Non‑Negotiables"** section):

- **PostgreSQL only in ops**: Runtime paths (embed, retrieval, ask) **MUST** connect to `postgresql://…`. SQLite is allowed **only** in unit tests guarded by `TB_TESTING=1`.
- **pgvector required**: `trailblazer db doctor` must show `pgvector: available`. If not, fail hard with a clear fixup.
- **Dimensions discipline**: The **provider's** configured dimension (e.g., `OPENAI_EMBED_DIM=1536`) **must match** what's persisted. If mismatch detected, **abort** with a remediation hint (or require an explicit `--reembed-all`).
- **No pagers**: All scripts/commands must export `PAGER=cat`, `LESS=-RFX`.
- **No regressions**: Before merge, run `make fmt && make lint && make check-md && make test` and ensure **zero** failures/warnings in IDE.

Commit this as:
`docs(shared): guardrails — Postgres-only (ops), pgvector req, dims discipline, no pagers`

______________________________________________________________________

### 2) Surgical code changes (keep it minimal)

**A. DB preflight = fail-fast Postgres in ops**

- In `src/trailblazer/cli/main.py`:
  Confirm `_run_db_preflight_check()` rejects non‑Postgres **unless** `TB_TESTING=1`. It already does; ensure the error message explicitly says "SQLite is for tests only; use `make db.up` + `trailblazer db init` + `trailblazer db doctor`".
- In any embed/retrieval entrypoint that bypasses the generic preflight, call `_run_db_preflight_check()`.

**B. Vector index creation (one helper, one CLI entry)**

- In `src/trailblazer/db/engine.py` add:

  ```python
  def ensure_vector_index() -> None:
      """Create pgvector index if missing (safe/no-op if exists)."""
      if not is_postgres():
          return
      engine = get_engine()
      with engine.connect() as conn:
          # IVFFLAT cosine index; requires ANALYZE and pgvector >= 0.5.0
          try:
              conn.execute(text("""
                  CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_vec
                  ON chunk_embeddings
                  USING ivfflat (embedding vector_cosine_ops)
                  WITH (lists = 100);
              """))
              conn.execute(text("ANALYZE chunk_embeddings;"))
              conn.commit()
          except Exception:
              # Do not explode; db.doctor will show remaining gaps
              pass
  ```

- In `trailblazer db init`, after `create_tables()` and `initialize_postgres_extensions()`, call `ensure_vector_index()` and print a success line.

**C. Dimensions sanity in CLI (no silent mismatch)**

- In `embed_load_cmd` (Typer), **before** calling `load_normalized_to_db(...)`:

  - Detect any existing embeddings' `dim` for the chosen `provider`.
    If existing `dim` != provider's configured dim, **abort** with:

    > "Embedding dimension mismatch (existing=X, requested=Y). Re-run with `--changed-only=false` and `--reembed-all` (or purge embeddings)."

- If your CLI currently **does not** accept `--batch`, keep it; do **not** add a new flag unless you confirm it's used. (I saw it present—keep as‑is.)

**D. Alignment with scripts (no phantom flags)**

- Our `scripts/reembed_corpus_openai.sh` currently passes `--provider`, and might pass `--dimensions`.

  - **Option 1 (preferred):** Remove the `--dimensions` flag from the script and instead export `OPENAI_EMBED_DIM=$EMBED_DIMENSIONS` before invoking the CLI.
  - **Option 2:** If you add a `--dimensions` Typer option that just sets `OPENAI_EMBED_DIM` internally, ensure it's **backward‑compatible** and validated.

- Ensure the embed loader writes `var/runs/<RUN_ID>/embed_assurance.json` with at least:

  ```json
  {
    "provider": "openai",
    "dimension": 1536,
    "docs_embedded": 123,
    "docs_skipped": 45,
    "chunks_embedded": 9876,
    "chunks_skipped": 0,
    "duration_seconds": 123.45
  }
  ```

  (Your reembed script already reads this file—keep the schema stable.)

**E. Observability (no pager, consistent file names)**

- Verify `monitor_embedding.sh` & `embed_dispatch.sh` export `PAGER=cat` and `LESS=-RFX` (I saw that—keep it).
- Ensure console progress in `embed_load_cmd` (start/end banners with counts), but keep it concise so it doesn't DOS the terminal.

**F. Don't break tests**

- Unit tests that assume SQLite must set `TB_TESTING=1` and never exercise the real embed path.

**Acceptance criteria**

- `make fmt && make lint && make check-md && make test` = **all green**.

- `trailblazer db init && trailblazer db doctor` prints pgvector available and shows the **vector index**.

- `trailblazer embed load --run-id <RID> --provider openai --batch 128`

  - Aborts on dimension mismatch with a **clear** message (unless `--reembed-all` used).
  - Produces `embed_assurance.json` with accurate counts & duration.

- `scripts/reembed_corpus_openai.sh` runs **without** unknown flags and **without** pagers.

**Commit message**

```
dev(embed): fail-fast Postgres-only, dims sanity; ensure pgvector index; align scripts; assurance file contract
```
