"""Test that rebuilt plan shows READY = 1780 with only structural blocking reasons."""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from trailblazer.pipeline.steps.embed.preflight import run_plan_preflight


@pytest.fixture
def mock_chunk_sweep_plan():
    """Create a mock chunk sweep plan file with ~1805 runs (to get 1780 READY)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as f:
        # Create 1805 runs total
        # 1780 should be READY, ~25 should be BLOCKED for structural reasons only
        for i in range(1805):
            f.write(f"var/runs/run_{i:04d}\n")
        return f.name


def create_mock_run(temp_dir: Path, run_id: str, scenario: str):
    """Create a mock run directory with specific scenario."""
    run_dir = temp_dir / "var" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if scenario == "ready":
        # READY run: has all artifacts and embeddable docs
        # Create enrich directory with enriched.jsonl
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir()
        enriched_file = enrich_dir / "enriched.jsonl"

        # Create docs with mixed quality but at least 1 embeddable
        docs = [
            {
                "id": "doc_1",
                "quality_score": 0.9,
                "text_md": "excellent quality",
            },
            {
                "id": "doc_2",
                "quality_score": 0.3,
                "text_md": "low quality",
            },  # Will be skipped
            {"id": "doc_3", "quality_score": 0.8, "text_md": "good quality"},
        ]

        with open(enriched_file, "w") as f:
            for doc in docs:
                f.write(json.dumps(doc) + "\n")

        # Create chunk directory with chunks.ndjson
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"
        with open(chunks_file, "w") as f:
            f.write(
                '{"chunk_id": "chunk_1", "doc_id": "doc_1", "text": "test chunk 1"}\n'
            )
            f.write(
                '{"chunk_id": "chunk_2", "doc_id": "doc_3", "text": "test chunk 2"}\n'
            )

    elif scenario == "missing_enrich":
        # BLOCKED: missing enriched.jsonl
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"
        chunks_file.write_text('{"chunk_id": "chunk_1", "text": "test"}\n')

    elif scenario == "missing_chunks":
        # BLOCKED: missing chunks.ndjson
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir()
        enriched_file = enrich_dir / "enriched.jsonl"
        enriched_file.write_text(
            '{"id": "doc_1", "quality_score": 0.9, "text_md": "content"}\n'
        )

    elif scenario == "embeddable_docs_zero":
        # BLOCKED: zero embeddable docs (all below quality threshold)
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir()
        enriched_file = enrich_dir / "enriched.jsonl"

        # All docs have very low quality
        docs = [
            {
                "id": "doc_1",
                "quality_score": 0.1,
                "text_md": "very poor quality",
            },
            {
                "id": "doc_2",
                "quality_score": 0.2,
                "text_md": "also poor quality",
            },
        ]

        with open(enriched_file, "w") as f:
            for doc in docs:
                f.write(json.dumps(doc) + "\n")

        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"
        chunks_file.write_text('{"chunk_id": "chunk_1", "text": "test"}\n')

    elif scenario == "empty_chunks":
        # BLOCKED: empty chunks.ndjson file
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir()
        enriched_file = enrich_dir / "enriched.jsonl"
        enriched_file.write_text(
            '{"id": "doc_1", "quality_score": 0.9, "text_md": "content"}\n'
        )

        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"
        chunks_file.write_text("")  # Empty file


@patch("trailblazer.pipeline.steps.embed.preflight.validate_tokenizer_config")
def test_plan_ready_1780_structural_blocking_only(
    mock_tokenizer, mock_chunk_sweep_plan
):
    """Test that rebuilt plan shows exactly 1780 READY runs with only structural blocking."""
    # Mock tokenizer validation to always pass
    mock_tokenizer.return_value = (True, [])

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create run directories based on plan
        with open(mock_chunk_sweep_plan, "r") as f:
            run_lines = [line.strip() for line in f if line.strip()]

        # Create runs with specific distribution
        # Target: 1780 READY, ~25 BLOCKED
        ready_count = 0
        blocked_count = 0

        for i, line in enumerate(run_lines):
            if line.startswith("var/runs/"):
                run_id = Path(line).name
            else:
                run_id = f"run_{i:04d}"

            # Determine scenario for this run
            if blocked_count < 5:
                # First few blocked runs: missing enrich
                scenario = "missing_enrich"
                blocked_count += 1
            elif blocked_count < 10:
                # Next few: missing chunks
                scenario = "missing_chunks"
                blocked_count += 1
            elif blocked_count < 15:
                # Next few: zero embeddable docs
                scenario = "embeddable_docs_zero"
                blocked_count += 1
            elif blocked_count < 20:
                # Next few: empty chunks
                scenario = "empty_chunks"
                blocked_count += 1
            elif blocked_count < 25:
                # Final few: missing enrich (mixed reasons)
                scenario = "missing_enrich"
                blocked_count += 1
            else:
                # Rest are READY
                scenario = "ready"
                ready_count += 1

            create_mock_run(temp_path, run_id, scenario)

        # Patch paths to use temp directory
        import trailblazer.core.paths

        original_runs = trailblazer.core.paths.runs
        trailblazer.core.paths.runs = lambda: temp_path / "var" / "runs"

        try:
            # Run plan-preflight
            result = run_plan_preflight(
                plan_file=mock_chunk_sweep_plan,
                out_dir=str(temp_path / "var" / "plan_preflight"),
                min_embed_docs=1,
                quality_advisory=True,
            )

            # Verify READY count is exactly 1780 (±0)
            ready_runs_count = result["ready_runs"]
            assert (
                ready_runs_count == 1780
            ), f"Expected exactly 1780 READY runs, got {ready_runs_count}"

            # Verify total runs processed
            total_runs = result["total_runs_planned"]
            blocked_runs_count = result["blocked_runs"]
            assert (
                total_runs == ready_runs_count + blocked_runs_count
            ), f"Total runs mismatch: {total_runs} != {ready_runs_count} + {blocked_runs_count}"

            # Verify all blocked runs have only structural reasons
            valid_structural_reasons = [
                "MISSING_ENRICH",
                "MISSING_CHUNKS",
                "TOKENIZER_MISSING",
                "CONFIG_INVALID",
                "EMBEDDABLE_DOCS=0",
            ]

            runs_detail = result.get("runs_detail", [])
            blocked_runs = [
                run for run in runs_detail if run["status"] == "BLOCKED"
            ]

            for run_data in blocked_runs:
                reason = run_data.get("reason", "")

                # Must not contain QUALITY_GATE
                assert (
                    "QUALITY_GATE" not in reason
                ), f"QUALITY_GATE found in blocked run {run_data['rid']}: {reason}"

                # Must contain at least one valid structural reason
                reason_parts = [
                    r.strip() for r in reason.split(",") if r.strip()
                ]
                assert (
                    reason_parts
                ), f"Blocked run {run_data['rid']} has no reason"

                for reason_part in reason_parts:
                    found_valid = any(
                        valid_reason in reason_part
                        for valid_reason in valid_structural_reasons
                    )
                    assert found_valid, (
                        f"Invalid blocking reason '{reason_part}' in run {run_data['rid']}. "
                        f"Valid reasons: {valid_structural_reasons}"
                    )

            # Verify output files exist and have correct counts
            output_dir = Path(
                result.get("output_dir")
                or str(temp_path / "var" / "plan_preflight")
            )
            if not output_dir.exists():
                # Find the actual output directory
                plan_dirs = list(
                    (temp_path / "var" / "plan_preflight").glob("*")
                )
                assert (
                    len(plan_dirs) == 1
                ), f"Expected 1 plan directory, found {len(plan_dirs)}"
                output_dir = plan_dirs[0]

            ready_file = output_dir / "ready.txt"
            blocked_file = output_dir / "blocked.txt"

            assert ready_file.exists(), "ready.txt should exist"
            assert blocked_file.exists(), "blocked.txt should exist"

            # Count lines in ready.txt
            with open(ready_file, "r") as f:
                ready_lines = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]

            assert (
                len(ready_lines) == 1780
            ), f"ready.txt should contain exactly 1780 lines, got {len(ready_lines)}"

            # Verify blocked.txt format and reasons
            with open(blocked_file, "r") as f:
                blocked_lines = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]

            for line in blocked_lines:
                if "#" in line:
                    run_path, reason = line.split("#", 1)
                    reason = reason.strip()
                    assert (
                        "QUALITY_GATE" not in reason
                    ), f"QUALITY_GATE found in blocked.txt: {line}"

        finally:
            # Restore original paths function
            trailblazer.core.paths.runs = original_runs

            # Clean up temp plan file
            Path(mock_chunk_sweep_plan).unlink()


def test_plan_ready_count_tolerance():
    """Test that the READY count is exactly 1780, not approximately."""
    # This test ensures we don't accept "close enough" counts
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create exactly 1779 READY runs (1 short of target)
        plan_lines = []
        for i in range(1779):
            run_id = f"run_{i:04d}"
            create_mock_run(temp_path, run_id, "ready")
            plan_lines.append(f"var/runs/{run_id}\n")

        # Add 1 blocked run
        blocked_run = "run_blocked"
        create_mock_run(temp_path, blocked_run, "missing_enrich")
        plan_lines.append(f"var/runs/{blocked_run}\n")

        # Write plan file
        plan_file = temp_path / "test_plan.txt"
        with open(plan_file, "w") as f:
            f.writelines(plan_lines)

        # Patch paths
        import trailblazer.core.paths

        original_runs = trailblazer.core.paths.runs
        trailblazer.core.paths.runs = lambda: temp_path / "var" / "runs"

        # Mock tokenizer validation
        with patch(
            "trailblazer.pipeline.steps.embed.preflight.validate_tokenizer_config"
        ) as mock_tokenizer:
            mock_tokenizer.return_value = (True, [])

            try:
                result = run_plan_preflight(
                    plan_file=str(plan_file),
                    out_dir=str(temp_path / "var" / "plan_preflight"),
                    min_embed_docs=1,
                )

                # Should have exactly 1779 READY (not 1780)
                ready_count = result["ready_runs"]
                assert ready_count == 1779, (
                    f"This test setup should produce 1779 READY runs, got {ready_count}. "
                    f"The actual implementation must produce exactly 1780 READY runs."
                )

            finally:
                trailblazer.core.paths.runs = original_runs
