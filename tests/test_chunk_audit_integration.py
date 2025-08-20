"""Integration tests for chunk audit and rechunk CLI commands."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from trailblazer.cli.main import app
from trailblazer.pipeline.steps.chunk.engine import chunk_document
from trailblazer.pipeline.steps.chunk.boundaries import count_tokens


class TestChunkAuditIntegration:
    """Integration tests for chunk audit and rechunk workflow."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def create_test_run_with_oversize_chunks(self, run_id: str) -> Path:
        """Create a test run directory with some oversize chunks."""
        run_dir = self.temp_path / "runs" / run_id
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        # Create chunks file with some oversize chunks
        chunks_file = chunk_dir / "chunks.ndjson"

        test_chunks = [
            {
                "chunk_id": f"{run_id}:0001",
                "doc_id": "doc1",
                "ord": 1,
                "text_md": "Short chunk content.",
                "char_count": 20,
                "token_count": 5,
                "chunk_type": "text",
                "meta": {},
                "split_strategy": "paragraph",
            },
            {
                "chunk_id": f"{run_id}:0002",
                "doc_id": "doc1",
                "ord": 2,
                "text_md": "This is a very long chunk that exceeds the token limit. "
                * 50,  # ~1000+ tokens
                "char_count": 2850,
                "token_count": 1200,  # Oversize!
                "chunk_type": "text",
                "meta": {},
                "split_strategy": "paragraph",
            },
            {
                "chunk_id": f"{run_id}:0003",
                "doc_id": "doc2",
                "ord": 1,
                "text_md": "Another oversize chunk with lots of repeated content. "
                * 40,  # ~800+ tokens
                "char_count": 2160,
                "token_count": 900,  # Oversize!
                "chunk_type": "text",
                "meta": {},
                "split_strategy": "paragraph",
            },
        ]

        with open(chunks_file, "w") as f:
            for chunk in test_chunks:
                f.write(json.dumps(chunk) + "\n")

        return run_dir

    def create_test_documents(self, run_id: str):
        """Create test enriched/normalized documents for rechunking."""
        run_dir = self.temp_path / "runs" / run_id

        # Create enriched document
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir(parents=True, exist_ok=True)
        enriched_file = enrich_dir / "enriched.jsonl"

        enriched_docs = [
            {
                "id": "doc1",
                "title": "Test Document 1",
                "text_md": "This is a very long document that will need to be chunked properly. "
                * 30,
                "attachments": [],
                "chunk_hints": {"preferHeadings": True},
                "section_map": [],
            },
            {
                "id": "doc2",
                "title": "Test Document 2",
                "text_md": "Another long document with content that needs proper chunking. "
                * 25,
                "attachments": [],
                "chunk_hints": {"preferHeadings": True},
                "section_map": [],
            },
        ]

        with open(enriched_file, "w") as f:
            for doc in enriched_docs:
                f.write(json.dumps(doc) + "\n")

    @patch("glob.glob")
    def test_chunk_audit_finds_oversize_chunks(self, mock_glob):
        """Test that chunk audit correctly identifies oversize chunks."""
        # Setup test data
        run_id = "test_run_001"
        run_dir = self.create_test_run_with_oversize_chunks(run_id)

        # Mock glob to return our test run
        mock_glob.return_value = [str(run_dir)]

        # Run chunk audit
        result = self.runner.invoke(
            app,
            [
                "chunk",
                "audit",
                "--runs-glob",
                str(self.temp_path / "runs" / "*"),
                "--max-tokens",
                "800",
                "--out-dir",
                str(self.temp_path / "chunk_audit"),
            ],
        )

        assert result.exit_code == 0

        # Check that audit files were created
        audit_dirs = list((self.temp_path / "chunk_audit").glob("*"))
        assert len(audit_dirs) == 1
        audit_dir = audit_dirs[0]

        # Check oversize.json
        oversize_file = audit_dir / "oversize.json"
        assert oversize_file.exists()

        with open(oversize_file) as f:
            oversize_data = json.load(f)

        # Should find 2 oversize chunks
        assert len(oversize_data) == 2

        # Check rechunk_targets.txt
        targets_file = audit_dir / "rechunk_targets.txt"
        assert targets_file.exists()

        with open(targets_file) as f:
            targets = f.read().strip().split("\n")

        # Should have 2 unique documents to rechunk
        assert len(targets) == 2
        assert f"{run_id},doc1" in targets
        assert f"{run_id},doc2" in targets

    def test_chunk_rechunk_fixes_oversize_chunks(self):
        """Test that rechunk command fixes oversize chunks using v2."""
        # Setup test data
        run_id = "test_run_002"
        run_dir = self.create_test_run_with_oversize_chunks(run_id)
        self.create_test_documents(run_id)

        # Create targets file
        targets_file = self.temp_path / "rechunk_targets.txt"
        with open(targets_file, "w") as f:
            f.write(f"{run_id},doc1\n")
            f.write(f"{run_id},doc2\n")

        # Run rechunk command
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            result = self.runner.invoke(
                app,
                [
                    "chunk",
                    "rechunk",
                    "--targets-file",
                    str(targets_file),
                    "--max-tokens",
                    "800",
                    "--min-tokens",
                    "120",
                    "--overlap-tokens",
                    "60",
                    "--out-dir",
                    str(self.temp_path / "chunk_fix"),
                ],
            )

        assert result.exit_code == 0

        # Check that chunks were updated
        chunks_file = run_dir / "chunk" / "chunks.ndjson"
        assert chunks_file.exists()

        # Read updated chunks
        updated_chunks = []
        with open(chunks_file) as f:
            for line in f:
                if line.strip():
                    updated_chunks.append(json.loads(line))

        # Verify no chunks exceed token limit
        for chunk in updated_chunks:
            assert (
                chunk["token_count"] <= 800
            ), f"Chunk {chunk['chunk_id']} still exceeds limit: {chunk['token_count']}"

        # Should have more chunks than before (due to splitting)
        assert len(updated_chunks) > 3

    def test_audit_rechunk_full_workflow(self):
        """Test the complete audit -> rechunk -> re-audit workflow."""
        # Setup test data with oversize chunks
        run_id = "test_run_003"
        run_dir = self.create_test_run_with_oversize_chunks(run_id)
        self.create_test_documents(run_id)

        # Step 1: Initial audit
        with patch("glob.glob", return_value=[str(run_dir)]):
            audit_result = self.runner.invoke(
                app,
                [
                    "chunk",
                    "audit",
                    "--runs-glob",
                    str(self.temp_path / "runs" / "*"),
                    "--max-tokens",
                    "800",
                    "--out-dir",
                    str(self.temp_path / "chunk_audit"),
                ],
            )

        assert audit_result.exit_code == 0

        # Get audit results
        audit_dirs = list((self.temp_path / "chunk_audit").glob("*"))
        audit_dir = audit_dirs[0]
        targets_file = audit_dir / "rechunk_targets.txt"

        # Step 2: Rechunk the problematic documents
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            rechunk_result = self.runner.invoke(
                app,
                [
                    "chunk",
                    "rechunk",
                    "--targets-file",
                    str(targets_file),
                    "--max-tokens",
                    "800",
                    "--min-tokens",
                    "120",
                    "--overlap-tokens",
                    "60",
                    "--out-dir",
                    str(self.temp_path / "chunk_fix"),
                ],
            )

        assert rechunk_result.exit_code == 0

        # Step 3: Re-audit to verify fixes
        with patch("glob.glob", return_value=[str(run_dir)]):
            reaudit_result = self.runner.invoke(
                app,
                [
                    "chunk",
                    "audit",
                    "--runs-glob",
                    str(self.temp_path / "runs" / "*"),
                    "--max-tokens",
                    "800",
                    "--out-dir",
                    str(self.temp_path / "chunk_audit_final"),
                ],
            )

        assert reaudit_result.exit_code == 0

        # Check final audit results - should have 0 oversize chunks
        final_audit_dirs = list(
            (self.temp_path / "chunk_audit_final").glob("*")
        )
        final_audit_dir = final_audit_dirs[0]

        final_oversize_file = final_audit_dir / "oversize.json"
        with open(final_oversize_file) as f:
            final_oversize_data = json.load(f)

        assert (
            len(final_oversize_data) == 0
        ), "Should have no oversize chunks after rechunking"

    def test_chunk_audit_empty_runs(self):
        """Test chunk audit with no runs or no chunk files."""
        # Run audit on empty directory
        result = self.runner.invoke(
            app,
            [
                "chunk",
                "audit",
                "--runs-glob",
                str(self.temp_path / "nonexistent" / "*"),
                "--max-tokens",
                "800",
                "--out-dir",
                str(self.temp_path / "empty_audit"),
            ],
        )

        assert result.exit_code == 0

        # Should still create audit files with zero results
        audit_dirs = list((self.temp_path / "empty_audit").glob("*"))
        assert len(audit_dirs) == 1

        audit_dir = audit_dirs[0]
        oversize_file = audit_dir / "oversize.json"

        with open(oversize_file) as f:
            oversize_data = json.load(f)

        assert len(oversize_data) == 0

    def test_chunk_rechunk_missing_targets(self):
        """Test rechunk command with missing targets file."""
        result = self.runner.invoke(
            app,
            [
                "chunk",
                "rechunk",
                "--targets-file",
                str(self.temp_path / "nonexistent.txt"),
                "--max-tokens",
                "800",
            ],
        )

        assert result.exit_code == 1  # Should fail

    def test_chunk_rechunk_missing_documents(self):
        """Test rechunk when source documents are missing."""
        # Create targets file but no source documents
        targets_file = self.temp_path / "targets.txt"
        with open(targets_file, "w") as f:
            f.write("missing_run,missing_doc\n")

        result = self.runner.invoke(
            app,
            [
                "chunk",
                "rechunk",
                "--targets-file",
                str(targets_file),
                "--max-tokens",
                "800",
                "--out-dir",
                str(self.temp_path / "chunk_fix"),
            ],
        )

        assert result.exit_code == 0  # Should complete but skip missing docs

        # Check that skipped docs were logged
        fix_dirs = list((self.temp_path / "chunk_fix").glob("*"))
        fix_dir = fix_dirs[0]

        skipped_file = fix_dir / "skipped_docs.jsonl"
        assert skipped_file.exists()

        with open(skipped_file) as f:
            skipped_data = [json.loads(line) for line in f if line.strip()]

        assert len(skipped_data) == 1
        assert "missing_doc" in skipped_data[0]["doc_id"]

    def test_v2_chunking_produces_valid_chunks(self):
        """Test that v2 chunking produces valid, compliant chunks."""
        # Test with various content types
        test_doc = """# Test Document

This is a regular paragraph with some content that should be chunked properly.

```python
def test_function():
    return "This is a code block"

def another_function():
    return "More code content here"
```

| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Data 1   | Data 2   | Data 3   |
| Row 2    | Row 2    | Row 2    |

Final paragraph with more content."""

        chunks = chunk_document(
            doc_id="test_doc",
            text_md=test_doc,
            source_system="test",
            hard_max_tokens=150,
            min_tokens=30,
            overlap_tokens=20,
        )

        # Verify all chunks comply with hard cap
        for chunk in chunks:
            actual_tokens = count_tokens(chunk.text_md)
            assert (
                actual_tokens <= 150
            ), f"Chunk {chunk.chunk_id} has {actual_tokens} tokens"
            assert hasattr(chunk, "split_strategy")
            assert chunk.split_strategy in [
                "heading",
                "paragraph",
                "sentence",
                "code-fence-lines",
                "table-rows",
                "token-window",
                "no-split",
                "force-truncate",
            ]


if __name__ == "__main__":
    pytest.main([__file__])
