"""Tests for Concept Groups expectation functionality."""

from trailblazer.qa.expect import contains_any


class TestConceptGroups:
    """Test concept group matching and synonym handling."""

    def test_group_matching_basic(self):
        """Test basic group term matching."""
        text = "This document covers testing strategy and QA processes"

        # Testing strategy group
        terms = ["testing strategy", "test strategy", "qa strategy"]
        assert contains_any(text, terms)

        # Continuous testing group
        terms = ["continuous testing", "test automation", "shift-left"]
        assert not contains_any(text, terms)

    def test_group_matching_hyphen_variants(self):
        """Test hyphen variant matching."""
        text = "This document covers capability-driven development"

        # Capability driven group
        terms = ["capability-driven", "capability led", "capability-led"]
        assert contains_any(text, terms)

        # Test with space variant
        text = "This document covers capability led development"
        assert contains_any(text, terms)

    def test_group_matching_bigrams(self):
        """Test bigram term matching."""
        text = "This document covers integration patterns and API design"

        # Integration patterns group
        terms = ["integration patterns", "ethos", "api pattern"]
        assert contains_any(text, terms)

        # Test with different bigram
        text = "This document covers api pattern and batch interfaces"
        assert contains_any(text, terms)

    def test_group_matching_case_insensitive(self):
        """Test case insensitive group matching."""
        text = "This document covers Governance and RACI processes"

        # Governance group
        terms = ["governance", "raaci", "raci", "decision rights"]
        assert contains_any(text, terms)

        # Test with lowercase
        text = "This document covers governance and raci processes"
        assert contains_any(text, terms)

    def test_group_matching_mixed_content(self):
        """Test matching in mixed title and snippet content."""
        title = "Sprint 0 Architecture Alignment"
        snippet = "This document covers the foundations sprint approach"

        combined = f"{title} {snippet}"

        # Sprint0 group
        terms = ["sprint 0", "architecture alignment", "aaw", "foundations sprint"]
        assert contains_any(combined, terms)

    def test_group_matching_no_matches(self):
        """Test when no group terms match."""
        text = "This document covers unrelated content"

        # Runbook group
        terms = ["runbook", "playbook", "sop", "operational guide"]
        assert not contains_any(text, terms)

    def test_group_matching_empty_terms(self):
        """Test edge cases with empty terms."""
        text = "This document covers testing strategy"

        assert not contains_any(text, [])
        assert not contains_any(text, [""])
        assert contains_any(text, ["", "testing"])

    def test_group_matching_special_characters(self):
        """Test matching with special characters in terms."""
        text = "This document covers shift-left testing approaches"

        # Continuous testing group with special characters
        terms = ["shift-left", "shift left", "ci testing"]
        assert contains_any(text, terms)
