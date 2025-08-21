"""Dense retrieval using vector similarity search."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..db.engine import (
    Chunk,
    ChunkEmbedding,
    Document,
    deserialize_embedding,
    get_session_factory,
)
from ..pipeline.steps.embed.provider import get_embedding_provider


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    # Normalize vectors
    a_norm = a / (np.linalg.norm(a) + 1e-8)
    b_norm = b / (np.linalg.norm(b) + 1e-8)

    # Compute dot product
    return float(np.dot(a_norm, b_norm))


def top_k(
    query_vec: np.ndarray,
    candidates: list[tuple[str, str, str, list[float], str, str]],
    k: int,
) -> list[dict[str, Any]]:
    """
    Compute top-k similar chunks with deterministic ordering.

    Args:
        query_vec: Query vector
        candidates: List of (chunk_id, doc_id, text_md, embedding, title, url)
        k: Number of top results to return

    Returns:
        List of dicts with chunk info and scores, ordered by similarity desc
    """
    scored_candidates = []

    for chunk_id, doc_id, text_md, embedding, title, url in candidates:
        candidate_vec = np.array(embedding)
        score = cosine_sim(query_vec, candidate_vec)

        scored_candidates.append(
            {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "text_md": text_md,
                "title": title,
                "url": url,
                "score": float(score),
            }
        )

    # Sort by score desc, then doc_id, then chunk_id for deterministic ordering
    def sort_key(x: dict[str, Any]) -> tuple[float, str, str]:
        return (-x["score"], x["doc_id"], x["chunk_id"])

    scored_candidates.sort(key=sort_key)

    return scored_candidates[:k]


class DenseRetriever:
    """Dense retrieval using vector embeddings."""

    def __init__(
        self,
        db_url: str | None = None,
        provider_name: str = "dummy",
        dim: int | None = None,
    ):
        """
        Initialize dense retriever.

        Args:
            db_url: Database URL (uses default if None)
            provider_name: Embedding provider name
            dim: Embedding dimension (auto-detected if None)
        """
        self.db_url = db_url
        self.provider_name = provider_name
        self.dim = dim
        self._provider = None
        self._session_factory = None

    @property
    def provider(self):
        """Lazy load embedding provider."""
        if self._provider is None:
            self._provider = get_embedding_provider(self.provider_name)
        return self._provider

    @property
    def session_factory(self):
        """Lazy load session factory."""
        if self._session_factory is None:
            if self.db_url:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker

                engine = create_engine(self.db_url, future=True)
                self._session_factory = sessionmaker(bind=engine)
            else:
                self._session_factory = get_session_factory()
        return self._session_factory

    def embed_query(self, text: str) -> np.ndarray:
        """Embed query text using the configured provider."""
        # Normalize text (CRLF -> LF)
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        embedding = self.provider.embed(normalized_text)
        return np.array(embedding)

    def fetch_candidates(
        self,
        provider: str,
        limit: int | None = None,
    ) -> list[tuple[str, str, str, list[float], str, str]]:
        """
        Fetch candidate chunks with embeddings.

        Args:
            provider: Provider name to filter embeddings
            limit: Maximum number of chunks to fetch

        Returns:
            List of (chunk_id, doc_id, text_md, embedding, title, url) tuples
        """
        with self.session_factory() as session:
            query = (
                session.query(
                    Chunk.chunk_id,
                    Chunk.doc_id,
                    Chunk.text_md,
                    ChunkEmbedding.embedding,
                    Document.title,
                    Document.url,
                )
                .join(ChunkEmbedding, Chunk.chunk_id == ChunkEmbedding.chunk_id)
                .join(Document, Chunk.doc_id == Document.doc_id)
                .filter(ChunkEmbedding.provider == provider)
                .order_by(Chunk.doc_id, Chunk.ord)  # Deterministic ordering
            )

            if limit:
                query = query.limit(limit)

            results = query.all()

            # Deserialize embeddings
            candidates = []
            for chunk_id, doc_id, text_md, embedding, title, url in results:
                deserialized_embedding = deserialize_embedding(embedding)
                candidates.append(
                    (
                        chunk_id,
                        doc_id,
                        text_md,
                        deserialized_embedding,
                        title or "",
                        url or "",
                    )
                )

            return candidates

    def search_postgres(
        self,
        query_vec: np.ndarray,
        provider: str,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        """
        Perform search using PostgreSQL + pgvector.

        Args:
            query_vec: Query embedding vector
            provider: Provider name to filter embeddings
            top_k: Number of top results to return

        Returns:
            List of chunk results with scores
        """
        with self.session_factory() as session:
            # Use ORM approach to avoid SQL parameter binding issues
            query = (
                session.query(
                    Chunk.chunk_id,
                    Chunk.doc_id,
                    Chunk.text_md,
                    Document.title,
                    Document.url,
                )
                .join(ChunkEmbedding, Chunk.chunk_id == ChunkEmbedding.chunk_id)
                .join(Document, Chunk.doc_id == Document.doc_id)
                .filter(ChunkEmbedding.provider == provider)
                .limit(top_k * 3)  # Get more candidates for proper ranking
            )

            candidates = []
            for chunk_id, doc_id, text_md, title, url in query.all():
                # Get the embedding for this chunk
                embedding_record = (
                    session.query(ChunkEmbedding)
                    .filter(
                        ChunkEmbedding.chunk_id == chunk_id,
                        ChunkEmbedding.provider == provider,
                    )
                    .first()
                )

                if embedding_record:
                    embedding_vec = np.array(deserialize_embedding(embedding_record.embedding))
                    score = cosine_sim(query_vec, embedding_vec)

                    candidates.append(
                        {
                            "chunk_id": chunk_id,
                            "doc_id": doc_id,
                            "text_md": text_md,
                            "title": title or "",
                            "url": url or "",
                            "score": float(score),
                        }
                    )

            # Sort by score descending, then doc_id, chunk_id for deterministic ordering
            candidates.sort(key=lambda x: (-x["score"], x["doc_id"], x["chunk_id"]))

            return candidates[:top_k]

    def search(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """
        Search for similar chunks using dense retrieval.

        Args:
            query: Query text
            top_k: Number of top results to return

        Returns:
            List of dicts with chunk info and similarity scores
        """
        # Embed the query
        query_vec = self.embed_query(query)

        # Use PostgreSQL + pgvector search (only supported database)
        return self.search_postgres(query_vec, self.provider_name, top_k)


def create_retriever(
    db_url: str | None = None,
    provider_name: str = "dummy",
    dim: int | None = None,
) -> DenseRetriever:
    """
    Factory function to create a DenseRetriever.

    Args:
        db_url: Database URL (uses default if None)
        provider_name: Embedding provider name
        dim: Embedding dimension (auto-detected if None)

    Returns:
        DenseRetriever instance
    """
    return DenseRetriever(db_url=db_url, provider_name=provider_name, dim=dim)
