# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

"""Test database schema and models."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from trailblazer.db.engine import (
    Chunk,
    ChunkEmbedding,
    Document,
    deserialize_embedding,
    get_engine,
    serialize_embedding,
)

# Mark all tests in this file as requiring pgvector
pytestmark = pytest.mark.pgvector


def test_database_models_import():
    """Test that database models can be imported."""


def test_database_schema_creation():
    """Test that database schema can be created."""

    # Use the PostgreSQL test database provided by conftest.py
    engine = get_engine()

    # Check that tables exist (created by conftest.py)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        tables = [row[0] for row in result]

        assert "documents" in tables
        assert "chunks" in tables
        assert "chunk_embeddings" in tables


def test_document_model():
    """Test Document model operations."""

    engine = get_engine()
    Session = sessionmaker(bind=engine)

    with Session() as session:
        doc = Document(
            doc_id="test_doc_1",
            source_system="confluence",
            title="Test Document",
            space_key="TEST",
            url="https://example.com/test",
            content_sha256="abc123",
            meta={"custom": "metadata"},
        )

        session.add(doc)
        session.commit()

        # Query back
        retrieved = session.get(Document, "test_doc_1")
        assert retrieved is not None
        assert retrieved.title == "Test Document"
        assert retrieved.source_system == "confluence"
        assert retrieved.meta == {"custom": "metadata"}


def test_chunk_model():
    """Test Chunk model operations."""

    engine = get_engine()
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create document first
        doc = Document(
            doc_id="test_doc_2",
            source_system="confluence",
            title="Test Document for Chunks",
            content_sha256="def456",
        )
        session.add(doc)
        session.flush()

        # Create chunk
        chunk = Chunk(
            chunk_id="test_doc_2:0001",
            doc_id="test_doc_2",
            ord=1,
            text_md="# Test Chunk\n\nThis is a test chunk.",
            char_count=30,
            token_count=6,
            meta={"section": "intro"},
        )

        session.add(chunk)
        session.commit()

        # Query back
        retrieved = session.get(Chunk, "test_doc_2:0001")
        assert retrieved is not None
        assert retrieved.doc_id == "test_doc_2"
        assert retrieved.ord == 1
        assert retrieved.text_md == "# Test Chunk\n\nThis is a test chunk."
        assert retrieved.meta == {"section": "intro"}


def test_chunk_embedding_model():
    """Test ChunkEmbedding model operations."""

    engine = get_engine()
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create document and chunk first
        doc = Document(
            doc_id="test_doc_3",
            source_system="confluence",
            title="Test Document for Embeddings",
            content_sha256="ghi789",
        )
        session.add(doc)
        session.flush()

        chunk = Chunk(
            chunk_id="test_doc_3:0001",
            doc_id="test_doc_3",
            ord=1,
            text_md="Test chunk for embeddings.",
            char_count=25,
            token_count=5,
        )
        session.add(chunk)
        session.flush()

        # Create embedding
        embedding = ChunkEmbedding(
            chunk_id="test_doc_3:0001",
            provider="openai",
            dim=1536,
            embedding=[0.1] * 1536,  # Simple test embedding
        )

        session.add(embedding)
        session.commit()

        # Query back
        retrieved = session.get(ChunkEmbedding, ("test_doc_3:0001", "openai"))
        assert retrieved is not None
        assert retrieved.chunk_id == "test_doc_3:0001"
        assert retrieved.provider == "openai"
        assert retrieved.dim == 1536
        assert len(retrieved.embedding) == 1536


def test_upsert_operations():
    """Test upsert functionality."""
    from trailblazer.db.engine import (
        upsert_chunk,
        upsert_document,
    )

    engine = get_engine()
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Test document upsert
        doc_data = {
            "doc_id": "upsert_test",
            "source_system": "confluence",
            "title": "Original Title",
            "content_sha256": "original_hash",
        }

        doc1 = upsert_document(session, doc_data)
        session.commit()

        assert doc1.title == "Original Title"

        # Update same document
        doc_data["title"] = "Updated Title"
        doc2 = upsert_document(session, doc_data)
        session.commit()

        assert doc2.doc_id == doc1.doc_id
        assert doc2.title == "Updated Title"

        # Test chunk upsert
        chunk_data = {
            "chunk_id": "upsert_test:0001",
            "doc_id": "upsert_test",
            "ord": 1,
            "text_md": "Original text",
            "char_count": 13,
            "token_count": 2,
        }

        chunk1 = upsert_chunk(session, chunk_data)
        session.commit()

        chunk_data["text_md"] = "Updated text"
        chunk2 = upsert_chunk(session, chunk_data)
        session.commit()

        assert chunk2.chunk_id == chunk1.chunk_id
        assert chunk2.text_md == "Updated text"


def test_foreign_key_constraints():
    """Test foreign key constraints."""

    engine = get_engine()
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Try to create chunk without document (should fail)
        chunk = Chunk(
            chunk_id="orphan_chunk",
            doc_id="nonexistent_doc",
            ord=1,
            text_md="Orphan chunk",
            char_count=12,
            token_count=2,
        )

        session.add(chunk)

        with pytest.raises(IntegrityError):
            session.commit()


def test_unique_constraints():
    """Test unique constraints."""

    engine = get_engine()
    Session = sessionmaker(bind=engine)

    with Session() as session:
        doc1 = Document(
            doc_id="unique_test_1",
            source_system="confluence",
            title="Document 1",
            content_sha256="unique_hash",
        )

        doc2 = Document(
            doc_id="unique_test_2",
            source_system="confluence",
            title="Document 2",
            content_sha256="unique_hash",  # Same hash - should fail
        )

        session.add(doc1)
        session.add(doc2)

        with pytest.raises(IntegrityError):
            session.commit()


def test_embedding_serialization():
    """Test embedding serialization/deserialization."""
    embedding = [0.1, 0.2, 0.3]

    # PostgreSQL with pgvector (should return as-is)
    serialized = serialize_embedding(embedding)
    assert serialized == embedding

    deserialized = deserialize_embedding(serialized)
    assert deserialized == embedding


def test_database_indexes():
    """Test that database indexes are created."""

    engine = get_engine()

    with engine.connect() as conn:
        # Check that indexes exist
        result = conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname NOT LIKE 'pg_%'")
        )
        indexes = [row[0] for row in result]

        # Check for some expected indexes
        index_names = [idx for idx in indexes if not idx.startswith("pk_")]
        assert len(index_names) > 0  # Should have some non-primary key indexes


def test_embedding_vector_operations():
    """Test that vector operations work with embeddings."""

    engine = get_engine()
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create test data
        doc = Document(
            doc_id="vector_test",
            source_system="test",
            title="Vector Test",
            content_sha256="vector_hash",
        )
        session.add(doc)
        session.flush()

        chunk = Chunk(
            chunk_id="vector_test:0001",
            doc_id="vector_test",
            ord=1,
            text_md="Vector test chunk",
            char_count=17,
            token_count=3,
        )
        session.add(chunk)
        session.flush()

        # Create embedding with known values
        embedding = ChunkEmbedding(
            chunk_id="vector_test:0001",
            provider="test",
            dim=3,
            embedding=[1.0, 0.0, 0.0],
        )
        session.add(embedding)
        session.commit()

        # Test that we can query the embedding
        retrieved = session.get(ChunkEmbedding, ("vector_test:0001", "test"))
        assert retrieved is not None
        import numpy as np

        assert np.array_equal(retrieved.embedding, [1.0, 0.0, 0.0])
