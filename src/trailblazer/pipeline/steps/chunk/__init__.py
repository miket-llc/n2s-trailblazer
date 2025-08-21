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

from .assurance import build_chunk_assurance
from .boundaries import (
    ChunkType,
    count_tokens,
    detect_content_type,
    normalize_text,
    split_by_headings,
    split_by_paragraphs,
    split_by_sentences,
    split_by_token_window,
    split_code_fence_by_lines,
    split_table_by_rows,
)
from .engine import Chunk, chunk_document
from .verify import verify_chunks

__all__ = [
    "Chunk",
    "ChunkType",
    "build_chunk_assurance",
    "chunk_document",
    "count_tokens",
    "detect_content_type",
    "normalize_text",
    "split_by_headings",
    "split_by_paragraphs",
    "split_by_sentences",
    "split_by_token_window",
    "split_code_fence_by_lines",
    "split_table_by_rows",
    "verify_chunks",
]
