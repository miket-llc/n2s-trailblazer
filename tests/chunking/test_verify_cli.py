"""Tests for chunk verify CLI command."""

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from trailblazer.cli.main import app


class TestVerifyCLI:
    """Test chunk verify CLI command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def create_test_run_with_violations(self, run_id: str):
        """Create a test run with intentional violations."""
        run_dir = self.temp_path / "runs" / run_id
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        chunks_file = chunk_dir / "chunks.ndjson"

        # Create chunks with violations
        chunks = [
            # Normal chunk
            {
                "chunk_id": f"{run_id}:0000",
                "text_md": "This is normal content.",
                "token_count": 50,
                "char_count": 25,
                "ord": 0,
                "split_strategy": "no-split",
                "title": "Test Document",
                "url": "https://example.com",
                "source_system": "confluence",
            },
            # Oversize chunk (intentional)
            {
                "chunk_id": f"{run_id}:0001",
                "text_md": " ".join(["word"] * 300),  # Will exceed 800 tokens
                "token_count": 1000,  # Intentionally wrong
                "char_count": 1500,
                "ord": 1,
                "split_strategy": "token-window",
                "title": "Oversize Document",
                "url": "https://example.com/oversize",
                "source_system": "confluence",
            },
            # Missing source_system
            {
                "chunk_id": f"{run_id}:0002",
                "text_md": "Content without source system.",
                "token_count": 30,
                "char_count": 35,
                "ord": 2,
                "split_strategy": "no-split",
                "title": "Missing Source",
                "url": "https://example.com/missing",
                # source_system missing
            },
        ]

        with open(chunks_file, "w") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk) + "\n")

        return run_dir

    def test_chunk_verify_finds_violations(self):
        """Test that chunk verify finds both oversize and missing traceability violations."""
        # Create test run with violations
        run_id = "test_run_violations"
        self.create_test_run_with_violations(run_id)

        # Run chunk verify
        result = self.runner.invoke(
            app,
            [
                "chunk",
                "verify",
                "--runs-glob",
                str(self.temp_path / "runs" / "*"),
                "--max-tokens",
                "800",
                "--require-traceability",
                "true",
                "--out-dir",
                str(self.temp_path / "chunk_verify"),
            ],
        )

        # Should exit with code 1 (violations found)
        assert result.exit_code == 1

        # Check that output files were created
        verify_dirs = list((self.temp_path / "chunk_verify").glob("*"))
        assert len(verify_dirs) == 1
        verify_dir = verify_dirs[0]

        # Should have breaches.json
        breaches_file = verify_dir / "breaches.json"
        assert breaches_file.exists()

        with open(breaches_file) as f:
            breaches = json.load(f)
        assert len(breaches) == 1  # One oversize chunk
        assert breaches[0]["chunk_id"] == f"{run_id}:0001"

        # Should have missing_traceability.json
        missing_file = verify_dir / "missing_traceability.json"
        assert missing_file.exists()

        with open(missing_file) as f:
            missing = json.load(f)
        assert len(missing) == 1  # One chunk missing source_system
        assert missing[0]["chunk_id"] == f"{run_id}:0002"

        # Should have report files
        assert (verify_dir / "report.json").exists()
        assert (verify_dir / "report.md").exists()
        assert (verify_dir / "log.out").exists()

    def test_chunk_verify_passes_clean_run(self):
        """Test that chunk verify passes for clean runs without violations."""
        # Create clean test run
        run_id = "test_run_clean"
        run_dir = self.temp_path / "runs" / run_id
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        chunks_file = chunk_dir / "chunks.ndjson"

        # Create clean chunks
        chunks = [
            {
                "chunk_id": f"{run_id}:0000",
                "text_md": "This is clean content.",
                "token_count": 50,
                "char_count": 25,
                "ord": 0,
                "split_strategy": "no-split",
                "title": "Clean Document",
                "url": "https://example.com/clean",
                "source_system": "confluence",
            }
        ]

        with open(chunks_file, "w") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk) + "\n")

        # Run chunk verify
        result = self.runner.invoke(
            app,
            [
                "chunk",
                "verify",
                "--runs-glob",
                str(self.temp_path / "runs" / "*"),
                "--max-tokens",
                "800",
                "--require-traceability",
                "true",
                "--out-dir",
                str(self.temp_path / "chunk_verify"),
            ],
        )

        # Should exit with code 0 (success)
        assert result.exit_code == 0

        # Check report
        verify_dirs = list((self.temp_path / "chunk_verify").glob("*"))
        assert len(verify_dirs) == 1
        verify_dir = verify_dirs[0]

        report_file = verify_dir / "report.json"
        assert report_file.exists()

        with open(report_file) as f:
            report = json.load(f)

        assert report["status"] == "PASS"
        assert report["violations"]["oversize_chunks"] == 0
        assert report["violations"]["missing_traceability"] == 0
