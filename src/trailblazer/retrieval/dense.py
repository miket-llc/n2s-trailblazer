"""Dense retrieval using vector similarity search."""

from __future__ import annotations

import json
import re
from pathlib import Path
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


def is_n2s_query(query: str) -> bool:
    """
    Detect if a query is N2S-related based on key terms.

    Args:
        query: Raw query text

    Returns:
        True if query contains N2S-related terms
    """
    n2s_patterns = [
        r"\bn2s\b",
        r"\bnavigate\s+to\s+saas\b",
        r"\bnavigate-to-saas\b",
        r"\blifecycle\b",
        r"\bmethodology\b",
        r"\bsprint\s+0\b",
        r"\bsprint\s+zero\b",
        r"\bdiscovery\b",
        r"\bbuild\b",
        r"\boptimize\b",
    ]

    query_lower = query.lower()
    return any(re.search(pattern, query_lower) for pattern in n2s_patterns)


def expand_n2s_query(query: str) -> str:
    """
    Expand N2S query with synonyms and related terms for BM25.

    Args:
        query: Original query text

    Returns:
        Expanded query with synonyms and phase terms
    """
    if not is_n2s_query(query):
        return query

    # N2S synonyms
    synonyms = ["N2S", "Navigate to SaaS", "Navigate-to-SaaS", "N-2-S"]

    # Phase and stage terms
    phases = ["Discovery", "Build", "Optimize"]
    stages = [
        "Start",
        "Prepare",
        "Sprint 0",
        "Plan",
        "Configure",
        "Test",
        "Deploy",
        "Go-Live",
        "Post Go-Live",
    ]

    # Governance terms
    governance = ["governance checkpoints", "entry criteria", "exit criteria"]

    # Concept terms (placeholder for future phrase matching enhancement)
    # concepts = [
    #     "capability-driven iterations",
    #     "cross-cutting",
    #     "Testing & QA",
    #     "Data Migration",
    #     "Integration",
    #     "Reporting & Analytics",
    #     "Org Readiness",
    # ]

    # Build expanded query
    expansion_terms = []

    # Add synonyms if query mentions N2S
    if re.search(r"\bn2s\b|\bnavigate.+saas\b", query.lower()):
        expansion_terms.extend(synonyms[:2])  # Add top 2 synonyms

    # Add methodology terms if lifecycle/methodology mentioned
    if re.search(r"\blifecycle\b|\bmethodology\b", query.lower()):
        expansion_terms.extend(phases)
        expansion_terms.extend(stages[:4])  # Add key stages

    # Add governance if governance-related
    if re.search(r"\bgovernance\b|\bcriteria\b|\bcheckpoint\b", query.lower()):
        expansion_terms.extend(governance)

    if expansion_terms:
        # Join with OR for BM25 expansion
        expanded = f"{query} OR " + " OR ".join(f'"{term}"' for term in expansion_terms)
        return expanded

    return query


def apply_domain_boosts(
    candidates: list[dict[str, Any]],
    enable_boosts: bool = True,
) -> list[dict[str, Any]]:
    """
    Apply domain-aware boosts to candidates.

    Args:
        candidates: List of candidate results with title, score, etc.
        enable_boosts: Whether to apply boosts

    Returns:
        Candidates with boosted scores
    """
    if not enable_boosts:
        return candidates

    boosted = []
    for candidate in candidates:
        title = candidate.get("title", "").lower()
        score = candidate.get("score", 0.0)

        # Apply boosts based on document type
        boost = 0.0
        if "methodology" in title:
            boost = 0.20
        elif "playbook" in title:
            boost = 0.15
        elif "runbook" in title:
            boost = 0.10

        # Apply negative boost for monthly pages
        if re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
            title,
        ) or re.search(r"\b(20\d{2})\b", title):  # Year patterns
            boost -= 0.10

        # Apply boost
        final_score = score + boost

        candidate_copy = candidate.copy()
        candidate_copy["score"] = final_score
        candidate_copy["boost_applied"] = boost
        boosted.append(candidate_copy)

    return boosted


def reciprocal_rank_fusion(
    dense_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """
    Combine dense and BM25 results using Reciprocal Rank Fusion.

    Args:
        dense_results: Results from dense retrieval (with scores)
        bm25_results: Results from BM25 retrieval (with scores)
        k: RRF parameter (typically 60)

    Returns:
        Fused results with RRF scores
    """
    # Create rank maps
    dense_ranks = {r["chunk_id"]: i + 1 for i, r in enumerate(dense_results)}
    bm25_ranks = {r["chunk_id"]: i + 1 for i, r in enumerate(bm25_results)}

    # Get all unique chunk IDs
    all_chunk_ids = set(dense_ranks.keys()) | set(bm25_ranks.keys())

    # Create result map for metadata lookup
    result_map = {}
    for r in dense_results:
        result_map[r["chunk_id"]] = r
    for r in bm25_results:
        if r["chunk_id"] not in result_map:
            result_map[r["chunk_id"]] = r

    # Calculate RRF scores
    fused_results = []
    for chunk_id in all_chunk_ids:
        rrf_score = 0.0

        # Add dense contribution
        if chunk_id in dense_ranks:
            rrf_score += 1.0 / (k + dense_ranks[chunk_id])

        # Add BM25 contribution
        if chunk_id in bm25_ranks:
            rrf_score += 1.0 / (k + bm25_ranks[chunk_id])

        # Get result metadata
        result = result_map[chunk_id].copy()
        result["rrf_score"] = rrf_score
        result["dense_rank"] = dense_ranks.get(chunk_id, None)
        result["bm25_rank"] = bm25_ranks.get(chunk_id, None)

        fused_results.append(result)

    # Sort by RRF score descending, then by chunk_id for deterministic ordering
    fused_results.sort(key=lambda x: (-x["rrf_score"], x["chunk_id"]))

    return fused_results


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
    """Dense retrieval using vector embeddings with hybrid BM25 support."""

    def __init__(
        self,
        db_url: str | None = None,
        provider_name: str = "dummy",
        dim: int | None = None,
        enable_bm25_fallback: bool = True,
        enable_hybrid: bool = True,
        topk_dense: int = 200,
        topk_bm25: int = 200,
        rrf_k: int = 60,
        enable_boosts: bool = True,
        enable_n2s_filter: bool = True,
        server_side: bool = False,
    ):
        """
        Initialize dense retriever.

        Args:
            db_url: Database URL (uses default if None)
            provider_name: Embedding provider name
            dim: Embedding dimension (auto-detected if None)
            enable_bm25_fallback: Enable BM25 full-text fallback when embeddings return 0 results
            enable_hybrid: Enable hybrid retrieval (dense + BM25 with RRF)
            topk_dense: Top-k for dense retrieval in hybrid mode
            topk_bm25: Top-k for BM25 retrieval in hybrid mode
            rrf_k: RRF parameter k (typically 60)
            enable_boosts: Enable domain-aware boosts
            enable_n2s_filter: Enable N2S query detection and filtering
            server_side: Use server-side RRF SQL function
        """
        self.db_url = db_url
        self.provider_name = provider_name
        self.dim = dim
        self.enable_bm25_fallback = enable_bm25_fallback
        self.enable_hybrid = enable_hybrid
        self.topk_dense = topk_dense
        self.topk_bm25 = topk_bm25
        self.rrf_k = rrf_k
        self.enable_boosts = enable_boosts
        self.enable_n2s_filter = enable_n2s_filter
        self.server_side = server_side
        self._provider = None
        self._session_factory = None
        self._bm25_index_created = False

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
        space_whitelist: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Perform search using PostgreSQL + pgvector.

        Args:
            query_vec: Query embedding vector
            provider: Provider name to filter embeddings
            top_k: Number of top results to return
            space_whitelist: Optional list of space keys to filter documents

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
                .filter(ChunkEmbedding.dim == 1536)  # Ensure dimension=1536 filter
            )

            # Add space whitelist filter if provided
            if space_whitelist:
                query = query.filter(Document.space_key.in_(space_whitelist))

            query = query.limit(top_k * 3)  # Get more candidates for proper ranking

            candidates = []
            for chunk_id, doc_id, text_md, title, url in query.all():
                # Get the embedding for this chunk
                embedding_record = (
                    session.query(ChunkEmbedding)
                    .filter(
                        ChunkEmbedding.chunk_id == chunk_id,
                        ChunkEmbedding.provider == provider,
                        ChunkEmbedding.dim == 1536,  # Ensure dimension=1536 filter
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

    def _ensure_bm25_index(self) -> None:
        """Ensure BM25 index exists for full-text search."""
        if self._bm25_index_created:
            return

        with self.session_factory() as session:
            try:
                from sqlalchemy import text

                # Create GIN index on tsvector for proper BM25
                session.execute(
                    text(
                        """
                    CREATE INDEX IF NOT EXISTS idx_chunks_content_tsvector
                    ON chunks USING GIN (to_tsvector('english', text_md))
                """
                    )
                )

                # Also keep trigram index for fallback compatibility
                session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                session.execute(
                    text(
                        """
                    CREATE INDEX IF NOT EXISTS idx_chunks_content_gin
                    ON chunks USING GIN (text_md gin_trgm_ops)
                """
                    )
                )

                session.commit()
                self._bm25_index_created = True
            except Exception as e:
                # Index creation failed, but continue - BM25 will be disabled
                print(f"Warning: Could not create BM25 index: {e}")
                self.enable_bm25_fallback = False

    def search_bm25(
        self,
        query: str,
        top_k: int = 200,
        space_whitelist: list[str] | None = None,
        n2s_filter: bool = False,
        expand_query: bool = True,
    ) -> list[dict[str, Any]]:
        """
        BM25 full-text search using PostgreSQL tsvector.

        Args:
            query: Search query
            top_k: Number of top results to return
            space_whitelist: Optional list of space keys to filter documents
            n2s_filter: Filter to N2S-related documents
            expand_query: Whether to expand N2S queries

        Returns:
            List of chunk results with BM25 scores
        """
        self._ensure_bm25_index()

        # Apply query expansion if enabled
        final_query = expand_n2s_query(query) if expand_query else query

        with self.session_factory() as session:
            from sqlalchemy import text

            # Build BM25 query using ts_rank_cd for better ranking
            sql_query = """
                SELECT
                    c.chunk_id,
                    c.doc_id,
                    c.text_md,
                    d.title,
                    d.url,
                    d.source_system,
                    d.meta,
                    ts_rank_cd(to_tsvector('english', c.text_md), plainto_tsquery('english', :query)) as score
                FROM chunks c
                JOIN documents d ON c.doc_id = d.doc_id
                WHERE to_tsvector('english', c.text_md) @@ plainto_tsquery('english', :query)
            """

            params = {"query": final_query}

            # Add N2S filter if requested
            if n2s_filter:
                sql_query += """
                    AND (d.title ILIKE '%N2S%'
                         OR d.title ILIKE '%Navigate to SaaS%'
                         OR d.title ILIKE '%Methodology%'
                         OR d.title ILIKE '%Playbook%'
                         OR d.title ILIKE '%Runbook%'
                         OR d.meta::text ILIKE '%doctype%methodology%'
                         OR d.meta::text ILIKE '%doctype%playbook%'
                         OR d.meta::text ILIKE '%doctype%runbook%')
                """

            # Add space whitelist filter if provided
            if space_whitelist:
                placeholders = ",".join([f":space_{i}" for i in range(len(space_whitelist))])
                sql_query += f" AND d.space_key IN ({placeholders})"
                for i, space_key in enumerate(space_whitelist):
                    params[f"space_{i}"] = space_key

            # Add ordering and limit
            sql_query += """
                ORDER BY score DESC, d.doc_id ASC, c.chunk_id ASC
                LIMIT :top_k
            """
            params["top_k"] = top_k

            try:
                result = session.execute(text(sql_query), params)

                candidates = []
                for row in result:
                    candidates.append(
                        {
                            "chunk_id": row[0],
                            "doc_id": row[1],
                            "text_md": row[2],
                            "title": row[3] or "",
                            "url": row[4] or "",
                            "source_system": row[5],
                            "meta": row[6],
                            "score": float(row[7]),
                            "search_type": "bm25",
                        }
                    )

                return candidates

            except Exception as e:
                print(f"Warning: BM25 search failed: {e}")
                return []

    def search_bm25_fallback(
        self,
        query: str,
        top_k: int = 8,
        space_whitelist: list[str] | None = None,
        n2s_filter: bool = True,
    ) -> list[dict[str, Any]]:
        """
        BM25-like full-text search fallback using PostgreSQL trigram similarity.

        Args:
            query: Search query
            top_k: Number of top results to return
            space_whitelist: Optional list of space keys to filter documents
            n2s_filter: Filter to N2S-related documents

        Returns:
            List of chunk results with similarity scores
        """
        if not self.enable_bm25_fallback:
            return []

        self._ensure_bm25_index()

        with self.session_factory() as session:
            from sqlalchemy import text

            # Build the SQL query using trigram similarity
            sql_query = """
                SELECT
                    c.chunk_id,
                    c.doc_id,
                    c.text_md,
                    d.title,
                    d.url,
                    similarity(c.text_md, :query) as score,
                    d.source_system
                FROM chunks c
                JOIN documents d ON c.doc_id = d.doc_id
                WHERE 1=1
            """

            params = {"query": query}

            # Add N2S filter if requested
            if n2s_filter:
                sql_query += """
                    AND (d.title ILIKE '%N2S%'
                         OR d.title ILIKE '%Navigate to SaaS%'
                         OR d.title ILIKE '%Methodology%'
                         OR d.title ILIKE '%Playbook%'
                         OR d.title ILIKE '%Governance%')
                """

            # Add space whitelist filter if provided
            if space_whitelist:
                placeholders = ",".join([f":space_{i}" for i in range(len(space_whitelist))])
                sql_query += f" AND d.space_key IN ({placeholders})"
                for i, space_key in enumerate(space_whitelist):
                    params[f"space_{i}"] = space_key

            # Add similarity threshold and ordering
            sql_query += """
                AND similarity(c.text_md, :query) > 0.1
                ORDER BY score DESC, d.doc_id ASC, c.chunk_id ASC
                LIMIT :top_k
            """
            params["top_k"] = top_k

            try:
                result = session.execute(text(sql_query), params)

                candidates = []
                for row in result:
                    candidates.append(
                        {
                            "chunk_id": row[0],
                            "doc_id": row[1],
                            "text_md": row[2],
                            "title": row[3] or "",
                            "url": row[4] or "",
                            "score": float(row[5]),
                            "source_system": row[6],
                            "fallback": "bm25",  # Mark as fallback result
                        }
                    )

                return candidates

            except Exception as e:
                print(f"Warning: BM25 fallback search failed: {e}")
                return []

    def search(
        self,
        query: str,
        top_k: int = 8,
        space_whitelist: list[str] | None = None,
        export_trace_dir: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar chunks using hybrid retrieval or dense with BM25 fallback.

        Args:
            query: Query text
            top_k: Number of top results to return
            space_whitelist: Optional list of space keys to filter documents
            export_trace_dir: Optional directory to export trace JSON

        Returns:
            List of dicts with chunk info and similarity scores
        """
        trace_data = {
            "query": query,
            "is_n2s_query": is_n2s_query(query),
            "hybrid_enabled": self.enable_hybrid,
            "candidates": [],
        }

        # Determine if we should apply N2S filtering
        apply_n2s_filter = self.enable_n2s_filter and is_n2s_query(query)

        if self.enable_hybrid:
            return self._search_hybrid(
                query,
                top_k,
                space_whitelist,
                apply_n2s_filter,
                trace_data,
                export_trace_dir,
            )
        else:
            return self._search_legacy(
                query,
                top_k,
                space_whitelist,
                apply_n2s_filter,
                trace_data,
                export_trace_dir,
            )

    def _search_hybrid(
        self,
        query: str,
        top_k: int,
        space_whitelist: list[str] | None,
        n2s_filter: bool,
        trace_data: dict[str, Any],
        export_trace_dir: str | None,
    ) -> list[dict[str, Any]]:
        """Perform hybrid search with dense + BM25 and RRF fusion."""
        try:
            # Dense retrieval
            query_vec = self.embed_query(query)
            dense_results = self.search_postgres(query_vec, self.provider_name, self.topk_dense, space_whitelist)

            # Mark as dense
            for r in dense_results:
                r["search_type"] = "dense"

            # BM25 retrieval
            bm25_results = self.search_bm25(query, self.topk_bm25, space_whitelist, n2s_filter, expand_query=True)

            # Apply RRF fusion
            fused_results = reciprocal_rank_fusion(dense_results, bm25_results, self.rrf_k)

            # Apply domain boosts
            boosted_results = apply_domain_boosts(fused_results, self.enable_boosts)

            # Sort by final score (RRF + boosts)
            final_results = sorted(boosted_results, key=lambda x: (-x["score"], x["chunk_id"]))[:top_k]

            # Update trace data
            trace_data.update(
                {
                    "dense_results": len(dense_results),
                    "bm25_results": len(bm25_results),
                    "fused_results": len(fused_results),
                    "final_results": len(final_results),
                    "n2s_filter_applied": n2s_filter,
                    "boosts_applied": self.enable_boosts,
                    "candidates": final_results[:5],  # Top 5 for trace
                }
            )

            # Export trace if requested
            if export_trace_dir:
                self._export_trace(trace_data, export_trace_dir)

            return final_results

        except Exception as e:
            print(f"Warning: Hybrid retrieval failed: {e}")
            # Fall back to legacy search
            return self._search_legacy(query, top_k, space_whitelist, n2s_filter, trace_data, export_trace_dir)

    def _search_legacy(
        self,
        query: str,
        top_k: int,
        space_whitelist: list[str] | None,
        n2s_filter: bool,
        trace_data: dict[str, Any],
        export_trace_dir: str | None,
    ) -> list[dict[str, Any]]:
        """Perform legacy dense retrieval with BM25 fallback."""
        # Try dense retrieval first
        try:
            query_vec = self.embed_query(query)
            candidates = self.search_postgres(query_vec, self.provider_name, top_k, space_whitelist)

            if candidates:
                # Mark as dense and apply boosts
                for r in candidates:
                    r["search_type"] = "dense"

                boosted_results = apply_domain_boosts(candidates, self.enable_boosts)

                trace_data.update(
                    {
                        "search_method": "dense_only",
                        "results": len(boosted_results),
                        "candidates": boosted_results[:5],
                    }
                )

                if export_trace_dir:
                    self._export_trace(trace_data, export_trace_dir)

                return boosted_results

        except Exception as e:
            print(f"Warning: Dense retrieval failed: {e}")

        # If dense retrieval returned no results or failed, try BM25 fallback
        if self.enable_bm25_fallback:
            print(f"Dense retrieval returned 0 results, falling back to BM25 for query: {query[:50]}...")
            fallback_results = self.search_bm25_fallback(query, top_k, space_whitelist, n2s_filter)

            trace_data.update(
                {
                    "search_method": "bm25_fallback",
                    "results": len(fallback_results),
                    "candidates": fallback_results[:5],
                }
            )

            if export_trace_dir:
                self._export_trace(trace_data, export_trace_dir)

            return fallback_results

        # No fallback available, return empty results
        return []

    def _export_trace(self, trace_data: dict[str, Any], export_dir: str) -> None:
        """Export trace data to JSON file."""
        try:
            trace_dir = Path(export_dir)
            trace_dir.mkdir(parents=True, exist_ok=True)

            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trace_file = trace_dir / f"trace_{timestamp}.json"

            with open(trace_file, "w") as f:
                json.dump(trace_data, f, indent=2)

            print(f"Trace exported to: {trace_file}")
        except Exception as e:
            print(f"Warning: Failed to export trace: {e}")


def create_retriever(
    db_url: str | None = None,
    provider_name: str = "dummy",
    dim: int | None = None,
    enable_bm25_fallback: bool = True,
    enable_hybrid: bool = True,
    topk_dense: int = 200,
    topk_bm25: int = 200,
    rrf_k: int = 60,
    enable_boosts: bool = True,
    enable_n2s_filter: bool = True,
    server_side: bool = False,
) -> DenseRetriever:
    """
    Factory function to create a DenseRetriever.

    Args:
        db_url: Database URL (uses default if None)
        provider_name: Embedding provider name
        dim: Embedding dimension (auto-detected if None)
        enable_bm25_fallback: Enable BM25 full-text fallback
        enable_hybrid: Enable hybrid retrieval (dense + BM25 with RRF)
        topk_dense: Top-k for dense retrieval in hybrid mode
        topk_bm25: Top-k for BM25 retrieval in hybrid mode
        rrf_k: RRF parameter k (typically 60)
        enable_boosts: Enable domain-aware boosts
        enable_n2s_filter: Enable N2S query detection and filtering
        server_side: Use server-side RRF SQL function

    Returns:
        DenseRetriever instance
    """
    return DenseRetriever(
        db_url=db_url,
        provider_name=provider_name,
        dim=dim,
        enable_bm25_fallback=enable_bm25_fallback,
        enable_hybrid=enable_hybrid,
        topk_dense=topk_dense,
        topk_bm25=topk_bm25,
        rrf_k=rrf_k,
        enable_boosts=enable_boosts,
        enable_n2s_filter=enable_n2s_filter,
        server_side=server_side,
    )
