# Retrieval System Discovery Summary

## Overview

Analysis of the Trailblazer retrieval system for QA and hardening project. This document summarizes key findings about SQL construction, database connectivity, deduplication, traceability, and CLI entrypoints.

## Key Findings

### 1. SQL Construction & Filtering

**Location**: `src/trailblazer/retrieval/dense.py` - `DenseRetriever.search_postgres()` method (lines 176-275)

- ✅ **Provider filter**: Present - `ChunkEmbedding.provider == provider` filter applied
- ❌ **Dimension filter**: **MISSING** - No `ce.dimension = 1536` filter in SQL queries
- **Critical Gap**: This means the retriever could return embeddings from any dimension, potentially causing retrieval failures

### 2. Database Connectivity

**Location**: `DenseRetriever.__init__()` and `session_factory` property (lines 67-110)

- ✅ **db_url parameter**: Accepted in constructor
- ✅ **Session factory**: Honors passed `db_url` correctly
- ✅ **CLI integration**: `ask` command accepts `--db-url` flag and threads it to retriever (line 1040)

### 3. Tie Breaking & Deduplication

**Location**: `search_postgres()` method (lines 176-275)

- ✅ **ORDER BY**: `score DESC, doc_id ASC, chunk_id ASC` for deterministic ordering (line 250)
- ❌ **Deduplication**: **MISSING** - No application-level dedupe of (doc_id, chunk_id) pairs
- **Note**: SQL gets `top_k * 3` candidates but no deduplication logic applied

### 4. Traceability Fields

**Location**: `search_postgres()` method (lines 195-210)

- ✅ **Joins**: `Document.title` and `Document.url` joined via `Chunk.doc_id == Document.doc_id`
- ✅ **Fields**: Included in search results
- ✅ **Traceability**: Present and functional

### 5. CLI Entrypoint

**Location**: `src/trailblazer/cli/main.py` - `ask()` function (line 1000)

- **Parameters**: Accepts `--db-url`, `--provider`, `--top-k`, `--max-chars`
- **Usage**: Can be called programmatically or via CLI
- **Integration**: Threads `db_url` to retriever correctly

## Identified Issues

### High Priority

1. **Missing dimension filter**: No `ce.dimension = 1536` filter in SQL queries
1. **No deduplication**: Duplicate (doc_id, chunk_id) pairs not removed

### Medium Priority

1. **SQL efficiency**: Gets `top_k * 3` candidates but could be optimized

## Recommendations

### Immediate Fixes Needed

1. Add `ChunkEmbedding.dimension == 1536` filter to SQL queries
1. Implement application-level deduplication of (doc_id, chunk_id) pairs
1. Ensure provider filter is always set to 'openai' for production use

### Testing Requirements

1. Verify dimension filter is applied in SQL query plans
1. Test deduplication logic with duplicate chunks
1. Validate db_url parameter threading through CLI to retriever

## File Paths Summary

- **Retriever Core**: `src/trailblazer/retrieval/dense.py`
- **CLI Entrypoint**: `src/trailblazer/cli/main.py` (ask function)
- **Database Models**: `src/trailblazer/db/engine.py`
- **QA Harness**: `src/trailblazer/qa/retrieval.py`
- **Standalone Script**: `scripts/qa_retrieval.py`
