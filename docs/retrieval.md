# Hybrid Retrieval with Domain Boosts and N2S Query Expansion

The N2S Trailblazer system now supports advanced hybrid retrieval that combines dense vector search with BM25 full-text search using Reciprocal Rank Fusion (RRF). This document describes the new features, configuration options, and usage examples.

## Overview

The hybrid retrieval system provides:

- **Hybrid Search**: Combines dense embeddings (pgvector cosine similarity) with BM25 full-text search
- **Reciprocal Rank Fusion (RRF)**: Mathematically sound fusion of dense and BM25 rankings
- **Domain-Aware Boosts**: Automatic scoring boosts for N2S-related document types
- **N2S Query Detection**: Automatic detection and expansion of Navigate-to-SaaS queries
- **Query Expansion**: Enriches N2S queries with synonyms and methodology terms
- **Server-Side Processing**: Optional SQL-based RRF for better performance

## Key Features

### 1. Hybrid Retrieval with RRF

The system retrieves `top_k` candidates from both dense and BM25 search, then fuses them using RRF:

```
RRF_score = 1/(k + dense_rank) + 1/(k + bm25_rank)
```

Where `k=60` by default (configurable with `--rrf-k`).

**Benefits:**
- Combines semantic similarity (dense) with keyword matching (BM25)
- Handles both conceptual queries and specific term searches
- Mathematically principled ranking fusion

### 2. Domain-Aware Boosts

Automatic scoring adjustments based on document type:

- **+0.20**: Methodology documents
- **+0.15**: Playbook documents
- **+0.10**: Runbook documents
- **-0.10**: Monthly/yearly pages (reduces noise from date-specific content)

### 3. N2S Query Detection and Expansion

Queries containing N2S-related terms are automatically:

1. **Detected** using pattern matching for terms like:
   - `n2s`, `navigate to saas`, `lifecycle`, `methodology`
   - `sprint 0`, `discovery`, `build`, `optimize`

2. **Expanded** with relevant synonyms and terms:
   - **Synonyms**: N2S, Navigate to SaaS, Navigate-to-SaaS, N-2-S
   - **Phases**: Discovery, Build, Optimize
   - **Stages**: Start, Prepare, Sprint 0, Plan, Configure, Test, Deploy, Go-Live
   - **Governance**: governance checkpoints, entry criteria, exit criteria
   - **Concepts**: capability-driven iterations, cross-cutting, Testing & QA

3. **Filtered** to prioritize N2S-related documents (when `--filter-n2s` is enabled)

## CLI Usage

### Basic Hybrid Search

```bash
# Default hybrid search (enabled by default)
trailblazer ask "N2S lifecycle overview"

# Disable hybrid, use dense-only with BM25 fallback
trailblazer ask "N2S lifecycle overview" --no-hybrid
```

### Hybrid Configuration

```bash
# Configure hybrid retrieval parameters
trailblazer ask "N2S lifecycle overview" \
  --hybrid \
  --topk-dense 200 \
  --topk-bm25 200 \
  --rrf-k 60
```

### Domain Boosts

```bash
# Enable domain boosts (default)
trailblazer ask "N2S methodology" --boosts

# Disable domain boosts
trailblazer ask "N2S methodology" --no-boosts
```

### N2S Query Processing

```bash
# Enable N2S query detection and filtering (default)
trailblazer ask "N2S lifecycle overview" --filter-n2s

# Disable N2S-specific processing
trailblazer ask "N2S lifecycle overview" --no-filter-n2s
```

### Server-Side Processing

```bash
# Use server-side RRF SQL function (better performance)
trailblazer ask "N2S lifecycle overview" --server-side

# Use client-side RRF processing (default)
trailblazer ask "N2S lifecycle overview"
```

### Trace Export

```bash
# Export detailed trace for analysis
trailblazer ask "N2S lifecycle overview" --export-trace ./traces/

# Trace includes:
# - Query expansion details
# - Dense/BM25 result counts
# - RRF scores and rankings
# - Applied boosts
# - Final candidate details
```

## Complete Flag Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--hybrid` / `--no-hybrid` | `True` | Enable hybrid retrieval (dense + BM25) |
| `--topk-dense` | `200` | Top-k candidates from dense retrieval |
| `--topk-bm25` | `200` | Top-k candidates from BM25 retrieval |
| `--rrf-k` | `60` | RRF parameter k (lower = more aggressive fusion) |
| `--boosts` / `--no-boosts` | `True` | Enable domain-aware scoring boosts |
| `--filter-n2s` / `--no-filter-n2s` | `True` | Enable N2S query detection/filtering |
| `--server-side` | `False` | Use server-side RRF SQL function |
| `--export-trace` | `None` | Export trace JSON to directory |

## Examples

### N2S Lifecycle Query

```bash
trailblazer ask "N2S lifecycle overview" --export-trace ./traces/
```

**Query Processing:**
1. Detected as N2S query ✓
2. Expanded with: "Discovery", "Build", "Optimize", "Sprint 0", etc.
3. N2S document filtering applied
4. Domain boosts applied (+0.20 for Methodology docs)
5. Results fused with RRF

**Expected Results:**
- At least one Methodology document in top-5
- Higher ranking for N2S-specific content
- Balanced semantic + keyword matching

### Technical Implementation Query

```bash
trailblazer ask "How to configure SSO integration?" --no-filter-n2s
```

**Query Processing:**
1. Not detected as N2S query
2. No query expansion applied
3. No N2S document filtering
4. Standard hybrid retrieval with domain boosts

### Performance Optimized Query

```bash
trailblazer ask "N2S governance checkpoints" \
  --server-side \
  --topk-dense 100 \
  --topk-bm25 100
```

**Query Processing:**
1. Uses server-side SQL RRF function
2. Reduced candidate pool for faster processing
3. All processing done in PostgreSQL

## Performance Tuning

### Candidate Pool Sizing

- **Small datasets** (`<10K chunks`): Use defaults (`topk-dense=200`, `topk-bm25=200`)
- **Large datasets** (`>100K chunks`): Consider reducing to `topk-dense=100`, `topk-bm25=100`
- **Very large datasets** (`>1M chunks`): Use `--server-side` with reduced pool sizes

### RRF Parameter Tuning

- **k=60** (default): Balanced fusion
- **k=30**: More aggressive fusion (emphasizes top-ranked results)
- **k=100**: More conservative fusion (considers more results equally)

### Query-Specific Optimization

- **N2S queries**: Keep defaults (`--filter-n2s`, `--boosts`)
- **Technical queries**: Consider `--no-filter-n2s` to avoid N2S bias
- **Exploratory queries**: Use `--export-trace` to analyze result composition

## Database Requirements

### Required Indexes

The system creates these indexes automatically:

```sql
-- For dense retrieval (pgvector)
CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_vec
ON chunk_embeddings USING ivfflat (embedding vector_cosine_ops);

-- For BM25 retrieval
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsvector
ON chunks USING GIN (to_tsvector('english', text_md));

-- For compatibility
CREATE INDEX IF NOT EXISTS idx_chunks_content_gin
ON chunks USING GIN (text_md gin_trgm_ops);
```

### Schema Compatibility

The hybrid system requires no schema changes and works with existing:
- `documents` table (title, meta, space_key fields)
- `chunks` table (text_md field)
- `chunk_embeddings` table (embedding field with pgvector)

## Troubleshooting

### Common Issues

**No results returned:**
- Check that embeddings exist for the provider
- Verify database connectivity
- Try `--no-hybrid` to test dense-only retrieval

**Poor N2S query results:**
- Ensure `--filter-n2s` is enabled for N2S queries
- Check that Methodology/Playbook documents exist in corpus
- Use `--export-trace` to analyze query expansion

**Performance issues:**
- Use `--server-side` for large datasets
- Reduce `--topk-dense` and `--topk-bm25` values
- Check database index status with `trailblazer db doctor`

### Debug Mode

```bash
# Export trace and analyze results
trailblazer ask "N2S lifecycle overview" --export-trace ./debug/

# Check trace file for:
# - Query expansion details
# - Candidate counts per retrieval method
# - RRF score calculations
# - Applied boosts and final rankings
```

## Migration from Legacy Retrieval

The hybrid system is **backward compatible**:

- Default behavior: hybrid enabled with sensible defaults
- Legacy mode: `--no-hybrid` for original dense + BM25 fallback
- Gradual adoption: Test with `--export-trace` before production use

## API Integration

For programmatic use:

```python
from trailblazer.retrieval.dense import create_retriever

# Create hybrid retriever
retriever = create_retriever(
    provider_name="openai",
    enable_hybrid=True,
    topk_dense=200,
    topk_bm25=200,
    rrf_k=60,
    enable_boosts=True,
    enable_n2s_filter=True,
    server_side=False,
)

# Search with trace export
results = retriever.search(
    query="N2S lifecycle overview",
    top_k=8,
    export_trace_dir="./traces/"
)
```

The hybrid retrieval system provides significant improvements in search quality, especially for N2S-related queries, while maintaining full backward compatibility with existing workflows.
