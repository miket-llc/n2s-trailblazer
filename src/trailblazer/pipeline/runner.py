from typing import Dict, List, Optional, TYPE_CHECKING
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
    limit: Optional[int] = None,
) -> str:
    phases = validate_phases(phases or DEFAULT_PHASES)

    # Check if this should use backlog-based processing
    if not run_id and len(phases) == 1 and phases[0] in ("embed", "chunk"):
        # Default behavior: process from backlog
        return run_from_backlog(
            phases[0], dry_run=dry_run, settings=settings, limit=limit
        )

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
    phase: str, out: str, settings: Optional["Settings"] = None, **kwargs
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
        # Chunk phase: process enriched or normalized docs into chunks using new chunking package
        from .steps.chunk.engine import (
            chunk_document,
            inject_media_placeholders,
        )
        from .steps.chunk.assurance import build_chunk_assurance
        import json
        import hashlib
        from datetime import datetime, timezone
        from pathlib import Path

        # Extract run_id from output path (runs/<run_id>/chunk)
        run_id = out.split("/")[-2]

        # Get chunking parameters from kwargs
        max_tokens = kwargs.get("max_tokens", 800)
        min_tokens = kwargs.get("min_tokens", 120)
        overlap_tokens = kwargs.get("overlap_tokens", 60)
        soft_min_tokens = kwargs.get("soft_min_tokens", 200)
        hard_min_tokens = kwargs.get("hard_min_tokens", 80)
        orphan_heading_merge = kwargs.get("orphan_heading_merge", True)
        small_tail_merge = kwargs.get("small_tail_merge", True)

        # Prefer enriched input if available, otherwise use normalized
        enriched_file = Path(out).parent / "enrich" / "enriched.jsonl"
        normalized_file = Path(out).parent / "normalize" / "normalized.ndjson"

        if enriched_file.exists():
            input_file = enriched_file
            input_type = "enriched"
        else:
            input_file = normalized_file
            input_type = "normalized"

        chunk_dir = Path(out)
        chunk_dir.mkdir(parents=True, exist_ok=True)

        chunks_file = chunk_dir / "chunks.ndjson"
        skipped_file = chunk_dir / "skipped_docs.jsonl"
        total_chunks = 0
        total_docs = 0
        token_counts = []
        char_counts = []
        split_strategies = []
        skipped_docs = []

        chunk_config = {
            "max_tokens": max_tokens,
            "hard_max_tokens": max_tokens,
            "min_tokens": min_tokens,
            "overlap_tokens": overlap_tokens,
            "soft_min_tokens": soft_min_tokens,
            "hard_min_tokens": hard_min_tokens,
            "orphan_heading_merge": orphan_heading_merge,
            "small_tail_merge": small_tail_merge,
            "prefer_headings": True,
            "respect_fences": True,
            "split_tables": "row-groups",
        }

        # Compute hash of input file for traceability
        input_hash = None
        if input_file.exists():
            with open(input_file, "rb") as f:
                input_hash = hashlib.sha256(f.read()).hexdigest()

        with open(input_file, "r") as fin, open(chunks_file, "w") as fout:
            for line_num, line in enumerate(fin, 1):
                if not line.strip():
                    continue

                try:
                    record = json.loads(line.strip())
                    doc_id = record.get("id", "")
                    if not doc_id:
                        continue

                    total_docs += 1

                    # Extract document data
                    title = record.get("title", "")
                    text_md = record.get("text_md", "")
                    url = record.get("url", "")
                    source_system = record.get("source_system", "")
                    labels = record.get("labels", [])
                    space = record.get("space", {})
                    attachments = record.get("attachments", [])

                    # Get enrichment data if available
                    if input_type == "enriched":
                        chunk_hints = record.get("chunk_hints", {})
                        section_map = record.get("section_map", [])

                        # Override config with chunk hints
                        hard_max_tokens = chunk_hints.get(
                            "maxTokens", max_tokens
                        )
                        min_tokens_doc = chunk_hints.get(
                            "minTokens", min_tokens
                        )
                        overlap_tokens_doc = chunk_hints.get(
                            "overlapTokens", overlap_tokens
                        )
                        prefer_headings = chunk_hints.get(
                            "preferHeadings", True
                        )
                        soft_boundaries = chunk_hints.get("softBoundaries", [])
                    else:
                        hard_max_tokens = max_tokens
                        min_tokens_doc = min_tokens
                        overlap_tokens_doc = overlap_tokens
                        prefer_headings = True
                        soft_boundaries = []
                        section_map = []

                    # Inject media placeholders
                    text_with_media = inject_media_placeholders(
                        text_md, attachments
                    )

                    # Create media refs for traceability
                    media_refs = []
                    for attachment in attachments:
                        media_refs.append(
                            {
                                "type": attachment.get("type", "attachment"),
                                "ref": attachment.get("filename", ""),
                            }
                        )

                    # Chunk document
                    emit_func = kwargs.get("emit")
                    chunks = chunk_document(
                        doc_id=doc_id,
                        text_md=text_with_media,
                        title=title,
                        url=url,
                        source_system=source_system,
                        labels=labels,
                        space=space,
                        media_refs=media_refs,
                        hard_max_tokens=hard_max_tokens,
                        min_tokens=min_tokens_doc,
                        overlap_tokens=overlap_tokens_doc,
                        prefer_headings=prefer_headings,
                        soft_boundaries=soft_boundaries,
                        section_map=section_map,
                        emit=emit_func,
                    )

                    # Write chunks
                    for chunk in chunks:
                        chunk_data = {
                            "chunk_id": chunk.chunk_id,
                            "text_md": chunk.text_md,
                            "char_count": chunk.char_count,
                            "token_count": chunk.token_count,
                            "ord": chunk.ord,
                            "chunk_type": chunk.chunk_type,
                            "meta": chunk.meta,
                            "split_strategy": chunk.split_strategy,
                            "doc_id": chunk.doc_id,
                            "title": chunk.title,
                            "url": chunk.url,
                            "source_system": chunk.source_system,
                            "labels": chunk.labels,
                            "space": chunk.space,
                            "media_refs": chunk.media_refs,
                        }
                        fout.write(json.dumps(chunk_data) + "\n")

                        total_chunks += 1
                        token_counts.append(chunk.token_count)
                        char_counts.append(chunk.char_count)
                        split_strategies.append(chunk.split_strategy)

                except Exception as e:
                    skipped_docs.append(
                        {
                            "doc_id": record.get("id", f"line_{line_num}"),
                            "reason": f"Error processing document: {str(e)}",
                            "line_number": line_num,
                        }
                    )
                    continue

        # Write skipped docs if any
        if skipped_docs:
            with open(skipped_file, "w") as f:
                for doc in skipped_docs:
                    f.write(json.dumps(doc) + "\n")

        # Build chunk assurance using new chunking package
        assurance = build_chunk_assurance(Path(out).parent, chunk_config)

        # Add additional metadata
        assurance.update(
            {
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "docCount": total_docs,
                "chunkCount": total_chunks,
                "tokenizer": "tiktoken",
                "chunkConfig": chunk_config,
                "inputType": input_type,
                "inputHash": input_hash,
                "artifacts": {
                    "chunks_file": str(chunks_file),
                    "input_file": str(input_file),
                    "normalized_file": str(normalized_file),
                    "enriched_file": str(enriched_file)
                    if enriched_file.exists()
                    else None,
                },
            }
        )

        # Add split strategy distribution
        if split_strategies:
            strategy_counts: Dict[str, int] = {}
            for strategy in split_strategies:
                strategy_counts[strategy] = (
                    strategy_counts.get(strategy, 0) + 1
                )
            assurance["splitStrategies"].update(strategy_counts)

        # Get quality distribution from enriched data if available
        if input_type == "enriched" and enriched_file.exists():
            quality_scores = []
            try:
                with open(enriched_file, "r") as f:
                    for line in f:
                        if line.strip():
                            record = json.loads(line.strip())
                            score = record.get("quality_score")
                            if score is not None:
                                quality_scores.append(score)

                if quality_scores:
                    sorted_scores = sorted(quality_scores)
                    n = len(sorted_scores)
                    p50_idx = int(0.5 * n)
                    p90_idx = int(0.9 * n)

                    # Assume default thresholds if not specified
                    min_quality = 0.60
                    max_below_threshold_pct = 0.20

                    below_threshold = sum(
                        1 for score in quality_scores if score < min_quality
                    )
                    below_threshold_pct = below_threshold / n if n > 0 else 1.0

                    quality_distribution = {
                        "p50": round(sorted_scores[min(p50_idx, n - 1)], 3),
                        "p90": round(sorted_scores[min(p90_idx, n - 1)], 3),
                        "belowThresholdPct": round(below_threshold_pct, 3),
                        "minQuality": min_quality,
                        "maxBelowThresholdPct": max_below_threshold_pct,
                    }
                    assurance["qualityDistribution"] = quality_distribution
            except Exception as e:
                log.warning("chunk.quality_distribution_failed", error=str(e))

        # Write chunk assurance file
        assurance_file = chunk_dir / "chunk_assurance.json"
        with open(assurance_file, "w") as f:
            json.dump(assurance, f, indent=2)

        log.info(
            "chunk.assurance",
            run_id=run_id,
            docs=total_docs,
            chunks=total_chunks,
            skipped=len(skipped_docs),
            assurance_file=str(assurance_file),
        )

        # Mark chunking complete in backlog
        try:
            from .backlog import mark_chunking_complete

            mark_chunking_complete(run_id, total_chunks)
        except Exception as e:
            log.warning("chunk.backlog_failed", error=str(e))

    elif phase == "embed":
        from .steps.embed.loader import load_normalized_to_db
        import json
        from datetime import datetime, timezone
        from pathlib import Path

        # Extract run_id from output path (runs/<run_id>/embed)
        run_id = out.split("/")[-2]

        # Create embed assurance by copying chunk assurance
        embed_dir = Path(out)
        embed_dir.mkdir(parents=True, exist_ok=True)

        chunk_assurance_file = (
            embed_dir.parent / "chunk" / "chunk_assurance.json"
        )
        embed_assurance_file = embed_dir / "embed_assurance.json"

        embed_assurance = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chunk": None,
            "embed": {
                "provider": settings.EMBED_PROVIDER if settings else "dummy",
                "model": settings.EMBED_MODEL if settings else None,
                "dimensions": settings.EMBED_DIMENSIONS if settings else None,
                "batch_size": settings.EMBED_BATCH_SIZE if settings else 128,
            },
        }

        # Copy chunk assurance data if available
        if chunk_assurance_file.exists():
            with open(chunk_assurance_file) as f:
                chunk_assurance = json.load(f)
            embed_assurance["chunk"] = chunk_assurance
            log.info(
                "embed.assurance.chunk_copied",
                run_id=run_id,
                chunk_docs=chunk_assurance.get("docCount"),
                chunk_count=chunk_assurance.get("chunkCount"),
            )
        else:
            log.warning("embed.assurance.no_chunk_data", run_id=run_id)

        # Write embed assurance
        with open(embed_assurance_file, "w") as f:
            json.dump(embed_assurance, f, indent=2)

        log.info(
            "embed.assurance.created",
            run_id=run_id,
            assurance_file=str(embed_assurance_file),
        )

        # Use settings for embedding configuration
        provider_name = settings.EMBED_PROVIDER if settings else "dummy"
        model = settings.EMBED_MODEL if settings else None
        dimensions = settings.EMBED_DIMENSIONS if settings else None
        batch_size = settings.EMBED_BATCH_SIZE if settings else 128

        load_normalized_to_db(
            run_id=run_id,
            provider_name=provider_name,
            model=model,
            dimensions=dimensions,
            batch_size=batch_size,
        )
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
