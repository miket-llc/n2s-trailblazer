import typer
from typing import List, Optional
from datetime import datetime
from ..core.logging import setup_logging, log
from ..core.config import SETTINGS
from ..pipeline.runner import run as run_pipeline

app = typer.Typer(add_completion=False, help="Trailblazer CLI")
ingest_app = typer.Typer(help="Ingestion commands")
normalize_app = typer.Typer(help="Normalization commands")
db_app = typer.Typer(help="Database commands")
embed_app = typer.Typer(help="Embedding commands")
app.add_typer(ingest_app, name="ingest")
app.add_typer(normalize_app, name="normalize")
app.add_typer(db_app, name="db")
app.add_typer(embed_app, name="embed")


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
    body_format: str = typer.Option(
        "storage", help="storage or atlas_doc_format"
    ),
    max_pages: Optional[int] = typer.Option(
        None, help="Stop after N pages (debug)"
    ),
) -> None:
    from ..core.artifacts import new_run_id, phase_dir
    from ..pipeline.steps.ingest.confluence import ingest_confluence

    rid = new_run_id()
    out = str(phase_dir(rid, "ingest"))
    dt = (
        datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    )
    metrics = ingest_confluence(
        outdir=out,
        space_keys=space or None,
        space_ids=space_id or None,
        since=dt,
        body_format=body_format,
        max_pages=max_pages,
    )
    log.info("cli.ingest.confluence.done", run_id=rid, **metrics)
    typer.echo(rid)


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


@db_app.command("init")
def db_init_cmd() -> None:
    """Initialize database schema (safe if tables already exist)."""
    from ..db.engine import create_tables, get_db_url

    db_url = get_db_url()
    typer.echo(f"Initializing database: {db_url}")

    try:
        create_tables()
        typer.echo("✅ Database schema initialized successfully")
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
    from ..db.engine import get_db_url
    from ..pipeline.steps.embed.loader import load_normalized_to_db

    if not run_id and not input_file:
        raise typer.BadParameter("Either --run-id or --input must be provided")

    db_url = get_db_url()
    typer.echo(f"Loading to database: {db_url}")
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


if __name__ == "__main__":
    app()
