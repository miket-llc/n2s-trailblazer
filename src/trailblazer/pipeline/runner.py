from typing import List, Optional, TYPE_CHECKING
from .dag import DEFAULT_PHASES, validate_phases
from ..core.artifacts import new_run_id, phase_dir
from ..core.logging import log

if TYPE_CHECKING:
    from ..core.config import Settings


def run(
    phases: Optional[List[str]] = None,
    dry_run: bool = False,
    run_id: Optional[str] = None,
    settings: Optional["Settings"] = None,
) -> str:
    phases = validate_phases(phases or DEFAULT_PHASES)
    rid = run_id or new_run_id()
    log.info("pipeline.run.start", run_id=rid, phases=phases, dry_run=dry_run)

    for phase in phases:
        outdir = phase_dir(rid, phase)
        log.info("phase.start", phase=phase, out=str(outdir), run_id=rid)
        if not dry_run:
            _execute_phase(phase, out=str(outdir), settings=settings)
        log.info("phase.end", phase=phase, run_id=rid)

    log.info("pipeline.run.end", run_id=rid)
    return rid


def _execute_phase(
    phase: str, out: str, settings: Optional["Settings"] = None
) -> None:
    if phase == "ingest":
        from .steps.ingest.confluence import ingest_confluence
        from ..core.config import SETTINGS

        ingest_confluence(
            out,
            space_keys=None,
            space_ids=None,
            since=None,
            body_format=SETTINGS.CONFLUENCE_BODY_FORMAT,
        )
    elif phase == "normalize":
        from .steps.normalize.html_to_md import normalize_from_ingest

        normalize_from_ingest(outdir=out)
    elif phase == "embed":
        from .steps.embed.loader import load_normalized_to_db

        # Extract run_id from output path (runs/<run_id>/embed)
        run_id = out.split("/")[-2]
        load_normalized_to_db(run_id=run_id, provider_name="dummy")
    elif phase == "retrieve":
        # This is handled via the CLI 'ask' command
        # Runner can create a placeholder directory for consistency
        from pathlib import Path

        Path(out).mkdir(parents=True, exist_ok=True)
        log.info(
            "phase.retrieve.placeholder",
            msg="Use 'trailblazer ask <question>' for interactive retrieval",
        )
    # other phases: placeholders
