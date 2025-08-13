from typing import Dict, Iterable, Optional, List, Any
import httpx
from httpx import BasicAuth
from tenacity import retry, wait_exponential, stop_after_attempt
from ..core.config import SETTINGS

V2_PREFIX = "/api/v2"  # appended to CONFLUENCE_BASE_URL path (which already includes /wiki)


class ConfluenceClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        token: Optional[str] = None,
    ):
        base = (base_url or SETTINGS.CONFLUENCE_BASE_URL).rstrip("/")
        if not base.endswith("/wiki"):
            # normalize to include /wiki for Cloud
            base = base + "/wiki"
        self.base_url = base  # e.g., https://ellucian.atlassian.net/wiki
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=30.0,
            auth=BasicAuth(
                email or SETTINGS.CONFLUENCE_EMAIL or "",
                token or SETTINGS.CONFLUENCE_API_TOKEN or "",
            ),
            headers={"Accept": "application/json"},
        )

    # -------- v2 endpoints (cursor pagination) --------

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_spaces(self, keys: Optional[List[str]] = None, limit: int = 100) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/spaces?keys=KEY1,KEY2&limit=100
        Yields space objects; follow Link/_links.next for pagination.
        """
        params: Dict[str, Any] = {"limit": limit}
        if keys:
            params["keys"] = ",".join(keys)
        url = f"{V2_PREFIX}/spaces"
        while url:
            r = self._client.get(url, params=params if "cursor=" not in url else None)
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                yield item
            url = data.get("_links", {}).get("next")

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_pages(
        self, space_id: Optional[str] = None, body_format: Optional[str] = None, limit: int = 100
    ) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/pages?space-id=<id>&body-format=storage|atlas_doc_format&limit=100
        """
        params: Dict[str, Any] = {"limit": limit}
        if space_id:
            params["space-id"] = space_id
        params["body-format"] = body_format or SETTINGS.CONFLUENCE_BODY_FORMAT
        url = f"{V2_PREFIX}/pages"
        while url:
            r = self._client.get(url, params=params if "cursor=" not in url else None)
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                yield item
            url = data.get("_links", {}).get("next")

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_page_by_id(self, page_id: str, body_format: Optional[str] = None) -> Dict:
        """
        GET /wiki/api/v2/pages/{id}?body-format=...
        """
        params: Dict[str, Any] = {"body-format": (body_format or SETTINGS.CONFLUENCE_BODY_FORMAT)}
        r = self._client.get(f"{V2_PREFIX}/pages/{page_id}", params=params)
        r.raise_for_status()
        return r.json()

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_attachments_for_page(self, page_id: str, limit: int = 100) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/pages/{id}/attachments?limit=...
        """
        params: Dict[str, Any] = {"limit": limit}
        url = f"{V2_PREFIX}/pages/{page_id}/attachments"
        while url:
            r = self._client.get(url, params=params if "cursor=" not in url else None)
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                yield item
            url = data.get("_links", {}).get("next")

    # -------- v1 CQL search (until v2 offers equivalent) --------

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def search_cql(
        self, cql: str, start: int = 0, limit: int = 50, expand: Optional[str] = None
    ) -> Dict:
        """
        GET /wiki/rest/api/content/search?cql=...&start=...&limit=...
        Note: server-side caps may apply when expanding bodies.
        """
        url = "/rest/api/content/search"
        params: Dict[str, Any] = {"cql": cql, "start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        r = self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()
