"""Tests for Doc Anchors expectation functionality."""

from trailblazer.qa.expect import canon, contains_any, doc_slug


class TestDocAnchors:
    """Test document anchor matching and slug normalization."""

    def test_canon_basic(self):
        """Test basic text canonicalization."""
        assert canon("Hello World") == "hello world"
        assert canon("Test-Document") == "test document"
        assert canon("Test_Document") == "test document"
        assert canon("Test–Document") == "test document"  # emdash
        assert canon("Test—Document") == "test document"  # endash
        assert canon("Test...Document") == "test document"
        assert canon("Test (Document)") == "test document"
        assert canon("Test & Document") == "test document"

    def test_canon_edge_cases(self):
        """Test edge cases in canonicalization."""
        assert canon("") == ""
        assert canon("") == ""
        assert canon("   ") == ""
        assert canon("A-B-C") == "a b c"
        assert canon("A__B__C") == "a b c"
        assert canon("A  B  C") == "a b c"

    def test_doc_slug_confluence(self):
        """Test Confluence URL slug extraction."""
        url = "https://company.atlassian.net/wiki/spaces/DEV/pages/12345/Sprint-0-Architecture"
        title = "Sprint 0 Architecture"

        slug = doc_slug(url, title)
        assert slug == "sprint 0 architecture"

    def test_doc_slug_git(self):
        """Test Git URL slug extraction."""
        url = "https://github.com/company/repo/blob/main/docs/testing-strategy.md"
        title = "Testing Strategy"

        slug = doc_slug(url, title)
        assert slug == "testing strategy"

    def test_doc_slug_generic(self):
        """Test generic URL slug extraction."""
        url = "https://example.com/docs/runbook"
        title = "Runbook"

        slug = doc_slug(url, title)
        assert slug == "runbook"

    def test_doc_slug_fallback_title(self):
        """Test fallback to title when URL parsing fails."""
        url = "https://example.com/invalid"
        title = "Configuration Guide"

        slug = doc_slug(url, title)
        assert slug == "invalid"

    def test_doc_slug_no_url_title(self):
        """Test behavior with no URL or title."""
        assert doc_slug("", "") == ""
        assert doc_slug("", "") == ""

    def test_contains_any_basic(self):
        """Test basic term matching."""
        text = "This is a test document about testing strategy"

        assert contains_any(text, ["test"])
        assert contains_any(text, ["strategy"])
        assert not contains_any(text, ["missing"])
        assert not contains_any(text, [])
        assert not contains_any("", ["test"])

    def test_contains_any_hyphen_variants(self):
        """Test hyphen variant matching."""
        text = "This document covers capability-driven development"

        assert contains_any(text, ["capability-driven"])
        assert contains_any(text, ["capability driven"])
        # Test that different terms don't match
        assert not contains_any(text, ["capability led"])

    def test_contains_any_case_insensitive(self):
        """Test case insensitive matching."""
        text = "This document covers Testing Strategy"

        assert contains_any(text, ["testing strategy"])
        assert contains_any(text, ["TESTING STRATEGY"])
        assert contains_any(text, ["Testing Strategy"])

    def test_contains_any_token_boundaries(self):
        """Test token boundary matching."""
        text = "This document covers testing strategy and test automation"

        # Should match "testing strategy" as a phrase
        assert contains_any(text, ["testing strategy"])

        # Should match "test automation" as a phrase
        assert contains_any(text, ["test automation"])

        # Should not match partial words
        assert not contains_any(text, ["testin"])
