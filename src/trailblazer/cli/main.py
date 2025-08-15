import typer
from typing import List, Optional
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path
import subprocess
import sys
from ..core.logging import setup_logging, log
from ..core.config import SETTINGS
from ..pipeline.runner import run as run_pipeline

app = typer.Typer(add_completion=False, help="Trailblazer CLI")
ingest_app = typer.Typer(help="Ingestion commands")
normalize_app = typer.Typer(help="Normalization commands")
db_app = typer.Typer(help="Database commands")
embed_app = typer.Typer(help="Embedding commands")
confluence_app = typer.Typer(help="Confluence commands")
ops_app = typer.Typer(help="Operations commands")
paths_app = typer.Typer(help="Workspace path commands")
app.add_typer(ingest_app, name="ingest")
app.add_typer(normalize_app, name="normalize")
app.add_typer(db_app, name="db")
app.add_typer(embed_app, name="embed")
app.add_typer(confluence_app, name="confluence")
app.add_typer(ops_app, name="ops")
app.add_typer(paths_app, name="paths")


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


@app.callback()
def _init() -> None:
    setup_logging()


@app.command()
def version() -> None:
    from .. import __version__

    typer.echo(__version__)


@app.command()
def run(
    phases: Optional[List[str]] = typer.Option(
        None, "--phases", help="Subset of phases to run, in order"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Do not execute; just scaffold outputs"
    ),
) -> None:
    rid = run_pipeline(phases=phases, dry_run=dry_run)
    log.info("cli.run.done", run_id=rid)


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
        help="Run ID to load (uses runs/<RUN_ID>/normalize/normalized.ndjson)",
    ),
    input_file: Optional[str] = typer.Option(
        None,
        "--input",
        help="Input NDJSON file to load (overrides --run-id)",
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
    dimensions: Optional[int] = typer.Option(
        None,
        "--dimensions",
        help="Embedding dimensions (e.g., 512, 1024, 1536)",
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
    """Load normalized documents to database with embeddings."""
    # Run database preflight check first
    _run_db_preflight_check()

    # Check dimension compatibility unless we're doing a full re-embed
    if not reembed_all:
        _check_dimension_compatibility(provider, dimensions)

    from ..db.engine import get_db_url
    from ..pipeline.steps.embed.loader import load_normalized_to_db

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
        metrics = load_normalized_to_db(
            run_id=run_id,
            input_file=input_file,
            provider_name=provider,
            model=model,
            dimensions=dimensions,
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
    • LLM-optional fields (summaries, keywords, taxonomy labels, suggested edges)
    • Enrichment fingerprints for selective re-embedding

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
    def progress_callback(
        docs_processed: int, rate: float, elapsed: float, docs_llm: int
    ):
        if progress:
            typer.echo(
                f"[ENRICH] docs={docs_processed} rate={rate:.1f}/s elapsed={elapsed:.1f}s llm_used={docs_llm}",
                err=True,
            )

    # Show banner
    if progress:
        progress_renderer.start_banner(
            run_id=run_id, spaces=1
        )  # Single "phase" for enrichment
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
            typer.echo(
                f"📊 Documents processed: {stats['docs_total']:,}", err=True
            )
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


if __name__ == "__main__":
    app()
