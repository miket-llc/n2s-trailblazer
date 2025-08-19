import typer
from typing import Any, Dict, List, Optional
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path
import subprocess
import sys
from ..core.logging import setup_logging, log
from ..core.config import SETTINGS
from ..pipeline.runner import run as run_pipeline
from .db_admin import app as db_admin_app
from ..core.config import Settings

app = typer.Typer(add_completion=False, help="Trailblazer CLI")


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Main callback to enforce environment checks before any command execution."""
    from ..env_checks import assert_virtualenv_on_macos

    assert_virtualenv_on_macos()

    # If no command was provided, show help
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


ingest_app = typer.Typer(help="Ingestion commands")
normalize_app = typer.Typer(help="Normalization commands")
db_app = typer.Typer(help="Database commands")
embed_app = typer.Typer(help="Embedding commands")
confluence_app = typer.Typer(help="Confluence commands")
ops_app = typer.Typer(help="Operations commands")
paths_app = typer.Typer(help="Workspace path commands")
runs_app = typer.Typer(help="Runs management commands")
qa_app = typer.Typer(help="Quality assurance commands")
app.add_typer(ingest_app, name="ingest")
app.add_typer(normalize_app, name="normalize")
app.add_typer(db_app, name="db")
app.add_typer(db_admin_app, name="db-admin")
app.add_typer(embed_app, name="embed")
app.add_typer(confluence_app, name="confluence")
app.add_typer(ops_app, name="ops")
app.add_typer(paths_app, name="paths")
app.add_typer(runs_app, name="runs")
app.add_typer(qa_app, name="qa")


def _run_db_preflight_check() -> None:
    """Run database health check and exit if it fails.

    This is used as a preflight check for commands that require database access.
    """
    from ..db.engine import check_db_health
    import os

    try:
        health_info = check_db_health()

        # Require PostgreSQL for production (unless in test mode)
        if health_info["dialect"] != "postgresql":
            if os.getenv("TB_TESTING") == "1":
                # Allow non-PostgreSQL in test mode
                return
            else:
                typer.echo(
                    "❌ Database preflight failed: PostgreSQL required for production",
                    err=True,
                )
                typer.echo(
                    f"Current database: {health_info['dialect']}",
                    err=True,
                )
                typer.echo(
                    "Only PostgreSQL is supported; use 'make db.up' + 'trailblazer db init' + 'trailblazer db doctor'",
                    err=True,
                )
                raise typer.Exit(1)

        # For PostgreSQL, require pgvector
        if (
            health_info["dialect"] == "postgresql"
            and not health_info["pgvector"]
        ):
            typer.echo(
                "❌ Database preflight failed: pgvector extension not found",
                err=True,
            )
            typer.echo(
                "Use 'make db.up' then 'trailblazer db doctor' to get started",
                err=True,
            )
            raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"❌ Database preflight failed: {e}", err=True)
        typer.echo(
            "Use 'make db.up' then 'trailblazer db doctor' to get started",
            err=True,
        )
        raise typer.Exit(1)


def _validate_no_legacy_chunk_flags() -> None:
    """Validate that no legacy --chunk-* flags are used in embed commands."""
    import sys

    legacy_flags = [
        "--chunk-size",
        "--chunk-overlap",
        "--chunk-strategy",
        "--max-chunk-size",
        "--min-chunk-size",
        "--chunk-method",
    ]

    for flag in legacy_flags:
        if flag in sys.argv:
            typer.echo(
                f"❌ Legacy chunk flag {flag} not supported; use 'trailblazer chunk run <RID>' first",
                err=True,
            )
            raise typer.Exit(1)


@app.callback()
def _init() -> None:
    setup_logging()


@app.command()
def version() -> None:
    from .. import __version__

    typer.echo(__version__)


@app.command()
def run(
    config_file: Optional[str] = typer.Option(
        None,
        "--config",
        help="Config file (.trailblazer.yaml auto-discovered)",
    ),
    phases: Optional[List[str]] = typer.Option(
        None, "--phases", help="Subset of phases to run, in order"
    ),
    reset: Optional[str] = typer.Option(
        None, "--reset", help="Reset scope: artifacts|embeddings|all"
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Resume from last incomplete run"
    ),
    since: Optional[str] = typer.Option(
        None, "--since", help="Override since timestamp"
    ),
    workers: Optional[int] = typer.Option(
        None, "--workers", help="Override worker count"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Limit number of runs to process from backlog"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Override embedding provider"
    ),
    model: Optional[str] = typer.Option(
        None, "--model", help="Override embedding model"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Do not execute; just scaffold outputs"
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompts"),
) -> None:
    """
    Run the end-to-end N2S pipeline with config-first approach.

    Golden Path: ingest → normalize → enrich → embed → compose → playbook

    Config precedence: config file < env vars < CLI flags
    """

    # Load config with proper precedence
    try:
        settings = Settings.load_config(config_file)
        log.info("config.loaded", config_file=config_file or "auto-discovered")
    except Exception as e:
        typer.echo(f"❌ Config error: {e}", err=True)
        raise typer.Exit(1)

    # Override settings with CLI flags (highest precedence)
    if phases:
        settings.PIPELINE_PHASES = phases
    if since:
        settings.CONFLUENCE_SINCE = since
    if workers:
        settings.PIPELINE_WORKERS = workers
    if provider:
        settings.EMBED_PROVIDER = provider
    if model:
        settings.EMBED_MODEL = model

    # Handle reset operations
    if reset:
        _handle_reset(reset, settings, yes, dry_run)
        if not resume:  # If not resuming, exit after reset
            return

    # Handle resume logic
    run_id = None
    if resume:
        run_id = _find_resumable_run(settings)
        if run_id:
            typer.echo(f"🔄 Resuming run: {run_id}", err=True)
        else:
            typer.echo("ℹ️  No resumable run found, starting fresh", err=True)

    # Execute pipeline
    rid = run_pipeline(
        phases=settings.PIPELINE_PHASES,
        dry_run=dry_run,
        run_id=run_id,
        settings=settings,
        limit=limit,
    )

    log.info("cli.run.done", run_id=rid, phases=settings.PIPELINE_PHASES)
    typer.echo(rid)  # For scripting


def _handle_reset(
    reset_scope: str, settings: Settings, yes: bool, dry_run: bool
) -> None:
    """Handle reset operations with confirmation and reporting."""
    import json
    import shutil
    from datetime import datetime, timezone
    from pathlib import Path
    from typing import Dict, Any
    from ..core.artifacts import runs_dir, new_run_id
    from ..db.engine import get_engine

    valid_scopes = ["artifacts", "embeddings", "all"]
    if reset_scope not in valid_scopes:
        typer.echo(
            f"❌ Invalid reset scope: {reset_scope}. Use: {', '.join(valid_scopes)}",
            err=True,
        )
        raise typer.Exit(1)

    # Prepare reset report
    reset_id = new_run_id()
    report_dir = Path(f"var/reports/{reset_id}")
    report_dir.mkdir(parents=True, exist_ok=True)
    reset_report = report_dir / "reset.md"

    report: Dict[str, Any] = {
        "reset_id": reset_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope": reset_scope,
        "dry_run": dry_run,
        "actions": [],
    }

    # Confirm reset unless --yes
    if not yes and not dry_run:
        typer.echo(f"⚠️  About to reset scope: {reset_scope}")
        if reset_scope in ["artifacts", "all"]:
            typer.echo("   This will delete run artifacts under var/runs/")
        if reset_scope in ["embeddings", "all"]:
            typer.echo("   This will clear embeddings from the database")
        confirm = typer.confirm("Continue?")
        if not confirm:
            typer.echo("Reset cancelled", err=True)
            raise typer.Exit(0)

    try:
        # Reset artifacts
        if reset_scope in ["artifacts", "all"]:
            runs_base = runs_dir()
            if runs_base.exists():
                if not dry_run:
                    shutil.rmtree(runs_base)
                    runs_base.mkdir(parents=True)
                report["actions"].append(
                    {
                        "type": "artifacts_cleared",
                        "path": str(runs_base),
                        "completed": not dry_run,
                    }
                )
                typer.echo(
                    f"🗑️  {'Would clear' if dry_run else 'Cleared'} artifacts: {runs_base}"
                )

        # Reset embeddings
        if reset_scope in ["embeddings", "all"]:
            if settings.TRAILBLAZER_DB_URL:
                try:
                    # Temporarily set the global SETTINGS for get_engine()
                    from ..core.config import SETTINGS

                    old_db_url = SETTINGS.TRAILBLAZER_DB_URL
                    SETTINGS.TRAILBLAZER_DB_URL = settings.TRAILBLAZER_DB_URL
                    engine = get_engine()
                    SETTINGS.TRAILBLAZER_DB_URL = old_db_url
                    if not dry_run:
                        # Clear embeddings tables
                        from sqlalchemy import text

                        with engine.connect() as conn:
                            conn.execute(
                                text(
                                    "TRUNCATE TABLE IF EXISTS embeddings CASCADE"
                                )
                            )
                            conn.execute(
                                text("TRUNCATE TABLE IF EXISTS chunks CASCADE")
                            )
                            conn.execute(
                                text(
                                    "TRUNCATE TABLE IF EXISTS documents CASCADE"
                                )
                            )
                            conn.commit()
                    report["actions"].append(
                        {
                            "type": "embeddings_cleared",
                            "database": settings.TRAILBLAZER_DB_URL.split("@")[
                                -1
                            ],  # Hide credentials
                            "completed": not dry_run,
                        }
                    )
                    typer.echo(
                        f"🗑️  {'Would clear' if dry_run else 'Cleared'} embeddings from database"
                    )
                except Exception as e:
                    report["actions"].append(
                        {"type": "embeddings_clear_failed", "error": str(e)}
                    )
                    typer.echo(f"❌ Failed to clear embeddings: {e}", err=True)
            else:
                typer.echo(
                    "⚠️  No database URL configured, skipping embeddings reset"
                )

        # Write reset report
        with open(reset_report, "w") as f:
            f.write(f"# Reset Report: {reset_id}\n\n")
            f.write(f"**Timestamp:** {report['timestamp']}\n")
            f.write(f"**Scope:** {reset_scope}\n")
            f.write(f"**Dry Run:** {dry_run}\n\n")
            f.write("## Actions Taken\n\n")
            for action in report["actions"]:
                f.write(
                    f"- **{action['type']}**: {action.get('path', action.get('database', 'N/A'))}\n"
                )
                if "error" in action:
                    f.write(f"  - Error: {action['error']}\n")

        # Also write JSON for automation
        with open(report_dir / "reset.json", "w") as f:
            json.dump(report, f, indent=2)

        typer.echo(f"📄 Reset report: {reset_report}")

    except Exception as e:
        typer.echo(f"❌ Reset failed: {e}", err=True)
        raise typer.Exit(1)


def _find_resumable_run(settings: Settings) -> Optional[str]:
    """Find the most recent incomplete run that can be resumed."""
    from ..core.artifacts import runs_dir, phase_dir

    runs_base = runs_dir()
    if not runs_base.exists():
        return None

    # Get all run directories sorted by modification time (newest first)
    run_dirs = [d for d in runs_base.iterdir() if d.is_dir()]
    run_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    for run_dir in run_dirs[:5]:  # Check last 5 runs
        run_id = run_dir.name

        # Check if this run is incomplete (missing final phase)
        final_phases = [
            "embed",
            "compose",
            "create",
        ]  # Any of these could be final
        has_final_phase = any(
            phase_dir(run_id, phase).exists()
            for phase in final_phases
            if phase in settings.PIPELINE_PHASES
        )

        if not has_final_phase:
            # Check if it has at least ingest phase
            if phase_dir(run_id, "ingest").exists():
                return run_id

    return None


@app.command()
def config(
    mask_secrets: bool = typer.Option(True, help="Mask secrets in output"),
) -> None:
    for k, v in SETTINGS.model_dump().items():
        if mask_secrets and "TOKEN" in k:
            v = "***"
        typer.echo(f"{k}={v}")


@ingest_app.command("confluence")
def ingest_confluence_cmd(
    space: List[str] = typer.Option(
        [], "--space", help="Confluence space keys"
    ),
    space_id: List[str] = typer.Option(
        [], "--space-id", help="Confluence space ids"
    ),
    since: Optional[str] = typer.Option(
        None, help='ISO timestamp, e.g. "2025-08-01T00:00:00Z"'
    ),
    auto_since: bool = typer.Option(
        False, "--auto-since", help="Auto-read since from state files"
    ),
    body_format: str = typer.Option(
        "atlas_doc_format",
        help="Body format: storage or atlas_doc_format (default: atlas_doc_format)",
    ),
    max_pages: Optional[int] = typer.Option(
        None, help="Stop after N pages (debug)"
    ),
    progress: bool = typer.Option(
        False, "--progress", help="Show per-page progress"
    ),
    progress_every: int = typer.Option(
        1, "--progress-every", help="Progress output every N pages"
    ),
    allow_empty: bool = typer.Option(
        False, "--allow-empty", help="Allow zero pages without error"
    ),
    log_format: str = typer.Option(
        "auto", "--log-format", help="Logging format: json|plain|auto"
    ),
    quiet_pretty: bool = typer.Option(
        False, "--quiet-pretty", help="Suppress banners but keep progress bars"
    ),
    no_color: bool = typer.Option(
        False, "--no-color", help="Disable colored output"
    ),
) -> None:
    from ..core.artifacts import new_run_id, phase_dir
    from ..pipeline.steps.ingest.confluence import ingest_confluence
    from ..core.logging import setup_logging, LogFormat
    from typing import cast
    from ..core.progress import init_progress

    # Setup logging first
    setup_logging(
        format_type=cast(LogFormat, log_format)
        if log_format in ("json", "plain", "auto")
        else "auto"
    )

    # Initialize progress renderer
    progress_renderer = init_progress(
        enabled=progress, quiet_pretty=quiet_pretty, no_color=no_color
    )

    rid = new_run_id()
    out = str(phase_dir(rid, "ingest"))

    try:
        dt = (
            datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since
            else None
        )

        # Determine since mode for banner
        since_mode = "none"
        if auto_since:
            since_mode = "auto-since"
        elif since:
            since_mode = f"since {since}"

        # Show start banner with resumability evidence
        num_spaces = len(space or []) + len(space_id or [])

        # Show resumability evidence if using since mode
        if since or auto_since:
            progress_renderer.resumability_evidence(
                since=since,
                spaces=num_spaces,
                pages_known=0,  # TODO: calculate from state files
                estimated_to_fetch=0,  # TODO: estimate based on CQL query
                skipped_unchanged=0,  # TODO: track during ingest
            )

        progress_renderer.start_banner(
            run_id=rid,
            spaces=num_spaces,
            since_mode=since_mode,
            max_pages=max_pages,
        )

        metrics = ingest_confluence(
            outdir=out,
            space_keys=space or None,
            space_ids=space_id or None,
            since=dt,
            auto_since=auto_since,
            body_format=body_format,
            max_pages=max_pages,
            progress=progress,
            progress_every=progress_every,
            run_id=rid,
        )

        # Check for empty results
        pages_processed = metrics.get("pages", 0)
        if pages_processed == 0:
            if allow_empty:
                log.warning(
                    "cli.ingest.confluence.empty_allowed",
                    run_id=rid,
                    message="No pages processed but --allow-empty set",
                )
            else:
                log.error(
                    "cli.ingest.confluence.empty_not_allowed",
                    run_id=rid,
                    message="No pages processed and --allow-empty not set",
                )
                raise typer.Exit(4)  # Empty result when not allowed

        # Metrics already shown in human-friendly format by pipeline

        # Print run_id to stdout (for scripting)
        typer.echo(rid)

    except ValueError as e:
        # Configuration/parameter error
        log.error("cli.ingest.confluence.config_error", error=str(e))
        typer.echo(f"❌ Configuration error: {e}", err=True)
        raise typer.Exit(2)
    except Exception as e:
        # Check if it's an auth/API error or other remote failure
        error_str = str(e).lower()
        if any(
            keyword in error_str
            for keyword in ["auth", "unauthorized", "forbidden", "401", "403"]
        ):
            log.error("cli.ingest.confluence.auth_error", error=str(e))
            typer.echo(f"❌ Authentication error: {e}", err=True)
            raise typer.Exit(2)
        elif any(
            keyword in error_str
            for keyword in ["connection", "timeout", "network", "api", "http"]
        ):
            log.error("cli.ingest.confluence.api_error", error=str(e))
            typer.echo(f"❌ API/Network error: {e}", err=True)
            raise typer.Exit(3)
        else:
            log.error("cli.ingest.confluence.unknown_error", error=str(e))
            typer.echo(f"❌ Unexpected error: {e}", err=True)
            raise typer.Exit(1)


@ingest_app.command("dita")
def ingest_dita_cmd(
    root: str = typer.Option(
        "data/raw/dita/ellucian-documentation",
        "--root",
        help="Root directory for DITA files",
    ),
    include: List[str] = typer.Option(
        [],
        "--include",
        help="Include glob patterns (default: **/*.dita, **/*.xml, **/*.ditamap)",
    ),
    exclude: List[str] = typer.Option(
        [], "--exclude", help="Exclude glob patterns"
    ),
    progress: bool = typer.Option(
        False, "--progress", help="Show per-file progress"
    ),
    progress_every: int = typer.Option(
        1, "--progress-every", help="Progress output every N files"
    ),
    log_format: str = typer.Option(
        "auto", "--log-format", help="Logging format: json|plain|auto"
    ),
    quiet_pretty: bool = typer.Option(
        False, "--quiet-pretty", help="Suppress banners but keep progress bars"
    ),
    no_color: bool = typer.Option(
        False, "--no-color", help="Disable colored output"
    ),
) -> None:
    """Ingest DITA topics and maps from local filesystem."""
    from ..core.artifacts import new_run_id, phase_dir
    from ..pipeline.steps.ingest.dita import ingest_dita
    from ..core.logging import setup_logging, LogFormat
    from typing import cast
    from ..core.progress import init_progress

    # Setup logging first
    setup_logging(
        format_type=cast(LogFormat, log_format)
        if log_format in ("json", "plain", "auto")
        else "auto"
    )

    # Initialize progress renderer
    progress_renderer = init_progress(
        enabled=progress, quiet_pretty=quiet_pretty, no_color=no_color
    )

    rid = new_run_id()
    out = str(phase_dir(rid, "ingest"))

    try:
        # Show start banner
        progress_renderer.start_banner(
            run_id=rid,
            spaces=1,  # Single root directory
            since_mode=f"root: {root}",
        )

        metrics = ingest_dita(
            outdir=out,
            root=root,
            include=include or None,
            exclude=exclude or None,
            progress=progress,
            progress_every=progress_every,
            run_id=rid,
        )

        log.info("cli.ingest.dita.done", run_id=rid, **metrics)

        # Print run_id to stdout (for scripting)
        typer.echo(rid)

    except Exception as e:
        log.error("cli.ingest.dita.error", run_id=rid, error=str(e))
        raise typer.Exit(1)


@confluence_app.command("spaces")
def confluence_spaces_cmd() -> None:
    """List Confluence spaces with structured logging and artifact output."""
    import json
    from tabulate import tabulate  # type: ignore
    from ..core.artifacts import new_run_id, phase_dir
    from ..adapters.confluence_api import ConfluenceClient

    rid = new_run_id()
    out_dir = phase_dir(rid, "ingest")
    out_dir.mkdir(parents=True, exist_ok=True)

    client = ConfluenceClient()
    spaces = []

    # Collect all spaces
    for space in client.get_spaces():
        space_data = {
            "id": str(space.get("id", "")),
            "key": space.get("key", ""),
            "name": space.get("name", ""),
            "type": space.get("type", ""),
            "status": space.get("status", ""),
            "homepage_id": str(
                space.get("homepageId", "") if space.get("homepageId") else ""
            ),
        }
        spaces.append(space_data)

        # Structured log per space
        log.info("confluence.space", **space_data)

    # Sort for deterministic output
    spaces.sort(key=lambda x: (x["key"], x["id"]))

    # Write spaces.json artifact
    spaces_file = out_dir / "spaces.json"
    with open(spaces_file, "w") as f:
        json.dump(spaces, f, indent=2, sort_keys=True)

    # Pretty console output
    if spaces:
        table_data = [
            [s["id"], s["key"], s["name"], s["type"], s["status"]]
            for s in spaces
        ]
        headers = ["ID", "KEY", "NAME", "TYPE", "STATUS"]
        typer.echo(tabulate(table_data, headers=headers, tablefmt="grid"))
    else:
        typer.echo("No spaces found.")

    typer.echo(f"\n📄 Spaces written to: {spaces_file}")
    log.info(
        "cli.confluence.spaces.done", run_id=rid, spaces_count=len(spaces)
    )


@ingest_app.command("diff-deletions")
def ingest_diff_deletions_cmd(
    space: str = typer.Option(..., "--space", help="Confluence space key"),
    baseline_run: str = typer.Option(
        ..., "--baseline-run", help="Baseline run ID"
    ),
    current_run: str = typer.Option(
        ..., "--current-run", help="Current run ID"
    ),
) -> None:
    """Find deleted page IDs between two runs."""
    import json
    from ..core.artifacts import runs_dir

    runs_base = runs_dir()

    # Read baseline seen IDs
    baseline_file = (
        runs_base / baseline_run / "ingest" / f"{space}_seen_page_ids.json"
    )
    if not baseline_file.exists():
        typer.echo(f"❌ Baseline file not found: {baseline_file}", err=True)
        raise typer.Exit(1)

    with open(baseline_file) as f:
        baseline_ids = set(json.load(f))

    # Read current seen IDs
    current_file = (
        runs_base / current_run / "ingest" / f"{space}_seen_page_ids.json"
    )
    if not current_file.exists():
        typer.echo(f"❌ Current file not found: {current_file}", err=True)
        raise typer.Exit(1)

    with open(current_file) as f:
        current_ids = set(json.load(f))

    # Find deletions (in baseline but not current)
    deleted_ids = sorted(list(baseline_ids - current_ids))

    # Write deletions to current run's ingest dir
    current_ingest_dir = runs_base / current_run / "ingest"
    current_ingest_dir.mkdir(parents=True, exist_ok=True)
    deleted_file = current_ingest_dir / "deleted_ids.json"

    with open(deleted_file, "w") as f:
        json.dump(deleted_ids, f, indent=2, sort_keys=True)

    typer.echo(f"🗑️  Found {len(deleted_ids)} deleted pages in space '{space}'")
    typer.echo(f"📄 Deletions written to: {deleted_file}")

    log.info(
        "cli.ingest.diff_deletions.done",
        space=space,
        baseline_run=baseline_run,
        current_run=current_run,
        deleted_count=len(deleted_ids),
    )


@normalize_app.command("from-ingest")
def normalize_from_ingest_cmd(
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="Run ID to normalize (uses runs/<RUN_ID>/ingest/confluence.ndjson)",
    ),
    input_file: Optional[str] = typer.Option(
        None,
        "--input",
        help="Input NDJSON file to normalize (overrides --run-id)",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Limit number of pages to process"
    ),
) -> None:
    from ..core.artifacts import new_run_id, phase_dir
    from ..pipeline.steps.normalize.html_to_md import normalize_from_ingest

    if not run_id and not input_file:
        raise typer.BadParameter("Either --run-id or --input must be provided")

    # Use provided run_id or create a new one if using input_file
    rid = run_id or new_run_id()
    out = str(phase_dir(rid, "normalize"))

    metrics = normalize_from_ingest(
        outdir=out,
        input_file=input_file,
        limit=limit,
    )
    log.info("cli.normalize.from_ingest.done", **metrics)
    typer.echo(f"Normalized to: {out}")


@db_app.command("check")
def db_check_cmd() -> None:
    """Check database connectivity and pgvector availability."""
    from ..db.engine import check_db_health, get_db_url

    try:
        # Mask credentials in URL for logging
        db_url = get_db_url()
        parsed_url = urlparse(db_url)
        if parsed_url.password:
            safe_url = db_url.replace(parsed_url.password, "***")
        else:
            safe_url = db_url

        typer.echo(f"🔍 Checking database: {safe_url}")

        health_info = check_db_health()

        typer.echo("✅ Database connection successful")
        typer.echo(f"  Engine: {health_info['dialect']}")
        typer.echo(f"  Host: {health_info['host']}")
        typer.echo(f"  Database: {health_info['database']}")
        typer.echo(
            f"  pgvector: {'✅ available' if health_info['pgvector'] else '❌ not available'}"
        )

        # Exit with error if PostgreSQL but no pgvector
        if (
            health_info["dialect"] == "postgresql"
            and not health_info["pgvector"]
        ):
            typer.echo(
                "\n⚠️  pgvector extension not found. Run 'trailblazer db init' or manually:",
                err=True,
            )
            typer.echo(
                "    psql -d your_db -c 'CREATE EXTENSION vector;'", err=True
            )
            raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"❌ Database check failed: {e}", err=True)
        raise typer.Exit(1)


@db_app.command("doctor")
def db_doctor_cmd() -> None:
    """Comprehensive database diagnosis and health check."""
    from ..db.engine import check_db_health, get_db_url

    try:
        # Show parsed DB URL (with masked credentials)
        db_url = get_db_url()
        parsed_url = urlparse(db_url)
        if parsed_url.password:
            safe_url = db_url.replace(parsed_url.password, "***")
        else:
            safe_url = db_url

        typer.echo("🏥 Database Doctor - Comprehensive Health Check")
        typer.echo("=" * 50)
        typer.echo(f"📊 Parsed DB URL: {safe_url}")
        typer.echo(f"🔧 Dialect: {parsed_url.scheme}")
        typer.echo(f"🌐 Host: {parsed_url.hostname or 'localhost'}")
        typer.echo(
            f"🗃️  Database: {parsed_url.path.lstrip('/') if parsed_url.path else 'default'}"
        )

        # Attempt connection and check health
        typer.echo("\n🔗 Testing connection...")
        health_info = check_db_health()

        typer.echo("✅ Connection successful!")
        typer.echo(f"   Engine: {health_info['dialect']}")
        typer.echo(f"   Host: {health_info['host']}")
        typer.echo(f"   Database: {health_info['database']}")

        # Check PostgreSQL specifics
        if health_info["dialect"] == "postgresql":
            typer.echo("\n🐘 PostgreSQL-specific checks:")
            if health_info["pgvector"]:
                typer.echo("   ✅ pgvector extension: available")

                # Check embedding dimensions by querying existing data
                from ..db.engine import get_session

                with get_session() as session:
                    from sqlalchemy import text

                    try:
                        result = session.execute(
                            text(
                                "SELECT DISTINCT dim FROM chunk_embeddings LIMIT 5"
                            )
                        )
                        dims = [row[0] for row in result]
                        if dims:
                            typer.echo(
                                f"   📏 Embedding dimensions found: {dims}"
                            )
                        else:
                            typer.echo(
                                "   📏 No embeddings found (empty database)"
                            )
                    except Exception as e:
                        typer.echo(f"   📏 Could not check embeddings: {e}")
            else:
                typer.echo("   ❌ pgvector extension: NOT available")
                typer.echo("      Run 'trailblazer db init' or manually:")
                typer.echo(
                    "      psql -d your_db -c 'CREATE EXTENSION vector;'"
                )
                raise typer.Exit(1)
        else:
            # Non-PostgreSQL database - not supported
            typer.echo(f"\n❌ Unsupported database: {health_info['dialect']}")
            typer.echo("   Only PostgreSQL is supported.")
            typer.echo("   Run 'make db.up' then 'trailblazer db doctor'")
            raise typer.Exit(1)

        # Final summary
        typer.echo("\n🎉 Database health check completed successfully!")
        typer.echo("   Ready for embed/ask operations")

    except Exception as e:
        typer.echo(f"\n❌ Database doctor failed: {e}", err=True)
        typer.echo("💡 Troubleshooting:")
        typer.echo("   1. Check TRAILBLAZER_DB_URL in your .env file")
        typer.echo("   2. Ensure PostgreSQL is running: make db.up")
        typer.echo("   3. Initialize database: trailblazer db init")
        typer.echo("   4. Verify pgvector extension is installed")
        raise typer.Exit(1)


@db_app.command("init")
def db_init_cmd() -> None:
    """Initialize database schema (safe if tables already exist)."""
    from urllib.parse import urlparse
    from ..db.engine import (
        create_tables,
        get_db_url,
        initialize_postgres_extensions,
        ensure_vector_index,
    )

    db_url = get_db_url()
    # Mask credentials for display
    parsed_url = urlparse(db_url)
    if parsed_url.password:
        safe_url = db_url.replace(parsed_url.password, "***")
    else:
        safe_url = db_url

    typer.echo(f"Initializing database: {safe_url}")

    try:
        # Try to create pgvector extension first if PostgreSQL
        initialize_postgres_extensions()

        # Create tables
        create_tables()
        typer.echo("✅ Database schema initialized successfully")

        # Create vector index if PostgreSQL
        ensure_vector_index()

        # Run a quick health check to confirm everything works
        from ..db.engine import check_db_health

        health_info = check_db_health()
        if (
            health_info["dialect"] == "postgresql"
            and not health_info["pgvector"]
        ):
            typer.echo(
                "⚠️  pgvector extension not detected. You may need to run manually:"
            )
            typer.echo("    psql -d your_db -c 'CREATE EXTENSION vector;'")
        elif (
            health_info["dialect"] == "postgresql" and health_info["pgvector"]
        ):
            typer.echo("✅ pgvector extension ready and vector index created")

    except Exception as e:
        typer.echo(f"❌ Error initializing database: {e}", err=True)
        raise typer.Exit(1)


def _check_dimension_compatibility(
    provider: str, requested_dim: Optional[int]
) -> None:
    """Check if requested dimensions are compatible with existing embeddings.

    Args:
        provider: The embedding provider name
        requested_dim: The requested dimension (if any)

    Raises:
        typer.Exit: If dimension mismatch detected and reembed_all not used
    """
    from ..db.engine import get_session
    from sqlalchemy import text

    if requested_dim is None:
        # Get dimension from provider configuration
        if provider == "openai":
            import os

            requested_dim = int(os.getenv("OPENAI_EMBED_DIM", "1536"))
        elif provider == "dummy":
            requested_dim = 384  # default dummy dimension
        else:
            # For other providers, can't check without actual provider instance
            return

    with get_session() as session:
        try:
            # Check for existing embeddings with this provider
            result = session.execute(
                text(
                    "SELECT DISTINCT dim FROM chunk_embeddings WHERE provider = :provider LIMIT 1"
                ),
                {"provider": provider},
            )
            existing_dims = [row[0] for row in result]

            if existing_dims and existing_dims[0] != requested_dim:
                typer.echo(
                    f"❌ Embedding dimension mismatch (existing={existing_dims[0]}, requested={requested_dim})",
                    err=True,
                )
                typer.echo(
                    "Re-run with '--changed-only=false' and '--reembed-all' (or purge embeddings).",
                    err=True,
                )
                raise typer.Exit(1)
        except Exception:
            # If we can't check, continue (might be empty database)
            pass


@embed_app.command("load")
def embed_load_cmd(
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="Run ID to load (uses runs/<RUN_ID>/chunk/chunks.ndjson)",
    ),
    chunks_file: Optional[str] = typer.Option(
        None,
        "--chunks-file",
        help="Chunks NDJSON file to load (overrides --run-id)",
    ),
    provider: str = typer.Option(
        "dummy",
        "--provider",
        help="Embedding provider (dummy, openai, sentencetransformers)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model name (e.g., text-embedding-3-small, BAAI/bge-small-en-v1.5)",
    ),
    dimension: Optional[int] = typer.Option(
        None,
        "--dimension",
        help="Embedding dimension (e.g., 512, 1024, 1536)",
    ),
    batch_size: int = typer.Option(
        128, "--batch", help="Batch size for embedding generation"
    ),
    max_docs: Optional[int] = typer.Option(
        None, "--max-docs", help="Maximum number of documents to process"
    ),
    max_chunks: Optional[int] = typer.Option(
        None, "--max-chunks", help="Maximum number of chunks to process"
    ),
    changed_only: bool = typer.Option(
        False,
        "--changed-only",
        help="Only embed documents with changed enrichment fingerprints",
    ),
    reembed_all: bool = typer.Option(
        False,
        "--reembed-all",
        help="Force re-embed all documents regardless of fingerprints",
    ),
    dry_run_cost: bool = typer.Option(
        False,
        "--dry-run-cost",
        help="Estimate token count and cost without calling API",
    ),
) -> None:
    """Load pre-chunked data to database with embeddings."""
    # Run database preflight check first
    _run_db_preflight_check()

    # Validate no legacy chunk flags
    _validate_no_legacy_chunk_flags()

    # Validate embed contract: no chunking allowed
    from ..pipeline.steps.embed.loader import (
        _validate_no_chunk_imports,
        _validate_materialized_chunks,
    )

    _validate_no_chunk_imports()
    if run_id:
        _validate_materialized_chunks(run_id)

    # Check dimension compatibility unless we're doing a full re-embed
    if not reembed_all:
        _check_dimension_compatibility(provider, dimension)

    from ..db.engine import get_db_url
    from ..pipeline.steps.embed.loader import load_chunks_to_db

    if not run_id and not chunks_file:
        raise typer.BadParameter(
            "Either --run-id or --chunks-file must be provided"
        )

    db_url = get_db_url()
    # Mask credentials for display
    parsed_url = urlparse(db_url)
    if parsed_url.password:
        safe_url = db_url.replace(parsed_url.password, "***")
    else:
        safe_url = db_url

    typer.echo(f"Loading to database: {safe_url}")
    typer.echo(f"Provider: {provider}")

    try:
        metrics = load_chunks_to_db(
            run_id=run_id,
            chunks_file=chunks_file,
            provider_name=provider,
            model=model,
            dimensions=dimension,
            batch_size=batch_size,
            max_docs=max_docs,
            max_chunks=max_chunks,
            changed_only=changed_only,
            reembed_all=reembed_all,
            dry_run_cost=dry_run_cost,
        )

        # Display summary
        typer.echo("\n📊 Summary:")
        if changed_only:
            typer.echo(
                f"  Documents: {metrics.get('docs_changed', 0)} changed, {metrics.get('docs_unchanged', 0)} unchanged"
            )
        if reembed_all:
            typer.echo("  Mode: Full re-embed (ignoring fingerprints)")
        typer.echo(
            f"  Documents: {metrics.get('docs_embedded', 0)} embedded, {metrics.get('docs_skipped', 0)} skipped"
        )
        typer.echo(
            f"  Chunks: {metrics.get('chunks_embedded', 0)} embedded, {metrics.get('chunks_skipped', 0)} skipped"
        )
        typer.echo(
            f"  Provider: {metrics['provider']} (dim={metrics['dimension']})"
        )
        if metrics.get("model"):
            typer.echo(f"  Model: {metrics['model']}")
        if dry_run_cost:
            typer.echo(
                f"  Estimated tokens: {metrics.get('estimated_tokens', 0):,}"
            )
            if metrics.get("estimated_cost"):
                typer.echo(
                    f"  Estimated cost: ${metrics.get('estimated_cost', 0):.4f}"
                )
        typer.echo(f"  Duration: {metrics['duration_seconds']:.2f}s")

    except Exception as e:
        typer.echo(f"❌ Error loading embeddings: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question to ask"),
    top_k: int = typer.Option(
        8, "--top-k", help="Number of top chunks to retrieve"
    ),
    max_chunks_per_doc: int = typer.Option(
        3, "--max-chunks-per-doc", help="Maximum chunks per document"
    ),
    provider: str = typer.Option(
        "dummy",
        "--provider",
        help="Embedding provider (dummy, openai, sentencetransformers)",
    ),
    max_chars: int = typer.Option(
        6000, "--max-chars", help="Maximum characters in context"
    ),
    format_output: str = typer.Option(
        "text", "--format", help="Output format (text, json)"
    ),
    out_dir: Optional[str] = typer.Option(
        None, "--out", help="Output directory (default: runs/<run_id>/ask/)"
    ),
    db_url: Optional[str] = typer.Option(
        None, "--db-url", help="Database URL override"
    ),
) -> None:
    """Ask a question using dense retrieval over embedded chunks."""
    # Run database preflight check only if not using custom db_url
    # When db_url is provided, the retriever will handle db connection validation
    if not db_url:
        _run_db_preflight_check()

    import json
    import os
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    from ..core.artifacts import new_run_id, phase_dir
    from ..retrieval.dense import create_retriever
    from ..retrieval.pack import (
        pack_context,
        group_by_doc,
        create_context_summary,
    )

    # Setup
    run_id = new_run_id()
    out_path = Path(out_dir) if out_dir else phase_dir(run_id, "ask")
    out_path.mkdir(parents=True, exist_ok=True)

    # Use db_url from parameter or environment
    final_db_url = db_url or os.getenv("TRAILBLAZER_DB_URL")
    if not final_db_url:
        typer.echo("❌ TRAILBLAZER_DB_URL required", err=True)
        raise typer.Exit(1)

    # NDJSON event emitter - outputs to stdout
    def emit_event(event_type: str, **kwargs):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "run_id": run_id,
            **kwargs,
        }
        print(json.dumps(event))

    # Human-readable progress to stderr
    typer.echo(f"🔍 Asking: {question}", err=True)
    typer.echo(f"📁 Output: {out_path}", err=True)
    typer.echo(f"🧠 Provider: {provider}", err=True)

    emit_event(
        "ask.start",
        question=question,
        provider=provider,
        top_k=top_k,
        max_chars=max_chars,
    )

    try:
        # Create retriever
        start_time = time.time()
        retriever = create_retriever(
            db_url=final_db_url, provider_name=provider
        )

        # Perform search with event logging
        search_start = time.time()
        emit_event(
            "search.begin", query=question, top_k=top_k, provider=provider
        )
        hits = retriever.search(question, top_k=top_k)
        emit_event("search.end", total_hits=len(hits))
        search_time = time.time() - search_start

        if not hits:
            typer.echo("❌ No results found", err=True)
            emit_event("ask.no_results")
            raise typer.Exit(1)

        # Group and pack results
        pack_start = time.time()
        grouped_hits = group_by_doc(hits, max_chunks_per_doc)
        context_str = pack_context(grouped_hits, max_chars)
        pack_time = time.time() - pack_start

        total_time = time.time() - start_time

        emit_event(
            "ask.pack_complete",
            total_hits=len(hits),
            selected_hits=len(grouped_hits),
            context_chars=len(context_str),
        )

        # Create timing info
        timing_info = {
            "total_seconds": total_time,
            "search_seconds": search_time,
            "pack_seconds": pack_time,
        }

        # Create summary using the existing function
        summary = create_context_summary(
            question, grouped_hits, provider, timing_info
        )
        summary["run_id"] = run_id

        # Write artifacts
        # 1. hits.jsonl
        hits_file = out_path / "hits.jsonl"
        with open(hits_file, "w") as f:
            for hit in grouped_hits:
                f.write(json.dumps(hit) + "\n")

        # 2. summary.json
        summary_file = out_path / "summary.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)

        # 3. context.txt
        context_file = out_path / "context.txt"
        with open(context_file, "w") as f:
            f.write(context_str)

        emit_event(
            "ask.artifacts_written",
            hits_file=str(hits_file),
            summary_file=str(summary_file),
            context_file=str(context_file),
        )

        # Output results
        if format_output == "json":
            typer.echo(json.dumps(summary, indent=2), err=True)
        else:
            # Text format - show summary to stderr
            typer.echo("\n📊 Results:", err=True)
            typer.echo(f"  Top hits: {len(grouped_hits)}", err=True)
            typer.echo(f"  Documents: {summary['unique_documents']}", err=True)
            typer.echo(
                f"  Characters: {summary['total_characters']:,}", err=True
            )
            typer.echo(
                f"  Score range: {summary['score_stats']['min']:.3f} - {summary['score_stats']['max']:.3f}",
                err=True,
            )
            typer.echo(f"  Duration: {total_time:.2f}s", err=True)

            # Show top few hits
            typer.echo("\n🎯 Top results:", err=True)
            for i, hit in enumerate(grouped_hits[:3]):
                title = hit.get("title", "Untitled")
                url = hit.get("url", "")
                score = hit.get("score", 0.0)
                typer.echo(
                    f"  {i + 1}. {title} (score: {score:.3f})", err=True
                )
                if url:
                    typer.echo(f"     {url}", err=True)

            if len(grouped_hits) > 3:
                typer.echo(
                    f"     ... and {len(grouped_hits) - 3} more", err=True
                )

            typer.echo("\n📄 Context preview (first 200 chars):", err=True)
            preview = context_str[:200].replace("\n", " ")
            typer.echo(
                f"  {preview}{'...' if len(context_str) > 200 else ''}",
                err=True,
            )

        typer.echo(f"\n✅ Artifacts written to: {out_path}", err=True)
        emit_event("ask.complete", total_time=total_time)

    except Exception as e:
        emit_event("ask.error", error=str(e))
        typer.echo(f"❌ Error during retrieval: {e}", err=True)
        raise typer.Exit(1)


@ops_app.command("prune-runs")
def ops_prune_runs_cmd(
    keep: int = typer.Option(
        ..., "--keep", help="Number of newest runs to keep"
    ),
    min_age_days: int = typer.Option(
        ..., "--min-age-days", help="Minimum age in days for deletion"
    ),
    dry_run: bool = typer.Option(
        True, "--dry-run/--no-dry-run", help="Dry run mode (default: true)"
    ),
) -> None:
    """Prune old run artifacts (safe, opt-in)."""
    import json
    import shutil
    from datetime import datetime, timedelta
    from pathlib import Path
    from ..core.artifacts import runs_dir

    runs_base = runs_dir()
    if not runs_base.exists():
        typer.echo("No runs directory found.")
        return

    # Get all run directories sorted by modification time (newest first)
    run_dirs = [d for d in runs_base.iterdir() if d.is_dir()]
    run_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    # Keep newest N runs
    protected_runs = set()
    if len(run_dirs) > keep:
        for i in range(keep):
            protected_runs.add(run_dirs[i].name)
    else:
        # If we have fewer runs than keep, protect all
        for d in run_dirs:
            protected_runs.add(d.name)

    # Read referenced runs from state files
    from ..core.paths import state

    state_dir = state() / "confluence"
    if state_dir.exists():
        for state_file in state_dir.glob("*_state.json"):
            try:
                with open(state_file) as f:
                    state_data = json.load(f)
                    if "last_run_id" in state_data:
                        protected_runs.add(state_data["last_run_id"])
            except Exception as e:
                typer.echo(f"⚠️  Warning: Could not read {state_file}: {e}")

    # Find candidates for deletion
    min_age = timedelta(days=min_age_days)
    now = datetime.now()
    candidates = []

    for run_dir in run_dirs:
        if run_dir.name in protected_runs:
            continue

        # Check age
        modified_time = datetime.fromtimestamp(run_dir.stat().st_mtime)
        if now - modified_time < min_age:
            continue

        candidates.append(
            {
                "run_id": run_dir.name,
                "path": str(run_dir),
                "modified_at": modified_time.isoformat(),
                "age_days": (now - modified_time).days,
            }
        )

    # Sort candidates by age for deterministic output
    candidates.sort(key=lambda x: str(x["modified_at"]))

    # Report
    report = {
        "timestamp": now.isoformat(),
        "dry_run": dry_run,
        "keep": keep,
        "min_age_days": min_age_days,
        "total_runs": len(run_dirs),
        "protected_runs": sorted(list(protected_runs)),
        "candidates": candidates,
        "deleted_count": 0 if dry_run else len(candidates),
    }

    # Write report
    reports_dir = Path("logs")
    reports_dir.mkdir(exist_ok=True)
    report_file = (
        reports_dir / f"prune_report_{now.strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)

    # Output
    typer.echo(f"🗂️  Total runs: {len(run_dirs)}")
    typer.echo(f"🛡️  Protected runs: {len(protected_runs)}")
    typer.echo(f"🗑️  Deletion candidates: {len(candidates)}")

    if candidates:
        typer.echo("\nCandidates for deletion:")
        for candidate in candidates:
            typer.echo(
                f"  - {candidate['run_id']} (age: {candidate['age_days']} days)"
            )

    if not dry_run and candidates:
        typer.echo(f"\n🔥 Deleting {len(candidates)} run directories...")
        for candidate in candidates:
            try:
                shutil.rmtree(str(candidate["path"]))
                typer.echo(f"  ✅ Deleted: {candidate['run_id']}")
            except Exception as e:
                typer.echo(f"  ❌ Failed to delete {candidate['run_id']}: {e}")
        report["deleted_count"] = len(candidates)
        # Update report with final status
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2, sort_keys=True)
    elif dry_run and candidates:
        typer.echo(
            "\n💡 This is a dry run. Use --no-dry-run to actually delete."
        )

    typer.echo(f"\n📄 Report written to: {report_file}")
    log.info(
        "cli.ops.prune_runs.done",
        **{k: v for k, v in report.items() if k != "candidates"},
    )


# ========== Paths Commands ==========


@paths_app.command()
def show(
    json_output: bool = typer.Option(
        False, "--json", help="Output paths as JSON"
    ),
) -> None:
    """Show resolved workspace paths."""
    from ..core import paths
    import json

    path_info = {
        "data": str(paths.data()),
        "workdir": str(paths.workdir()),
        "runs": str(paths.runs()),
        "state": str(paths.state()),
        "logs": str(paths.logs()),
        "cache": str(paths.cache()),
        "tmp": str(paths.tmp()),
    }

    if json_output:
        typer.echo(json.dumps(path_info, indent=2))
    else:
        typer.echo("📁 Workspace Paths")
        typer.echo("==================")
        typer.echo(f"Data (inputs):     {path_info['data']}")
        typer.echo(f"Workdir (managed): {path_info['workdir']}")
        typer.echo("")
        typer.echo("Tool-managed directories:")
        typer.echo(f"  Runs:   {path_info['runs']}")
        typer.echo(f"  State:  {path_info['state']}")
        typer.echo(f"  Logs:   {path_info['logs']}")
        typer.echo(f"  Cache:  {path_info['cache']}")
        typer.echo(f"  Tmp:    {path_info['tmp']}")


@paths_app.command()
def ensure() -> None:
    """Create all workspace directories."""
    from ..core import paths

    paths.ensure_all()
    typer.echo("✅ All workspace directories created")


# ========== Thin Wrapper Commands ==========


def _validate_workspace_only() -> None:
    """Validate that we're only writing to var/ workspace."""
    from ..core import paths

    # Ensure workspace directories exist
    paths.ensure_all()

    # Check for legacy output paths that should not exist (data/ is OK as source)
    legacy_paths = ["./runs", "./state", "./logs"]
    for path in legacy_paths:
        if Path(path).exists():
            typer.echo(
                f"❌ Error: Legacy output path '{path}' exists. All data must be under var/",
                err=True,
            )
            typer.echo(
                "Please run 'trailblazer paths ensure' and migrate data to var/",
                err=True,
            )
            raise typer.Exit(1)


def _get_confluence_spaces() -> List[str]:
    """Get list of all Confluence spaces using the existing command."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "trailblazer.cli.main",
                "confluence",
                "spaces",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        # Parse space keys from the output - assuming JSON format
        import json

        spaces = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    space_data = json.loads(line)
                    if "key" in space_data:
                        spaces.append(space_data["key"])
                except json.JSONDecodeError:
                    continue

        if not spaces:
            typer.echo("⚠️  No Confluence spaces found", err=True)
            typer.echo(
                "💡 Check your Confluence credentials in .env:", err=True
            )
            typer.echo(
                "   CONFLUENCE_BASE_URL=https://your-site.atlassian.net/wiki",
                err=True,
            )
            typer.echo("   CONFLUENCE_EMAIL=your-email@company.com", err=True)
            typer.echo("   CONFLUENCE_API_TOKEN=your-token", err=True)
            typer.echo("   Try: trailblazer confluence spaces", err=True)

        return spaces
    except subprocess.CalledProcessError as e:
        typer.echo("❌ Failed to enumerate Confluence spaces", err=True)
        typer.echo(f"   Error: {e}", err=True)
        typer.echo("💡 Troubleshooting:", err=True)
        typer.echo("   1. Check Confluence credentials in .env file", err=True)
        typer.echo(
            "   2. Test connection: trailblazer confluence spaces", err=True
        )
        typer.echo("   3. Verify CONFLUENCE_BASE_URL format", err=True)
        raise typer.Exit(1)


def _get_runs_needing_normalization() -> List[str]:
    """Get list of run IDs that need normalization."""
    from ..core import paths

    runs_dir = paths.runs()
    runs_needing_norm = []

    if not runs_dir.exists():
        return []

    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue

        ingest_dir = run_dir / "ingest"
        normalize_dir = run_dir / "normalize"

        # Check if ingest exists but normalize doesn't
        if ingest_dir.exists() and not normalize_dir.exists():
            # Check for either confluence.ndjson or dita.ndjson
            if (ingest_dir / "confluence.ndjson").exists() or (
                ingest_dir / "dita.ndjson"
            ).exists():
                runs_needing_norm.append(run_dir.name)

    return sorted(runs_needing_norm)


@app.command()
def plan(
    confluence: bool = typer.Option(
        True, "--confluence/--no-confluence", help="Plan Confluence ingestion"
    ),
    dita: bool = typer.Option(
        True, "--dita/--no-dita", help="Plan DITA ingestion"
    ),
) -> None:
    """
    Dry-run preview showing what would be ingested (no writes).

    This command shows you exactly what 'trailblazer ingest-all' would process
    without actually performing any ingestion. Use this to verify your setup
    before running the full pipeline.

    Example:
        trailblazer plan                    # Preview everything
        trailblazer plan --no-dita          # Preview only Confluence
        trailblazer plan --no-confluence    # Preview only DITA
    """
    _validate_workspace_only()

    typer.echo("🔍 Trailblazer Ingestion Plan (dry-run preview)")
    typer.echo("=" * 50)

    total_items = 0

    if confluence:
        typer.echo("\n📋 Confluence Spaces:")
        try:
            spaces = _get_confluence_spaces()
            typer.echo(f"   Total spaces: {len(spaces)}")
            if spaces:
                typer.echo("   Sample spaces:", err=True)
                for space in spaces[:5]:
                    typer.echo(f"     - {space}", err=True)
                if len(spaces) > 5:
                    typer.echo(
                        f"     ... and {len(spaces) - 5} more", err=True
                    )
            total_items += len(spaces)
        except typer.Exit:
            typer.echo("   ⚠️  Could not enumerate spaces", err=True)

    if dita:
        typer.echo("\n📄 DITA Files:")
        dita_root = Path("data/raw/dita/ellucian-documentation")
        if dita_root.exists():
            dita_files = (
                list(dita_root.glob("**/*.xml"))
                + list(dita_root.glob("**/*.dita"))
                + list(dita_root.glob("**/*.ditamap"))
            )
            typer.echo(f"   Total files: {len(dita_files)}")
            total_items += len(dita_files)
        else:
            typer.echo("   ⚠️  DITA root not found", err=True)

    typer.echo(f"\n📊 Total items to process: {total_items}")
    typer.echo("🔄 To execute: trailblazer ingest-all")
    typer.echo("📝 No files will be written in this preview")


@app.command()
def ingest_all(
    confluence: bool = typer.Option(
        True, "--confluence/--no-confluence", help="Ingest Confluence"
    ),
    dita: bool = typer.Option(True, "--dita/--no-dita", help="Ingest DITA"),
    progress: bool = typer.Option(
        True, "--progress/--no-progress", help="Show progress"
    ),
    progress_every: int = typer.Option(
        10, "--progress-every", help="Progress frequency"
    ),
    no_color: bool = typer.Option(
        False, "--no-color", help="Disable colored output"
    ),
    since: Optional[str] = typer.Option(
        None, "--since", help="ISO timestamp for delta ingestion"
    ),
    auto_since: bool = typer.Option(
        False, "--auto-since", help="Auto-detect since from state"
    ),
    max_pages: Optional[int] = typer.Option(
        None, "--max-pages", help="Debug: limit pages"
    ),
    from_scratch: bool = typer.Option(
        False, "--from-scratch", help="Clear var/state before starting"
    ),
) -> None:
    """
    Ingest all Confluence spaces and DITA files with enforced ADF format.

    This is the main command for full data ingestion. It:
    • Calls 'trailblazer ingest confluence' for every space (ADF enforced)
    • Calls 'trailblazer ingest dita' for all XML files
    • Creates a session index showing all commands executed
    • Validates workspace is var/ only

    Progress and logs are forwarded from underlying commands.
    Run 'trailblazer plan' first to preview what will be processed.

    Examples:
        trailblazer ingest-all                    # Full ingestion
        trailblazer ingest-all --from-scratch     # Clear state first
        trailblazer ingest-all --no-dita          # Confluence only
        trailblazer ingest-all --since 2025-01-01T00:00:00Z  # Delta mode
    """
    _validate_workspace_only()

    if from_scratch:
        from ..core import paths
        import shutil

        state_dir = paths.state()
        if state_dir.exists():
            shutil.rmtree(state_dir)
            typer.echo("🗑️  Cleared var/state for fresh start")
        paths.ensure_all()

    session_id = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    index_file = Path(f"var/runs/INDEX-{session_id}.md")

    typer.echo(f"🚀 Starting full ingestion session: {session_id}")
    typer.echo(f"📋 Session index: {index_file}")

    # Create session index
    with open(index_file, "w") as f:
        f.write(f"# Ingestion Session {session_id}\n\n")
        f.write(f"Started: {datetime.now().isoformat()}\n\n")
        f.write("## Commands Executed\n\n")

    total_runs = 0

    if confluence:
        typer.echo("\n📋 Ingesting Confluence spaces...")
        spaces = _get_confluence_spaces()

        for space in spaces:
            # Build command
            cmd = [
                sys.executable,
                "-m",
                "trailblazer.cli.main",
                "ingest",
                "confluence",
                "--space",
                space,
                "--body-format",
                "atlas_doc_format",  # Enforce ADF
            ]

            if progress:
                cmd.append("--progress")
            if progress_every != 10:
                cmd.extend(["--progress-every", str(progress_every)])
            if no_color:
                cmd.append("--no-color")
            if since:
                cmd.extend(["--since", since])
            if auto_since:
                cmd.append("--auto-since")
            if max_pages:
                cmd.extend(["--max-pages", str(max_pages)])

            # Log to session index
            with open(index_file, "a") as f:
                f.write(f"### Confluence Space: {space}\n")
                f.write(f"```bash\n{' '.join(cmd)}\n```\n\n")

            typer.echo(f"▶️  Ingesting space: {space}")
            typer.echo(f"   Command: {' '.join(cmd)}", err=True)

            try:
                subprocess.run(cmd, check=True)
                total_runs += 1
                typer.echo(f"✅ Completed space: {space}")
            except subprocess.CalledProcessError as e:
                typer.echo(
                    f"❌ Failed space: {space} (exit {e.returncode})", err=True
                )

    if dita:
        typer.echo("\n📄 Ingesting DITA files...")

        # Build command
        cmd = [
            sys.executable,
            "-m",
            "trailblazer.cli.main",
            "ingest",
            "dita",
            "--root",
            "data/raw/dita/ellucian-documentation",
        ]

        if progress:
            cmd.append("--progress")
        if progress_every != 10:
            cmd.extend(["--progress-every", str(progress_every)])
        if no_color:
            cmd.append("--no-color")

        # Log to session index
        with open(index_file, "a") as f:
            f.write("### DITA Files\n")
            f.write(f"```bash\n{' '.join(cmd)}\n```\n\n")

        typer.echo("▶️  Ingesting DITA files")
        typer.echo(f"   Command: {' '.join(cmd)}", err=True)

        try:
            subprocess.run(cmd, check=True)
            total_runs += 1
            typer.echo("✅ Completed DITA ingestion")
        except subprocess.CalledProcessError as e:
            typer.echo(
                f"❌ Failed DITA ingestion (exit {e.returncode})", err=True
            )

    # Finalize session index
    with open(index_file, "a") as f:
        f.write("## Summary\n\n")
        f.write(f"- Total successful runs: {total_runs}\n")
        f.write(f"- Completed: {datetime.now().isoformat()}\n")
        f.write("- All data under: var/\n")
        f.write("- ADF format enforced for Confluence\n")

    typer.echo("\n🎉 Ingestion session complete!")
    typer.echo(f"📊 Total runs: {total_runs}")
    typer.echo(f"📋 Session index: {index_file}")


@app.command()
def normalize_all(
    progress: bool = typer.Option(
        True, "--progress/--no-progress", help="Show progress"
    ),
) -> None:
    """
    Normalize all runs that are missing normalized output.

    Scans var/runs/ for ingest directories that don't have corresponding
    normalize directories and processes them using 'trailblazer normalize from-ingest'.

    This is typically run after 'trailblazer ingest-all' to complete the pipeline.
    Normalization converts raw ingested data to the unified format used downstream.

    Examples:
        trailblazer normalize-all           # Normalize everything needed
        trailblazer normalize-all --no-progress  # Quiet mode
    """
    _validate_workspace_only()

    runs_to_normalize = _get_runs_needing_normalization()

    if not runs_to_normalize:
        typer.echo("✅ All runs are already normalized")
        return

    typer.echo(
        f"🔄 Found {len(runs_to_normalize)} runs needing normalization:"
    )
    for run_id in runs_to_normalize:
        typer.echo(f"  - {run_id}")

    typer.echo()

    successful = 0
    for run_id in runs_to_normalize:
        cmd = [
            sys.executable,
            "-m",
            "trailblazer.cli.main",
            "normalize",
            "from-ingest",
            "--run-id",
            run_id,
        ]

        typer.echo(f"▶️  Normalizing: {run_id}")
        if progress:
            typer.echo(f"   Command: {' '.join(cmd)}", err=True)

        try:
            subprocess.run(cmd, check=True, capture_output=not progress)
            successful += 1
            typer.echo(f"✅ Completed: {run_id}")
        except subprocess.CalledProcessError as e:
            typer.echo(f"❌ Failed: {run_id} (exit {e.returncode})", err=True)

    typer.echo(
        f"\n📊 Normalization complete: {successful}/{len(runs_to_normalize)} successful"
    )


@app.command()
def enrich(
    run_id: str = typer.Argument(
        ..., help="Run ID to enrich (must have normalize phase completed)"
    ),
    llm: bool = typer.Option(
        False,
        "--llm/--no-llm",
        help="Enable LLM-based enrichment (default: off)",
    ),
    max_docs: Optional[int] = typer.Option(
        None, "--max-docs", help="Maximum number of documents to process"
    ),
    budget: Optional[str] = typer.Option(
        None, "--budget", help="Budget limit for LLM usage (soft limit)"
    ),
    min_quality: float = typer.Option(
        0.60, "--min-quality", help="Minimum quality score threshold (0.0-1.0)"
    ),
    max_below_threshold_pct: float = typer.Option(
        0.20,
        "--max-below-threshold-pct",
        help="Maximum percentage of docs below quality threshold",
    ),
    progress: bool = typer.Option(
        True, "--progress/--no-progress", help="Show progress output"
    ),
    no_color: bool = typer.Option(
        False, "--no-color", help="Disable colored output"
    ),
) -> None:
    """
    Enrich normalized documents with metadata and quality signals.

    This command processes normalized documents and adds:
    • Rule-based fields (collections, path_tags, readability, quality flags)
    • New schema fields (fingerprint, section_map, chunk_hints, quality metrics, quality_score)
    • LLM-optional fields (summaries, keywords, taxonomy labels, suggested edges)
    • Enrichment fingerprints for selective re-embedding

    Quality gating: Documents with quality_score below --min-quality are flagged.
    If more than --max-below-threshold-pct of documents are below threshold,
    downstream preflight checks will fail to prevent poor quality embeddings.

    The enrichment phase is DB-free and runs before embedding to prepare
    documents with additional metadata that improves search and retrieval.

    Example:
        trailblazer enrich RUN_ID_HERE                    # Rule-based only
        trailblazer enrich RUN_ID_HERE --llm             # Include LLM enrichment
        trailblazer enrich RUN_ID_HERE --max-docs 100    # Limit processing
    """
    import json
    import time
    from datetime import datetime, timezone

    from ..core.artifacts import phase_dir
    from ..core.progress import get_progress
    from ..obs.events import EventEmitter
    from ..pipeline.steps.enrich import enrich_from_normalized

    # Validate run exists and has normalized data
    normalize_dir = phase_dir(run_id, "normalize")
    if not normalize_dir.exists():
        typer.echo(
            f"❌ Run {run_id} not found or normalize phase not completed",
            err=True,
        )
        raise typer.Exit(1)

    normalized_file = normalize_dir / "normalized.ndjson"
    if not normalized_file.exists():
        typer.echo(
            f"❌ Normalized file not found: {normalized_file}", err=True
        )
        raise typer.Exit(1)

    # Setup output directory
    enrich_dir = phase_dir(run_id, "enrich")
    enrich_dir.mkdir(parents=True, exist_ok=True)

    # Use standardized progress renderer and event emitter
    progress_renderer = get_progress()
    event_emitter = EventEmitter(
        run_id=run_id,
        phase="enrich",
        component="enricher",
    )

    # Compatibility wrapper for enricher callback
    def emit_event(event_type: str, **kwargs):
        """Compatibility wrapper for enricher callback."""
        if "enrich.begin" in event_type:
            event_emitter.enrich_start(metadata=kwargs)
        elif "enrich.doc" in event_type:
            event_emitter.enrich_tick(
                processed=kwargs.get("docs_processed", 0)
            )
        elif "enrich.end" in event_type or "enrich.complete" in event_type:
            event_emitter.enrich_complete(
                total_processed=kwargs.get("docs_total", 0),
                duration_ms=int(kwargs.get("duration_seconds", 0) * 1000),
            )
        elif "enrich.error" in event_type:
            event_emitter.error(kwargs.get("error", "Unknown error"))
        else:
            # Fallback for backward compatibility
            print(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event": event_type,
                        "run_id": run_id,
                        **kwargs,
                    }
                ),
                flush=True,
            )

    # Progress callback for human-readable updates to stderr
    def progress_callback(
        docs_processed: int, rate: float, elapsed: float, docs_llm: int
    ):
        if progress:
            typer.echo(
                f"[ENRICH] docs={docs_processed} rate={rate:.1f}/s elapsed={elapsed:.1f}s llm_used={docs_llm}",
                err=True,
            )

    # Show banner using standardized progress renderer
    if progress and progress_renderer.enabled:
        progress_renderer.console.print(
            "🔄 [bold cyan]Document Enrichment[/bold cyan]"
        )
        progress_renderer.console.print(
            f"📁 Input: [cyan]{normalized_file.name}[/cyan]"
        )
        progress_renderer.console.print(
            f"📂 Output: [cyan]{enrich_dir.name}[/cyan]"
        )
        progress_renderer.console.print(
            f"🧠 LLM enabled: [green]{llm}[/green]"
        )
        if max_docs:
            progress_renderer.console.print(
                f"📊 Max docs: [yellow]{max_docs:,}[/yellow]"
            )
        progress_renderer.console.print("")

    try:
        # Run enrichment
        start_time = time.time()
        stats = enrich_from_normalized(
            run_id=run_id,
            llm_enabled=llm,
            max_docs=max_docs,
            budget=budget,
            min_quality=min_quality,
            max_below_threshold_pct=max_below_threshold_pct,
            progress_callback=progress_callback if progress else None,
            emit_event=emit_event,
        )
        duration = time.time() - start_time

        # Generate assurance report
        assurance_json = enrich_dir / "assurance.json"
        assurance_md = enrich_dir / "assurance.md"

        with open(assurance_json, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)

        # Generate markdown report
        _generate_enrichment_assurance_md(stats, assurance_md)

        # Show completion summary using standardized progress renderer
        if progress and progress_renderer.enabled:
            progress_renderer.console.print("")
            progress_renderer.console.print(
                "📊 [bold green]Enrichment Complete[/bold green]"
            )
            progress_renderer.console.print(
                f"📄 Documents processed: [cyan]{stats['docs_total']:,}[/cyan]"
            )
            if llm:
                progress_renderer.console.print(
                    f"🧠 LLM enriched: [cyan]{stats['docs_llm']:,}[/cyan]"
                )
                progress_renderer.console.print(
                    f"🔗 Suggested edges: [cyan]{stats['suggested_edges_total']:,}[/cyan]"
                )
            progress_renderer.console.print(
                f"⚠️  Quality flags: [yellow]{sum(stats['quality_flags_counts'].values()):,}[/yellow]"
            )
            progress_renderer.console.print(
                f"⏱️  Duration: [blue]{duration:.1f}s[/blue]"
            )
            progress_renderer.console.print(
                f"📄 Assurance: [cyan]{assurance_json}[/cyan]"
            )
            progress_renderer.console.print(
                f"📄 Assurance: [cyan]{assurance_md}[/cyan]"
            )

        emit_event("enrich.complete", duration_seconds=duration)

    except Exception as e:
        emit_event("enrich.error", error=str(e))
        typer.echo(f"❌ Enrichment failed: {e}", err=True)
        raise typer.Exit(1)


def _generate_enrichment_assurance_md(stats: dict, output_path: Path) -> None:
    """Generate a markdown assurance report."""
    content = f"""# Enrichment Assurance Report

**Run ID:** {stats["run_id"]}
**Completed:** {stats["completed_at"]}
**Duration:** {stats["duration_seconds"]}s

## Summary

- **Documents processed:** {stats["docs_total"]:,}
- **LLM enriched:** {stats["docs_llm"]:,}
- **Suggested edges:** {stats["suggested_edges_total"]:,}
- **LLM enabled:** {stats["llm_enabled"]}

## Quality Flags

"""

    if stats["quality_flags_counts"]:
        for flag, count in sorted(stats["quality_flags_counts"].items()):
            content += f"- **{flag}:** {count:,} documents\n"
    else:
        content += "No quality flags detected.\n"

    # Calculate rate safely
    if stats["duration_seconds"] > 0:
        rate = stats["docs_total"] / stats["duration_seconds"]
        content += f"""
## Processing Rate

- **Rate:** {rate:.1f} documents/second
"""
    else:
        content += """
## Processing Rate

- **Rate:** N/A (completed instantly)
"""

    content += """
## Artifacts Generated

- `enriched.jsonl` - Enriched document metadata
- `fingerprints.jsonl` - Enrichment fingerprints for selective re-embedding
"""

    if stats["suggested_edges_total"] > 0:
        content += "- `suggested_edges.jsonl` - LLM-suggested document relationships\n"

    content += """
## Next Steps

Run `trailblazer embed load --run-id {run_id}` to embed the enriched documents into the vector database.
""".format(run_id=stats["run_id"])

    output_path.write_text(content, encoding="utf-8")


@app.command("enrich-sweep")
def enrich_sweep(
    runs_glob: str = typer.Option(
        "var/runs/*", "--runs-glob", help="Glob pattern for run directories"
    ),
    min_quality: float = typer.Option(
        0.60, "--min-quality", help="Minimum quality score threshold (0.0-1.0)"
    ),
    max_below_threshold_pct: float = typer.Option(
        0.20,
        "--max-below-threshold-pct",
        help="Maximum percentage of docs below quality threshold",
    ),
    max_workers: int = typer.Option(
        8, "--max-workers", help="Maximum concurrent workers for enrichment"
    ),
    force: bool = typer.Option(
        False, "--force", help="Recompute even if enriched.jsonl exists"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Discovery only; write candidate lists, don't run enrich",
    ),
    out_dir: str = typer.Option(
        "var/enrich_sweep",
        "--out-dir",
        help="Output directory for sweep results",
    ),
) -> None:
    """
    Enrichment sweep over all runs under var/runs/* (ONLY enrichment).

    Enumerates all run directories, validates each has normalize/normalized.ndjson
    with >0 lines, runs enrich for valid runs, and produces comprehensive reports.

    Outputs under var/enrich_sweep/<TS>/:
    - sweep.json — structured report with runs, statuses, timings, and counts
    - sweep.csv — tabular (rid,status,reason,elapsed_ms,enriched_lines)
    - overview.md — human summary with PASS/BLOCKED/FAIL tables
    - ready_for_chunk.txt — list of RID with PASS
    - blocked.txt — list with RID,reason for MISSING_NORMALIZE
    - failures.txt — list with RID,reason for ENRICH_ERROR
    - log.out — tmux-friendly progress log

    Examples:
        # Dry-run to see how many will run
        trailblazer enrich sweep --dry-run

        # Run enrichment across ALL runs (8 workers), forcing recompute
        trailblazer enrich sweep --force --max-workers 8

        # Then, inspect results
        ls -1 var/enrich_sweep/<TS>/
        sed -n '1,120p' var/enrich_sweep/<TS>/overview.md
        wc -l var/enrich_sweep/<TS>/ready_for_chunk.txt
    """
    import concurrent.futures
    import csv
    import glob
    import json
    import subprocess
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    from ..core.artifacts import runs_dir

    # Create timestamped output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(out_dir) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_output_dir = output_dir / "runs"
    runs_output_dir.mkdir(exist_ok=True)

    # Setup output files
    log_file = output_dir / "log.out"
    sweep_json_file = output_dir / "sweep.json"
    sweep_csv_file = output_dir / "sweep.csv"
    overview_md_file = output_dir / "overview.md"
    ready_file = output_dir / "ready_for_chunk.txt"
    blocked_file = output_dir / "blocked.txt"
    failures_file = output_dir / "failures.txt"

    def log_progress(message: str):
        """Log progress to both stderr and log file."""
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp_str}] {message}"
        typer.echo(log_msg, err=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")

    log_progress(f"🔍 ENRICH SWEEP STARTING - Output: {output_dir}")
    log_progress(f"📂 Discovering runs with pattern: {runs_glob}")

    # Discover runs
    run_dirs = []
    pattern = (
        runs_glob if runs_glob.startswith("var/") else f"var/runs/{runs_glob}"
    )

    for run_path_str in sorted(glob.glob(pattern)):
        run_path = Path(run_path_str)
        if run_path.is_dir():
            run_dirs.append(run_path)

    log_progress(f"📊 Found {len(run_dirs)} run directories")

    # Classify runs
    candidates = []
    blocked = []

    for run_dir in run_dirs:
        run_id = run_dir.name
        normalize_file = run_dir / "normalize" / "normalized.ndjson"

        if not normalize_file.exists():
            blocked.append((run_id, "MISSING_NORMALIZE"))
            continue

        # Check if file has content
        try:
            with open(normalize_file, "r") as f:
                first_line = f.readline()
                if not first_line.strip():
                    blocked.append((run_id, "MISSING_NORMALIZE"))
                    continue
        except Exception:
            blocked.append((run_id, "MISSING_NORMALIZE"))
            continue

        candidates.append(run_id)

    log_progress(f"✅ Candidates: {len(candidates)}, Blocked: {len(blocked)}")

    # Write blocked runs
    with open(blocked_file, "w", encoding="utf-8") as f:
        for run_id, reason in blocked:
            f.write(f"{run_id},{reason}\n")

    if dry_run:
        # Write candidates and exit
        candidates_file = output_dir / "candidates.txt"
        with open(candidates_file, "w", encoding="utf-8") as f:
            for run_id in candidates:
                f.write(f"{run_id}\n")

        log_progress(
            f"🔍 DRY RUN COMPLETE - {len(candidates)} candidates, {len(blocked)} blocked"
        )
        log_progress(f"📄 Candidates: {candidates_file}")
        log_progress(f"📄 Blocked: {blocked_file}")
        return

    # Execute enrichment for candidates
    results = []
    ready_runs = []
    failed_runs = []

    def enrich_single_run(run_id: str) -> dict:
        """Enrich a single run and return result."""
        start_time = time.time()

        try:
            # Build command
            cmd = [
                "trailblazer",
                "enrich",
                run_id,
                "--min-quality",
                str(min_quality),
                "--max-below-threshold-pct",
                str(max_below_threshold_pct),
            ]
            # Note: trailblazer enrich doesn't have a --force flag
            # It will overwrite existing enriched.jsonl by default

            # Capture output
            stdout_file = runs_output_dir / f"{run_id}.out"
            stderr_file = runs_output_dir / f"{run_id}.err"

            with open(stdout_file, "w") as out, open(stderr_file, "w") as err:
                result = subprocess.run(
                    cmd,
                    stdout=out,
                    stderr=err,
                    text=True,
                    timeout=3600,  # 1 hour timeout
                )

            elapsed_ms = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                # Verify enriched.jsonl exists and has content
                enrich_file = runs_dir() / run_id / "enrich" / "enriched.jsonl"
                if enrich_file.exists():
                    with open(enrich_file, "r") as f:
                        line_count = sum(1 for _ in f)
                    if line_count > 0:
                        return {
                            "run_id": run_id,
                            "status": "PASS",
                            "reason": "",
                            "elapsed_ms": elapsed_ms,
                            "enriched_lines": line_count,
                        }

                return {
                    "run_id": run_id,
                    "status": "FAIL",
                    "reason": "ENRICH_ERROR: No enriched output",
                    "elapsed_ms": elapsed_ms,
                    "enriched_lines": 0,
                }
            else:
                # Get last error line from stderr
                try:
                    with open(stderr_file, "r") as f:
                        lines = f.readlines()
                        last_error = (
                            lines[-1].strip() if lines else "Unknown error"
                        )
                except Exception:
                    last_error = f"Exit code {result.returncode}"

                return {
                    "run_id": run_id,
                    "status": "FAIL",
                    "reason": f"ENRICH_ERROR: {last_error}",
                    "elapsed_ms": elapsed_ms,
                    "enriched_lines": 0,
                }

        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "run_id": run_id,
                "status": "FAIL",
                "reason": "ENRICH_ERROR: Timeout after 1 hour",
                "elapsed_ms": elapsed_ms,
                "enriched_lines": 0,
            }
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "run_id": run_id,
                "status": "FAIL",
                "reason": f"ENRICH_ERROR: {str(e)}",
                "elapsed_ms": elapsed_ms,
                "enriched_lines": 0,
            }

    # Process runs with bounded concurrency
    log_progress(
        f"🚀 Processing {len(candidates)} runs with {max_workers} workers"
    )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:
        future_to_run = {
            executor.submit(enrich_single_run, run_id): run_id
            for run_id in candidates
        }

        completed = 0
        for future in concurrent.futures.as_completed(future_to_run):
            run_id = future_to_run[future]
            try:
                result = future.result()
                results.append(result)

                completed += 1
                status = result["status"]
                elapsed_ms = result["elapsed_ms"]
                reason = (
                    f" reason={result['reason']}" if result["reason"] else ""
                )

                log_progress(
                    f"ENRICH [{status}] {run_id} (ms={elapsed_ms}){reason} [{completed}/{len(candidates)}]"
                )

                if status == "PASS":
                    ready_runs.append(run_id)
                else:
                    failed_runs.append((run_id, result["reason"]))

            except Exception as e:
                log_progress(
                    f"ENRICH [FAIL] {run_id} (ms=0) reason=Exception: {str(e)} [{completed + 1}/{len(candidates)}]"
                )
                results.append(
                    {
                        "run_id": run_id,
                        "status": "FAIL",
                        "reason": f"ENRICH_ERROR: {str(e)}",
                        "elapsed_ms": 0,
                        "enriched_lines": 0,
                    }
                )
                failed_runs.append((run_id, f"ENRICH_ERROR: {str(e)}"))
                completed += 1

    # Write output files
    log_progress("📝 Writing output files...")

    # ready_for_chunk.txt
    with open(ready_file, "w", encoding="utf-8") as f:
        for run_id in ready_runs:
            f.write(f"{run_id}\n")

    # failures.txt
    with open(failures_file, "w", encoding="utf-8") as f:
        for run_id, reason in failed_runs:
            f.write(f"{run_id},{reason}\n")

    # sweep.csv
    with open(sweep_csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["rid", "status", "reason", "elapsed_ms", "enriched_lines"]
        )
        for result in results:
            writer.writerow(
                [
                    result["run_id"],
                    result["status"],
                    result["reason"],
                    result["elapsed_ms"],
                    result["enriched_lines"],
                ]
            )

    # sweep.json
    sweep_data = {
        "timestamp": timestamp,
        "runs_glob": runs_glob,
        "parameters": {
            "min_quality": min_quality,
            "max_below_threshold_pct": max_below_threshold_pct,
            "max_workers": max_workers,
            "force": force,
        },
        "summary": {
            "total_discovered": len(run_dirs),
            "candidates": len(candidates),
            "blocked": len(blocked),
            "passed": len(ready_runs),
            "failed": len(failed_runs),
        },
        "results": results,
        "blocked_runs": [
            {"run_id": run_id, "reason": reason} for run_id, reason in blocked
        ],
    }

    with open(sweep_json_file, "w", encoding="utf-8") as f:
        json.dump(sweep_data, f, indent=2)

    # overview.md
    total_runs = len(run_dirs)
    pass_count = len(ready_runs)
    fail_count = len(failed_runs)
    blocked_count = len(blocked)

    overview_content = f"""# Enrichment Sweep Overview

**Timestamp:** {timestamp}
**Output Directory:** {output_dir}
**Runs Pattern:** {runs_glob}

## Summary

- **Total Runs Discovered:** {total_runs:,}
- **Candidates (valid normalize):** {len(candidates):,}
- **Blocked (missing normalize):** {blocked_count:,}
- **Passed Enrichment:** {pass_count:,}
- **Failed Enrichment:** {fail_count:,}

## Parameters

- **Min Quality:** {min_quality}
- **Max Below Threshold %:** {max_below_threshold_pct}
- **Max Workers:** {max_workers}
- **Force Recompute:** {force}

## Results by Status

### PASS ({pass_count:,} runs)
Ready for chunking. See `ready_for_chunk.txt`.

### BLOCKED ({blocked_count:,} runs)
Missing or empty normalize/normalized.ndjson. See `blocked.txt`.

### FAILED ({fail_count:,} runs)
Enrichment errors. See `failures.txt` and individual run logs in `runs/`.

## Next Steps

1. Review failed runs in `failures.txt` and `runs/*.err` files
2. Use `ready_for_chunk.txt` for the next pipeline stage
3. Re-run blocked runs after fixing normalization issues

## Files Generated

- `sweep.json` - Structured data with all results
- `sweep.csv` - Tabular format for analysis
- `ready_for_chunk.txt` - {pass_count:,} runs ready for chunking
- `blocked.txt` - {blocked_count:,} runs missing normalization
- `failures.txt` - {fail_count:,} runs with enrichment errors
- `log.out` - Execution log
- `runs/` - Individual run stdout/stderr logs
"""

    with open(overview_md_file, "w", encoding="utf-8") as f:
        f.write(overview_content)

    # Final summary
    log_progress("✅ ENRICH SWEEP COMPLETE")
    log_progress(
        f"📊 Results: {pass_count} PASS, {fail_count} FAIL, {blocked_count} BLOCKED"
    )
    log_progress(f"📄 Overview: {overview_md_file}")
    log_progress(f"📄 Ready for chunk: {ready_file} ({pass_count:,} runs)")


@app.command()
def chunk(
    run_id: str = typer.Argument(
        ...,
        help="Run ID to chunk (must have enrich or normalize phase completed)",
    ),
    max_tokens: int = typer.Option(
        800, "--max-tokens", help="Hard maximum tokens per chunk"
    ),
    min_tokens: int = typer.Option(
        120, "--min-tokens", help="Minimum tokens per chunk"
    ),
    overlap_tokens: int = typer.Option(
        60, "--overlap-tokens", help="Overlap tokens when splitting"
    ),
    soft_min_tokens: int = typer.Option(
        200,
        "--soft-min-tokens",
        help="Target minimum tokens after glue (v2.2)",
    ),
    hard_min_tokens: int = typer.Option(
        80,
        "--hard-min-tokens",
        help="Absolute minimum tokens for any chunk (v2.2)",
    ),
    orphan_heading_merge: bool = typer.Option(
        True,
        "--orphan-heading-merge/--no-orphan-heading-merge",
        help="Merge orphan headings with neighbors (v2.2)",
    ),
    small_tail_merge: bool = typer.Option(
        True,
        "--small-tail-merge/--no-small-tail-merge",
        help="Merge small tail chunks when possible (v2.2)",
    ),
    progress: bool = typer.Option(
        True, "--progress/--no-progress", help="Show progress output"
    ),
) -> None:
    """
    Chunk enriched or normalized documents into token-bounded pieces.

    This command processes documents and creates chunks suitable for embedding:
    • Guaranteed hard token cap with layered splitting strategy
    • Layered splitting strategy: headings → paragraphs → sentences → token window
    • Special handling for code fences and tables
    • Overlap support for better context continuity
    • Records per-chunk token counts and split strategies

    The chunker prefers enriched input (enriched.jsonl) over normalized input
    (normalized.ndjson) when available. Enriched input enables heading-aware
    chunking with better quality.

    Examples:
        trailblazer chunk RUN_ID_HERE                            # Use defaults (800/120/60 tokens)
        trailblazer chunk RUN_ID_HERE --max-tokens 1000         # Custom token limits
        trailblazer chunk RUN_ID_HERE --overlap-tokens 80       # Custom overlap

        # v2.2 bottom-end controls
        trailblazer chunk RUN_ID_HERE --soft-min-tokens 200 --hard-min-tokens 80
        trailblazer chunk RUN_ID_HERE --no-orphan-heading-merge --no-small-tail-merge
    """
    import time

    from ..core.artifacts import phase_dir
    from ..core.progress import get_progress
    from ..pipeline.runner import _execute_phase
    from ..obs.events import EventEmitter

    # Validate run exists
    run_dir = phase_dir(run_id, "").parent
    if not run_dir.exists():
        typer.echo(f"❌ Run {run_id} not found", err=True)
        raise typer.Exit(1)

    # Check for input files
    enrich_dir = phase_dir(run_id, "enrich")
    normalize_dir = phase_dir(run_id, "normalize")

    enriched_file = enrich_dir / "enriched.jsonl"
    normalized_file = normalize_dir / "normalized.ndjson"

    if enriched_file.exists():
        input_type = "enriched"
        input_file = enriched_file
    elif normalized_file.exists():
        input_type = "normalized"
        input_file = normalized_file
    else:
        typer.echo(
            f"❌ No input files found. Run 'trailblazer enrich {run_id}' or 'trailblazer normalize {run_id}' first",
            err=True,
        )
        raise typer.Exit(1)

    # Create chunk directory
    chunk_dir = phase_dir(run_id, "chunk")
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # Use standardized progress renderer
    progress_renderer = get_progress()

    # Show banner using standardized progress renderer
    if progress and progress_renderer.enabled:
        progress_renderer.console.print(
            "🔄 [bold cyan]Document Chunking[/bold cyan]"
        )
        progress_renderer.console.print(
            f"📁 Input: [cyan]{input_file.name}[/cyan] ({input_type})"
        )
        progress_renderer.console.print(
            f"📂 Output: [cyan]{chunk_dir.name}[/cyan]"
        )
        progress_renderer.console.print(
            f"🔢 Max tokens: [yellow]{max_tokens}[/yellow]"
        )
        progress_renderer.console.print(
            f"🔢 Min tokens: [yellow]{min_tokens}[/yellow]"
        )
        progress_renderer.console.print(
            f"🔗 Overlap tokens: [yellow]{overlap_tokens}[/yellow]"
        )
        progress_renderer.console.print(
            f"📏 Soft min tokens: [yellow]{soft_min_tokens}[/yellow]"
        )
        progress_renderer.console.print(
            f"📏 Hard min tokens: [yellow]{hard_min_tokens}[/yellow]"
        )
        progress_renderer.console.print(
            f"🔀 Orphan heading merge: [green]{orphan_heading_merge}[/green]"
        )
        progress_renderer.console.print(
            f"🔀 Small tail merge: [green]{small_tail_merge}[/green]"
        )
        progress_renderer.console.print("")

    try:
        # Create EventEmitter for chunk events
        emitter = EventEmitter(
            run_id=run_id, phase="chunk", component="chunker"
        )

        # Create wrapper emit function for the engine
        def emit_wrapper(event_type: str, **kwargs):
            """Wrapper emit function to bridge CLI EventEmitter to chunk engine."""
            if event_type == "chunk.begin":
                input_file = kwargs.get("input_file")
                emitter.chunk_start(input_file=input_file)
            elif event_type == "chunk.doc":
                # Use generic _emit for chunk.doc events with chunk-specific data
                from ..obs.events import EventAction

                emitter._emit(EventAction.TICK, **kwargs)
            elif event_type == "chunk.end":
                total_chunks = kwargs.get("total_chunks", 0)
                duration_ms = kwargs.get("duration_ms", 0)
                emitter.chunk_complete(
                    total_chunks=total_chunks, duration_ms=duration_ms
                )
            elif event_type == "chunk.force_truncate":
                emitter.warning(
                    f"Chunk force truncated: {kwargs.get('chunk_id', 'unknown')}",
                    **kwargs,
                )
            elif event_type == "chunk.coverage_warning":
                emitter.warning(
                    f"Coverage warning for doc {kwargs.get('doc_id', 'unknown')}",
                    **kwargs,
                )
            else:
                # Generic event
                from ..obs.events import EventAction

                emitter._emit(EventAction.TICK, **kwargs)

        # Run chunking via pipeline runner with EventEmitter
        start_time = time.time()
        with emitter:
            _execute_phase(
                "chunk",
                str(chunk_dir),
                max_tokens=max_tokens,
                min_tokens=min_tokens,
                overlap_tokens=overlap_tokens,
                soft_min_tokens=soft_min_tokens,
                hard_min_tokens=hard_min_tokens,
                orphan_heading_merge=orphan_heading_merge,
                small_tail_merge=small_tail_merge,
                emit=emit_wrapper,
            )
        duration = time.time() - start_time

        # Read results
        chunks_file = chunk_dir / "chunks.ndjson"
        assurance_file = chunk_dir / "chunk_assurance.json"

        if chunks_file.exists():
            with open(chunks_file) as f:
                chunk_count = sum(1 for line in f if line.strip())
        else:
            chunk_count = 0

        if assurance_file.exists():
            import json

            with open(assurance_file) as f:
                assurance_data = json.load(f)
                doc_count = assurance_data.get("docCount", 0)
                token_stats = assurance_data.get("tokenStats", {})
        else:
            doc_count = 0
            token_stats = {}

        # Show completion summary using standardized progress renderer
        if progress and progress_renderer.enabled:
            progress_renderer.console.print(
                f"✅ [bold green]Chunking complete[/bold green] in [blue]{duration:.1f}s[/blue]"
            )
            progress_renderer.console.print(
                f"📄 Documents: [cyan]{doc_count}[/cyan]"
            )
            progress_renderer.console.print(
                f"🧩 Chunks: [cyan]{chunk_count}[/cyan]"
            )

            if token_stats:
                progress_renderer.console.print(
                    f"🔢 Token range: [yellow]{token_stats.get('min', 0)}-{token_stats.get('max', 0)}[/yellow] "
                    f"(median: [yellow]{token_stats.get('median', 0)}[/yellow])"
                )

            progress_renderer.console.print(
                f"\n📁 Artifacts written to: [cyan]{chunk_dir}[/cyan]"
            )
            progress_renderer.console.print(
                f"   • chunks.ndjson - [cyan]{chunk_count}[/cyan] chunks ready for embedding"
            )
            progress_renderer.console.print(
                "   • chunk_assurance.json - Quality metrics and statistics"
            )

    except Exception as e:
        typer.echo(f"❌ Chunking failed: {e}", err=True)
        raise typer.Exit(1)


chunk_app = typer.Typer(help="Chunking operations for documents")
app.add_typer(chunk_app, name="chunk")


@chunk_app.command("audit")
def chunk_audit(
    runs_glob: str = typer.Option(
        "var/runs/*", "--runs-glob", help="Glob pattern for run directories"
    ),
    max_tokens: int = typer.Option(
        800, "--max-tokens", help="Token limit to check against"
    ),
    out_dir: str = typer.Option(
        "var/chunk_audit",
        "--out-dir",
        help="Output directory for audit results",
    ),
) -> None:
    """
    Audit existing chunks for token limit violations.

    Scans all chunks in the specified runs and identifies any that exceed
    the token limit. Outputs detailed reports and rechunk targets.

    Example:
        trailblazer chunk audit --runs-glob 'var/runs/*' --max-tokens 800
    """
    import json
    import glob
    import statistics
    from datetime import datetime, timezone
    from pathlib import Path
    from ..pipeline.steps.chunk.boundaries import count_tokens

    # Create timestamped output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    audit_dir = Path(out_dir) / timestamp
    audit_dir.mkdir(parents=True, exist_ok=True)

    typer.echo(f"🔍 Auditing chunks with token limit: {max_tokens}", err=True)
    typer.echo(f"📁 Results will be written to: {audit_dir}", err=True)

    oversize_chunks = []
    all_token_counts = []
    run_count = 0
    total_chunks = 0

    # Find all chunk files
    run_dirs = glob.glob(runs_glob)

    for run_dir in run_dirs:
        chunks_file = Path(run_dir) / "chunk" / "chunks.ndjson"
        if not chunks_file.exists():
            continue

        run_id = Path(run_dir).name
        run_count += 1

        try:
            with open(chunks_file, "r") as f:
                for line_num, line in enumerate(f, 1):
                    if not line.strip():
                        continue

                    try:
                        chunk_data = json.loads(line)
                        chunk_id = chunk_data.get(
                            "chunk_id", f"{run_id}:unknown:{line_num}"
                        )
                        text_md = chunk_data.get("text_md", "")
                        recorded_tokens = chunk_data.get("token_count", 0)

                        # Recompute token count to verify
                        actual_tokens = count_tokens(text_md)
                        all_token_counts.append(actual_tokens)
                        total_chunks += 1

                        if actual_tokens > max_tokens:
                            oversize_chunks.append(
                                {
                                    "rid": run_id,
                                    "doc_id": chunk_id.split(":")[0]
                                    if ":" in chunk_id
                                    else run_id,
                                    "chunk_id": chunk_id,
                                    "token_count": actual_tokens,
                                    "recorded_tokens": recorded_tokens,
                                    "char_count": len(text_md),
                                }
                            )

                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            typer.echo(f"⚠️  Error processing {chunks_file}: {e}", err=True)
            continue

    # Generate reports
    oversize_file = audit_dir / "oversize.json"
    with open(oversize_file, "w") as f:
        json.dump(oversize_chunks, f, indent=2)

    # Create histogram
    hist_data: Dict
    if all_token_counts:
        hist_data = {
            "total_chunks": len(all_token_counts),
            "oversize_count": len(oversize_chunks),
            "oversize_percentage": len(oversize_chunks)
            / len(all_token_counts)
            * 100,
            "token_stats": {
                "min": min(all_token_counts),
                "max": max(all_token_counts),
                "median": statistics.median(all_token_counts),
                "p95": statistics.quantiles(all_token_counts, n=20)[18]
                if len(all_token_counts) >= 20
                else max(all_token_counts),
                "mean": statistics.mean(all_token_counts),
            },
            "token_limit": max_tokens,
        }
    else:
        hist_data = {
            "total_chunks": 0,
            "oversize_count": 0,
            "oversize_percentage": 0,
            "token_stats": {},
            "token_limit": max_tokens,
        }

    hist_file = audit_dir / "hist.json"
    with open(hist_file, "w") as f:
        json.dump(hist_data, f, indent=2)

    # Create rechunk targets file
    rechunk_targets = []
    for chunk in oversize_chunks:
        target = f"{chunk['rid']},{chunk['doc_id']}"
        if target not in rechunk_targets:
            rechunk_targets.append(target)

    targets_file = audit_dir / "rechunk_targets.txt"
    with open(targets_file, "w") as f:
        for target in rechunk_targets:
            f.write(target + "\n")

    # Create overview markdown
    overview_md = f"""# Chunk Audit Results

**Audit Date:** {datetime.now(timezone.utc).isoformat()}
**Token Limit:** {max_tokens}
**Runs Processed:** {run_count}
**Total Chunks:** {total_chunks}

## Summary

- **Oversize Chunks:** {len(oversize_chunks)} ({hist_data["oversize_percentage"]:.1f}%)
- **Unique Documents Affected:** {len(rechunk_targets)}

## Token Statistics

- **Min:** {hist_data["token_stats"].get("min", 0)}
- **Median:** {hist_data["token_stats"].get("median", 0)}
- **P95:** {hist_data["token_stats"].get("p95", 0)}
- **Max:** {hist_data["token_stats"].get("max", 0)}

## Files Generated

- `oversize.json` - Detailed list of oversize chunks
- `hist.json` - Token count histogram and statistics
- `rechunk_targets.txt` - List of (rid,doc_id) pairs for re-chunking
"""

    overview_file = audit_dir / "overview.md"
    with open(overview_file, "w") as f:
        f.write(overview_md)

    # Output results
    typer.echo("\n📊 Audit Results:", err=True)
    typer.echo(f"   Runs processed: {run_count}", err=True)
    typer.echo(f"   Total chunks: {total_chunks}", err=True)
    typer.echo(
        f"   Oversize chunks: {len(oversize_chunks)} ({hist_data['oversize_percentage']:.1f}%)",
        err=True,
    )
    typer.echo(f"   Documents affected: {len(rechunk_targets)}", err=True)

    if all_token_counts:
        typer.echo(
            f"   Token range: {hist_data['token_stats']['min']}-{hist_data['token_stats']['max']} (median: {hist_data['token_stats']['median']})",
            err=True,
        )

    typer.echo(f"\n📁 Audit files written to: {audit_dir}", err=True)
    typer.echo(
        f"   • oversize.json - {len(oversize_chunks)} oversize chunks",
        err=True,
    )
    typer.echo(
        f"   • rechunk_targets.txt - {len(rechunk_targets)} documents to re-chunk",
        err=True,
    )
    typer.echo("   • hist.json - Token statistics", err=True)
    typer.echo("   • overview.md - Human-readable summary", err=True)


@chunk_app.command("rechunk")
def chunk_rechunk(
    targets_file: str = typer.Option(
        ..., "--targets-file", help="File with rid,doc_id pairs to re-chunk"
    ),
    max_tokens: int = typer.Option(
        800, "--max-tokens", help="Hard maximum tokens per chunk"
    ),
    min_tokens: int = typer.Option(
        120, "--min-tokens", help="Minimum tokens per chunk"
    ),
    overlap_tokens: int = typer.Option(
        60, "--overlap-tokens", help="Overlap tokens when splitting"
    ),
    out_dir: str = typer.Option(
        "var/chunk_fix", "--out-dir", help="Output directory for fix results"
    ),
) -> None:
    """
    Re-chunk specific documents using Chunking v2.

    Takes a targets file (from chunk audit) and re-chunks only the specified
    documents using the new layered splitting strategy with hard token caps.

    Example:
        trailblazer chunk rechunk --targets-file var/chunk_audit/20240101_120000/rechunk_targets.txt
    """
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    # Import chunking functions from the canonical chunk engine
    from ..pipeline.steps.chunk.engine import (
        chunk_document,
        inject_media_placeholders,
    )

    targets_path = Path(targets_file)
    if not targets_path.exists():
        typer.echo(f"❌ Targets file not found: {targets_file}", err=True)
        raise typer.Exit(1)

    # Create timestamped output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fix_dir = Path(out_dir) / timestamp
    fix_dir.mkdir(parents=True, exist_ok=True)

    typer.echo("🔧 Re-chunking with Chunking v2", err=True)
    typer.echo(f"   Hard max tokens: {max_tokens}", err=True)
    typer.echo(f"   Min tokens: {min_tokens}", err=True)
    typer.echo(f"   Overlap tokens: {overlap_tokens}", err=True)
    typer.echo(f"📁 Results will be written to: {fix_dir}", err=True)

    # Read targets
    targets = []
    with open(targets_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and "," in line:
                rid, doc_id = line.split(",", 1)
                targets.append((rid.strip(), doc_id.strip()))

    typer.echo(f"📋 Found {len(targets)} documents to re-chunk", err=True)

    processed_count = 0
    skipped_docs = []
    success_count = 0

    for rid, doc_id in targets:
        try:
            # Find the original document
            run_dir = Path("var/runs") / rid
            enrich_file = run_dir / "enrich" / "enriched.jsonl"
            normalize_file = run_dir / "normalize" / "normalized.ndjson"

            record = None
            input_type = None

            # Try enriched first
            if enrich_file.exists():
                with open(enrich_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("id") == doc_id:
                            record = data
                            input_type = "enriched"
                            break

            # Fall back to normalized
            if not record and normalize_file.exists():
                with open(normalize_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("id") == doc_id:
                            record = data
                            input_type = "normalized"
                            break

            if not record:
                skipped_docs.append(
                    {
                        "doc_id": doc_id,
                        "rid": rid,
                        "reason": "Document not found in enriched or normalized files",
                    }
                )
                continue

            # Re-chunk using the canonical chunk engine
            doc_id = record.get("id", "")
            title = record.get("title", "")
            text_md = record.get("text_md", "")
            attachments = record.get("attachments", [])

            if not doc_id:
                typer.echo("⚠️ Skipping record with missing id", err=True)
                continue

            # Inject media placeholders
            text_with_media = inject_media_placeholders(text_md, attachments)

            if input_type == "enriched":
                # Use enrichment data for better chunking
                chunk_hints = record.get("chunk_hints", {})
                section_map = record.get("section_map", [])

                new_chunks = chunk_document(
                    doc_id=doc_id,
                    text_md=text_with_media,
                    title=title,
                    source_system=record.get("source_system", ""),
                    labels=record.get("labels", []),
                    space=record.get("space"),
                    media_refs=attachments,
                    hard_max_tokens=chunk_hints.get("maxTokens", max_tokens),
                    min_tokens=chunk_hints.get("minTokens", min_tokens),
                    overlap_tokens=chunk_hints.get(
                        "overlapTokens", overlap_tokens
                    ),
                    soft_min_tokens=chunk_hints.get("softMinTokens", 200),
                    hard_min_tokens=chunk_hints.get("hardMinTokens", 80),
                    prefer_headings=chunk_hints.get("preferHeadings", True),
                    soft_boundaries=chunk_hints.get("softBoundaries", []),
                    section_map=section_map,
                )
            else:
                # Normalized data - use default parameters
                new_chunks = chunk_document(
                    doc_id=doc_id,
                    text_md=text_with_media,
                    title=title,
                    source_system=record.get("source_system", ""),
                    labels=record.get("labels", []),
                    space=record.get("space"),
                    media_refs=attachments,
                    hard_max_tokens=max_tokens,
                    min_tokens=min_tokens,
                    overlap_tokens=overlap_tokens,
                )

            # Verify no chunks exceed the limit
            oversized = [
                chunk for chunk in new_chunks if chunk.token_count > max_tokens
            ]
            if oversized:
                skipped_docs.append(
                    {
                        "doc_id": doc_id,
                        "rid": rid,
                        "reason": f"Still has {len(oversized)} chunks exceeding {max_tokens} tokens after rechunking",
                    }
                )
                continue

            # Write back to chunk file
            chunk_dir = run_dir / "chunk"
            chunks_file = chunk_dir / "chunks.ndjson"

            if chunks_file.exists():
                # Read existing chunks, replace ones for this doc
                existing_chunks = []
                with open(chunks_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        chunk_data = json.loads(line)
                        chunk_id = chunk_data.get("chunk_id", "")
                        # Keep chunks that don't belong to this doc
                        if not chunk_id.startswith(f"{doc_id}:"):
                            existing_chunks.append(chunk_data)

                # Add new chunks
                for chunk in new_chunks:
                    chunk_dict = {
                        "chunk_id": chunk.chunk_id,
                        "text_md": chunk.text_md,
                        "char_count": chunk.char_count,
                        "token_count": chunk.token_count,
                        "ord": chunk.ord,
                        "chunk_type": chunk.chunk_type,
                        "meta": chunk.meta,
                        "split_strategy": chunk.split_strategy,
                    }
                    existing_chunks.append(chunk_dict)

                # Write back
                with open(chunks_file, "w") as f:
                    for chunk_data in existing_chunks:
                        f.write(json.dumps(chunk_data) + "\n")

            success_count += 1
            processed_count += 1

            if processed_count % 10 == 0:
                typer.echo(
                    f"   Processed {processed_count}/{len(targets)} documents...",
                    err=True,
                )

        except Exception as e:
            skipped_docs.append(
                {
                    "doc_id": doc_id,
                    "rid": rid,
                    "reason": f"Error during rechunking: {str(e)}",
                }
            )
            processed_count += 1

    # Write skipped docs log
    if skipped_docs:
        skipped_file = fix_dir / "skipped_docs.jsonl"
        with open(skipped_file, "w") as f:
            for doc in skipped_docs:
                f.write(json.dumps(doc) + "\n")

    # Create summary
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "targets_processed": len(targets),
        "successful_rechunks": success_count,
        "skipped_docs": len(skipped_docs),
        "chunking_parameters": {
            "hard_max_tokens": max_tokens,
            "min_tokens": min_tokens,
            "overlap_tokens": overlap_tokens,
        },
    }

    summary_file = fix_dir / "rechunk_summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    # Output results
    typer.echo("\n✅ Re-chunking complete!", err=True)
    typer.echo(f"   Targets processed: {len(targets)}", err=True)
    typer.echo(f"   Successful re-chunks: {success_count}", err=True)
    typer.echo(f"   Skipped documents: {len(skipped_docs)}", err=True)

    if skipped_docs:
        typer.echo("\n⚠️  Some documents were skipped:", err=True)
        for doc in skipped_docs[:5]:  # Show first 5
            typer.echo(
                f"   • {doc['doc_id']} ({doc['rid']}): {doc['reason']}",
                err=True,
            )
        if len(skipped_docs) > 5:
            typer.echo(
                f"   ... and {len(skipped_docs) - 5} more (see skipped_docs.jsonl)",
                err=True,
            )

    typer.echo(f"\n📁 Fix files written to: {fix_dir}", err=True)
    typer.echo("   • rechunk_summary.json - Summary of operation", err=True)
    if skipped_docs:
        typer.echo(
            f"   • skipped_docs.jsonl - {len(skipped_docs)} skipped documents",
            err=True,
        )


@chunk_app.command("verify")
def chunk_verify(
    runs_glob: str = typer.Option(
        "var/runs/*", "--runs-glob", help="Glob pattern for run directories"
    ),
    max_tokens: int = typer.Option(
        800, "--max-tokens", help="Maximum token limit to verify against"
    ),
    soft_min: int = typer.Option(
        200, "--soft-min", help="Soft minimum token threshold for v2.2"
    ),
    hard_min: int = typer.Option(
        80, "--hard-min", help="Hard minimum token threshold for v2.2"
    ),
    require_traceability: bool = typer.Option(
        True,
        "--require-traceability",
        help="Require traceability fields (title|url, source_system)",
    ),
    out_dir: str = typer.Option(
        "var/chunk_verify",
        "--out-dir",
        help="Output directory for verification results",
    ),
) -> None:
    """
    Verify all chunks across runs for token cap compliance and traceability.

    Re-tokenizes all emitted chunks and asserts:
    - token_count <= max_tokens for every chunk
    - If --require-traceability, each chunk has title OR url, and source_system

    On violation → exit 1 and write:
    - report.json, report.md, breaches.json (oversize)
    - missing_traceability.json
    - log.out

    Examples:
        # Basic verification with v2.2 parameters
        trailblazer chunk verify --runs-glob 'var/runs/*' --max-tokens 800 --soft-min 200 --hard-min 80 --require-traceability true

        # After upgrading to v2.2, verify all runs
        trailblazer chunk verify --runs-glob 'var/runs/*' --max-tokens 800 --soft-min 200 --hard-min 80

        # If verify flags small tails or gaps, use audit and rechunk
        trailblazer chunk audit --runs-glob 'var/runs/*' --max-tokens 800
        trailblazer chunk rechunk --targets-file var/chunk_audit/<TS>/rechunk_targets.txt --max-tokens 800 --min-tokens 120 --overlap-tokens 60
        trailblazer chunk verify --runs-glob 'var/runs/*' --max-tokens 800 --soft-min 200 --hard-min 80
    """
    from ..pipeline.steps.chunk.verify import verify_chunks

    typer.echo("🔍 Verifying chunks across runs", err=True)
    typer.echo(f"   Runs pattern: {runs_glob}", err=True)
    typer.echo(f"   Max tokens: {max_tokens}", err=True)
    typer.echo(f"   Soft min: {soft_min}", err=True)
    typer.echo(f"   Hard min: {hard_min}", err=True)
    typer.echo(f"   Require traceability: {require_traceability}", err=True)

    try:
        report = verify_chunks(
            runs_glob=runs_glob,
            max_tokens=max_tokens,
            soft_min=soft_min,
            hard_min=hard_min,
            require_traceability=require_traceability,
            out_dir=out_dir,
        )

        typer.echo("\n📊 Verification Results:", err=True)
        typer.echo(
            f"   Total runs: {report['statistics']['total_runs']}", err=True
        )
        typer.echo(
            f"   Total chunks: {report['statistics']['total_chunks']}",
            err=True,
        )
        typer.echo(
            f"   Oversize violations: {report['violations']['oversize_chunks']}",
            err=True,
        )
        typer.echo(
            f"   Missing traceability: {report['violations']['missing_traceability']}",
            err=True,
        )

        if report["status"] == "PASS":
            typer.echo("\n✅ All chunks pass verification", err=True)
            return
        else:
            typer.echo("\n❌ Chunks failed verification", err=True)
            typer.echo(
                "📁 Detailed reports written to verification output directory",
                err=True,
            )
            raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"❌ Verification failed: {e}", err=True)
        raise typer.Exit(1)


@app.command("chunk-sweep")
def chunk_sweep(
    input_file: str = typer.Option(
        ..., "--input-file", help="Input file with list of run IDs to chunk"
    ),
    max_tokens: int = typer.Option(
        800, "--max-tokens", help="Maximum tokens per chunk"
    ),
    min_tokens: int = typer.Option(
        120, "--min-tokens", help="Minimum tokens per chunk"
    ),
    max_workers: int = typer.Option(
        8, "--max-workers", help="Maximum concurrent workers for chunking"
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-chunk even if files exist"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List targets only; no chunking"
    ),
    out_dir: str = typer.Option(
        "var/chunk_sweep",
        "--out-dir",
        help="Output directory for sweep results",
    ),
) -> None:
    """
    Chunk sweep over runs listed in input file (ONLY chunking).

    Reads run IDs from input file, validates each has enrich/enriched.jsonl
    with >0 lines, runs chunk for valid runs, and produces comprehensive reports.

    Outputs under var/chunk_sweep/<TS>/:
    - sweep.json — structured report with runs, statuses, timings, and counts
    - sweep.csv — tabular (rid,status,reason,elapsed_ms,chunk_lines,tokens_total,tokens_p95)
    - overview.md — human summary with PASS/BLOCKED/FAIL tables
    - ready_for_preflight.txt — list of RID with PASS
    - blocked.txt — list with RID,reason for MISSING_ENRICH
    - failures.txt — list with RID,reason for CHUNK_ERROR
    - log.out — tmux-friendly progress log
    - runs/ — individual run stdout/stderr logs

    Examples:
        # Dry-run to confirm targets
        trailblazer chunk sweep --input-file var/enrich_sweep/20250818_184044/ready_for_chunk.txt --dry-run

        # Run chunking across all targets (8 workers), forcing recompute
        trailblazer chunk sweep \\
          --input-file var/enrich_sweep/20250818_184044/ready_for_chunk.txt \\
          --force --max-workers 8

        # Inspect results
        ls -1 var/chunk_sweep/<TS>/
        sed -n '1,120p' var/chunk_sweep/<TS>/overview.md
        wc -l var/chunk_sweep/<TS>/ready_for_preflight.txt
    """
    import concurrent.futures
    import csv
    import json
    import subprocess
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    from ..core.artifacts import runs_dir

    # Validate input file exists
    input_path = Path(input_file)
    if not input_path.exists():
        typer.echo(f"❌ Input file not found: {input_file}", err=True)
        raise typer.Exit(1)

    # Create timestamped output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(out_dir) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_output_dir = output_dir / "runs"
    runs_output_dir.mkdir(exist_ok=True)

    # Setup output files
    log_file = output_dir / "log.out"
    sweep_json_file = output_dir / "sweep.json"
    sweep_csv_file = output_dir / "sweep.csv"
    overview_md_file = output_dir / "overview.md"
    ready_file = output_dir / "ready_for_preflight.txt"
    blocked_file = output_dir / "blocked.txt"
    failures_file = output_dir / "failures.txt"

    def log_progress(message: str):
        """Log progress to both stderr and log file."""
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp_str}] {message}"
        typer.echo(log_msg, err=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")

    log_progress(f"🔍 CHUNK SWEEP STARTING - Output: {output_dir}")
    log_progress(f"📂 Loading targets from: {input_file}")

    # Load targets from input file
    targets = []
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    targets.append(line)
    except Exception as e:
        typer.echo(f"❌ Failed to read input file: {e}", err=True)
        raise typer.Exit(1)

    # Sort deterministically
    targets = sorted(targets)
    log_progress(f"📊 Loaded {len(targets)} target runs")

    # Classify runs
    candidates = []
    blocked = []

    for run_id in targets:
        enrich_file = runs_dir() / run_id / "enrich" / "enriched.jsonl"

        if not enrich_file.exists():
            blocked.append((run_id, "MISSING_ENRICH"))
            continue

        # Check if file has content
        try:
            with open(enrich_file, "r") as f:
                first_line = f.readline()
                if not first_line.strip():
                    blocked.append((run_id, "MISSING_ENRICH"))
                    continue
        except Exception:
            blocked.append((run_id, "MISSING_ENRICH"))
            continue

        candidates.append(run_id)

    log_progress(f"✅ Candidates: {len(candidates)}, Blocked: {len(blocked)}")

    # Write blocked runs
    with open(blocked_file, "w", encoding="utf-8") as f:
        for run_id, reason in blocked:
            f.write(f"{run_id},{reason}\n")

    if dry_run:
        # Write candidates and exit
        candidates_file = output_dir / "candidates.txt"
        with open(candidates_file, "w", encoding="utf-8") as f:
            for run_id in candidates:
                f.write(f"{run_id}\n")

        log_progress(
            f"🔍 DRY RUN COMPLETE - {len(candidates)} candidates, {len(blocked)} blocked"
        )
        log_progress(f"📄 Candidates: {candidates_file}")
        log_progress(f"📄 Blocked: {blocked_file}")
        return

    # Execute chunking for candidates
    results = []
    ready_runs = []
    failed_runs = []

    def chunk_single_run(run_id: str) -> dict:
        """Chunk a single run and return result."""
        start_time = time.time()

        try:
            # Build command
            cmd = [
                "trailblazer",
                "chunk",
                run_id,
                "--max-tokens",
                str(max_tokens),
                "--min-tokens",
                str(min_tokens),
            ]
            # Note: trailblazer chunk doesn't have a --force flag
            # It will overwrite existing chunks.ndjson by default

            # Capture output
            stdout_file = runs_output_dir / f"{run_id}.out"
            stderr_file = runs_output_dir / f"{run_id}.err"

            with open(stdout_file, "w") as out, open(stderr_file, "w") as err:
                result = subprocess.run(
                    cmd,
                    stdout=out,
                    stderr=err,
                    text=True,
                    timeout=3600,  # 1 hour timeout
                )

            elapsed_ms = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                # Verify chunks.ndjson exists and has content
                chunk_file = runs_dir() / run_id / "chunk" / "chunks.ndjson"
                assurance_file = (
                    runs_dir() / run_id / "chunk" / "chunk_assurance.json"
                )

                if chunk_file.exists() and assurance_file.exists():
                    with open(chunk_file, "r") as f:
                        chunk_lines = sum(1 for _ in f)

                    # Parse assurance for token stats
                    try:
                        with open(assurance_file, "r") as f:
                            assurance_data = json.load(f)
                        token_stats = assurance_data.get("tokenStats", {})
                        tokens_total = token_stats.get("total", 0)
                        tokens_p95 = token_stats.get("p95", 0)
                    except Exception:
                        tokens_total = 0
                        tokens_p95 = 0

                    if chunk_lines > 0:
                        return {
                            "run_id": run_id,
                            "status": "PASS",
                            "reason": "",
                            "elapsed_ms": elapsed_ms,
                            "chunk_lines": chunk_lines,
                            "tokens_total": tokens_total,
                            "tokens_p95": tokens_p95,
                        }

                return {
                    "run_id": run_id,
                    "status": "FAIL",
                    "reason": "CHUNK_ERROR: No chunk output",
                    "elapsed_ms": elapsed_ms,
                    "chunk_lines": 0,
                    "tokens_total": 0,
                    "tokens_p95": 0,
                }
            else:
                # Get last error line from stderr
                try:
                    with open(stderr_file, "r") as f:
                        lines = f.readlines()
                        last_error = (
                            lines[-1].strip() if lines else "Unknown error"
                        )
                except Exception:
                    last_error = f"Exit code {result.returncode}"

                return {
                    "run_id": run_id,
                    "status": "FAIL",
                    "reason": f"CHUNK_ERROR: {last_error}",
                    "elapsed_ms": elapsed_ms,
                    "chunk_lines": 0,
                    "tokens_total": 0,
                    "tokens_p95": 0,
                }

        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "run_id": run_id,
                "status": "FAIL",
                "reason": "CHUNK_ERROR: Timeout after 1 hour",
                "elapsed_ms": elapsed_ms,
                "chunk_lines": 0,
                "tokens_total": 0,
                "tokens_p95": 0,
            }
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "run_id": run_id,
                "status": "FAIL",
                "reason": f"CHUNK_ERROR: {str(e)}",
                "elapsed_ms": elapsed_ms,
                "chunk_lines": 0,
                "tokens_total": 0,
                "tokens_p95": 0,
            }

    # Process runs with bounded concurrency
    log_progress(
        f"🚀 Processing {len(candidates)} runs with {max_workers} workers"
    )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:
        future_to_run = {
            executor.submit(chunk_single_run, run_id): run_id
            for run_id in candidates
        }

        completed = 0
        for future in concurrent.futures.as_completed(future_to_run):
            run_id = future_to_run[future]
            try:
                result = future.result()
                results.append(result)

                completed += 1
                status = result["status"]
                elapsed_ms = result["elapsed_ms"]
                reason = (
                    f" reason={result['reason']}" if result["reason"] else ""
                )

                log_progress(
                    f"CHUNK [{status}] {run_id} (ms={elapsed_ms}){reason} [{completed}/{len(candidates)}]"
                )

                if status == "PASS":
                    ready_runs.append(run_id)
                else:
                    failed_runs.append((run_id, result["reason"]))

            except Exception as e:
                log_progress(
                    f"CHUNK [FAIL] {run_id} (ms=0) reason=Exception: {str(e)} [{completed + 1}/{len(candidates)}]"
                )
                results.append(
                    {
                        "run_id": run_id,
                        "status": "FAIL",
                        "reason": f"CHUNK_ERROR: {str(e)}",
                        "elapsed_ms": 0,
                        "chunk_lines": 0,
                        "tokens_total": 0,
                        "tokens_p95": 0,
                    }
                )
                failed_runs.append((run_id, f"CHUNK_ERROR: {str(e)}"))
                completed += 1

    # Write output files
    log_progress("📝 Writing output files...")

    # ready_for_preflight.txt
    with open(ready_file, "w", encoding="utf-8") as f:
        for run_id in ready_runs:
            f.write(f"{run_id}\n")

    # failures.txt
    with open(failures_file, "w", encoding="utf-8") as f:
        for run_id, reason in failed_runs:
            f.write(f"{run_id},{reason}\n")

    # sweep.csv
    with open(sweep_csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "rid",
                "status",
                "reason",
                "elapsed_ms",
                "chunk_lines",
                "tokens_total",
                "tokens_p95",
            ]
        )
        for result in results:
            writer.writerow(
                [
                    result["run_id"],
                    result["status"],
                    result["reason"],
                    result["elapsed_ms"],
                    result["chunk_lines"],
                    result["tokens_total"],
                    result["tokens_p95"],
                ]
            )

    # Calculate totals for summary
    total_chunk_lines = sum(
        r["chunk_lines"] for r in results if r["status"] == "PASS"
    )
    total_tokens = sum(
        r["tokens_total"] for r in results if r["status"] == "PASS"
    )

    # sweep.json
    sweep_data = {
        "timestamp": timestamp,
        "input_file": input_file,
        "parameters": {
            "max_tokens": max_tokens,
            "min_tokens": min_tokens,
            "max_workers": max_workers,
            "force": force,
        },
        "summary": {
            "total_targets": len(targets),
            "candidates": len(candidates),
            "blocked": len(blocked),
            "passed": len(ready_runs),
            "failed": len(failed_runs),
            "total_chunks": total_chunk_lines,
            "total_tokens": total_tokens,
        },
        "results": results,
        "blocked_runs": [
            {"run_id": run_id, "reason": reason} for run_id, reason in blocked
        ],
    }

    with open(sweep_json_file, "w", encoding="utf-8") as f:
        json.dump(sweep_data, f, indent=2)

    # overview.md
    total_targets = len(targets)
    pass_count = len(ready_runs)
    fail_count = len(failed_runs)
    blocked_count = len(blocked)

    overview_content = f"""# Chunk Sweep Overview

**Timestamp:** {timestamp}
**Output Directory:** {output_dir}
**Input File:** {input_file}

## Summary

- **Total Targets:** {total_targets:,}
- **Candidates (valid enrich):** {len(candidates):,}
- **Blocked (missing enrich):** {blocked_count:,}
- **Passed Chunking:** {pass_count:,}
- **Failed Chunking:** {fail_count:,}

## Chunk Statistics

- **Total Chunks Created:** {total_chunk_lines:,}
- **Total Tokens:** {total_tokens:,}
- **Average Chunks per Run:** {total_chunk_lines / max(1, pass_count):.1f}

## Parameters

- **Max Tokens:** {max_tokens}
- **Min Tokens:** {min_tokens}
- **Max Workers:** {max_workers}
- **Force Recompute:** {force}

## Results by Status

### PASS ({pass_count:,} runs)
Ready for preflight and embedding. See `ready_for_preflight.txt`.

### BLOCKED ({blocked_count:,} runs)
Missing or empty enrich/enriched.jsonl. See `blocked.txt`.

### FAILED ({fail_count:,} runs)
Chunking errors. See `failures.txt` and individual run logs in `runs/`.

## Next Steps

1. Review failed runs in `failures.txt` and `runs/*.err` files
2. Use `ready_for_preflight.txt` for the preflight and embedding phase
3. Re-run blocked runs after fixing enrichment issues

## Files Generated

- `sweep.json` - Structured data with all results
- `sweep.csv` - Tabular format for analysis
- `ready_for_preflight.txt` - {pass_count:,} runs ready for preflight
- `blocked.txt` - {blocked_count:,} runs missing enrichment
- `failures.txt` - {fail_count:,} runs with chunking errors
- `log.out` - Execution log
- `runs/` - Individual run stdout/stderr logs
"""

    with open(overview_md_file, "w", encoding="utf-8") as f:
        f.write(overview_content)

    # Final summary
    log_progress("✅ CHUNK SWEEP COMPLETE")
    log_progress(
        f"📊 Results: {pass_count} PASS, {fail_count} FAIL, {blocked_count} BLOCKED"
    )
    log_progress(
        f"📊 Chunks: {total_chunk_lines:,} chunks, {total_tokens:,} tokens"
    )
    log_progress(f"📄 Overview: {overview_md_file}")
    log_progress(f"📄 Ready for preflight: {ready_file} ({pass_count:,} runs)")


@app.command()
def status() -> None:
    """
    Show quick status of last runs and totals.

    Displays an overview of your workspace including:
    • Total runs and recent activity
    • Breakdown by source (Confluence vs DITA)
    • Normalization status and pending work
    • Disk usage summary

    Use this to check progress and see what needs attention.

    Example:
        trailblazer status    # Show current workspace status
    """
    _validate_workspace_only()

    from ..core import paths

    typer.echo("📊 Trailblazer Status")
    typer.echo("=" * 30)

    # Check runs directory
    runs_dir = paths.runs()
    if not runs_dir.exists():
        typer.echo("📁 No runs directory found")
        return

    # Get all runs
    all_runs = sorted(
        [d.name for d in runs_dir.iterdir() if d.is_dir()], reverse=True
    )

    if not all_runs:
        typer.echo("📁 No runs found")
        return

    typer.echo(f"📂 Total runs: {len(all_runs)}")
    typer.echo(f"🕐 Latest: {all_runs[0]}")

    # Analyze recent runs
    confluence_runs = []
    dita_runs = []
    normalized_runs = []

    for run_id in all_runs[:10]:  # Check last 10 runs
        run_dir = runs_dir / run_id
        ingest_dir = run_dir / "ingest"
        normalize_dir = run_dir / "normalize"

        if (ingest_dir / "confluence.ndjson").exists():
            confluence_runs.append(run_id)
        if (ingest_dir / "dita.ndjson").exists():
            dita_runs.append(run_id)
        if normalize_dir.exists():
            normalized_runs.append(run_id)

    typer.echo(f"\n📋 Recent Confluence runs: {len(confluence_runs)}")
    if confluence_runs:
        typer.echo(f"   Latest: {confluence_runs[0]}")

    typer.echo(f"📄 Recent DITA runs: {len(dita_runs)}")
    if dita_runs:
        typer.echo(f"   Latest: {dita_runs[0]}")

    typer.echo(f"🔄 Normalized runs: {len(normalized_runs)}")

    # Check for runs needing normalization
    needs_norm = _get_runs_needing_normalization()
    if needs_norm:
        typer.echo(f"⚠️  Runs needing normalization: {len(needs_norm)}")
        typer.echo("   Run: trailblazer normalize-all")
    else:
        typer.echo("✅ All runs normalized")

    # Show workspace usage
    import shutil

    total, used, free = shutil.disk_usage(runs_dir)
    runs_size = sum(
        f.stat().st_size for f in runs_dir.rglob("*") if f.is_file()
    )

    typer.echo("\n💾 Workspace usage:")
    typer.echo(f"   Runs data: {runs_size / (1024**2):.1f} MB")
    typer.echo(f"   Disk free: {free / (1024**3):.1f} GB")


@app.command("enrich-all")
def enrich_all(
    pattern: str = typer.Option(
        "2025-08-*", "--pattern", help="Pattern to match run directories"
    ),
    batch_size: int = typer.Option(
        50, "--batch-size", help="Progress report every N runs"
    ),
    no_llm: bool = typer.Option(
        True, "--no-llm", help="Disable LLM enrichment (default: disabled)"
    ),
    no_progress: bool = typer.Option(
        True,
        "--no-progress",
        help="Disable progress output (default: disabled)",
    ),
) -> None:
    """Enrich all runs that need enrichment in bulk."""
    from ..core.artifacts import runs_dir

    base_dir = runs_dir()
    if not base_dir.exists():
        typer.echo("❌ No runs directory found", err=True)
        raise typer.Exit(1)

        # Find runs that need enrichment
    runs_to_enrich = []

    typer.echo("🔍 Finding all runs that need enrichment...")

    for run_dir in base_dir.glob(pattern):
        if (
            run_dir.is_dir()
            and (run_dir / "ingest").exists()
            and (run_dir / "normalize").exists()
            and not (run_dir / "enrich").exists()
        ):
            runs_to_enrich.append(run_dir.name)

    if not runs_to_enrich:
        typer.echo("✅ No runs need enrichment")
        return

    total_runs = len(runs_to_enrich)
    typer.echo(f"📊 Total runs to enrich: {total_runs}")

    # Process each run
    counter = 0
    for run_id in runs_to_enrich:
        counter += 1
        typer.echo(f"[{counter}/{total_runs}] ENRICHING: {run_id}")

        # Call the existing enrich function directly
        try:
            from ..pipeline.steps.enrich.enricher import enrich_from_normalized

            enrich_from_normalized(
                run_id=run_id,
                llm_enabled=not no_llm,
                max_docs=None,
                budget=None,
                progress_callback=None if no_progress else lambda *args: None,
                emit_event=None,
            )

        except Exception as e:
            typer.echo(f"❌ Failed to enrich {run_id}: {e}", err=True)
            continue

        # Progress update
        if counter % batch_size == 0:
            typer.echo(f"📈 Progress: {counter}/{total_runs} runs enriched")

    typer.echo("✅ MASSIVE ENRICHMENT COMPLETE")
    typer.echo(f"📊 All {total_runs} runs have been enriched!")


@app.command("monitor")
def monitor_cmd(
    run_id: Optional[str] = typer.Option(
        None, "--run", help="Run ID to monitor (default: latest)"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="JSON output for CI dashboards"
    ),
    interval: float = typer.Option(
        2.0, "--interval", help="Refresh interval in seconds"
    ),
) -> None:
    """Monitor running processes with live TUI or JSON output."""
    from ..obs.monitor import TrailblazerMonitor

    monitor = TrailblazerMonitor(
        run_id=run_id, json_mode=json_output, refresh_interval=interval
    )

    monitor.run()


@ops_app.command("monitor")
def ops_monitor_cmd(
    interval: int = typer.Option(
        15, "--interval", help="Monitor interval in seconds"
    ),
    alpha: float = typer.Option(0.25, "--alpha", help="EWMA smoothing factor"),
) -> None:
    """Monitor embedding progress with real-time ETA and worker stats."""
    import json
    import time
    import subprocess
    import os
    from datetime import datetime, timezone, timedelta
    from pathlib import Path

    progress_file = Path("var/logs/reembed_progress.json")
    runs_file = Path("var/logs/temp_runs_to_embed.txt")
    log_dir = Path("var/logs")

    if not progress_file.exists():
        typer.echo(f"❌ {progress_file} not found", err=True)
        raise typer.Exit(2)

    def iso_to_epoch(iso_str: str) -> int:
        """Convert ISO 8601 string to epoch timestamp."""
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except (ValueError, TypeError):
            return int(datetime.now(timezone.utc).timestamp())

    def ewma(alpha: float, current: float, previous: float) -> float:
        """Calculate exponentially weighted moving average."""
        return alpha * current + (1 - alpha) * previous

    docs_rate_ewma = 0.0

    # Get start time
    with open(progress_file) as f:
        progress_data = json.load(f)

    started_at = progress_data.get("started_at", "")
    start_ts = iso_to_epoch(started_at) if started_at else int(time.time())

    typer.echo("🎯 Embedding monitor started - Ctrl+C to stop")

    try:
        while True:
            # Clear screen
            os.system("clear" if os.name == "posix" else "cls")

            now = int(time.time())
            current_time = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            typer.echo(f"[MONITOR] {current_time}  interval={interval}s")

            # Load current progress
            try:
                with open(progress_file) as f:
                    progress_data = json.load(f)

                # Display key metrics
                summary = {
                    "started_at": progress_data.get("started_at"),
                    "total_runs": progress_data.get("total_runs", 0),
                    "completed_runs": progress_data.get("completed_runs", 0),
                    "failed_runs": progress_data.get("failed_runs", 0),
                    "total_docs": progress_data.get("total_docs", 0),
                    "total_chunks": progress_data.get("total_chunks", 0),
                    "estimated_cost": progress_data.get("estimated_cost", 0),
                }

                for key, value in summary.items():
                    typer.echo(f"  {key}: {value}")

                # Calculate progress
                runs_data = progress_data.get("runs", {})
                docs_planned = sum(
                    run.get("docs_planned", 0) for run in runs_data.values()
                )
                if docs_planned == 0 and runs_file.exists():
                    # Fallback: read from runs file
                    with open(runs_file) as f:
                        docs_planned = sum(
                            int(line.split(":")[1])
                            for line in f
                            if ":" in line
                        )

                docs_embedded = sum(
                    run.get("docs_embedded", 0) for run in runs_data.values()
                )

                elapsed = max(1, now - start_ts)
                docs_rate = docs_embedded / elapsed
                docs_rate_ewma = ewma(alpha, docs_rate, docs_rate_ewma)

                # Count active workers
                try:
                    result = subprocess.run(
                        ["pgrep", "-fc", "trailblazer embed load"],
                        capture_output=True,
                        text=True,
                    )
                    active_workers = (
                        int(result.stdout.strip())
                        if result.returncode == 0
                        else 1
                    )
                except (subprocess.SubprocessError, ValueError):
                    active_workers = 1

                # Calculate ETA
                remain = max(0, docs_planned - docs_embedded)
                if docs_rate_ewma > 0:
                    eta_sec = int(remain / docs_rate_ewma)
                    eta_str = str(timedelta(seconds=eta_sec))
                else:
                    eta_str = "unknown"

                typer.echo("---- progress ----")
                typer.echo(
                    f"docs: {docs_embedded} / {docs_planned}   elapsed: {elapsed}s   rate(ewma): {docs_rate_ewma:.2f} docs/s   active_workers: {active_workers}   ETA: {eta_str}"
                )

                # Show recent runs
                typer.echo("---- recent runs ----")
                recent_runs = list(runs_data.items())
                recent_runs.sort(
                    key=lambda x: x[1].get("completed_at", ""), reverse=True
                )

                for run_id, run_data in recent_runs[:8]:
                    status = run_data.get("status", "unknown")
                    docs = run_data.get("docs_embedded", 0)
                    chunks = run_data.get("chunks_embedded", 0)
                    duration = run_data.get("duration_seconds", 0)
                    error = run_data.get("error", "")
                    typer.echo(
                        f"{run_id}  {status}  docs={docs} chunks={chunks} dur={duration}s err={error}"
                    )

                # Show recent logs
                if log_dir.exists():
                    typer.echo("---- tail of active logs ----")
                    log_files = list(log_dir.glob("embed-*.out"))
                    log_files.sort(
                        key=lambda x: x.stat().st_mtime, reverse=True
                    )

                    for log_file in log_files[:2]:
                        typer.echo(f">>> {log_file}")
                        try:
                            with open(log_file) as f:
                                lines = f.readlines()
                                for line in lines[-30:]:
                                    typer.echo(line.rstrip())
                        except (IOError, OSError):
                            typer.echo("Error reading log file")
                        typer.echo()

            except Exception as e:
                typer.echo(f"Error reading progress: {e}", err=True)

            time.sleep(interval)

    except KeyboardInterrupt:
        typer.echo("\n👋 Monitor stopped by user")


@ops_app.command("dispatch")
def ops_dispatch_cmd(
    workers: int = typer.Option(
        2, "--workers", help="Number of parallel workers"
    ),
    runs_file: str = typer.Option(
        "var/logs/temp_runs_to_embed.txt",
        "--runs-file",
        help="File with runs to embed",
    ),
) -> None:
    """Dispatch parallel embedding jobs from runs file."""
    import subprocess
    from pathlib import Path

    runs_path = Path(runs_file)
    if not runs_path.exists() or runs_path.stat().st_size == 0:
        typer.echo(f"❌ {runs_file} missing or empty", err=True)
        raise typer.Exit(2)

    typer.echo(f"🚀 Dispatching {workers} parallel embedding workers")
    typer.echo(f"📁 Runs file: {runs_file}")

    # Read runs and dispatch
    try:
        with open(runs_path) as f:
            lines = [
                line.strip() for line in f if line.strip() and ":" in line
            ]

        if not lines:
            typer.echo("❌ No valid runs found in file", err=True)
            raise typer.Exit(1)

        typer.echo(f"📊 Found {len(lines)} runs to embed")

        # Build xargs command for parallel processing
        cmd = [
            "xargs",
            "-n",
            "2",
            "-P",
            str(workers),
            "bash",
            "-lc",
            """
            run_id="$0"; docs="${1:-0}";
            echo "[DISPATCH] $run_id ($docs docs)"
            PYTHONPATH=src python3 -m trailblazer.cli.main embed load --run-id "$run_id" --provider "${EMBED_PROVIDER:-openai}" --model "${EMBED_MODEL:-text-embedding-3-small}" --dimension "${EMBED_DIMENSIONS:-1536}" --batch "${BATCH_SIZE:-128}"
            """,
        ]

        # Prepare input for xargs (run_id:docs -> run_id docs)
        input_data = ""
        for line in lines:
            if ":" in line:
                run_id, docs = line.split(":", 1)
                input_data += f"{run_id.strip()} {docs.strip()}\n"

        # Execute parallel dispatch
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
        process.communicate(input=input_data)

        if process.returncode == 0:
            typer.echo("✅ Dispatch completed successfully")
        else:
            typer.echo("❌ Dispatch failed", err=True)
            raise typer.Exit(process.returncode)

    except Exception as e:
        typer.echo(f"❌ Dispatch error: {e}", err=True)
        raise typer.Exit(1)


@ops_app.command("track-pages")
def ops_track_pages_cmd(
    log_file: Optional[str] = typer.Option(
        None, "--log-file", help="Specific log file to track (default: latest)"
    ),
) -> None:
    """Track and display page processing from embedding logs."""
    import time
    from pathlib import Path
    from ..core.paths import logs

    logs_dir = logs()
    pages_log = logs_dir / "processed_pages.log"

    typer.echo("🚀 Starting page titles tracker...")
    typer.echo(f"📄 Log file: {pages_log}")
    typer.echo("Press Ctrl+C to stop")

    # Initialize log file
    with open(pages_log, "w") as f:
        f.write(
            f"=== Page Titles Tracking Started at {datetime.now().isoformat()} ===\n"
        )
        f.write("Format: [TIMESTAMP] [DOC_NUMBER] TITLE (STATUS)\n\n")

    try:
        while True:
            # Find the most recent embedding log
            if log_file:
                latest_log = Path(log_file)
            else:
                embed_logs = list(logs_dir.glob("embed-*.out"))
                if not embed_logs:
                    typer.echo("⏳ Waiting for embedding logs...")
                    time.sleep(5)
                    continue
                latest_log = max(embed_logs, key=lambda x: x.stat().st_mtime)

            if latest_log.exists():
                typer.echo(f"📖 Tracking pages from: {latest_log}")
                _track_pages_from_log(latest_log, pages_log)
            else:
                typer.echo("⏳ Waiting for embedding logs...")
                time.sleep(5)
    except KeyboardInterrupt:
        typer.echo("\n👋 Page tracking stopped")


def _track_pages_from_log(log_file: Path, output_log: Path) -> None:
    """Track pages from a specific log file."""
    import re
    import subprocess
    from datetime import datetime

    run_id = log_file.stem.replace("embed-", "")

    # Use tail -f to follow the log file
    try:
        process = subprocess.Popen(
            ["tail", "-f", str(log_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if process.stdout:
            for line in process.stdout:
                # Match patterns like: 📖 [123] Page Title (embedding) or ⏭️ [123] Page Title (skipped)
                match = re.search(
                    r"(📖|⏭️).*\[(\d+)\].*\((embedding|skipped)\)", line
                )
                if match:
                    icon, doc_num, status = match.groups()

                    # Extract title (everything between ] and ( )
                    title_match = re.search(
                        r"\] (.*) \((embedding|skipped)\)", line
                    )
                    title = title_match.group(1) if title_match else "Unknown"

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # Log to file
                    with open(output_log, "a") as f:
                        f.write(
                            f"[{timestamp}] [{doc_num}] {title} ({status}) - Run: {run_id}\n"
                        )

                    # Display to console
                    if status == "embedding":
                        typer.echo(f"✨ [{doc_num}] {title}")
                    else:
                        typer.echo(f"⏭️ [{doc_num}] {title} (skipped)")

    except KeyboardInterrupt:
        if process:
            process.terminate()
        raise


@ops_app.command("kill")
def ops_kill_cmd() -> None:
    """Kill all running embedding processes."""
    import subprocess

    try:
        # Kill trailblazer embedding processes
        result = subprocess.run(
            [
                "pkill",
                "-f",
                "trailblazer.*(embed|ingest|enrich|chunk|classif|compose|playbook|ask|retrieve)",
            ],
            capture_output=True,
        )

        if result.returncode == 0:
            typer.echo("✅ Killed running Trailblazer processes")
        else:
            typer.echo("ℹ️  No running Trailblazer processes found")

    except Exception as e:
        typer.echo(f"❌ Error killing processes: {e}", err=True)
        raise typer.Exit(1)


@runs_app.command("reset")
def runs_reset_cmd(
    scope: str = typer.Option(
        "processed", "--scope", help="Reset scope: processed|embeddings|all"
    ),
    run_ids: Optional[List[str]] = typer.Option(
        None, "--run-id", help="Specific run IDs to reset"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Limit number of runs to reset"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be reset without doing it"
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompts"),
) -> None:
    """
    Reset runs in the processed_runs backlog.

    Scopes:
    - processed: Reset chunk/embed status and claim fields (safe)
    - embeddings: Also delete embeddings from database (destructive)
    - all: Reset status + delete embeddings + delete chunk artifacts (destructive)
    """
    from ..pipeline.backlog import reset_runs

    valid_scopes = ["processed", "embeddings", "all"]
    if scope not in valid_scopes:
        typer.echo(
            f"❌ Invalid scope: {scope}. Use: {', '.join(valid_scopes)}",
            err=True,
        )
        raise typer.Exit(1)

    # Show what would be affected
    if not dry_run and not yes and scope in ("embeddings", "all"):
        typer.echo(f"⚠️  About to reset scope: {scope}")
        if scope == "embeddings":
            typer.echo("   This will delete embeddings from the database")
        elif scope == "all":
            typer.echo("   This will delete embeddings AND chunk artifacts")

        confirm = typer.confirm("Continue?")
        if not confirm:
            typer.echo("Reset cancelled", err=True)
            raise typer.Exit(0)

    # Execute reset
    try:
        filters = {}
        if limit:
            filters["limit"] = limit

        result = reset_runs(
            run_ids=run_ids,
            scope=scope,
            filters=filters,
            dry_run=dry_run,
            confirmed=yes or dry_run,
        )

        if dry_run:
            typer.echo(
                f"🔍 Would reset {result['reset_count']} runs (scope: {scope})"
            )
        else:
            typer.echo(
                f"✅ Reset {result['reset_count']} runs (scope: {scope})"
            )

    except Exception as e:
        typer.echo(f"❌ Reset failed: {e}", err=True)
        raise typer.Exit(1)


@runs_app.command("status")
def runs_status_cmd() -> None:
    """Show processed runs status distribution."""
    from ..pipeline.backlog import get_db_connection

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    status,
                    COUNT(*) as count,
                    MIN(normalized_at) as earliest,
                    MAX(normalized_at) as latest
                FROM processed_runs
                GROUP BY status
                ORDER BY count DESC
            """)

            results = cursor.fetchall()

            if not results:
                typer.echo("No runs found in processed_runs table")
                return

            typer.echo("📊 Processed Runs Status:")
            typer.echo("")

            for row in results:
                status, count, earliest, latest = row
                typer.echo(f"  {status:12} : {count:4,} runs")
                if earliest and latest:
                    typer.echo(f"               {earliest} to {latest}")
                typer.echo("")

    except Exception as e:
        typer.echo(f"❌ Failed to get status: {e}", err=True)
        raise typer.Exit(1)


# Add logs management subcommands
logs_app = typer.Typer(name="logs", help="Log management commands")
app.add_typer(logs_app)


@logs_app.command("index")
def logs_index():
    """Summarize runs with sizes/segments/last update times."""
    try:
        from ..log_management import LogManager

        manager = LogManager()
        summary = manager.get_index_summary()

        typer.echo("📂 Log Index Summary:")
        typer.echo(f"   Total runs: {summary['total_runs']}")
        typer.echo(f"   Total size: {summary['total_size_mb']:.1f} MB")
        typer.echo("")

        if not summary["runs"]:
            typer.echo("   No log runs found")
            return

        # Show header
        typer.echo(
            f"{'Run ID':<20} {'Status':<8} {'Size (MB)':<10} {'Segments':<9} {'Last Modified'}"
        )
        typer.echo("-" * 80)

        # Show runs (limit to first 50 for readability)
        for run_info in summary["runs"][:50]:
            size_mb = round(run_info["size_bytes"] / (1024 * 1024), 2)
            segments = f"{run_info['segments']}"
            if run_info["compressed_segments"] > 0:
                segments += f"+{run_info['compressed_segments']}gz"

            last_mod = (
                run_info["last_modified"][:19]
                if run_info["last_modified"]
                else "unknown"
            )

            typer.echo(
                f"{run_info['run_id']:<20} {run_info['status']:<8} {size_mb:<10.2f} {segments:<9} {last_mod}"
            )

        if len(summary["runs"]) > 50:
            typer.echo(f"... and {len(summary['runs']) - 50} more runs")

    except Exception as e:
        typer.echo(f"❌ Failed to get log index: {e}", err=True)
        raise typer.Exit(1)


@logs_app.command("prune")
def logs_prune(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Show what would be done without doing it",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip confirmation prompts (required for actual deletion)",
    ),
):
    """Compress old segments and delete beyond retention (never active); prints a clear plan."""
    try:
        from ..log_management import LogManager

        manager = LogManager()

        # Always start with compression
        typer.echo("🗜️  Checking for old segments to compress...")
        compress_result = manager.compress_old_segments(
            dry_run=True
        )  # Always dry-run first

        if compress_result["compressed"]:
            typer.echo(
                f"   Found {len(compress_result['compressed'])} segments to compress"
            )
            for path in compress_result["compressed"][:10]:  # Show first 10
                typer.echo(f"     {path}")
            if len(compress_result["compressed"]) > 10:
                typer.echo(
                    f"     ... and {len(compress_result['compressed']) - 10} more"
                )
        else:
            typer.echo("   No segments need compression")

        # Check what would be pruned
        from ..core.config import SETTINGS

        typer.echo(
            f"\n🗑️  Checking for logs to prune (retention: {SETTINGS.LOGS_RETENTION_DAYS} days)..."
        )
        prune_result = manager.prune_old_logs(
            dry_run=True
        )  # Always dry-run first

        if prune_result["deleted_runs"]:
            typer.echo(
                f"   Found {len(prune_result['deleted_runs'])} run directories to delete"
            )
            for run_id in prune_result["deleted_runs"][:10]:  # Show first 10
                typer.echo(f"     {run_id}")
            if len(prune_result["deleted_runs"]) > 10:
                typer.echo(
                    f"     ... and {len(prune_result['deleted_runs']) - 10} more"
                )
        else:
            typer.echo("   No runs to prune")

        # Show errors if any
        if compress_result["errors"] or prune_result["errors"]:
            typer.echo("\n⚠️  Errors found:")
            for error in (compress_result["errors"] + prune_result["errors"])[
                :5
            ]:
                typer.echo(f"     {error}")

        # Actually execute if requested and not dry-run
        if not dry_run:
            if not yes:
                total_actions = len(compress_result["compressed"]) + len(
                    prune_result["deleted_runs"]
                )
                if total_actions > 0:
                    typer.echo(
                        f"\n❓ Proceed with {total_actions} actions? This cannot be undone."
                    )
                    if not typer.confirm("Continue?"):
                        typer.echo("Cancelled")
                        return

            # Execute compression
            if compress_result["compressed"]:
                typer.echo("\n🗜️  Compressing segments...")
                actual_compress = manager.compress_old_segments(dry_run=False)
                typer.echo(
                    f"   Compressed {len(actual_compress['compressed'])} segments"
                )

            # Execute pruning
            if prune_result["deleted_runs"]:
                typer.echo("\n🗑️  Pruning old logs...")
                actual_prune = manager.prune_old_logs(dry_run=False)
                typer.echo(
                    f"   Deleted {len(actual_prune['deleted_runs'])} run directories"
                )

        elif dry_run:
            typer.echo(
                "\n💡 This was a dry run. Use --no-dry-run --yes to actually perform these actions."
            )

    except Exception as e:
        typer.echo(f"❌ Failed to prune logs: {e}", err=True)
        raise typer.Exit(1)


@logs_app.command("doctor")
def logs_doctor():
    """Fix symlinks/permissions and validate segments; non-zero on unfixable issues."""
    try:
        from ..log_management import LogManager

        manager = LogManager()
        result = manager.doctor_logs()

        typer.echo("🏥 Log Doctor Report:")

        if result["fixed"]:
            typer.echo(f"\n✅ Fixed {len(result['fixed'])} issues:")
            for fix in result["fixed"]:
                typer.echo(f"   {fix}")

        if result["issues"]:
            typer.echo(f"\n⚠️  Found {len(result['issues'])} issues:")
            for issue in result["issues"]:
                typer.echo(f"   {issue}")

        typer.echo(f"\n📊 Overall health: {result['health']}")

        # Exit with error if unfixable issues
        if result["health"] != "healthy":
            raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"❌ Log doctor failed: {e}", err=True)
        raise typer.Exit(1)


@embed_app.command("corpus")
def embed_corpus_cmd(
    provider: str = typer.Option(
        "openai",
        "--provider",
        help="Embedding provider (openai, sentencetransformers)",
    ),
    model: str = typer.Option(
        "text-embedding-3-small",
        "--model",
        help="Model name (e.g., text-embedding-3-small, BAAI/bge-small-en-v1.5)",
    ),
    dimension: int = typer.Option(
        1536,
        "--dimension",
        help="Embedding dimension (e.g., 512, 1024, 1536)",
    ),
    batch_size: int = typer.Option(
        1000,
        "--batch",
        help="Batch size for embedding generation (max chunks per batch)",
    ),
    large_run_threshold: int = typer.Option(
        2000,
        "--large-run-threshold",
        help="Runs with more chunks than this get batched",
    ),
    resume_from: Optional[str] = typer.Option(
        None,
        "--resume-from",
        help="Resume from specific run ID",
    ),
    reembed_all: bool = typer.Option(
        False,
        "--reembed-all",
        help="Force re-embed all documents regardless of fingerprints",
    ),
    changed_only: bool = typer.Option(
        False,
        "--changed-only",
        help="Only embed documents with changed enrichment fingerprints",
    ),
    max_runs: Optional[int] = typer.Option(
        None,
        "--max-runs",
        help="Maximum number of runs to process",
    ),
    dry_run_cost: bool = typer.Option(
        False,
        "--dry-run-cost",
        help="Estimate token count and cost without calling API",
    ),
    progress: bool = typer.Option(
        True,
        "--progress/--no-progress",
        help="Show progress bars and real-time status",
    ),
) -> None:
    """Embed entire corpus with end-to-end observability and batching support."""
    # Run database preflight check first
    _run_db_preflight_check()

    # Validate provider
    if provider == "dummy":
        typer.echo(
            "❌ Dummy provider not allowed for corpus embedding", err=True
        )
        typer.echo(
            "Use --provider openai or --provider sentencetransformers",
            err=True,
        )
        raise typer.Exit(1)

    # Check dimension compatibility unless we're doing a full re-embed
    if not reembed_all:
        _check_dimension_compatibility(provider, dimension)

    from ..core.paths import runs, logs, progress as progress_dir
    from ..pipeline.steps.embed.loader import load_chunks_to_db
    import json
    import time
    from datetime import datetime, timezone

    # Setup paths
    runs_dir = runs()
    logs_dir = logs() / "embedding"
    progress_file = progress_dir() / "embedding.json"

    # Ensure directories exist
    logs_dir.mkdir(parents=True, exist_ok=True)
    progress_dir().mkdir(parents=True, exist_ok=True)

    # Setup logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"corpus_embedding_{timestamp}.log"

    def log_message(msg: str, level: str = "INFO"):
        timestamp = datetime.now(timezone.utc).isoformat()
        formatted_msg = f"{timestamp} [{level}] {msg}"
        print(formatted_msg)
        with open(log_file, "a") as f:
            f.write(formatted_msg + "\n")

    log_message("🚀 Starting corpus embedding", "INFO")
    log_message(
        f"Provider: {provider}, Model: {model}, Dimension: {dimension}",
        "INFO",
    )
    log_message(
        f"Batch size: {batch_size}, Large run threshold: {large_run_threshold}",
        "INFO",
    )
    log_message(
        f"Re-embed all: {reembed_all}, Changed only: {changed_only}", "INFO"
    )
    log_message(f"Log file: {log_file}", "INFO")

    # Get list of runs
    normalized_runs = []
    for run_dir in runs_dir.iterdir():
        if run_dir.is_dir():
            normalized_file = run_dir / "normalize" / "normalized.ndjson"
            if normalized_file.exists():
                normalized_runs.append(run_dir.name)

    normalized_runs.sort()
    total_runs = len(normalized_runs)

    if total_runs == 0:
        log_message("❌ No normalized runs found", "ERROR")
        raise typer.Exit(1)

    log_message(f"Found {total_runs} normalized runs", "INFO")

    # Find starting position if resuming
    start_index = 0
    if resume_from:
        try:
            start_index = normalized_runs.index(resume_from)
            log_message(
                f"Resuming from run: {resume_from} (index {start_index})",
                "INFO",
            )
        except ValueError:
            log_message(f"❌ Resume run '{resume_from}' not found", "ERROR")
            raise typer.Exit(1)

    # Apply max_runs limit
    if max_runs:
        end_index = min(start_index + max_runs, total_runs)
        runs_to_process = normalized_runs[start_index:end_index]
        log_message(
            f"Processing {len(runs_to_process)} runs (limited by --max-runs)",
            "INFO",
        )
    else:
        runs_to_process = normalized_runs[start_index:]
        log_message(f"Processing {len(runs_to_process)} runs", "INFO")

    # Initialize progress tracking
    progress_data = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_runs": len(runs_to_process),
        "processed_runs": 0,
        "successful_runs": 0,
        "failed_runs": 0,
        "total_docs": 0,
        "total_chunks": 0,
        "total_embeddings": 0,
        "estimated_cost": 0.0,
        "current_run": None,
        "status": "running",
    }

    def update_progress():
        with open(progress_file, "w") as f:
            json.dump(progress_data, f, indent=2)

    update_progress()

    # Process each run
    success_count = 0
    failure_count = 0
    total_docs_embedded = 0
    total_chunks_embedded = 0
    total_estimated_cost = 0.0

    start_time = time.time()

    for i, run_id in enumerate(runs_to_process):
        current_run_num = start_index + i + 1
        progress_data["current_run"] = run_id
        progress_data["processed_runs"] = current_run_num
        update_progress()

        log_message("")
        log_message(
            f"🔥 [{current_run_num}/{len(runs_to_process)}] Processing: {run_id}",
            "INFO",
        )

        # Check if this is a large run that needs batching
        chunks_file = runs_dir / run_id / "chunk" / "chunks.ndjson"
        chunk_count = 0
        if chunks_file.exists():
            with open(chunks_file) as f:
                chunk_count = sum(1 for _ in f)

        if chunk_count > large_run_threshold:
            log_message(
                f"📊 Large run detected: {run_id} ({chunk_count:,} chunks)",
                "INFO",
            )
            batches_needed = (chunk_count + batch_size - 1) // batch_size
            log_message(f"  Batches needed: {batches_needed}", "INFO")

            # Process in batches
            batch_success = 0
            batch_failure = 0

            for batch_num in range(1, batches_needed + 1):
                log_message(
                    f"  🔥 Processing batch {batch_num}/{batches_needed}",
                    "INFO",
                )

                batch_start_time = time.time()

                try:
                    metrics = load_chunks_to_db(
                        run_id=run_id,
                        provider_name=provider,
                        model=model,
                        dimensions=dimension,
                        batch_size=batch_size,
                        max_chunks=batch_size,
                        changed_only=changed_only,
                        reembed_all=reembed_all,
                        dry_run_cost=dry_run_cost,
                    )

                    batch_duration = time.time() - batch_start_time
                    log_message(
                        f"  ✅ Batch {batch_num}/{batches_needed} completed ({batch_duration:.1f}s)",
                        "INFO",
                    )
                    log_message(
                        f"    Chunks: {metrics.get('chunks_embedded', 0)} embedded",
                        "INFO",
                    )
                    batch_success += 1

                    # Update totals
                    total_docs_embedded += metrics.get("docs_embedded", 0)
                    total_chunks_embedded += metrics.get("chunks_embedded", 0)
                    if metrics.get("estimated_cost"):
                        total_estimated_cost += metrics.get(
                            "estimated_cost", 0
                        )

                except Exception as e:
                    batch_duration = time.time() - batch_start_time
                    log_message(
                        f"  ❌ Batch {batch_num}/{batches_needed} failed ({batch_duration:.1f}s): {e}",
                        "ERROR",
                    )
                    batch_failure += 1

                # Brief pause between batches
                time.sleep(2)

            if batch_failure == 0:
                log_message(
                    f"✅ SUCCESS: {run_id} (all {batches_needed} batches completed)",
                    "INFO",
                )
                success_count += 1
            else:
                log_message(
                    f"❌ PARTIAL FAILURE: {run_id} ({batch_failure}/{batches_needed} batches failed)",
                    "ERROR",
                )
                failure_count += 1

        else:
            # Process single run
            log_message(
                f"📄 Processing single run: {run_id} ({chunk_count:,} chunks)",
                "INFO",
            )

            run_start_time = time.time()

            try:
                metrics = load_chunks_to_db(
                    run_id=run_id,
                    provider_name=provider,
                    model=model,
                    dimensions=dimension,
                    batch_size=batch_size,
                    changed_only=changed_only,
                    reembed_all=reembed_all,
                    dry_run_cost=dry_run_cost,
                )

                run_duration = time.time() - run_start_time
                log_message(
                    f"✅ SUCCESS: {run_id} completed ({run_duration:.1f}s)",
                    "INFO",
                )
                log_message(
                    f"  Documents: {metrics.get('docs_embedded', 0)} embedded",
                    "INFO",
                )
                log_message(
                    f"  Chunks: {metrics.get('chunks_embedded', 0)} embedded",
                    "INFO",
                )
                success_count += 1

                # Update totals
                total_docs_embedded += metrics.get("docs_embedded", 0)
                total_chunks_embedded += metrics.get("chunks_embedded", 0)
                if metrics.get("estimated_cost"):
                    total_estimated_cost += metrics.get("estimated_cost", 0)

            except Exception as e:
                run_duration = time.time() - run_start_time
                log_message(
                    f"❌ FAILED: {run_id} ({run_duration:.1f}s): {e}", "ERROR"
                )
                failure_count += 1

        # Update progress
        progress_data["successful_runs"] = success_count
        progress_data["failed_runs"] = failure_count
        progress_data["total_docs"] = total_docs_embedded
        progress_data["total_chunks"] = total_chunks_embedded
        progress_data["total_embeddings"] = total_chunks_embedded
        progress_data["estimated_cost"] = total_estimated_cost
        update_progress()

        # Periodic health check
        if current_run_num % 100 == 0:
            log_message(
                f"🔍 Health check after {current_run_num} runs...", "INFO"
            )
            try:
                from ..db.engine import check_db_health

                check_db_health()
                log_message("✅ Database health check passed", "INFO")
            except Exception as e:
                log_message(f"⚠️ Database health check warning: {e}", "WARN")

    # Final summary
    total_duration = time.time() - start_time
    progress_data["status"] = "completed"
    progress_data["completed_at"] = datetime.now(timezone.utc).isoformat()
    progress_data["total_duration_seconds"] = total_duration
    update_progress()

    log_message("")
    log_message("🎉 CORPUS EMBEDDING COMPLETE!", "INFO")
    log_message("=" * 50, "INFO")
    log_message(f"Total runs processed: {len(runs_to_process)}", "INFO")
    log_message(f"Successful: {success_count}", "INFO")
    log_message(f"Failed: {failure_count}", "INFO")
    log_message(
        f"Success rate: {(success_count * 100 / len(runs_to_process)):.1f}%",
        "INFO",
    )
    log_message(f"Total documents embedded: {total_docs_embedded:,}", "INFO")
    log_message(f"Total chunks embedded: {total_chunks_embedded:,}", "INFO")
    log_message(f"Total estimated cost: ${total_estimated_cost:.4f}", "INFO")
    log_message(f"Total duration: {total_duration:.1f}s", "INFO")
    log_message(f"Progress file: {progress_file}", "INFO")
    log_message(f"Log file: {log_file}", "INFO")

    if failure_count > 0:
        log_message(
            "❌ Some runs failed. Check the log file for details.", "ERROR"
        )
        raise typer.Exit(1)
    else:
        log_message("✅ All runs completed successfully!", "INFO")


@embed_app.command("preflight")
def embed_preflight_cmd(
    run: str = typer.Argument(
        ..., help="Run ID to validate for embedding preflight"
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Embedding provider (openai, sentencetransformers)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model name (e.g., text-embedding-3-small)",
    ),
    dimension: Optional[int] = typer.Option(
        None,
        "--dimension",
        help="Embedding dimension (e.g., 512, 1024, 1536)",
    ),
) -> None:
    """
    Validate a run is ready for embedding with preflight checks.

    Validates that:
    - Enriched and chunk files exist and have content
    - Tokenizer is available
    - Provider/model/dimension are resolved
    - Chunk statistics are computed

    Writes preflight.json with validation results and stats.
    """
    import json
    import statistics
    from datetime import datetime, timezone
    from ..core.paths import runs
    from ..core.config import SETTINGS
    from ..obs.events import stage_run, emit_info

    # Resolve provider/model/dim from CLI args, env, or defaults
    resolved_provider = provider or SETTINGS.EMBED_PROVIDER or "openai"
    resolved_model = model or SETTINGS.EMBED_MODEL or "text-embedding-3-small"
    resolved_dim = dimension or SETTINGS.EMBED_DIMENSIONS or 1536

    typer.echo(f"🔍 Preflight check for run: {run}", err=True)
    typer.echo(
        f"Provider: {resolved_provider}, Model: {resolved_model}, Dimension: {resolved_dim}",
        err=True,
    )

    # Use stage_run context manager for consistent event emission
    with stage_run(
        "preflight",
        run,
        "embed",
        provider=resolved_provider,
        model=resolved_model,
        dimension=resolved_dim,
    ) as ctx:
        emit_info(
            "preflight",
            run,
            "embed",
            message="Starting preflight validation",
            provider=resolved_provider,
            model=resolved_model,
            dimension=resolved_dim,
        )

        # Validate run directory exists
        run_dir = runs() / run
        if not run_dir.exists():
            emit_info(
                "preflight",
                run,
                "embed",
                message="Preflight validation failed",
                status="BLOCKED",
                reason="RUN_NOT_FOUND",
            )
            typer.echo(f"❌ Run directory not found: {run_dir}", err=True)
            raise typer.Exit(1)

        # Check enriched.jsonl
        enriched_file = run_dir / "enrich" / "enriched.jsonl"
        if not enriched_file.exists():
            emit_info(
                "preflight",
                run,
                "embed",
                message="Preflight validation failed",
                status="BLOCKED",
                reason="MISSING_ENRICHED",
            )
            typer.echo(
                f"❌ Enriched file not found: {enriched_file}", err=True
            )
            typer.echo("Run 'trailblazer enrich <RID>' first", err=True)
            raise typer.Exit(1)

        # Count lines in enriched file
        with open(enriched_file) as f:
            enriched_lines = sum(1 for line in f if line.strip())

        if enriched_lines == 0:
            emit_info(
                "preflight",
                run,
                "embed",
                message="Preflight validation failed",
                status="BLOCKED",
                reason="EMPTY_ENRICHED",
            )
            typer.echo(f"❌ Enriched file is empty: {enriched_file}", err=True)
            raise typer.Exit(1)

        typer.echo(f"✓ Enriched file: {enriched_lines} documents", err=True)

        # Check chunks.ndjson
        chunks_file = run_dir / "chunk" / "chunks.ndjson"
        if not chunks_file.exists():
            emit_info(
                "preflight",
                run,
                "embed",
                message="Preflight validation failed",
                status="BLOCKED",
                reason="MISSING_CHUNKS",
            )
            typer.echo(f"❌ Chunks file not found: {chunks_file}", err=True)
            typer.echo("Run chunking phase first", err=True)
            raise typer.Exit(1)

    # Load and analyze chunks
    chunks = []
    with open(chunks_file) as f:
        for line in f:
            if line.strip():
                chunk_data = json.loads(line.strip())
                chunks.append(chunk_data)

    if not chunks:
        typer.echo(f"❌ Chunks file is empty: {chunks_file}", err=True)
        raise typer.Exit(1)

    typer.echo(f"✓ Chunks file: {len(chunks)} chunks", err=True)

    # Verify tokenizer availability
    try:
        import tiktoken

        tokenizer_version = tiktoken.__version__
        typer.echo(f"✓ Tokenizer: tiktoken v{tokenizer_version}", err=True)
    except ImportError:
        typer.echo(
            "❌ Tokenizer not available: tiktoken not installed", err=True
        )
        raise typer.Exit(1)

    # Compute chunk statistics
    token_counts = [chunk.get("token_count", 0) for chunk in chunks]
    if not token_counts or all(t == 0 for t in token_counts):
        typer.echo("❌ No valid token counts found in chunks", err=True)
        raise typer.Exit(1)

    # Compute P95 manually since statistics.quantile is not available in all Python versions
    sorted_tokens = sorted(token_counts)
    p95_index = int(0.95 * len(sorted_tokens))
    p95_value = sorted_tokens[min(p95_index, len(sorted_tokens) - 1)]

    token_stats = {
        "count": len(token_counts),
        "min": min(token_counts),
        "median": int(statistics.median(token_counts)),
        "p95": p95_value,
        "max": max(token_counts),
        "total": sum(token_counts),
    }

    typer.echo(
        f"✓ Token stats: {token_stats['count']} chunks, {token_stats['min']}-{token_stats['max']} tokens (median: {token_stats['median']})",
        err=True,
    )

    # Check quality distribution from chunk assurance
    chunk_assurance_file = run_dir / "chunk" / "chunk_assurance.json"
    quality_distribution = None
    quality_check_passed = True
    quality_failure_reason = None

    if chunk_assurance_file.exists():
        try:
            with open(chunk_assurance_file) as f:
                assurance_data = json.load(f)
                quality_distribution = assurance_data.get(
                    "qualityDistribution"
                )

            if quality_distribution:
                below_threshold_pct = quality_distribution.get(
                    "belowThresholdPct", 0.0
                )
                max_below_threshold_pct = quality_distribution.get(
                    "maxBelowThresholdPct", 0.20
                )
                min_quality = quality_distribution.get("minQuality", 0.60)

                typer.echo(
                    f"✓ Quality distribution: P50={quality_distribution.get('p50', 0.0)}, "
                    f"P90={quality_distribution.get('p90', 0.0)}, "
                    f"Below threshold: {below_threshold_pct:.1%}",
                    err=True,
                )

                # Quality gate is now informational only - don't fail entire runs
                if below_threshold_pct > max_below_threshold_pct:
                    typer.echo(
                        f"⚠️  Quality info: {below_threshold_pct:.1%} of documents "
                        f"have quality_score < {min_quality} (threshold: {max_below_threshold_pct:.1%}). "
                        f"Low-quality documents will be filtered during embedding.",
                        err=True,
                    )
                else:
                    typer.echo(
                        f"✓ Quality info: {below_threshold_pct:.1%} below threshold (max: {max_below_threshold_pct:.1%})",
                        err=True,
                    )
                # Always pass quality check - filtering happens at document level during embedding
                quality_check_passed = True
            else:
                typer.echo(
                    "⚠️  No quality distribution found (enrichment may not have been run)",
                    err=True,
                )
        except Exception as e:
            typer.echo(
                f"⚠️  Failed to read quality distribution: {e}", err=True
            )
    else:
        typer.echo("⚠️  No chunk assurance file found", err=True)

    # Quality check is now informational only - preflight always passes
    # Individual documents will be filtered during embedding based on quality scores

    # Create preflight directory and write results
    preflight_dir = run_dir / "preflight"
    preflight_dir.mkdir(exist_ok=True)

    preflight_data = {
        "status": "success",
        "run_id": run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "enriched_docs": enriched_lines,
            "chunks": len(chunks),
        },
        "tokenStats": token_stats,
        "qualityDistribution": quality_distribution,
        "qualityCheck": {
            "passed": quality_check_passed,
            "reason": quality_failure_reason,
        },
        "provider": resolved_provider,
        "model": resolved_model,
        "dimension": resolved_dim,
        "dimensions": resolved_dim,  # transitional alias for compatibility
        "notes": [
            f"Validated {enriched_lines} enriched documents",
            f"Validated {len(chunks)} chunks with token range {token_stats['min']}-{token_stats['max']}",
            f"Tokenizer: tiktoken v{tokenizer_version}",
            f"Quality gate: {'PASSED' if quality_check_passed else 'FAILED'}",
        ],
    }

    # Add delta section if previous manifest exists (non-blocking)
    try:
        from ..pipeline.steps.embed.manifest import (
            find_last_manifest,
            load_manifest,
            compute_current_state,
            compare_manifests,
        )

        manifest_path = find_last_manifest(run)
        if manifest_path is not None:
            previous_manifest = load_manifest(manifest_path)
            if previous_manifest is not None:
                # Compute current state for comparison
                current_state = compute_current_state(
                    run, resolved_provider, resolved_model, resolved_dim
                )

                # Compare manifests
                has_changes, reasons = compare_manifests(
                    current_state, previous_manifest
                )

                preflight_data["delta"] = {
                    "changed": has_changes,
                    "reasons": reasons,
                    "previousManifest": str(manifest_path),
                    "previousTimestamp": previous_manifest.get("timestamp"),
                }

                typer.echo(f"📄 Previous manifest: {manifest_path}", err=True)
                if has_changes:
                    typer.echo(
                        f"🔄 Changes detected: {', '.join(reasons)}", err=True
                    )
                else:
                    typer.echo(
                        "✅ No changes detected since last manifest", err=True
                    )

    except Exception as e:
        # Delta computation failed, but this is non-blocking for preflight
        typer.echo(f"⚠️  Could not compute delta: {e}", err=True)

    preflight_file = preflight_dir / "preflight.json"
    with open(preflight_file, "w") as f:
        json.dump(preflight_data, f, indent=2)

        # Update context and emit success event
        ctx.update(
            enriched_docs=enriched_lines, chunks=len(chunks), status="READY"
        )
        emit_info(
            "preflight",
            run,
            "embed",
            message="Preflight validation completed",
            status="READY",
            enriched_docs=enriched_lines,
            chunks=len(chunks),
        )

        typer.echo(f"✅ Preflight complete: {preflight_file}", err=True)
        typer.echo(
            f"Run ready for embedding with {resolved_provider}/{resolved_model} at dimension {resolved_dim}",
            err=True,
        )


@embed_app.command("plan-preflight")
def embed_plan_preflight_cmd(
    plan_file: str = typer.Option(
        "var/temp_runs_to_embed.txt",
        "--plan-file",
        help="Plan file with runs to validate (format: run_id:chunk_count per line)",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Embedding provider (openai, sentencetransformers)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model name (e.g., text-embedding-3-small)",
    ),
    dimension: Optional[int] = typer.Option(
        None,
        "--dimension",
        help="Embedding dimension (e.g., 512, 1024, 1536)",
    ),
    price_per_1k: Optional[float] = typer.Option(
        None,
        "--price-per-1k",
        help="Price per 1K tokens (USD) for cost estimation",
    ),
    tps_per_worker: Optional[float] = typer.Option(
        None,
        "--tps-per-worker",
        help="Tokens per second per worker for time estimation",
    ),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        help="Number of workers for time estimation",
    ),
    out_dir: str = typer.Option(
        "var/plan_preflight/",
        "--out-dir",
        help="Output directory (tool creates timestamped subdirectory)",
    ),
) -> None:
    """
    Run preflight checks for all runs in a plan file.

    Reads a plan file (default: var/temp_runs_to_embed.txt) and runs
    preflight validation for each run, then produces aggregated reports
    with ready/blocked decisions, reasons, and optional cost/time estimates.

    Writes plan_preflight.json, plan_preflight.csv, plan_preflight.md,
    ready.txt, blocked.txt, and log.out to a timestamped output directory.

    Exit codes:
    - 0: Success (even if some runs are blocked)
    - 1: Fatal error (missing plan file, no runs, CLI misuse)
    """
    import json
    import csv
    import subprocess
    from datetime import datetime, timezone
    from pathlib import Path
    from ..core.paths import runs
    from ..core.config import SETTINGS
    from ..obs.events import stage_run, emit_info

    # Resolve provider/model/dimension from CLI args, env, or defaults
    resolved_provider = provider or SETTINGS.EMBED_PROVIDER or "openai"
    resolved_model = model or SETTINGS.EMBED_MODEL or "text-embedding-3-small"
    resolved_dimension = dimension or SETTINGS.EMBED_DIMENSIONS or 1536

    typer.echo("🔍 Plan preflight check", err=True)
    typer.echo(f"Plan file: {plan_file}", err=True)
    typer.echo(
        f"Provider: {resolved_provider}, Model: {resolved_model}, Dimension: {resolved_dimension}",
        err=True,
    )

    # Check plan file exists
    plan_path = Path(plan_file)
    if not plan_path.exists():
        typer.echo(f"❌ Plan file not found: {plan_file}", err=True)
        raise typer.Exit(1)

    # Read plan file and parse run IDs
    run_entries = []
    with open(plan_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            # Skip blank lines and comments
            if not line or line.startswith("#"):
                continue

            if ":" not in line:
                typer.echo(
                    f"⚠️  Skipping invalid line {line_num}: {line}", err=True
                )
                continue

            run_id, chunk_count_str = line.split(":", 1)
            run_id = run_id.strip()
            chunk_count_str = chunk_count_str.strip()

            try:
                chunk_count = int(chunk_count_str)
            except ValueError:
                typer.echo(
                    f"⚠️  Skipping line {line_num} with invalid chunk count: {line}",
                    err=True,
                )
                continue

            run_entries.append((run_id, chunk_count))

    if not run_entries:
        typer.echo(
            f"❌ No valid runs found in plan file: {plan_file}", err=True
        )
        raise typer.Exit(1)

    typer.echo(f"📊 Found {len(run_entries)} runs in plan", err=True)

    # Create timestamped output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(out_dir) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    typer.echo(f"📁 Output directory: {output_dir}", err=True)

    # Use stage_run context manager for consistent event emission
    with stage_run(
        "plan_preflight",
        timestamp,
        "embed",
        total_runs=len(run_entries),
        provider=resolved_provider,
        model=resolved_model,
        dimension=resolved_dimension,
    ) as ctx:
        # Initialize collections for results
        runs_data: List[Dict[str, Any]] = []
        ready_runs: List[str] = []
        blocked_runs: List[str] = []
        log_entries: List[str] = []

        # Setup structured logging function

    def log_progress(message: str):
        """Log progress to both stderr and log file with structured format."""
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp_str}] {message}"
        typer.echo(log_msg, err=True)
        log_entries.append(log_msg)

    # Process each run
    total_runs = len(run_entries)
    for idx, (run_id, expected_chunk_count) in enumerate(run_entries, 1):
        # No output here - will be logged after preflight completes

        # Run preflight for this run
        try:
            # Build preflight command
            preflight_cmd = [
                "python",
                "-m",
                "trailblazer.cli.main",
                "embed",
                "preflight",
                run_id,
                "--provider",
                resolved_provider,
                "--model",
                resolved_model,
                "--dimension",
                str(resolved_dimension),
            ]

            # Set PYTHONPATH to ensure module can be found
            import os

            env = os.environ.copy()
            env["PYTHONPATH"] = "src"

            result = subprocess.run(
                preflight_cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=Path.cwd(),
            )

            preflight_exit_code = result.returncode

        except Exception as e:
            log_progress(
                f"PREFLIGHT [BLOCKED] {run_id} (reason=PREFLIGHT_ERROR) [{idx}/{total_runs}]"
            )

            # Add to blocked with error reason
            blocked_runs.append(run_id)
            runs_data.append(
                {
                    "rid": run_id,
                    "status": "BLOCKED",
                    "reason": f"PREFLIGHT_ERROR: {str(e)}",
                    "docCount": 0,
                    "chunkCount": 0,
                    "tokenStats": {
                        "min": 0,
                        "median": 0,
                        "p95": 0,
                        "max": 0,
                        "total": 0,
                    },
                    "qualityDistribution": {
                        "p50": 0,
                        "p90": 0,
                        "belowThresholdPct": 0,
                        "minQuality": 0,
                        "maxBelowThresholdPct": 0,
                    },
                    "provider": resolved_provider,
                    "model": resolved_model,
                    "dimension": resolved_dimension,
                    "estimatedCalls": 0,
                    "estimatedTokens": 0,
                    "estCostUSD": None,
                    "estTimeSec": None,
                }
            )
            continue

        # Parse preflight results
        run_dir = runs() / run_id
        preflight_file = run_dir / "preflight" / "preflight.json"

        # Initialize run data with defaults
        run_data: Dict[str, Any] = {
            "rid": run_id,
            "status": "BLOCKED",
            "reason": None,
            "docCount": 0,
            "chunkCount": 0,
            "tokenStats": {
                "min": 0,
                "median": 0,
                "p95": 0,
                "max": 0,
                "total": 0,
            },
            "qualityDistribution": {
                "p50": 0,
                "p90": 0,
                "belowThresholdPct": 0,
                "minQuality": 0,
                "maxBelowThresholdPct": 0,
            },
            "provider": resolved_provider,
            "model": resolved_model,
            "dimension": resolved_dimension,
            "estimatedCalls": 0,
            "estimatedTokens": 0,
            "estCostUSD": None,
            "estTimeSec": None,
        }

        if preflight_exit_code == 0:
            # Preflight passed - parse results
            if preflight_file.exists():
                try:
                    with open(preflight_file) as f:
                        preflight_data = json.load(f)

                    run_data.update(
                        {
                            "status": "READY",
                            "docCount": preflight_data.get("counts", {}).get(
                                "enriched_docs", 0
                            ),
                            "chunkCount": preflight_data.get("counts", {}).get(
                                "chunks", 0
                            ),
                            "tokenStats": preflight_data.get("tokenStats", {}),
                            "qualityDistribution": preflight_data.get(
                                "qualityDistribution", {}
                            ),
                            "estimatedCalls": preflight_data.get(
                                "counts", {}
                            ).get("chunks", 0),
                            "estimatedTokens": preflight_data.get(
                                "tokenStats", {}
                            ).get("total", 0),
                        }
                    )

                    ready_runs.append(run_id)
                    # Extract key stats for structured logging
                    doc_count = preflight_data.get("counts", {}).get(
                        "enriched_docs", 0
                    )
                    chunk_count = preflight_data.get("counts", {}).get(
                        "chunks", 0
                    )
                    total_tokens = preflight_data.get("tokenStats", {}).get(
                        "total", 0
                    )

                    # Emit READY status event
                    emit_info(
                        "plan_preflight",
                        timestamp,
                        "embed",
                        message="Run preflight validation completed",
                        target_run_id=run_id,
                        status="READY",
                        docs=doc_count,
                        chunks=chunk_count,
                        tokens=total_tokens,
                    )

                    log_progress(
                        f"PREFLIGHT [READY] {run_id} (docs={doc_count}, chunks={chunk_count}, tokens={total_tokens}) [{idx}/{total_runs}]"
                    )

                except Exception as e:
                    run_data.update(
                        {
                            "status": "BLOCKED",
                            "reason": f"PREFLIGHT_PARSE_ERROR: {str(e)}",
                        }
                    )
                    blocked_runs.append(run_id)

                    # Emit BLOCKED status event
                    emit_info(
                        "plan_preflight",
                        timestamp,
                        "embed",
                        message="Run preflight validation failed",
                        target_run_id=run_id,
                        status="BLOCKED",
                        reason="PREFLIGHT_PARSE_ERROR",
                    )

                    log_progress(
                        f"PREFLIGHT [BLOCKED] {run_id} (reason=PREFLIGHT_PARSE_ERROR) [{idx}/{total_runs}]"
                    )
            else:
                run_data.update(
                    {"status": "BLOCKED", "reason": "PREFLIGHT_FILE_MISSING"}
                )
                blocked_runs.append(run_id)

                # Emit BLOCKED status event
                emit_info(
                    "plan_preflight",
                    timestamp,
                    "embed",
                    message="Run preflight validation failed",
                    target_run_id=run_id,
                    status="BLOCKED",
                    reason="PREFLIGHT_FILE_MISSING",
                )

                log_progress(
                    f"PREFLIGHT [BLOCKED] {run_id} (reason=PREFLIGHT_FILE_MISSING) [{idx}/{total_runs}]"
                )
        else:
            # Preflight failed - determine reason
            reason = "UNKNOWN_ERROR"
            if (
                "enriched.jsonl" in result.stderr
                or "MISSING_ENRICH" in result.stderr
            ):
                reason = "MISSING_ENRICH"
            elif (
                "chunks.ndjson" in result.stderr
                or "MISSING_CHUNKS" in result.stderr
            ):
                reason = "MISSING_CHUNKS"
            elif (
                "quality" in result.stderr.lower()
                or "QUALITY_GATE" in result.stderr
            ):
                reason = "QUALITY_GATE"
            elif (
                "tiktoken" in result.stderr
                or "TOKENIZER_MISSING" in result.stderr
            ):
                reason = "TOKENIZER_MISSING"
            elif (
                "provider" in result.stderr.lower()
                or "model" in result.stderr.lower()
            ):
                reason = "CONFIG_INVALID"

            run_data.update({"status": "BLOCKED", "reason": reason})
            blocked_runs.append(run_id)

            # Emit BLOCKED status event
            emit_info(
                "plan_preflight",
                timestamp,
                "embed",
                message="Run preflight validation failed",
                target_run_id=run_id,
                status="BLOCKED",
                reason=reason,
            )

            log_progress(
                f"PREFLIGHT [BLOCKED] {run_id} (reason={reason}) [{idx}/{total_runs}]"
            )

        # Add cost/time estimates if pricing info provided
        estimated_tokens = run_data["estimatedTokens"]
        if (
            price_per_1k is not None
            and isinstance(estimated_tokens, int)
            and estimated_tokens > 0
        ):
            run_data["estCostUSD"] = (estimated_tokens / 1000.0) * price_per_1k

        if (
            tps_per_worker is not None
            and workers is not None
            and isinstance(estimated_tokens, int)
            and estimated_tokens > 0
        ):
            total_tps = tps_per_worker * workers
            run_data["estTimeSec"] = estimated_tokens / total_tps

        runs_data.append(run_data)

    # Calculate aggregate totals
    total_docs = sum(
        run["docCount"]
        for run in runs_data
        if isinstance(run.get("docCount"), int)
    )
    total_chunks = sum(
        run["chunkCount"]
        for run in runs_data
        if isinstance(run.get("chunkCount"), int)
    )
    total_tokens = sum(
        run["tokenStats"].get("total", 0)
        for run in runs_data
        if isinstance(run.get("tokenStats"), dict)
        and isinstance(run["tokenStats"].get("total"), int)
    )

    est_cost_usd = None
    est_time_sec = None
    if price_per_1k is not None:
        est_cost_usd = sum(
            run["estCostUSD"]
            for run in runs_data
            if run["estCostUSD"] is not None
            and isinstance(run["estCostUSD"], (int, float))
        )
    if tps_per_worker is not None and workers is not None:
        est_time_sec = sum(
            run["estTimeSec"]
            for run in runs_data
            if run["estTimeSec"] is not None
            and isinstance(run["estTimeSec"], (int, float))
        )

    # Build final JSON report
    report_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": resolved_provider,
        "model": resolved_model,
        "dimension": resolved_dimension,
        "pricePer1k": price_per_1k,
        "tpsPerWorker": tps_per_worker,
        "workers": workers,
        "runsTotal": len(runs_data),
        "runsReady": len(ready_runs),
        "runsBlocked": len(blocked_runs),
        "totals": {
            "docs": total_docs,
            "chunks": total_chunks,
            "tokens": total_tokens,
            "estCostUSD": est_cost_usd,
            "estTimeSec": est_time_sec,
        },
        "runs": runs_data,
    }

    # Write JSON report
    json_file = output_dir / "plan_preflight.json"
    with open(json_file, "w") as f:
        json.dump(report_data, f, indent=2)

    # Write CSV report
    csv_file = output_dir / "plan_preflight.csv"
    with open(csv_file, "w", newline="") as f:
        fieldnames = [
            "rid",
            "status",
            "reason",
            "docCount",
            "chunkCount",
            "tokenTotal",
            "estCalls",
            "estTokens",
            "estCostUSD",
            "estTimeSec",
            "provider",
            "model",
            "dimension",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for run in runs_data:
            writer.writerow(
                {
                    "rid": run["rid"],
                    "status": run["status"],
                    "reason": run["reason"] or "",
                    "docCount": run["docCount"],
                    "chunkCount": run["chunkCount"],
                    "tokenTotal": run["tokenStats"].get("total", 0)
                    if isinstance(run.get("tokenStats"), dict)
                    else 0,
                    "estCalls": run["estimatedCalls"],
                    "estTokens": run["estimatedTokens"],
                    "estCostUSD": run["estCostUSD"] or "",
                    "estTimeSec": run["estTimeSec"] or "",
                    "provider": run["provider"],
                    "model": run["model"],
                    "dimension": run["dimension"],
                }
            )

    # Write Markdown report
    md_file = output_dir / "plan_preflight.md"
    with open(md_file, "w") as f:
        f.write("# Plan Preflight Report\n\n")
        f.write(f"**Timestamp:** {report_data['timestamp']}\n")
        f.write(f"**Provider:** {resolved_provider}\n")
        f.write(f"**Model:** {resolved_model}\n")
        f.write(f"**Dimension:** {resolved_dimension}\n\n")

        f.write("## Summary\n\n")
        f.write(f"- **Total Runs:** {len(runs_data)}\n")
        f.write(f"- **Ready:** {len(ready_runs)}\n")
        f.write(f"- **Blocked:** {len(blocked_runs)}\n")
        f.write(f"- **Total Documents:** {total_docs:,}\n")
        f.write(f"- **Total Chunks:** {total_chunks:,}\n")
        f.write(f"- **Total Tokens:** {total_tokens:,}\n")

        if est_cost_usd is not None:
            f.write(f"- **Estimated Cost:** ${est_cost_usd:.4f} USD\n")
        if est_time_sec is not None:
            f.write(f"- **Estimated Time:** {est_time_sec:.1f} seconds\n")

        f.write(f"\n## Ready Runs ({len(ready_runs)})\n\n")
        if ready_runs:
            f.write(
                "| Run ID | Docs | Chunks | Tokens | Est Cost | Est Time |\n"
            )
            f.write(
                "|--------|------|--------|--------|----------|----------|\n"
            )
            for run in runs_data:
                if run["status"] == "READY":
                    cost_str = (
                        f"${run['estCostUSD']:.4f}"
                        if run["estCostUSD"]
                        else "N/A"
                    )
                    time_str = (
                        f"{run['estTimeSec']:.1f}s"
                        if run["estTimeSec"]
                        else "N/A"
                    )
                    token_total = (
                        run["tokenStats"].get("total", 0)
                        if isinstance(run.get("tokenStats"), dict)
                        else 0
                    )
                    f.write(
                        f"| {run['rid']} | {run['docCount']} | {run['chunkCount']} | {token_total:,} | {cost_str} | {time_str} |\n"
                    )
        else:
            f.write("*No ready runs*\n")

        f.write(f"\n## Blocked Runs ({len(blocked_runs)})\n\n")
        if blocked_runs:
            f.write("| Run ID | Reason |\n")
            f.write("|--------|--------|\n")
            for run in runs_data:
                if run["status"] == "BLOCKED":
                    f.write(f"| {run['rid']} | {run['reason']} |\n")
        else:
            f.write("*No blocked runs*\n")

        f.write("\n## How to fix common failures\n\n")
        f.write(
            "- **MISSING_ENRICH** → run `trailblazer enrich run --run <RID>`\n"
        )
        f.write(
            "- **MISSING_CHUNKS** → run `trailblazer chunk run --run <RID>`\n"
        )
        f.write(
            "- **QUALITY_GATE** → re-run enrich with `--min-quality` lowered (carefully) or fix source docs\n"
        )
        f.write(
            "- **TOKENIZER_MISSING** → install/ensure tokenizer in ops venv\n"
        )
        f.write(
            "- **CONFIG_INVALID** → ensure provider/model/dimension set in env or flags\n"
        )

    # Write ready.txt
    ready_file = output_dir / "ready.txt"
    with open(ready_file, "w") as f:
        for run_id in ready_runs:
            f.write(f"{run_id}\n")

    # Write blocked.txt
    blocked_file = output_dir / "blocked.txt"
    with open(blocked_file, "w") as f:
        for run in runs_data:
            if run["status"] == "BLOCKED":
                f.write(f"{run['rid']}: {run['reason']}\n")

    # Write log.out (structured logs were already added via log_progress)
    log_file = output_dir / "log.out"
    with open(log_file, "w") as f:
        for entry in log_entries:
            f.write(f"{entry}\n")

        # Update context and emit completion event
        ctx.update(
            ready_runs=len(ready_runs),
            blocked_runs=len(blocked_runs),
            total_runs=len(run_entries),
        )
        emit_info(
            "plan_preflight",
            timestamp,
            "embed",
            message="Plan preflight completed",
            ready_runs=len(ready_runs),
            blocked_runs=len(blocked_runs),
            total_runs=len(run_entries),
        )

        # Final summary
        typer.echo("\n📊 Plan Preflight Complete", err=True)
        typer.echo(f"✅ Ready: {len(ready_runs)} runs", err=True)
        typer.echo(f"❌ Blocked: {len(blocked_runs)} runs", err=True)
        typer.echo(f"📁 Reports written to: {output_dir}", err=True)

        # Always exit 0 - this is a reporting tool
        typer.echo("✅ Plan preflight completed successfully", err=True)


@embed_app.command("status")
def embed_status_cmd() -> None:
    """Show current embedding status and database counts."""
    # Run database preflight check first
    _run_db_preflight_check()

    from ..db.engine import get_engine
    from sqlalchemy import text
    from ..core.paths import logs
    import time

    typer.echo("📊 Embedding Status Report")
    typer.echo("=" * 40)

    try:
        engine = get_engine()
        with engine.connect() as conn:
            # Get document counts
            result = conn.execute(text("SELECT COUNT(*) FROM documents"))
            doc_count = result.fetchone()[0]

            result = conn.execute(text("SELECT COUNT(*) FROM chunks"))
            chunk_count = result.fetchone()[0]

            result = conn.execute(
                text("SELECT COUNT(*) FROM chunk_embeddings")
            )
            embedding_count = result.fetchone()[0]

            # Get provider and dimension info
            result = conn.execute(
                text("""
                SELECT provider, dim, COUNT(*) as count
                FROM chunk_embeddings
                GROUP BY provider, dim
                ORDER BY count DESC
            """)
            )
            provider_info = result.fetchall()

            # Get latest embedding timestamp
            result = conn.execute(
                text("""
                SELECT MAX(created_at) as latest_embedding
                FROM chunk_embeddings
            """)
            )
            latest_embedding = result.fetchone()[0]

        typer.echo(f"📄 Documents: {doc_count:,}")
        typer.echo(f"🔤 Chunks: {chunk_count:,}")
        typer.echo(f"🧠 Embeddings: {embedding_count:,}")

        if provider_info:
            typer.echo("\n🔌 Embedding Providers:")
            for provider, dim, count in provider_info:
                typer.echo(f"  • {provider} (dim={dim}): {count:,} embeddings")

        if latest_embedding:
            typer.echo(f"\n⏰ Latest embedding: {latest_embedding}")

        # Show latest logs
        logs_dir = logs() / "embedding"
        if logs_dir.exists():
            log_files = list(logs_dir.glob("*.log"))
            if log_files:
                latest_log = max(log_files, key=lambda x: x.stat().st_mtime)
                typer.echo(f"\n📋 Latest log: {latest_log.name}")

                # Show last few lines if it's a recent log
                if latest_log.stat().st_mtime > (
                    time.time() - 3600
                ):  # Last hour
                    typer.echo("📝 Recent log entries:")
                    try:
                        with open(latest_log, "r") as f:
                            lines = f.readlines()
                            for line in lines[-5:]:  # Last 5 lines
                                typer.echo(f"  {line.rstrip()}")
                    except Exception:
                        typer.echo("  (Unable to read log file)")

        typer.echo(
            f"\n💾 Database: {engine.url.drivername}://{engine.url.host}:{engine.url.port}/{engine.url.database}"
        )

    except Exception as e:
        typer.echo(f"❌ Error getting status: {e}", err=True)
        raise typer.Exit(1)


@embed_app.command("diff")
def embed_diff_cmd(
    run: str = typer.Argument(..., help="Run ID to compare against manifest"),
    against: str = typer.Option(
        "last",
        "--against",
        help="Compare against 'last' manifest or path to specific manifest",
    ),
    format_type: str = typer.Option(
        "json",
        "--format",
        help="Output format: 'json' or 'md'",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Embedding provider (openai, sentencetransformers)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model name (e.g., text-embedding-3-small)",
    ),
    dimension: Optional[int] = typer.Option(
        None,
        "--dimension",
        help="Embedding dimension (e.g., 512, 1024, 1536)",
    ),
) -> None:
    """
    Compare current embedding state against a previous manifest.

    Detects changes in content, provider, model, dimension, tokenizer,
    chunker version, or chunk configuration that would require re-embedding.

    Outputs diff report to var/delta/<RID>/<timestamp>/.
    """
    import json
    from datetime import datetime
    from pathlib import Path
    from ..core.config import SETTINGS
    from ..pipeline.steps.embed.manifest import (
        compute_current_state,
        find_last_manifest,
        load_manifest,
        compare_manifests,
        create_diff_report,
        format_diff_as_markdown,
    )

    # Resolve provider/model/dimension from CLI args, env, or defaults
    resolved_provider = provider or SETTINGS.EMBED_PROVIDER or "openai"
    resolved_model = model or SETTINGS.EMBED_MODEL or "text-embedding-3-small"
    resolved_dimension = dimension or SETTINGS.EMBED_DIMENSIONS or 1536

    typer.echo(f"🔍 Computing diff for run: {run}", err=True)
    typer.echo(
        f"Provider: {resolved_provider}, Model: {resolved_model}, Dimension: {resolved_dimension}",
        err=True,
    )

    # Determine comparison target
    if against == "last":
        manifest_path = find_last_manifest(run)
        if manifest_path is None:
            typer.echo(
                f"❌ No previous manifest found for run: {run}", err=True
            )
            raise typer.Exit(1)
        typer.echo(f"📄 Comparing against: {manifest_path}", err=True)
    else:
        manifest_path = Path(against)
        if not manifest_path.exists():
            typer.echo(f"❌ Manifest not found: {manifest_path}", err=True)
            raise typer.Exit(1)
        typer.echo(f"📄 Comparing against: {manifest_path}", err=True)

    # Load previous manifest
    previous_manifest = load_manifest(manifest_path)
    if previous_manifest is None:
        typer.echo(f"❌ Failed to load manifest: {manifest_path}", err=True)
        raise typer.Exit(1)

    # Compute current state
    try:
        current_state = compute_current_state(
            run, resolved_provider, resolved_model, resolved_dimension
        )
    except Exception as e:
        typer.echo(f"❌ Failed to compute current state: {e}", err=True)
        raise typer.Exit(1)

    # Compare manifests
    has_changes, reasons = compare_manifests(current_state, previous_manifest)

    # Create diff report
    diff_report = create_diff_report(
        run, current_state, previous_manifest, has_changes, reasons
    )

    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    delta_dir = Path("var") / "delta" / run / timestamp
    delta_dir.mkdir(parents=True, exist_ok=True)

    # Write diff report
    if format_type == "json":
        diff_file = delta_dir / "diff.json"
        with open(diff_file, "w", encoding="utf-8") as f:
            json.dump(diff_report, f, indent=2, ensure_ascii=False)
        typer.echo(f"📄 Diff report written: {diff_file}", err=True)
    elif format_type == "md":
        diff_file = delta_dir / "diff.md"
        markdown_content = format_diff_as_markdown(diff_report)
        with open(diff_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        typer.echo(f"📄 Diff report written: {diff_file}", err=True)
    else:
        typer.echo(f"❌ Unknown format: {format_type}", err=True)
        raise typer.Exit(1)

    # Print summary
    if has_changes:
        typer.echo(f"🔄 Changes detected: {', '.join(reasons)}", err=True)
        raise typer.Exit(0)  # Changed but successful
    else:
        typer.echo("✅ No changes detected", err=True)
        raise typer.Exit(0)


@embed_app.command("reembed-if-changed")
def embed_reembed_if_changed_cmd(
    run: str = typer.Argument(..., help="Run ID to conditionally re-embed"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force re-embedding even if no changes detected",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Embedding provider (openai, sentencetransformers)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model name (e.g., text-embedding-3-small)",
    ),
    dimension: Optional[int] = typer.Option(
        None,
        "--dimension",
        help="Embedding dimension (e.g., 512, 1024, 1536)",
    ),
    batch_size: int = typer.Option(
        128, "--batch", help="Batch size for embedding generation"
    ),
) -> None:
    """
    Conditionally re-embed a run only if changes are detected.

    This command:
    1. Runs preflight checks
    2. Compares current state against the last manifest
    3. Skips embedding if no changes and --force not set
    4. Proceeds with embedding if changes detected or --force set
    5. Writes a new manifest after successful embedding
    """
    import os
    import subprocess
    import sys
    from pathlib import Path
    from ..core.config import SETTINGS
    from ..pipeline.steps.embed.manifest import (
        find_last_manifest,
        load_manifest,
        compute_current_state,
        compare_manifests,
    )

    # Resolve provider/model/dimension from CLI args, env, or defaults
    resolved_provider = provider or SETTINGS.EMBED_PROVIDER or "openai"
    resolved_model = model or SETTINGS.EMBED_MODEL or "text-embedding-3-small"
    resolved_dimension = dimension or SETTINGS.EMBED_DIMENSIONS or 1536

    typer.echo(f"🔍 Conditional re-embed for run: {run}", err=True)
    typer.echo(
        f"Provider: {resolved_provider}, Model: {resolved_model}, Dimension: {resolved_dimension}",
        err=True,
    )

    # Step 1: Run preflight checks
    typer.echo("1️⃣ Running preflight checks...", err=True)
    try:
        preflight_cmd = [
            sys.executable,
            "-m",
            "trailblazer.cli.main",
            "embed",
            "preflight",
            run,
            "--provider",
            resolved_provider,
            "--model",
            resolved_model,
            "--dim",
            str(resolved_dimension),
        ]

        result = subprocess.run(
            preflight_cmd,
            capture_output=True,
            text=True,
            env={**dict(os.environ), "PYTHONPATH": "src"},
            cwd=Path.cwd(),
        )

        if result.returncode != 0:
            typer.echo("❌ Preflight checks failed", err=True)
            typer.echo(result.stderr, err=True)
            raise typer.Exit(1)

        typer.echo("✅ Preflight checks passed", err=True)
    except Exception as e:
        typer.echo(f"❌ Preflight error: {e}", err=True)
        raise typer.Exit(1)

    # Step 2: Check for changes (unless force is set)
    if not force:
        typer.echo("2️⃣ Checking for changes...", err=True)

        # Find last manifest
        manifest_path = find_last_manifest(run)
        if manifest_path is None:
            typer.echo(
                "📄 No previous manifest found, proceeding with embedding",
                err=True,
            )
        else:
            # Load previous manifest
            previous_manifest = load_manifest(manifest_path)
            if previous_manifest is None:
                typer.echo(
                    "⚠️  Failed to load previous manifest, proceeding with embedding",
                    err=True,
                )
            else:
                try:
                    # Compute current state
                    current_state = compute_current_state(
                        run,
                        resolved_provider,
                        resolved_model,
                        resolved_dimension,
                    )

                    # Compare manifests
                    has_changes, reasons = compare_manifests(
                        current_state, previous_manifest
                    )

                    if not has_changes:
                        typer.echo(
                            "✅ No changes detected, skipping embedding",
                            err=True,
                        )
                        return  # Exit successfully without embedding
                    else:
                        typer.echo(
                            f"🔄 Changes detected: {', '.join(reasons)}",
                            err=True,
                        )
                        typer.echo("📄 Proceeding with embedding...", err=True)

                except Exception as e:
                    typer.echo(
                        f"⚠️  Error checking changes: {e}, proceeding with embedding",
                        err=True,
                    )
    else:
        typer.echo("2️⃣ Force flag set, skipping change detection", err=True)

    # Step 3: Proceed with embedding
    typer.echo("3️⃣ Starting embedding...", err=True)
    try:
        embed_cmd = [
            sys.executable,
            "-m",
            "trailblazer.cli.main",
            "embed",
            "load",
            "--run-id",
            run,
            "--provider",
            resolved_provider,
            "--model",
            resolved_model,
            "--dimension",
            str(resolved_dimension),
            "--batch",
            str(batch_size),
        ]

        result = subprocess.run(
            embed_cmd,
            env={**dict(os.environ), "PYTHONPATH": "src"},
            cwd=Path.cwd(),
            text=True,
        )

        if result.returncode != 0:
            typer.echo("❌ Embedding failed", err=True)
            raise typer.Exit(1)

        typer.echo("✅ Embedding completed successfully", err=True)

    except Exception as e:
        typer.echo(f"❌ Embedding error: {e}", err=True)
        raise typer.Exit(1)


@qa_app.command("retrieval")
def qa_retrieval_cmd(
    queries_file: str = typer.Option(
        "prompts/qa/queries_n2s.yaml",
        "--queries-file",
        help="YAML file containing queries to test",
    ),
    budgets: str = typer.Option(
        "1500,4000,6000",
        "--budgets",
        help="Comma-separated character budgets for context packing",
    ),
    top_k: int = typer.Option(
        12,
        "--top-k",
        help="Number of top results to retrieve per query",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Embedding provider (defaults from env: TRAILBLAZER_EMBED_PROVIDER)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Embedding model (defaults from env: TRAILBLAZER_EMBED_MODEL)",
    ),
    dimension: Optional[int] = typer.Option(
        None,
        "--dimension",
        help="Embedding dimension (defaults from env: TRAILBLAZER_EMBED_DIMENSION)",
    ),
    out_dir: str = typer.Option(
        "var/retrieval_qc",
        "--out-dir",
        help="Output directory for QA artifacts",
    ),
    min_unique_docs: int = typer.Option(
        3,
        "--min-unique-docs",
        help="Minimum unique documents required per budget",
    ),
    max_tie_rate: float = typer.Option(
        0.35,
        "--max-tie-rate",
        help="Maximum allowed tie rate (identical scores)",
    ),
    require_traceability: bool = typer.Option(
        True,
        "--require-traceability/--no-require-traceability",
        help="Require title, url, source_system fields",
    ),
) -> None:
    """
    Run retrieval QA harness with domain queries and health metrics.

    Tests retrieval quality using curated N2S domain questions across
    multiple context budgets. Generates readiness report with health
    metrics including doc diversity, tie rates, and traceability.

    Example:
        trailblazer qa retrieval \\
          --queries-file prompts/qa/queries_n2s.yaml \\
          --budgets 1500,4000,6000 \\
          --provider openai --model text-embedding-3-small --dimension 1536
    """
    import os
    from datetime import datetime, timezone
    from ..qa.retrieval import run_retrieval_qa

    # Set pager environment variables
    os.environ["PAGER"] = "cat"
    os.environ["LESS"] = "-RFX"

    # Run preflight check
    _run_db_preflight_check()

    # Parse budgets
    try:
        budget_list = [int(b.strip()) for b in budgets.split(",")]
    except ValueError:
        typer.echo(
            "❌ Invalid budgets format. Use comma-separated integers.",
            err=True,
        )
        raise typer.Exit(1)

    # Get defaults from environment
    if provider is None:
        provider = os.getenv("TRAILBLAZER_EMBED_PROVIDER", "openai")
    if model is None:
        model = os.getenv("TRAILBLAZER_EMBED_MODEL", "text-embedding-3-small")
    if dimension is None:
        dimension = int(os.getenv("TRAILBLAZER_EMBED_DIMENSION", "1536"))

    # Create timestamped output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(out_dir) / timestamp

    try:
        # Run the QA harness
        results = run_retrieval_qa(
            queries_file=queries_file,
            budgets=budget_list,
            top_k=top_k,
            provider=provider,
            model=model,
            dimension=dimension,
            output_dir=output_dir,
            min_unique_docs=min_unique_docs,
            max_tie_rate=max_tie_rate,
            require_traceability=require_traceability,
        )

        # Print summary
        typer.echo(
            f"✅ QA completed: {results['total_queries']} queries", err=True
        )
        typer.echo(f"📊 Pass rate: {results['pass_rate']:.1%}", err=True)
        typer.echo(f"📁 Results: {output_dir}", err=True)

        # Exit with error code if overall failure
        if not results["overall_pass"]:
            raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"❌ QA error: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    # Enforce macOS venv check before any commands
    from ..env_checks import assert_virtualenv_on_macos

    assert_virtualenv_on_macos()

    app()
