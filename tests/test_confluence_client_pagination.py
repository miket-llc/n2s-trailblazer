import pytest
from unittest.mock import Mock
from src.trailblazer.adapters.confluence_api import ConfluenceClient


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing pagination."""
    return Mock()


def test_paginate_with_links_next(mock_http_client):
    """Test pagination using _links.next."""

    client = ConfluenceClient()
    client._client = mock_http_client

    # Mock responses for pagination
    response1 = Mock()
    response1.raise_for_status.return_value = None
    response1.json.return_value = {
        "results": [{"id": "1", "title": "Page 1"}, {"id": "2", "title": "Page 2"}],
        "_links": {"next": "/api/v2/pages?cursor=next1"},
    }
    response1.headers = {}

    response2 = Mock()
    response2.raise_for_status.return_value = None
    response2.json.return_value = {
        "results": [{"id": "3", "title": "Page 3"}],
        "_links": {},  # No next link
    }
    response2.headers = {}

    # Setup mock to return different responses for different calls
    mock_http_client.get.side_effect = [response1, response2]

    # Test pagination
    results = list(client._paginate("/api/v2/pages", {"limit": 2}))

    assert len(results) == 3
    assert results[0]["id"] == "1"
    assert results[1]["id"] == "2"
    assert results[2]["id"] == "3"

    # Check that get was called twice
    assert mock_http_client.get.call_count == 2

    # First call should use params
    first_call = mock_http_client.get.call_args_list[0]
    assert first_call[0][0] == "/api/v2/pages"
    assert first_call[1]["params"] == {"limit": 2}

    # Second call should use cursor URL without params
    second_call = mock_http_client.get.call_args_list[1]
    assert second_call[0][0] == "/api/v2/pages?cursor=next1"
    assert second_call[1]["params"] is None


def test_paginate_with_link_header(mock_http_client):
    """Test pagination using Link header as fallback."""

    client = ConfluenceClient()
    client._client = mock_http_client

    # Mock responses for pagination
    response1 = Mock()
    response1.raise_for_status.return_value = None
    response1.json.return_value = {
        "results": [{"id": "1", "title": "Page 1"}],
        "_links": {},  # No _links.next
    }
    # Use Link header instead
    response1.headers = {
        "Link": '</api/v2/pages?cursor=abc123>; rel="next", '
        '</api/v2/pages?cursor=prev>; rel="prev"'
    }

    response2 = Mock()
    response2.raise_for_status.return_value = None
    response2.json.return_value = {"results": [{"id": "2", "title": "Page 2"}], "_links": {}}
    response2.headers = {}  # No more pages

    mock_http_client.get.side_effect = [response1, response2]

    # Test pagination
    results = list(client._paginate("/api/v2/pages", {"limit": 1}))

    assert len(results) == 2
    assert results[0]["id"] == "1"
    assert results[1]["id"] == "2"

    # Check calls
    assert mock_http_client.get.call_count == 2

    # Second call should use the URL from Link header
    second_call = mock_http_client.get.call_args_list[1]
    assert second_call[0][0] == "/api/v2/pages?cursor=abc123"


def test_paginate_single_page(mock_http_client):
    """Test pagination with only one page (no next links)."""

    client = ConfluenceClient()
    client._client = mock_http_client

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"results": [{"id": "1", "title": "Only Page"}], "_links": {}}
    response.headers = {}

    mock_http_client.get.return_value = response

    # Test pagination
    results = list(client._paginate("/api/v2/pages", {"limit": 10}))

    assert len(results) == 1
    assert results[0]["id"] == "1"

    # Should only make one call
    assert mock_http_client.get.call_count == 1


def test_paginate_empty_results(mock_http_client):
    """Test pagination with empty results."""

    client = ConfluenceClient()
    client._client = mock_http_client

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"results": [], "_links": {}}
    response.headers = {}

    mock_http_client.get.return_value = response

    # Test pagination
    results = list(client._paginate("/api/v2/pages", {"limit": 10}))

    assert len(results) == 0
    assert mock_http_client.get.call_count == 1


def test_get_spaces_integration():
    """Integration test for get_spaces using pagination."""

    client = ConfluenceClient()
    mock_client = Mock()
    client._client = mock_client

    # Mock paginated response
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "results": [
            {"id": "123", "key": "TEST", "name": "Test Space"},
            {"id": "456", "key": "DEV", "name": "Dev Space"},
        ],
        "_links": {},
    }
    response.headers = {}

    mock_client.get.return_value = response

    # Test get_spaces
    spaces = list(client.get_spaces(keys=["TEST", "DEV"]))

    assert len(spaces) == 2
    assert spaces[0]["key"] == "TEST"
    assert spaces[1]["key"] == "DEV"

    # Check the API call
    call_args = mock_client.get.call_args
    assert call_args[0][0] == "/api/v2/spaces"
    assert call_args[1]["params"]["keys"] == "TEST,DEV"
    assert call_args[1]["params"]["limit"] == 100
