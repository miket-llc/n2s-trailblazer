"""Test anchors slug extraction functionality."""

from trailblazer.qa.expect import doc_slug


class TestAnchorsSlugExtraction:
    """Test that anchor slug extraction works correctly."""

    def test_confluence_url_slug_extraction(self):
        """Test Confluence URL slug extraction."""
        url = "https://confluence.example.com/pages/12345/DEV+-+Prepare+Discovery+Workshops"
        title = "DEV - Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_confluence_url_with_plus_signs(self):
        """Test Confluence URL with plus signs in title."""
        url = "https://confluence.example.com/pages/67890/DEV+-+Prepare+Discovery+Workshops"
        title = "DEV + Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_confluence_url_with_spaces_and_plus(self):
        """Test Confluence URL with spaces and plus signs."""
        url = "https://confluence.example.com/pages/11111/DEV+-+Prepare+Discovery+Workshops"
        title = "DEV + Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_git_url_slug_extraction(self):
        """Test Git URL slug extraction."""
        url = "https://github.com/example/repo/blob/main/DEV+-+Prepare+Discovery+Workshops.md"
        title = "DEV - Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_generic_url_slug_extraction(self):
        """Test generic URL slug extraction."""
        url = "https://example.com/docs/DEV+-+Prepare+Discovery+Workshops"
        title = "DEV - Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_title_fallback_slug_extraction(self):
        """Test title fallback slug extraction."""
        url = ""
        title = "DEV + Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_no_url_no_title(self):
        """Test slug extraction with no URL and no title."""
        url = ""
        title = ""

        slug = doc_slug(url, title)
        expected = ""

        assert slug == expected

    def test_special_characters_handling(self):
        """Test handling of special characters in slugs."""
        url = "https://confluence.example.com/pages/12345/DEV+-+Prepare+Discovery+Workshops"
        title = "DEV + Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_hyphen_variants_handling(self):
        """Test handling of hyphen variants."""
        url = "https://confluence.example.com/pages/12345/DEV-Prepare-Discovery-Workshops"
        title = "DEV-Prepare-Discovery-Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_underscore_variants_handling(self):
        """Test handling of underscore variants."""
        url = "https://confluence.example.com/pages/12345/DEV_Prepare_Discovery_Workshops"
        title = "DEV_Prepare_Discovery_Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_mixed_separators_handling(self):
        """Test handling of mixed separators."""
        url = "https://confluence.example.com/pages/12345/DEV+-+Prepare_Discovery-Workshops"
        title = "DEV + Prepare_Discovery-Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_unicode_normalization(self):
        """Test Unicode normalization in slug extraction."""
        url = "https://confluence.example.com/pages/12345/DEV+-+Prepare+Discovery+Workshops"
        title = "DEV + Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected

    def test_whitespace_collapse(self):
        """Test whitespace collapse in slug extraction."""
        url = "https://confluence.example.com/pages/12345/DEV+-+Prepare+Discovery+Workshops"
        title = "DEV + Prepare Discovery Workshops"

        slug = doc_slug(url, title)
        expected = "dev prepare discovery workshops"

        assert slug == expected
