# Guardrails for Trailblazer prompts

Read me first (do not skip): Guardrails for Trailblazer prompts

Work on main only. No feature branches, no PRs, commit atomically to main.

Always use a venv:

```bash
make setup
# (creates .venv, installs dev deps, installs pre-commit hooks)
```

Never hand-fix lint/format. Use the toolchain:

```bash
make fmt     # ruff --fix + black
make lint    # ruff check + mypy
make test    # pytest -q
```

Only commit/push if all three succeed.

Pre-commit must be installed and green before each commit.

Save this prompt to prompts/ as instructed before you code.

Proof-of-work inside Cursor: after changes, run the exact shell commands above and paste the command + last 10 lines of their output into the prompt response (no screenshots, no placeholders).

Secrets: read from .env, never printed or committed.

Confluence: Cloud v2 endpoints with Basic auth (email + API token). Use v1 CQL only for delta prefiltering.

Artifacts: every phase writes to runs/<run_id>/<phase>/..., never mutate previous runs.

If any step fails, stop and fix; do not push broken code.
You are responsible for verifying the code actually runs locally (CLI + tests), not just "compiles".
