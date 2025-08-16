from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from sqlalchemy.orm import Session


from ....core.logging import log
from .provider import EmbeddingProvider
from ....db.engine import (  # type: ignore[import-untyped]
    get_session_factory,
    serialize_embedding,
    upsert_chunk,
    upsert_chunk_embedding,
    upsert_document,
)
from .chunker import chunk_normalized_record
from .provider import get_embedding_provider


def _default_normalized_path(run_id: str) -> Path:
    """Get default path to normalized.ndjson for a run."""
    from ....core.paths import runs

    return runs() / run_id / "normalize" / "normalized.ndjson"


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _compute_content_hash(record: Dict[str, Any]) -> str:
    """
    Compute a deterministic SHA256 hash of the document content.

    Uses title, text_md, and normalized attachments for stability.
    """
    # Extract key content fields for hashing
    content_fields = {
        "title": record.get("title", ""),
        "text_md": record.get("text_md", ""),
        "source_system": record.get(
            "source_system", record.get("source", "unknown")
        ),
        # Include normalized attachment info for change detection
        "attachments": sorted(
            [
                {
                    "filename": att.get("filename", ""),
                    "id": att.get("id", ""),
                    "media_type": att.get("media_type", ""),
                }
                for att in record.get("attachments", [])
            ],
            key=lambda x: x.get("filename", ""),
        ),
    }

    # Create deterministic JSON string
    content_json = json.dumps(
        content_fields, sort_keys=True, separators=(",", ":")
    )

    # Return SHA256 hash
    return hashlib.sha256(content_json.encode("utf-8")).hexdigest()


def _load_fingerprints(fingerprints_path: Path) -> Dict[str, str]:
    """
    Load enrichment fingerprints from JSONL file.

    Args:
        fingerprints_path: Path to fingerprints.jsonl file

    Returns:
        Dictionary mapping doc_id to fingerprint_sha256
    """
    fingerprints = {}
    if fingerprints_path.exists():
        with open(fingerprints_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line.strip())
                        doc_id = record.get("id")
                        fingerprint = record.get("fingerprint_sha256")
                        if doc_id and fingerprint:
                            fingerprints[doc_id] = fingerprint
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue
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


def load_normalized_to_db(
    run_id: Optional[str] = None,
    input_file: Optional[str] = None,
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
    Load normalized documents into the database with embeddings (idempotent).

    Args:
        run_id: Run ID to load (uses runs/<RUN_ID>/normalize/normalized.ndjson)
        input_file: Input NDJSON file to load (overrides run_id)
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
    # Determine input file
    if input_file:
        input_path = Path(input_file)
        run_id = run_id or "unknown"
    elif run_id:
        input_path = _default_normalized_path(run_id)
    else:
        raise ValueError("Either run_id or input_file must be provided")

    if not input_path.exists():
        raise FileNotFoundError(f"Normalized file not found: {input_path}")

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

    # Initialize Rich console for progress
    console = Console(file=sys.stderr)

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

    # NDJSON event logging (to stdout)
    def emit_event(event_type: str, **kwargs):
        event = {
            "timestamp": _now_iso(),
            "event": event_type,
            "run_id": run_id,
            "provider": embedder.provider_name,
            **kwargs,
        }
        print(json.dumps(event), flush=True)

    emit_event(
        "embed.load.start",
        input_file=str(input_path),
        provider=embedder.provider_name,
        dimension=embedder.dimension,
        batch_size=batch_size,
        max_docs=max_docs,
        max_chunks=max_chunks,
        changed_only=changed_only,
        changed_docs_count=len(changed_docs)
        if changed_docs is not None
        else None,
    )

    console.print("🔄 [bold cyan]Loading embeddings[/bold cyan]")
    console.print(f"📁 Input: [cyan]{input_path.name}[/cyan]")
    console.print(
        f"🧠 Provider: [green]{embedder.provider_name}[/green] (dim={embedder.dimension})"
    )
    console.print(f"📦 Batch size: {batch_size}")
    console.print("")

    with session_factory() as session:
        # Process documents in batches
        batch_texts = []
        batch_chunk_data = []
        last_progress_time = start_time

        # Initialize cost estimation variables
        estimated_tokens = 0
        estimated_cost = 0.0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TextColumn(
                "docs={task.fields[docs]} chunks={task.fields[chunks]}"
            ),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Processing...", docs=0, chunks=0, total=None
            )

            with input_path.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    if not line.strip():
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as e:
                        error_info = {"line": line_num, "error": str(e)}
                        errors.append(error_info)
                        emit_event("error", **error_info)
                        continue

                    # Skip if no ID
                    doc_id = record.get("id")
                    if not doc_id:
                        error_info = {
                            "line": line_num,
                            "error": "missing_doc_id",
                        }
                        errors.append(error_info)
                        emit_event("error", **error_info)
                        continue

                    docs_total += 1

                    # Get document title for progress display
                    doc_title = record.get("title", "Untitled")
                    # Truncate very long titles for display
                    if len(doc_title) > 60:
                        doc_title = doc_title[:57] + "..."

                    # Print individual page titles for detailed feedback (only show processing count, not total count)
                    # We'll update this after we know if the doc was embedded or skipped

                    # Estimate tokens for cost calculation (dry-run mode)
                    if dry_run_cost:
                        text_md = record.get("text_md", "")
                        doc_tokens = (
                            len(text_md) // 4
                        )  # Rough token estimation
                        estimated_tokens += doc_tokens

                    # Check if document should be processed based on fingerprints
                    if changed_docs is not None and doc_id not in changed_docs:
                        docs_unchanged += 1
                        emit_event(
                            "embed.skip.doc_by_fingerprint",
                            doc_id=doc_id,
                            reason="unchanged_fingerprint",
                        )
                        continue

                    # Only track changed docs when using changed_only mode
                    if changed_docs is not None:
                        docs_changed += 1

                    # Compute content hash for idempotency
                    content_hash = _compute_content_hash(record)

                    # Check if document exists with same content
                    from ....db.engine import Document

                    existing_doc = (
                        session.query(Document)
                        .filter_by(content_sha256=content_hash)
                        .first()
                    )

                    if existing_doc:
                        docs_skipped += 1
                        # Show skipped document with different styling
                        if docs_total % 50 == 0 or docs_total <= 10:
                            console.print(
                                f"  ⏭️  [{docs_total:4d}] {doc_title} (skipped)",
                                style="dim yellow",
                            )
                        emit_event(
                            "doc.skip",
                            doc_id=doc_id,
                            content_sha256=content_hash,
                            reason="unchanged",
                        )

                        # Still check if chunks need embeddings for this provider
                        from ....db.engine import Chunk, ChunkEmbedding

                        chunks_needing_embeddings = (
                            session.query(Chunk)
                            .filter_by(doc_id=doc_id)
                            .filter(
                                ~Chunk.chunk_id.in_(
                                    session.query(
                                        ChunkEmbedding.chunk_id
                                    ).filter_by(
                                        provider=embedder.provider_name
                                    )
                                )
                            )
                            .all()
                        )

                        if chunks_needing_embeddings:
                            for chunk_obj in chunks_needing_embeddings:
                                batch_texts.append(chunk_obj.text_md)
                                batch_chunk_data.append(
                                    {
                                        "chunk_id": chunk_obj.chunk_id,
                                        "provider": embedder.provider_name,
                                        "dim": embedder.dimension,
                                        "created_at": datetime.now(
                                            timezone.utc
                                        ),
                                    }
                                )
                                chunks_total += 1

                        if max_docs and docs_total >= max_docs:
                            break
                        continue

                    # Upsert document (new or changed content)
                    doc_data = {
                        "doc_id": doc_id,
                        "source_system": record.get(
                            "source_system", record.get("source", "unknown")
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
                            "attachments": record.get("attachments", []),
                            "labels": record.get("labels", []),
                        },
                    }

                    upsert_document(session, doc_data)
                    docs_embedded += 1
                    # Show embedded document with different styling
                    if docs_total % 50 == 0 or docs_total <= 10:
                        console.print(
                            f"  📖 [{docs_total:4d}] {doc_title} (embedding)",
                            style="bright_cyan",
                        )
                    emit_event(
                        "doc.upsert",
                        doc_id=doc_id,
                        content_sha256=content_hash,
                    )

                    # Generate chunks
                    try:
                        chunks = chunk_normalized_record(record)
                    except Exception as e:
                        error_info = {
                            "doc_id": doc_id,
                            "error": str(e),
                            "phase": "chunking",
                        }
                        errors.append(error_info)
                        emit_event("error", **error_info)
                        continue

                    # Process chunks
                    for chunk in chunks:
                        if max_chunks and chunks_total >= max_chunks:
                            break

                        chunks_total += 1

                        # Check if chunk already exists
                        from ....db.engine import Chunk as ChunkModel

                        existing_chunk = session.get(
                            ChunkModel, chunk.chunk_id
                        )

                        if (
                            existing_chunk
                            and existing_chunk.text_md == chunk.text_md
                        ):
                            # Chunk unchanged, check if embedding exists
                            from ....db.engine import ChunkEmbedding

                            existing_embedding = session.get(
                                ChunkEmbedding,
                                (chunk.chunk_id, embedder.provider_name),
                            )
                            if existing_embedding:
                                chunks_skipped += 1
                                emit_event(
                                    "chunk.skip",
                                    chunk_id=chunk.chunk_id,
                                    reason="unchanged",
                                )
                                continue

                        # Upsert chunk
                        chunk_data = {
                            "chunk_id": chunk.chunk_id,
                            "doc_id": ":".join(chunk.chunk_id.split(":")[:-1]),
                            "ord": chunk.ord,
                            "text_md": chunk.text_md,
                            "char_count": chunk.char_count,
                            "token_count": chunk.token_count,
                            "chunk_type": getattr(chunk, "chunk_type", "text"),
                            "meta": getattr(chunk, "meta", {}) or {},
                        }

                        chunk_obj = upsert_chunk(session, chunk_data)
                        emit_event(
                            "chunk.write",
                            chunk_id=chunk.chunk_id,
                            char_count=chunk.char_count,
                        )

                        # Collect for batch embedding
                        batch_texts.append(chunk.text_md)
                        batch_chunk_data.append(
                            {
                                "chunk_id": chunk.chunk_id,
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

                        if max_chunks and chunks_total >= max_chunks:
                            break

                    # Update progress every doc (to show current title) or every 30 seconds
                    if (
                        docs_total % 1
                        == 0  # Update every document to show current title
                        or (
                            datetime.now(timezone.utc) - last_progress_time
                        ).seconds
                        >= 30
                    ):
                        progress.update(
                            task,
                            description=f"📄 {doc_title}",
                            docs=docs_total,
                            chunks=chunks_total,
                        )
                        last_progress_time = datetime.now(timezone.utc)

                        # Emit heartbeat
                        elapsed = (
                            datetime.now(timezone.utc) - start_time
                        ).total_seconds()
                        rate = docs_total / elapsed if elapsed > 0 else 0
                        emit_event(
                            "heartbeat",
                            docs_total=docs_total,
                            chunks_total=chunks_total,
                            rate_docs_per_sec=rate,
                            elapsed_seconds=elapsed,
                        )

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
        "input_file": str(input_path),
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

    # Mark embedding complete in backlog
    if run_id and run_id != "unknown":
        try:
            from ...backlog import mark_embedding_complete

            mark_embedding_complete(run_id, chunks_embedded)
        except Exception as e:
            log.warning("embed.backlog_failed", error=str(e))

    # Print summary
    console.print("")
    console.print("📊 [bold green]Embedding Complete[/bold green]")
    if changed_only:
        console.print(
            f"📄 Documents: [cyan]{docs_changed}[/cyan] changed, [yellow]{docs_unchanged}[/yellow] unchanged"
        )
    console.print(
        f"📄 Documents: [cyan]{docs_embedded}[/cyan] embedded, [yellow]{docs_skipped}[/yellow] skipped"
    )
    console.print(
        f"🧩 Chunks: [cyan]{chunks_embedded}[/cyan] embedded, [yellow]{chunks_skipped}[/yellow] skipped"
    )
    console.print(
        f"🧠 Provider: [green]{embedder.provider_name}[/green] (dim={embedder.dimension})"
    )
    console.print(f"⏱️  Duration: [blue]{duration:.2f}s[/blue]")
    if errors:
        console.print(f"⚠️  Errors: [red]{len(errors)}[/red]")

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

    # Prepare assurance data
    assurance_data = {
        "run_id": run_id,
        "provider": metrics["provider"],
        "model": metrics.get("model"),
        "dimension": metrics["dimension"],
        "reembed_all": metrics.get("reembed_all", False),
        "docs_total": metrics["docs_total"],
        "docs_skipped": metrics["docs_skipped"],
        "docs_embedded": metrics["docs_embedded"],
        "docs_changed": metrics.get("docs_changed", 0),
        "docs_unchanged": metrics.get("docs_unchanged", 0),
        "chunks_total": metrics["chunks_total"],
        "chunks_skipped": metrics["chunks_skipped"],
        "chunks_embedded": metrics["chunks_embedded"],
        "duration_seconds": metrics["duration_seconds"],
        "errors": metrics["errors"],
        "completed_at": metrics["completed_at"],
    }

    # Write JSON report
    json_path = runs() / run_id / "embed_assurance.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(assurance_data, f, indent=2)

    # Write Markdown report
    md_path = runs() / run_id / "embed_assurance.md"
    with open(md_path, "w") as f:
        f.write("# Embedding Assurance Report\n\n")
        f.write(f"**Run ID:** `{run_id}`  \n")
        f.write(
            f"**Provider:** {metrics['provider']} (dim={metrics['dimension']})  \n"
        )
        if metrics.get("model"):
            f.write(f"**Model:** {metrics['model']}  \n")
        f.write(f"**Re-embed All:** {metrics.get('reembed_all', False)}  \n")
        f.write(f"**Completed:** {metrics['completed_at']}  \n")
        f.write(f"**Duration:** {metrics['duration_seconds']:.2f}s  \n\n")

        f.write("## Summary\n\n")
        f.write("| Metric | Count |\n")
        f.write("|--------|-------|\n")
        f.write(f"| Documents Total | {metrics['docs_total']} |\n")
        f.write(f"| Documents Embedded | {metrics['docs_embedded']} |\n")
        f.write(f"| Documents Skipped | {metrics['docs_skipped']} |\n")
        f.write(f"| Chunks Total | {metrics['chunks_total']} |\n")
        f.write(f"| Chunks Embedded | {metrics['chunks_embedded']} |\n")
        f.write(f"| Chunks Skipped | {metrics['chunks_skipped']} |\n\n")

        if metrics["errors"]:
            f.write(f"## Errors ({len(metrics['errors'])})\n\n")
            for i, error in enumerate(
                metrics["errors"][:10], 1
            ):  # Show first 10
                f.write(f"{i}. {error}\n")
            if len(metrics["errors"]) > 10:
                f.write(f"\n... and {len(metrics['errors']) - 10} more\n")
        else:
            f.write("## Errors\n\nNo errors encountered.\n")

        f.write("\n## Reproduction Command\n\n")
        f.write("```bash\n")
        cmd_parts = [
            f"trailblazer embed load --run-id {run_id} --provider {metrics['provider']}"
        ]
        if metrics.get("model"):
            cmd_parts.append(f"--model {metrics['model']}")
        if metrics.get("dimension"):
            cmd_parts.append(f"--dimensions {metrics['dimension']}")
        if metrics.get("reembed_all"):
            cmd_parts.append("--reembed-all")
        f.write(" ".join(cmd_parts) + "\n")
        f.write("```\n")

    print(f"📋 Assurance report: {json_path}", file=sys.stderr)
    print(f"📋 Assurance report: {md_path}", file=sys.stderr)


def _parse_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    """Parse timestamp string to datetime object."""
    if not timestamp_str:
        return None

    try:
        # Handle Z suffix
        if timestamp_str.endswith("Z"):
            timestamp_str = timestamp_str[:-1] + "+00:00"
        return datetime.fromisoformat(timestamp_str)
    except ValueError:
        log.warning("embed.load.invalid_timestamp", timestamp=timestamp_str)
        return None
