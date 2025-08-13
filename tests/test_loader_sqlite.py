import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

from trailblazer.db.engine import (
    Document,
    Chunk,
    ChunkEmbedding,
    create_tables,
    get_engine,
    get_session_factory,
)
from trailblazer.pipeline.steps.embed.loader import load_normalized_to_db


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db_url = f"sqlite:///{db_path}"

        # Patch the database URL
        with patch("trailblazer.db.engine.get_db_url", return_value=db_url):
            # Reset global engine
            import trailblazer.db.engine as engine_module

            engine_module._engine = None
            engine_module._session_factory = None

            # Create tables
            create_tables()

            yield db_url


@pytest.fixture
def sample_normalized_data():
    """Create sample normalized data for testing."""
    return [
        {
            "id": "doc1",
            "title": "First Document",
            "space_key": "TEST",
            "space_id": "123",
            "url": "https://example.com/doc1",
            "version": 1,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
            "body_repr": "storage",
            "text_md": "# First Document\n\nThis is the first test document with some content.",
            "links": ["https://example.com/link1"],
            "attachments": [
                {
                    "filename": "file1.pdf",
                    "url": "https://example.com/file1.pdf",
                }
            ],
            "source": "confluence",
        },
        {
            "id": "doc2",
            "title": "Second Document",
            "space_key": "TEST",
            "space_id": "123",
            "url": "https://example.com/doc2",
            "version": 2,
            "created_at": "2025-01-03T00:00:00Z",
            "updated_at": "2025-01-04T00:00:00Z",
            "body_repr": "adf",
            "text_md": "# Second Document\n\nThis is the second test document with different content for testing chunking and embedding.",
            "links": [],
            "attachments": [],
            "source": "confluence",
        },
    ]


@pytest.fixture
def normalized_file(sample_normalized_data):
    """Create a temporary normalized NDJSON file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ndjson", delete=False
    ) as f:
        for record in sample_normalized_data:
            f.write(json.dumps(record) + "\n")
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink()


def test_load_normalized_to_db_basic(temp_db, normalized_file):
    """Test basic loading of normalized data to database."""
    metrics = load_normalized_to_db(
        input_file=normalized_file,
        provider_name="dummy",
        batch_size=10,
        max_docs=None,
        max_chunks=None,
    )

    # Check metrics
    assert metrics["docs_processed"] == 2
    assert metrics["docs_upserted"] == 2
    assert metrics["chunks_processed"] > 0
    assert metrics["embeddings_processed"] > 0
    assert metrics["provider"] == "dummy"
    assert metrics["dimension"] == 384  # Default dummy dimension

    # Check database contents
    session_factory = get_session_factory()
    with session_factory() as session:
        # Check documents
        docs = session.query(Document).all()
        assert len(docs) == 2

        doc1 = session.query(Document).filter_by(doc_id="doc1").first()
        assert doc1 is not None
        assert doc1.title == "First Document"
        assert doc1.source == "confluence"
        assert doc1.space_key == "TEST"

        # Check chunks
        chunks = session.query(Chunk).all()
        assert len(chunks) > 0

        chunk1 = session.query(Chunk).filter_by(doc_id="doc1").first()
        assert chunk1 is not None
        assert "First Document" in chunk1.text_md
        assert chunk1.char_count > 0
        assert chunk1.token_count > 0

        # Check embeddings
        embeddings = session.query(ChunkEmbedding).all()
        assert len(embeddings) > 0

        embedding1 = (
            session.query(ChunkEmbedding)
            .filter_by(chunk_id=chunk1.chunk_id)
            .first()
        )
        assert embedding1 is not None
        assert embedding1.provider == "dummy"
        assert embedding1.dim == 384


def test_load_normalized_idempotency(temp_db, normalized_file):
    """Test that loading the same data twice doesn't duplicate rows."""
    # First load
    metrics1 = load_normalized_to_db(
        input_file=normalized_file, provider_name="dummy", batch_size=5
    )

    # Second load
    metrics2 = load_normalized_to_db(
        input_file=normalized_file, provider_name="dummy", batch_size=5
    )

    # Should process same number but not upsert on second run
    assert metrics1["docs_processed"] == metrics2["docs_processed"]
    assert metrics1["chunks_processed"] == metrics2["chunks_processed"]

    # Check database counts remain the same
    session_factory = get_session_factory()
    with session_factory() as session:
        doc_count = session.query(Document).count()
        chunk_count = session.query(Chunk).count()
        embedding_count = session.query(ChunkEmbedding).count()

        assert doc_count == 2
        assert chunk_count == metrics1["chunks_processed"]
        assert embedding_count == metrics1["embeddings_processed"]


def test_load_normalized_with_limits(temp_db, normalized_file):
    """Test loading with max_docs and max_chunks limits."""
    # Test max_docs limit
    metrics = load_normalized_to_db(
        input_file=normalized_file, provider_name="dummy", max_docs=1
    )

    assert metrics["docs_processed"] == 1

    session_factory = get_session_factory()
    with session_factory() as session:
        doc_count = session.query(Document).count()
        assert doc_count == 1


def test_load_normalized_batch_size(temp_db, normalized_file):
    """Test different batch sizes."""
    # Test with small batch size
    metrics = load_normalized_to_db(
        input_file=normalized_file,
        provider_name="dummy",
        batch_size=1,  # Very small batch
    )

    assert metrics["embeddings_processed"] > 0

    # Verify embeddings were created
    session_factory = get_session_factory()
    with session_factory() as session:
        embedding_count = session.query(ChunkEmbedding).count()
        assert embedding_count == metrics["embeddings_processed"]


def test_load_normalized_missing_file(temp_db):
    """Test error handling for missing input file."""
    with pytest.raises(FileNotFoundError):
        load_normalized_to_db(
            input_file="/nonexistent/file.ndjson", provider_name="dummy"
        )


def test_load_normalized_invalid_json(temp_db):
    """Test handling of invalid JSON lines."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ndjson", delete=False
    ) as f:
        f.write('{"id": "valid-1", "title": "Valid", "text_md": "content"}\n')
        f.write("invalid json line\n")
        f.write(
            '{"id": "valid-2", "title": "Another", "text_md": "more content"}\n'
        )
        temp_path = f.name

    try:
        # Should not crash on invalid JSON
        metrics = load_normalized_to_db(
            input_file=temp_path, provider_name="dummy"
        )

        # Should process the valid lines only
        assert metrics["docs_processed"] == 2

    finally:
        Path(temp_path).unlink()


def test_load_normalized_empty_content(temp_db):
    """Test handling of documents with empty content."""
    empty_record = {
        "id": "empty-doc",
        "title": "Empty Document",
        "text_md": "",
        "source": "confluence",
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ndjson", delete=False
    ) as f:
        f.write(json.dumps(empty_record) + "\n")
        temp_path = f.name

    try:
        metrics = load_normalized_to_db(
            input_file=temp_path, provider_name="dummy"
        )

        # Should process document and create chunk for title
        assert metrics["docs_processed"] == 1
        assert metrics["chunks_processed"] == 1  # Title creates a chunk

    finally:
        Path(temp_path).unlink()


def test_chunk_id_format(temp_db, normalized_file):
    """Test that chunk IDs follow the expected format."""
    load_normalized_to_db(input_file=normalized_file, provider_name="dummy")

    session_factory = get_session_factory()
    with session_factory() as session:
        chunks = session.query(Chunk).all()

        for chunk in chunks:
            # Chunk ID should be in format doc_id:nnnn
            assert ":" in chunk.chunk_id
            doc_id, ord_str = chunk.chunk_id.split(":", 1)
            assert doc_id == chunk.doc_id
            assert len(ord_str) == 4  # 4-digit zero-padded
            assert ord_str.isdigit()
            assert int(ord_str) == chunk.ord


def test_embedding_storage_format(temp_db, normalized_file):
    """Test that embeddings are stored in correct format for SQLite."""
    load_normalized_to_db(input_file=normalized_file, provider_name="dummy")

    session_factory = get_session_factory()
    with session_factory() as session:
        embedding = session.query(ChunkEmbedding).first()
        assert embedding is not None

        # For SQLite, embedding should be stored as JSON string
        stored_embedding = embedding.embedding

        # Should be parseable as JSON
        if isinstance(stored_embedding, str):
            parsed = json.loads(stored_embedding)
            assert isinstance(parsed, list)
            assert len(parsed) == embedding.dim
            assert all(isinstance(x, (int, float)) for x in parsed)


def test_database_schema_creation(temp_db):
    """Test that database schema is created correctly."""
    engine = get_engine()

    # Check that tables exist
    with engine.connect() as conn:
        # Check documents table
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
            )
        )
        assert result.fetchone() is not None

        # Check chunks table
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
            )
        )
        assert result.fetchone() is not None

        # Check chunk_embeddings table
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_embeddings'"
            )
        )
        assert result.fetchone() is not None
