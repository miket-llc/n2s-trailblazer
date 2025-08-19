"""Tests for audit -> rechunk -> re-audit integration workflow."""

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from trailblazer.cli.main import app


class TestAuditRechunkIntegration:
    """Test end-to-end audit -> rechunk -> re-audit workflow."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def create_run_with_oversize_chunks(self, run_id: str):
        """Create a run with intentionally oversize chunks."""
        run_dir = self.temp_path / "runs" / run_id

        # Create enrich directory with source data for rechunking
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir(parents=True, exist_ok=True)

        enriched_file = enrich_dir / "enriched.jsonl"
        with open(enriched_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "oversize_doc",
                        "title": "Large Document",
                        "text_md": " ".join(["word"] * 500),  # Large content
                        "attachments": [],
                        "chunk_hints": {"preferHeadings": True},
                        "section_map": [],
                        "url": "https://example.com/large",
                        "source_system": "confluence",
                        "labels": ["test"],
                        "space": {"id": "123", "key": "TEST"},
                    }
                )
                + "\n"
            )

        # Create chunk directory with oversize chunks
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        chunks_file = chunk_dir / "chunks.ndjson"
        with open(chunks_file, "w") as f:
            # Intentionally oversize chunk
            f.write(
                json.dumps(
                    {
                        "chunk_id": "oversize_doc:0000",
                        "text_md": " ".join(
                            ["word"] * 500
                        ),  # Will exceed 800 tokens
                        "token_count": 1000,  # Intentionally wrong
                        "char_count": 2500,
                        "ord": 0,
                        "split_strategy": "no-split",
                        "meta": {},
                    }
                )
                + "\n"
            )

        return run_dir

    def test_end_to_end_audit_rechunk_audit(self):
        """Test complete workflow: audit -> rechunk -> re-audit shows zero oversize."""

        # Step 1: Create run with oversize chunks
        run_id = "audit_rechunk_test"
        self.create_run_with_oversize_chunks(run_id)

        # Step 2: Run initial audit
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

        # Find audit output directory
        audit_dirs = list((self.temp_path / "chunk_audit").glob("*"))
        assert len(audit_dirs) == 1
        audit_dir = audit_dirs[0]

        # Should have found oversize chunks
        rechunk_targets_file = audit_dir / "rechunk_targets.txt"
        assert rechunk_targets_file.exists()

        with open(rechunk_targets_file) as f:
            targets = f.read().strip()
        assert f"{run_id},oversize_doc" in targets

        # Step 3: Run rechunk
        rechunk_result = self.runner.invoke(
            app,
            [
                "chunk",
                "rechunk",
                "--targets-file",
                str(rechunk_targets_file),
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

        # Step 4: Run audit again
        audit2_result = self.runner.invoke(
            app,
            [
                "chunk",
                "audit",
                "--runs-glob",
                str(self.temp_path / "runs" / "*"),
                "--max-tokens",
                "800",
                "--out-dir",
                str(self.temp_path / "chunk_audit2"),
            ],
        )

        assert audit2_result.exit_code == 0

        # Find second audit output
        audit2_dirs = list((self.temp_path / "chunk_audit2").glob("*"))
        assert len(audit2_dirs) == 1
        audit2_dir = audit2_dirs[0]

        # Should show zero oversize chunks now
        oversize_file = audit2_dir / "oversize.json"
        if oversize_file.exists():
            with open(oversize_file) as f:
                oversize_data = json.load(f)
            assert len(oversize_data) == 0, (
                "Should have no oversize chunks after rechunking"
            )

        # Check that chunks were actually updated
        chunks_file = (
            self.temp_path / "runs" / run_id / "chunk" / "chunks.ndjson"
        )
        with open(chunks_file) as f:
            chunks = [json.loads(line) for line in f if line.strip()]

        # Should now have multiple smaller chunks instead of one large one
        assert len(chunks) > 1, (
            "Should have split large chunk into multiple chunks"
        )

        # All chunks should be within token limit
        from trailblazer.chunking.boundaries import count_tokens

        for chunk in chunks:
            actual_tokens = count_tokens(chunk["text_md"])
            assert actual_tokens <= 800, (
                f"Chunk still exceeds limit: {actual_tokens} tokens"
            )
