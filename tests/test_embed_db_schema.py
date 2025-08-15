"""Tests for the embedding database schema."""

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Only run these tests with explicit test environment
pytestmark = pytest.mark.skipif(
    os.getenv("TB_TESTING") != "1",
    reason="Requires TB_TESTING=1 for database schema tests",
)


def test_database_models_import():
    """Test that database models can be imported."""


def test_database_schema_creation():
    """Test that database schema can be created."""
    from trailblazer.db.engine import Base

    # Create in-memory SQLite database for testing
    engine = create_engine("sqlite:///:memory:")

    # Patch the global engine
    with pytest.MonkeyPatch().context() as m:
        m.setenv("TB_TESTING", "1")
        m.setattr("trailblazer.db.engine._engine", engine)

        # Create all tables
        Base.metadata.create_all(engine)

        # Check that tables exist
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = [row[0] for row in result]

            assert "documents" in tables
            assert "chunks" in tables
            assert "chunk_embeddings" in tables


def test_document_model():
    """Test Document model operations."""
    from trailblazer.db.engine import Base, Document

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create a document
        doc = Document(
            doc_id="test-doc-1",
            source_system="confluence",
            title="Test Document",
            space_key="TEST",
            url="https://example.com/test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            content_sha256="abcd1234" * 8,  # 64 char hash
            meta={
                "version": 1,
                "space_id": "space123",
                "links": [],
                "attachments": [],
            },
        )

        session.add(doc)
        session.commit()

        # Retrieve the document
        retrieved = session.get(Document, "test-doc-1")
        assert retrieved is not None
        assert retrieved.title == "Test Document"
        assert retrieved.source_system == "confluence"
        assert retrieved.content_sha256 == "abcd1234" * 8
        assert retrieved.meta["version"] == 1


def test_chunk_model():
    """Test Chunk model operations."""
    from trailblazer.db.engine import Base, Chunk, Document

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create a document first
        doc = Document(
            doc_id="test-doc-1",
            source_system="confluence",
            title="Test Document",
            content_sha256="hash123" * 8,
            meta={},
        )
        session.add(doc)

        # Create chunks
        chunk1 = Chunk(
            chunk_id="test-doc-1:0000",
            doc_id="test-doc-1",
            ord=0,
            text_md="# First Chunk\n\nThis is the first chunk.",
            char_count=35,
            token_count=8,
            meta={"section": "intro"},
        )

        chunk2 = Chunk(
            chunk_id="test-doc-1:0001",
            doc_id="test-doc-1",
            ord=1,
            text_md="## Second Chunk\n\nThis is the second chunk.",
            char_count=37,
            token_count=9,
            meta={"section": "body"},
        )

        session.add_all([chunk1, chunk2])
        session.commit()

        # Test relationships
        doc_with_chunks = session.get(Document, "test-doc-1")
        assert len(doc_with_chunks.chunks) == 2
        assert doc_with_chunks.chunks[0].ord == 0
        assert doc_with_chunks.chunks[1].ord == 1

        # Test chunk retrieval
        chunk = session.get(Chunk, "test-doc-1:0000")
        assert chunk.doc_id == "test-doc-1"
        assert chunk.document.title == "Test Document"


def test_chunk_embedding_model():
    """Test ChunkEmbedding model operations."""
    from trailblazer.db.engine import Base, Chunk, ChunkEmbedding, Document

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create document and chunk
        doc = Document(
            doc_id="test-doc-1",
            source_system="confluence",
            title="Test Document",
            content_sha256="hash123" * 8,
            meta={},
        )

        chunk = Chunk(
            chunk_id="test-doc-1:0000",
            doc_id="test-doc-1",
            ord=0,
            text_md="Test chunk content",
            char_count=18,
            token_count=3,
            meta={},
        )

        session.add_all([doc, chunk])
        session.flush()  # Ensure chunk exists before embedding

        # Create embedding
        embedding = ChunkEmbedding(
            chunk_id="test-doc-1:0000",
            provider="dummy",
            dim=384,
            embedding=[0.1, 0.2, 0.3] * 128,  # 384 dims
            created_at=datetime.now(timezone.utc),
        )

        session.add(embedding)
        session.commit()

        # Test retrieval
        retrieved = session.get(ChunkEmbedding, ("test-doc-1:0000", "dummy"))
        assert retrieved is not None
        assert retrieved.provider == "dummy"
        assert retrieved.dim == 384
        assert len(retrieved.embedding) == 384
        assert retrieved.chunk.text_md == "Test chunk content"


def test_upsert_functions():
    """Test upsert utility functions."""
    from trailblazer.db.engine import (
        Base,
        upsert_chunk,
        upsert_chunk_embedding,
        upsert_document,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Test document upsert
        doc_data = {
            "doc_id": "test-doc-1",
            "source_system": "confluence",
            "title": "Original Title",
            "content_sha256": "hash123" * 8,
            "meta": {"version": 1},
        }

        # First upsert (insert)
        doc1 = upsert_document(session, doc_data)
        session.commit()

        assert doc1.title == "Original Title"

        # Second upsert (update)
        doc_data["title"] = "Updated Title"
        doc_data["meta"] = {"version": 2}
        doc2 = upsert_document(session, doc_data)
        session.commit()

        # Should be the same object, updated
        assert doc2.doc_id == doc1.doc_id
        assert doc2.title == "Updated Title"
        assert doc2.meta["version"] == 2

        # Test chunk upsert
        chunk_data = {
            "chunk_id": "test-doc-1:0000",
            "doc_id": "test-doc-1",
            "ord": 0,
            "text_md": "Original chunk",
            "char_count": 14,
            "token_count": 2,
            "meta": {},
        }

        chunk1 = upsert_chunk(session, chunk_data)
        session.commit()

        # Update chunk
        chunk_data["text_md"] = "Updated chunk"
        chunk_data["char_count"] = 13
        chunk2 = upsert_chunk(session, chunk_data)
        session.commit()

        assert chunk2.chunk_id == chunk1.chunk_id
        assert chunk2.text_md == "Updated chunk"
        assert chunk2.char_count == 13

        # Test embedding upsert
        embedding_data = {
            "chunk_id": "test-doc-1:0000",
            "provider": "dummy",
            "dim": 256,
            "embedding": [0.1] * 256,
            "created_at": datetime.now(timezone.utc),
        }

        emb1 = upsert_chunk_embedding(session, embedding_data)
        session.commit()

        # Update embedding
        embedding_data["embedding"] = [0.2] * 256
        emb2 = upsert_chunk_embedding(session, embedding_data)
        session.commit()

        assert emb2.chunk_id == emb1.chunk_id
        assert emb2.provider == emb1.provider
        assert emb2.embedding == [0.2] * 256


def test_content_sha256_uniqueness():
    """Test that content_sha256 uniqueness constraint works."""
    from trailblazer.db.engine import Base, Document
    from sqlalchemy.exc import IntegrityError

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create first document
        doc1 = Document(
            doc_id="doc-1",
            source_system="confluence",
            content_sha256="duplicate_hash" * 4,
            meta={},
        )
        session.add(doc1)
        session.commit()

        # Try to create second document with same hash
        doc2 = Document(
            doc_id="doc-2",
            source_system="confluence",
            content_sha256="duplicate_hash" * 4,
            meta={},
        )
        session.add(doc2)

        # Should raise integrity error
        with pytest.raises(IntegrityError):
            session.commit()


def test_chunk_doc_ord_uniqueness():
    """Test that (doc_id, ord) uniqueness constraint works."""
    from trailblazer.db.engine import Base, Chunk, Document
    from sqlalchemy.exc import IntegrityError

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create document
        doc = Document(
            doc_id="test-doc",
            source_system="confluence",
            content_sha256="hash123" * 8,
            meta={},
        )
        session.add(doc)

        # Create first chunk
        chunk1 = Chunk(
            chunk_id="test-doc:0000",
            doc_id="test-doc",
            ord=0,
            text_md="First chunk",
            char_count=11,
            token_count=2,
            meta={},
        )
        session.add(chunk1)
        session.commit()

        # Try to create second chunk with same doc_id and ord
        chunk2 = Chunk(
            chunk_id="test-doc:0001",  # Different chunk_id
            doc_id="test-doc",  # Same doc_id
            ord=0,  # Same ord - should fail
            text_md="Duplicate chunk",
            char_count=15,
            token_count=2,
            meta={},
        )
        session.add(chunk2)

        # Should raise integrity error
        with pytest.raises(IntegrityError):
            session.commit()


def test_embedding_serialization():
    """Test embedding serialization for different database types."""
    from trailblazer.db.engine import (
        deserialize_embedding,
        serialize_embedding,
    )

    # Test with mock postgres (should return as-is)
    with pytest.MonkeyPatch().context() as m:
        m.setattr("trailblazer.db.engine.is_postgres", lambda: True)

        embedding = [0.1, 0.2, 0.3]
        serialized = serialize_embedding(embedding)
        assert serialized == embedding

        deserialized = deserialize_embedding(serialized)
        assert deserialized == embedding

    # Test with SQLite (should use JSON)
    with pytest.MonkeyPatch().context() as m:
        m.setattr("trailblazer.db.engine.is_postgres", lambda: False)

        embedding = [0.1, 0.2, 0.3]
        serialized = serialize_embedding(embedding)
        assert isinstance(serialized, str)  # Should be JSON string

        deserialized = deserialize_embedding(serialized)
        assert deserialized == embedding


def test_indexes_created():
    """Test that database indexes are properly created."""
    from trailblazer.db.engine import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        # Check that indexes exist (SQLite specific query)
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        )
        indexes = [row[0] for row in result]

        # Should have our custom indexes
        assert any("documents" in idx for idx in indexes)
        assert any("chunks" in idx for idx in indexes)
        assert any("chunk_embeddings" in idx for idx in indexes)
