"""
Integration tests for embed manifest functionality.

This module tests the end-to-end behavior:
- Manifest creation after embedding
- Diff detection between runs
- Skip behavior for unchanged runs
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from trailblazer.pipeline.steps.embed.manifest import (
    CONTENT_CHANGE,
    MODEL_CHANGE,
    compare_manifests,
    compute_current_state,
    find_last_manifest,
    load_manifest,
    write_embed_manifest,
)

# Mark all tests as integration tests (need database)
pytestmark = pytest.mark.integration


@patch("trailblazer.core.paths.runs")
@patch("trailblazer.pipeline.steps.embed.manifest.get_git_commit")
@patch("trailblazer.pipeline.steps.embed.manifest.get_tokenizer_info")
def test_embed_then_reembed_unchanged(mock_tokenizer, mock_git, mock_runs):
    """Test that embedding twice with identical inputs produces identical manifests."""
    # Setup mocks
    mock_git.return_value = "stable_commit_hash"
    mock_tokenizer.return_value = {"name": "tiktoken", "version": "0.5.0"}

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "test_run"
        mock_runs.return_value = Path(tmpdir)

        # Create mock files
        enrich_dir = run_dir / "enrich"
        chunk_dir = run_dir / "chunk"
        enrich_dir.mkdir(parents=True)
        chunk_dir.mkdir(parents=True)

        # Create stable mock data
        with open(enrich_dir / "enriched.jsonl", "w") as f:
            f.write(
                '{"id": "doc1", "chunk_hints": {"maxTokens": 800, "minTokens": 120, "preferHeadings": true}}\n'
            )

        with open(enrich_dir / "fingerprints.jsonl", "w") as f:
            f.write(
                '{"id": "doc1", "fingerprint_sha256": "stable_fingerprint"}\n'
            )

        with open(chunk_dir / "chunks.ndjson", "w") as f:
            f.write(
                '{"chunk_id": "doc1_chunk1", "token_count": 100, "content_hash": "stable_hash1"}\n'
            )
            f.write(
                '{"chunk_id": "doc1_chunk2", "token_count": 150, "content_hash": "stable_hash2"}\n'
            )

        # First embedding
        manifest1_path = write_embed_manifest(
            "test_run", "openai", "text-embedding-3-small", 1536, 50
        )
        manifest1 = load_manifest(manifest1_path)

        # Second embedding (simulating re-run with identical inputs)
        manifest2_path = write_embed_manifest(
            "test_run", "openai", "text-embedding-3-small", 1536, 50
        )
        manifest2 = load_manifest(manifest2_path)

        # Manifests should be identical except for timestamp
        assert manifest1["runId"] == manifest2["runId"]
        assert manifest1["gitCommit"] == manifest2["gitCommit"]
        assert manifest1["provider"] == manifest2["provider"]
        assert manifest1["model"] == manifest2["model"]
        assert manifest1["dimension"] == manifest2["dimension"]
        assert manifest1["tokenizer"] == manifest2["tokenizer"]
        assert manifest1["enricherVersion"] == manifest2["enricherVersion"]
        assert manifest1["chunkerVersion"] == manifest2["chunkerVersion"]
        assert manifest1["chunkConfig"] == manifest2["chunkConfig"]
        assert manifest1["docFingerprints"] == manifest2["docFingerprints"]
        assert manifest1["chunkSetHash"] == manifest2["chunkSetHash"]
        assert manifest1["chunksEmbedded"] == manifest2["chunksEmbedded"]
        assert manifest1["totalChunks"] == manifest2["totalChunks"]

        # Timestamps will be different but both should be valid ISO format
        assert manifest1["timestamp"] != manifest2["timestamp"]

        # Compare manifests should show no changes
        has_changes, reasons = compare_manifests(manifest2, manifest1)
        assert not has_changes
        assert len(reasons) == 0


@patch("trailblazer.core.paths.runs")
@patch("trailblazer.pipeline.steps.embed.manifest.get_git_commit")
@patch("trailblazer.pipeline.steps.embed.manifest.get_tokenizer_info")
def test_detect_content_change(mock_tokenizer, mock_git, mock_runs):
    """Test that content changes are detected correctly."""
    # Setup mocks
    mock_git.return_value = "stable_commit_hash"
    mock_tokenizer.return_value = {"name": "tiktoken", "version": "0.5.0"}

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "test_run"
        mock_runs.return_value = Path(tmpdir)

        # Create mock files
        enrich_dir = run_dir / "enrich"
        chunk_dir = run_dir / "chunk"
        enrich_dir.mkdir(parents=True)
        chunk_dir.mkdir(parents=True)

        # Create initial mock data
        with open(enrich_dir / "enriched.jsonl", "w") as f:
            f.write(
                '{"id": "doc1", "chunk_hints": {"maxTokens": 800, "minTokens": 120, "preferHeadings": true}}\n'
            )

        with open(enrich_dir / "fingerprints.jsonl", "w") as f:
            f.write('{"id": "doc1", "fingerprint_sha256": "fingerprint1"}\n')

        with open(chunk_dir / "chunks.ndjson", "w") as f:
            f.write(
                '{"chunk_id": "doc1_chunk1", "token_count": 100, "content_hash": "hash1"}\n'
            )

        # Create initial manifest
        manifest1_path = write_embed_manifest(
            "test_run", "openai", "text-embedding-3-small", 1536, 25
        )
        manifest1 = load_manifest(manifest1_path)

        # Simulate content change by updating chunks
        with open(chunk_dir / "chunks.ndjson", "w") as f:
            f.write(
                '{"chunk_id": "doc1_chunk1", "token_count": 100, "content_hash": "hash1_changed"}\n'
            )
            f.write(
                '{"chunk_id": "doc1_chunk2", "token_count": 150, "content_hash": "hash2_new"}\n'
            )

        # Create new manifest with changed content
        manifest2_path = write_embed_manifest(
            "test_run", "openai", "text-embedding-3-small", 1536, 30
        )
        manifest2 = load_manifest(manifest2_path)

        # Compare manifests should show content change
        has_changes, reasons = compare_manifests(manifest2, manifest1)
        assert has_changes
        assert CONTENT_CHANGE in reasons
        assert manifest1["chunkSetHash"] != manifest2["chunkSetHash"]


@patch("trailblazer.core.paths.runs")
@patch("trailblazer.pipeline.steps.embed.manifest.get_git_commit")
@patch("trailblazer.pipeline.steps.embed.manifest.get_tokenizer_info")
def test_detect_model_change(mock_tokenizer, mock_git, mock_runs):
    """Test that model changes are detected correctly."""
    # Setup mocks
    mock_git.return_value = "stable_commit_hash"
    mock_tokenizer.return_value = {"name": "tiktoken", "version": "0.5.0"}

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "test_run"
        mock_runs.return_value = Path(tmpdir)

        # Create mock files
        enrich_dir = run_dir / "enrich"
        chunk_dir = run_dir / "chunk"
        enrich_dir.mkdir(parents=True)
        chunk_dir.mkdir(parents=True)

        # Create stable mock data
        with open(enrich_dir / "enriched.jsonl", "w") as f:
            f.write(
                '{"id": "doc1", "chunk_hints": {"maxTokens": 800, "minTokens": 120, "preferHeadings": true}}\n'
            )

        with open(enrich_dir / "fingerprints.jsonl", "w") as f:
            f.write(
                '{"id": "doc1", "fingerprint_sha256": "stable_fingerprint"}\n'
            )

        with open(chunk_dir / "chunks.ndjson", "w") as f:
            f.write(
                '{"chunk_id": "doc1_chunk1", "token_count": 100, "content_hash": "stable_hash"}\n'
            )

        # Create initial manifest with small model
        manifest1_path = write_embed_manifest(
            "test_run", "openai", "text-embedding-3-small", 1536, 25
        )
        manifest1 = load_manifest(manifest1_path)

        # Compute current state with different model
        current_state = compute_current_state(
            "test_run", "openai", "text-embedding-3-large", 1536
        )

        # Compare should show model change
        has_changes, reasons = compare_manifests(current_state, manifest1)
        assert has_changes
        assert MODEL_CHANGE in reasons
        assert current_state["model"] == "text-embedding-3-large"
        assert manifest1["model"] == "text-embedding-3-small"


@patch("trailblazer.core.paths.runs")
def test_find_last_manifest(mock_runs):
    """Test finding the last manifest for a run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_runs.return_value = Path(tmpdir)

        # No manifest exists
        manifest_path = find_last_manifest("nonexistent_run")
        assert manifest_path is None

        # Create a manifest
        run_dir = Path(tmpdir) / "test_run"
        embed_dir = run_dir / "embed"
        embed_dir.mkdir(parents=True)

        manifest_file = embed_dir / "manifest.json"
        with open(manifest_file, "w") as f:
            json.dump({"runId": "test_run"}, f)

        # Should find the manifest
        found_path = find_last_manifest("test_run")
        assert found_path == manifest_file
        assert found_path.exists()


if __name__ == "__main__":
    pytest.main([__file__])
