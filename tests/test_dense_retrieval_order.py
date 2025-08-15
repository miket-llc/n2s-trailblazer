"""Test dense retrieval ordering and determinism."""

# PostgreSQL testcontainer handles temporary database setup
from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from trailblazer.db.engine import Base, Document, Chunk, ChunkEmbedding
from trailblazer.retrieval.dense import DenseRetriever, cosine_sim, top_k
import numpy as np


@pytest.fixture
def temp_db():
    """Create a temporary PostgreSQL database with test data."""
    from trailblazer.db.engine import get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)

    # Create session
    Session = sessionmaker(bind=engine)
    session = Session()

    # Add test documents
    doc1 = Document(
        doc_id="doc1",
        source_system="test",
        title="Test Document 1",
        url="http://example.com/doc1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        content_sha256="test_hash_doc1" * 4,  # 64 char hash
        meta={},
    )
    doc2 = Document(
        doc_id="doc2",
        source_system="test",
        title="Test Document 2",
        url="http://example.com/doc2",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        content_sha256="test_hash_doc2" * 4,  # 64 char hash
        meta={},
    )
    session.add_all([doc1, doc2])

    # Add test chunks for doc1
    chunks_doc1 = [
        Chunk(
            chunk_id="doc1:0001",
            doc_id="doc1",
            ord=1,
            text_md="This is the first chunk about testing.",
            char_count=39,
            token_count=8,
        ),
        Chunk(
            chunk_id="doc1:0002",
            doc_id="doc1",
            ord=2,
            text_md="This is the second chunk about algorithms.",
            char_count=41,
            token_count=8,
        ),
        Chunk(
            chunk_id="doc1:0003",
            doc_id="doc1",
            ord=3,
            text_md="This is the third chunk about machine learning.",
            char_count=47,
            token_count=9,
        ),
    ]

    # Add test chunks for doc2
    chunks_doc2 = [
        Chunk(
            chunk_id="doc2:0001",
            doc_id="doc2",
            ord=1,
            text_md="Another document chunk about databases.",
            char_count=38,
            token_count=6,
        ),
        Chunk(
            chunk_id="doc2:0002",
            doc_id="doc2",
            ord=2,
            text_md="Second chunk in doc2 about data structures.",
            char_count=43,
            token_count=8,
        ),
        Chunk(
            chunk_id="doc2:0003",
            doc_id="doc2",
            ord=3,
            text_md="Final chunk about optimization techniques.",
            char_count=40,
            token_count=6,
        ),
    ]

    session.add_all(chunks_doc1 + chunks_doc2)

    # Add dummy embeddings (deterministic)
    all_chunks = chunks_doc1 + chunks_doc2
    for chunk in all_chunks:
        # Create deterministic embeddings based on chunk text (384-dimensional to match dummy provider)
        text_hash = hash(chunk.text_md) % 1000

        # Create 384-dimensional embedding
        embedding = []
        for i in range(384):
            val = 0.1 + ((text_hash + i) % 100) * 0.001  # 0.1 to 0.199
            embedding.append(val)

        chunk_emb = ChunkEmbedding(
            chunk_id=chunk.chunk_id,
            provider="dummy",
            dim=384,
            embedding=embedding,
        )
        session.add(chunk_emb)

    session.commit()
    session.close()

    yield str(engine.url)

    # Cleanup (PostgreSQL test container handles this)
    engine.dispose()


def test_cosine_similarity():
    """Test cosine similarity computation."""
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    assert abs(cosine_sim(a, b) - 1.0) < 1e-6

    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0])
    assert abs(cosine_sim(a, b) - 0.0) < 1e-6

    a = np.array([1.0, 1.0, 0.0])
    b = np.array([1.0, 1.0, 0.0])
    assert abs(cosine_sim(a, b) - 1.0) < 1e-6


def test_top_k_ordering():
    """Test top-k selection with deterministic ordering."""
    query_vec = np.array([0.15, 0.25, 0.35])

    candidates = [
        ("chunk1", "doc1", "text1", [0.1, 0.2, 0.3], "Title1", "url1"),
        (
            "chunk2",
            "doc1",
            "text2",
            [0.2, 0.3, 0.4],
            "Title1",
            "url1",
        ),  # Higher similarity
        (
            "chunk3",
            "doc2",
            "text3",
            [0.1, 0.2, 0.3],
            "Title2",
            "url2",
        ),  # Same as chunk1
    ]

    results = top_k(query_vec, candidates, k=3)

    assert len(results) == 3
    # Results should be ordered by score desc, then doc_id, then chunk_id
    assert results[0]["chunk_id"] == "chunk2"  # Highest score
    # For ties between chunk1 and chunk3 (same embedding), doc1 < doc2
    assert results[1]["chunk_id"] == "chunk1"  # doc1 comes before doc2
    assert results[2]["chunk_id"] == "chunk3"


def test_retriever_deterministic_ordering(temp_db):
    """Test that retriever produces deterministic ordering."""
    retriever = DenseRetriever(db_url=temp_db, provider_name="dummy")

    # Run the same query multiple times
    query = "testing algorithms"

    results1 = retriever.search(query, top_k=6)
    results2 = retriever.search(query, top_k=6)

    # Results should be identical
    assert len(results1) == len(results2)
    assert len(results1) == 6  # All chunks

    for r1, r2 in zip(results1, results2):
        assert r1["chunk_id"] == r2["chunk_id"]
        assert abs(r1["score"] - r2["score"]) < 1e-6
        assert r1["doc_id"] == r2["doc_id"]


def test_retriever_score_ordering(temp_db):
    """Test that results are properly ordered by score."""
    retriever = DenseRetriever(db_url=temp_db, provider_name="dummy")

    results = retriever.search("testing algorithms", top_k=6)

    # Scores should be in descending order
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)

    # For same scores, should be ordered by doc_id then chunk_id
    for i in range(len(results) - 1):
        if abs(results[i]["score"] - results[i + 1]["score"]) < 1e-6:
            # Same score - check doc_id ordering
            if results[i]["doc_id"] == results[i + 1]["doc_id"]:
                # Same doc - check chunk_id ordering
                assert results[i]["chunk_id"] <= results[i + 1]["chunk_id"]
            else:
                assert results[i]["doc_id"] <= results[i + 1]["doc_id"]


def test_retriever_metadata(temp_db):
    """Test that retriever returns proper metadata."""
    retriever = DenseRetriever(db_url=temp_db, provider_name="dummy")

    results = retriever.search("testing", top_k=3)

    assert len(results) == 3

    for result in results:
        assert "chunk_id" in result
        assert "doc_id" in result
        assert "text_md" in result
        assert "title" in result
        assert "url" in result
        assert "score" in result

        assert isinstance(result["score"], float)
        assert 0.0 <= result["score"] <= 1.0
        assert result["title"] in ["Test Document 1", "Test Document 2"]
        assert result["url"].startswith("http://example.com/")


def test_retriever_empty_results():
    """Test retriever behavior with empty database."""
    from trailblazer.db.engine import get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)

    retriever = DenseRetriever(db_url=str(engine.url), provider_name="dummy")
    results = retriever.search("test query", top_k=5)
    assert results == []
