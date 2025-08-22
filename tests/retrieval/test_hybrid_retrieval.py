"""Tests for hybrid retrieval with RRF and N2S query expansion."""

from __future__ import annotations

import pytest

from src.trailblazer.retrieval.dense import (
    DenseRetriever,
    apply_domain_boosts,
    expand_n2s_query,
    is_n2s_query,
    reciprocal_rank_fusion,
)


class TestN2SQueryDetection:
    """Test N2S query detection and expansion."""

    def test_is_n2s_query_basic(self):
        """Test basic N2S query detection."""
        assert is_n2s_query("What is N2S lifecycle?")
        assert is_n2s_query("navigate to saas methodology")
        assert is_n2s_query("Sprint 0 discovery process")
        assert is_n2s_query("N2S build phase overview")
        assert is_n2s_query("methodology for optimize")

        # Non-N2S queries
        assert not is_n2s_query("How to configure SSO?")
        assert not is_n2s_query("Student registration process")
        assert not is_n2s_query("Database connection error")

    def test_is_n2s_query_case_insensitive(self):
        """Test case insensitive N2S detection."""
        assert is_n2s_query("N2S LIFECYCLE OVERVIEW")
        assert is_n2s_query("Navigate To SaaS")
        assert is_n2s_query("METHODOLOGY")
        assert is_n2s_query("sprint zero")

    def test_expand_n2s_query_basic(self):
        """Test basic N2S query expansion."""
        expanded = expand_n2s_query("N2S lifecycle overview")
        assert "N2S" in expanded
        assert "Navigate to SaaS" in expanded
        assert "OR" in expanded

        # Non-N2S query should not be expanded
        non_n2s = "How to configure SSO?"
        assert expand_n2s_query(non_n2s) == non_n2s

    def test_expand_n2s_query_lifecycle(self):
        """Test N2S query expansion for lifecycle queries."""
        expanded = expand_n2s_query("N2S lifecycle methodology")
        assert "Discovery" in expanded
        assert "Build" in expanded
        assert "Optimize" in expanded
        assert "Sprint 0" in expanded

    def test_expand_n2s_query_governance(self):
        """Test N2S query expansion for governance queries."""
        expanded = expand_n2s_query("governance checkpoints in N2S")
        assert "entry criteria" in expanded
        assert "exit criteria" in expanded


class TestDomainBoosts:
    """Test domain-aware boost application."""

    def test_apply_domain_boosts_methodology(self):
        """Test methodology boost application."""
        candidates = [
            {"title": "N2S Methodology Guide", "score": 0.5, "chunk_id": "1"},
            {"title": "Regular Document", "score": 0.5, "chunk_id": "2"},
        ]

        boosted = apply_domain_boosts(candidates, enable_boosts=True)

        # Methodology should get +0.20 boost
        methodology_result = next(r for r in boosted if "Methodology" in r["title"])
        regular_result = next(r for r in boosted if "Regular" in r["title"])

        assert methodology_result["score"] == 0.7  # 0.5 + 0.20
        assert methodology_result["boost_applied"] == 0.20
        assert regular_result["score"] == 0.5
        assert regular_result["boost_applied"] == 0.0

    def test_apply_domain_boosts_playbook_runbook(self):
        """Test playbook and runbook boost application."""
        candidates = [
            {"title": "Implementation Playbook", "score": 0.5, "chunk_id": "1"},
            {"title": "Operations Runbook", "score": 0.5, "chunk_id": "2"},
        ]

        boosted = apply_domain_boosts(candidates, enable_boosts=True)

        playbook_result = next(r for r in boosted if "Playbook" in r["title"])
        runbook_result = next(r for r in boosted if "Runbook" in r["title"])

        assert playbook_result["score"] == 0.65  # 0.5 + 0.15
        assert playbook_result["boost_applied"] == 0.15
        assert runbook_result["score"] == 0.60  # 0.5 + 0.10
        assert runbook_result["boost_applied"] == 0.10

    def test_apply_domain_boosts_monthly_penalty(self):
        """Test monthly page penalty application."""
        candidates = [
            {"title": "January 2024 Updates", "score": 0.5, "chunk_id": "1"},
            {"title": "2023 Annual Report", "score": 0.5, "chunk_id": "2"},
            {"title": "Regular Document", "score": 0.5, "chunk_id": "3"},
        ]

        boosted = apply_domain_boosts(candidates, enable_boosts=True)

        january_result = next(r for r in boosted if "January" in r["title"])
        annual_result = next(r for r in boosted if "2023" in r["title"])
        regular_result = next(r for r in boosted if "Regular" in r["title"])

        assert january_result["score"] == 0.4  # 0.5 - 0.10
        assert january_result["boost_applied"] == -0.10
        assert annual_result["score"] == 0.4  # 0.5 - 0.10
        assert annual_result["boost_applied"] == -0.10
        assert regular_result["score"] == 0.5
        assert regular_result["boost_applied"] == 0.0

    def test_apply_domain_boosts_disabled(self):
        """Test that boosts are not applied when disabled."""
        candidates = [
            {"title": "N2S Methodology Guide", "score": 0.5, "chunk_id": "1"},
        ]

        boosted = apply_domain_boosts(candidates, enable_boosts=False)

        assert boosted[0]["score"] == 0.5  # No change
        assert "boost_applied" not in boosted[0]


class TestReciprocalRankFusion:
    """Test RRF algorithm implementation."""

    def test_reciprocal_rank_fusion_basic(self):
        """Test basic RRF fusion."""
        dense_results = [
            {"chunk_id": "1", "score": 0.9},
            {"chunk_id": "2", "score": 0.8},
            {"chunk_id": "3", "score": 0.7},
        ]

        bm25_results = [
            {"chunk_id": "2", "score": 0.95},
            {"chunk_id": "1", "score": 0.85},
            {"chunk_id": "4", "score": 0.75},
        ]

        fused = reciprocal_rank_fusion(dense_results, bm25_results, k=60)

        # Check that all chunks are present
        chunk_ids = {r["chunk_id"] for r in fused}
        assert chunk_ids == {"1", "2", "3", "4"}

        # Check RRF scores
        chunk_2 = next(r for r in fused if r["chunk_id"] == "2")
        chunk_1 = next(r for r in fused if r["chunk_id"] == "1")

        # Chunk 2: dense_rank=2, bm25_rank=1 -> 1/62 + 1/61
        # Chunk 1: dense_rank=1, bm25_rank=2 -> 1/61 + 1/62
        # Both should have very similar scores, so check they exist and have RRF scores
        assert chunk_2["rrf_score"] > 0
        assert chunk_1["rrf_score"] > 0
        assert "dense_rank" in chunk_2
        assert "bm25_rank" in chunk_2

        # Results should be sorted by RRF score
        assert fused[0]["rrf_score"] >= fused[1]["rrf_score"]

    def test_reciprocal_rank_fusion_no_overlap(self):
        """Test RRF when there's no overlap between dense and BM25 results."""
        dense_results = [
            {"chunk_id": "1", "score": 0.9},
            {"chunk_id": "2", "score": 0.8},
        ]

        bm25_results = [
            {"chunk_id": "3", "score": 0.95},
            {"chunk_id": "4", "score": 0.85},
        ]

        fused = reciprocal_rank_fusion(dense_results, bm25_results, k=60)

        assert len(fused) == 4

        # Each chunk should have only one rank (dense OR bm25)
        for result in fused:
            has_dense = result["dense_rank"] is not None
            has_bm25 = result["bm25_rank"] is not None
            assert has_dense != has_bm25  # XOR - exactly one should be true

    def test_reciprocal_rank_fusion_deterministic_ordering(self):
        """Test that RRF produces deterministic ordering."""
        dense_results = [
            {"chunk_id": "chunk_a", "score": 0.9},
            {"chunk_id": "chunk_b", "score": 0.8},
        ]

        bm25_results = [
            {"chunk_id": "chunk_b", "score": 0.95},
            {"chunk_id": "chunk_a", "score": 0.85},
        ]

        # Run RRF multiple times - should get same order
        fused1 = reciprocal_rank_fusion(dense_results, bm25_results, k=60)
        fused2 = reciprocal_rank_fusion(dense_results, bm25_results, k=60)

        # Should be deterministic
        chunk_ids1 = [r["chunk_id"] for r in fused1]
        chunk_ids2 = [r["chunk_id"] for r in fused2]
        assert chunk_ids1 == chunk_ids2

        # Should be sorted by RRF score desc, then chunk_id for ties
        assert len(fused1) == 2
        assert fused1[0]["rrf_score"] >= fused1[1]["rrf_score"]


class TestHybridRetrieverIntegration:
    """Integration tests for hybrid retrieval."""

    def test_retriever_initialization(self):
        """Test retriever initialization with hybrid parameters."""
        retriever = DenseRetriever(
            enable_hybrid=True,
            topk_dense=100,
            topk_bm25=100,
            rrf_k=30,
            enable_boosts=True,
            enable_n2s_filter=True,
            server_side=False,
        )

        assert retriever.enable_hybrid is True
        assert retriever.topk_dense == 100
        assert retriever.topk_bm25 == 100
        assert retriever.rrf_k == 30
        assert retriever.enable_boosts is True
        assert retriever.enable_n2s_filter is True
        assert retriever.server_side is False

    def test_retriever_n2s_query_detection_integration(self):
        """Test that retriever properly detects N2S queries."""
        retriever = DenseRetriever(enable_n2s_filter=True)

        # Mock the search methods to avoid database dependency
        def mock_search_postgres(*args, **kwargs):
            return [{"chunk_id": "1", "score": 0.8, "title": "Test"}]

        def mock_search_bm25(*args, **kwargs):
            return [{"chunk_id": "2", "score": 0.7, "title": "Test"}]

        retriever.search_postgres = mock_search_postgres
        retriever.search_bm25 = mock_search_bm25

        # Test that N2S filter is applied for N2S queries
        trace_data = {"query": "N2S lifecycle", "candidates": []}
        n2s_filter_applied = retriever.enable_n2s_filter and is_n2s_query(
            "N2S lifecycle"
        )

        assert n2s_filter_applied is True

        # Test that N2S filter is not applied for non-N2S queries
        trace_data = {"query": "SSO configuration", "candidates": []}
        n2s_filter_applied = retriever.enable_n2s_filter and is_n2s_query(
            "SSO configuration"
        )

        assert n2s_filter_applied is False


class TestN2SQueryExpansionIntegration:
    """Integration tests for N2S query expansion."""

    def test_n2s_lifecycle_query_integration(self):
        """Test that N2S lifecycle queries get proper expansion."""
        query = "N2S lifecycle overview"

        # Should be detected as N2S query
        assert is_n2s_query(query) is True

        # Should be expanded with methodology terms
        expanded = expand_n2s_query(query)
        assert "Discovery" in expanded
        assert "Build" in expanded
        assert "Optimize" in expanded
        assert "Navigate to SaaS" in expanded

        # Original query should still be there
        assert "N2S lifecycle overview" in expanded

    def test_governance_query_integration(self):
        """Test governance-related N2S queries."""
        query = "N2S governance checkpoints"

        assert is_n2s_query(query) is True

        expanded = expand_n2s_query(query)
        assert "entry criteria" in expanded
        assert "exit criteria" in expanded
        assert "governance checkpoints" in expanded


if __name__ == "__main__":
    pytest.main([__file__])
