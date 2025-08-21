import pytest
from trailblazer.pipeline.steps.embed.provider import (
    DummyEmbedder,
    get_embedding_provider,
)


def test_dummy_embedder_deterministic():
    """Test that DummyEmbedder produces deterministic results."""
    embedder = DummyEmbedder(dim=384)

    text = "This is a test sentence for embedding."

    # Generate embedding multiple times
    embedding1 = embedder.embed(text)
    embedding2 = embedder.embed(text)

    # Should be identical
    assert embedding1 == embedding2
    assert len(embedding1) == 384

    # All values should be in [0, 1) range
    assert all(0 <= val < 1 for val in embedding1)


def test_dummy_embedder_different_texts():
    """Test that different texts produce different embeddings."""
    embedder = DummyEmbedder(dim=256)

    text1 = "First test sentence."
    text2 = "Second test sentence."

    embedding1 = embedder.embed(text1)
    embedding2 = embedder.embed(text2)

    # Should be different
    assert embedding1 != embedding2
    assert len(embedding1) == len(embedding2) == 256


def test_dummy_embedder_case_insensitive():
    """Test that embedder is case insensitive."""
    embedder = DummyEmbedder(dim=128)

    text1 = "Test Sentence"
    text2 = "test sentence"
    text3 = "TEST SENTENCE"

    embedding1 = embedder.embed(text1)
    embedding2 = embedder.embed(text2)
    embedding3 = embedder.embed(text3)

    # Should all be the same (case insensitive)
    assert embedding1 == embedding2 == embedding3


def test_dummy_embedder_whitespace_normalized():
    """Test that whitespace is normalized."""
    embedder = DummyEmbedder(dim=64)

    text1 = "test sentence"
    text2 = "  test sentence  "
    text3 = "\ttest sentence\n"

    embedding1 = embedder.embed(text1)
    embedding2 = embedder.embed(text2)
    embedding3 = embedder.embed(text3)

    # Should all be the same (whitespace normalized)
    assert embedding1 == embedding2 == embedding3


def test_dummy_embedder_batch():
    """Test batch embedding functionality."""
    embedder = DummyEmbedder(dim=100)

    texts = ["First sentence", "Second sentence", "Third sentence"]

    # Test batch processing
    batch_embeddings = embedder.embed_batch(texts)

    # Test individual processing
    individual_embeddings = [embedder.embed(text) for text in texts]

    # Should produce same results
    assert len(batch_embeddings) == len(individual_embeddings) == 3
    for batch_emb, ind_emb in zip(batch_embeddings, individual_embeddings):
        assert batch_emb == ind_emb
        assert len(batch_emb) == 100


def test_dummy_embedder_dimensions():
    """Test different embedding dimensions."""
    dimensions = [1, 10, 100, 384, 1536]
    text = "Test embedding dimensions"

    for dim in dimensions:
        embedder = DummyEmbedder(dim=dim)
        embedding = embedder.embed(text)

        assert len(embedding) == dim
        assert embedder.dimension == dim
        assert all(0 <= val < 1 for val in embedding)


def test_dummy_embedder_empty_text():
    """Test handling of empty text."""
    embedder = DummyEmbedder(dim=50)

    empty_embedding = embedder.embed("")
    whitespace_embedding = embedder.embed("   ")

    # Both should produce the same result (normalized to empty)
    assert empty_embedding == whitespace_embedding
    assert len(empty_embedding) == 50


def test_dummy_embedder_provider_properties():
    """Test provider properties."""
    embedder = DummyEmbedder(dim=256)

    assert embedder.provider_name == "dummy"
    assert embedder.dimension == 256


def test_get_embedding_provider_dummy():
    """Test getting dummy provider via factory function."""
    # Explicitly request dummy provider
    provider = get_embedding_provider("dummy")
    assert provider.provider_name == "dummy"
    assert isinstance(provider, DummyEmbedder)

    # Explicit dummy
    provider2 = get_embedding_provider("dummy")
    assert provider2.provider_name == "dummy"
    assert isinstance(provider2, DummyEmbedder)


def test_get_embedding_provider_default():
    """Test getting default provider via env var."""
    # Default will use EMBED_PROVIDER env var, which may be set to openai
    import os

    provider = get_embedding_provider()
    expected_provider = os.getenv("EMBED_PROVIDER", "dummy")
    assert provider.provider_name == expected_provider


def test_get_embedding_provider_unknown():
    """Test error handling for unknown provider."""
    with pytest.raises(
        ValueError, match="Unknown embedding provider: unknown"
    ):
        get_embedding_provider("unknown")


def test_dummy_embedder_unicode():
    """Test handling of unicode text."""
    embedder = DummyEmbedder(dim=128)

    texts = [
        "English text",
        "Texte français",
        "Texto español",
        "日本語テキスト",
        "Русский текст",
    ]

    embeddings = [embedder.embed(text) for text in texts]

    # All should be valid embeddings
    for embedding in embeddings:
        assert len(embedding) == 128
        assert all(0 <= val < 1 for val in embedding)

    # All should be different
    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            assert embeddings[i] != embeddings[j]


def test_dummy_embedder_long_text():
    """Test handling of very long text."""
    embedder = DummyEmbedder(dim=256)

    # Create very long text
    long_text = "This is a test sentence. " * 1000

    embedding = embedder.embed(long_text)

    assert len(embedding) == 256
    assert all(0 <= val < 1 for val in embedding)


def test_dummy_embedder_stability_across_instances():
    """Test that different instances produce same results for same text."""
    text = "Stability test"

    embedder1 = DummyEmbedder(dim=200)
    embedder2 = DummyEmbedder(dim=200)

    embedding1 = embedder1.embed(text)
    embedding2 = embedder2.embed(text)

    # Should be identical even across different instances
    assert embedding1 == embedding2
