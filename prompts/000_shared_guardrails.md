# Shared Guardrails

PREAMBLE — Shared Guardrails (paste at the top of every prompt)
Save once as prompts/000_shared_guardrails.md and also paste at the top when
you run this prompt.

Trailblazer Prompt Guardrails (read first)

Main only. Do all work on main. No feature branches/PRs for this task.

Always use a venv + our toolchain:

```bash
make setup        # creates .venv, installs dev deps, installs pre-commit
make fmt          # ruff --fix + black
make lint         # ruff check + mypy
make test         # pytest -q
```
Only commit/push if all three succeed.

Never hand-fix lint/format. Use the Make targets above.

**Markdown files:** markdownlint runs automatically via pre-commit hooks (line
length ≤80 chars, start with # heading). Fix manually or use `--fix` flag if
needed. **Always start .md files with a top-level heading.**

Proof-of-work in your reply: paste the exact commands you ran and the last
~10 lines of their output (no screenshots).

Secrets: never commit real credentials. Examples must use placeholders.

Confluence: Cloud v2 + Basic auth. Use v1 CQL only to prefilter when --since
is set. Bodies/attachments fetched via v2.

Artifacts immutable: write to runs/run-id/phase/…; never mutate previous runs.
