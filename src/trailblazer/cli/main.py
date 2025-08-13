import typer
from typing import List, Optional
from datetime import datetime
from ..core.logging import setup_logging, log
from ..core.config import SETTINGS
from ..pipeline.runner import run as run_pipeline

app = typer.Typer(add_completion=False, help="Trailblazer CLI")
ingest_app = typer.Typer(help="Ingestion commands")
app.add_typer(ingest_app, name="ingest")


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


if __name__ == "__main__":
    app()
