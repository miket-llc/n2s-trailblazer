from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlparse

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
    text,
)

from pgvector.sqlalchemy import Vector as VECTOR  # type: ignore[import-untyped]
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func

from ..core.config import SETTINGS


class Base(DeclarativeBase):
    pass


# Global engine and session factory
_engine = None
_session_factory = None


def get_db_url() -> str:
    """Get database URL from settings.

    Raises:
        ValueError: If DB_URL is not configured.
    """
    db_url = SETTINGS.TRAILBLAZER_DB_URL
    if not db_url:
        raise ValueError(
            "TRAILBLAZER_DB_URL is required. "
            "Set TRAILBLAZER_DB_URL to a PostgreSQL URL in your .env file. "
            "Run 'make db.up' then 'trailblazer db doctor' to get started."
        )
    return db_url


def get_engine():
    """Get or create the SQLAlchemy engine.

    Raises:
        ValueError: If database URL is not PostgreSQL.
    """
    global _engine
    if _engine is None:
        db_url = get_db_url()

        # Ensure we're using PostgreSQL
        if not db_url.startswith("postgres"):
            raise ValueError(
                "Only PostgreSQL is supported. "
                "Set TRAILBLAZER_DB_URL to a PostgreSQL URL in your .env file. "
                "Run 'make db.up' then 'trailblazer db doctor' to get started."
            )

        _engine = create_engine(db_url, future=True)
    return _engine


def get_session() -> Session:
    """Get a new database session."""
    session_factory = get_session_factory()
    return session_factory()


def get_session_factory():
    """Get or create the session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory


def create_tables():
    """Create all tables defined in models."""
    Base.metadata.create_all(get_engine())


# Removed is_postgres() since we only support PostgreSQL


def check_db_health() -> Dict[str, Any]:
    """Check database connectivity and capabilities.

    Returns:
        Dict with status info including connectivity, dialect, database name, and pgvector availability.

    Raises:
        Exception: If database connection fails.
    """
    engine = get_engine()

    with engine.connect() as conn:
        # Test basic connectivity
        conn.execute(text("SELECT 1"))

        # Get database info
        dialect = engine.dialect.name
        db_url = get_db_url()
        parsed_url = urlparse(db_url)
        db_name = parsed_url.path.lstrip("/") if parsed_url.path else "default"

        # Check for pgvector if PostgreSQL
        pgvector_available = False
        if dialect == "postgresql":
            try:
                result = conn.execute(
                    text(
                        "SELECT extname FROM pg_extension WHERE extname='vector'"
                    )
                )
                pgvector_available = result.fetchone() is not None
            except Exception:
                # Extension query failed, pgvector not available
                pass

        return {
            "status": "ok",
            "dialect": dialect,
            "database": db_name,
            "pgvector": pgvector_available,
            "host": parsed_url.hostname or "localhost",
        }


def initialize_postgres_extensions():
    """Initialize PostgreSQL extensions if needed (pgvector).

    Silently continues if extension creation fails (e.g., insufficient permissions).
    """
    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        except Exception:
            # Extension creation failed (likely permissions), but that's OK
            # The user can create it manually if needed
            pass


def ensure_vector_index() -> None:
    """Create pgvector index if missing (safe/no-op if exists)."""
    engine = get_engine()
    with engine.connect() as conn:
        # IVFFLAT cosine index; requires ANALYZE and pgvector >= 0.5.0
        try:
            conn.execute(
                text(
                    """
                CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_vec
                ON chunk_embeddings
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            """
                )
            )
            conn.execute(text("ANALYZE chunk_embeddings;"))
            conn.commit()
        except Exception:
            # Do not explode; db.doctor will show remaining gaps
            pass


class Document(Base):
    """Document table - stores metadata from normalized documents."""

    __tablename__ = "documents"

    doc_id = Column(String, primary_key=True)
    source_system = Column(
        String, nullable=False
    )  # e.g., "confluence", "dita"
    title = Column(String)
    space_key = Column(String)
    url = Column(String)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))
    content_sha256 = Column(
        String, nullable=False, unique=True
    )  # For idempotency
    meta = Column(JSON)  # Additional metadata as JSON

    # Relationships
    chunks = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )

    # Index for efficient queries
    __table_args__ = (
        Index("idx_documents_source_space", "source_system", "space_key"),
        Index("idx_documents_content_hash", "content_sha256"),
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
    chunk_type = Column(
        String, nullable=False, default="text"
    )  # text, code, table, macro, digest
    meta = Column(JSON)  # Additional chunk metadata as JSON

    # Relationships
    document = relationship("Document", back_populates="chunks")
    embeddings = relationship(
        "ChunkEmbedding", back_populates="chunk", cascade="all, delete-orphan"
    )

    # Composite index for efficient document-based queries
    __table_args__ = (
        Index("idx_chunks_doc_ord", "doc_id", "ord"),
        Index("idx_chunks_unique_doc_ord", "doc_id", "ord", unique=True),
    )


class ChunkEmbedding(Base):
    """Chunk embedding table - stores vector embeddings for chunks."""

    __tablename__ = "chunk_embeddings"

    chunk_id = Column(String, ForeignKey("chunks.chunk_id"), primary_key=True)
    provider = Column(String, primary_key=True)  # e.g., "dummy", "openai"
    dim = Column(Integer, nullable=False)  # Embedding dimension
    created_at = Column(DateTime(timezone=True), default=func.now())

    # Embedding storage - pgvector (dimension can be configured)
    embedding = Column(VECTOR())

    # Relationships
    chunk = relationship("Chunk", back_populates="embeddings")

    # Unique constraint
    __table_args__ = (
        Index(
            "idx_chunk_embeddings_unique", "chunk_id", "provider", unique=True
        ),
    )


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


def serialize_embedding(embedding: List[float]) -> List[float]:
    """Return embedding as-is for pgvector storage."""
    return embedding


def deserialize_embedding(stored_embedding: List[float]) -> List[float]:
    """Return embedding as-is from pgvector storage."""
    return stored_embedding
