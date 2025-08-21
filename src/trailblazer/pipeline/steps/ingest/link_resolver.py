"""Link resolution helpers for traceability."""

import re
from urllib.parse import parse_qs, urlparse, urlunparse


class LinkInfo:
    """Information about a parsed link."""

    def __init__(
        self,
        raw_url: str,
        normalized_url: str,
        anchor: str | None = None,
        text: str | None = None,
        target_type: str = "external",
        target_page_id: str | None = None,
    ):
        self.raw_url = raw_url
        self.normalized_url = normalized_url
        self.anchor = anchor
        self.text = text
        self.target_type = target_type  # confluence|external|attachment
        self.target_page_id = target_page_id


def normalize_url(url: str) -> str:
    """
    Normalize URL by removing tracking parameters while preserving anchors.

    Args:
        url: Raw URL to normalize

    Returns:
        Normalized URL with tracking params removed
    """
    if not url:
        return url

    parsed = urlparse(url)

    # Remove common tracking parameters
    tracking_params = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "_gl",
    }

    if parsed.query:
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        # Remove tracking params
        filtered_params = {k: v for k, v in query_params.items() if k not in tracking_params}

        # Rebuild query string
        new_query = "&".join(f"{k}={v[0]}" if v and v[0] else k for k, v in filtered_params.items())

        # Reconstruct URL
        normalized = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )
        return normalized

    return url


def classify_link_type(url: str, confluence_base_url: str) -> str:
    """
    Classify a link as confluence, external, or attachment.

    Args:
        url: URL to classify
        confluence_base_url: Base URL of the Confluence instance

    Returns:
        Link type: "confluence", "external", or "attachment"
    """
    if not url:
        return "external"

    # Handle relative URLs
    if url.startswith("/"):
        if "/download/attachments/" in url:
            return "attachment"
        elif "/spaces/" in url or "/pages/" in url:
            return "confluence"
        return "external"

    # Handle absolute URLs
    parsed = urlparse(url)
    confluence_parsed = urlparse(confluence_base_url)

    # Same domain check
    if parsed.netloc.lower() != confluence_parsed.netloc.lower():
        return "external"

    # Check path patterns
    path = parsed.path.lower()
    if "/download/attachments/" in path:
        return "attachment"
    elif "/spaces/" in path or "/pages/" in path or "/wiki/" in path:
        return "confluence"

    return "external"


def extract_confluence_page_id(url: str) -> str | None:
    """
    Extract page ID from a Confluence URL.

    Handles patterns like:
    - /spaces/SPACE/pages/123456/Page+Title
    - /wiki/spaces/SPACE/pages/123456/Page+Title
    - /pages/viewpage.action?pageId=123456

    Args:
        url: Confluence URL to parse

    Returns:
        Page ID if found, None otherwise
    """
    if not url:
        return None

    # Pattern 1: /spaces/SPACE/pages/ID/title or /wiki/spaces/SPACE/pages/ID/title
    match = re.search(r"/spaces/[^/]+/pages/(\d+)", url)
    if match:
        return match.group(1)

    # Pattern 2: viewpage.action?pageId=ID
    match = re.search(r"[?&]pageId=(\d+)", url)
    if match:
        return match.group(1)

    return None


def extract_links_from_storage_with_classification(xhtml: str | None, confluence_base_url: str) -> list[LinkInfo]:
    """
    Extract and classify links from Confluence Storage format.

    Args:
        xhtml: Storage format HTML content
        confluence_base_url: Base URL of Confluence instance

    Returns:
        List of LinkInfo objects with classification
    """
    if not xhtml:
        return []

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(xhtml, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        if not hasattr(a, "get"):
            continue

        raw_url = a.get("href")
        if not raw_url or not isinstance(raw_url, str):
            continue

        text = a.get_text(strip=True) if a else None
        anchor = None

        # Extract anchor from URL
        if "#" in raw_url:
            anchor = raw_url.split("#", 1)[1]

        normalized_url = normalize_url(raw_url)
        target_type = classify_link_type(raw_url, confluence_base_url)
        target_page_id = None

        if target_type == "confluence":
            target_page_id = extract_confluence_page_id(raw_url)

        links.append(
            LinkInfo(
                raw_url=raw_url,
                normalized_url=normalized_url,
                anchor=anchor,
                text=text,
                target_type=target_type,
                target_page_id=target_page_id,
            )
        )

    return links


def extract_links_from_adf_with_classification(adf: dict | None, confluence_base_url: str) -> list[LinkInfo]:
    """
    Extract and classify links from ADF format.

    Args:
        adf: ADF document structure
        confluence_base_url: Base URL of Confluence instance

    Returns:
        List of LinkInfo objects with classification
    """
    if not adf:
        return []

    links = []

    def walk(node: dict, current_text: str = ""):
        """Walk ADF tree and extract links."""
        # Extract text content for context
        if node.get("type") == "text":
            current_text = node.get("text", "")

        # Check for link marks
        marks = node.get("marks", []) or []
        for mark in marks:
            if mark.get("type") == "link":
                attrs = mark.get("attrs", {})
                raw_url = attrs.get("href")

                if raw_url:
                    anchor = None
                    if "#" in raw_url:
                        anchor = raw_url.split("#", 1)[1]

                    normalized_url = normalize_url(raw_url)
                    target_type = classify_link_type(raw_url, confluence_base_url)
                    target_page_id = None

                    if target_type == "confluence":
                        target_page_id = extract_confluence_page_id(raw_url)

                    links.append(
                        LinkInfo(
                            raw_url=raw_url,
                            normalized_url=normalized_url,
                            anchor=anchor,
                            text=current_text if current_text else None,
                            target_type=target_type,
                            target_page_id=target_page_id,
                        )
                    )

        # Recurse into content
        content = node.get("content", [])
        if isinstance(content, list):
            for child in content:
                if isinstance(child, dict):
                    walk(child, current_text)

    walk(adf)
    return links
