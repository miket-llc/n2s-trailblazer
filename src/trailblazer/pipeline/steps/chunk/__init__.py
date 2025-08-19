"""
Chunking step for the Trailblazer pipeline.

This package provides document chunking functionality with:
- Layered splitting strategy (headings, paragraphs, sentences, code, tables, token window)
- Hard token caps with guaranteed compliance
- Bottom-end controls (soft/hard minimum tokens with glue pass)
- Coverage tracking and verification
- Full traceability metadata
- Assurance reporting and corpus verification
"""

from .engine import chunk_document, Chunk
from .boundaries import (
    ChunkType,
    count_tokens,
    normalize_text,
    detect_content_type,
    split_by_headings,
    split_by_paragraphs,
    split_by_sentences,
    split_code_fence_by_lines,
    split_table_by_rows,
    split_by_token_window,
)
from .assurance import build_chunk_assurance
from .verify import verify_chunks

__all__ = [
    "chunk_document",
    "Chunk",
    "ChunkType",
    "count_tokens",
    "normalize_text",
    "detect_content_type",
    "split_by_headings",
    "split_by_paragraphs",
    "split_by_sentences",
    "split_code_fence_by_lines",
    "split_table_by_rows",
    "split_by_token_window",
    "build_chunk_assurance",
    "verify_chunks",
]
