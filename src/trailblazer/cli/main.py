import typer
from typing import List, Optional
from datetime import datetime
from urllib.parse import urlparse
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
app.add_typer(ingest_app, name="ingest")
app.add_typer(normalize_app, name="normalize")
app.add_typer(db_app, name="db")
app.add_typer(embed_app, name="embed")
app.add_typer(confluence_app, name="confluence")
app.add_typer(ops_app, name="ops")


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
                    "Use 'make db.up' then 'trailblazer db doctor' to get started",
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
        enabled=progress, quiet_pretty=quiet_pretty
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

        # Show start banner
        num_spaces = len(space or []) + len(space_id or [])
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

        log.info("cli.ingest.confluence.done", run_id=rid, **metrics)

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
        enabled=progress, quiet_pretty=quiet_pretty
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
    log.info("cli.normalize.from_ingest.done", run_id=rid, **metrics)
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
            # Non-PostgreSQL database
            if health_info["dialect"] == "sqlite":
                # Only allow SQLite in test mode
                import os

                if os.getenv("TB_TESTING") != "1":
                    typer.echo("\n❌ SQLite detected in production mode!")
                    typer.echo(
                        "   SQLite is only allowed for tests (TB_TESTING=1)"
                    )
                    typer.echo("   For production, use PostgreSQL:")
                    typer.echo(
                        "   Run 'make db.up' then 'trailblazer db doctor'"
                    )
                    raise typer.Exit(1)
                else:
                    typer.echo("\n⚠️  SQLite mode (testing only)")
            else:
                typer.echo(
                    f"\n⚠️  Non-PostgreSQL database: {health_info['dialect']}"
                )
                typer.echo(
                    "   For optimal performance, PostgreSQL + pgvector is recommended"
                )

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

    except Exception as e:
        typer.echo(f"❌ Error initializing database: {e}", err=True)
        raise typer.Exit(1)


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
    batch_size: int = typer.Option(
        128, "--batch", help="Batch size for embedding generation"
    ),
    max_docs: Optional[int] = typer.Option(
        None, "--max-docs", help="Maximum number of documents to process"
    ),
    max_chunks: Optional[int] = typer.Option(
        None, "--max-chunks", help="Maximum number of chunks to process"
    ),
) -> None:
    """Load normalized documents to database with embeddings."""
    # Run database preflight check first
    _run_db_preflight_check()

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
            batch_size=batch_size,
            max_docs=max_docs,
            max_chunks=max_chunks,
        )

        # Display summary
        typer.echo("\n📊 Summary:")
        typer.echo(
            f"  Documents: {metrics['docs_processed']} processed, {metrics['docs_upserted']} upserted"
        )
        typer.echo(
            f"  Chunks: {metrics['chunks_processed']} processed, {metrics['chunks_upserted']} upserted"
        )
        typer.echo(
            f"  Embeddings: {metrics['embeddings_processed']} processed, {metrics['embeddings_upserted']} upserted"
        )
        typer.echo(
            f"  Provider: {metrics['provider']} (dim={metrics['dimension']})"
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
    import time
    from pathlib import Path

    from ..core.artifacts import new_run_id, phase_dir
    from ..retrieval.dense import create_retriever
    from ..retrieval.pack import (
        group_by_doc,
        pack_context,
        create_context_summary,
    )

    # Setup
    run_id = new_run_id()
    out_path = Path(out_dir) if out_dir else phase_dir(run_id, "ask")
    out_path.mkdir(parents=True, exist_ok=True)

    typer.echo(f"🔍 Asking: {question}")
    typer.echo(f"📁 Output: {out_path}")
    typer.echo(f"🧠 Provider: {provider}")

    try:
        # Create retriever
        start_time = time.time()
        retriever = create_retriever(db_url=db_url, provider_name=provider)

        # Perform search
        search_start = time.time()
        raw_hits = retriever.search(question, top_k=top_k)
        search_time = time.time() - search_start

        if not raw_hits:
            typer.echo("❌ No results found")
            raise typer.Exit(1)

        # Group and pack results
        pack_start = time.time()
        grouped_hits = group_by_doc(raw_hits, max_chunks_per_doc)
        context = pack_context(grouped_hits, max_chars)
        pack_time = time.time() - pack_start

        total_time = time.time() - start_time

        # Create timing info
        timing_info = {
            "total_seconds": total_time,
            "search_seconds": search_time,
            "pack_seconds": pack_time,
        }

        # Write artifacts
        # 1. hits.jsonl
        hits_file = out_path / "hits.jsonl"
        with open(hits_file, "w") as f:
            for hit in grouped_hits:
                f.write(json.dumps(hit) + "\n")

        # 2. summary.json
        summary = create_context_summary(
            question, grouped_hits, provider, timing_info
        )
        summary_file = out_path / "summary.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)

        # 3. context.txt
        context_file = out_path / "context.txt"
        with open(context_file, "w") as f:
            f.write(context)

        # Output results
        if format_output == "json":
            typer.echo(json.dumps(summary, indent=2))
        else:
            # Text format - show summary
            typer.echo("\n📊 Results:")
            typer.echo(f"  Top hits: {len(grouped_hits)}")
            typer.echo(f"  Documents: {summary['unique_documents']}")
            typer.echo(f"  Characters: {summary['total_characters']:,}")
            typer.echo(
                f"  Score range: {summary['score_stats']['min']:.3f} - {summary['score_stats']['max']:.3f}"
            )
            typer.echo(f"  Duration: {total_time:.2f}s")

            # Show top few hits
            typer.echo("\n🎯 Top results:")
            for i, hit in enumerate(grouped_hits[:3]):
                title = hit.get("title", "Untitled")
                url = hit.get("url", "")
                score = hit.get("score", 0.0)
                typer.echo(f"  {i + 1}. {title} (score: {score:.3f})")
                if url:
                    typer.echo(f"     {url}")

            if len(grouped_hits) > 3:
                typer.echo(f"     ... and {len(grouped_hits) - 3} more")

            typer.echo("\n📄 Context preview (first 200 chars):")
            preview = context[:200].replace("\n", " ")
            typer.echo(f"  {preview}{'...' if len(context) > 200 else ''}")

        typer.echo(f"\n✅ Artifacts written to: {out_path}")

    except Exception as e:
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
    state_dir = Path("state/confluence")
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


if __name__ == "__main__":
    app()
