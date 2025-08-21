"""
Tests for embed manifest functionality.

This module tests:
- Manifest creation and writing
- Deterministic hashing of chunk sets
- Diff detection between manifests
- All change reason types
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from trailblazer.pipeline.steps.embed.manifest import (
    CHUNK_CONFIG_CHANGE,
    CHUNKER_CHANGE,
    CONTENT_CHANGE,
    DIMENSION_CHANGE,
    MODEL_CHANGE,
    PROVIDER_CHANGE,
    TOKENIZER_CHANGE,
    compare_manifests,
    compute_chunk_set_hash,
    create_diff_report,
    create_embed_manifest,
    format_diff_as_markdown,
    get_component_versions,
    get_git_commit,
    get_tokenizer_info,
)

# Mark all tests as unit tests (business logic, no database)
pytestmark = pytest.mark.unit


def test_get_git_commit():
    """Test git commit retrieval."""
    commit = get_git_commit()
    # Should return either a valid commit hash or "unknown"
    assert isinstance(commit, str)
    assert len(commit) > 0
    # If it's a real commit, it should be a hex string
    if commit != "unknown":
        assert len(commit) == 40  # SHA-1 is 40 characters
        int(commit, 16)  # Should not raise ValueError


def test_get_tokenizer_info():
    """Test tokenizer info retrieval."""
    info = get_tokenizer_info()
    assert isinstance(info, dict)
    assert "name" in info
    assert "version" in info
    assert isinstance(info["name"], str)
    assert isinstance(info["version"], str)


def test_get_component_versions():
    """Test component version retrieval."""
    versions = get_component_versions()
    assert isinstance(versions, dict)
    assert "enricherVersion" in versions
    assert "chunkerVersion" in versions
    assert versions["enricherVersion"] == "v1"
    assert versions["chunkerVersion"] == "v1"


def test_compute_chunk_set_hash_deterministic():
    """Test that chunk set hash is deterministic."""
    chunks = [
        {
            "chunk_id": "doc1_chunk1",
            "token_count": 100,
            "content_hash": "abc123",
        },
        {
            "chunk_id": "doc1_chunk2",
            "token_count": 150,
            "content_hash": "def456",
        },
        {
            "chunk_id": "doc2_chunk1",
            "token_count": 200,
            "content_hash": "ghi789",
        },
    ]

    # Hash should be the same for same input
    hash1 = compute_chunk_set_hash(chunks)
    hash2 = compute_chunk_set_hash(chunks)
    assert hash1 == hash2

    # Hash should be the same regardless of input order (chunks are sorted internally)
    chunks_reordered = [
        {
            "chunk_id": "doc2_chunk1",
            "token_count": 200,
            "content_hash": "ghi789",
        },
        {
            "chunk_id": "doc1_chunk1",
            "token_count": 100,
            "content_hash": "abc123",
        },
        {
            "chunk_id": "doc1_chunk2",
            "token_count": 150,
            "content_hash": "def456",
        },
    ]
    hash3 = compute_chunk_set_hash(chunks_reordered)
    assert hash1 == hash3

    # Hash should be 64 characters (SHA256 hex)
    assert len(hash1) == 64
    assert all(c in "0123456789abcdef" for c in hash1)


def test_compute_chunk_set_hash_changes():
    """Test that chunk set hash changes when content changes."""
    chunks1 = [
        {
            "chunk_id": "doc1_chunk1",
            "token_count": 100,
            "content_hash": "abc123",
        },
    ]

    chunks2 = [
        {
            "chunk_id": "doc1_chunk1",
            "token_count": 100,
            "content_hash": "abc124",
        },  # Different hash
    ]

    chunks3 = [
        {
            "chunk_id": "doc1_chunk1",
            "token_count": 101,
            "content_hash": "abc123",
        },  # Different token count
    ]

    chunks4 = [
        {
            "chunk_id": "doc1_chunk2",
            "token_count": 100,
            "content_hash": "abc123",
        },  # Different chunk ID
    ]

    hash1 = compute_chunk_set_hash(chunks1)
    hash2 = compute_chunk_set_hash(chunks2)
    hash3 = compute_chunk_set_hash(chunks3)
    hash4 = compute_chunk_set_hash(chunks4)

    # All hashes should be different
    assert hash1 != hash2
    assert hash1 != hash3
    assert hash1 != hash4
    assert hash2 != hash3
    assert hash2 != hash4
    assert hash3 != hash4


def test_compare_manifests_no_changes():
    """Test manifest comparison with no changes."""
    manifest = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "abc123",
    }

    has_changes, reasons = compare_manifests(manifest, manifest)
    assert not has_changes
    assert len(reasons) == 0


def test_compare_manifests_provider_change():
    """Test manifest comparison with provider change."""
    current = {
        "provider": "sentencetransformers",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "abc123",
    }

    previous = current.copy()
    previous["provider"] = "openai"

    has_changes, reasons = compare_manifests(current, previous)
    assert has_changes
    assert PROVIDER_CHANGE in reasons
    assert len(reasons) == 1


def test_compare_manifests_model_change():
    """Test manifest comparison with model change."""
    current = {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "abc123",
    }

    previous = current.copy()
    previous["model"] = "text-embedding-3-small"

    has_changes, reasons = compare_manifests(current, previous)
    assert has_changes
    assert MODEL_CHANGE in reasons
    assert len(reasons) == 1


def test_compare_manifests_dimension_change():
    """Test manifest comparison with dimension change."""
    current = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 3072,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "abc123",
    }

    previous = current.copy()
    previous["dimension"] = 1536

    has_changes, reasons = compare_manifests(current, previous)
    assert has_changes
    assert DIMENSION_CHANGE in reasons
    assert len(reasons) == 1


def test_compare_manifests_tokenizer_change():
    """Test manifest comparison with tokenizer change."""
    current = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.6.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "abc123",
    }

    previous = current.copy()
    previous["tokenizer"] = {"name": "tiktoken", "version": "0.5.0"}

    has_changes, reasons = compare_manifests(current, previous)
    assert has_changes
    assert TOKENIZER_CHANGE in reasons
    assert len(reasons) == 1


def test_compare_manifests_chunker_change():
    """Test manifest comparison with chunker version change."""
    current = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v2",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "abc123",
    }

    previous = current.copy()
    previous["chunkerVersion"] = "v1"

    has_changes, reasons = compare_manifests(current, previous)
    assert has_changes
    assert CHUNKER_CHANGE in reasons
    assert len(reasons) == 1


def test_compare_manifests_chunk_config_change():
    """Test manifest comparison with chunk config change."""
    current = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 1000,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "abc123",
    }

    previous = current.copy()
    previous["chunkConfig"] = {
        "maxTokens": 800,
        "minTokens": 120,
        "preferHeadings": True,
    }

    has_changes, reasons = compare_manifests(current, previous)
    assert has_changes
    assert CHUNK_CONFIG_CHANGE in reasons
    assert len(reasons) == 1


def test_compare_manifests_content_change():
    """Test manifest comparison with content change."""
    current = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "def456",
    }

    previous = current.copy()
    previous["chunkSetHash"] = "abc123"

    has_changes, reasons = compare_manifests(current, previous)
    assert has_changes
    assert CONTENT_CHANGE in reasons
    assert len(reasons) == 1


def test_compare_manifests_multiple_changes():
    """Test manifest comparison with multiple changes."""
    current = {
        "provider": "sentencetransformers",
        "model": "different-model",
        "dimension": 768,
        "tokenizer": {"name": "tiktoken", "version": "0.6.0"},
        "chunkerVersion": "v2",
        "chunkConfig": {
            "maxTokens": 1000,
            "minTokens": 150,
            "preferHeadings": False,
        },
        "chunkSetHash": "xyz789",
    }

    previous = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "abc123",
    }

    has_changes, reasons = compare_manifests(current, previous)
    assert has_changes
    assert len(reasons) == 7  # All possible changes
    assert PROVIDER_CHANGE in reasons
    assert MODEL_CHANGE in reasons
    assert DIMENSION_CHANGE in reasons
    assert TOKENIZER_CHANGE in reasons
    assert CHUNKER_CHANGE in reasons
    assert CHUNK_CONFIG_CHANGE in reasons
    assert CONTENT_CHANGE in reasons


def test_create_diff_report():
    """Test diff report creation."""
    current = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
        "chunkerVersion": "v1",
        "chunkConfig": {
            "maxTokens": 800,
            "minTokens": 120,
            "preferHeadings": True,
        },
        "chunkSetHash": "def456",
        "totalChunks": 100,
    }

    previous = current.copy()
    previous["chunkSetHash"] = "abc123"
    previous["timestamp"] = "2024-01-01T00:00:00Z"

    diff_report = create_diff_report(
        "test_run", current, previous, True, [CONTENT_CHANGE]
    )

    assert diff_report["runId"] == "test_run"
    assert diff_report["changed"] is True
    assert diff_report["reasons"] == [CONTENT_CHANGE]
    assert "timestamp" in diff_report
    assert "current" in diff_report
    assert "previous" in diff_report
    assert diff_report["current"]["chunkSetHash"] == "def456"
    assert diff_report["previous"]["chunkSetHash"] == "abc123"


def test_format_diff_as_markdown():
    """Test diff report markdown formatting."""
    diff_report = {
        "runId": "test_run",
        "timestamp": "2024-01-01T12:00:00Z",
        "changed": True,
        "reasons": [CONTENT_CHANGE, MODEL_CHANGE],
        "current": {
            "provider": "openai",
            "model": "text-embedding-3-large",
            "dimension": 1536,
            "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
            "chunkerVersion": "v1",
            "chunkConfig": {
                "maxTokens": 800,
                "minTokens": 120,
                "preferHeadings": True,
            },
            "chunkSetHash": "def456789012",
            "totalChunks": 100,
        },
        "previous": {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "dimension": 1536,
            "tokenizer": {"name": "tiktoken", "version": "0.5.0"},
            "chunkerVersion": "v1",
            "chunkConfig": {
                "maxTokens": 800,
                "minTokens": 120,
                "preferHeadings": True,
            },
            "chunkSetHash": "abc123456789",
            "totalChunks": 95,
            "timestamp": "2024-01-01T00:00:00Z",
        },
    }

    markdown = format_diff_as_markdown(diff_report)

    assert "# Embed Diff Report: test_run" in markdown
    assert "**Changed:** True" in markdown
    assert "CONTENT_CHANGE, MODEL_CHANGE" in markdown
    assert "## Current State" in markdown
    assert "## Previous State" in markdown
    assert "text-embedding-3-large" in markdown
    assert "text-embedding-3-small" in markdown
    assert "def456789012..." in markdown  # Truncated hash
    assert "abc123456789..." in markdown  # Truncated hash


@patch("trailblazer.core.paths.runs")
@patch("trailblazer.pipeline.steps.embed.manifest.get_git_commit")
@patch("trailblazer.pipeline.steps.embed.manifest.get_tokenizer_info")
def test_create_embed_manifest(mock_tokenizer, mock_git, mock_runs):
    """Test embed manifest creation with mocked dependencies."""
    # Setup mocks
    mock_git.return_value = "abc123commit"
    mock_tokenizer.return_value = {"name": "tiktoken", "version": "0.5.0"}

    # Mock file system
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "test_run"
        mock_runs.return_value = Path(tmpdir)

        # Create mock files
        enrich_dir = run_dir / "enrich"
        chunk_dir = run_dir / "chunk"
        enrich_dir.mkdir(parents=True)
        chunk_dir.mkdir(parents=True)

        # Create mock enriched.jsonl
        with open(enrich_dir / "enriched.jsonl", "w") as f:
            f.write(
                '{"id": "doc1", "chunk_hints": {"maxTokens": 800, "minTokens": 120, "preferHeadings": true}}\n'
            )

        # Create mock fingerprints.jsonl
        with open(enrich_dir / "fingerprints.jsonl", "w") as f:
            f.write('{"id": "doc1", "fingerprint_sha256": "fingerprint1"}\n')

        # Create mock chunks.ndjson
        with open(chunk_dir / "chunks.ndjson", "w") as f:
            f.write(
                '{"chunk_id": "doc1_chunk1", "token_count": 100, "content_hash": "hash1"}\n'
            )
            f.write(
                '{"chunk_id": "doc1_chunk2", "token_count": 150, "content_hash": "hash2"}\n'
            )

        # Create manifest
        manifest = create_embed_manifest(
            "test_run", "openai", "text-embedding-3-small", 1536, 50
        )

        # Verify manifest structure
        assert manifest["runId"] == "test_run"
        assert manifest["gitCommit"] == "abc123commit"
        assert manifest["provider"] == "openai"
        assert manifest["model"] == "text-embedding-3-small"
        assert manifest["dimension"] == 1536
        assert manifest["tokenizer"] == {
            "name": "tiktoken",
            "version": "0.5.0",
        }
        assert manifest["enricherVersion"] == "v1"
        assert manifest["chunkerVersion"] == "v1"
        assert manifest["chunkConfig"]["maxTokens"] == 800
        assert manifest["docFingerprints"] == ["fingerprint1"]
        assert manifest["chunksEmbedded"] == 50
        assert manifest["totalChunks"] == 2
        assert "chunkSetHash" in manifest
        assert "timestamp" in manifest

        # Verify timestamp format
        datetime.fromisoformat(manifest["timestamp"].replace("Z", "+00:00"))


if __name__ == "__main__":
    pytest.main([__file__])
