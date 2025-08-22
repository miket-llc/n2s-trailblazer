"""Test dense retriever functionality."""

from unittest.mock import Mock

import pytest

from trailblazer.retrieval.dense import DenseRetriever

# Mark as unit test - this test mocks database operations
pytestmark = pytest.mark.unit


def test_dimension_filter_present():
    """Test that the dense retriever includes dimension=1536 filter."""
    # Mock the session and query objects
    mock_session = Mock()
    mock_query = Mock()
    mock_session.query.return_value = mock_query
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []

    # Mock the session factory as a context manager
    mock_session_factory = Mock()
    mock_context = Mock()
    mock_context.__enter__ = Mock(return_value=mock_session)
    mock_context.__exit__ = Mock(return_value=None)
    mock_session_factory.return_value = mock_context

    # Create retriever with mocked session factory
    retriever = DenseRetriever(db_url="dummy", provider_name="openai")
    retriever._session_factory = mock_session_factory

    # Call the search method
    retriever.search_postgres([0.1] * 1536, "openai", 8)

    # Verify that the dimension filter was applied
    filter_calls = [call[0][0] for call in mock_query.filter.call_args_list]

    # Check that dimension filter is present
    dimension_filter_found = False
    for filter_call in filter_calls:
        if hasattr(filter_call, "left") and hasattr(filter_call, "right"):
            if filter_call.left.name == "dim" and filter_call.right.value == 1536:
                dimension_filter_found = True
                break

    assert dimension_filter_found, "Dimension filter (dim=1536) not found in query"
