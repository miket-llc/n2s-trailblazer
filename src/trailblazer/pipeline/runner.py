from typing import List, Optional
from .dag import DEFAULT_PHASES, validate_phases
from ..core.artifacts import new_run_id, phase_dir
from ..core.logging import log


def run(
    phases: Optional[List[str]] = None, dry_run: bool = False, run_id: Optional[str] = None
) -> str:
    phases = validate_phases(phases or DEFAULT_PHASES)
    rid = run_id or new_run_id()
    log.info("pipeline.run.start", run_id=rid, phases=phases, dry_run=dry_run)

    for phase in phases:
        outdir = phase_dir(rid, phase)
        log.info("phase.start", phase=phase, out=str(outdir), run_id=rid)
        if not dry_run:
            _execute_phase(phase, out=str(outdir))
        log.info("phase.end", phase=phase, run_id=rid)

    log.info("pipeline.run.end", run_id=rid)
    return rid


def _execute_phase(phase: str, out: str) -> None:
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
    # other phases: placeholders
