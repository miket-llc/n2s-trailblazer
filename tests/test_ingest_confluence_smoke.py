import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime

from src.trailblazer.pipeline.steps.ingest.confluence import ingest_confluence


@pytest.fixture
def temp_outdir(tmp_path):
    """Create a temporary output directory."""
    return str(tmp_path)


@pytest.fixture
def mock_confluence_client():
    """Mock confluence client with fake data."""
    client = Mock()

    # Mock spaces data
    client.get_spaces.return_value = [{"id": "space1", "key": "TEST", "name": "Test Space"}]

    # Mock pages data
    client.get_pages.return_value = [
        {
            "id": "page1",
            "title": "Test Page 1",
            "space": {"id": "space1", "key": "TEST"},
            "version": {"number": 1, "createdAt": "2025-01-01T12:00:00.000Z"},
            "_links": {"webui": "/wiki/spaces/TEST/pages/page1"},
            "body": {"storage": {"value": "<p>Test content 1</p>"}},
        },
        {
            "id": "page2",
            "title": "Test Page 2",
            "space": {"id": "space1", "key": "TEST"},
            "version": {"number": 2, "createdAt": "2025-01-01T13:00:00.000Z"},
            "_links": {"webui": "/wiki/spaces/TEST/pages/page2"},
            "body": {"storage": {"value": "<p>Test content 2</p>"}},
        },
    ]

    # Mock page by ID responses
    def get_page_by_id(page_id, body_format=None):
        pages = {
            "page1": {
                "id": "page1",
                "title": "Test Page 1",
                "space": {"id": "space1", "key": "TEST"},
                "version": {"number": 1, "createdAt": "2025-01-01T12:00:00.000Z"},
                "_links": {"webui": "/wiki/spaces/TEST/pages/page1"},
                "body": {"storage": {"value": "<p>Test content 1</p>"}},
            },
            "page2": {
                "id": "page2",
                "title": "Test Page 2",
                "space": {"id": "space1", "key": "TEST"},
                "version": {"number": 2, "createdAt": "2025-01-01T13:00:00.000Z"},
                "_links": {"webui": "/wiki/spaces/TEST/pages/page2"},
                "body": {"storage": {"value": "<p>Test content 2</p>"}},
            },
        }
        return pages.get(page_id, {})

    client.get_page_by_id.side_effect = get_page_by_id

    # Mock attachments (empty for simplicity)
    client.get_attachments_for_page.return_value = []

    # Mock base URL
    client.base_url = "https://test.atlassian.net/wiki"

    return client


def test_ingest_confluence_smoke(temp_outdir, mock_confluence_client):
    """Test basic confluence ingest functionality."""

    with patch(
        "src.trailblazer.pipeline.steps.ingest.confluence.ConfluenceClient"
    ) as mock_client_class:
        mock_client_class.return_value = mock_confluence_client

        # Run ingest
        metrics = ingest_confluence(
            outdir=temp_outdir,
            space_keys=["TEST"],
            space_ids=None,
            since=None,
            body_format="storage",
            max_pages=None,
        )

        # Check return metrics
        assert metrics["spaces"] == 1
        assert metrics["pages"] == 2
        assert metrics["attachments"] == 0
        assert metrics["body_format"] == "storage"
        assert "duration_seconds" in metrics

        # Check files exist
        outdir = Path(temp_outdir)
        assert (outdir / "confluence.ndjson").exists()
        assert (outdir / "metrics.json").exists()
        assert (outdir / "manifest.json").exists()

        # Check NDJSON content
        ndjson_path = outdir / "confluence.ndjson"
        lines = ndjson_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        # Parse each line and check structure
        for line in lines:
            page_data = json.loads(line)
            assert "id" in page_data
            assert "title" in page_data
            assert "attachments" in page_data
            assert isinstance(page_data["attachments"], list)
            assert page_data["space_key"] == "TEST"
            assert page_data["space_id"] == "space1"

        # Check specific page data
        page1 = json.loads(lines[0])
        assert page1["id"] == "page1"
        assert page1["title"] == "Test Page 1"
        assert page1["body_html"] == "<p>Test content 1</p>"
        assert page1["url"] == "https://test.atlassian.net/wiki/spaces/TEST/pages/page1"

        # Check metrics file
        metrics_path = outdir / "metrics.json"
        with open(metrics_path, encoding="utf-8") as f:
            saved_metrics = json.load(f)
        assert saved_metrics["pages"] == 2
        assert saved_metrics["spaces"] == 1

        # Check manifest file
        manifest_path = outdir / "manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["phase"] == "ingest"
        assert manifest["step"] == "confluence"
        assert "started_at" in manifest
        assert "completed_at" in manifest


def test_ingest_confluence_max_pages(temp_outdir, mock_confluence_client):
    """Test max_pages limiting."""

    with patch(
        "src.trailblazer.pipeline.steps.ingest.confluence.ConfluenceClient"
    ) as mock_client_class:
        mock_client_class.return_value = mock_confluence_client

        # Run ingest with max_pages=1
        metrics = ingest_confluence(
            outdir=temp_outdir,
            space_keys=["TEST"],
            space_ids=None,
            since=None,
            body_format="storage",
            max_pages=1,
        )

        # Should only process 1 page
        assert metrics["pages"] == 1

        # Check NDJSON has only 1 line
        ndjson_path = Path(temp_outdir) / "confluence.ndjson"
        lines = ndjson_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1


def test_ingest_confluence_with_since(temp_outdir, mock_confluence_client):
    """Test ingest with since parameter using CQL search."""

    # Mock CQL search results
    mock_confluence_client.search_cql.return_value = {"results": [{"id": "page1"}, {"id": "page2"}]}

    with patch(
        "src.trailblazer.pipeline.steps.ingest.confluence.ConfluenceClient"
    ) as mock_client_class:
        mock_client_class.return_value = mock_confluence_client

        since_dt = datetime(2025, 1, 1, 10, 0, 0)

        # Run ingest with since parameter
        metrics = ingest_confluence(
            outdir=temp_outdir,
            space_keys=["TEST"],
            space_ids=None,
            since=since_dt,
            body_format="storage",
            max_pages=None,
        )

        # Should have called CQL search
        mock_confluence_client.search_cql.assert_called_once()
        cql_call = mock_confluence_client.search_cql.call_args[0][0]
        assert "lastModified >" in cql_call
        assert "type=page" in cql_call

        # Should still process 2 pages
        assert metrics["pages"] == 2
        assert metrics["since"] == since_dt.isoformat()
