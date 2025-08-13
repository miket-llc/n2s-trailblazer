from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)

try:
    from sqlalchemy.dialects.postgresql import VECTOR  # type: ignore[attr-defined]
except ImportError:
    # pgvector not available, will use JSON fallback
    VECTOR = None
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func

from ..core.config import SETTINGS

# Default SQLite DB path
DEFAULT_DB_URL = "sqlite:///./.trailblazer.db"


class Base(DeclarativeBase):
    pass


# Global engine and session factory
_engine = None
_session_factory = None


def get_db_url() -> str:
    """Get database URL from settings or use default SQLite."""
    return SETTINGS.TRAILBLAZER_DB_URL or DEFAULT_DB_URL


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        db_url = get_db_url()
        _engine = create_engine(db_url, future=True)
    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory


def create_tables():
    """Create all tables defined in models."""
    Base.metadata.create_all(get_engine())


def is_postgres() -> bool:
    """Check if the current database is PostgreSQL."""
    return get_db_url().startswith("postgresql")


class Document(Base):
    """Document table - stores metadata from normalized documents."""

    __tablename__ = "documents"

    doc_id = Column(String, primary_key=True)
    source = Column(String, nullable=False)  # e.g., "confluence"
    title = Column(String)
    space_key = Column(String)
    url = Column(String)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))
    body_repr = Column(String)  # "storage" | "adf"
    meta = Column(JSON)  # Additional metadata as JSON

    # Relationships
    chunks = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """Chunk table - stores text chunks from documents."""

    __tablename__ = "chunks"

    chunk_id = Column(String, primary_key=True)  # format: {doc_id}:{ord:04d}
    doc_id = Column(String, ForeignKey("documents.doc_id"), nullable=False)
    ord = Column(Integer, nullable=False)  # Order within document
    text_md = Column(Text, nullable=False)  # Markdown text content
    char_count = Column(Integer, nullable=False)
    token_count = Column(
        Integer, nullable=False
    )  # Simple proxy: len(text.split())

    # Relationships
    document = relationship("Document", back_populates="chunks")
    embeddings = relationship(
        "ChunkEmbedding", back_populates="chunk", cascade="all, delete-orphan"
    )

    # Composite index for efficient document-based queries
    __table_args__ = (Index("idx_chunks_doc_ord", "doc_id", "ord"),)


class ChunkEmbedding(Base):
    """Chunk embedding table - stores vector embeddings for chunks."""

    __tablename__ = "chunk_embeddings"

    chunk_id = Column(String, ForeignKey("chunks.chunk_id"), primary_key=True)
    provider = Column(String, primary_key=True)  # e.g., "dummy", "openai"
    dim = Column(Integer, nullable=False)  # Embedding dimension
    created_at = Column(DateTime(timezone=True), default=func.now())

    # Embedding storage - will be set dynamically in __init_subclass__
    embedding = Column(JSON)  # Default to JSON

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Set embedding column type based on database
        if is_postgres() and VECTOR is not None:
            cls.embedding = Column(VECTOR)  # pgvector VECTOR type
        else:
            cls.embedding = Column(JSON)  # JSON array for SQLite

    # Relationships
    chunk = relationship("Chunk", back_populates="embeddings")


def upsert_document(session, doc_data: Dict[str, Any]) -> Document:
    """Upsert a document record."""
    doc = session.get(Document, doc_data["doc_id"])
    if doc is None:
        doc = Document(**doc_data)
        session.add(doc)
    else:
        # Update existing document
        for key, value in doc_data.items():
            setattr(doc, key, value)
    return doc


def upsert_chunk(session, chunk_data: Dict[str, Any]) -> Chunk:
    """Upsert a chunk record."""
    chunk = session.get(Chunk, chunk_data["chunk_id"])
    if chunk is None:
        chunk = Chunk(**chunk_data)
        session.add(chunk)
    else:
        # Update existing chunk
        for key, value in chunk_data.items():
            setattr(chunk, key, value)
    return chunk


def upsert_chunk_embedding(
    session, embedding_data: Dict[str, Any]
) -> ChunkEmbedding:
    """Upsert a chunk embedding record."""
    key_tuple = (embedding_data["chunk_id"], embedding_data["provider"])
    embedding = session.get(ChunkEmbedding, key_tuple)

    if embedding is None:
        embedding = ChunkEmbedding(**embedding_data)
        session.add(embedding)
    else:
        # Update if provider/dim changed
        for field_name, value in embedding_data.items():
            setattr(embedding, field_name, value)

    return embedding


def serialize_embedding(embedding: List[float]) -> Any:
    """Serialize embedding for storage based on database type."""
    if is_postgres():
        # For PostgreSQL with pgvector, return as-is (SQLAlchemy handles conversion)
        return embedding
    else:
        # For SQLite, store as JSON
        return json.dumps(embedding)


def deserialize_embedding(stored_embedding: Any) -> List[float]:
    """Deserialize embedding from storage based on database type."""
    if is_postgres():
        # For PostgreSQL, return as-is
        return stored_embedding
    else:
        # For SQLite, parse JSON
        if isinstance(stored_embedding, str):
            return json.loads(stored_embedding)
        return stored_embedding
