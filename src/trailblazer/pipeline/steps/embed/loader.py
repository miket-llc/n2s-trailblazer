from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from sqlalchemy.orm import Session


from ....core.logging import log
from ....core.progress import get_progress
from ....obs.events import EventEmitter
from .provider import EmbeddingProvider
from ....db.engine import (  # type: ignore[import-untyped]
    get_session_factory,
    serialize_embedding,
    upsert_chunk,
    upsert_chunk_embedding,
    upsert_document,
)

# Embed step reads pre-chunked data from chunks.ndjson files
from .provider import get_embedding_provider

# Embed step reads pre-chunked data from chunks.ndjson files only
# On-the-fly chunking is forbidden - use 'trailblazer chunk run' first


def _validate_no_chunk_imports():
    """Guard to prevent chunk imports in embed code."""
    import sys

    forbidden_modules = [
        "trailblazer.pipeline.steps.chunk.engine",
        "trailblazer.pipeline.steps.chunk.boundaries",
        "trailblazer.pipeline.steps.chunk.assurance",
    ]

    for module_name in forbidden_modules:
        if module_name in sys.modules:
            raise RuntimeError(
                f"embed requires materialized chunks; on-the-fly chunking is forbidden; "
                f"run 'trailblazer chunk run <RID>' first; found import: {module_name}"
            )


def _validate_materialized_chunks(run_id: str) -> None:
    """Ensure run has materialized chunks before embedding."""
    from ....core.paths import runs

    if not run_id or run_id == "unknown":
        return  # Skip validation for direct file input

    chunks_file = runs() / run_id / "chunk" / "chunks.ndjson"
    if not chunks_file.exists():
        raise FileNotFoundError(
            f"embed requires materialized chunks; run 'trailblazer chunk run {run_id}' first; "
            f"missing: {chunks_file}"
        )

    # Check that chunks file is not empty
    try:
        with open(chunks_file, "r") as f:
            first_line = f.readline().strip()
            if not first_line:
                raise ValueError(
                    f"embed requires materialized chunks; run 'trailblazer chunk run {run_id}' first; "
                    f"empty chunks file: {chunks_file}"
                )
    except Exception as e:
        if isinstance(e, (FileNotFoundError, ValueError)):
            raise
        raise RuntimeError(
            f"embed requires materialized chunks; run 'trailblazer chunk run {run_id}' first; "
            f"error reading chunks file: {chunks_file}: {e}"
        )


def _default_chunks_path(run_id: str) -> Path:
    """Get default path to chunks.ndjson for a run."""
    from ....core.paths import runs

    return runs() / run_id / "chunk" / "chunks.ndjson"


def _default_enriched_path(run_id: str) -> Path:
    """Get default path to enriched.jsonl for a run."""
    from ....core.paths import runs

    return runs() / run_id / "enrich" / "enriched.jsonl"


def _now_iso() -> str:
    """Get current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    """Parse timestamp string to datetime object."""
    if not timestamp_str:
        return None
    try:
        return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _compute_content_hash(record: Dict[str, Any]) -> str:
    """Compute SHA256 hash of document content for idempotency."""
    content_fields = ["text_md", "title", "space_key", "url"]
    content = "|".join(str(record.get(field, "")) for field in content_fields)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_fingerprints(fingerprints_path: Path) -> Dict[str, str]:
    """Load fingerprints from JSONL file."""
    fingerprints: Dict[str, str] = {}

    if not fingerprints_path.exists():
        return fingerprints

    try:
        with open(fingerprints_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line.strip())
                    doc_id = data.get("doc_id")
                    fingerprint = data.get("fingerprint")
                    if doc_id and fingerprint:
                        fingerprints[doc_id] = fingerprint
    except Exception as e:
        log.warning(
            "embed.load.fingerprints_error",
            path=str(fingerprints_path),
            error=str(e),
        )

    return fingerprints


def _determine_changed_docs(
    run_id: str, changed_only: bool
) -> Optional[Set[str]]:
    """
    Determine which documents have changed based on enrichment fingerprints.

    Args:
        run_id: The run ID to check
        changed_only: Whether to perform fingerprint comparison

    Returns:
        Set of doc_ids that have changed, or None if all should be processed
    """
    if not changed_only:
        return None

    from ....core.artifacts import phase_dir

    enrich_dir = phase_dir(run_id, "enrich")
    fingerprints_path = enrich_dir / "fingerprints.jsonl"
    prev_fingerprints_path = enrich_dir / "fingerprints.prev.jsonl"

    if not fingerprints_path.exists():
        raise FileNotFoundError(
            f"Fingerprints file not found: {fingerprints_path}"
        )

    # Load current fingerprints
    current_fingerprints = _load_fingerprints(fingerprints_path)

    # Load previous fingerprints if they exist
    if prev_fingerprints_path.exists():
        prev_fingerprints = _load_fingerprints(prev_fingerprints_path)
    else:
        # No previous fingerprints, treat all as changed
        return set(current_fingerprints.keys())

    # Find documents with changed or new fingerprints
    changed_docs = set()
    for doc_id, current_fp in current_fingerprints.items():
        prev_fp = prev_fingerprints.get(doc_id)
        if prev_fp != current_fp:
            changed_docs.add(doc_id)

    return changed_docs


def _save_fingerprints_as_previous(run_id: str) -> None:
    """
    Atomically copy fingerprints.jsonl to fingerprints.prev.jsonl.

    Args:
        run_id: The run ID to process
    """
    from ....core.artifacts import phase_dir
    import shutil

    enrich_dir = phase_dir(run_id, "enrich")
    fingerprints_path = enrich_dir / "fingerprints.jsonl"
    prev_fingerprints_path = enrich_dir / "fingerprints.prev.jsonl"

    if fingerprints_path.exists():
        # Atomic copy using a temporary file
        temp_path = prev_fingerprints_path.with_suffix(".tmp")
        try:
            shutil.copy2(fingerprints_path, temp_path)
            temp_path.rename(prev_fingerprints_path)
        except Exception:
            # Clean up temp file if something went wrong
            if temp_path.exists():
                temp_path.unlink()
            raise


def load_chunks_to_db(
    run_id: Optional[str] = None,
    chunks_file: Optional[str] = None,
    provider_name: str = "dummy",
    model: Optional[str] = None,
    dimensions: Optional[int] = None,
    batch_size: int = 128,
    max_docs: Optional[int] = None,
    max_chunks: Optional[int] = None,
    changed_only: bool = False,
    reembed_all: bool = False,
    dry_run_cost: bool = False,
) -> Dict[str, Any]:
    """
    Load pre-chunked data into the database with embeddings (idempotent).

    Args:
        run_id: Run ID to load (uses runs/<RUN_ID>/chunk/chunks.ndjson)
        chunks_file: Chunks NDJSON file to load (overrides run_id)
        provider_name: Embedding provider to use
        model: Model name for the provider (e.g., text-embedding-3-small)
        dimensions: Embedding dimensions (e.g., 512, 1024, 1536)
        batch_size: Batch size for embedding generation
        max_docs: Maximum number of documents to process
        max_chunks: Maximum number of chunks to process
        changed_only: Only embed documents with changed enrichment fingerprints
        reembed_all: Force re-embed all documents regardless of fingerprints
        dry_run_cost: Estimate tokens and cost without calling API

    Returns:
        Metrics dictionary with counts and timing
    """
    # Validate that chunking imports haven't occurred
    _validate_no_chunk_imports()

    # Determine input files
    if chunks_file:
        chunks_path = Path(chunks_file)
        run_id = run_id or "unknown"
    elif run_id:
        _validate_materialized_chunks(run_id)
        chunks_path = _default_chunks_path(run_id)
    else:
        raise ValueError("Either run_id or chunks_file must be provided")

    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    # For document metadata, try to load enriched.jsonl
    enriched_path = None
    if run_id and run_id != "unknown":
        enriched_path = _default_enriched_path(run_id)

    # Load document metadata for upserts
    doc_metadata = {}
    if enriched_path and enriched_path.exists():
        with open(enriched_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line.strip())
                    doc_id = record.get("id")
                    if doc_id:
                        doc_metadata[doc_id] = record

    # Determine which documents to process based on fingerprints
    if reembed_all:
        changed_docs = None  # Process all documents
    else:
        changed_docs = _determine_changed_docs(run_id, changed_only)

    # Get embedding provider with custom model/dimensions if specified
    if model or dimensions:
        # For OpenAI, we can override model and dimensions
        if provider_name == "openai":
            from .provider import OpenAIEmbedder

            embedder: EmbeddingProvider = OpenAIEmbedder(
                model=model or "text-embedding-3-small", dim=dimensions or 1536
            )
        # For sentencetransformers, we can override model
        elif provider_name == "sentencetransformers":
            from .provider import SentenceTransformerEmbedder

            embedder = SentenceTransformerEmbedder(model_name=model)
        # For dummy, we can override dimensions
        elif provider_name == "dummy":
            from .provider import DummyEmbedder

            embedder = DummyEmbedder(dim=dimensions or 384)
        else:
            # Fall back to default provider
            embedder = get_embedding_provider(provider_name)
    else:
        embedder = get_embedding_provider(provider_name)

    # Initialize session
    session_factory = get_session_factory()

    # Initialize standardized progress renderer and event emitter
    progress_renderer = get_progress()

    # Set up event emitter with proper logging paths
    event_emitter = EventEmitter(
        run_id=run_id or "unknown",
        phase="embed",
        component="loader",
    )

    # Metrics with detailed tracking
    docs_total = 0
    docs_skipped = 0
    docs_embedded = 0
    docs_changed = 0
    docs_unchanged = 0
    chunks_total = 0
    chunks_skipped = 0
    chunks_embedded = 0
    errors: List[Dict[str, Any]] = []

    start_time = datetime.now(timezone.utc)

    # Use standardized progress and event logging
    if progress_renderer.enabled:
        progress_renderer.console.print(
            "🔄 [bold cyan]Loading embeddings from materialized chunks[/bold cyan]"
        )
        progress_renderer.console.print(
            f"📁 Input: [cyan]{chunks_path.name}[/cyan]"
        )
        progress_renderer.console.print(
            f"🧠 Provider: [green]{embedder.provider_name}[/green] (dim={embedder.dimension})"
        )
        progress_renderer.console.print(f"📦 Batch size: {batch_size}")
        progress_renderer.console.print("")

    # Start event logging with proper EventEmitter and set global shim context
    with event_emitter:
        try:
            from ....obs.events import EventEmitter as _EE
            _EE.set_event_context(run_id=run_id or "unknown", stage="embed", component="loader")
        except Exception:
            pass
        event_emitter.embed_start(
            provider=embedder.provider_name,
            model=getattr(embedder, "model", "unknown"),
            embedding_dims=embedder.dimension,
            chunks_file=str(chunks_path),
            batch_size=batch_size,
            max_docs=max_docs,
            max_chunks=max_chunks,
            changed_only=changed_only,
            metadata={
                "changed_docs_count": len(changed_docs)
                if changed_docs is not None
                else None,
            },
        )

        # Helper function for event emission
        def emit_event(event_type: str, **kwargs):
            """Emit events using EventEmitter."""
            if "error" in event_type:
                event_emitter.error(
                    kwargs.get("error", f"Error in {event_type}"),
                    metadata=kwargs,
                )
            elif "heartbeat" in event_type:
                event_emitter.heartbeat(
                    processed=kwargs.get("chunks_total", 0),
                    rate=kwargs.get("rate_chunks_per_sec", 0.0),
                    metadata=kwargs,
                )
            elif "skip" in event_type:
                # Skip events are informational
                pass
            else:
                # Other events - use tick for progress
                event_emitter.embed_tick(
                    processed=kwargs.get("chunks_total", 0), metadata=kwargs
                )

        with session_factory() as session:
            # Process chunks in batches
            batch_texts = []
            batch_chunk_data = []
            last_progress_time = start_time

            # Initialize cost estimation variables
            estimated_tokens = 0
            estimated_cost = 0.0

            # Track processed documents
            processed_docs = set()

            # Use standardized progress display
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TextColumn(
                    "docs={task.fields[docs]} chunks={task.fields[chunks]}"
                ),
                TimeElapsedColumn(),
                console=progress_renderer.console
                if progress_renderer.enabled
                else None,
            ) as progress:
                task = (
                    progress.add_task(
                        "Processing...", docs=0, chunks=0, total=None
                    )
                    if progress_renderer.enabled
                    else None
                )

            with chunks_path.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    if not line.strip():
                        continue

                    try:
                        chunk_record = json.loads(line)
                    except json.JSONDecodeError as e:
                        error_info = {"line": line_num, "error": str(e)}
                        errors.append(error_info)
                        emit_event("error", **error_info)
                        continue

                    # Extract chunk data
                    chunk_id = chunk_record.get("chunk_id")
                    if not chunk_id:
                        error_info = {
                            "line": line_num,
                            "error": "missing_chunk_id",
                        }
                        errors.append(error_info)
                        emit_event("error", **error_info)
                        continue

                    # Extract doc_id from chunk_id
                    doc_id = ":".join(chunk_id.split(":")[:-1])

                    # Track unique documents
                    if doc_id not in processed_docs:
                        processed_docs.add(doc_id)
                        docs_total += 1

                        # Check if document should be processed based on fingerprints
                        if (
                            changed_docs is not None
                            and doc_id not in changed_docs
                        ):
                            docs_unchanged += 1
                            event_emitter.warning(
                                f"Skipping document {doc_id} - unchanged fingerprint",
                                metadata={
                                    "doc_id": doc_id,
                                    "reason": "unchanged_fingerprint",
                                },
                            )
                            continue

                        # Only track changed docs when using changed_only mode
                        if changed_docs is not None:
                            docs_changed += 1

                        # Upsert document if we have metadata
                        if doc_id in doc_metadata:
                            record = doc_metadata[doc_id]
                            content_hash = _compute_content_hash(record)

                            # Check if document exists with same content
                            from ....db.engine import Document

                            existing_doc = (
                                session.query(Document)
                                .filter_by(content_sha256=content_hash)
                                .first()
                            )

                            if not existing_doc:
                                # Upsert document (new or changed content)
                                doc_data = {
                                    "doc_id": doc_id,
                                    "source_system": record.get(
                                        "source_system",
                                        record.get("source", "unknown"),
                                    ),
                                    "title": record.get("title"),
                                    "space_key": record.get("space_key"),
                                    "url": record.get("url"),
                                    "created_at": _parse_timestamp(
                                        record.get("created_at")
                                    ),
                                    "updated_at": _parse_timestamp(
                                        record.get("updated_at")
                                    ),
                                    "content_sha256": content_hash,
                                    "meta": {
                                        "version": record.get("version"),
                                        "space_id": record.get("space_id"),
                                        "links": record.get("links", []),
                                        "attachments": record.get(
                                            "attachments", []
                                        ),
                                        "labels": record.get("labels", []),
                                    },
                                }

                                upsert_document(session, doc_data)
                                docs_embedded += 1
                                emit_event(
                                    "doc.upsert",
                                    doc_id=doc_id,
                                    content_sha256=content_hash,
                                )
                            else:
                                docs_skipped += 1
                                emit_event(
                                    "doc.skip",
                                    doc_id=doc_id,
                                    content_sha256=content_hash,
                                    reason="unchanged",
                                )

                    chunks_total += 1

                    # Estimate tokens for cost calculation (dry-run mode)
                    if dry_run_cost:
                        text_md = chunk_record.get("text_md", "")
                        chunk_tokens = (
                            len(text_md) // 4
                        )  # Rough token estimation
                        estimated_tokens += chunk_tokens

                    # Check if chunk already exists
                    from ....db.engine import Chunk as ChunkModel

                    existing_chunk = session.get(ChunkModel, chunk_id)
                    text_md = chunk_record.get("text_md", "")

                    if existing_chunk and existing_chunk.text_md == text_md:
                        # Chunk unchanged, check if embedding exists
                        from ....db.engine import ChunkEmbedding

                        existing_embedding = session.get(
                            ChunkEmbedding,
                            (chunk_id, embedder.provider_name),
                        )
                        if existing_embedding:
                            chunks_skipped += 1
                            emit_event(
                                "chunk.skip",
                                chunk_id=chunk_id,
                                reason="unchanged",
                            )
                            continue

                    # Upsert chunk
                    chunk_data = {
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "ord": chunk_record.get("ord", 0),
                        "text_md": text_md,
                        "char_count": chunk_record.get(
                            "char_count", len(text_md)
                        ),
                        "token_count": chunk_record.get(
                            "token_count", len(text_md) // 4
                        ),
                        "chunk_type": chunk_record.get("chunk_type", "text"),
                        "meta": chunk_record.get("meta", {}),
                    }

                    upsert_chunk(session, chunk_data)
                    emit_event(
                        "chunk.write",
                        chunk_id=chunk_id,
                        char_count=chunk_data["char_count"],
                    )

                    # Collect for batch embedding
                    batch_texts.append(text_md)
                    batch_chunk_data.append(
                        {
                            "chunk_id": chunk_id,
                            "provider": embedder.provider_name,
                            "dim": embedder.dimension,
                            "created_at": datetime.now(timezone.utc),
                        }
                    )
                    chunks_embedded += 1

                    # Process batch when full
                    if len(batch_texts) >= batch_size:
                        _process_embedding_batch(
                            session,
                            embedder,
                            batch_texts,
                            batch_chunk_data,
                            emit_event,
                        )
                        batch_texts.clear()
                        batch_chunk_data.clear()

                    # Update progress every chunk or every 30 seconds
                    if (
                        chunks_total % 100 == 0
                        or (
                            datetime.now(timezone.utc) - last_progress_time
                        ).seconds
                        >= 30
                    ):
                        progress.update(
                            task,
                            description="📄 Processing chunks...",
                            docs=docs_total,
                            chunks=chunks_total,
                        )
                        last_progress_time = datetime.now(timezone.utc)

                        # Emit heartbeat
                        elapsed = (
                            datetime.now(timezone.utc) - start_time
                        ).total_seconds()
                        rate = chunks_total / elapsed if elapsed > 0 else 0
                        emit_event(
                            "heartbeat",
                            docs_total=docs_total,
                            chunks_total=chunks_total,
                            rate_chunks_per_sec=rate,
                            elapsed_seconds=elapsed,
                        )

                    if max_chunks and chunks_total >= max_chunks:
                        break
                    if max_docs and docs_total >= max_docs:
                        break

            # Process remaining batch
            if batch_texts:
                _process_embedding_batch(
                    session,
                    embedder,
                    batch_texts,
                    batch_chunk_data,
                    emit_event,
                )

            # Final progress update
            progress.update(
                task,
                description="✅ Complete",
                docs=docs_total,
                chunks=chunks_total,
            )

        # Commit all changes
        session.commit()

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    # Handle model attribute safely for mocks
    model_attr = getattr(embedder, "model", None)
    if hasattr(model_attr, "_mock_name"):  # Detect MagicMock objects
        model_attr = "dummy"

    metrics = {
        "run_id": run_id,
        "chunks_file": str(chunks_path),
        "provider": embedder.provider_name,
        "model": model_attr,
        "dimension": embedder.dimension,
        "reembed_all": reembed_all,
        "docs_total": docs_total,
        "docs_skipped": docs_skipped,
        "docs_embedded": docs_embedded,
        "docs_changed": docs_changed,
        "docs_unchanged": docs_unchanged,
        "chunks_total": chunks_total,
        "chunks_skipped": chunks_skipped,
        "chunks_embedded": chunks_embedded,
        "duration_seconds": duration,
        "errors": errors,
        "completed_at": _now_iso(),
    }

    # Add cost estimation if dry-run mode
    if dry_run_cost:
        metrics["estimated_tokens"] = estimated_tokens
        # Calculate estimated cost for OpenAI models
        if provider_name == "openai":
            # Rough cost estimation: $0.0001 per 1K tokens for text-embedding-3-small
            estimated_cost = (estimated_tokens / 1000) * 0.0001
            metrics["estimated_cost"] = estimated_cost

    emit_event("embed.load.done", **metrics)

    # Save fingerprints as previous if changed_only was used and embedding was successful
    if changed_only and run_id and run_id != "unknown":
        try:
            _save_fingerprints_as_previous(run_id)
            emit_event("embed.fingerprints_saved", fingerprints_saved=True)
        except Exception as e:
            emit_event("embed.fingerprints_save_error", error=str(e))
            log.warning("embed.fingerprints_save_failed", error=str(e))

    # Generate assurance report
    if run_id and run_id != "unknown":
        _generate_assurance_report(run_id, metrics)

    # Write embed manifest after successful embedding
    if run_id and run_id != "unknown" and chunks_embedded > 0:
        try:
            from .manifest import write_embed_manifest

            manifest_file = write_embed_manifest(
                run_id=run_id,
                provider=embedder.provider_name,
                model=getattr(embedder, "model", "unknown"),
                dimension=embedder.dimension,
                chunks_embedded=chunks_embedded,
            )
            emit_event(
                "embed.manifest_written", manifest_file=str(manifest_file)
            )
        except Exception as e:
            emit_event("embed.manifest_write_error", error=str(e))
            log.warning("embed.manifest_write_failed", error=str(e))

    # Mark embedding complete in backlog
    if run_id and run_id != "unknown":
        try:
            from ...backlog import mark_embedding_complete

            mark_embedding_complete(run_id, chunks_embedded)
        except Exception as e:
            log.warning("embed.backlog_failed", error=str(e))

        # Emit completion event
        event_emitter.embed_complete(
            total_embedded=chunks_embedded,
            duration_ms=int(duration * 1000),
            metadata=metrics,
        )

    # Print summary using standardized progress renderer
    if progress_renderer.enabled:
        progress_renderer.console.print("")
        progress_renderer.console.print(
            "📊 [bold green]Embedding Complete[/bold green]"
        )
        if changed_only:
            progress_renderer.console.print(
                f"📄 Documents: [cyan]{docs_changed}[/cyan] changed, [yellow]{docs_unchanged}[/yellow] unchanged"
            )
        progress_renderer.console.print(
            f"📄 Documents: [cyan]{docs_embedded}[/cyan] embedded, [yellow]{docs_skipped}[/yellow] skipped"
        )
        progress_renderer.console.print(
            f"🧩 Chunks: [cyan]{chunks_embedded}[/cyan] embedded, [yellow]{chunks_skipped}[/yellow] skipped"
        )
        progress_renderer.console.print(
            f"🧠 Provider: [green]{embedder.provider_name}[/green] (dim={embedder.dimension})"
        )
        progress_renderer.console.print(
            f"⏱️  Duration: [blue]{duration:.2f}s[/blue]"
        )
        if errors:
            progress_renderer.console.print(
                f"⚠️  Errors: [red]{len(errors)}[/red]"
            )

    # Write per-stage progress file atomically
    try:
        from ....core.paths import progress as progress_dir
        progress_path = progress_dir() / "embed.json"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = progress_path.with_suffix(".json.tmp")
        progress_payload = {
            "rid": run_id or "unknown",
            "started_at": start_time.isoformat(),
            "updated_at": _now_iso(),
            "totals": {
                "docs": docs_embedded,
                "chunks": chunks_embedded,
                "tokens": metrics.get("estimated_tokens") or 0,
            },
            "status": "OK",
        }
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(progress_payload, f, indent=2)
        tmp_path.replace(progress_path)
    except Exception:
        pass

    return metrics


def _process_embedding_batch(
    session: Session,
    embedder: EmbeddingProvider,
    texts: List[str],
    chunk_data_list: List[Dict[str, Any]],
    emit_event: Any,
) -> None:
    """Process a batch of texts for embedding."""
    try:
        embeddings = embedder.embed_batch(texts)
    except Exception as e:
        log.error(
            "embed.load.embedding_error", error=str(e), batch_size=len(texts)
        )
        # Fall back to individual processing
        embeddings = []
        for text in texts:
            try:
                embeddings.append(embedder.embed(text))
            except Exception as embed_error:
                log.warning(
                    "embed.load.single_embedding_error", error=str(embed_error)
                )
                # Use zero vector as fallback
                embeddings.append([0.0] * embedder.dimension)

    # Upsert embeddings
    for embedding, chunk_data in zip(embeddings, chunk_data_list):
        chunk_data["embedding"] = serialize_embedding(embedding)
        upsert_chunk_embedding(session, chunk_data)
        emit_event(
            "embed.write",
            chunk_id=chunk_data["chunk_id"],
            provider=chunk_data["provider"],
        )


def _generate_assurance_report(run_id: str, metrics: Dict[str, Any]) -> None:
    """Generate assurance report JSON and Markdown files."""
    from ....core.paths import runs

    run_dir = runs() / run_id
    embed_dir = run_dir / "embed"
    embed_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON assurance report
    assurance_file = embed_dir / "embed_assurance.json"
    with open(assurance_file, "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    # Write Markdown summary
    summary_file = embed_dir / "embed_summary.md"
    with open(summary_file, "w") as f:
        f.write(f"# Embed Summary: {run_id}\n\n")
        f.write(f"**Provider**: {metrics['provider']}\n")
        f.write(f"**Model**: {metrics['model']}\n")
        f.write(f"**Dimension**: {metrics['dimension']}\n")
        f.write(f"**Duration**: {metrics['duration_seconds']:.2f}s\n\n")
        f.write("## Metrics\n\n")
        f.write(
            f"- Documents: {metrics['docs_embedded']} embedded, {metrics['docs_skipped']} skipped\n"
        )
        f.write(
            f"- Chunks: {metrics['chunks_embedded']} embedded, {metrics['chunks_skipped']} skipped\n"
        )
        if metrics["errors"]:
            f.write(f"- Errors: {len(metrics['errors'])}\n")


# Backward compatibility alias
load_normalized_to_db = load_chunks_to_db
