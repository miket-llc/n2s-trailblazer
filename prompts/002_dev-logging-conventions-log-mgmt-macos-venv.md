PROMPT FOR CLAUDE — DEV: Standard Logging Convention + Smart Log Management + macOS venv Check (Golden Path, Config‑First, NO prompt archiving)

Execute now. Don't draft a plan. Paste the guardrails verbatim first, then perform the numbered steps and paste proof‑of‑work (commands + outputs).
Do not move, delete, or archive any files in prompts/. We will only save this new prompt and list non‑numbered prompts to README for visibility—nothing else.
No assumptions: discover CLI names and code paths from the repo at run time and use those values.

000 — Paste guardrails (verbatim, unchanged)

Open prompts/000_shared_guardrails.md.

Paste its full contents at the very top of your reply, unchanged. (Mandatory.)

✅ To‑Do Checklist (≤9 items)

1. Save THIS prompt (NO archiving) & refresh README (read‑only listing of non‑numbered prompts)
   set -euo pipefail
   git rev-parse --abbrev-ref HEAD | grep -qx "main"

# Compute next number and save ONLY this new prompt (do NOT touch other files)

NEXT_NUM=$(printf "%03d" $(( $(ls -1 prompts 2>/dev/null | grep -E '^[0-9]{3}_.+.md$' | sed 's/_.*//' | sort -n | tail -n1 | sed 's/^0*//' 2>/dev/null || echo 0) + 1 )))
FILE="prompts/${NEXT_NUM}\_dev-logging-conventions-log-mgmt-macos-venv.md"
echo ">> TARGET PROMPT FILE: $FILE"

# (Use your editor automation to save THIS prompt into $FILE)

# Refresh README to show both numbered and non-numbered prompts WITHOUT moving anything

{
echo "# Prompts Index"
echo
echo "## Numbered prompts"
ls -1 prompts 2>/dev/null | grep -E '^[0-9]{3}*.+.md$' | sort | awk '{printf("- %s\\n",$0)}'
echo
echo "## Other prompt files (left in place; not moved or deleted)"
comm -23 \<(ls -1 prompts 2>/dev/null | sort) \<(ls -1 prompts 2>/dev/null | grep -E '^[0-9]{3}*.+.md$' | sort) | awk '{printf("- %s\\n",$0)}'
} > prompts/README.md

git add "$FILE" prompts/README.md
git commit -m "Add ${FILE}; refresh prompts/README without moving or archiving existing prompts"

Paste the $FILE path and the two README sections (first ~10 lines each).

2. Update Shared Non‑Negotiables — Logging & macOS venv (append verbatim; no edits elsewhere)

Append the following blocks to prompts/000_shared_guardrails.md (exact text):

Logging Non‑Negotiables (Standard Convention & Smart Management)

File naming (canonical): For each run, write NDJSON events to var/logs/\<run_id>/events.ndjson and pretty/TTY status to var/logs/\<run_id>/stderr.log. Maintain symlinks: var/logs/\<run_id>.ndjson → var/logs/\<run_id>/events.ndjson, and latest symlinks: var/logs/latest.ndjson, var/logs/latest.stderr.log. Each event line MUST include ts, run_id, phase, component, level, and worker_id (if any).

Streams rule: NDJSON → stdout only; pretty/status → stderr only. Never mix on the same stream.

Rotation: When events.ndjson exceeds logs.rotation_mb (default: 512 MiB), continue in events.ndjson.N (N=1,2,…) and update symlinks.

Compression: Compress segments older than logs.compress_after_days (default: 2) to .gz.

Retention: Prune logs older than logs.retention_days (default: 14) via trailblazer logs prune (dry‑run by default; requires --yes to delete). Never prune active runs.

Status JSON: Write an atomic snapshot to var/status/\<run_id>.json and update var/status/latest.json symlink on each heartbeat.

Reports: Assurance artifacts live in var/reports/\<run_id>/ and are never auto‑deleted.

macOS Virtualenv Non‑Negotiable

On macOS (Darwin), all runtime commands must run inside a virtual environment. If not detected (VIRTUAL_ENV, Poetry/Conda, or sys.prefix != sys.base_prefix), fail fast with clear guidance: "Activate your venv: source .venv/bin/activate or run make setup."

CI/automation may bypass with TB_ALLOW_SYSTEM_PYTHON=1 only if explicitly set in CI config.

git add prompts/000_shared_guardrails.md
git commit -m "Guardrails: add logging convention, smart log management, and macOS venv enforcement"

Paste the new section headings as proof.

3. Discover logging & orchestrator surfaces (no guessing)
   export PAGER=cat; export LESS='-RFX'
   if command -v rg >/dev/null 2>&1; then RG="rg -n --hidden --no-ignore"; else RG="grep -RIn"; fi

# CLI entrypoints & orchestrator

$RG -i 'console_scripts|entry_points|if __name__ == .__main__.' -g '!__/var/__' -g '!__/node_modules/__' || true
trailblazer --help || true
trailblazer run --help || true # If absent, discover the actual orchestrator command and show its help.

# Existing observability/log sinks in code

$RG -i 'ndjson|events?.jsonl|events?.ndjson|status.json|heartbeat|eta|EPS|monitor' -g '!__/var/__' || true

Paste the relevant help lines and any current log paths found.

4. Implement standard logging convention (sink + symlinks + rotation/compression/retention)

Add/extend an Observability sink that:

Creates var/logs/\<run_id>/, writes NDJSON to events.ndjson, pretty to stderr, and manages symlinks (\<run_id>.ndjson, latest.\*).

Handles rotation (logs.rotation_mb), compression (logs.compress_after_days), retention via trailblazer logs prune, and atomic status JSON.

Works whether stdout is TTY or redirected, without double‑emitting.

Update all long‑running commands (ingest/normalize/enrich/chunk/classify/embed/ask/compose/monitor) to use the sink.

Add offline tests for rotation/compression/retention and status writes.

git add -A
git commit -m "Observability: standardized log sink (events.ndjson/stderr.log), symlinks, rotation, compression, retention, status.json"

Paste a tree var/logs/\<run_id> (from a short smoke run) showing events.ndjson, stderr.log, and symlinks.

5. Add log management CLI (trailblazer logs …)

Implement subcommands (respecting existing CLI framework & config keys logs.\*):

trailblazer logs index → summarize runs with sizes/segments/last update times.

trailblazer logs prune [--dry-run] [--yes] → compress old segments and delete beyond retention (never active); prints a clear plan.

trailblazer logs doctor → fix symlinks/permissions and validate segments; non‑zero on unfixable issues.

git add -A
git commit -m "CLI: add trailblazer logs (index|prune|doctor) with config-driven rotation/compression/retention"
trailblazer logs --help || true
trailblazer logs index 2> >(tee /dev/stderr) 1> >(head -n 50)

Paste logs --help and one screen of logs index.

6. Enforce macOS venv check globally (tests included)

Add env_checks.assert_virtualenv_on_macos(); call at CLI bootstrap.

Fail fast with helpful message; allow bypass via TB_ALLOW_SYSTEM_PYTHON=1.

Add tests mocking Darwin/system Python vs venv contexts.

git add -A
git commit -m "Env: enforce macOS virtualenv check with explicit bypass; tests"

Paste the error message from a simulated fail and success output with the bypass set.

7. (Optional) Backlog integration: store log paths & last heartbeat for each run

If graphdb.processed_runs exists, add logs_dir and last_event_ts (idempotent migration).

Update on run start and each heartbeat; surface via logs index and runs.\* events.

git add -A
git commit -m "Backlog integration: logs_dir & last_event_ts; expose in runs events and logs index"

Paste a SELECT run_id, status, logs_dir, last_event_ts FROM graphdb.processed_runs LIMIT 5;.

8. Smoke run: produce a fresh run, then exercise log tooling (NO prompt changes)

# Create a short run to produce logs/status (help or tiny slice)

trailblazer run --help 2> >(tee /dev/stderr) 1> >(head -n 40) || true

# Show files for latest run via symlink

RUN_DIR="$(dirname "$(readlink var/logs/latest.ndjson 2>/dev/null || echo "")")"
echo "RUN_DIR=${RUN_DIR}"; test -n "${RUN_DIR}" && ls -lah "${RUN_DIR}" || true

trailblazer logs index 2> >(tee /dev/stderr) 1> >(cat)
trailblazer logs prune --dry-run 2> >(tee /dev/stderr) 1> >(cat)
trailblazer logs doctor 2> >(tee /dev/stderr) 1> >(cat)

Paste: directory listing and the outputs of logs index/prune/doctor.

9. Proof‑of‑work & Definition of Done

Paste the exact commands you ran for steps 1–8 and the last ~10 lines of:

make fmt
make lint
make test

Definition of Done:

Logging follows the standard convention: var/logs/\<run_id>/events.ndjson, var/logs/\<run_id>/stderr.log, plus symlinks var/logs/\<run_id>.ndjson and var/logs/latest.\*.

Rotation, compression, retention implemented and configurable; trailblazer logs (index|prune|doctor) works (safe by default with --dry-run).

Status JSON written atomically to var/status/\<run_id>.json and var/status/latest.json symlink updated.

macOS venv check enforced globally; bypass only via TB_ALLOW_SYSTEM_PYTHON=1.

No files in prompts/ were moved, deleted, or archived by this prompt.

Golden Path & config‑first; Postgres‑only runtime; streams rule respected.

make fmt && make lint && make test PASS with zero IDE lint errors.

Final commit:

git add -A
git commit -m "Standard logging convention + smart log management + macOS venv enforcement; NO prompt archiving"
