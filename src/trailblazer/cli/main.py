import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import typer

from ..core.config import SETTINGS, Settings
from ..core.logging import log, setup_logging
from ..pipeline.runner import run as run_pipeline
from .db_admin import app as db_admin_app

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
admin_app = typer.Typer(help="Administrative commands")
app.add_typer(ingest_app, name="ingest")
app.add_typer(normalize_app, name="normalize")
app.add_typer(db_app, name="db")
app.add_typer(db_admin_app, name="db-admin")
app.add_typer(embed_app, name="embed")
app.add_typer(confluence_app, name="confluence")
app.add_typer(ops_app, name="ops")
app.add_typer(paths_app, name="paths")
app.add_typer(runs_app, name="runs")
app.add_typer(admin_app, name="admin")


def _run_db_preflight_check() -> None:
    """Run database health check and exit if it fails.

    This is used as a preflight check for commands that require database access.
    """
    import os

    from ..db.engine import check_db_health

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
                raise typer.Exit(1) from e

        # For PostgreSQL, require pgvector
        if health_info["dialect"] == "postgresql" and not health_info["pgvector"]:
            typer.echo(
                "❌ Database preflight failed: pgvector extension not found",
                err=True,
            )
            typer.echo(
                "Use 'make db.up' then 'trailblazer db doctor' to get started",
                err=True,
            )
            raise typer.Exit(1) from e

    except Exception as e:
        typer.echo(f"❌ Database preflight failed: {e}", err=True)
        typer.echo(
            "Use 'make db.up' then 'trailblazer db doctor' to get started",
            err=True,
        )
        raise typer.Exit(1) from e


@app.callback()
def _init() -> None:
    setup_logging()


@app.command()
def version() -> None:
    from .. import __version__

    typer.echo(__version__)


@app.command()
def run(
    config_file: str | None = typer.Option(
        None,
        "--config",
        help="Config file (.trailblazer.yaml auto-discovered)",
    ),
    phases: list[str] | None = typer.Option(None, "--phases", help="Subset of phases to run, in order"),
    reset: str | None = typer.Option(None, "--reset", help="Reset scope: artifacts|embeddings|all"),
    resume: bool = typer.Option(False, "--resume", help="Resume from last incomplete run"),
    since: str | None = typer.Option(None, "--since", help="Override since timestamp"),
    workers: int | None = typer.Option(None, "--workers", help="Override worker count"),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of runs to process from backlog"),
    provider: str | None = typer.Option(None, "--provider", help="Override embedding provider"),
    model: str | None = typer.Option(None, "--model", help="Override embedding model"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not execute; just scaffold outputs"),
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
        raise typer.Exit(1) from e

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


def _handle_reset(reset_scope: str, settings: Settings, yes: bool, dry_run: bool) -> None:
    """Handle reset operations with confirmation and reporting."""
    import json
    import shutil
    from datetime import datetime, timezone
    from pathlib import Path
    from typing import Any

    from ..core.artifacts import new_run_id, runs_dir
    from ..db.engine import get_engine

    valid_scopes = ["artifacts", "embeddings", "all"]
    if reset_scope not in valid_scopes:
        typer.echo(
            f"❌ Invalid reset scope: {reset_scope}. Use: {', '.join(valid_scopes)}",
            err=True,
        )
        raise typer.Exit(1) from e

    # Prepare reset report
    reset_id = new_run_id()
    report_dir = Path(f"var/reports/{reset_id}")
    report_dir.mkdir(parents=True, exist_ok=True)
    reset_report = report_dir / "reset.md"

    report: dict[str, Any] = {
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
                typer.echo(f"🗑️  {'Would clear' if dry_run else 'Cleared'} artifacts: {runs_base}")

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
                            conn.execute(text("TRUNCATE TABLE IF EXISTS embeddings CASCADE"))
                            conn.execute(text("TRUNCATE TABLE IF EXISTS chunks CASCADE"))
                            conn.execute(text("TRUNCATE TABLE IF EXISTS documents CASCADE"))
                            conn.commit()
                    report["actions"].append(
                        {
                            "type": "embeddings_cleared",
                            "database": settings.TRAILBLAZER_DB_URL.split("@")[-1],  # Hide credentials
                            "completed": not dry_run,
                        }
                    )
                    typer.echo(f"🗑️  {'Would clear' if dry_run else 'Cleared'} embeddings from database")
                except Exception as e:
                    report["actions"].append({"type": "embeddings_clear_failed", "error": str(e)})
                    typer.echo(f"❌ Failed to clear embeddings: {e}", err=True)
            else:
                typer.echo("⚠️  No database URL configured, skipping embeddings reset")

        # Write reset report
        with open(reset_report, "w") as f:
            f.write(f"# Reset Report: {reset_id}\n\n")
            f.write(f"**Timestamp:** {report['timestamp']}\n")
            f.write(f"**Scope:** {reset_scope}\n")
            f.write(f"**Dry Run:** {dry_run}\n\n")
            f.write("## Actions Taken\n\n")
            for action in report["actions"]:
                f.write(f"- **{action['type']}**: {action.get('path', action.get('database', 'N/A'))}\n")
                if "error" in action:
                    f.write(f"  - Error: {action['error']}\n")

        # Also write JSON for automation
        with open(report_dir / "reset.json", "w") as f:
            json.dump(report, f, indent=2)

        typer.echo(f"📄 Reset report: {reset_report}")

    except Exception as e:
        typer.echo(f"❌ Reset failed: {e}", err=True)
        raise typer.Exit(1) from e


def _find_resumable_run(settings: Settings) -> str | None:
    """Find the most recent incomplete run that can be resumed."""
    from ..core.artifacts import phase_dir, runs_dir

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
            phase_dir(run_id, phase).exists() for phase in final_phases if phase in settings.PIPELINE_PHASES
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
    space: list[str] = typer.Option([], "--space", help="Confluence space keys"),
    space_id: list[str] = typer.Option([], "--space-id", help="Confluence space ids"),
    since: str | None = typer.Option(None, help='ISO timestamp, e.g. "2025-08-01T00:00:00Z"'),
    auto_since: bool = typer.Option(False, "--auto-since", help="Auto-read since from state files"),
    body_format: str = typer.Option(
        "atlas_doc_format",
        help="Body format: storage or atlas_doc_format (default: atlas_doc_format)",
    ),
    max_pages: int | None = typer.Option(None, help="Stop after N pages (debug)"),
    progress: bool = typer.Option(False, "--progress", help="Show per-page progress"),
    progress_every: int = typer.Option(1, "--progress-every", help="Progress output every N pages"),
    allow_empty: bool = typer.Option(False, "--allow-empty", help="Allow zero pages without error"),
    log_format: str = typer.Option("auto", "--log-format", help="Logging format: json|plain|auto"),
    quiet_pretty: bool = typer.Option(False, "--quiet-pretty", help="Suppress banners but keep progress bars"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
) -> None:
    from typing import cast

    from ..core.artifacts import new_run_id, phase_dir
    from ..core.logging import LogFormat, setup_logging
    from ..core.progress import init_progress
    from ..pipeline.steps.ingest.confluence import ingest_confluence

    # Setup logging first
    setup_logging(format_type=(cast(LogFormat, log_format) if log_format in ("json", "plain", "auto") else "auto"))

    # Initialize progress renderer
    progress_renderer = init_progress(enabled=progress, quiet_pretty=quiet_pretty, no_color=no_color)

    rid = new_run_id()
    out = str(phase_dir(rid, "ingest"))

    try:
        dt = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None

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
        raise typer.Exit(2) from e
    except Exception as e:
        # Check if it's an auth/API error or other remote failure
        error_str = str(e).lower()
        if any(keyword in error_str for keyword in ["auth", "unauthorized", "forbidden", "401", "403"]):
            log.error("cli.ingest.confluence.auth_error", error=str(e))
            typer.echo(f"❌ Authentication error: {e}", err=True)
            raise typer.Exit(2) from e
        elif any(keyword in error_str for keyword in ["connection", "timeout", "network", "api", "http"]):
            log.error("cli.ingest.confluence.api_error", error=str(e))
            typer.echo(f"❌ API/Network error: {e}", err=True)
            raise typer.Exit(3) from e
        else:
            log.error("cli.ingest.confluence.unknown_error", error=str(e))
            typer.echo(f"❌ Unexpected error: {e}", err=True)
            raise typer.Exit(1) from e


@ingest_app.command("dita")
def ingest_dita_cmd(
    root: str = typer.Option(
        "data/raw/dita/ellucian-documentation",
        "--root",
        help="Root directory for DITA files",
    ),
    include: list[str] = typer.Option(
        [],
        "--include",
        help="Include glob patterns (default: **/*.dita, **/*.xml, **/*.ditamap)",
    ),
    exclude: list[str] = typer.Option([], "--exclude", help="Exclude glob patterns"),
    progress: bool = typer.Option(False, "--progress", help="Show per-file progress"),
    progress_every: int = typer.Option(1, "--progress-every", help="Progress output every N files"),
    log_format: str = typer.Option("auto", "--log-format", help="Logging format: json|plain|auto"),
    quiet_pretty: bool = typer.Option(False, "--quiet-pretty", help="Suppress banners but keep progress bars"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
) -> None:
    """Ingest DITA topics and maps from local filesystem."""
    from typing import cast

    from ..core.artifacts import new_run_id, phase_dir
    from ..core.logging import LogFormat, setup_logging
    from ..core.progress import init_progress
    from ..pipeline.steps.ingest.dita import ingest_dita

    # Setup logging first
    setup_logging(format_type=(cast(LogFormat, log_format) if log_format in ("json", "plain", "auto") else "auto"))

    # Initialize progress renderer
    progress_renderer = init_progress(enabled=progress, quiet_pretty=quiet_pretty, no_color=no_color)

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
        raise typer.Exit(1) from e


@confluence_app.command("spaces")
def confluence_spaces_cmd() -> None:
    """List Confluence spaces with structured logging and artifact output."""
    import json

    from tabulate import tabulate  # type: ignore

    from ..adapters.confluence_api import ConfluenceClient
    from ..core.artifacts import new_run_id, phase_dir

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
            "homepage_id": str(space.get("homepageId", "") if space.get("homepageId") else ""),
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
        table_data = [[s["id"], s["key"], s["name"], s["type"], s["status"]] for s in spaces]
        headers = ["ID", "KEY", "NAME", "TYPE", "STATUS"]
        typer.echo(tabulate(table_data, headers=headers, tablefmt="grid"))
    else:
        typer.echo("No spaces found.")

    typer.echo(f"\n📄 Spaces written to: {spaces_file}")
    log.info("cli.confluence.spaces.done", run_id=rid, spaces_count=len(spaces))


@ingest_app.command("diff-deletions")
def ingest_diff_deletions_cmd(
    space: str = typer.Option(..., "--space", help="Confluence space key"),
    baseline_run: str = typer.Option(..., "--baseline-run", help="Baseline run ID"),
    current_run: str = typer.Option(..., "--current-run", help="Current run ID"),
) -> None:
    """Find deleted page IDs between two runs."""
    import json

    from ..core.artifacts import runs_dir

    runs_base = runs_dir()

    # Read baseline seen IDs
    baseline_file = runs_base / baseline_run / "ingest" / f"{space}_seen_page_ids.json"
    if not baseline_file.exists():
        typer.echo(f"❌ Baseline file not found: {baseline_file}", err=True)
        raise typer.Exit(1) from e

    with open(baseline_file) as f:
        baseline_ids = set(json.load(f))

    # Read current seen IDs
    current_file = runs_base / current_run / "ingest" / f"{space}_seen_page_ids.json"
    if not current_file.exists():
        typer.echo(f"❌ Current file not found: {current_file}", err=True)
        raise typer.Exit(1) from e

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
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Run ID to normalize (uses runs/<RUN_ID>/ingest/confluence.ndjson)",
    ),
    input_file: str | None = typer.Option(
        None,
        "--input",
        help="Input NDJSON file to normalize (overrides --run-id)",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of pages to process"),
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
        typer.echo(f"  pgvector: {'✅ available' if health_info['pgvector'] else '❌ not available'}")

        # Exit with error if PostgreSQL but no pgvector
        if health_info["dialect"] == "postgresql" and not health_info["pgvector"]:
            typer.echo(
                "\n⚠️  pgvector extension not found. Run 'trailblazer db init' or manually:",
                err=True,
            )
            typer.echo("    psql -d your_db -c 'CREATE EXTENSION vector;'", err=True)
            raise typer.Exit(1) from e

    except Exception as e:
        typer.echo(f"❌ Database check failed: {e}", err=True)
        raise typer.Exit(1) from e


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
        typer.echo(f"🗃️  Database: {parsed_url.path.lstrip('/') if parsed_url.path else 'default'}")

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
                        result = session.execute(text("SELECT DISTINCT dim FROM chunk_embeddings LIMIT 5"))
                        dims = [row[0] for row in result]
                        if dims:
                            typer.echo(f"   📏 Embedding dimensions found: {dims}")
                        else:
                            typer.echo("   📏 No embeddings found (empty database)")
                    except Exception as e:
                        typer.echo(f"   📏 Could not check embeddings: {e}")
            else:
                typer.echo("   ❌ pgvector extension: NOT available")
                typer.echo("      Run 'trailblazer db init' or manually:")
                typer.echo("      psql -d your_db -c 'CREATE EXTENSION vector;'")
                raise typer.Exit(1) from e
        else:
            # Non-PostgreSQL database - not supported
            typer.echo(f"\n❌ Unsupported database: {health_info['dialect']}")
            typer.echo("   Only PostgreSQL is supported.")
            typer.echo("   Run 'make db.up' then 'trailblazer db doctor'")
            raise typer.Exit(1) from e

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
        raise typer.Exit(1) from e


@db_app.command("init")
def db_init_cmd() -> None:
    """Initialize database schema (safe if tables already exist)."""
    from urllib.parse import urlparse

    from ..db.engine import (
        create_tables,
        ensure_vector_index,
        get_db_url,
        initialize_postgres_extensions,
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
        if health_info["dialect"] == "postgresql" and not health_info["pgvector"]:
            typer.echo("⚠️  pgvector extension not detected. You may need to run manually:")
            typer.echo("    psql -d your_db -c 'CREATE EXTENSION vector;'")
        elif health_info["dialect"] == "postgresql" and health_info["pgvector"]:
            typer.echo("✅ pgvector extension ready and vector index created")

    except Exception as e:
        typer.echo(f"❌ Error initializing database: {e}", err=True)
        raise typer.Exit(1) from e


def _check_dimension_compatibility(provider: str, requested_dim: int | None) -> None:
    """Check if requested dimensions are compatible with existing embeddings.

    Args:
        provider: The embedding provider name
        requested_dim: The requested dimension (if any)

    Raises:
        typer.Exit: If dimension mismatch detected and reembed_all not used
    """
    from sqlalchemy import text

    from ..db.engine import get_session

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
                text("SELECT DISTINCT dim FROM chunk_embeddings WHERE provider = :provider LIMIT 1"),
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
                raise typer.Exit(1) from e
        except Exception:
            # If we can't check, continue (might be empty database)
            pass


@embed_app.command("load")
def embed_load_cmd(
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Run ID to load (uses runs/<RUN_ID>/normalize/normalized.ndjson)",
    ),
    input_file: str | None = typer.Option(
        None,
        "--input",
        help="Input NDJSON file to load (overrides --run-id)",
    ),
    provider: str = typer.Option(
        "dummy",
        "--provider",
        help="Embedding provider (dummy, openai, sentencetransformers)",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model name (e.g., text-embedding-3-small, BAAI/bge-small-en-v1.5)",
    ),
    dimension: int | None = typer.Option(
        None,
        "--dimension",
        help="Embedding dimension (e.g., 512, 1024, 1536)",
    ),
    batch_size: int = typer.Option(128, "--batch", help="Batch size for embedding generation"),
    max_docs: int | None = typer.Option(None, "--max-docs", help="Maximum number of documents to process"),
    max_chunks: int | None = typer.Option(None, "--max-chunks", help="Maximum number of chunks to process"),
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
    """Load normalized documents to database with embeddings."""
    # Run database preflight check first
    _run_db_preflight_check()

    # Check dimension compatibility unless we're doing a full re-embed
    if not reembed_all:
        _check_dimension_compatibility(provider, dimension)

    from ..db.engine import get_db_url
    from ..pipeline.steps.embed.loader import load_chunks_to_db

    if not run_id and not input_file:
        raise typer.BadParameter("Either --run-id or --input must be provided")

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
            chunks_file=input_file,
            provider_name=provider,
            model=model,
            dimension=dimension,
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
        typer.echo(f"  Documents: {metrics.get('docs_embedded', 0)} embedded, {metrics.get('docs_skipped', 0)} skipped")
        typer.echo(
            f"  Chunks: {metrics.get('chunks_embedded', 0)} embedded, {metrics.get('chunks_skipped', 0)} skipped"
        )
        typer.echo(f"  Provider: {metrics['provider']} (dim={metrics['dimension']})")
        if metrics.get("model"):
            typer.echo(f"  Model: {metrics['model']}")
        if dry_run_cost:
            typer.echo(f"  Estimated tokens: {metrics.get('estimated_tokens', 0):,}")
            if metrics.get("estimated_cost"):
                typer.echo(f"  Estimated cost: ${metrics.get('estimated_cost', 0):.4f}")
        typer.echo(f"  Duration: {metrics['duration_seconds']:.2f}s")

    except Exception as e:
        typer.echo(f"❌ Error loading embeddings: {e}", err=True)
        raise typer.Exit(1) from e


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question to ask"),
    top_k: int = typer.Option(8, "--top-k", help="Number of top chunks to retrieve"),
    max_chunks_per_doc: int = typer.Option(3, "--max-chunks-per-doc", help="Maximum chunks per document"),
    provider: str = typer.Option(
        "dummy",
        "--provider",
        help="Embedding provider (dummy, openai, sentencetransformers)",
    ),
    max_chars: int = typer.Option(6000, "--max-chars", help="Maximum characters in context"),
    format_output: str = typer.Option("text", "--format", help="Output format (text, json)"),
    out_dir: str | None = typer.Option(None, "--out", help="Output directory (default: runs/<run_id>/ask/)"),
    db_url: str | None = typer.Option(None, "--db-url", help="Database URL override"),
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
        create_context_summary,
        group_by_doc,
        pack_context,
    )

    # Setup
    run_id = new_run_id()
    out_path = Path(out_dir) if out_dir else phase_dir(run_id, "ask")
    out_path.mkdir(parents=True, exist_ok=True)

    # Use db_url from parameter or environment
    final_db_url = db_url or os.getenv("TRAILBLAZER_DB_URL")
    if not final_db_url:
        typer.echo("❌ TRAILBLAZER_DB_URL required", err=True)
        raise typer.Exit(1) from e

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
        retriever = create_retriever(db_url=final_db_url, provider_name=provider)

        # Perform search with event logging
        search_start = time.time()
        emit_event("search.begin", query=question, top_k=top_k, provider=provider)
        hits = retriever.search(question, top_k=top_k)
        emit_event("search.end", total_hits=len(hits))
        search_time = time.time() - search_start

        if not hits:
            typer.echo("❌ No results found", err=True)
            emit_event("ask.no_results")
            raise typer.Exit(1) from e

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
        summary = create_context_summary(question, grouped_hits, provider, timing_info)
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
            typer.echo(f"  Characters: {summary['total_characters']:,}", err=True)
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
                typer.echo(f"  {i + 1}. {title} (score: {score:.3f})", err=True)
                if url:
                    typer.echo(f"     {url}", err=True)

            if len(grouped_hits) > 3:
                typer.echo(f"     ... and {len(grouped_hits) - 3} more", err=True)

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
        raise typer.Exit(1) from e


@ops_app.command("prune-runs")
def ops_prune_runs_cmd(
    keep: int = typer.Option(..., "--keep", help="Number of newest runs to keep"),
    min_age_days: int = typer.Option(..., "--min-age-days", help="Minimum age in days for deletion"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Dry run mode (default: true)"),
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
    report_file = reports_dir / f"prune_report_{now.strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)

    # Output
    typer.echo(f"🗂️  Total runs: {len(run_dirs)}")
    typer.echo(f"🛡️  Protected runs: {len(protected_runs)}")
    typer.echo(f"🗑️  Deletion candidates: {len(candidates)}")

    if candidates:
        typer.echo("\nCandidates for deletion:")
        for candidate in candidates:
            typer.echo(f"  - {candidate['run_id']} (age: {candidate['age_days']} days)")

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
        typer.echo("\n💡 This is a dry run. Use --no-dry-run to actually delete.")

    typer.echo(f"\n📄 Report written to: {report_file}")
    log.info(
        "cli.ops.prune_runs.done",
        **{k: v for k, v in report.items() if k != "candidates"},
    )


# ========== Paths Commands ==========


@paths_app.command()
def show(
    json_output: bool = typer.Option(False, "--json", help="Output paths as JSON"),
) -> None:
    """Show resolved workspace paths."""
    import json

    from ..core import paths

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
            raise typer.Exit(1) from e


def _get_confluence_spaces() -> list[str]:
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
            typer.echo("💡 Check your Confluence credentials in .env:", err=True)
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
        typer.echo("   2. Test connection: trailblazer confluence spaces", err=True)
        typer.echo("   3. Verify CONFLUENCE_BASE_URL format", err=True)
        raise typer.Exit(1) from e


def _get_runs_needing_normalization() -> list[str]:
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
            if (ingest_dir / "confluence.ndjson").exists() or (ingest_dir / "dita.ndjson").exists():
                runs_needing_norm.append(run_dir.name)

    return sorted(runs_needing_norm)


@app.command()
def plan(
    confluence: bool = typer.Option(True, "--confluence/--no-confluence", help="Plan Confluence ingestion"),
    dita: bool = typer.Option(True, "--dita/--no-dita", help="Plan DITA ingestion"),
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
                    typer.echo(f"     ... and {len(spaces) - 5} more", err=True)
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
    confluence: bool = typer.Option(True, "--confluence/--no-confluence", help="Ingest Confluence"),
    dita: bool = typer.Option(True, "--dita/--no-dita", help="Ingest DITA"),
    progress: bool = typer.Option(True, "--progress/--no-progress", help="Show progress"),
    progress_every: int = typer.Option(10, "--progress-every", help="Progress frequency"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    since: str | None = typer.Option(None, "--since", help="ISO timestamp for delta ingestion"),
    auto_since: bool = typer.Option(False, "--auto-since", help="Auto-detect since from state"),
    max_pages: int | None = typer.Option(None, "--max-pages", help="Debug: limit pages"),
    from_scratch: bool = typer.Option(False, "--from-scratch", help="Clear var/state before starting"),
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
        import shutil

        from ..core import paths

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
                typer.echo(f"❌ Failed space: {space} (exit {e.returncode})", err=True)

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
            typer.echo(f"❌ Failed DITA ingestion (exit {e.returncode})", err=True)

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
    progress: bool = typer.Option(True, "--progress/--no-progress", help="Show progress"),
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

    typer.echo(f"🔄 Found {len(runs_to_normalize)} runs needing normalization:")
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

    typer.echo(f"\n📊 Normalization complete: {successful}/{len(runs_to_normalize)} successful")


@app.command()
def enrich(
    run_id: str = typer.Argument(..., help="Run ID to enrich (must have normalize phase completed)"),
    llm: bool = typer.Option(
        False,
        "--llm/--no-llm",
        help="Enable LLM-based enrichment (default: off)",
    ),
    max_docs: int | None = typer.Option(None, "--max-docs", help="Maximum number of documents to process"),
    budget: str | None = typer.Option(None, "--budget", help="Budget limit for LLM usage (soft limit)"),
    min_quality: float = typer.Option(0.60, "--min-quality", help="Minimum quality score threshold (0.0-1.0)"),
    max_below_threshold_pct: float = typer.Option(
        0.20,
        "--max-below-threshold-pct",
        help="Maximum percentage of docs below quality threshold",
    ),
    progress: bool = typer.Option(True, "--progress/--no-progress", help="Show progress output"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
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
    from ..core.progress import ProgressRenderer
    from ..pipeline.steps.enrich import enrich_from_normalized

    # Validate run exists and has normalized data
    normalize_dir = phase_dir(run_id, "normalize")
    if not normalize_dir.exists():
        typer.echo(
            f"❌ Run {run_id} not found or normalize phase not completed",
            err=True,
        )
        raise typer.Exit(1) from e

    normalized_file = normalize_dir / "normalized.ndjson"
    if not normalized_file.exists():
        typer.echo(f"❌ Normalized file not found: {normalized_file}", err=True)
        raise typer.Exit(1) from e

    # Setup output directory
    enrich_dir = phase_dir(run_id, "enrich")
    enrich_dir.mkdir(parents=True, exist_ok=True)

    # Setup progress renderer
    progress_renderer = ProgressRenderer(no_color=no_color)

    # NDJSON event emitter - outputs to stdout
    def emit_event(event_type: str, **kwargs):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "run_id": run_id,
            **kwargs,
        }
        print(json.dumps(event))

    # Progress callback for human-readable updates to stderr
    def progress_callback(docs_processed: int, rate: float, elapsed: float, docs_llm: int):
        if progress:
            typer.echo(
                f"[ENRICH] docs={docs_processed} rate={rate:.1f}/s elapsed={elapsed:.1f}s llm_used={docs_llm}",
                err=True,
            )

    # Show banner
    if progress:
        progress_renderer.start_banner(run_id=run_id, spaces=1)  # Single "phase" for enrichment
        typer.echo(f"📁 Input: {normalized_file}", err=True)
        typer.echo(f"📂 Output: {enrich_dir}", err=True)
        typer.echo(f"🧠 LLM enabled: {llm}", err=True)
        if max_docs:
            typer.echo(f"📊 Max docs: {max_docs:,}", err=True)
        typer.echo("", err=True)

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

        # Show completion summary
        if progress:
            typer.echo("", err=True)
            typer.echo("✅ ENRICH COMPLETE", err=True)
            typer.echo(f"📊 Documents processed: {stats['docs_total']:,}", err=True)
            if llm:
                typer.echo(f"🧠 LLM enriched: {stats['docs_llm']:,}", err=True)
                typer.echo(
                    f"🔗 Suggested edges: {stats['suggested_edges_total']:,}",
                    err=True,
                )
            typer.echo(
                f"⚠️  Quality flags: {sum(stats['quality_flags_counts'].values()):,}",
                err=True,
            )
            typer.echo(f"⏱️  Duration: {duration:.1f}s", err=True)
            typer.echo(f"📄 Assurance: {assurance_json}", err=True)
            typer.echo(f"📄 Assurance: {assurance_md}", err=True)

        emit_event("enrich.complete", duration_seconds=duration)

    except Exception as e:
        emit_event("enrich.error", error=str(e))
        typer.echo(f"❌ Enrichment failed: {e}", err=True)
        raise typer.Exit(1) from e


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


@app.command()
def chunk(
    run_id: str = typer.Argument(
        ...,
        help="Run ID to chunk (must have enrich or normalize phase completed)",
    ),
    max_tokens: int = typer.Option(800, "--max-tokens", help="Maximum tokens per chunk"),
    min_tokens: int = typer.Option(120, "--min-tokens", help="Minimum tokens per chunk"),
    progress: bool = typer.Option(True, "--progress/--no-progress", help="Show progress output"),
) -> None:
    """
    Chunk enriched or normalized documents into token-bounded pieces.

    This command processes documents and creates chunks suitable for embedding:
    • Respects chunk_hints from enrichment for heading-aligned splits
    • Uses soft boundaries and section maps for better chunk quality
    • Enforces token limits with overflow handling
    • Records per-chunk token counts for assurance

    The chunker prefers enriched input (enriched.jsonl) over normalized input
    (normalized.ndjson) when available. Enriched input enables heading-aware
    chunking with better quality.

    Example:
        trailblazer chunk RUN_ID_HERE                     # Use defaults (800/120 tokens)
        trailblazer chunk RUN_ID_HERE --max-tokens 1000  # Custom token limits
    """
    import time

    from ..core.artifacts import phase_dir
    from ..pipeline.runner import _execute_phase

    # Validate run exists
    run_dir = phase_dir(run_id, "").parent
    if not run_dir.exists():
        typer.echo(f"❌ Run {run_id} not found", err=True)
        raise typer.Exit(1) from e

    # Check for input files
    enrich_dir = phase_dir(run_id, "enrich")
    normalize_dir = phase_dir(run_id, "normalize")

    enriched_file = enrich_dir / "enriched.jsonl"
    normalized_file = normalize_dir / "normalized.ndjson"

    if enriched_file.exists():
        input_type = "enriched"
        typer.echo(f"📄 Using enriched input: {enriched_file}", err=True)
    elif normalized_file.exists():
        input_type = "normalized"
        typer.echo(f"📄 Using normalized input: {normalized_file}", err=True)
    else:
        typer.echo(
            f"❌ No input files found. Run 'trailblazer enrich {run_id}' or 'trailblazer normalize {run_id}' first",
            err=True,
        )
        raise typer.Exit(1) from e

    # Create chunk directory
    chunk_dir = phase_dir(run_id, "chunk")
    chunk_dir.mkdir(parents=True, exist_ok=True)

    typer.echo(f"🔄 Chunking documents for run: {run_id}", err=True)
    typer.echo(f"   Input type: {input_type}", err=True)
    typer.echo(f"   Max tokens: {max_tokens}", err=True)
    typer.echo(f"   Min tokens: {min_tokens}", err=True)

    if progress:
        typer.echo("", err=True)

    try:
        # Run chunking via pipeline runner
        start_time = time.time()
        _execute_phase("chunk", str(chunk_dir))
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

        typer.echo(f"✅ Chunking complete in {duration:.1f}s", err=True)
        typer.echo(f"   Documents: {doc_count}", err=True)
        typer.echo(f"   Chunks: {chunk_count}", err=True)

        if token_stats:
            typer.echo(
                f"   Token range: {token_stats.get('min', 0)}-{token_stats.get('max', 0)} "
                f"(median: {token_stats.get('median', 0)})",
                err=True,
            )

        typer.echo(f"\n📁 Artifacts written to: {chunk_dir}", err=True)
        typer.echo(
            f"   • chunks.ndjson - {chunk_count} chunks ready for embedding",
            err=True,
        )
        typer.echo(
            "   • chunk_assurance.json - Quality metrics and statistics",
            err=True,
        )

    except Exception as e:
        typer.echo(f"❌ Chunking failed: {e}", err=True)
        raise typer.Exit(1) from e


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
    all_runs = sorted([d.name for d in runs_dir.iterdir() if d.is_dir()], reverse=True)

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
    runs_size = sum(f.stat().st_size for f in runs_dir.rglob("*") if f.is_file())

    typer.echo("\n💾 Workspace usage:")
    typer.echo(f"   Runs data: {runs_size / (1024**2):.1f} MB")
    typer.echo(f"   Disk free: {free / (1024**3):.1f} GB")


@app.command("enrich-all")
def enrich_all(
    pattern: str = typer.Option("2025-08-*", "--pattern", help="Pattern to match run directories"),
    batch_size: int = typer.Option(50, "--batch-size", help="Progress report every N runs"),
    no_llm: bool = typer.Option(True, "--no-llm", help="Disable LLM enrichment (default: disabled)"),
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
        raise typer.Exit(1) from e

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
    run_id: str | None = typer.Option(None, "--run", help="Run ID to monitor (default: latest)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output for CI dashboards"),
    interval: float = typer.Option(2.0, "--interval", help="Refresh interval in seconds"),
) -> None:
    """Monitor running processes with live TUI or JSON output."""
    from ..obs.monitor import TrailblazerMonitor

    monitor = TrailblazerMonitor(run_id=run_id, json_mode=json_output, refresh_interval=interval)

    monitor.run()


@ops_app.command("monitor")
def ops_monitor_cmd(
    interval: int = typer.Option(15, "--interval", help="Monitor interval in seconds"),
    alpha: float = typer.Option(0.25, "--alpha", help="EWMA smoothing factor"),
) -> None:
    """Monitor embedding progress with real-time ETA and worker stats."""
    import json
    import os
    import subprocess
    import time
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    progress_file = Path("var/logs/reembed_progress.json")
    runs_file = Path("var/logs/temp_runs_to_embed.txt")
    log_dir = Path("var/logs")

    if not progress_file.exists():
        typer.echo(f"❌ {progress_file} not found", err=True)
        raise typer.Exit(2) from e

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
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
                docs_planned = sum(run.get("docs_planned", 0) for run in runs_data.values())
                if docs_planned == 0 and runs_file.exists():
                    # Fallback: read from runs file
                    with open(runs_file) as f:
                        docs_planned = sum(int(line.split(":")[1]) for line in f if ":" in line)

                docs_embedded = sum(run.get("docs_embedded", 0) for run in runs_data.values())

                elapsed = max(1, now - start_ts)
                docs_rate = docs_embedded / elapsed
                docs_rate_ewma = ewma(alpha, docs_rate, docs_rate_ewma)

                # Count active workers
                try:
                    result = subprocess.run(
                        ["pgrep", "-fc", "trailblazer embed load"],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    active_workers = int(result.stdout.strip()) if result.returncode == 0 else 1
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
                recent_runs.sort(key=lambda x: x[1].get("completed_at", ""), reverse=True)

                for run_id, run_data in recent_runs[:8]:
                    status = run_data.get("status", "unknown")
                    docs = run_data.get("docs_embedded", 0)
                    chunks = run_data.get("chunks_embedded", 0)
                    duration = run_data.get("duration_seconds", 0)
                    error = run_data.get("error", "")
                    typer.echo(f"{run_id}  {status}  docs={docs} chunks={chunks} dur={duration}s err={error}")

                # Show recent logs
                if log_dir.exists():
                    typer.echo("---- tail of active logs ----")
                    log_files = list(log_dir.glob("embed-*.out"))
                    log_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

                    for log_file in log_files[:2]:
                        typer.echo(f">>> {log_file}")
                        try:
                            with open(log_file) as f:
                                lines = f.readlines()
                                for line in lines[-30:]:
                                    typer.echo(line.rstrip())
                        except OSError:
                            typer.echo("Error reading log file")
                        typer.echo()

            except Exception as e:
                typer.echo(f"Error reading progress: {e}", err=True)

            time.sleep(interval)

    except KeyboardInterrupt:
        typer.echo("\n👋 Monitor stopped by user")


@ops_app.command("dispatch")
def ops_dispatch_cmd(
    workers: int = typer.Option(2, "--workers", help="Number of parallel workers"),
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
        raise typer.Exit(2) from e

    typer.echo(f"🚀 Dispatching {workers} parallel embedding workers")
    typer.echo(f"📁 Runs file: {runs_file}")

    # Read runs and dispatch
    try:
        with open(runs_path) as f:
            lines = [line.strip() for line in f if line.strip() and ":" in line]

        if not lines:
            typer.echo("❌ No valid runs found in file", err=True)
            raise typer.Exit(1) from e

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
        raise typer.Exit(1) from e


@ops_app.command("track-pages")
def ops_track_pages_cmd(
    log_file: str | None = typer.Option(None, "--log-file", help="Specific log file to track (default: latest)"),
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
        f.write(f"=== Page Titles Tracking Started at {datetime.now().isoformat()} ===\n")
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
                match = re.search(r"(📖|⏭️).*\[(\d+)\].*\((embedding|skipped)\)", line)
                if match:
                    icon, doc_num, status = match.groups()

                    # Extract title (everything between ] and ( )
                    title_match = re.search(r"\] (.*) \((embedding|skipped)\)", line)
                    title = title_match.group(1) if title_match else "Unknown"

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # Log to file
                    with open(output_log, "a") as f:
                        f.write(f"[{timestamp}] [{doc_num}] {title} ({status}) - Run: {run_id}\n")

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
            check=False,
            capture_output=True,
        )

        if result.returncode == 0:
            typer.echo("✅ Killed running Trailblazer processes")
        else:
            typer.echo("ℹ️  No running Trailblazer processes found")

    except Exception as e:
        typer.echo(f"❌ Error killing processes: {e}", err=True)
        raise typer.Exit(1) from e


@runs_app.command("reset")
def runs_reset_cmd(
    scope: str = typer.Option("processed", "--scope", help="Reset scope: processed|embeddings|all"),
    run_ids: list[str] | None = typer.Option(None, "--run-id", help="Specific run IDs to reset"),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of runs to reset"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be reset without doing it"),
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
        raise typer.Exit(1) from e

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
            typer.echo(f"🔍 Would reset {result['reset_count']} runs (scope: {scope})")
        else:
            typer.echo(f"✅ Reset {result['reset_count']} runs (scope: {scope})")

    except Exception as e:
        typer.echo(f"❌ Reset failed: {e}", err=True)
        raise typer.Exit(1) from e


@runs_app.command("status")
def runs_status_cmd() -> None:
    """Show processed runs status distribution."""
    from ..pipeline.backlog import get_db_connection

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    status,
                    COUNT(*) as count,
                    MIN(normalized_at) as earliest,
                    MAX(normalized_at) as latest
                FROM processed_runs
                GROUP BY status
                ORDER BY count DESC
            """
            )

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
        raise typer.Exit(1) from e


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
        typer.echo(f"{'Run ID':<20} {'Status':<8} {'Size (MB)':<10} {'Segments':<9} {'Last Modified'}")
        typer.echo("-" * 80)

        # Show runs (limit to first 50 for readability)
        for run_info in summary["runs"][:50]:
            size_mb = round(run_info["size_bytes"] / (1024 * 1024), 2)
            segments = f"{run_info['segments']}"
            if run_info["compressed_segments"] > 0:
                segments += f"+{run_info['compressed_segments']}gz"

            last_mod = run_info["last_modified"][:19] if run_info["last_modified"] else "unknown"

            typer.echo(f"{run_info['run_id']:<20} {run_info['status']:<8} {size_mb:<10.2f} {segments:<9} {last_mod}")

        if len(summary["runs"]) > 50:
            typer.echo(f"... and {len(summary['runs']) - 50} more runs")

    except Exception as e:
        typer.echo(f"❌ Failed to get log index: {e}", err=True)
        raise typer.Exit(1) from e


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
        compress_result = manager.compress_old_segments(dry_run=True)  # Always dry-run first

        if compress_result["compressed"]:
            typer.echo(f"   Found {len(compress_result['compressed'])} segments to compress")
            for path in compress_result["compressed"][:10]:  # Show first 10
                typer.echo(f"     {path}")
            if len(compress_result["compressed"]) > 10:
                typer.echo(f"     ... and {len(compress_result['compressed']) - 10} more")
        else:
            typer.echo("   No segments need compression")

        # Check what would be pruned
        from ..core.config import SETTINGS

        typer.echo(f"\n🗑️  Checking for logs to prune (retention: {SETTINGS.LOGS_RETENTION_DAYS} days)...")
        prune_result = manager.prune_old_logs(dry_run=True)  # Always dry-run first

        if prune_result["deleted_runs"]:
            typer.echo(f"   Found {len(prune_result['deleted_runs'])} run directories to delete")
            for run_id in prune_result["deleted_runs"][:10]:  # Show first 10
                typer.echo(f"     {run_id}")
            if len(prune_result["deleted_runs"]) > 10:
                typer.echo(f"     ... and {len(prune_result['deleted_runs']) - 10} more")
        else:
            typer.echo("   No runs to prune")

        # Show errors if any
        if compress_result["errors"] or prune_result["errors"]:
            typer.echo("\n⚠️  Errors found:")
            for error in (compress_result["errors"] + prune_result["errors"])[:5]:
                typer.echo(f"     {error}")

        # Actually execute if requested and not dry-run
        if not dry_run:
            if not yes:
                total_actions = len(compress_result["compressed"]) + len(prune_result["deleted_runs"])
                if total_actions > 0:
                    typer.echo(f"\n❓ Proceed with {total_actions} actions? This cannot be undone.")
                    if not typer.confirm("Continue?"):
                        typer.echo("Cancelled")
                        return

            # Execute compression
            if compress_result["compressed"]:
                typer.echo("\n🗜️  Compressing segments...")
                actual_compress = manager.compress_old_segments(dry_run=False)
                typer.echo(f"   Compressed {len(actual_compress['compressed'])} segments")

            # Execute pruning
            if prune_result["deleted_runs"]:
                typer.echo("\n🗑️  Pruning old logs...")
                actual_prune = manager.prune_old_logs(dry_run=False)
                typer.echo(f"   Deleted {len(actual_prune['deleted_runs'])} run directories")

        elif dry_run:
            typer.echo("\n💡 This was a dry run. Use --no-dry-run --yes to actually perform these actions.")

    except Exception as e:
        typer.echo(f"❌ Failed to prune logs: {e}", err=True)
        raise typer.Exit(1) from e


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
            raise typer.Exit(1) from e

    except Exception as e:
        typer.echo(f"❌ Log doctor failed: {e}", err=True)
        raise typer.Exit(1) from e


@embed_app.command("run")
def embed_run_cmd(
    run_id: str = typer.Argument(..., help="Run ID to embed"),
    provider: str = typer.Option(
        "openai",
        "--provider",
        help="Embedding provider (only openai supported)",
    ),
    model: str = typer.Option(
        "text-embedding-3-small",
        "--model",
        help="Model name (e.g., text-embedding-3-small)",
    ),
    dimension: int = typer.Option(
        1536,
        "--dimension",
        help="Embedding dimension (must be 1536)",
    ),
    batch_size: int = typer.Option(
        50,
        "--batch-size",
        help="Batch size for embedding generation",
    ),
) -> None:
    """Embed a single run using the working simple loader."""
    # Run database preflight check first
    _run_db_preflight_check()

    if provider != "openai":
        typer.echo("❌ Only OpenAI provider is supported", err=True)
        raise typer.Exit(1) from e

    if dimension != 1536:
        typer.echo("❌ Only 1536 dimensions supported", err=True)
        raise typer.Exit(1) from e

    try:
        from ..pipeline.steps.embed.simple_loader import simple_embed_run

        typer.echo(f"🔄 Embedding run {run_id} with {provider}/{model} (dim={dimension})")

        assurance = simple_embed_run(
            run_id=run_id,
            provider=provider,
            model=model,
            dimension=dimension,
            batch_size=batch_size,
        )

        typer.echo(f"✅ Embedded {assurance['chunks_embedded']} chunks from {assurance['docs_embedded']} documents")
        typer.echo(f"⏱️  Duration: {assurance['duration_seconds']:.2f} seconds")

        if assurance["errors"]:
            typer.echo(f"⚠️  {len(assurance['errors'])} errors occurred", err=True)

    except Exception as e:
        typer.echo(f"❌ Embed failed: {e}", err=True)
        raise typer.Exit(1) from e


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
        help="Embedding dimension (singular, always 1536 per requirements)",
    ),
    batch_size: int = typer.Option(
        50,
        "--batch",
        help="Batch size for embedding generation (max chunks per batch)",
    ),
    large_run_threshold: int = typer.Option(
        2000,
        "--large-run-threshold",
        help="Runs with more chunks than this get batched",
    ),
    resume_from: str | None = typer.Option(
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
    max_runs: int | None = typer.Option(
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
    if provider != "openai":
        typer.echo("❌ Only OpenAI provider is supported", err=True)
        raise typer.Exit(1) from e

    if dimension != 1536:
        typer.echo("❌ Only 1536 dimensions supported", err=True)
        raise typer.Exit(1) from e

    from datetime import datetime, timezone

    from ..core.paths import runs
    from ..pipeline.steps.embed.simple_loader import simple_embed_run

    # Simple working corpus embedding using our proven approach
    typer.echo(f"🚀 Starting corpus embedding with {provider}/{model} (dim={dimension})")

    # Get all runs with chunks
    runs_dir = runs()
    runs_with_chunks = []

    for run_dir in runs_dir.iterdir():
        if run_dir.is_dir() and (run_dir / "chunk" / "chunks.ndjson").exists():
            runs_with_chunks.append(run_dir.name)

    runs_with_chunks.sort()

    if resume_from:
        try:
            start_index = runs_with_chunks.index(resume_from)
            runs_with_chunks = runs_with_chunks[start_index:]
            typer.echo(f"📍 Resuming from: {resume_from}")
        except ValueError:
            typer.echo(f"❌ Resume run '{resume_from}' not found", err=True)
            raise typer.Exit(1) from e

    if max_runs:
        runs_with_chunks = runs_with_chunks[:max_runs]

    total_runs = len(runs_with_chunks)
    typer.echo(f"📊 Found {total_runs} runs with chunks to embed")

    if total_runs == 0:
        typer.echo("❌ No runs with chunks found", err=True)
        raise typer.Exit(1) from e

    # Process each run using our simple working approach
    success_count = 0
    failure_count = 0
    total_docs_embedded = 0
    total_chunks_embedded = 0
    start_time = datetime.now(timezone.utc)

    for i, run_id in enumerate(runs_with_chunks, 1):
        typer.echo(f"🔄 [{i}/{total_runs}] {run_id}")

        try:
            assurance = simple_embed_run(
                run_id=run_id,
                provider=provider,
                model=model,
                dimension=dimension,
                batch_size=batch_size,
            )

            success_count += 1
            total_docs_embedded += assurance["docs_embedded"]
            total_chunks_embedded += assurance["chunks_embedded"]

            typer.echo(
                f"  ✅ {assurance['chunks_embedded']} chunks, {assurance['docs_embedded']} docs ({assurance['duration_seconds']:.1f}s)"
            )

        except Exception as e:
            failure_count += 1
            typer.echo(f"  ❌ Failed: {e}")
            continue

    # Final summary
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    typer.echo("\n🎉 Corpus embedding complete!")
    typer.echo(f"✅ {success_count} successful runs")
    typer.echo(f"❌ {failure_count} failed runs")
    typer.echo(f"📊 {total_chunks_embedded} total chunks embedded")
    typer.echo(f"📄 {total_docs_embedded} total documents")
    typer.echo(f"⏱️  Total duration: {duration:.1f} seconds")

    if failure_count > 0:
        typer.echo(f"⚠️  {failure_count} runs failed", err=True)
        raise typer.Exit(1) from e


@embed_app.command("reembed-if-changed")
def embed_reembed_if_changed_cmd(
    run_id: str = typer.Argument(..., help="Run ID to reembed if changed"),
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
    batch_size: int = typer.Option(128, "--batch", help="Batch size for embedding generation"),
) -> None:
    """Re-embed a run only if content has changed since last embedding."""
    # Run database preflight check first
    _run_db_preflight_check()

    from ..pipeline.steps.embed.loader import load_chunks_to_db

    try:
        metrics = load_chunks_to_db(
            run_id=run_id,
            provider_name=provider,
            model=model,
            dimension=dimension,
            batch_size=batch_size,
            changed_only=True,  # Only embed changed documents
        )

        # Check if anything was actually embedded
        if metrics["chunks_embedded"] == 0:
            typer.echo("No changes detected, skipping embedding", err=True)
            return

        # Display summary
        typer.echo(f"✅ Re-embedded {metrics['chunks_embedded']} chunks", err=True)
        typer.echo(
            f"Provider: {metrics['provider']} (dim={metrics['dimension']})",
            err=True,
        )

    except Exception as e:
        typer.echo(f"❌ Re-embedding failed: {e}", err=True)
        raise typer.Exit(1) from e


# OLD PREFLIGHT COMMAND REMOVED - USE plan-preflight INSTEAD


@embed_app.command("dispatch")
def embed_dispatch_cmd(
    plan_preflight_dir: str = typer.Option(
        ...,
        "--plan-preflight-dir",
        help="Plan preflight directory with ready.txt",
    ),
    skip_unchanged: bool = typer.Option(
        False,
        "--skip-unchanged",
        help="Use reembed-if-changed to skip unchanged runs",
    ),
    notes: str = typer.Option(
        "",
        "--notes",
        help="Operator notes for dispatch manifest",
    ),
    workers: int = typer.Option(
        8,
        "--workers",
        help="Number of parallel workers",
    ),
) -> None:
    """Dispatch embedding for all runs in a validated plan-preflight bundle."""
    import concurrent.futures
    import json
    import os
    from datetime import datetime, timezone
    from pathlib import Path

    from ..pipeline.steps.embed.loader import load_chunks_to_db

    # Load .env file if it exists
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.strip() and not line.startswith("#") and "=" in line:
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value
        typer.echo("📊 Environment loaded from .env", err=True)

    # Validate plan directory
    plan_dir = Path(plan_preflight_dir)
    if not plan_dir.exists():
        typer.echo(f"❌ Plan directory not found: {plan_preflight_dir}", err=True)
        raise typer.Exit(1) from e

    ready_file = plan_dir / "ready.txt"
    if not ready_file.exists():
        typer.echo(f"❌ ready.txt not found in {plan_preflight_dir}", err=True)
        raise typer.Exit(1) from e

    # Read runs from ready.txt (these are already validated by plan-preflight)
    runs = []
    with open(ready_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # Handle both formats: "var/runs/run_id" and just "run_id"
                if line.startswith("var/runs/"):
                    run_id = line[9:]  # Remove "var/runs/"
                else:
                    run_id = line
                runs.append(run_id)

    typer.echo(f"🚀 Dispatching {len(runs)} validated runs", err=True)
    typer.echo(f"📁 Plan: {plan_preflight_dir}", err=True)
    typer.echo(f"👥 Workers: {workers}", err=True)

    # Create dispatch log directory
    dispatch_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dispatch_log_dir = Path("var/logs/dispatch") / dispatch_ts
    dispatch_log_dir.mkdir(parents=True, exist_ok=True)

    # Archive plan-preflight bundle
    import shutil

    shutil.copytree(plan_dir, dispatch_log_dir / "plan_preflight")
    typer.echo(f"📦 Archived plan to: {dispatch_log_dir}/plan_preflight", err=True)

    # Create dispatch manifest
    manifest = {
        "dispatchTs": datetime.now(timezone.utc).isoformat(),
        "planPreflightDir": str(plan_preflight_dir),
        "runsPlanned": len(runs),
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "workers": workers,
        "batchSize": 128,
        "notes": notes,
        "mode": "reembed-if-changed" if skip_unchanged else "embed",
    }

    manifest_file = dispatch_log_dir / "dispatch_manifest.json"
    with open(manifest_file, "w") as f:
        json.dump(manifest, f, indent=2)

    typer.echo(f"📄 Created manifest: {manifest_file}", err=True)

    # Process runs with workers
    def process_run(run_id: str) -> dict:
        """Process a single run."""
        try:
            metrics = load_chunks_to_db(
                run_id=run_id,
                provider_name="openai",
                model="text-embedding-3-small",
                dimension=1536,
                batch_size=128,
                changed_only=skip_unchanged,
            )
            return {"run_id": run_id, "status": "success", "metrics": metrics}
        except Exception as e:
            return {"run_id": run_id, "status": "error", "error": str(e)}

    # Run embedding with thread pool
    completed = 0
    failed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_run = {executor.submit(process_run, run_id): run_id for run_id in runs}

        for future in concurrent.futures.as_completed(future_to_run):
            run_id = future_to_run[future]
            try:
                result = future.result()
                if result["status"] == "success":
                    completed += 1
                    metrics = result["metrics"]
                    typer.echo(
                        f"✅ {run_id}: {metrics['chunks_embedded']} chunks embedded",
                        err=True,
                    )
                else:
                    failed += 1
                    typer.echo(f"❌ {run_id}: {result['error']}", err=True)
            except Exception as e:
                failed += 1
                typer.echo(f"❌ {run_id}: {e}", err=True)

            # Progress update
            total_processed = completed + failed
            if total_processed % 10 == 0 or total_processed == len(runs):
                typer.echo(
                    f"📊 Progress: {total_processed}/{len(runs)} ({completed} ✅, {failed} ❌)",
                    err=True,
                )

    typer.echo(
        f"\n🎉 Dispatch complete: {completed} successful, {failed} failed",
        err=True,
    )


@embed_app.command("plan-preflight")
def embed_plan_preflight_cmd(
    plan_file: str = typer.Option(
        "var/temp_runs_to_embed.txt",
        "--plan-file",
        help="Plan file with runs to validate (format: 'run_id:chunk_count' or 'var/runs/run_id' per line)",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Embedding provider (openai, sentencetransformers)",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model name (e.g., text-embedding-3-small)",
    ),
    dimension: int | None = typer.Option(
        None,
        "--dimension",
        help="Embedding dimension (always 1536 per requirements)",
    ),
    out_dir: str = typer.Option(
        "var/plan_preflight/",
        "--out-dir",
        help="Output directory (tool creates timestamped subdirectory)",
    ),
    min_embed_docs: int = typer.Option(
        1,
        "--min-embed-docs",
        help="Minimum embeddable docs required",
    ),
    quality_advisory: bool = typer.Option(
        True,
        "--quality-advisory/--no-quality-advisory",
        help="Quality is advisory only (always True per requirements)",
    ),
) -> None:
    """
    Run preflight checks for all runs in a plan file.

    Uses advisory quality gates - only blocks runs for structural issues
    or when embeddable_docs < min_embed_docs. Quality is purely advisory.

    Writes doc_skiplist.json for each run with quality-based skips.
    """
    from ..core.config import SETTINGS
    from ..pipeline.steps.embed.preflight import run_plan_preflight

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

    try:
        # Call the library function (proper architecture)
        result = run_plan_preflight(
            plan_file=plan_file,
            provider=resolved_provider,
            model=resolved_model,
            dimension=resolved_dimension,
            min_embed_docs=min_embed_docs,
            quality_advisory=quality_advisory,
            out_dir=out_dir,
        )

        # Report results
        typer.echo("\n📊 Plan Preflight Complete", err=True)
        typer.echo(f"✅ Ready: {result['ready_runs']} runs", err=True)
        typer.echo(f"❌ Blocked: {result['blocked_runs']} runs", err=True)
        typer.echo(
            f"📄 Total embeddable docs: {result['total_embeddable_docs']:,}",
            err=True,
        )
        typer.echo(
            f"📄 Total skipped docs: {result['total_skipped_docs']:,}",
            err=True,
        )

        # Find the output directory from the result
        output_dirs = list(Path(out_dir).glob("*"))
        if output_dirs:
            latest_dir = max(output_dirs, key=lambda p: p.stat().st_mtime)
            typer.echo(f"📁 Reports written to: {latest_dir}", err=True)

        typer.echo("✅ Plan preflight completed successfully", err=True)

    except Exception as e:
        typer.echo(f"❌ Plan preflight failed: {e}", err=True)
        raise typer.Exit(1) from e


@embed_app.command("plan-diagnose")
def embed_plan_diagnose_cmd(
    plan_dir: str | None = typer.Option(
        None,
        "--plan-dir",
        help="Plan bundle directory to diagnose (defaults to latest)",
    ),
    out_dir: str = typer.Option(
        "var/plan_diagnose",
        "--out-dir",
        help="Output directory for diagnostic pack",
    ),
) -> None:
    """
    Diagnose why runs are blocked in a plan-preflight bundle.

    Analyzes each blocked run to determine the exact structural reason
    and generates fix lists and repair guidance.
    """
    import glob
    from pathlib import Path

    from ..pipeline.steps.embed.diagnose import (
        diagnose_blocked_runs,
        write_diagnostic_pack,
    )

    # Find plan directory
    if plan_dir:
        if not Path(plan_dir).exists():
            typer.echo(f"❌ Plan directory not found: {plan_dir}", err=True)
            raise typer.Exit(1) from e
        target_plan_dir = plan_dir
    else:
        # Auto-find latest plan bundle
        plan_dirs = glob.glob("var/plan_preflight*/*/")
        if not plan_dirs:
            typer.echo("❌ No plan preflight directories found", err=True)
            raise typer.Exit(1) from e
        target_plan_dir = sorted(plan_dirs)[-1].rstrip("/")

    typer.echo(f"🔍 Diagnosing plan bundle: {target_plan_dir}", err=True)

    try:
        # Run diagnosis
        result = diagnose_blocked_runs(target_plan_dir)

        # Write diagnostic pack
        diagnostic_dir = write_diagnostic_pack(result, out_dir)

        # Report results
        typer.echo("\n📊 Diagnosis Complete", err=True)
        typer.echo(f"Total blocked runs: {result['total_blocked']}", err=True)
        typer.echo("Reason breakdown:", err=True)

        for reason, count in sorted(result["reason_counts"].items(), key=lambda x: x[1], reverse=True):
            typer.echo(f"  {reason}: {count} runs", err=True)

        typer.echo(f"\n📁 Diagnostic pack: {diagnostic_dir}", err=True)
        typer.echo(
            f"📄 See {diagnostic_dir}/reasons.md for detailed analysis",
            err=True,
        )

    except Exception as e:
        typer.echo(f"❌ Diagnosis failed: {e}", err=True)
        raise typer.Exit(1) from e


@embed_app.command("status")
def embed_status_cmd() -> None:
    """Show current embedding status and database counts."""
    # Run database preflight check first
    _run_db_preflight_check()

    import time

    from sqlalchemy import text

    from ..core.paths import logs
    from ..db.engine import get_engine

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

            result = conn.execute(text("SELECT COUNT(*) FROM chunk_embeddings"))
            embedding_count = result.fetchone()[0]

            # Get provider and dimension info
            result = conn.execute(
                text(
                    """
                SELECT provider, dim, COUNT(*) as count
                FROM chunk_embeddings
                GROUP BY provider, dim
                ORDER BY count DESC
            """
                )
            )
            provider_info = result.fetchall()

            # Get latest embedding timestamp
            result = conn.execute(
                text(
                    """
                SELECT MAX(created_at) as latest_embedding
                FROM chunk_embeddings
            """
                )
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
                if latest_log.stat().st_mtime > (time.time() - 3600):  # Last hour
                    typer.echo("📝 Recent log entries:")
                    try:
                        with open(latest_log) as f:
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
        raise typer.Exit(1) from e


@embed_app.command("clean-preflight")
def embed_clean_preflight_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be cleaned without doing it"),
) -> None:
    """Purge bad preflight artifacts (safely archive, never delete)."""
    import glob
    import json
    import shutil
    from datetime import datetime, timezone
    from pathlib import Path

    typer.echo("🧹 Cleaning bad preflight artifacts", err=True)

    # Scan for plan_preflight directories
    plan_preflight_dirs = glob.glob("var/plan_preflight*/")
    if not plan_preflight_dirs:
        typer.echo("ℹ️  No plan_preflight directories found", err=True)
        return

    bad_bundles = []
    good_bundles = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_base = Path(f"var/archive/bad_plan_preflight/{timestamp}")

    for plan_dir_str in plan_preflight_dirs:
        plan_dir = Path(plan_dir_str)

        is_bad = False
        reasons = []

        # Check for missing or invalid plan_preflight.json
        plan_json_path = plan_dir / "plan_preflight.json"
        if not plan_json_path.exists():
            is_bad = True
            reasons.append("missing_plan_preflight_json")
        else:
            try:
                with open(plan_json_path) as f:
                    plan_data = json.load(f)

                # Check for QUALITY_GATE in any run reason
                runs_detail = plan_data.get("runs_detail", [])
                for run_data in runs_detail:
                    reason = run_data.get("reason", "")
                    if "QUALITY_GATE" in reason:
                        is_bad = True
                        reasons.append("contains_quality_gate")
                        break

            except (json.JSONDecodeError, KeyError) as e:
                is_bad = True
                reasons.append(f"invalid_plan_json: {e}")

        # Check ready.txt/blocked.txt count consistency
        ready_file = plan_dir / "ready.txt"
        blocked_file = plan_dir / "blocked.txt"

        if ready_file.exists() and blocked_file.exists() and plan_json_path.exists():
            try:
                with open(ready_file) as f:
                    ready_count = sum(1 for line in f if line.strip() and not line.strip().startswith("#"))
                with open(blocked_file) as f:
                    blocked_count = sum(1 for line in f if line.strip() and not line.strip().startswith("#"))

                if plan_json_path.exists():
                    with open(plan_json_path) as f:
                        plan_data = json.load(f)

                    json_ready = plan_data.get("ready_runs", 0)
                    json_blocked = plan_data.get("blocked_runs", 0)

                    # Allow 1% tolerance for count disagreement
                    total_json = json_ready + json_blocked
                    total_files = ready_count + blocked_count

                    if total_json > 0 and abs(total_files - total_json) / total_json > 0.01:
                        is_bad = True
                        reasons.append(f"count_mismatch: json={total_json} files={total_files}")

            except Exception as e:
                is_bad = True
                reasons.append(f"count_check_error: {e}")

        if is_bad:
            bad_bundles.append((plan_dir, reasons))
        else:
            good_bundles.append(plan_dir)

    # Also check for stray plan .txt files at root level
    stray_files = []
    for pattern in ["var/plan_*.txt", "var/ready_*.txt", "var/blocked_*.txt"]:
        stray_files.extend(glob.glob(pattern))

    # Report findings
    typer.echo("\n📊 Scan Results:", err=True)
    typer.echo(f"   Good bundles: {len(good_bundles)}", err=True)
    typer.echo(f"   Bad bundles: {len(bad_bundles)}", err=True)
    typer.echo(f"   Stray files: {len(stray_files)}", err=True)

    if bad_bundles:
        typer.echo("\n🚨 Bad bundles found:", err=True)
        for plan_dir, reasons in bad_bundles:
            typer.echo(f"   - {plan_dir.name}: {', '.join(reasons)}", err=True)

    if stray_files:
        typer.echo("\n📄 Stray plan files found:", err=True)
        for stray_file in stray_files:
            typer.echo(f"   - {stray_file}", err=True)

    if not bad_bundles and not stray_files:
        typer.echo("✅ No bad preflight artifacts found", err=True)
        return

    if dry_run:
        typer.echo(f"\n🔍 DRY RUN: Would archive to {archive_base}/", err=True)
        return

    # Archive bad bundles and stray files
    if bad_bundles or stray_files:
        archive_base.mkdir(parents=True, exist_ok=True)

        # Archive bad bundles
        for plan_dir, reasons in bad_bundles:
            archive_dest = archive_base / plan_dir.name
            typer.echo(f"📦 Archiving {plan_dir.name} -> {archive_dest}", err=True)
            shutil.copytree(plan_dir, archive_dest)
            shutil.rmtree(plan_dir)

        # Archive stray files
        if stray_files:
            stray_dir = archive_base / "stray_files"
            stray_dir.mkdir(exist_ok=True)
            for stray_file in stray_files:
                stray_path = Path(stray_file)
                dest_path = stray_dir / stray_path.name
                typer.echo(f"📦 Archiving {stray_file} -> {dest_path}", err=True)
                shutil.move(stray_file, dest_path)

        # Write cleanup report
        report = {
            "timestamp": timestamp,
            "bad_bundles_archived": len(bad_bundles),
            "stray_files_archived": len(stray_files),
            "archive_location": str(archive_base),
            "bad_bundles": [{"bundle": str(plan_dir), "reasons": reasons} for plan_dir, reasons in bad_bundles],
            "stray_files": stray_files,
        }

        report_file = archive_base / "cleanup_report.json"
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)

        typer.echo("\n✅ Cleanup complete", err=True)
        typer.echo(f"   Archived {len(bad_bundles)} bad bundles", err=True)
        typer.echo(f"   Archived {len(stray_files)} stray files", err=True)
        typer.echo(f"   Archive location: {archive_base}", err=True)
        typer.echo(f"   Report: {report_file}", err=True)


@admin_app.command("script-audit")
def admin_script_audit_cmd(
    fix: bool = typer.Option(False, "--fix", help="Apply fixes (remove/upgrade scripts)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without doing it"),
) -> None:
    """Audit and remove/upgrade legacy scripts to Python-only."""
    import glob
    import json
    import re
    import shutil
    from datetime import datetime, timezone
    from pathlib import Path
    from typing import Any, cast

    typer.echo("🔍 Auditing scripts for legacy patterns", err=True)

    # Define forbidden patterns
    forbidden_patterns = {
        "dimensions_plural": {
            "regex": r"--dimensions\b",
            "description": "Uses --dimensions (plural) instead of --dimension",
            "action": "upgrade",
        },
        "embed_chunk_mixing": {
            "regex": r"(chunk.*embed|embed.*chunk)",
            "description": "Mixing embed and chunk operations in same script",
            "action": "remove",
        },
        "plan_preflight_final": {
            "regex": r"plan_preflight_final",
            "description": "References deprecated plan_preflight_final directory",
            "action": "upgrade",
        },
        "deprecated_cli_paths": {
            "regex": r"trailblazer\.pipeline\.(chunk|embed)",
            "description": "Direct imports of deprecated pipeline modules",
            "action": "remove",
        },
        "adhoc_plan_txt": {
            "regex": r"(var/plan_[^/]+\.txt|var/ready_[^/]+\.txt|var/blocked_[^/]+\.txt)",
            "description": "Writing/reading ad-hoc plan .txt outside canonical locations",
            "action": "upgrade",
        },
        "bespoke_monitors": {
            "regex": r"(monitor_embedding|monitor_batch|monitor_retry)\.sh",
            "description": "Non-canonical monitoring scripts",
            "action": "upgrade",
        },
        "subprocess_usage": {
            "regex": r"(subprocess\.|os\.system|pexpect|pty\.|shlex\.)",
            "description": "Uses subprocess/system calls instead of Python CLI",
            "action": "remove",
        },
    }

    # Scan scripts directory
    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [f for f in script_files if Path(f).is_file() and f.endswith((".sh", ".py", ".bash"))]

    if not script_files:
        typer.echo("ℹ️  No script files found in scripts/", err=True)
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    audit_dir = Path(f"var/script_audit/{timestamp}")

    audit_results = []
    remove_scripts: list[Path] = []
    upgrade_scripts: list[Path] = []
    keep_scripts: list[Path] = []

    typer.echo(f"📁 Scanning {len(script_files)} script files...", err=True)

    for script_path in script_files:
        script_file = Path(script_path)
        patterns_found = []
        action = "keep"

        try:
            with open(script_file, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Check each forbidden pattern
            for pattern_name, pattern_info in forbidden_patterns.items():
                if re.search(pattern_info["regex"], content, re.IGNORECASE):
                    patterns_found.append(
                        {
                            "name": pattern_name,
                            "description": pattern_info["description"],
                            "suggested_action": pattern_info["action"],
                        }
                    )

                    # Determine overall action (remove takes precedence over upgrade)
                    if pattern_info["action"] == "remove":
                        action = "remove"
                    elif pattern_info["action"] == "upgrade" and action != "remove":
                        action = "upgrade"

            # Special case: monitor_embedding.sh should be kept as canonical
            if script_file.name == "monitor_embedding.sh" and script_file.parent.name == "scripts":
                action = "keep"
                patterns_found = [p for p in patterns_found if p["name"] != "bespoke_monitors"]

            audit_result = {
                "path": str(script_file),
                "patterns": patterns_found,
                "action": action,
                "size_bytes": (script_file.stat().st_size if script_file.exists() else 0),
            }

            audit_results.append(audit_result)

            if action == "remove":
                remove_scripts.append(script_file)
            elif action == "upgrade":
                upgrade_scripts.append(script_file)
            else:
                keep_scripts.append(script_file)

        except Exception as e:
            typer.echo(f"⚠️  Error reading {script_file}: {e}", err=True)
            audit_results.append(
                {
                    "path": str(script_file),
                    "patterns": [
                        {
                            "name": "read_error",
                            "description": f"Failed to read: {e}",
                        }
                    ],
                    "action": "error",
                }
            )

    # Report findings
    typer.echo("\n📊 Audit Results:", err=True)
    typer.echo(f"   Keep: {len(keep_scripts)}", err=True)
    typer.echo(f"   Upgrade: {len(upgrade_scripts)}", err=True)
    typer.echo(f"   Remove: {len(remove_scripts)}", err=True)

    if remove_scripts:
        typer.echo("\n🚨 Scripts to remove:", err=True)
        for script in cast(list[Path], remove_scripts[:10]):  # Show first 10
            script_result = next(p for p in audit_results if Path(cast(str, p["path"])) == script)
            patterns = cast(list[dict[str, Any]], script_result["patterns"])
            typer.echo(
                f"   - {script.name}: {len(patterns)} issues",
                err=True,
            )

    if upgrade_scripts:
        typer.echo("\n🔧 Scripts to upgrade:", err=True)
        for script in cast(list[Path], upgrade_scripts[:10]):  # Show first 10
            typer.echo(f"   - {script.name}", err=True)

    if dry_run:
        typer.echo(
            f"\n🔍 DRY RUN: Would create audit report in {audit_dir}/",
            err=True,
        )
        return

    # Create audit directory and report
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON report
    report_data = {
        "timestamp": timestamp,
        "total_scripts": len(script_files),
        "keep_count": len(keep_scripts),
        "upgrade_count": len(upgrade_scripts),
        "remove_count": len(remove_scripts),
        "forbidden_patterns": forbidden_patterns,
        "results": audit_results,
    }

    report_json = audit_dir / "report.json"
    with open(report_json, "w") as f:
        json.dump(report_data, f, indent=2)

    # Write human-readable report
    report_md = audit_dir / "report.md"
    with open(report_md, "w") as f:
        f.write("# Script Audit Report\n\n")
        f.write(f"**Timestamp:** {timestamp}\n")
        f.write(f"**Total Scripts:** {len(script_files)}\n\n")
        f.write("## Summary\n\n")
        f.write(f"- **Keep:** {len(keep_scripts)} scripts\n")
        f.write(f"- **Upgrade:** {len(upgrade_scripts)} scripts\n")
        f.write(f"- **Remove:** {len(remove_scripts)} scripts\n\n")

        if remove_scripts:
            f.write(f"## Scripts to Remove ({len(remove_scripts)})\n\n")
            for script in cast(list[Path], remove_scripts):
                result = next(r for r in audit_results if Path(cast(str, r["path"])) == script)
                f.write(f"### {script.name}\n")
                f.write(f"**Path:** `{script}`\n")
                f.write("**Issues:**\n")
                patterns = cast(list[dict[str, Any]], result["patterns"])
                for pattern in patterns:
                    f.write(f"- {pattern['description']}\n")
                f.write("\n")

        if upgrade_scripts:
            f.write(f"## Scripts to Upgrade ({len(upgrade_scripts)})\n\n")
            for script in cast(list[Path], upgrade_scripts):
                result = next(r for r in audit_results if Path(cast(str, r["path"])) == script)
                f.write(f"### {script.name}\n")
                f.write(f"**Path:** `{script}`\n")
                f.write("**Issues:**\n")
                patterns = cast(list[dict[str, Any]], result["patterns"])
                for pattern in patterns:
                    f.write(f"- {pattern['description']}\n")
                f.write("\n")

    if not fix:
        typer.echo(f"\n📄 Audit complete. Report: {report_md}", err=True)
        typer.echo("   Use --fix to apply changes", err=True)
        return

    # Apply fixes
    legacy_dir = Path("scripts/_legacy") / timestamp
    changes_made = 0

    if remove_scripts:
        legacy_dir.mkdir(parents=True, exist_ok=True)

        for script in remove_scripts:
            # Move to legacy directory
            legacy_dest = legacy_dir / script.name
            typer.echo(f"📦 Moving {script.name} -> {legacy_dest}", err=True)
            shutil.move(script, legacy_dest)

            # Create stub that exits with error
            stub_content = f"""#!/bin/bash
# LEGACY SCRIPT REMOVED - Use Python CLI instead
echo "❌ This script has been removed. Use 'trailblazer --help' for current commands."
echo "   Archived to: scripts/_legacy/{timestamp}/{script.name}"
exit 1
"""
            with open(script, "w") as f:
                f.write(stub_content)
            script.chmod(0o755)
            changes_made += 1

    if upgrade_scripts:
        for script in upgrade_scripts:
            # For now, just mark them for manual upgrade
            # In a real implementation, we'd rewrite them as thin CLI wrappers
            typer.echo(
                f"🔧 Marking {script.name} for upgrade (manual intervention needed)",
                err=True,
            )

            # Add a comment at the top indicating it needs upgrade
            try:
                with open(script) as f:
                    content = f.read()

                upgrade_comment = f"""# WARNING: This script contains legacy patterns and should be upgraded
# See: {report_md}
# Use only Python CLI commands: trailblazer --help

"""
                if not content.startswith("# WARNING:"):
                    with open(script, "w") as f:
                        f.write(upgrade_comment + content)
                    changes_made += 1
            except Exception as e:
                typer.echo(f"⚠️  Failed to mark {script} for upgrade: {e}", err=True)

    # Update report with changes made
    report_data["changes_applied"] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "removed_count": len(remove_scripts),
        "upgraded_count": len(upgrade_scripts),
        "total_changes": changes_made,
    }

    with open(report_json, "w") as f:
        json.dump(report_data, f, indent=2)

    typer.echo("\n✅ Script audit complete", err=True)
    typer.echo(f"   Changes made: {changes_made}", err=True)
    typer.echo(f"   Report: {report_md}", err=True)
    if remove_scripts:
        typer.echo(f"   Legacy scripts: {legacy_dir}", err=True)


if __name__ == "__main__":
    # Enforce macOS venv check before any commands
    from ..env_checks import assert_virtualenv_on_macos

    assert_virtualenv_on_macos()

    app()
