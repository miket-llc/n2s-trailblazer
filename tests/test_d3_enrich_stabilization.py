"""Integration tests for D3 Enrich Stabilization features."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch


from trailblazer.pipeline.steps.enrich.enricher import enrich_from_normalized
from trailblazer.pipeline.steps.chunk.engine import (
    chunk_document,
    inject_media_placeholders,
)
from trailblazer.cli.main import embed_preflight_cmd


def chunk_enriched_record(record):
    """Helper function to chunk an enriched record."""
    doc_id = record.get("id", "")
    title = record.get("title", "")
    text_md = record.get("text_md", "")
    attachments = record.get("attachments", [])
    chunk_hints = record.get("chunk_hints", {})
    section_map = record.get("section_map", [])

    if not doc_id:
        raise ValueError("Record missing required 'id' field")

    text_with_media = inject_media_placeholders(text_md, attachments)
    return chunk_document(
        doc_id=doc_id,
        text_md=text_with_media,
        title=title,
        source_system=record.get("source_system", ""),
        labels=record.get("labels", []),
        space=record.get("space"),
        media_refs=attachments,
        hard_max_tokens=chunk_hints.get("maxTokens", 800),
        min_tokens=chunk_hints.get("minTokens", 120),
        overlap_tokens=chunk_hints.get("overlapTokens", 60),
        soft_min_tokens=chunk_hints.get("softMinTokens", 200),
        hard_min_tokens=chunk_hints.get("hardMinTokens", 80),
        prefer_headings=chunk_hints.get("preferHeadings", True),
        soft_boundaries=chunk_hints.get("softBoundaries", []),
        section_map=section_map,
    )


class TestEnrichChunkPreflightFlow:
    """Test the complete enrich → chunk → preflight flow."""

    def test_healthy_sample_passes_preflight(self):
        """Test that a healthy sample passes through the entire pipeline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            run_id = "test-healthy-run"

            # Setup directories
            runs_dir = tmpdir_path / "runs" / run_id
            normalize_dir = runs_dir / "normalize"
            enrich_dir = runs_dir / "enrich"
            chunk_dir = runs_dir / "chunk"
            preflight_dir = runs_dir / "preflight"

            normalize_dir.mkdir(parents=True)
            enrich_dir.mkdir(parents=True)
            chunk_dir.mkdir(parents=True)
            preflight_dir.mkdir(parents=True)

            # Create healthy test documents
            healthy_docs = [
                {
                    "id": "doc1",
                    "title": "Well Structured Document",
                    "text_md": "# Introduction\n\nThis is a well-structured document with good content.\n\n## Features\n\n- Clear headings\n- Good length\n- Proper structure\n\n## Conclusion\n\nThis document should score well on quality metrics.",
                    "source_system": "confluence",
                    "attachments": [],
                },
                {
                    "id": "doc2",
                    "title": "API Documentation",
                    "text_md": "# API Reference\n\n## Authentication\n\nUse API keys for authentication.\n\n## Endpoints\n\n### GET /users\n\nRetrieve user list.\n\n### POST /users\n\nCreate a new user.",
                    "source_system": "confluence",
                    "attachments": [],
                },
            ]

            # Write normalized input
            normalized_file = normalize_dir / "normalized.ndjson"
            with open(normalized_file, "w", encoding="utf-8") as f:
                for doc in healthy_docs:
                    f.write(json.dumps(doc) + "\n")

            # Mock the phase_dir function to use our temp directory
            with patch(
                "trailblazer.core.artifacts.phase_dir"
            ) as mock_phase_dir:

                def mock_phase_dir_impl(run_id_arg, phase):
                    return runs_dir / phase

                mock_phase_dir.side_effect = mock_phase_dir_impl

                # Run enrichment
                stats = enrich_from_normalized(
                    run_id=run_id,
                    min_quality=0.60,
                    max_below_threshold_pct=0.20,
                )

                # Verify enrichment results
                assert stats["docs_total"] == 2
                assert "quality_distribution" in stats

                quality_dist = stats["quality_distribution"]
                assert (
                    quality_dist["belowThresholdPct"] <= 0.20
                )  # Should pass threshold

                # Verify enriched file has new schema fields
                enriched_file = enrich_dir / "enriched.jsonl"
                assert enriched_file.exists()

                with open(enriched_file, "r", encoding="utf-8") as f:
                    enriched_docs = [
                        json.loads(line) for line in f if line.strip()
                    ]

                assert len(enriched_docs) == 2
                for doc in enriched_docs:
                    # Check new schema fields
                    assert "fingerprint" in doc
                    assert "section_map" in doc
                    assert "chunk_hints" in doc
                    assert "quality" in doc
                    assert "quality_score" in doc

                    # Quality should be decent for our well-structured docs
                    assert doc["quality_score"] >= 0.60

                # Test chunking with enriched records
                chunks_all = []
                for doc in enriched_docs:
                    chunks = chunk_enriched_record(doc)
                    chunks_all.extend(chunks)

                    # Verify chunks have token counts
                    for chunk in chunks:
                        assert hasattr(chunk, "token_count")
                        assert chunk.token_count > 0

                # Write chunks file
                chunks_file = chunk_dir / "chunks.ndjson"
                with open(chunks_file, "w", encoding="utf-8") as f:
                    for chunk in chunks_all:
                        chunk_data = {
                            "chunk_id": chunk.chunk_id,
                            "doc_id": chunk.chunk_id.split(":")[0],
                            "ord": chunk.ord,
                            "text_md": chunk.text_md,
                            "char_count": chunk.char_count,
                            "token_count": chunk.token_count,
                            "chunk_type": chunk.chunk_type.value
                            if hasattr(chunk.chunk_type, "value")
                            else str(chunk.chunk_type),
                            "meta": chunk.meta,
                        }
                        f.write(json.dumps(chunk_data) + "\n")

                # Create chunk assurance with quality distribution
                chunk_assurance = {
                    "run_id": run_id,
                    "docCount": len(enriched_docs),
                    "chunkCount": len(chunks_all),
                    "qualityDistribution": quality_dist,
                    "tokenStats": {
                        "count": len(chunks_all),
                        "min": min(c.token_count for c in chunks_all),
                        "max": max(c.token_count for c in chunks_all),
                        "median": sorted([c.token_count for c in chunks_all])[
                            len(chunks_all) // 2
                        ],
                        "total": sum(c.token_count for c in chunks_all),
                    },
                }

                assurance_file = chunk_dir / "chunk_assurance.json"
                with open(assurance_file, "w") as f:
                    json.dump(chunk_assurance, f, indent=2)

                # Mock the CLI context for preflight test
                with patch("trailblazer.cli.main.typer"):
                    with patch("trailblazer.core.paths.runs") as mock_runs:
                        mock_runs.return_value = tmpdir_path / "runs"

                        # This should pass without raising an exception
                        try:
                            embed_preflight_cmd(
                                run=run_id,
                                provider="openai",
                                model="text-embedding-3-small",
                                dim=1536,
                            )
                            preflight_passed = True
                        except SystemExit as e:
                            preflight_passed = e.code == 0

                        assert preflight_passed, (
                            "Healthy sample should pass preflight"
                        )

    def test_poor_quality_sample_fails_preflight(self):
        """Test that a poor quality sample fails preflight checks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            run_id = "test-poor-quality-run"

            # Setup directories
            runs_dir = tmpdir_path / "runs" / run_id
            normalize_dir = runs_dir / "normalize"
            enrich_dir = runs_dir / "enrich"
            chunk_dir = runs_dir / "chunk"

            normalize_dir.mkdir(parents=True)
            enrich_dir.mkdir(parents=True)
            chunk_dir.mkdir(parents=True)

            # Create poor quality test documents
            poor_docs = [
                {
                    "id": "bad1",
                    "title": "Empty",
                    "text_md": "",
                    "source_system": "confluence",
                    "attachments": [],
                },
                {
                    "id": "bad2",
                    "title": "Short",
                    "text_md": "Too short",
                    "source_system": "confluence",
                    "attachments": [],
                },
                {
                    "id": "bad3",
                    "title": "No Structure",
                    "text_md": "This is a document with no headings or structure just a wall of text that goes on and on without any meaningful organization or formatting.",
                    "source_system": "confluence",
                    "attachments": [],
                },
            ]

            # Write normalized input
            normalized_file = normalize_dir / "normalized.ndjson"
            with open(normalized_file, "w", encoding="utf-8") as f:
                for doc in poor_docs:
                    f.write(json.dumps(doc) + "\n")

            # Mock the phase_dir function
            with patch(
                "trailblazer.core.artifacts.phase_dir"
            ) as mock_phase_dir:

                def mock_phase_dir_impl(run_id_arg, phase):
                    return runs_dir / phase

                mock_phase_dir.side_effect = mock_phase_dir_impl

                # Run enrichment with strict quality thresholds
                stats = enrich_from_normalized(
                    run_id=run_id,
                    min_quality=0.60,
                    max_below_threshold_pct=0.10,  # Very strict threshold
                )

                quality_dist = stats["quality_distribution"]
                # Should have high percentage below threshold
                assert quality_dist["belowThresholdPct"] > 0.10

                # Create minimal chunk assurance for preflight test
                chunks_file = chunk_dir / "chunks.ndjson"
                with open(chunks_file, "w", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {"chunk_id": "bad1:0000", "token_count": 10}
                        )
                        + "\n"
                    )

                chunk_assurance = {
                    "run_id": run_id,
                    "docCount": 3,
                    "chunkCount": 1,
                    "qualityDistribution": quality_dist,
                    "tokenStats": {
                        "count": 1,
                        "min": 10,
                        "max": 10,
                        "median": 10,
                        "total": 10,
                    },
                }

                assurance_file = chunk_dir / "chunk_assurance.json"
                with open(assurance_file, "w") as f:
                    json.dump(chunk_assurance, f, indent=2)

                # Mock the CLI context for preflight test
                with patch("trailblazer.cli.main.typer"):
                    with patch("trailblazer.core.paths.runs") as mock_runs:
                        mock_runs.return_value = tmpdir_path / "runs"

                        # This should fail due to quality gate
                        preflight_failed = False
                        try:
                            embed_preflight_cmd(
                                run=run_id,
                                provider="openai",
                                model="text-embedding-3-small",
                                dim=1536,
                            )
                        except SystemExit as e:
                            preflight_failed = e.code != 0

                        assert preflight_failed, (
                            "Poor quality sample should fail preflight"
                        )

    def test_enriched_sample_output_format(self):
        """Test that enriched.jsonl sample has the expected format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            run_id = "test-sample-format"

            # Setup directories
            runs_dir = tmpdir_path / "runs" / run_id
            normalize_dir = runs_dir / "normalize"
            enrich_dir = runs_dir / "enrich"

            normalize_dir.mkdir(parents=True)
            enrich_dir.mkdir(parents=True)

            # Create sample document
            sample_doc = {
                "id": "sample-doc",
                "title": "Sample Document",
                "text_md": "# Sample Title\n\nThis is sample content.\n\n## Section 1\n\n- Item 1\n- Item 2\n\n## Section 2\n\nMore content here.",
                "source_system": "confluence",
                "attachments": [{"name": "image.png", "type": "image"}],
            }

            # Write normalized input
            normalized_file = normalize_dir / "normalized.ndjson"
            with open(normalized_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(sample_doc) + "\n")

            # Mock the phase_dir function
            with patch(
                "trailblazer.core.artifacts.phase_dir"
            ) as mock_phase_dir:

                def mock_phase_dir_impl(run_id_arg, phase):
                    return runs_dir / phase

                mock_phase_dir.side_effect = mock_phase_dir_impl

                # Run enrichment
                enrich_from_normalized(run_id=run_id)

                # Read the enriched output
                enriched_file = enrich_dir / "enriched.jsonl"
                with open(enriched_file, "r", encoding="utf-8") as f:
                    enriched_doc = json.loads(f.readline().strip())

                # Verify the complete schema
                expected_fields = [
                    "id",
                    "source_system",
                    "collection",
                    "path_tags",
                    "readability",
                    "media_density",
                    "link_density",
                    "quality_flags",
                    "fingerprint",
                    "section_map",
                    "chunk_hints",
                    "quality",
                    "quality_score",
                ]

                for field in expected_fields:
                    assert field in enriched_doc, f"Missing field: {field}"

                # Verify specific field structures match the spec
                fingerprint = enriched_doc["fingerprint"]
                assert isinstance(fingerprint, dict)
                assert "doc" in fingerprint and "version" in fingerprint

                section_map = enriched_doc["section_map"]
                assert isinstance(section_map, list)
                if section_map:
                    section = section_map[0]
                    required_section_fields = [
                        "heading",
                        "level",
                        "startChar",
                        "endChar",
                        "tokenStart",
                        "tokenEnd",
                    ]
                    for field in required_section_fields:
                        assert field in section

                chunk_hints = enriched_doc["chunk_hints"]
                assert isinstance(chunk_hints, dict)
                required_hint_fields = [
                    "maxTokens",
                    "minTokens",
                    "preferHeadings",
                    "softBoundaries",
                ]
                for field in required_hint_fields:
                    assert field in chunk_hints

                quality_metrics = enriched_doc["quality"]
                assert isinstance(quality_metrics, dict)
                assert "word_count" in quality_metrics
                assert "structure_score" in quality_metrics

                quality_score = enriched_doc["quality_score"]
                assert isinstance(quality_score, (int, float))
                assert 0.0 <= quality_score <= 1.0

                # Print sample for documentation
                print("\n=== Sample enriched.jsonl entry ===")
                print(json.dumps(enriched_doc, indent=2))
