"""Tests for chunker assurance JSON schema and breach detection."""

import json
import tempfile
from pathlib import Path

import pytest

from trailblazer.pipeline.runner import _execute_phase


class TestChunkerAssuranceSchema:
    """Test chunker assurance JSON schema and breach detection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def create_test_run(self, run_id: str, content_length: str = "normal"):
        """Create a test run with specified content length."""
        run_dir = self.temp_path / "runs" / run_id
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir(parents=True, exist_ok=True)

        if content_length == "short":
            text_content = "Short content for testing."
        elif content_length == "long":
            text_content = (
                "This is very long content that should be split into multiple chunks. "
                * 50
            )
        else:  # normal
            text_content = (
                "This is normal length content for testing chunking behavior. "
                * 10
            )

        enriched_file = enrich_dir / "enriched.jsonl"
        with open(enriched_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "doc1",
                        "title": "Test Document",
                        "text_md": text_content,
                        "attachments": [],
                        "chunk_hints": {"preferHeadings": True},
                        "section_map": [],
                    }
                )
                + "\n"
            )

        return run_dir

    def test_assurance_schema_structure(self):
        """Test that assurance JSON has correct structure."""
        run_id = "test_assurance_001"
        run_dir = self.create_test_run(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir), max_tokens=800)

        # Read assurance file
        assurance_file = chunk_dir / "chunk_assurance.json"
        assert assurance_file.exists()

        with open(assurance_file) as f:
            assurance = json.load(f)

        # Test top-level required fields
        required_top_level = [
            "run_id",
            "timestamp",
            "docCount",
            "chunkCount",
            "tokenStats",
            "chunkConfig",
            "inputType",
            "inputHash",
            "artifacts",
            "tokenCap",
            "charStats",
            "status",
        ]

        for field in required_top_level:
            assert field in assurance, f"Missing required field: {field}"

        # Test run_id matches
        assert assurance["run_id"] == run_id

        # Test counts are positive integers
        assert isinstance(assurance["docCount"], int)
        assert isinstance(assurance["chunkCount"], int)
        assert assurance["docCount"] > 0
        assert assurance["chunkCount"] > 0

        # Test timestamp format (ISO format)
        assert "T" in assurance["timestamp"]
        assert "Z" in assurance["timestamp"] or "+" in assurance["timestamp"]

    def test_token_cap_structure(self):
        """Test tokenCap structure and breach detection."""
        run_id = "test_token_cap_001"
        run_dir = self.create_test_run(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute with specific token limit
        _execute_phase(
            "chunk", str(chunk_dir), max_tokens=600, overlap_tokens=50
        )

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        token_cap = assurance["tokenCap"]

        # Test tokenCap structure
        required_token_cap_fields = [
            "maxTokens",
            "hardMaxTokens",
            "overlapTokens",
            "breaches",
        ]

        for field in required_token_cap_fields:
            assert field in token_cap, f"Missing tokenCap field: {field}"

        # Test values match parameters
        assert token_cap["maxTokens"] == 600
        assert token_cap["hardMaxTokens"] == 600
        assert token_cap["overlapTokens"] == 50

        # Test breaches structure
        breaches = token_cap["breaches"]
        assert "count" in breaches
        assert "examples" in breaches
        assert isinstance(breaches["count"], int)
        assert isinstance(breaches["examples"], list)
        assert breaches["count"] >= 0

        # With hard cap, should have no breaches
        assert breaches["count"] == 0, "Hard cap should prevent all breaches"

    def test_char_stats_structure(self):
        """Test charStats structure and calculations."""
        run_id = "test_char_stats_001"
        run_dir = self.create_test_run(run_id, "long")  # Use long content
        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase(
            "chunk", str(chunk_dir), max_tokens=200
        )  # Force multiple chunks

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        char_stats = assurance["charStats"]

        # Test charStats structure
        required_char_fields = ["min", "median", "p95", "max"]

        for field in required_char_fields:
            assert field in char_stats, f"Missing charStats field: {field}"
            assert isinstance(char_stats[field], int)
            assert char_stats[field] > 0

        # Test logical relationships
        assert char_stats["min"] <= char_stats["median"]
        assert char_stats["median"] <= char_stats["p95"]
        assert char_stats["p95"] <= char_stats["max"]

    def test_token_stats_structure(self):
        """Test tokenStats structure and calculations."""
        run_id = "test_token_stats_001"
        run_dir = self.create_test_run(run_id, "long")
        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir), max_tokens=300)

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        token_stats = assurance["tokenStats"]

        # Test tokenStats structure
        required_token_fields = [
            "count",
            "min",
            "median",
            "p95",
            "max",
            "total",
        ]

        for field in required_token_fields:
            assert field in token_stats, f"Missing tokenStats field: {field}"
            assert isinstance(token_stats[field], int)
            assert token_stats[field] > 0

        # Test logical relationships
        assert token_stats["min"] <= token_stats["median"]
        assert token_stats["median"] <= token_stats["p95"]
        assert token_stats["p95"] <= token_stats["max"]
        assert token_stats["count"] == assurance["chunkCount"]

        # Test that max doesn't exceed hard limit
        assert token_stats["max"] <= 300

    def test_split_strategies_tracking(self):
        """Test splitStrategies tracking and distribution."""
        run_id = "test_strategies_001"
        run_dir = self.create_test_run(run_id, "long")
        chunk_dir = run_dir / "chunk"

        # Execute chunking to force splits
        _execute_phase("chunk", str(chunk_dir), max_tokens=150)

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        # Should have splitStrategies
        assert "splitStrategies" in assurance
        strategies = assurance["splitStrategies"]

        # Should be a dictionary with strategy counts
        assert isinstance(strategies, dict)
        assert len(strategies) > 0

        # All strategies should be valid
        valid_strategies = {
            "heading",
            "paragraph",
            "sentence",
            "code-fence-lines",
            "table-rows",
            "token-window",
            "no-split",
            "force-truncate",
        }

        for strategy in strategies.keys():
            assert (
                strategy in valid_strategies
            ), f"Invalid strategy: {strategy}"

        # Counts should sum to total chunks
        total_strategy_count = sum(strategies.values())
        assert total_strategy_count == assurance["chunkCount"]

    def test_status_determination(self):
        """Test status determination based on breaches."""
        run_id = "test_status_001"
        run_dir = self.create_test_run(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute chunking with reasonable limits
        _execute_phase("chunk", str(chunk_dir), max_tokens=800)

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        # Status should be present
        assert "status" in assurance
        status = assurance["status"]
        assert status in ["PASS", "FAIL"]

        # Status should match breach count
        breach_count = assurance["tokenCap"]["breaches"]["count"]

        if breach_count == 0:
            assert status == "PASS"
        else:
            assert status == "FAIL"

    def test_chunk_config_tracking(self):
        """Test that chunk configuration is properly tracked."""
        run_id = "test_config_001"
        run_dir = self.create_test_run(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute with specific parameters
        custom_params = {
            "max_tokens": 750,
            "min_tokens": 100,
            "overlap_tokens": 45,
        }

        _execute_phase("chunk", str(chunk_dir), **custom_params)

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        chunk_config = assurance["chunkConfig"]

        # Test config structure
        required_config_fields = [
            "hard_max_tokens",
            "min_tokens",
            "overlap_tokens",
            "model",
        ]

        for field in required_config_fields:
            assert field in chunk_config, f"Missing chunkConfig field: {field}"

        # Test values match parameters
        assert chunk_config["hard_max_tokens"] == 750
        assert chunk_config["min_tokens"] == 100
        assert chunk_config["overlap_tokens"] == 45
        assert chunk_config["model"] == "text-embedding-3-small"

    def test_artifacts_tracking(self):
        """Test that artifacts are properly tracked."""
        run_id = "test_artifacts_001"
        run_dir = self.create_test_run(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir))

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        artifacts = assurance["artifacts"]

        # Test artifacts structure
        required_artifact_fields = [
            "chunks_file",
            "input_file",
            "normalized_file",
            "enriched_file",
        ]

        for field in required_artifact_fields:
            assert field in artifacts, f"Missing artifacts field: {field}"

        # Test that files actually exist where claimed
        chunks_file = Path(artifacts["chunks_file"])
        assert chunks_file.exists()

        input_file = Path(artifacts["input_file"])
        assert input_file.exists()

    def test_input_hash_consistency(self):
        """Test that input hash is consistent and changes with content."""
        run_id = "test_hash_001"
        run_dir = self.create_test_run(run_id)
        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir))

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance1 = json.load(f)

        hash1 = assurance1["inputHash"]
        assert hash1 is not None
        assert len(hash1) == 64  # SHA256 hex length

        # Modify input file
        enrich_dir = run_dir / "enrich"
        enriched_file = enrich_dir / "enriched.jsonl"
        with open(enriched_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "doc1",
                        "title": "Modified Document",
                        "text_md": "Modified content for hash testing.",
                        "attachments": [],
                    }
                )
                + "\n"
            )

        # Execute chunking again
        _execute_phase("chunk", str(chunk_dir))

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance2 = json.load(f)

        hash2 = assurance2["inputHash"]

        # Hash should be different
        assert hash1 != hash2

    def test_assurance_with_mixed_content(self):
        """Test assurance with mixed content types."""
        run_id = "test_mixed_001"
        run_dir = self.temp_path / "runs" / run_id
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir(parents=True, exist_ok=True)

        # Create document with mixed content
        mixed_content = """# Main Heading

Regular paragraph content here.

```python
def example_function():
    return "This is code content"
```

| Column 1 | Column 2 |
|----------|----------|
| Data 1   | Data 2   |
| Data 3   | Data 4   |

Final paragraph with more text."""

        enriched_file = enrich_dir / "enriched.jsonl"
        with open(enriched_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "doc1",
                        "title": "Mixed Content Document",
                        "text_md": mixed_content,
                        "attachments": [],
                        "chunk_hints": {"preferHeadings": True},
                        "section_map": [],
                    }
                )
                + "\n"
            )

        chunk_dir = run_dir / "chunk"

        # Execute chunking
        _execute_phase("chunk", str(chunk_dir), max_tokens=200)

        with open(chunk_dir / "chunk_assurance.json") as f:
            assurance = json.load(f)

        # Should have multiple split strategies
        strategies = assurance["splitStrategies"]
        assert (
            len(strategies) > 1
        ), "Mixed content should use multiple strategies"

        # Should still have no breaches
        assert assurance["tokenCap"]["breaches"]["count"] == 0
        assert assurance["status"] == "PASS"


if __name__ == "__main__":
    pytest.main([__file__])
