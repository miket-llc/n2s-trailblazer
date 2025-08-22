"""Integration tests for expectation harness with real artifacts."""

from unittest.mock import patch

from trailblazer.qa.expect import evaluate_query_expectations


class TestExpectationsIntegration:
    """Test expectation harness with realistic data."""

    def test_with_sample_artifacts(self):
        """Test expectation evaluation with sample retrieved items."""
        # Sample retrieved items that might come from a real query
        retrieved_items = [
            {
                "doc_id": "doc1",
                "chunk_id": "chunk1",
                "score": 0.95,
                "title": "Sprint 0 Architecture Alignment",
                "url": "https://confluence.com/pages/123/Sprint-0-Architecture",
                "snippet": "This document covers the Sprint 0 approach for architecture alignment and capability-driven development.",
                "source_system": "confluence",
            },
            {
                "doc_id": "doc2",
                "chunk_id": "chunk2",
                "score": 0.87,
                "title": "Testing Strategy Overview",
                "url": "https://confluence.com/pages/456/Testing-Strategy",
                "snippet": "Comprehensive testing strategy including continuous testing and test automation approaches.",
                "source_system": "confluence",
            },
            {
                "doc_id": "doc3",
                "chunk_id": "chunk3",
                "score": 0.82,
                "title": "Governance Model",
                "url": "https://confluence.com/pages/789/Governance-Model",
                "snippet": "Project governance framework with RACI matrices and decision rights.",
                "source_system": "confluence",
            },
        ]

        # Test with lifecycle_overview query
        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            mock_load.return_value = (
                {
                    "lifecycle_overview": {
                        "any_doc_slugs": [
                            "sprint 0 architecture",
                            "discovery workshops",
                            "navigate to saas overview",
                        ]
                    }
                },
                {
                    "require_by_query": {"lifecycle_overview": ["sprint0", "governance"]},
                    "groups": {
                        "sprint0": {"any_of": ["sprint 0", "architecture alignment", "aaw"]},
                        "governance": {"any_of": ["governance", "raaci", "raci", "decision rights"]},
                    },
                },
            )

            result = evaluate_query_expectations("lifecycle_overview", retrieved_items, top_k=12, threshold=0.7)

            # Should pass: anchors hit (sprint 0 architecture)
            # and concepts hit (sprint0, governance groups)
            assert result["passed"]
            assert result["score"] >= 0.7
            assert "sprint 0 architecture" in result["anchors_hit"]
            assert "sprint0" in result["hit_groups"]
            assert "governance" in result["hit_groups"]

    def test_with_missing_expectations(self):
        """Test behavior when expectation files are missing."""
        # Test with query that has no expectations defined
        retrieved_items = [{"title": "Some Document", "url": "https://example.com/doc", "snippet": "Some content"}]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            # Return empty expectations
            mock_load.return_value = ({}, {})

            result = evaluate_query_expectations("unknown_query", retrieved_items)

            # Should handle gracefully with empty expectations
            assert result["anchors_score"] == 0.0
            assert result["concepts_score"] == 1.0  # No required groups = 1.0
            assert result["score"] == 0.4  # 0.6 * 0.0 + 0.4 * 1.0
            assert not result["passed"]  # Below 0.7 threshold

    def test_top_k_limiting(self):
        """Test that top_k properly limits items considered."""
        # Create more items than top_k
        retrieved_items = [
            {"title": f"Document {i}", "url": f"https://example.com/doc{i}", "snippet": f"Content {i}"}
            for i in range(20)  # More than top_k=12
        ]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            mock_load.return_value = (
                {
                    "test_query": {
                        "any_doc_slugs": ["doc15"]  # URL path component
                    }
                },
                {},
            )

            # Test with top_k=5 (should not find document 15)
            result = evaluate_query_expectations("test_query", retrieved_items, top_k=5)

            assert result["anchors_score"] == 0.0
            assert result["score"] == 0.4  # 0.6 * 0.0 + 0.4 * 1.0 (no concepts defined)

            # Test with top_k=20 (should find document 15)
            result = evaluate_query_expectations("test_query", retrieved_items, top_k=20)

            assert result["anchors_score"] == 1.0
            assert result["score"] == 1.0

    def test_threshold_variations(self):
        """Test different threshold values affect pass/fail decisions."""
        retrieved_items = [
            {
                "title": "Test Document",
                "url": "https://example.com/doc",
                "snippet": "This document covers testing strategy",
            }
        ]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            mock_load.return_value = (
                {},
                {
                    "require_by_query": {"test_query": ["testing_strategy"]},
                    "groups": {"testing_strategy": {"any_of": ["testing strategy", "test strategy"]}},
                },
            )

            # Test with low threshold (0.3) - should pass
            result = evaluate_query_expectations("test_query", retrieved_items, threshold=0.3)

            assert result["passed"]

            # Test with high threshold (0.9) - should fail
            result = evaluate_query_expectations("test_query", retrieved_items, threshold=0.9)

            assert not result["passed"]
