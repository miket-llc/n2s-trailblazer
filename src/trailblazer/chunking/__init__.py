"""
Trailblazer Chunking Package

Decoupled chunking functionality with guaranteed hard token caps,
enrich-first boundaries, and comprehensive traceability.
"""

from .engine import chunk_document, Chunk
from .assurance import build_chunk_assurance

__all__ = ["chunk_document", "Chunk", "build_chunk_assurance"]
