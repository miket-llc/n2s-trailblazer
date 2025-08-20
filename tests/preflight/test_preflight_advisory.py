"""Test preflight advisory mode behavior."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from trailblazer.pipeline.steps.embed.preflight import run_preflight_check


@pytest.fixture
def mock_run_with_low_quality():
    """Create a mock run with 40% low-quality documents."""
    with tempfile.TemporaryDirectory() as temp_dir:
        run_dir = Path(temp_dir) / "test_run"
        run_dir.mkdir()

        # Create enrich directory
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir()

        # Create enriched.jsonl with mixed quality
        enriched_file = enrich_dir / "enriched.jsonl"
        docs = []

        # 6 high-quality docs (quality_score >= 0.60)
        for i in range(6):
            docs.append(
                {
                    "id": f"doc_{i}",
                    "quality_score": 0.8,
                    "title": f"Good Doc {i}",
                }
            )

        # 4 low-quality docs (quality_score < 0.60) = 40%
        for i in range(6, 10):
            docs.append(
                {
                    "id": f"doc_{i}",
                    "quality_score": 0.4,
                    "title": f"Poor Doc {i}",
                }
            )

        with open(enriched_file, "w") as f:
            for doc in docs:
                f.write(json.dumps(doc) + "\n")

        # Create chunk directory
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()

        # Create chunks.ndjson
        chunks_file = chunk_dir / "chunks.ndjson"
        with open(chunks_file, "w") as f:
            for i in range(10):
                chunk = {
                    "chunk_id": f"doc_{i}:0000",
                    "doc_id": f"doc_{i}",
                    "text_md": f"Content for doc {i}",
                    "token_count": 100,
                }
                f.write(json.dumps(chunk) + "\n")

        yield run_dir.name


def test_preflight_advisory_mode_passes_with_low_quality(
    mock_run_with_low_quality,
):
    """Test that advisory mode passes even with 40% low-quality docs."""
    with patch("trailblazer.pipeline.steps.embed.preflight.runs") as mock_runs:
        mock_runs.return_value = Path(mock_run_with_low_quality).parent

        result = run_preflight_check(
            run_id=mock_run_with_low_quality,
            quality_advisory=True,
            quality_hard_gate=False,
            min_quality=0.60,
        )

        # Should be READY despite 40% low quality
        assert result["status"] == "READY"
        assert result["docTotals"]["all"] == 10
        assert result["docTotals"]["embeddable"] == 6  # 60% are embeddable
        assert result["docTotals"]["skipped"] == 4  # 40% are skipped
        assert result["advisory"]["quality"] is True

        # Check that doc_skiplist.json was created
        skiplist_file = (
            Path(mock_run_with_low_quality) / "preflight" / "doc_skiplist.json"
        )
        assert skiplist_file.exists()

        with open(skiplist_file) as f:
            skiplist = json.load(f)

        assert len(skiplist["skip"]) == 4
        assert skiplist["reason"] == "quality_below_min"


def test_preflight_hard_gate_mode_blocks_with_low_quality(
    mock_run_with_low_quality,
):
    """Test that hard gate mode blocks when quality threshold is exceeded."""
    with patch("trailblazer.pipeline.steps.embed.preflight.runs") as mock_runs:
        mock_runs.return_value = Path(mock_run_with_low_quality).parent

        result = run_preflight_check(
            run_id=mock_run_with_low_quality,
            quality_advisory=False,
            quality_hard_gate=True,
            min_quality=0.60,
            max_below_threshold_pct=0.20,  # 40% exceeds this threshold
        )

        # Should be BLOCKED due to quality gate
        assert result["status"] == "BLOCKED"
        assert "QUALITY_GATE" in result["reasons"]
        assert result["docTotals"]["all"] == 10
        assert result["docTotals"]["embeddable"] == 6
        assert result["docTotals"]["skipped"] == 4
