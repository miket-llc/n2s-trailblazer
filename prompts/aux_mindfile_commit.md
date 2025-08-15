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

______________________________________________________________________

## PROMPT — Commit the latest mindfile to docs/ (Option B)

Save this prompt as: prompts/aux_mindfile_commit.md
Work on: main (no feature branches)
VERY IMPORTANT: Start by pasting the entire content of prompts/000_shared_guardrails.md verbatim at the top of this prompt. Do not modify guardrails in this task.

### To-Dos (≤9)

✅ Create file docs/2025-08-13-1358-trailblazer-mindfile.md with the exact content below (no edits).

✅ Run make setup (ensure pre-commit hooks installed).

✅ Run make fmt (this auto-fixes Markdown issues like MD032 blanks-around-lists).

✅ Run make lint and confirm zero IDE/CLI linter errors.

✅ Run make test and confirm green tests.

✅ Commit on main with the message: docs(mindfile): add 2025-08-13 13:58 EDT mindfile.

✅ Push to origin main.

✅ Paste proof-of-work: the commands you ran and the last ~10 lines of output for make fmt, make lint, make test.

✅ Do not modify prompts/000_shared_guardrails.md or any existing stricter configs in this task.
