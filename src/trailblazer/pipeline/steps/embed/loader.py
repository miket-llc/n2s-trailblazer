from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ....core.artifacts import ROOT
from ....core.logging import log
from ....db.engine import (  # type: ignore[import-untyped]
    get_session_factory,
    serialize_embedding,
    upsert_chunk,
    upsert_chunk_embedding,
    upsert_document,
)
from .chunker import chunk_normalized_record
from .provider import EmbeddingProvider, get_embedding_provider


def _default_normalized_path(run_id: str) -> Path:
    """Get default path to normalized.ndjson for a run."""
    return ROOT / "runs" / run_id / "normalize" / "normalized.ndjson"


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_normalized_to_db(
    run_id: Optional[str] = None,
    input_file: Optional[str] = None,
    provider_name: str = "dummy",
    batch_size: int = 128,
    max_docs: Optional[int] = None,
    max_chunks: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Load normalized documents into the database with embeddings.

    Args:
        run_id: Run ID to load (uses runs/<RUN_ID>/normalize/normalized.ndjson)
        input_file: Input NDJSON file to load (overrides run_id)
        provider_name: Embedding provider to use
        batch_size: Batch size for embedding generation
        max_docs: Maximum number of documents to process
        max_chunks: Maximum number of chunks to process

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

    # Get embedding provider
    embedder = get_embedding_provider(provider_name)

    # Initialize session
    session_factory = get_session_factory()

    # Metrics
    docs_processed = 0
    docs_upserted = 0
    chunks_processed = 0
    chunks_upserted = 0
    embeddings_processed = 0
    embeddings_upserted = 0

    start_time = datetime.now(timezone.utc)

    log.info(
        "embed.load.start",
        run_id=run_id,
        input_file=str(input_path),
        provider=embedder.provider_name,
        dimension=embedder.dimension,
        batch_size=batch_size,
        max_docs=max_docs,
        max_chunks=max_chunks,
    )

    with session_factory() as session:
        # Process documents in batches
        batch_texts = []
        batch_chunk_data = []

        with input_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    log.warning(
                        "embed.load.invalid_json", line=line_num, error=str(e)
                    )
                    continue

                # Skip if no ID
                doc_id = record.get("id")
                if not doc_id:
                    log.warning("embed.load.missing_doc_id", line=line_num)
                    continue

                # Upsert document
                doc_data = {
                    "doc_id": doc_id,
                    "source": record.get("source", "confluence"),
                    "title": record.get("title"),
                    "space_key": record.get("space_key"),
                    "url": record.get("url"),
                    "created_at": _parse_timestamp(record.get("created_at")),
                    "updated_at": _parse_timestamp(record.get("updated_at")),
                    "body_repr": record.get("body_repr"),
                    "meta": {
                        "version": record.get("version"),
                        "space_id": record.get("space_id"),
                        "links": record.get("links", []),
                        "attachments": record.get("attachments", []),
                    },
                }

                doc = upsert_document(session, doc_data)
                docs_processed += 1
                if session.is_modified(doc):
                    docs_upserted += 1

                # Generate chunks
                try:
                    chunks = chunk_normalized_record(record)
                except Exception as e:
                    log.warning(
                        "embed.load.chunk_error",
                        doc_id=record.get("id"),
                        error=str(e),
                    )
                    continue

                # Process chunks
                for chunk in chunks:
                    if max_chunks and chunks_processed >= max_chunks:
                        break

                    # Upsert chunk
                    chunk_data = {
                        "chunk_id": chunk.chunk_id,
                        "doc_id": chunk.chunk_id.split(":")[
                            0
                        ],  # Extract doc_id from chunk_id
                        "ord": chunk.ord,
                        "text_md": chunk.text_md,
                        "char_count": chunk.char_count,
                        "token_count": chunk.token_count,
                    }

                    chunk_obj = upsert_chunk(session, chunk_data)
                    chunks_processed += 1
                    if session.is_modified(chunk_obj):
                        chunks_upserted += 1

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

                    # Process batch when full
                    if len(batch_texts) >= batch_size:
                        _process_embedding_batch(
                            session, embedder, batch_texts, batch_chunk_data
                        )
                        embeddings_processed += len(batch_texts)
                        embeddings_upserted += len(
                            batch_texts
                        )  # Simplified for now
                        batch_texts.clear()
                        batch_chunk_data.clear()

                    if max_chunks and chunks_processed >= max_chunks:
                        break

                if max_docs and docs_processed >= max_docs:
                    break

        # Process remaining batch
        if batch_texts:
            _process_embedding_batch(
                session, embedder, batch_texts, batch_chunk_data
            )
            embeddings_processed += len(batch_texts)
            embeddings_upserted += len(batch_texts)

        # Commit all changes
        session.commit()

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    metrics = {
        "run_id": run_id,
        "input_file": str(input_path),
        "provider": embedder.provider_name,
        "dimension": embedder.dimension,
        "docs_processed": docs_processed,
        "docs_upserted": docs_upserted,
        "chunks_processed": chunks_processed,
        "chunks_upserted": chunks_upserted,
        "embeddings_processed": embeddings_processed,
        "embeddings_upserted": embeddings_upserted,
        "duration_seconds": duration,
        "completed_at": _now_iso(),
    }

    log.info("embed.load.done", **metrics)
    return metrics


def _process_embedding_batch(
    session: Session,
    embedder: EmbeddingProvider,
    texts: List[str],
    chunk_data_list: List[Dict[str, Any]],
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
