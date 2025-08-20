"""Tests for selective re-embed functionality using enrichment fingerprints."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from trailblazer.pipeline.steps.embed.loader import (
    _determine_changed_docs,
    _load_fingerprints,
    _save_fingerprints_as_previous,
    load_normalized_to_db,
)


class TestFingerprintManagement:
    """Test fingerprint loading and comparison logic."""

    def test_load_fingerprints_empty_file(self):
        """Test loading fingerprints from non-existent file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fingerprints_path = temp_path / "fingerprints.jsonl"

            fingerprints = _load_fingerprints(fingerprints_path)
            assert fingerprints == {}

    def test_load_fingerprints_valid_file(self):
        """Test loading fingerprints from valid JSONL file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fingerprints_path = temp_path / "fingerprints.jsonl"

            # Create test fingerprints file
            test_data = [
                {
                    "id": "doc1",
                    "enrichment_version": "v1",
                    "fingerprint_sha256": "hash1",
                },
                {
                    "id": "doc2",
                    "enrichment_version": "v1",
                    "fingerprint_sha256": "hash2",
                },
                {
                    "id": "doc3",
                    "enrichment_version": "v1",
                    "fingerprint_sha256": "hash3",
                },
            ]

            with open(fingerprints_path, "w", encoding="utf-8") as f:
                for record in test_data:
                    f.write(json.dumps(record) + "\n")

            fingerprints = _load_fingerprints(fingerprints_path)

            expected = {"doc1": "hash1", "doc2": "hash2", "doc3": "hash3"}
            assert fingerprints == expected

    def test_load_fingerprints_malformed_lines(self):
        """Test loading fingerprints with some malformed lines."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fingerprints_path = temp_path / "fingerprints.jsonl"

            # Create file with mixed valid and invalid lines
            with open(fingerprints_path, "w", encoding="utf-8") as f:
                f.write('{"id": "doc1", "fingerprint_sha256": "hash1"}\n')
                f.write("invalid json line\n")
                f.write('{"id": "doc2", "fingerprint_sha256": "hash2"}\n')
                f.write('{"missing_id": "value"}\n')
                f.write('{"id": "doc3", "fingerprint_sha256": "hash3"}\n')

            # Should only load valid records, skip malformed ones
            fingerprints = _load_fingerprints(fingerprints_path)

            expected = {"doc1": "hash1", "doc2": "hash2", "doc3": "hash3"}
            assert fingerprints == expected

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_save_fingerprints_as_previous(self, mock_phase_dir):
        """Test saving fingerprints as previous version."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            enrich_dir = temp_path / "enrich"
            enrich_dir.mkdir()

            mock_phase_dir.return_value = enrich_dir

            # Create test fingerprints file
            fingerprints_path = enrich_dir / "fingerprints.jsonl"
            test_content = '{"id": "doc1", "fingerprint_sha256": "hash1"}\n'
            fingerprints_path.write_text(test_content)

            # Save as previous
            _save_fingerprints_as_previous("test-run")

            # Verify previous file was created
            prev_path = enrich_dir / "fingerprints.prev.jsonl"
            assert prev_path.exists()
            assert prev_path.read_text() == test_content


class TestChangedDocsDetermination:
    """Test logic for determining which documents have changed."""

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_determine_changed_docs_disabled(self, mock_phase_dir):
        """Test that when changed_only=False, all docs are processed."""
        result = _determine_changed_docs("test-run", changed_only=False)
        assert result is None

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_determine_changed_docs_no_fingerprints_file(self, mock_phase_dir):
        """Test error when fingerprints file doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            enrich_dir = temp_path / "enrich"
            enrich_dir.mkdir()

            mock_phase_dir.return_value = enrich_dir

            with pytest.raises(
                FileNotFoundError, match="Fingerprints file not found"
            ):
                _determine_changed_docs("test-run", changed_only=True)

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_determine_changed_docs_no_previous(self, mock_phase_dir):
        """Test that all docs are treated as changed when no previous fingerprints exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            enrich_dir = temp_path / "enrich"
            enrich_dir.mkdir()

            mock_phase_dir.return_value = enrich_dir

            # Create current fingerprints file
            fingerprints_path = enrich_dir / "fingerprints.jsonl"
            test_data = [
                {"id": "doc1", "fingerprint_sha256": "hash1"},
                {"id": "doc2", "fingerprint_sha256": "hash2"},
            ]

            with open(fingerprints_path, "w", encoding="utf-8") as f:
                for record in test_data:
                    f.write(json.dumps(record) + "\n")

            changed_docs = _determine_changed_docs(
                "test-run", changed_only=True
            )

            assert changed_docs == {"doc1", "doc2"}

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_determine_changed_docs_with_changes(self, mock_phase_dir):
        """Test identifying changed documents when previous fingerprints exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            enrich_dir = temp_path / "enrich"
            enrich_dir.mkdir()

            mock_phase_dir.return_value = enrich_dir

            # Create previous fingerprints
            prev_path = enrich_dir / "fingerprints.prev.jsonl"
            prev_data = [
                {"id": "doc1", "fingerprint_sha256": "hash1"},
                {"id": "doc2", "fingerprint_sha256": "hash2"},
                {"id": "doc3", "fingerprint_sha256": "hash3"},
            ]

            with open(prev_path, "w", encoding="utf-8") as f:
                for record in prev_data:
                    f.write(json.dumps(record) + "\n")

            # Create current fingerprints with some changes and additions
            current_path = enrich_dir / "fingerprints.jsonl"
            current_data = [
                {"id": "doc1", "fingerprint_sha256": "hash1"},  # Unchanged
                {"id": "doc2", "fingerprint_sha256": "hash2_new"},  # Changed
                {"id": "doc3", "fingerprint_sha256": "hash3"},  # Unchanged
                {"id": "doc4", "fingerprint_sha256": "hash4"},  # New
            ]

            with open(current_path, "w", encoding="utf-8") as f:
                for record in current_data:
                    f.write(json.dumps(record) + "\n")

            changed_docs = _determine_changed_docs(
                "test-run", changed_only=True
            )

            # Should include changed and new documents
            assert changed_docs == {"doc2", "doc4"}

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_determine_changed_docs_no_changes(self, mock_phase_dir):
        """Test when no documents have changed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            enrich_dir = temp_path / "enrich"
            enrich_dir.mkdir()

            mock_phase_dir.return_value = enrich_dir

            # Create identical fingerprints files
            test_data = [
                {"id": "doc1", "fingerprint_sha256": "hash1"},
                {"id": "doc2", "fingerprint_sha256": "hash2"},
            ]

            for filename in ["fingerprints.jsonl", "fingerprints.prev.jsonl"]:
                filepath = enrich_dir / filename
                with open(filepath, "w", encoding="utf-8") as f:
                    for record in test_data:
                        f.write(json.dumps(record) + "\n")

            changed_docs = _determine_changed_docs(
                "test-run", changed_only=True
            )

            # No documents should be marked as changed
            assert changed_docs == set()


class TestSelectiveReEmbedIntegration:
    """Integration tests for the selective re-embed functionality."""

    @patch("trailblazer.pipeline.steps.embed.loader.get_embedding_provider")
    @patch("trailblazer.pipeline.steps.embed.loader.get_session_factory")
    @patch("trailblazer.pipeline.steps.embed.loader._default_normalized_path")
    @patch("trailblazer.core.artifacts.phase_dir")
    def test_changed_only_filters_documents(
        self,
        mock_phase_dir,
        mock_norm_path,
        mock_session_factory,
        mock_provider,
    ):
        """Test that changed_only flag properly filters documents."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup normalized file
            normalized_file = temp_path / "normalized.ndjson"
            test_docs = [
                {
                    "id": "doc1",
                    "title": "Doc 1",
                    "text_md": "Content 1",
                    "source_system": "confluence",
                },
                {
                    "id": "doc2",
                    "title": "Doc 2",
                    "text_md": "Content 2",
                    "source_system": "confluence",
                },
                {
                    "id": "doc3",
                    "title": "Doc 3",
                    "text_md": "Content 3",
                    "source_system": "confluence",
                },
            ]

            with open(normalized_file, "w", encoding="utf-8") as f:
                for doc in test_docs:
                    f.write(json.dumps(doc) + "\n")

            # Setup fingerprints
            enrich_dir = temp_path / "enrich"
            enrich_dir.mkdir()

            # Previous fingerprints
            prev_path = enrich_dir / "fingerprints.prev.jsonl"
            prev_fingerprints = [
                {"id": "doc1", "fingerprint_sha256": "fp1"},
                {"id": "doc2", "fingerprint_sha256": "fp2"},
                {"id": "doc3", "fingerprint_sha256": "fp3"},
            ]

            with open(prev_path, "w", encoding="utf-8") as f:
                for fp in prev_fingerprints:
                    f.write(json.dumps(fp) + "\n")

            # Current fingerprints (only doc2 changed)
            current_path = enrich_dir / "fingerprints.jsonl"
            current_fingerprints = [
                {"id": "doc1", "fingerprint_sha256": "fp1"},  # Same
                {"id": "doc2", "fingerprint_sha256": "fp2_new"},  # Changed
                {"id": "doc3", "fingerprint_sha256": "fp3"},  # Same
            ]

            with open(current_path, "w", encoding="utf-8") as f:
                for fp in current_fingerprints:
                    f.write(json.dumps(fp) + "\n")

            # Setup mocks
            mock_norm_path.return_value = normalized_file
            mock_phase_dir.return_value = enrich_dir

            # Mock session and provider
            mock_session = mock_session_factory.return_value
            mock_session.__enter__ = lambda x: mock_session
            mock_session.__exit__ = lambda *args: None
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_session.commit.return_value = None

            mock_embedder = mock_provider.return_value
            mock_embedder.provider_name = "dummy"
            mock_embedder.dimension = 10

            # Test with changed_only=True
            metrics = load_normalized_to_db(
                run_id="test-run",
                provider_name="dummy",
                changed_only=True,
                max_docs=10,
            )

            # Should process only changed document (doc2)
            assert metrics["docs_changed"] == 1
            assert metrics["docs_unchanged"] == 2
            assert metrics["docs_total"] == 3

    @patch("trailblazer.pipeline.steps.embed.loader.get_embedding_provider")
    @patch("trailblazer.pipeline.steps.embed.loader.get_session_factory")
    @patch("trailblazer.pipeline.steps.embed.loader._default_normalized_path")
    @patch("trailblazer.core.artifacts.phase_dir")
    def test_changed_only_disabled_processes_all(
        self,
        mock_phase_dir,
        mock_norm_path,
        mock_session_factory,
        mock_provider,
    ):
        """Test that when changed_only=False, all documents are processed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup normalized file
            normalized_file = temp_path / "normalized.ndjson"
            test_docs = [
                {
                    "id": "doc1",
                    "title": "Doc 1",
                    "text_md": "Content 1",
                    "source_system": "confluence",
                },
                {
                    "id": "doc2",
                    "title": "Doc 2",
                    "text_md": "Content 2",
                    "source_system": "confluence",
                },
            ]

            with open(normalized_file, "w", encoding="utf-8") as f:
                for doc in test_docs:
                    f.write(json.dumps(doc) + "\n")

            # Setup mocks
            mock_norm_path.return_value = normalized_file

            # Mock session and provider
            mock_session = mock_session_factory.return_value
            mock_session.__enter__ = lambda x: mock_session
            mock_session.__exit__ = lambda *args: None
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_session.commit.return_value = None

            mock_embedder = mock_provider.return_value
            mock_embedder.provider_name = "dummy"
            mock_embedder.dimension = 10

            # Test with changed_only=False (default)
            metrics = load_normalized_to_db(
                run_id="test-run",
                provider_name="dummy",
                changed_only=False,
                max_docs=10,
            )

            # Should process all documents
            assert (
                metrics["docs_changed"] == 0
            )  # Not tracked when changed_only=False
            assert (
                metrics["docs_unchanged"] == 0
            )  # Not tracked when changed_only=False
            assert metrics["docs_total"] == 2
