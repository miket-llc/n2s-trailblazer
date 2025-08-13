from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Generate embedding for given text."""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding dimension."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier."""
        pass


class DummyEmbedder(EmbeddingProvider):
    """Deterministic dummy embedder for testing (no network required)."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        """Generate deterministic embedding from SHA256 hash."""
        # Normalize text to ensure determinism
        normalized_text = text.strip().lower()

        # Generate hash
        hash_obj = hashlib.sha256(normalized_text.encode("utf-8"))
        hash_bytes = hash_obj.digest()

        # Convert hash to float array in [0, 1)
        # Repeat hash if needed to fill dimension
        needed_bytes = self.dim * 4  # 4 bytes per float32
        extended_bytes = (
            hash_bytes * ((needed_bytes // len(hash_bytes)) + 1)
        )[:needed_bytes]

        # Convert to float32 array
        int_array = np.frombuffer(extended_bytes, dtype=np.uint32)
        float_array = int_array.astype(np.float32) / (
            2**32
        )  # Normalize to [0, 1)

        return float_array[: self.dim].tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for batch of texts."""
        return [self.embed(text) for text in texts]

    @property
    def dimension(self) -> int:
        return self.dim

    @property
    def provider_name(self) -> str:
        return "dummy"


class OpenAIEmbedder(EmbeddingProvider):
    """OpenAI embedding provider (requires API key)."""

    def __init__(self, model: str = "text-embedding-3-small", dim: int = 1536):
        self.model = model
        self.dim = dim
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

    def embed(self, text: str) -> List[float]:
        """Generate embedding using OpenAI API."""
        try:
            import openai  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "openai package required for OpenAI embeddings: pip install openai"
            )

        client = openai.OpenAI(api_key=self.api_key)
        response = client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=(
                self.dim if self.model.startswith("text-embedding-3") else None
            ),
        )
        return response.data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for batch of texts."""
        try:
            import openai  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "openai package required for OpenAI embeddings: pip install openai"
            )

        client = openai.OpenAI(api_key=self.api_key)
        response = client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=(
                self.dim if self.model.startswith("text-embedding-3") else None
            ),
        )
        return [data.embedding for data in response.data]

    @property
    def dimension(self) -> int:
        return self.dim

    @property
    def provider_name(self) -> str:
        return "openai"


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Sentence Transformers local model embedder."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or os.getenv(
            "SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2"
        )
        self._model = None
        self._dim = None

    @property
    def model(self):
        """Lazy load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
            except ImportError:
                raise ImportError(
                    "sentence-transformers package required: pip install sentence-transformers"
                )

            self._model = SentenceTransformer(self.model_name)
            # Cache dimension
            self._dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed(self, text: str) -> List[float]:
        """Generate embedding using local sentence transformer."""
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for batch of texts."""
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    @property
    def dimension(self) -> int:
        if self._dim is None:
            # Trigger model loading to get dimension
            _ = self.model
        return self._dim or 0

    @property
    def provider_name(self) -> str:
        return "sentencetransformers"


def get_embedding_provider(
    provider_name: Optional[str] = None,
) -> EmbeddingProvider:
    """
    Get embedding provider based on configuration.

    Args:
        provider_name: Provider name ("dummy", "openai", "sentencetransformers")
                      or None to use EMBED_PROVIDER env var (default: "dummy")

    Returns:
        EmbeddingProvider instance
    """
    provider_name = provider_name or os.getenv("EMBED_PROVIDER", "dummy")
    assert provider_name  # Ensure it's not None after fallback

    if provider_name == "dummy":
        dim = int(os.getenv("EMBED_DUMMY_DIM", "384"))
        return DummyEmbedder(dim=dim)
    elif provider_name == "openai":
        model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
        dim = int(os.getenv("OPENAI_EMBED_DIM", "1536"))
        return OpenAIEmbedder(model=model, dim=dim)
    elif provider_name == "sentencetransformers":
        model = os.getenv("SENTENCE_TRANSFORMER_MODEL")  # Can be None
        return SentenceTransformerEmbedder(model_name=model)  # type: ignore[arg-type]
    else:
        raise ValueError(f"Unknown embedding provider: {provider_name}")
