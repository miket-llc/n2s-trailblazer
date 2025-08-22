"""Test for N2S query requirement: top-5 should contain Methodology documents."""

from __future__ import annotations

import pytest

from src.trailblazer.retrieval.dense import (
    apply_domain_boosts,
    expand_n2s_query,
    is_n2s_query,
    reciprocal_rank_fusion,
)

# Mark all tests as unit tests - these test pure functions and algorithms  
pytestmark = pytest.mark.unit


class TestN2SMethodologyRequirement:
    """Test that N2S queries return Methodology documents in top-5."""

    def test_n2s_lifecycle_methodology_in_top_5(self):
        """
        Test that query='N2S lifecycle overview' returns at least one
        doctype=Methodology node in top-5 results.
        """
        # Simulate search results with various document types
        mock_dense_results = [
            {
                "chunk_id": "doc1:0001",
                "doc_id": "doc1",
                "title": "N2S Implementation Playbook",
                "score": 0.85,
                "meta": {"doctype": "Playbook"},
            },
            {
                "chunk_id": "doc2:0001",
                "doc_id": "doc2",
                "title": "Student Registration Guide",
                "score": 0.80,
                "meta": {"doctype": "Guide"},
            },
            {
                "chunk_id": "doc3:0001",
                "doc_id": "doc3",
                "title": "N2S Lifecycle Methodology",
                "score": 0.75,
                "meta": {"doctype": "Methodology"},
            },
        ]

        mock_bm25_results = [
            {
                "chunk_id": "doc4:0001",
                "doc_id": "doc4",
                "title": "Navigate to SaaS Overview",
                "score": 0.90,
                "meta": {"doctype": "Overview"},
            },
            {
                "chunk_id": "doc3:0001",  # Same as dense (overlap)
                "doc_id": "doc3",
                "title": "N2S Lifecycle Methodology",
                "score": 0.85,
                "meta": {"doctype": "Methodology"},
            },
            {
                "chunk_id": "doc5:0001",
                "doc_id": "doc5",
                "title": "Sprint 0 Discovery Process",
                "score": 0.70,
                "meta": {"doctype": "Process"},
            },
        ]

        # Apply RRF fusion
        fused_results = reciprocal_rank_fusion(mock_dense_results, mock_bm25_results, k=60)

        # Apply domain boosts (Methodology gets +0.20)
        boosted_results = apply_domain_boosts(fused_results, enable_boosts=True)

        # Sort by final score and take top-5
        top_5 = sorted(boosted_results, key=lambda x: (-x["score"], x["chunk_id"]))[:5]

        # Check that at least one result in top-5 has doctype=Methodology
        methodology_in_top_5 = any(
            result.get("meta", {}).get("doctype") == "Methodology" or "methodology" in result.get("title", "").lower()
            for result in top_5
        )

        assert methodology_in_top_5, (
            f"Expected at least one Methodology document in top-5 results. Got: {[r.get('title', '') for r in top_5]}"
        )

        # Verify the Methodology document got the expected boost
        methodology_result = next(
            (r for r in boosted_results if "methodology" in r.get("title", "").lower()),
            None,
        )

        assert methodology_result is not None
        assert methodology_result.get("boost_applied", 0) == 0.20

    def test_n2s_query_detection_for_lifecycle(self):
        """Test that 'N2S lifecycle overview' is correctly detected as N2S query."""
        query = "N2S lifecycle overview"

        assert is_n2s_query(query) is True

        # Should trigger query expansion
        expanded = expand_n2s_query(query)
        assert expanded != query  # Should be different from original
        assert "Discovery" in expanded
        assert "Build" in expanded
        assert "Optimize" in expanded

    def test_boosts_disabled_reduces_methodology_likelihood(self):
        """
        Sanity check: turning --boosts off should reduce likelihood of
        Methodology in top-5 (compared to boosts enabled).
        """
        # Same test data as above
        mock_dense_results = [
            {
                "chunk_id": "doc1:0001",
                "doc_id": "doc1",
                "title": "High Score Non-Methodology",
                "score": 0.95,  # Very high score
                "meta": {"doctype": "Guide"},
            },
            {
                "chunk_id": "doc2:0001",
                "doc_id": "doc2",
                "title": "N2S Lifecycle Methodology",
                "score": 0.70,  # Lower base score
                "meta": {"doctype": "Methodology"},
            },
        ]

        mock_bm25_results = [
            {
                "chunk_id": "doc3:0001",
                "doc_id": "doc3",
                "title": "Another High Score Document",
                "score": 0.90,
                "meta": {"doctype": "Process"},
            },
        ]

        # Test with boosts enabled
        fused_with_boosts = reciprocal_rank_fusion(mock_dense_results, mock_bm25_results, k=60)
        boosted_with_boosts = apply_domain_boosts(fused_with_boosts, enable_boosts=True)

        # Test with boosts disabled
        fused_no_boosts = reciprocal_rank_fusion(mock_dense_results, mock_bm25_results, k=60)
        boosted_no_boosts = apply_domain_boosts(fused_no_boosts, enable_boosts=False)

        # Find methodology document scores
        methodology_with_boosts = next(r for r in boosted_with_boosts if "methodology" in r.get("title", "").lower())

        methodology_no_boosts = next(r for r in boosted_no_boosts if "methodology" in r.get("title", "").lower())

        # With boosts, methodology should have higher score
        assert methodology_with_boosts["score"] > methodology_no_boosts["score"], (
            f"Expected Methodology to have higher score with boosts enabled. "
            f"With boosts: {methodology_with_boosts['score']:.3f}, "
            f"without boosts: {methodology_no_boosts['score']:.3f}"
        )

    def test_n2s_filter_restricts_to_n2s_documents(self):
        """Test that N2S filter restricts results to N2S-related documents."""
        # Mock documents - some N2S related, some not
        mock_candidates = [
            {
                "chunk_id": "doc1:0001",
                "title": "N2S Implementation Guide",
                "score": 0.80,
                "meta": {"doctype": "Methodology"},
            },
            {
                "chunk_id": "doc2:0001",
                "title": "Student Registration Process",
                "score": 0.85,  # Higher score but not N2S
                "meta": {"doctype": "Process"},
            },
            {
                "chunk_id": "doc3:0001",
                "title": "Navigate to SaaS Playbook",
                "score": 0.75,
                "meta": {"doctype": "Playbook"},
            },
            {
                "chunk_id": "doc4:0001",
                "title": "Database Configuration",
                "score": 0.90,  # Highest score but not N2S
                "meta": {"doctype": "Configuration"},
            },
        ]

        # Simulate N2S filtering (would be done in SQL, but test logic here)
        def is_n2s_document(doc):
            title = doc.get("title", "").lower()
            doctype = doc.get("meta", {}).get("doctype", "").lower()

            n2s_terms = [
                "n2s",
                "navigate to saas",
                "methodology",
                "playbook",
                "runbook",
            ]
            return any(term in title for term in n2s_terms) or doctype in [
                "methodology",
                "playbook",
                "runbook",
            ]

        n2s_filtered = [doc for doc in mock_candidates if is_n2s_document(doc)]

        # Should only include N2S-related documents
        # Expected: "N2S Implementation Guide" (has N2S + Methodology),
        #           "Navigate to SaaS Playbook" (has Navigate to SaaS + Playbook)
        # Excluded: "Student Registration Process", "Database Configuration"
        assert len(n2s_filtered) == 2  # Only the N2S-related documents

        titles = [doc["title"] for doc in n2s_filtered]
        assert "N2S Implementation Guide" in titles
        assert "Navigate to SaaS Playbook" in titles
        assert "Student Registration Process" not in titles
        assert "Database Configuration" not in titles


if __name__ == "__main__":
    pytest.main([__file__])
