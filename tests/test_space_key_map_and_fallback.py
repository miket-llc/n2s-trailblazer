"""Test space_key resolution with API lookup and URL fallback."""

from unittest.mock import MagicMock
from httpx import Response

from trailblazer.pipeline.steps.ingest.confluence import _resolve_space_key


def test_space_key_from_cache():
    """Test that cached space_key is returned first."""
    client = MagicMock()
    client._client = MagicMock()
    space_key_cache = {"27787275": "PM"}
    space_key_unknown_count = {}

    result = _resolve_space_key(
        client,
        space_key_cache,
        "27787275",
        "https://example.com/spaces/PM/pages/123",
        space_key_unknown_count,
    )

    assert result == "PM"
    assert len(space_key_unknown_count) == 0
    # Should not have called API since it was cached
    client._client.get.assert_not_called()


def test_space_key_from_api():
    """Test API lookup when not in cache."""
    client = MagicMock()
    client._client = MagicMock()

    # Mock successful API response
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "27787275", "key": "PM"}
    client._client.get.return_value = mock_response

    space_key_cache = {}
    space_key_unknown_count = {}

    result = _resolve_space_key(
        client,
        space_key_cache,
        "27787275",
        "https://example.com/spaces/PM/pages/123",
        space_key_unknown_count,
    )

    assert result == "PM"
    assert space_key_cache["27787275"] == "PM"  # Should cache the result
    assert len(space_key_unknown_count) == 0
    client._client.get.assert_called_once_with("/api/v2/spaces/27787275")


def test_space_key_from_url_fallback():
    """Test URL regex fallback when API fails."""
    client = MagicMock()
    client._client = MagicMock()

    # Mock API failure
    client._client.get.side_effect = Exception("API Error")

    space_key_cache = {}
    space_key_unknown_count = {}

    result = _resolve_space_key(
        client,
        space_key_cache,
        "27787275",
        "https://ellucian.atlassian.net/wiki/spaces/PM/pages/123456/Some+Page",
        space_key_unknown_count,
    )

    assert result == "PM"
    assert space_key_cache["27787275"] == "PM"  # Should cache the result
    assert len(space_key_unknown_count) == 0


def test_space_key_url_fallback_various_formats():
    """Test URL regex with different URL formats."""
    client = MagicMock()
    client._client = MagicMock()
    client._client.get.side_effect = Exception("API Error")

    test_cases = [
        ("https://example.com/wiki/spaces/DEV/pages/123", "DEV"),
        (
            "https://company.atlassian.net/wiki/spaces/INFRA/pages/456/title",
            "INFRA",
        ),
        ("https://site.com/spaces/PM123/pages/789", "PM123"),
        ("https://site.com/spaces/ABC/pages/", "ABC"),
    ]

    for url, expected_key in test_cases:
        space_key_cache = {}
        space_key_unknown_count = {}

        result = _resolve_space_key(
            client, space_key_cache, "12345", url, space_key_unknown_count
        )

        assert result == expected_key, (
            f"URL {url} should extract key {expected_key}"
        )
        assert space_key_cache["12345"] == expected_key


def test_space_key_unknown_fallback():
    """Test __unknown__ fallback when both API and URL parsing fail."""
    client = MagicMock()
    client._client = MagicMock()

    # Mock API failure
    client._client.get.side_effect = Exception("API Error")

    space_key_cache = {}
    space_key_unknown_count = {}

    # URL doesn't match pattern
    result = _resolve_space_key(
        client,
        space_key_cache,
        "27787275",
        "https://example.com/some/other/path",
        space_key_unknown_count,
    )

    assert result == "__unknown__"
    assert "27787275" not in space_key_cache  # Should not cache unknown
    assert space_key_unknown_count["27787275"] == 1


def test_space_key_unknown_counter_increments():
    """Test that unknown counter increments on repeated failures."""
    client = MagicMock()
    client._client = MagicMock()
    client._client.get.side_effect = Exception("API Error")

    space_key_cache = {}
    space_key_unknown_count = {}

    # Call multiple times with same space_id
    for i in range(3):
        result = _resolve_space_key(
            client,
            space_key_cache,
            "12345",
            "https://example.com/bad/url",
            space_key_unknown_count,
        )
        assert result == "__unknown__"

    assert space_key_unknown_count["12345"] == 3


def test_space_key_missing_space_id():
    """Test handling of missing space_id."""
    client = MagicMock()
    client._client = MagicMock()
    space_key_cache = {}
    space_key_unknown_count = {}

    result = _resolve_space_key(
        client,
        space_key_cache,
        None,
        "https://example.com/spaces/PM/pages/123",
        space_key_unknown_count,
    )

    assert result == "__unknown__"
    assert space_key_unknown_count["__missing_space_id__"] == 1
    client._client.get.assert_not_called()


def test_space_key_api_404_fallback_to_url():
    """Test that 404 API response falls back to URL parsing."""
    client = MagicMock()
    client._client = MagicMock()

    # Mock 404 API response
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 404
    client._client.get.return_value = mock_response

    space_key_cache = {}
    space_key_unknown_count = {}

    result = _resolve_space_key(
        client,
        space_key_cache,
        "27787275",
        "https://example.com/spaces/PM/pages/123",
        space_key_unknown_count,
    )

    assert result == "PM"  # Should get from URL
    assert space_key_cache["27787275"] == "PM"
    assert len(space_key_unknown_count) == 0


def test_space_key_api_success_with_missing_key():
    """Test API response without key field falls back to URL."""
    client = MagicMock()
    client._client = MagicMock()

    # Mock API response without key field
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "27787275",
        "name": "Project Management",
    }
    client._client.get.return_value = mock_response

    space_key_cache = {}
    space_key_unknown_count = {}

    result = _resolve_space_key(
        client,
        space_key_cache,
        "27787275",
        "https://example.com/spaces/PM/pages/123",
        space_key_unknown_count,
    )

    assert result == "PM"  # Should get from URL
    assert space_key_cache["27787275"] == "PM"
    assert len(space_key_unknown_count) == 0
