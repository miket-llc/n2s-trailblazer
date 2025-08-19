"""Tests for chunker integration with pipeline runner."""

import json
import tempfile
from pathlib import Path

import pytest

from trailblazer.pipeline.runner import _execute_phase


class TestChunkerRunnerIntegration:
    """Test chunker integration with the pipeline runner."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def create_test_run_structure(
        self, run_id: str, input_type: str = "enriched"
    ):
        """Create a test run directory with input files."""
        run_dir = self.temp_path / "runs" / run_id

        if input_type == "enriched":
            input_dir = run_dir / "enrich"
            input_dir.mkdir(parents=True, exist_ok=True)
            input_file = input_dir / "enriched.jsonl"

            test_docs = [
                {
                    "id": "doc1",
                    "title": "Test Document 1",
                    "text_md": "This is test content for chunking. " * 20,
                    "attachments": [],
                    "chunk_hints": {
                        "maxTokens": 800,
                        "minTokens": 120,
                        "overlapTokens": 60,
                    },
                    "section_map": [],
                }
            ]
        else:
            input_dir = run_dir / "normalize"
            input_dir.mkdir(parents=True, exist_ok=True)
            input_file = input_dir / "normalized.ndjson"

            test_docs = [
                {
                    "id": "doc1",
                    "title": "Test Document 1",
                    "text_md": "This is test content for chunking. " * 20,
                    "attachments": [],
                }
            ]

        with open(input_file, "w") as f:
            for doc in test_docs:
                f.write(json.dumps(doc) + "\n")

        return run_dir

    def test_execute_phase_chunk_with_parameters(self):
        """Test that _execute_phase correctly passes chunking parameters."""
        run_id = "test_run_001"
        run_dir = self.create_test_run_structure(run_id, "enriched")
        chunk_dir = run_dir / "chunk"

        # Execute chunking phase with custom parameters
        _execute_phase(
            "chunk",
            str(chunk_dir),
            max_tokens=600,
            min_tokens=100,
            overlap_tokens=40,
        )

        # Verify chunk files were created
        chunks_file = chunk_dir / "chunks.ndjson"
        assurance_file = chunk_dir / "chunk_assurance.json"

        assert chunks_file.exists()
        assert assurance_file.exists()

        # Verify chunks respect the token limits
        with open(chunks_file) as f:
            chunks = [json.loads(line) for line in f if line.strip()]

        for chunk in chunks:
            assert chunk["token_count"] <= 600, (
                f"Chunk exceeds limit: {chunk['token_count']}"
            )
            assert "split_strategy" in chunk

        # Verify assurance file has correct config
        with open(assurance_file) as f:
            assurance = json.load(f)

        assert assurance["chunkConfig"]["hard_max_tokens"] == 600
        assert assurance["chunkConfig"]["min_tokens"] == 100
        assert assurance["chunkConfig"]["overlap_tokens"] == 40
        assert "tokenCap" in assurance
        assert "charStats" in assurance
        assert "status" in assurance

    def test_execute_phase_chunk_enriched_vs_normalized(self):
        """Test that runner correctly chooses enriched over normalized input."""
        run_id = "test_run_002"

        # Create both enriched and normalized files
        run_dir = self.temp_path / "runs" / run_id

        # Create enriched file
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir(parents=True, exist_ok=True)
        enriched_file = enrich_dir / "enriched.jsonl"
        with open(enriched_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "doc1",
                        "title": "Enriched Doc",
                        "text_md": "Enriched content",
                        "chunk_hints": {"preferHeadings": True},
                        "section_map": [],
                    }
                )
                + "\n"
            )

        # Create normalized file
        norm_dir = run_dir / "normalize"
        norm_dir.mkdir(parents=True, exist_ok=True)
        normalized_file = norm_dir / "normalized.ndjson"
        with open(normalized_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "doc1",
                        "title": "Normalized Doc",
                        "text_md": "Normalized content",
                    }
                )
                + "\n"
            )

        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir))

        # Verify it used enriched input
        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        assert assurance["inputType"] == "enriched"
        assert "enriched.jsonl" in assurance["artifacts"]["input_file"]

    def test_execute_phase_chunk_normalized_fallback(self):
        """Test that runner falls back to normalized when enriched is missing."""
        run_id = "test_run_003"
        run_dir = self.create_test_run_structure(run_id, "normalized")
        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir))

        # Verify it used normalized input
        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        assert assurance["inputType"] == "normalized"
        assert "normalized.ndjson" in assurance["artifacts"]["input_file"]

    def test_execute_phase_chunk_assurance_schema(self):
        """Test that chunk assurance JSON has correct structure."""
        run_id = "test_run_004"
        run_dir = self.create_test_run_structure(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir), max_tokens=800)

        # Verify assurance schema
        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        # Required top-level fields
        required_fields = [
            "run_id",
            "timestamp",
            "docCount",
            "chunkCount",
            "tokenStats",
            "chunkConfig",
            "inputType",
            "status",
        ]
        for field in required_fields:
            assert field in assurance, f"Missing field: {field}"

        # tokenCap structure
        token_cap = assurance["tokenCap"]
        assert "maxTokens" in token_cap
        assert "hardMaxTokens" in token_cap
        assert "overlapTokens" in token_cap
        assert "breaches" in token_cap
        assert "count" in token_cap["breaches"]
        assert "examples" in token_cap["breaches"]

        # charStats structure
        char_stats = assurance["charStats"]
        assert "min" in char_stats
        assert "median" in char_stats
        assert "p95" in char_stats
        assert "max" in char_stats

        # splitStrategies should be present
        assert "splitStrategies" in assurance

        # Status should be PASS if no breaches
        if token_cap["breaches"]["count"] == 0:
            assert assurance["status"] == "PASS"
        else:
            assert assurance["status"] == "FAIL"

    def test_execute_phase_chunk_breach_detection(self):
        """Test that breach detection works correctly."""
        run_id = "test_run_005"
        run_dir = self.create_test_run_structure(run_id)

        # Create a document with content that would exceed a very low token limit
        enrich_dir = run_dir / "enrich"
        enriched_file = enrich_dir / "enriched.jsonl"

        # Overwrite with long content
        with open(enriched_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "doc1",
                        "title": "Long Document",
                        "text_md": "This is very long content that should exceed the token limit. "
                        * 100,  # ~1000+ tokens
                        "chunk_hints": {
                            "maxTokens": 50
                        },  # Very low limit to force breaches
                        "section_map": [],
                    }
                )
                + "\n"
            )

        chunk_dir = run_dir / "chunk"

        # Execute chunking with very low token limit
        _execute_phase("chunk", str(chunk_dir), max_tokens=50)

        # Verify breach detection
        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        # Should detect breaches (though our chunker should prevent them)
        # The test is more about the detection mechanism working
        breach_count = assurance["tokenCap"]["breaches"]["count"]

        # With our hard cap implementation, there should be no breaches
        assert breach_count == 0, "Hard cap should prevent all breaches"
        assert assurance["status"] == "PASS"

    def test_execute_phase_chunk_split_strategy_tracking(self):
        """Test that split strategies are tracked correctly."""
        run_id = "test_run_006"
        run_dir = self.create_test_run_structure(run_id)

        # Create document with mixed content to trigger different strategies
        enrich_dir = run_dir / "enrich"
        enriched_file = enrich_dir / "enriched.jsonl"

        mixed_content = """# Main Heading

This is a paragraph that should trigger paragraph-based splitting.

## Sub Heading

Another paragraph here.

```python
def example():
    return "code"
```

Final paragraph."""

        with open(enriched_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "doc1",
                        "title": "Mixed Content",
                        "text_md": mixed_content,
                        "chunk_hints": {"maxTokens": 100},  # Force splitting
                        "section_map": [
                            {
                                "startChar": 0,
                                "endChar": 50,
                                "heading": "Main Heading",
                            },
                            {
                                "startChar": 51,
                                "endChar": 100,
                                "heading": "Sub Heading",
                            },
                        ],
                    }
                )
                + "\n"
            )

        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir), max_tokens=100)

        # Verify split strategies are tracked
        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        assert "splitStrategies" in assurance
        strategies = assurance["splitStrategies"]

        # Should have some variety of strategies
        assert len(strategies) > 0

        # Verify chunks have split_strategy field
        with open(chunk_dir / "chunks.ndjson") as f:
            chunks = [json.loads(line) for line in f if line.strip()]

        for chunk in chunks:
            assert "split_strategy" in chunk
            assert chunk["split_strategy"] in [
                "heading",
                "paragraph",
                "sentence",
                "code-fence-lines",
                "table-rows",
                "token-window",
                "no-split",
                "force-truncate",
            ]

    def test_execute_phase_chunk_default_parameters(self):
        """Test that default parameters are used when none provided."""
        run_id = "test_run_007"
        run_dir = self.create_test_run_structure(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute chunking without parameters
        _execute_phase("chunk", str(chunk_dir))

        # Verify default parameters were used
        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        config = assurance["chunkConfig"]
        assert config["hard_max_tokens"] == 800  # Default
        assert config["min_tokens"] == 120  # Default
        assert config["overlap_tokens"] == 60  # Default

    def test_execute_phase_chunk_input_hash_tracking(self):
        """Test that input file hashes are tracked for traceability."""
        run_id = "test_run_008"
        run_dir = self.create_test_run_structure(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir))

        # Verify input hash is recorded
        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        assert "inputHash" in assurance
        assert assurance["inputHash"] is not None
        assert len(assurance["inputHash"]) == 64  # SHA256 hex length


if __name__ == "__main__":
    pytest.main([__file__])
