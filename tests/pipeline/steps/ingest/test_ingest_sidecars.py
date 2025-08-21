"""Test ingest confluence sidecar exports (CSV and summary JSON)."""

import csv
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from trailblazer.pipeline.steps.ingest.confluence import ingest_confluence

# Mark all tests as integration tests (need database)
pytestmark = pytest.mark.integration


@pytest.fixture
def tiny_ndjson_fixture(tmp_path):
    """Create a small NDJSON fixture file for testing."""
    ndjson_data = [
        {
            "id": "123",
            "title": "Test Page 1",
            "space_key": "DEV",
            "space_id": "1001",
            "version": 5,
            "updated_at": "2025-01-10T10:00:00Z",
            "url": "https://example.com/page1",
            "body_html": "<p>Content here</p>",
            "attachments": [
                {
                    "id": "att1",
                    "filename": "doc1.pdf",
                    "media_type": "application/pdf",
                    "file_size": 1024,
                    "download_url": "https://example.com/att1",
                }
            ],
        },
        {
            "id": "456",
            "title": "Test Page 2",
            "space_key": "DEV",
            "space_id": "1001",
            "version": 3,
            "updated_at": "2025-01-12T15:30:00Z",
            "url": "https://example.com/page2",
            "body_html": "",  # Empty body
            "attachments": [
                {
                    "id": "att2",
                    "filename": "image.png",
                    "media_type": "image/png",
                    "file_size": 2048,
                    "download_url": "https://example.com/att2",
                },
                {
                    "id": "att3",
                    "filename": "sheet.xlsx",
                    "media_type": "application/vnd.ms-excel",
                    "file_size": 4096,
                    "download_url": "https://example.com/att3",
                },
            ],
        },
        {
            "id": "789",
            "title": "Another Space Page",
            "space_key": "PROD",
            "space_id": "2001",
            "version": 1,
            "updated_at": "2025-01-05T08:15:00Z",
            "url": "https://example.com/page3",
            "body_html": "<p>Production content with some text here</p>",
            "attachments": [],
        },
    ]

    # Write to temp file
    ndjson_file = tmp_path / "test_input.ndjson"
    with open(ndjson_file, "w") as f:
        for item in ndjson_data:
            f.write(json.dumps(item) + "\n")

    return ndjson_file, ndjson_data


def test_ingest_sidecars_csv_and_summary(tmp_path, tiny_ndjson_fixture):
    """Test that ingest produces correct CSV files and summary.json."""
    ndjson_file, expected_data = tiny_ndjson_fixture

    # Mock the confluence API to avoid real API calls
    with patch(
        "trailblazer.pipeline.steps.ingest.confluence.ConfluenceClient"
    ) as mock_client_class:
        # We'll simulate processing by manually calling the enhanced function
        # but with mocked API responses that match our fixture data

        mock_client = mock_client_class.return_value
        mock_client.site_base = "https://example.com"
        mock_client.get_spaces.return_value = iter(
            [{"id": "1001", "key": "DEV"}, {"id": "2001", "key": "PROD"}]
        )

        # Mock the page retrieval to return our test data
        def mock_get_pages(space_id=None, body_format="storage"):
            if space_id == "1001":  # DEV space
                return iter(
                    [
                        {
                            "id": "123",
                            "title": "Test Page 1",
                            "spaceId": "1001",
                            "version": {
                                "number": 5,
                                "createdAt": "2025-01-10T10:00:00Z",
                            },
                            "createdAt": "2025-01-01T10:00:00Z",
                            "body": {
                                "storage": {"value": "<p>Content here</p>"}
                            },
                            "_links": {"webui": "/page1"},
                        },
                        {
                            "id": "456",
                            "title": "Test Page 2",
                            "spaceId": "1001",
                            "version": {
                                "number": 3,
                                "createdAt": "2025-01-12T15:30:00Z",
                            },
                            "createdAt": "2025-01-02T15:30:00Z",
                            "body": {"storage": {"value": ""}},
                            "_links": {"webui": "/page2"},
                        },
                    ]
                )
            elif space_id == "2001":  # PROD space
                return iter(
                    [
                        {
                            "id": "789",
                            "title": "Another Space Page",
                            "spaceId": "2001",
                            "version": {
                                "number": 1,
                                "createdAt": "2025-01-05T08:15:00Z",
                            },
                            "createdAt": "2025-01-03T08:15:00Z",
                            "body": {
                                "storage": {
                                    "value": "<p>Production content with some text here</p>"
                                }
                            },
                            "_links": {"webui": "/page3"},
                        }
                    ]
                )
            return iter([])

        mock_client.get_pages.side_effect = mock_get_pages

        def mock_get_attachments(page_id):
            if page_id == "123":
                return iter(
                    [
                        {
                            "id": "att1",
                            "title": "doc1.pdf",
                            "mediaType": "application/pdf",
                            "fileSize": 1024,
                            "_links": {"download": "/att1"},
                        }
                    ]
                )
            elif page_id == "456":
                return iter(
                    [
                        {
                            "id": "att2",
                            "title": "image.png",
                            "mediaType": "image/png",
                            "fileSize": 2048,
                            "_links": {"download": "/att2"},
                        },
                        {
                            "id": "att3",
                            "title": "sheet.xlsx",
                            "mediaType": "application/vnd.ms-excel",
                            "fileSize": 4096,
                            "_links": {"download": "/att3"},
                        },
                    ]
                )
            return iter([])

        mock_client.get_attachments_for_page.side_effect = mock_get_attachments

        # Run ingest with our test configuration
        outdir = str(tmp_path / "ingest")
        metrics = ingest_confluence(
            outdir=outdir,
            space_keys=["DEV", "PROD"],
            space_ids=None,
            since=None,
            auto_since=False,
            body_format="storage",
            max_pages=None,
            progress=False,
            progress_every=1,
            run_id="test-run-sidecars",
        )

        # Verify basic metrics
        assert metrics["pages"] == 3
        assert metrics["attachments"] == 3
        assert metrics["spaces"] == 2

        # Check pages.csv
        pages_csv_path = Path(outdir) / "pages.csv"
        assert pages_csv_path.exists()

        with open(pages_csv_path, newline="") as f:
            reader = csv.DictReader(f)
            pages_rows = list(reader)

        # Should be sorted by space_key, page_id
        assert len(pages_rows) == 3
        assert pages_rows[0]["space_key"] == "DEV"
        assert pages_rows[0]["page_id"] == "123"
        assert pages_rows[0]["title"] == "Test Page 1"
        assert pages_rows[0]["attachments_count"] == "1"

        assert pages_rows[1]["space_key"] == "DEV"
        assert pages_rows[1]["page_id"] == "456"
        assert pages_rows[1]["attachments_count"] == "2"

        assert pages_rows[2]["space_key"] == "PROD"
        assert pages_rows[2]["page_id"] == "789"
        assert pages_rows[2]["attachments_count"] == "0"

        # Check attachments.csv
        attachments_csv_path = Path(outdir) / "attachments.csv"
        assert attachments_csv_path.exists()

        with open(attachments_csv_path, newline="") as f:
            reader = csv.DictReader(f)
            att_rows = list(reader)

        # Should be sorted by page_id, filename
        assert len(att_rows) == 3
        assert att_rows[0]["page_id"] == "123"
        assert att_rows[0]["filename"] == "doc1.pdf"
        assert att_rows[1]["page_id"] == "456"
        assert att_rows[2]["page_id"] == "456"

        # Check summary.json
        summary_path = Path(outdir) / "summary.json"
        assert summary_path.exists()

        with open(summary_path) as f:
            summary = json.load(f)

        assert summary["run_id"] == "test-run-sidecars"
        assert summary["total_pages"] == 3
        assert summary["total_attachments"] == 3
        assert "started_at" in summary
        assert "completed_at" in summary

        # Check per-space stats
        assert "DEV" in summary["spaces"]
        assert "PROD" in summary["spaces"]

        dev_stats = summary["spaces"]["DEV"]
        assert dev_stats["pages"] == 2
        assert dev_stats["attachments"] == 3
        assert dev_stats["empty_bodies"] == 1  # Page 456 has empty body

        prod_stats = summary["spaces"]["PROD"]
        assert prod_stats["pages"] == 1
        assert prod_stats["attachments"] == 0
        assert prod_stats["empty_bodies"] == 0
        assert prod_stats["avg_chars"] > 0  # Has content

        # Check seen page IDs files
        dev_seen_file = Path(outdir) / "DEV_seen_page_ids.json"
        assert dev_seen_file.exists()
        with open(dev_seen_file) as f:
            dev_seen = json.load(f)
        assert sorted(dev_seen) == ["123", "456"]

        prod_seen_file = Path(outdir) / "PROD_seen_page_ids.json"
        assert prod_seen_file.exists()
        with open(prod_seen_file) as f:
            prod_seen = json.load(f)
        assert prod_seen == ["789"]
