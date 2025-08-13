from typing import Dict, Iterable, Optional, List, Any
import httpx
from httpx import BasicAuth
from tenacity import retry, wait_exponential, stop_after_attempt
from ..core.config import SETTINGS
from ..core.logging import log

V2_PREFIX = "/wiki/api/v2"  # Confluence Cloud API path


class ConfluenceClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        token: Optional[str] = None,
    ):
        # For Confluence Cloud API, use the base domain
        base = (base_url or SETTINGS.CONFLUENCE_BASE_URL).rstrip("/")
        if base.endswith("/wiki"):
            # Use base domain for API calls
            api_base = base.replace("/wiki", "")
        else:
            api_base = base
        self.base_url = base  # Keep original for web UI links
        self._client = httpx.Client(
            base_url=api_base,  # API calls go to domain root
            timeout=30.0,
            auth=BasicAuth(
                email or SETTINGS.CONFLUENCE_EMAIL or "",
                token or SETTINGS.CONFLUENCE_API_TOKEN or "",
            ),
            headers={"Accept": "application/json"},
        )

    # -------- Helper methods --------

    def _paginate(self, url: str, params: Dict[str, Any]) -> Iterable[Dict]:
        """
        Helper for cursor pagination. Follows _links.next or Link header.
        """
        current_url = url
        while current_url:
            # Only use params on first request, subsequent have cursor
            request_params = params if "cursor=" not in current_url else None
            r = self._client.get(current_url, params=request_params)
            r.raise_for_status()
            data = r.json()

            # Yield all results from this page
            for item in data.get("results", []):
                yield item

            # Get next URL from _links.next or Link header
            current_url = data.get("_links", {}).get("next")
            if not current_url:
                # Try Link header as fallback
                link_header = r.headers.get("Link", "")
                if 'rel="next"' in link_header:
                    # Parse Link header
                    for link in link_header.split(","):
                        if 'rel="next"' in link:
                            current_url = link.split(";")[0].strip().strip("<>")
                            break

    # -------- v2 endpoints (cursor pagination) --------

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_spaces(
        self, keys: Optional[List[str]] = None, limit: int = 100
    ) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/spaces?keys=KEY1,KEY2&limit=100
        Yields space objects; follow Link/_links.next for pagination.
        """
        log.info("confluence.get_spaces.start", keys=keys, limit=limit)
        count = 0
        params: Dict[str, Any] = {"limit": limit}
        if keys:
            params["keys"] = ",".join(keys)

        for item in self._paginate(f"{V2_PREFIX}/spaces", params):
            yield item
            count += 1

        log.info("confluence.get_spaces.done", count=count)

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_pages(
        self,
        space_id: Optional[str] = None,
        body_format: Optional[str] = None,
        limit: int = 100,
    ) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/pages?space-id=<id>&body-format=storage|..&limit=100
        """
        log.info(
            "confluence.get_pages.start",
            space_id=space_id,
            body_format=body_format,
            limit=limit,
        )
        count = 0
        params: Dict[str, Any] = {"limit": limit}
        if space_id:
            params["space-id"] = space_id
        params["body-format"] = body_format or SETTINGS.CONFLUENCE_BODY_FORMAT

        for item in self._paginate(f"{V2_PREFIX}/pages", params):
            yield item
            count += 1

        log.info("confluence.get_pages.done", space_id=space_id, count=count)

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_page_by_id(self, page_id: str, body_format: Optional[str] = None) -> Dict:
        """
        GET /wiki/api/v2/pages/{id}?body-format=...
        """
        params: Dict[str, Any] = {
            "body-format": (body_format or SETTINGS.CONFLUENCE_BODY_FORMAT)
        }
        r = self._client.get(f"{V2_PREFIX}/pages/{page_id}", params=params)
        r.raise_for_status()
        return r.json()

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_attachments_for_page(
        self, page_id: str, limit: int = 100
    ) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/pages/{id}/attachments?limit=...
        """
        count = 0
        params: Dict[str, Any] = {"limit": limit}

        for item in self._paginate(f"{V2_PREFIX}/pages/{page_id}/attachments", params):
            yield item
            count += 1

        log.debug("confluence.get_attachments.done", page_id=page_id, count=count)

    # -------- v1 CQL search (until v2 offers equivalent) --------

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def search_cql(
        self,
        cql: str,
        start: int = 0,
        limit: int = 50,
        expand: Optional[str] = None,
    ) -> Dict:
        """
        GET /wiki/rest/api/content/search?cql=...&start=...&limit=...
        Note: server-side caps may apply when expanding bodies.
        """
        url = "/rest/api/content/search"
        params: Dict[str, Any] = {
            "cql": cql,
            "start": start,
            "limit": limit,
        }
        if expand:
            params["expand"] = expand
        r = self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()
