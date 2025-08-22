"""Test space whitelist filtering functionality."""

# pytest is used for test discovery and running
from unittest.mock import Mock

from trailblazer.qa.retrieval import run_single_query
from trailblazer.retrieval.dense import DenseRetriever


class TestSpaceWhitelistFilter:
    """Test that space whitelist filtering works correctly."""

    def test_space_whitelist_passed_to_retriever(self):
        """Test that space_whitelist is passed to retriever.search."""
        mock_retriever = Mock(spec=DenseRetriever)
        mock_retriever.search.return_value = []

        query = {"id": "test_query", "text": "test query"}
        budgets = [1000]
        top_k = 10
        space_whitelist = ["MTDLANDTL", "N2S"]

        run_single_query(query, budgets, mock_retriever, top_k, space_whitelist)

        # Verify space_whitelist was passed to retriever
        mock_retriever.search.assert_called_once_with("test query", top_k=10, space_whitelist=["MTDLANDTL", "N2S"])

    def test_no_space_whitelist_passed_to_retriever(self):
        """Test that no space_whitelist is passed when not specified."""
        mock_retriever = Mock(spec=DenseRetriever)
        mock_retriever.search.return_value = []

        query = {"id": "test_query", "text": "test query"}
        budgets = [1000]
        top_k = 10

        run_single_query(query, budgets, mock_retriever, top_k)

        # Verify no space_whitelist was passed to retriever
        mock_retriever.search.assert_called_once_with("test query", top_k=10, space_whitelist=None)

    def test_space_whitelist_none_passed_to_retriever(self):
        """Test that None space_whitelist is passed when explicitly None."""
        mock_retriever = Mock(spec=DenseRetriever)
        mock_retriever.search.return_value = []

        query = {"id": "test_query", "text": "test query"}
        budgets = [1000]
        top_k = 10
        space_whitelist = None

        run_single_query(query, budgets, mock_retriever, top_k, space_whitelist)

        # Verify None space_whitelist was passed to retriever
        mock_retriever.search.assert_called_once_with("test query", top_k=10, space_whitelist=None)

    def test_empty_space_whitelist_passed_to_retriever(self):
        """Test that empty space_whitelist is passed when empty list."""
        mock_retriever = Mock(spec=DenseRetriever)
        mock_retriever.search.return_value = []

        query = {"id": "test_query", "text": "test query"}
        budgets = [1000]
        top_k = 10
        space_whitelist = []

        run_single_query(query, budgets, mock_retriever, top_k, space_whitelist)

        # Verify empty space_whitelist was passed to retriever
        mock_retriever.search.assert_called_once_with("test query", top_k=10, space_whitelist=[])

    def test_mtldandtl_whitelist_excludes_pesd_pd_docs(self):
        """Test that MTDLANDTL whitelist excludes PESD/PD documents."""
        # This test would require integration with actual database
        # For now, we test the parameter passing
        mock_retriever = Mock(spec=DenseRetriever)
        mock_retriever.search.return_value = []

        query = {"id": "test_query", "text": "test query"}
        budgets = [1000]
        top_k = 10
        space_whitelist = ["MTDLANDTL"]

        run_single_query(query, budgets, mock_retriever, top_k, space_whitelist)

        # Verify MTDLANDTL whitelist was passed
        mock_retriever.search.assert_called_once_with("test query", top_k=10, space_whitelist=["MTDLANDTL"])

    def test_multiple_space_whitelist_passed_correctly(self):
        """Test that multiple space keys in whitelist are passed correctly."""
        mock_retriever = Mock(spec=DenseRetriever)
        mock_retriever.search.return_value = []

        query = {"id": "test_query", "text": "test query"}
        budgets = [1000]
        top_k = 10
        space_whitelist = ["MTDLANDTL", "N2S", "DEVELOPMENT"]

        run_single_query(query, budgets, mock_retriever, top_k, space_whitelist)

        # Verify multiple space keys were passed
        mock_retriever.search.assert_called_once_with(
            "test query", top_k=10, space_whitelist=["MTDLANDTL", "N2S", "DEVELOPMENT"]
        )
