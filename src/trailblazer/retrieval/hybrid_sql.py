"""SQL functions for server-side hybrid retrieval with RRF."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

# Server-side RRF SQL function
HYBRID_RRF_SQL = """
WITH dense_results AS (
    SELECT
        c.chunk_id,
        c.doc_id,
        c.text_md,
        d.title,
        d.url,
        d.source_system,
        d.meta,
        ROW_NUMBER() OVER (ORDER BY ce.embedding <=> :qemb, d.doc_id, c.chunk_id) as dense_rank,
        (ce.embedding <=> :qemb) as dense_score
    FROM chunks c
    JOIN chunk_embeddings ce ON c.chunk_id = ce.chunk_id
    JOIN documents d ON c.doc_id = d.doc_id
    WHERE ce.provider = :provider
    AND ce.dim = :dimension
    {space_filter}
    ORDER BY ce.embedding <=> :qemb
    LIMIT :topk_dense
),
bm25_results AS (
    SELECT
        c.chunk_id,
        c.doc_id,
        c.text_md,
        d.title,
        d.url,
        d.source_system,
        d.meta,
        ROW_NUMBER() OVER (ORDER BY ts_rank_cd(to_tsvector('english', c.text_md), plainto_tsquery('english', :q)) DESC, d.doc_id, c.chunk_id) as bm25_rank,
        ts_rank_cd(to_tsvector('english', c.text_md), plainto_tsquery('english', :q)) as bm25_score
    FROM chunks c
    JOIN documents d ON c.doc_id = d.doc_id
    WHERE to_tsvector('english', c.text_md) @@ plainto_tsquery('english', :q)
    {space_filter}
    {n2s_filter}
    ORDER BY ts_rank_cd(to_tsvector('english', c.text_md), plainto_tsquery('english', :q)) DESC
    LIMIT :topk_bm25
),
fused_results AS (
    SELECT
        COALESCE(d.chunk_id, b.chunk_id) as chunk_id,
        COALESCE(d.doc_id, b.doc_id) as doc_id,
        COALESCE(d.text_md, b.text_md) as text_md,
        COALESCE(d.title, b.title) as title,
        COALESCE(d.url, b.url) as url,
        COALESCE(d.source_system, b.source_system) as source_system,
        COALESCE(d.meta, b.meta) as meta,
        d.dense_rank,
        b.bm25_rank,
        d.dense_score,
        b.bm25_score,
        -- RRF Score: 1/(k + rank)
        COALESCE(1.0 / (:rrf_k + d.dense_rank), 0.0) + COALESCE(1.0 / (:rrf_k + b.bm25_rank), 0.0) as rrf_score
    FROM dense_results d
    FULL OUTER JOIN bm25_results b ON d.chunk_id = b.chunk_id
),
boosted_results AS (
    SELECT
        *,
        -- Apply domain boosts
        CASE
            WHEN LOWER(title) LIKE '%methodology%' THEN rrf_score + 0.20
            WHEN LOWER(title) LIKE '%playbook%' THEN rrf_score + 0.15
            WHEN LOWER(title) LIKE '%runbook%' THEN rrf_score + 0.10
            ELSE rrf_score
        END -
        -- Apply negative boost for monthly pages
        CASE
            WHEN LOWER(title) ~ '\\b(january|february|march|april|may|june|july|august|september|october|november|december)\\b'
                OR LOWER(title) ~ '\\b(20\\d{{2}})\\b' THEN 0.10
            ELSE 0.0
        END as final_score
    FROM fused_results
)
SELECT
    chunk_id,
    doc_id,
    text_md,
    title,
    url,
    source_system,
    meta,
    dense_rank,
    bm25_rank,
    dense_score,
    bm25_score,
    rrf_score,
    final_score
FROM boosted_results
ORDER BY final_score DESC, chunk_id ASC
LIMIT :top_k
"""


def execute_hybrid_rrf_sql(
    session: Any,
    query_embedding: list[float],
    query_text: str,
    provider: str,
    dimension: int,
    topk_dense: int = 200,
    topk_bm25: int = 200,
    rrf_k: int = 60,
    top_k: int = 8,
    space_whitelist: list[str] | None = None,
    n2s_filter: bool = False,
    expand_query: bool = True,
) -> list[dict[str, Any]]:
    """
    Execute server-side hybrid RRF query.

    Args:
        session: SQLAlchemy session
        query_embedding: Query embedding vector
        query_text: Query text for BM25
        provider: Embedding provider name
        dimension: Embedding dimension
        topk_dense: Top-k for dense retrieval
        topk_bm25: Top-k for BM25 retrieval
        rrf_k: RRF parameter k
        top_k: Final number of results to return
        space_whitelist: Optional list of space keys to filter
        n2s_filter: Apply N2S document filtering
        expand_query: Whether to expand N2S queries

    Returns:
        List of hybrid search results
    """
    # Import query expansion here to avoid circular imports
    from .dense import expand_n2s_query

    # Apply query expansion if enabled
    final_query = expand_n2s_query(query_text) if expand_query else query_text

    # Build space filter
    space_filter = ""
    if space_whitelist:
        placeholders = ",".join([f":space_{i}" for i in range(len(space_whitelist))])
        space_filter = f"AND d.space_key IN ({placeholders})"

    # Build N2S filter
    n2s_filter_sql = ""
    if n2s_filter:
        n2s_filter_sql = """
            AND (d.title ILIKE '%N2S%'
                 OR d.title ILIKE '%Navigate to SaaS%'
                 OR d.title ILIKE '%Methodology%'
                 OR d.title ILIKE '%Playbook%'
                 OR d.title ILIKE '%Runbook%'
                 OR d.meta::text ILIKE '%doctype%methodology%'
                 OR d.meta::text ILIKE '%doctype%playbook%'
                 OR d.meta::text ILIKE '%doctype%runbook%')
        """

    # Format the SQL with filters
    sql = HYBRID_RRF_SQL.format(space_filter=space_filter, n2s_filter=n2s_filter_sql)

    # Prepare parameters
    params = {
        "qemb": query_embedding,
        "q": final_query,
        "provider": provider,
        "dimension": dimension,
        "topk_dense": topk_dense,
        "topk_bm25": topk_bm25,
        "rrf_k": rrf_k,
        "top_k": top_k,
    }

    # Add space filter parameters
    if space_whitelist:
        for i, space_key in enumerate(space_whitelist):
            params[f"space_{i}"] = space_key

    try:
        result = session.execute(text(sql), params)

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
                    "dense_rank": row[7],
                    "bm25_rank": row[8],
                    "dense_score": float(row[9]) if row[9] else None,
                    "bm25_score": float(row[10]) if row[10] else None,
                    "rrf_score": float(row[11]),
                    "score": float(row[12]),  # final_score
                    "search_type": "hybrid_sql",
                }
            )

        return candidates

    except Exception as e:
        print(f"Warning: Server-side hybrid RRF failed: {e}")
        return []
