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

# PROMPT OPS-002 — Run Backfill + Incrementals with Observability (OPS)

**Goal:** Run space listing, do a controlled backfill, then incrementals using --auto-since, with sidecars & logs; load embeddings; lightly verify retrieval.

**Work on:** main only (no code changes beyond 007's outputs)

## To-Dos

1. **Verify env & toolchain.**

   ```bash
   git rev-parse --abbrev-ref HEAD
   make setup && make fmt && make lint && make test && make check-md
   ```

   Ensure .env has Confluence + DB placeholders (local only). Never commit .env.

1. **List spaces (artifact + visibility).**

   ```bash
   RID=$(date -u +'%Y%m%dT%H%M%SZ')_spaces
   trailblazer confluence spaces | tee logs/spaces-$RID.out
   test -f runs/$RID/ingest/spaces.json && head -n 5 runs/$RID/ingest/spaces.json
   ```

1. **Prepare spaces manifest & state dir (untracked).**

   ```bash
   mkdir -p state/confluence logs
   printf "DEV\nDOC\n" > state/confluence/spaces.txt
   ```

   Confirm state/ is git-ignored.

1. **Backfill one space with visibility.**

   ```bash
   RID=$(date -u +'%Y%m%dT%H%M%SZ')_backfill
   SPACE=DEV
   trailblazer ingest confluence --space "$SPACE" --progress --progress-every 5 2>&1 | tee logs/ingest-$RID-$SPACE.log
   ls runs/$RID/ingest/{pages.csv,attachments.csv,summary.json} -l
   ```

   Inspect the last 30 lines of the log for confluence.page and attachment lines.

1. **Write/update high-watermark (auto-since state).**
   After backfill completes, set state/confluence/${SPACE}\_state.json using the run artifact's max updated_at.
   (If 007 wrote this automatically, just inspect it.)

1. **Incremental ingest (new/changed only).**

   ```bash
   RID=$(date -u +'%Y%m%dT%H%M%SZ')_delta
   SPACE=DEV
   trailblazer ingest confluence --space "$SPACE" --auto-since --progress --progress-every 5 2>&1 | tee logs/ingest-$RID-$SPACE.log
   ```

   Confirm smaller pages.csv vs backfill if little changed; verify the space's state file now shows the newer last_highwater.

1. **Load embeddings (idempotent) and smoke ask.**

   ```bash
   trailblazer db init
   trailblazer embed load --run-id "$RID" --provider "${EMBED_PROVIDER:-dummy}" --batch 256
   trailblazer ask "What is Navigate to SaaS?" --top-k 8 --max-chunks-per-doc 2 --provider "${EMBED_PROVIDER:-dummy}" --format text
   ```

1. **Deletions diff & safe prune (dry-run).**

   ```bash
   trailblazer ingest diff-deletions --space "$SPACE" --baseline-run <OLD_RID> --current-run $RID
   trailblazer ops prune-runs --keep 5 --min-age-days 14 --dry-run | tee logs/prune-dry-run.out
   ```

1. **Proof-of-work (paste back).**

   - tail ~30 lines: logs/ingest-<RID>-<SPACE>.log showing page/attach progress.
   - head of runs/<RID>/ingest/pages.csv and summary.json.
   - cat state/confluence/${SPACE}\_state.json.
   - output of diff-deletions and the dry-run prune list.

## Answers to your two concerns (operationalized here)

**"Are we really only downloading what's updated?"**
With --auto-since, ingest uses the space high-watermark (updated_at) from state to seed --since (v1 CQL prefilter), then fetches full bodies/attachments via v2 only for those candidate pages. Your incremental step (Task 6) confirms this by showing reduced pages in pages.csv and logs.

**"Delete old data we don't need?"**
Use diff-deletions to inventory removed upstream pages (no DB tombstones yet), and ops prune-runs --dry-run to list old run directories while keeping the newest and any state-referenced runs. Only delete when you remove --dry-run. (We'll wire DB tombstones in 007/008.)
