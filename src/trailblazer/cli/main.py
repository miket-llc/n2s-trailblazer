import typer
from typing import List, Optional
from datetime import datetime
from ..core.logging import setup_logging, log
from ..core.config import SETTINGS
from ..pipeline.runner import run as run_pipeline

app = typer.Typer(add_completion=False, help="Trailblazer CLI")
ingest_app = typer.Typer(help="Ingestion commands")
normalize_app = typer.Typer(help="Normalization commands")
app.add_typer(ingest_app, name="ingest")
app.add_typer(normalize_app, name="normalize")


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


if __name__ == "__main__":
    app()
