"""Dense retrieval using pgvector for semantic search."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text

from ....core.logging import log
from ....db.engine import get_session_factory
from ..embed.provider import get_embedding_provider


class SearchHit:
    """A search result hit with metadata."""

    def __init__(
        self,
        chunk_id: str,
        doc_id: str,
        title: str,
        url: str,
        text_md: str,
        score: float,
        source_system: str,
    ):
        self.chunk_id = chunk_id
        self.doc_id = doc_id
        self.title = title
        self.url = url
        self.text_md = text_md
        self.score = score
        self.source_system = source_system

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "url": self.url,
            "text_md": self.text_md,
            "score": self.score,
            "source_system": self.source_system,
        }


class DenseRetriever:
    """Dense retriever using pgvector for semantic search."""

    def __init__(self, db_url: str, provider: str = "dummy"):
        """Initialize the retriever.

        Args:
            db_url: PostgreSQL connection URL
            provider: Embedding provider name (dummy, openai, etc.)
        """
        self.db_url = db_url
        self.provider = provider
        self.embedder = get_embedding_provider(provider)
        self.session_factory = get_session_factory()

    def embed_query(self, query: str) -> List[float]:
        """Embed a query using the same provider as documents.

        Args:
            query: Query text to embed

        Returns:
            Embedding vector as list of floats
        """
        return self.embedder.embed(query)

    def search(
        self,
        query: str,
        top_k: int = 8,
        emit_event: Optional[Callable] = None,
    ) -> List[SearchHit]:
        """Search for relevant chunks using pgvector cosine similarity.

        Args:
            query: Search query
            top_k: Number of results to return
            emit_event: Optional event emitter function

        Returns:
            List of SearchHit objects ordered by relevance
        """
        if emit_event:
            emit_event(
                "search.begin",
                query=query,
                top_k=top_k,
                provider=self.provider,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Embed the query
        query_vector = self.embed_query(query)

        if emit_event:
            emit_event(
                "search.embed",
                query_length=len(query),
                vector_dim=len(query_vector),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Convert vector to string format for PostgreSQL vector type
        vector_str = "[" + ",".join(str(x) for x in query_vector) + "]"

        # SQL query using pgvector cosine similarity (PostgreSQL only)
        sql_query = text(
            """
            SELECT 
                c.chunk_id,
                c.doc_id, 
                d.title,
                d.url,
                c.text_md,
                1 - (ce.embedding::vector <=> :query_vector) as score,
                d.source_system
            FROM chunks c
            JOIN documents d ON c.doc_id = d.doc_id
            JOIN chunk_embeddings ce ON c.chunk_id = ce.chunk_id
            WHERE ce.provider = :provider
            ORDER BY score DESC, c.doc_id ASC, c.chunk_id ASC
            LIMIT :top_k
        """
        )

        hits = []
        with self.session_factory() as session:
            try:
                result = session.execute(
                    sql_query,
                    {
                        "query_vector": vector_str,
                        "provider": self.provider,
                        "top_k": top_k,
                    },
                )

                for row in result:
                    hit = SearchHit(
                        chunk_id=row[0],
                        doc_id=row[1],
                        title=row[2] or "",
                        url=row[3] or "",
                        text_md=row[4],
                        score=float(row[5]),
                        source_system=row[6],
                    )
                    hits.append(hit)

                if emit_event:
                    emit_event(
                        "search.batch",
                        hits_found=len(hits),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )

            except Exception as e:
                log.error("search.error", error=str(e), provider=self.provider)
                if emit_event:
                    emit_event(
                        "search.error",
                        error=str(e),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                raise

        if emit_event:
            emit_event(
                "search.end",
                total_hits=len(hits),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        return hits


def pack_context(
    hits: List[SearchHit],
    max_chars: int = 6000,
    max_chunks_per_doc: Optional[int] = None,
) -> tuple[str, List[SearchHit]]:
    """Pack search hits into context string respecting boundaries.

    Args:
        hits: List of search hits
        max_chars: Maximum character count for context
        max_chunks_per_doc: Maximum chunks per document

    Returns:
        Tuple of (context_string, selected_hits)
    """
    if not hits:
        return "", []

    selected_hits = []
    context_parts: List[str] = []
    current_chars = 0
    docs_seen = set()
    doc_chunk_counts: Dict[str, int] = {}

    for hit in hits:
        # Track chunks per document if limit specified
        if max_chunks_per_doc is not None:
            doc_count = doc_chunk_counts.get(hit.doc_id, 0)
            if doc_count >= max_chunks_per_doc:
                continue
            doc_chunk_counts[hit.doc_id] = doc_count + 1

        # Check if adding this hit would exceed character limit
        hit_text = hit.text_md

        # Add media placeholder if this is the first chunk from this document
        # and the text contains media references
        if hit.doc_id not in docs_seen and "![media:" in hit_text:
            # Find first media placeholder
            import re

            media_match = re.search(r"!\[media: ([^\]]+)\]", hit_text)
            if media_match:
                hit_text = f"![media: {media_match.group(1)}]\n\n{hit_text}"

        docs_seen.add(hit.doc_id)

        # Format the hit with metadata
        hit_formatted = f"**Document:** {hit.title or hit.doc_id}\n"
        hit_formatted += f"**Source:** {hit.source_system}\n"
        if hit.url:
            hit_formatted += f"**URL:** {hit.url}\n"
        hit_formatted += f"**Score:** {hit.score:.4f}\n\n"
        hit_formatted += hit_text + "\n\n---\n\n"

        # Check if we can fit this hit
        if current_chars + len(hit_formatted) > max_chars and context_parts:
            break

        # Never split code blocks - if we're in the middle of a code block, skip
        if "```" in hit_text:
            # Count code block markers to see if we're inside one
            open_blocks = hit_text.count("```") % 2
            if open_blocks != 0:
                # We're ending in an open code block, don't split here
                continue

        context_parts.append(hit_formatted)
        selected_hits.append(hit)
        current_chars += len(hit_formatted)

    context_str = "".join(context_parts)
    return context_str, selected_hits
