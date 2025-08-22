"""Tests for mixed expectation scenarios."""

from unittest.mock import patch

from trailblazer.qa.expect import evaluate_query_expectations


class TestMixedScenarios:
    """Test various combinations of anchor and concept scoring."""

    def test_anchors_only_pass(self):
        """Test scenario where only anchors pass."""
        # Mock retrieved items with matching slug
        retrieved_items = [
            {
                "url": "https://confluence.com/pages/123/sprint-0-architecture",
                "title": "Sprint 0 Architecture",
                "snippet": "This document covers unrelated content",
            }
        ]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            # Mock anchors with matching slug
            mock_load.return_value = (
                {"test_query": {"any_doc_slugs": ["sprint 0 architecture"]}},
                {
                    "require_by_query": {"test_query": ["testing_strategy"]},
                    "groups": {
                        "testing_strategy": {
                            "any_of": ["testing strategy", "test strategy"]
                        }
                    },
                },
            )

            result = evaluate_query_expectations(
                "test_query", retrieved_items, mode="doc+concept"
            )

            # Anchors should pass (1.0), concepts should fail (0.0)
            # Final score: 0.6 * 1.0 + 0.4 * 0.0 = 0.6
            assert result["anchors_score"] == 1.0
            assert result["concepts_score"] == 0.0
            assert result["score"] == 0.6
            assert not result["passed"]  # Below 0.7 threshold

    def test_concepts_only_pass(self):
        """Test scenario where only concepts pass."""
        # Mock retrieved items with no matching slug but matching content
        retrieved_items = [
            {
                "url": "https://confluence.com/pages/123/unrelated",
                "title": "Unrelated Document",
                "snippet": "This document covers testing strategy and automation",
            }
        ]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            # Mock anchors with no matching slug
            mock_load.return_value = (
                {"test_query": {"any_doc_slugs": ["sprint 0 architecture"]}},
                {
                    "require_by_query": {"test_query": ["testing_strategy"]},
                    "groups": {
                        "testing_strategy": {
                            "any_of": ["testing strategy", "test strategy"]
                        }
                    },
                },
            )

            result = evaluate_query_expectations(
                "test_query", retrieved_items, mode="doc+concept"
            )

            # Anchors should fail (0.0), concepts should pass (1.0)
            # Final score: 0.6 * 0.0 + 0.4 * 1.0 = 0.4
            assert result["anchors_score"] == 0.0
            assert result["concepts_score"] == 1.0
            assert result["score"] == 0.4
            assert not result["passed"]  # Below 0.7 threshold

    def test_both_pass(self):
        """Test scenario where both anchors and concepts pass."""
        # Mock retrieved items with matching slug and content
        retrieved_items = [
            {
                "url": "https://confluence.com/pages/123/sprint-0-architecture",
                "title": "Sprint 0 Architecture",
                "snippet": "This document covers testing strategy and automation",
            }
        ]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            # Mock both anchors and concepts with matches
            mock_load.return_value = (
                {"test_query": {"any_doc_slugs": ["sprint 0 architecture"]}},
                {
                    "require_by_query": {"test_query": ["testing_strategy"]},
                    "groups": {
                        "testing_strategy": {
                            "any_of": ["testing strategy", "test strategy"]
                        }
                    },
                },
            )

            result = evaluate_query_expectations(
                "test_query", retrieved_items, mode="doc+concept"
            )

            # Both should pass (1.0)
            # Final score: 0.6 * 1.0 + 0.4 * 1.0 = 1.0
            assert result["anchors_score"] == 1.0
            assert result["concepts_score"] == 1.0
            assert result["score"] == 1.0
            assert result["passed"]  # Above 0.7 threshold

    def test_neither_pass(self):
        """Test scenario where neither anchors nor concepts pass."""
        # Mock retrieved items with no matches
        retrieved_items = [
            {
                "url": "https://confluence.com/pages/123/unrelated",
                "title": "Unrelated Document",
                "snippet": "This document covers unrelated content",
            }
        ]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            # Mock both anchors and concepts with no matches
            mock_load.return_value = (
                {"test_query": {"any_doc_slugs": ["sprint 0 architecture"]}},
                {
                    "require_by_query": {"test_query": ["testing_strategy"]},
                    "groups": {
                        "testing_strategy": {
                            "any_of": ["testing strategy", "test strategy"]
                        }
                    },
                },
            )

            result = evaluate_query_expectations(
                "test_query", retrieved_items, mode="doc+concept"
            )

            # Both should fail (0.0)
            # Final score: 0.6 * 0.0 + 0.4 * 0.0 = 0.0
            assert result["anchors_score"] == 0.0
            assert result["concepts_score"] == 0.0
            assert result["score"] == 0.0
            assert not result["passed"]  # Below 0.7 threshold

    def test_doc_only_mode(self):
        """Test doc-only scoring mode."""
        retrieved_items = [
            {
                "url": "https://confluence.com/pages/123/sprint-0-architecture",
                "title": "Sprint 0 Architecture",
                "snippet": "This document covers unrelated content",
            }
        ]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            mock_load.return_value = (
                {"test_query": {"any_doc_slugs": ["sprint 0 architecture"]}},
                {},
            )

            result = evaluate_query_expectations(
                "test_query", retrieved_items, mode="doc-only"
            )

            # Only anchors should be considered
            assert result["score"] == 1.0
            assert result["passed"]

    def test_concept_only_mode(self):
        """Test concept-only scoring mode."""
        retrieved_items = [
            {
                "url": "https://confluence.com/pages/123/unrelated",
                "title": "Unrelated Document",
                "snippet": "This document covers testing strategy",
            }
        ]

        with patch("trailblazer.qa.expect.load_expectations") as mock_load:
            mock_load.return_value = (
                {},
                {
                    "require_by_query": {"test_query": ["testing_strategy"]},
                    "groups": {
                        "testing_strategy": {
                            "any_of": ["testing strategy", "test strategy"]
                        }
                    },
                },
            )

            result = evaluate_query_expectations(
                "test_query", retrieved_items, mode="concept-only"
            )

            # Only concepts should be considered
            assert result["score"] == 1.0
            assert result["passed"]
