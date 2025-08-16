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

    # Check if this should use backlog-based processing
    if not run_id and len(phases) == 1 and phases[0] in ("embed", "chunk"):
        # Default behavior: process from backlog
        return run_from_backlog(phases[0], dry_run=dry_run, settings=settings)

    # Traditional single-run mode
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


def run_from_backlog(
    phase: str,
    dry_run: bool = False,
    settings: Optional["Settings"] = None,
    limit: Optional[int] = None,
) -> str:
    """
    Process runs from the backlog for chunk or embed phases.

    Args:
        phase: 'chunk' or 'embed'
        dry_run: Whether to execute or just show what would be done
        settings: Pipeline settings
        limit: Limit number of runs to process

    Returns:
        Status message
    """
    from .backlog import (
        get_backlog_summary,
        claim_run_for_chunking,
        claim_run_for_embedding,
    )

    if phase not in ("chunk", "embed"):
        raise ValueError(
            f"Backlog processing only supports chunk/embed, got: {phase}"
        )

    # Show backlog summary
    summary = get_backlog_summary(phase)
    total = summary["total"]
    sample_runs = summary["sample_run_ids"]

    if total == 0:
        log.info(
            f"{phase}.backlog.empty", message=f"No runs available for {phase}"
        )
        return f"No runs available for {phase}"

    # Print banner to stderr
    import sys

    earliest = summary.get("earliest", "unknown")
    latest = summary.get("latest", "unknown")
    print(
        f"🔄 {phase.title()} Backlog: {total} runs available", file=sys.stderr
    )
    print(f"   Date range: {earliest} to {latest}", file=sys.stderr)
    print(f"   Sample runs: {', '.join(sample_runs[:5])}", file=sys.stderr)

    if dry_run:
        return f"Would process {total} runs for {phase}"

    processed = 0
    while True:
        if limit and processed >= limit:
            break

        # Claim next run
        if phase == "chunk":
            run_record = claim_run_for_chunking()
        else:  # embed
            run_record = claim_run_for_embedding()

        if not run_record:
            log.info(f"{phase}.backlog.exhausted", processed=processed)
            break

        run_id = run_record["run_id"]
        log.info(
            f"{phase}.backlog.processing",
            run_id=run_id,
            progress=f"{processed + 1}/{total}",
        )

        try:
            # Execute the phase
            outdir = phase_dir(run_id, phase)
            _execute_phase(phase, str(outdir), settings=settings)
            processed += 1

        except Exception as e:
            log.error(f"{phase}.backlog.failed", run_id=run_id, error=str(e))
            # Continue processing other runs

    return f"Processed {processed} runs for {phase}"


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
    elif phase == "chunk":
        # Chunk phase: process normalized docs into chunks
        from .steps.embed.chunker import chunk_normalized_record
        import json
        from pathlib import Path

        # Extract run_id from output path (runs/<run_id>/chunk)
        run_id = out.split("/")[-2]

        # Input: normalized.ndjson, Output: chunked records
        normalized_file = Path(out).parent / "normalize" / "normalized.ndjson"
        chunk_dir = Path(out)
        chunk_dir.mkdir(parents=True, exist_ok=True)

        chunks_file = chunk_dir / "chunks.ndjson"
        total_chunks = 0

        with open(normalized_file, "r") as fin, open(chunks_file, "w") as fout:
            for line in fin:
                record = json.loads(line.strip())
                chunks = chunk_normalized_record(record)
                for chunk in chunks:
                    chunk_data = {
                        "chunk_id": chunk.chunk_id,
                        "doc_id": record.get("id"),
                        "ord": chunk.ord,
                        "text_md": chunk.text_md,
                        "char_count": chunk.char_count,
                        "token_count": chunk.token_count,
                        "chunk_type": chunk.chunk_type,
                        "meta": chunk.meta,
                    }
                    fout.write(json.dumps(chunk_data) + "\n")
                    total_chunks += 1

        # Mark chunking complete in backlog
        try:
            from .backlog import mark_chunking_complete

            mark_chunking_complete(run_id, total_chunks)
        except Exception as e:
            log.warning("chunk.backlog_failed", error=str(e))

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
