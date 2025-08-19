"""Test that normalize step emits proper events and maintains traceability."""

import json
import tempfile
from pathlib import Path

from trailblazer.pipeline.steps.normalize.html_to_md import (
    normalize_from_ingest,
)
from trailblazer.obs.events import EventEmitter, set_global_emitter


class TestNormalizeEvents:
    """Test normalize event emission and traceability preservation."""

    def test_normalize_emits_events(self):
        """Test that normalize emits events during processing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test input file
            ingest_dir = temp_path / "test-run" / "ingest"
            ingest_dir.mkdir(parents=True, exist_ok=True)

            input_file = ingest_dir / "confluence.ndjson"
            test_data = [
                {
                    "id": "page1",
                    "title": "Test Page 1",
                    "space_key": "TEST",
                    "url": "https://example.com/page1",
                    "body_storage": "<p>Test content 1</p>",
                    "attachments": [
                        {
                            "filename": "file1.pdf",
                            "download_url": "http://example.com/file1.pdf",
                        }
                    ],
                    "source_system": "confluence",
                },
                {
                    "id": "page2",
                    "title": "Test Page 2",
                    "space_key": "TEST",
                    "url": "https://example.com/page2",
                    "body_adf": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Test content 2"}
                                ],
                            }
                        ],
                    },
                    "attachments": [],
                    "source_system": "confluence",
                },
            ]

            with open(input_file, "w") as f:
                for record in test_data:
                    f.write(json.dumps(record) + "\n")

            # Set up output directory
            normalize_dir = temp_path / "test-run" / "normalize"
            normalize_dir.mkdir(parents=True, exist_ok=True)

            # Set up event logging
            log_dir = temp_path / "logs"
            log_dir.mkdir(exist_ok=True)

            emitter = EventEmitter(
                run_id="test-run",
                phase="normalize",
                component="run",
                log_dir=str(log_dir),
            )
            set_global_emitter(emitter)

            with emitter:
                # Run normalize
                result = normalize_from_ingest(
                    outdir=str(normalize_dir), input_file=str(input_file)
                )

            # Verify result
            assert result["pages"] == 2
            assert result["empty_bodies"] == 0
            assert result["attachments"] == 1

            # Verify events were emitted
            events_file = log_dir / "test-run" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            # Should have at least start and completion events
            assert len(events) >= 2

            # Check for start event
            start_events = [
                e
                for e in events
                if "Starting normalization"
                in e.get("metadata", {}).get("message", "")
            ]
            assert len(start_events) >= 1
            start_event = start_events[0]
            assert start_event["level"] == "info"
            assert start_event["run_id"] == "test-run"

            # Check for completion event
            completion_events = [
                e
                for e in events
                if "Normalization completed"
                in e.get("metadata", {}).get("message", "")
            ]
            assert len(completion_events) >= 1
            completion_event = completion_events[0]
            assert completion_event["level"] == "info"
            assert completion_event["run_id"] == "test-run"
            assert completion_event["metadata"]["docs"] == 2
            assert completion_event["metadata"]["empty_bodies"] == 0
            assert completion_event["metadata"]["attachments"] == 1

            # Clean up
            set_global_emitter(None)

    def test_normalized_output_preserves_traceability(self):
        """Test that normalized.ndjson preserves traceability fields."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test input with traceability fields
            ingest_dir = temp_path / "test-run" / "ingest"
            ingest_dir.mkdir(parents=True, exist_ok=True)

            input_file = ingest_dir / "confluence.ndjson"
            test_record = {
                "id": "page123",
                "title": "Traceability Test Page",
                "space_key": "TRACE",
                "space_id": "space123",
                "url": "https://example.com/page123",
                "version": 5,
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-02T00:00:00Z",
                "body_storage": "<p>Content with <a href='https://external.com'>external link</a></p>",
                "attachments": [
                    {
                        "filename": "doc.pdf",
                        "download_url": "http://example.com/doc.pdf",
                    },
                    {
                        "filename": "image.png",
                        "download_url": "http://example.com/image.png",
                    },
                ],
                "labels": ["important", "documentation"],
                "source_system": "confluence",
                "content_sha256": "abc123def456",
                "ancestors": [{"title": "Parent Page"}],
            }

            with open(input_file, "w") as f:
                f.write(json.dumps(test_record) + "\n")

            # Set up output directory
            normalize_dir = temp_path / "test-run" / "normalize"
            normalize_dir.mkdir(parents=True, exist_ok=True)

            # Run normalize
            normalize_from_ingest(
                outdir=str(normalize_dir), input_file=str(input_file)
            )

            # Read normalized output
            normalized_file = normalize_dir / "normalized.ndjson"
            assert normalized_file.exists()

            with open(normalized_file, "r") as f:
                normalized_record = json.loads(f.readline().strip())

            # Verify traceability fields are preserved
            required_traceability_fields = [
                "id",
                "title",
                "space_key",
                "space_id",
                "url",
                "version",
                "created_at",
                "updated_at",
                "source_system",
                "labels",
                "content_sha256",
                "attachments",
                "links",
            ]

            for field in required_traceability_fields:
                assert field in normalized_record, (
                    f"Missing traceability field: {field}"
                )

            # Verify specific values
            assert normalized_record["id"] == "page123"
            assert normalized_record["title"] == "Traceability Test Page"
            assert normalized_record["space_key"] == "TRACE"
            assert normalized_record["space_id"] == "space123"
            assert normalized_record["url"] == "https://example.com/page123"
            assert normalized_record["version"] == 5
            assert normalized_record["source_system"] == "confluence"
            assert normalized_record["labels"] == [
                "important",
                "documentation",
            ]
            assert normalized_record["content_sha256"] == "abc123def456"

            # Verify attachments structure
            assert len(normalized_record["attachments"]) == 2
            assert normalized_record["attachments"][0]["filename"] == "doc.pdf"
            assert (
                normalized_record["attachments"][0]["url"]
                == "http://example.com/doc.pdf"
            )

            # Verify links were extracted
            assert "links" in normalized_record
            assert (
                len(normalized_record["links"]) >= 1
            )  # Should extract external link

            # Verify breadcrumbs were created
            assert "breadcrumbs" in normalized_record
            assert "Parent Page" in normalized_record["breadcrumbs"]
            assert "Traceability Test Page" in normalized_record["breadcrumbs"]

            # Verify markdown conversion happened
            assert "text_md" in normalized_record
            assert "Content with" in normalized_record["text_md"]
            assert normalized_record["body_repr"] == "storage"
