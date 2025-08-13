PROMPT 008 — Console Observability & Progress UX (Ingest)
Preamble — update shared guardrails first

Open prompts/000_shared_guardrails.md and append (do not weaken existing rules):

Console UX policy:

Default to pretty, human-readable progress when attached to a TTY; default to JSON only in CI or when stdout is redirected.

Never intermix pretty output and JSON on the same stream. JSON → stdout; pretty/status/progress → stderr.

Always print the run_id at start/end of every command and write a final one-line summary.

Throttle progress updates; no more than 1 line per --progress-every N pages.

Keep the structured event names stable: confluence.space, confluence.page, confluence.attachments.

Save this prompt as: prompts/008_console_observability.md.

To-dos (≤9):

Pretty progress renderer

Implement a small progress layer (can use rich only for TTY pretty; do not change structlog).

Stage bars: spaces → pages → attachments. Show processed/total, rate, elapsed.

Emit to stderr only.

Stable JSON vs pretty separation

Keep all log.info("confluence.\*", …) events on stdout (structlog JSON).

Route typer.echo progress/status to stderr.

Add --log-format json|plain (default auto: json in CI/redirect, plain in TTY).

Start/finish banners & per-stage summaries

On start: print run_id, spaces targeted, since/auto-since mode, max_pages (stderr).

On finish: totals per space (pages, attachments, empty bodies) and elapsed (stderr).

Write/extend summary.json to include these counts and progress_checkpoints.

Progress checkpoints & resume indicators

Every --progress-every N, write/overwrite progress.json in the run dir with last page_id, counts, and timestamp.

On (re)start, if --auto-since and a prior progress.json exists, print a one-liner "resuming from …" indicator (stderr).

Space key mapping visibility

Before page fetch, print a compact table (stderr) of {id, key, name} for the spaces being ingested; read from the existing confluence spaces call/artifact when available.

CLI options (non-breaking)

--progress keeps working; honor --progress-every.

Add --quiet-pretty to suppress banners but keep progress bars (for long runs).

Artifacts

Ensure the already-present pages.csv, attachments.csv, summary.json remain deterministic; add progress.json (rolling) and final_summary.txt (one-line, human).

Tests (offline)

Test that stdout has JSON events, stderr has pretty text, and that progress.json updates at the expected cadence.

Snapshot last 10 lines of stderr for a tiny run.

Docs & guardrails

Update README "Observability & Ops" with examples of pretty + structured runs and how to tee both streams separately.

Run make fmt && make lint && make test && make check-md and commit to main only.
