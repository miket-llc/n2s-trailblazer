"""Policy test: QUALITY_GATE must never appear as a run-level blocking reason."""

import pytest
import tempfile
import json
from pathlib import Path

from trailblazer.pipeline.steps.embed.preflight import (
    run_preflight_check,
    run_plan_preflight,
)


def test_preflight_never_emits_quality_gate_reason():
    """Test that run_preflight_check never emits QUALITY_GATE as a blocking reason."""
    # Test with various scenarios that might trigger quality issues
    test_scenarios = [
        {
            "name": "high_below_threshold_pct",
            "quality_stats": {"belowThresholdPct": 0.8},  # 80% below threshold
            "embeddable_docs": 10,
            "expected_status": "READY",  # Should still be READY since quality is advisory
        },
        {
            "name": "zero_embeddable_docs",
            "quality_stats": {"belowThresholdPct": 0.0},
            "embeddable_docs": 0,
            "expected_status": "BLOCKED",
            "expected_reasons": [
                "EMBEDDABLE_DOCS=0"
            ],  # This is the only valid blocking reason
        },
        {
            "name": "low_quality_but_embeddable",
            "quality_stats": {"belowThresholdPct": 0.9},  # 90% below threshold
            "embeddable_docs": 5,
            "expected_status": "READY",  # Quality is advisory, should not block
        },
    ]

    for scenario in test_scenarios:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock run directory structure
            run_id = "test_run"
            run_dir = Path(temp_dir) / "var" / "runs" / run_id
            run_dir.mkdir(parents=True)

            # Create mock enriched.jsonl
            enrich_dir = run_dir / "enrich"
            enrich_dir.mkdir()
            enriched_file = enrich_dir / "enriched.jsonl"

            # Create documents based on scenario
            embeddable_count = scenario["embeddable_docs"]
            below_threshold_pct = scenario["quality_stats"][
                "belowThresholdPct"
            ]

            docs = []
            total_docs = max(
                10, embeddable_count
            )  # At least 10 docs for meaningful percentages

            for i in range(total_docs):
                # Determine quality based on below_threshold_pct
                if i < int(total_docs * below_threshold_pct):
                    quality_score = 0.3  # Below threshold
                else:
                    quality_score = 0.8  # Above threshold

                # Skip some docs to control embeddable count
                if i >= embeddable_count:
                    quality_score = (
                        0.3  # Make these below threshold so they get skipped
                    )

                doc = {
                    "id": f"doc_{i}",
                    "title": f"Document {i}",
                    "quality_score": quality_score,
                    "text_md": f"Content for document {i}",
                }
                docs.append(doc)

            with open(enriched_file, "w") as f:
                for doc in docs:
                    f.write(json.dumps(doc) + "\n")

            # Create mock chunks.ndjson
            chunk_dir = run_dir / "chunk"
            chunk_dir.mkdir()
            chunks_file = chunk_dir / "chunks.ndjson"
            chunks_file.write_text('{"chunk_id": "chunk_1", "text": "test"}\n')

            # Patch paths to use temp directory
            import trailblazer.core.paths

            original_runs = trailblazer.core.paths.runs
            trailblazer.core.paths.runs = (
                lambda: Path(temp_dir) / "var" / "runs"
            )

            try:
                # Run preflight check
                result = run_preflight_check(
                    run_id=run_id,
                    min_quality=0.60,
                    max_below_threshold_pct=0.20,
                    min_embed_docs=1,
                )

                # Verify QUALITY_GATE never appears in reasons
                reasons = result.get("reasons", [])
                assert (
                    "QUALITY_GATE" not in reasons
                ), f"QUALITY_GATE found in reasons for scenario '{scenario['name']}': {reasons}"

                # Verify expected status
                assert result["status"] == scenario["expected_status"], (
                    f"Wrong status for scenario '{scenario['name']}': "
                    f"expected {scenario['expected_status']}, got {result['status']}"
                )

                # Verify expected reasons if specified
                if "expected_reasons" in scenario:
                    for expected_reason in scenario["expected_reasons"]:
                        assert expected_reason in reasons, (
                            f"Expected reason '{expected_reason}' not found in {reasons} "
                            f"for scenario '{scenario['name']}'"
                        )

            finally:
                # Restore original paths function
                trailblazer.core.paths.runs = original_runs


def test_plan_preflight_never_emits_quality_gate_reason():
    """Test that plan-preflight never emits QUALITY_GATE in run reasons."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create multiple runs with varying quality
        run_ids = [
            "run_high_quality",
            "run_low_quality",
            "run_zero_embeddable",
        ]

        for i, run_id in enumerate(run_ids):
            run_dir = Path(temp_dir) / "var" / "runs" / run_id
            run_dir.mkdir(parents=True)

            # Create enrich directory and enriched.jsonl
            enrich_dir = run_dir / "enrich"
            enrich_dir.mkdir()
            enriched_file = enrich_dir / "enriched.jsonl"

            if run_id == "run_zero_embeddable":
                # Create run with zero embeddable docs (all below quality threshold)
                docs = [
                    {
                        "id": "doc_1",
                        "quality_score": 0.1,
                        "text_md": "low quality",
                    },
                    {
                        "id": "doc_2",
                        "quality_score": 0.2,
                        "text_md": "low quality",
                    },
                ]
            elif run_id == "run_low_quality":
                # Create run with mostly low quality but some embeddable
                docs = [
                    {
                        "id": "doc_1",
                        "quality_score": 0.1,
                        "text_md": "low quality",
                    },
                    {
                        "id": "doc_2",
                        "quality_score": 0.8,
                        "text_md": "good quality",
                    },
                    {
                        "id": "doc_3",
                        "quality_score": 0.2,
                        "text_md": "low quality",
                    },
                ]
            else:
                # High quality run
                docs = [
                    {
                        "id": "doc_1",
                        "quality_score": 0.9,
                        "text_md": "excellent",
                    },
                    {
                        "id": "doc_2",
                        "quality_score": 0.8,
                        "text_md": "good quality",
                    },
                ]

            with open(enriched_file, "w") as f:
                for doc in docs:
                    f.write(json.dumps(doc) + "\n")

            # Create chunks.ndjson
            chunk_dir = run_dir / "chunk"
            chunk_dir.mkdir()
            chunks_file = chunk_dir / "chunks.ndjson"
            chunks_file.write_text('{"chunk_id": "chunk_1", "text": "test"}\n')

        # Create plan file
        plan_file = Path(temp_dir) / "test_plan.txt"
        with open(plan_file, "w") as f:
            for run_id in run_ids:
                f.write(f"var/runs/{run_id}\n")

        # Patch paths to use temp directory
        import trailblazer.core.paths

        original_runs = trailblazer.core.paths.runs
        trailblazer.core.paths.runs = lambda: Path(temp_dir) / "var" / "runs"

        try:
            # Run plan-preflight
            result = run_plan_preflight(
                plan_file=str(plan_file),
                out_dir=str(Path(temp_dir) / "var" / "plan_preflight"),
                min_embed_docs=1,
            )

            # Check that no run has QUALITY_GATE in its reason
            runs_detail = result.get("runs_detail", [])
            for run_data in runs_detail:
                reason = run_data.get("reason", "")
                assert (
                    "QUALITY_GATE" not in reason
                ), f"QUALITY_GATE found in reason for run {run_data.get('rid')}: {reason}"

                # Verify that only valid blocking reasons are used
                if run_data.get("status") == "BLOCKED":
                    valid_reasons = [
                        "MISSING_ENRICH",
                        "MISSING_CHUNKS",
                        "TOKENIZER_MISSING",
                        "CONFIG_INVALID",
                        "EMBEDDABLE_DOCS=0",
                    ]
                    reason_parts = [
                        r.strip() for r in reason.split(",") if r.strip()
                    ]
                    for reason_part in reason_parts:
                        assert any(
                            valid_reason in reason_part
                            for valid_reason in valid_reasons
                        ), f"Invalid blocking reason found: {reason_part} in {reason}"

        finally:
            # Restore original paths function
            trailblazer.core.paths.runs = original_runs


def test_quality_advisory_always_true():
    """Test that quality is always advisory and never blocks runs based on quality alone."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a run with terrible quality but some embeddable docs
        run_id = "terrible_quality_run"
        run_dir = Path(temp_dir) / "var" / "runs" / run_id
        run_dir.mkdir(parents=True)

        # Create enrich directory
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir()
        enriched_file = enrich_dir / "enriched.jsonl"

        # Create docs with very poor quality (95% below threshold)
        docs = []
        for i in range(20):
            if i < 19:  # 19 out of 20 are poor quality
                quality_score = 0.1
            else:  # 1 out of 20 is good quality
                quality_score = 0.9

            docs.append(
                {
                    "id": f"doc_{i}",
                    "quality_score": quality_score,
                    "text_md": f"Content {i}",
                }
            )

        with open(enriched_file, "w") as f:
            for doc in docs:
                f.write(json.dumps(doc) + "\n")

        # Create chunks.ndjson
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"
        chunks_file.write_text('{"chunk_id": "chunk_1", "text": "test"}\n')

        # Patch paths
        import trailblazer.core.paths

        original_runs = trailblazer.core.paths.runs
        trailblazer.core.paths.runs = lambda: Path(temp_dir) / "var" / "runs"

        try:
            # Run preflight with very strict quality requirements
            result = run_preflight_check(
                run_id=run_id,
                min_quality=0.60,  # High threshold
                max_below_threshold_pct=0.10,  # Very strict (only 10% allowed below threshold)
                min_embed_docs=1,
            )

            # Even with terrible quality, should be READY because quality is advisory
            assert (
                result["status"] == "READY"
            ), f"Run should be READY despite poor quality (quality is advisory): {result}"

            # Should not have QUALITY_GATE reason
            reasons = result.get("reasons", [])
            assert (
                "QUALITY_GATE" not in reasons
            ), f"QUALITY_GATE should never appear in reasons: {reasons}"

            # Should have quality stats for advisory purposes
            quality_stats = result.get("quality", {})
            below_threshold_pct = quality_stats.get("belowThresholdPct", 0)
            assert (
                below_threshold_pct > 0.9
            ), "Should detect high below-threshold percentage"

            # Advisory flag should be set
            advisory = result.get("advisory", {})
            assert (
                advisory.get("quality") is True
            ), "Quality should be marked as advisory"

        finally:
            trailblazer.core.paths.runs = original_runs
