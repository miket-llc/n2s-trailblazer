# Trailblazer Mindfile (Python)

**Purpose.** Living, high-signal guide for architecture, invariants, and working agreements. Source of truth for assistants (MAX/Claude) and humans.

**Scope.** Python monorepo for N2S Trailblazer: ingest (Confluence v2), normalize, enrich/classify, embed, retrieve, compose/create, audit, and (later) serve.

---

## 1) Core principles (non-negotiables)

* **CLI-first.** Everything is runnable via `trailblazer …`.
* **Explicit phases.** Stable nouns (`ingest`, `normalize`, …). No numeric module names.
* **Idempotent steps.** Safe to re-run; new `run_id` per execution.
* **Artifacts are sacred.** Each phase writes deterministic outputs under `runs/<run_id>/<phase>/`.
* **Config via env.** `.env` (local only) + Pydantic Settings. No secrets in code or git.
* **Observability.** Structured JSON logs (structlog), per-phase `metrics.json` + `manifest.json`.
* **Small, typed I/O.** Pydantic models between steps; avoid implicit coupling.
* **Fail soft on data.** Skip/bubble errors per item; never crash the entire run unless integrity is at risk.

---

## 2) Current state (v0.1 scaffold)

* **Repo:** `miket-llc/n2s-trailblazer` (Python)
* **CLI:** Typer app → `trailblazer`
* **Packages:** `trailblazer.core`, `trailblazer.adapters`, `trailblazer.pipeline`, `trailblazer.cli`
* **Phases:** `ingest → normalize → enrich → classify → embed → retrieve → compose → create → audit`
* **Data workspaces:** `data/` (raw/staged/processed/generated), **gitignored**
* **Run artifacts:** `runs/<run_id>/<phase>/…`, **gitignored**
* **Tooling:** ruff, black, mypy (non-strict), pytest, pre-commit

---

## 3) Directory layout (canonical)

* `prompts/`

  * `000_scaffold_python_monorepo.md`
  * `001_ingest_confluence_v2.md`
* `configs/`

  * `dev.env.example`
  * `pipeline.yaml`
* `src/`

  * `trailblazer/`

    * `core/` (config, logging, artifacts, db, models)
    * `adapters/` (Confluence client)
    * `pipeline/` (dag, runner, steps/\*)
    * `cli/` (Typer entrypoint)
* `data/` (gitignored) → raw / staged / processed / generated
* `runs/` (gitignored) → per-run phase outputs
* `tests/` (unit, integration)
* **Note:** `data/` and `runs/` must remain untracked.

---

## 4) Configuration & secrets

Environment variables (via `.env` locally):

* `CONFLUENCE_BASE_URL` (default `https://ellucian.atlassian.net/wiki`)
* `CONFLUENCE_EMAIL`
* `CONFLUENCE_API_TOKEN` *(API key generated in Atlassian; paired with email)*
* `CONFLUENCE_BODY_FORMAT` = `storage` | `atlas_doc_format` (default: `storage`)
* `TRAILBLAZER_DB_URL` (optional until DB work begins)

**Rules**

* Never commit `.env`.
* Secrets only via env/CI secrets.

---

## 5) Confluence ingest (Cloud v2 + Basic auth)

**Auth.** Basic (email + API token).
**Base.** `https://ellucian.atlassian.net/wiki/api/v2`.
**Pagination.** Cursor via `_links.next` or `Link: rel="next"`.

**Endpoints we use**

* Spaces: `GET /api/v2/spaces?keys=K1,K2&limit=…`
* Pages: `GET /api/v2/pages?space-id=<id>&body-format=storage|atlas_doc_format&limit=…`
* Page by ID: `GET /api/v2/pages/{id}?body-format=…`
* Attachments: `GET /api/v2/pages/{id}/attachments?limit=…`
* **Delta search (temporary):** v1 CQL `GET /rest/api/content/search?cql=…` to preselect page IDs when `--since` is provided, then fetch bodies via v2.

**Invariants**

* **Bodies** come from **v2** (more reliable; explicit `body-format`).
* **URLs** are absolute: page `_links.webui` → full URL; attachment `downloadLink` → full URL.
* **Rate limiting** handled with exponential backoff (tenacity).

---

## 6) Models (contract between phases)

```python
# trailblazer.core.models
class Attachment(BaseModel):
  id: str
  filename: str | None = None
  media_type: str | None = None
  file_size: int | None = None
  download_url: str | None = None  # absolute

class Page(BaseModel):
  id: str
  title: str
  space_key: str | None = None
  space_id: str | None = None
  created_at: datetime | None = None
  updated_at: datetime | None = None  # version.createdAt
  version: int | None = None
  body_html: str | None = None       # storage/adf HTML
  url: str | None = None             # absolute
  attachments: list[Attachment] = []
  metadata: dict = {}
```

---

## 7) Artifacts (file shapes)

Per run & phase directory: `runs/<run_id>/<phase>/`

* **NDJSON:** `confluence.ndjson` — one `Page` per line (attachments embedded).
* **Metrics:** `metrics.json` — counts, durations, args.
* **Manifest:** `manifest.json` — run\_id, phase, started/completed, code version.

**Example NDJSON line (abridged)**

```json
{"id":"123","title":"Foo","space_key":"DEV","space_id":"111","updated_at":"2025-08-10T12:34:56Z","version":42,"url":"https://…/wiki/spaces/DEV/pages/123/Foo","body_html":"<p>…</p>","attachments":[{"id":"att-1","filename":"diagram.png","download_url":"https://…"}]}
```

---

## 8) Phase contract (inputs → outputs → next)

* **ingest**

  * in: Confluence (network)
  * out: `confluence.ndjson`, `metrics.json`, `manifest.json`
  * next: `normalize` consumes NDJSON

* **normalize**

  * in: NDJSON (HTML bodies)
  * out: Markdown + cleaned metadata, attachment maps

* **enrich**

  * in: normalized docs
  * out: enriched metadata (structure, inferred fields), suggested edges with confidence

* **classify**

  * in: enriched docs
  * out: `classification` JSON (templateType, docType, phase/stage, offeringType, focusAreas)

* **embed**

  * in: normalized/enriched text
  * out: vectors in Postgres (pgvector), content rows for retrieval

* **retrieve**

  * in: queries
  * out: chunks + (optional) graph expansion

* **compose**

  * in: retrieved chunks
  * out: structured JSON for documents (token-budgeted)

* **create**

  * in: composed JSON
  * out: files (Markdown, etc.)

* **audit**

  * in: all prior outputs
  * out: coverage/quality/drift reports

---

## 9) CLI conventions

* `trailblazer run --phases ingest normalize … [--dry-run]`
* `trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z [--body-format storage|atlas_doc_format] [--max-pages N]`
* All commands return a **run\_id** on success.
* Logs are JSON to stdout; metrics & manifest always written.

---

## 10) Idempotency & reproducibility

* New `run_id` each run: `YYYY-MM-DD_HHMMSS_xxxx`.
* Never mutate past run outputs.
* Deterministic transforms (same input → same output) where feasible.
* When state/hwm is introduced, store under `runs/<run_id>/ingest/state.json` (and optionally a stable cache dir) — **not** in git.

---

## 11) Error handling & retries

* External IO wrapped with tenacity (exponential backoff, max 5 attempts).
* Per-item failures logged with `error=true`, continue run.
* Add `--fail-fast` flag later if needed.

---

## 12) Testing strategy

* **Unit:** client pagination, URL normalization, data mappers.
* **Integration (mocked):** ingest writes valid NDJSON + metrics.
* **Contract snapshots:** small golden samples for normalize/enrich.
* **CI gates:** ruff, black, mypy, pytest must pass.

---

## 13) Database (planned)

* Postgres + pgvector.
* Schemas:

  * `graphdb.nodes`, `graphdb.chunks`, `graphdb.chunk_embeddings`, `graphdb.edges`
* Edge types (planned): `RELATES_TO`, `REFERENCES`, `SUPPORTS`, `IMPLEMENTS`, `DEPENDS_ON`
* Confidence on LLM-suggested edges; thresholded inserts (≥0.7 default).

---

## 14) Token budgeting (planned)

* Composer enforces token budget using tokenizer counts.
* Prioritize chunks by qualityScore/relevance; truncate/skip overflow.
* Output structured JSON; final rendering handled in `create`.

---

## 15) Quality & audit (planned)

* Coverage: % of expected docs generated (per playbook outline).
* Quality: lint rules for structure, missing sections, link validity.
* Drift: compare current artifacts vs prior runs.

---

## 16) Working agreements (assistants + devs)

* **Branches:** `scaffold/*`, `feat/*`, `fix/*`, `docs/*`
* **Commits:** conventional (`feat(ingest): …`)
* **Pre-commit** must be installed and green before PR.
* **Patch size:** prefer < 400 LOC per PR unless unavoidable.
* **Prompts:** every major change starts with a versioned prompt saved under `prompts/NNN_*.md`.
* **MAX vs standard models:** use **MAX** for multi-file edits or long diffs; standard is fine for single-file tweaks.

---

## 17) Decisions log (ADRs, concise)

* **ADR-001:** Python package, CLI-first; no numeric module names.
* **ADR-002:** Confluence **Cloud v2** for pages/attachments; **Basic auth** (email + API token).
* **ADR-003:** Use **v1 CQL** only to pre-filter by `lastModified` for deltas; fetch bodies via v2.
* **ADR-004:** NDJSON with embedded attachments is the ingest artifact contract.
* **ADR-005:** Structured logging with structlog; per-phase metrics & manifest are mandatory.

---

## 18) Open questions / TODOs

* Introduce per-space high-watermarks (state file + resume strategy).
* Decide default `body_format` long-term: `storage` vs `atlas_doc_format`.
* Attachments: decide whether to **download** or **reference** (current: reference only).
* Add `serve` phase (HTTP API) vs CLI-only.
* Schema for normalized Markdown + attachment map.
* Database migrations (Alembic?) and seed scripts.

---

## 19) How to contribute (quick)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

trailblazer --help
trailblazer ingest confluence --space DEV --max-pages 10 --since 2025-08-01T00:00:00Z
pytest -q && ruff check . && black --check src tests
```

---

## 20) Versioning & change log

* **v0.1.0** — Scaffold + Confluence ingest (client + CLI + NDJSON).
* Next: Normalize (HTML→MD), Enrich, Classify, DB/pgvector, Retriever, Composer/Creator, Audit.

---

**Reminder:** Keep this mindfile current. When architecture or contracts change, update **here first**, then prompts, then code.
