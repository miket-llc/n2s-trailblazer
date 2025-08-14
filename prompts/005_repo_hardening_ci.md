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

# PROMPT 005 — Repo Hardening + Normalize Finalization + CI (Non-Regression, ≤9 to-dos)

**Save as:** `prompts/005_repo_hardening_ci.md`
**Branch policy:** **MAIN ONLY** (no feature branches)
**Before you start:** paste the entire `prompts/000_shared_guardrails.md` **verbatim at the very top** of this prompt. Do **not** modify that file in this task.

**Goal**
Lock down lint/format behavior across local dev, pre-commit, and CI; finish/verify Normalize; keep **zero IDE errors**; do **not** undo any changes already made by us or Claude.

______________________________________________________________________

## To-Dos (max 9)

- [ ] **Canonicalize Markdown config (no rule changes).**
  Make **`.markdownlint.json` (or .jsonc) the single source of truth**. If a duplicate config exists (e.g., `.markdownlintrc`), remove it to avoid drift. Keep any existing `.markdownlintignore` if present. **Do not relax rules.**

- [ ] **Pre-commit hooks (verify/add; don't weaken).**
  Ensure the following hooks run (add only if missing; keep stricter existing ones):

  - **mdformat** (formats `.md`)
  - **markdownlint-cli2** with `--fix`
  - **ruff**, **black**, **mypy**
  - **gitleaks** (secret scan)
  - **pre-push** hook that runs `pytest -q` and must pass

- [ ] **Makefile (augment, don't break).**
  Confirm these exist; add if missing (names must match):

  - `fmt` → `ruff --fix .`, `black .`, **`mdformat` for all `*.md`**

  - `lint` → `ruff check .`, `black --check .`, `mypy src`, **`markdownlint-cli2`**

  - **New helpers**:

    - `md` → `npx markdownlint "**/*.md" --fix --config .markdownlint.json`
    - `check-md` → same as above **without** `--fix`

  - **New**: `ci` → `make fmt && make lint && make test && make check-md`

- [ ] **CI workflow (mirror local; don't regress).**
  Add `.github/workflows/ci.yml` running on **push to main**:

  1. setup **Python 3.11**, **Node 18**
  1. `pip install -e ".[dev]"`
  1. `make fmt && make lint && make test && make check-md`
  1. **(optional but recommended)**: run gitleaks in detect-only mode (won't block dev once pre-commit protects pushes)

- [ ] **Secrets & hygiene.**

  - Ensure `configs/dev.env.example` contains **placeholders only** (no real email/token).
  - Confirm `.gitignore` ignores: `var/runs/`, `data/`, `.venv/`, `.env`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.DS_Store`.
  - Run a local secret scan and fix if anything flags (rotate & scrub history if needed).

- [ ] **Normalize phase (verify or complete; don't rewrite existing).**

  - If Normalize is already implemented, **verify**: reads `var/runs/<RID>/ingest/confluence.ndjson`; outputs `var/runs/<RID>/normalize/normalized.ndjson` with `text_md`, `links[]`, `attachments[]`, `body_repr`, plus `metrics.json` & `manifest.json`.
  - If missing parts: **finish minimally** without undoing previous work. Support **Storage (XHTML/HTML)** now; if `body_repr=="adf"` exists, route through the ADF converter (from 004 Rev A/B), otherwise skip with a warning count in metrics.

- [ ] **Tests (determinism + format paths).**
  Add/ensure:

  - **Determinism test**: asserts **ATX headings** (e.g., `# H`) and **no triple blank lines** in output.
  - **Storage test**: renders a simple page with a link + attachment map.
  - **ADF test**: if ADF path exists, include a minimal link-mark case; otherwise skip with reason.

- [ ] **Repo-wide Markdown cleanup (tooling, not hand edits).**
  Run `mdformat $(git ls-files '*.md')`, then `make check-md`. If the IDE still warns (e.g., **MD032 blanks-around-lists**), **adjust the files via formatter or align the config**—do **not** waive rules per file.

- [ ] **README — Contributing & Non-Regression.**
  Add/ensure a short section that reiterates: **main-only**, the **Make** commands, **Markdown hygiene** (mdformat + markdownlint), **secrets policy**, **zero-errors policy**, and "**do not weaken Shared Guardrails**." Link to the latest mindfile in `docs/`.

______________________________________________________________________

## Snippets (use **only if missing**; merge with existing — **do not overwrite stricter configs**)

**`.github/workflows/ci.yml`**

```yaml
name: CI
on:
  push:
    branches: ["main"]
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - uses: actions/setup-node@v4
        with:
          node-version: "18"

      - name: Install dependencies
        run: |
          python -m venv .venv
          . .venv/bin/activate
          pip install -e ".[dev]"
          npm -v || (sudo apt-get update && sudo apt-get install -y npm)
          npm install -g markdownlint-cli2 || true

      - name: Format
        run: . .venv/bin/activate && make fmt

      - name: Lint
        run: . .venv/bin/activate && make lint

      - name: Test
        run: . .venv/bin/activate && make test

      - name: Markdown (no fix)
        run: npx markdownlint "**/*.md" --config .markdownlint.json

      # Optional: secrets scan (non-blocking)
      - name: Gitleaks (detect only)
        uses: gitleaks/gitleaks-action@v2
        with:
          args: detect --no-banner --redact --source .
        continue-on-error: true
```

**`.gitignore` additions (if missing)**

```
.venv/
.env
__pycache__/
.pytest_cache/
.mypy_cache/
var/runs/
data/
.DS_Store
```

**Pre-commit examples (only add if missing; keep stricter existing hooks)**

```yaml
# mdformat
- repo: https://github.com/executablebooks/mdformat
  rev: 0.7.17
  hooks:
    - id: mdformat
      additional_dependencies: [mdformat-gfm]
      files: \.(md|markdown)$

# markdownlint-cli2 (with --fix)
- repo: https://github.com/DavidAnson/markdownlint-cli2
  rev: v0.17.2
  hooks:
    - id: markdownlint-cli2
      args: ["--fix", "--config=.markdownlint.json"]
      files: \.(md|markdown)$

# gitleaks
- repo: https://github.com/gitleaks/gitleaks
  rev: v8.18.2
  hooks:
    - id: gitleaks
      args: ["protect", "--verbose", "--redact", "--staged"]
      pass_filenames: false

# pre-push: run pytest
- repo: local
  hooks:
    - id: pytest-on-push
      name: pytest on push
      entry: pytest -q
      language: system
      pass_filenames: false
      stages: [push]
```

______________________________________________________________________

## Acceptance

- **Shared Guardrails** file was **pasted at the top** of this prompt and **left unchanged**.
- `make fmt && make lint && make test && make check-md` pass locally (inside `.venv`) with **zero IDE linter errors**.
- CI workflow exists and runs the same steps on pushes to **main**.
- Markdown config unified; no duplicate configs remain.
- `configs/dev.env.example` has placeholders only.
- Normalize verified/finished; determinism test(s) pass.
- README contains the Contributing & Non-Regression section and a link to the latest mindfile in `docs/`.

______________________________________________________________________

## Proof-of-Work to paste back

Paste the exact commands and the **last ~10 lines** of output (no screenshots):

```bash
make setup
make fmt
make lint
make test
make check-md
```

If any tool complains about Markdown (e.g., **MD032**), re-run `make fmt` and fix by formatter or by aligning the rules—**never** with ad-hoc manual tweaks.
