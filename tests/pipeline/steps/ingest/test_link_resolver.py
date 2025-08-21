"""Tests for link resolution and classification helpers."""

from trailblazer.pipeline.steps.ingest.link_resolver import (
    normalize_url,
    classify_link_type,
    extract_confluence_page_id,
    extract_links_from_storage_with_classification,
    extract_links_from_adf_with_classification,
)


class TestNormalizeUrl:
    """Test URL normalization."""

    def test_normalize_removes_tracking_params(self):
        url = "https://example.com/page?utm_source=test&utm_medium=email&real_param=value"
        result = normalize_url(url)
        assert result == "https://example.com/page?real_param=value"

    def test_normalize_preserves_anchors(self):
        url = "https://example.com/page?utm_source=test#section1"
        result = normalize_url(url)
        assert result == "https://example.com/page#section1"

    def test_normalize_handles_empty_url(self):
        assert normalize_url("") == ""
        assert normalize_url(None) is None

    def test_normalize_no_query_params(self):
        url = "https://example.com/page"
        result = normalize_url(url)
        assert result == url


class TestClassifyLinkType:
    """Test link type classification."""

    def test_classify_confluence_absolute(self):
        confluence_base = "https://example.atlassian.net/wiki"
        url = "https://example.atlassian.net/wiki/spaces/DEV/pages/123456/Test"
        result = classify_link_type(url, confluence_base)
        assert result == "confluence"

    def test_classify_confluence_relative(self):
        confluence_base = "https://example.atlassian.net/wiki"
        url = "/spaces/DEV/pages/123456/Test"
        result = classify_link_type(url, confluence_base)
        assert result == "confluence"

    def test_classify_attachment_relative(self):
        confluence_base = "https://example.atlassian.net/wiki"
        url = "/download/attachments/123456/file.pdf"
        result = classify_link_type(url, confluence_base)
        assert result == "attachment"

    def test_classify_attachment_absolute(self):
        confluence_base = "https://example.atlassian.net/wiki"
        url = "https://example.atlassian.net/download/attachments/123456/file.pdf"
        result = classify_link_type(url, confluence_base)
        assert result == "attachment"

    def test_classify_external(self):
        confluence_base = "https://example.atlassian.net/wiki"
        url = "https://google.com"
        result = classify_link_type(url, confluence_base)
        assert result == "external"

    def test_classify_empty_url(self):
        confluence_base = "https://example.atlassian.net/wiki"
        result = classify_link_type("", confluence_base)
        assert result == "external"


class TestExtractConfluencePageId:
    """Test Confluence page ID extraction."""

    def test_extract_spaces_pattern(self):
        url = "/spaces/DEV/pages/123456/Page+Title"
        result = extract_confluence_page_id(url)
        assert result == "123456"

    def test_extract_wiki_spaces_pattern(self):
        url = "/wiki/spaces/DEV/pages/789012/Another+Page"
        result = extract_confluence_page_id(url)
        assert result == "789012"

    def test_extract_viewpage_pattern(self):
        url = "/pages/viewpage.action?pageId=345678&spaceKey=DEV"
        result = extract_confluence_page_id(url)
        assert result == "345678"

    def test_extract_no_match(self):
        url = "/some/other/path"
        result = extract_confluence_page_id(url)
        assert result is None

    def test_extract_empty_url(self):
        result = extract_confluence_page_id("")
        assert result is None

        result = extract_confluence_page_id(None)
        assert result is None


class TestExtractLinksFromStorage:
    """Test link extraction from Storage format."""

    def test_extract_basic_links(self):
        xhtml = """
        <p>Check out <a href="https://example.com">Example</a> and
        <a href="/spaces/DEV/pages/123/Test">internal page</a></p>
        """
        confluence_base = "https://example.atlassian.net/wiki"

        links = extract_links_from_storage_with_classification(
            xhtml, confluence_base
        )

        assert len(links) == 2

        external_link = next(
            link for link in links if link.target_type == "external"
        )
        assert external_link.raw_url == "https://example.com"
        assert external_link.text == "Example"

        internal_link = next(
            link for link in links if link.target_type == "confluence"
        )
        assert internal_link.raw_url == "/spaces/DEV/pages/123/Test"
        assert internal_link.target_page_id == "123"
        assert internal_link.text == "internal page"

    def test_extract_links_with_anchors(self):
        xhtml = '<p><a href="https://example.com#section1">Link with anchor</a></p>'
        confluence_base = "https://example.atlassian.net/wiki"

        links = extract_links_from_storage_with_classification(
            xhtml, confluence_base
        )

        assert len(links) == 1
        assert links[0].anchor == "section1"
        assert links[0].raw_url == "https://example.com#section1"

    def test_extract_empty_content(self):
        links = extract_links_from_storage_with_classification(
            "", "https://example.atlassian.net/wiki"
        )
        assert links == []

        links = extract_links_from_storage_with_classification(
            None, "https://example.atlassian.net/wiki"
        )
        assert links == []


class TestExtractLinksFromAdf:
    """Test link extraction from ADF format."""

    def test_extract_adf_links(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Visit ",
                        },
                        {
                            "type": "text",
                            "text": "Example",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {"href": "https://example.com"},
                                }
                            ],
                        },
                        {
                            "type": "text",
                            "text": " and ",
                        },
                        {
                            "type": "text",
                            "text": "internal",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {
                                        "href": "/spaces/DEV/pages/456/Internal"
                                    },
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        confluence_base = "https://example.atlassian.net/wiki"

        links = extract_links_from_adf_with_classification(
            adf, confluence_base
        )

        assert len(links) == 2

        external_link = next(
            link for link in links if link.target_type == "external"
        )
        assert external_link.raw_url == "https://example.com"
        assert external_link.text == "Example"

        internal_link = next(
            link for link in links if link.target_type == "confluence"
        )
        assert internal_link.raw_url == "/spaces/DEV/pages/456/Internal"
        assert internal_link.target_page_id == "456"
        assert internal_link.text == "internal"

    def test_extract_adf_empty_content(self):
        links = extract_links_from_adf_with_classification(
            {}, "https://example.atlassian.net/wiki"
        )
        assert links == []

        links = extract_links_from_adf_with_classification(
            None, "https://example.atlassian.net/wiki"
        )
        assert links == []
