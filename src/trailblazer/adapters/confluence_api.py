from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin

import httpx
from httpx import BasicAuth
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.config import SETTINGS

V2_PREFIX = "/api/v2"


class ConfluenceClient:
    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        token: str | None = None,
    ):
        base = (base_url or SETTINGS.CONFLUENCE_BASE_URL or "").rstrip("/")
        if not base.endswith("/wiki"):
            base = base + "/wiki"
        self.site_base = base  # e.g. https://ellucian.atlassian.net/wiki
        self.api_base = self.site_base  # httpx base_url
        self._client = httpx.Client(
            base_url=self.api_base,
            timeout=30.0,
            auth=BasicAuth(
                email or SETTINGS.CONFLUENCE_EMAIL or "",
                token or SETTINGS.CONFLUENCE_API_TOKEN or "",
            ),
            headers={"Accept": "application/json"},
        )

    # ---------- pagination helper ----------
    def _next_link(self, resp: httpx.Response, data: dict) -> str | None:
        nxt = (data.get("_links") or {}).get("next")
        if nxt:
            # v2 returns absolute or relative; normalize
            if nxt.startswith("http"):
                return nxt
            else:
                # Handle relative URLs properly - nxt should be like "/wiki/api/v2/pages?..."
                # Don't double-add /wiki since it's already in the relative path
                base_without_wiki = self.api_base.replace("/wiki", "")
                return urljoin(base_without_wiki + "/", nxt.lstrip("/"))

        # fallback: Link header
        link = resp.headers.get("Link", "")
        # very simple parse
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                if url.startswith("http"):
                    return url
                else:
                    # Handle relative URLs properly
                    base_without_wiki = self.api_base.replace("/wiki", "")
                    return urljoin(base_without_wiki + "/", url.lstrip("/"))
        return None

    def _paginate(self, url: str, params: dict | None = None) -> Iterable[dict]:
        first = True
        while True:
            r = self._client.get(url, params=params if first else None)
            r.raise_for_status()
            data = r.json()
            yield from data.get("results", [])
            nxt = self._next_link(r, data)
            if not nxt:
                break
            url, params, first = nxt, None, False

    # ---------- v2 ----------
    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_spaces(self, keys: list[str] | None = None, limit: int = 100) -> Iterable[dict]:
        params: dict[str, Any] = {"limit": limit}
        if keys:
            params["keys"] = ",".join(keys)
        yield from self._paginate(f"{V2_PREFIX}/spaces", params)

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_pages(
        self,
        space_id: str | None = None,
        body_format: str | None = None,
        limit: int = 100,
    ) -> Iterable[dict]:
        params: dict[str, Any] = {"limit": limit}
        if space_id:
            params["space-id"] = space_id
        if body_format:
            params["body-format"] = body_format
        yield from self._paginate(f"{V2_PREFIX}/pages", params)

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_page_by_id(self, page_id: str, body_format: str | None = None) -> dict:
        params: dict[str, Any] = {}
        if body_format:
            params["body-format"] = body_format
        r = self._client.get(f"{V2_PREFIX}/pages/{page_id}", params=params)
        r.raise_for_status()
        return r.json()

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_attachments_for_page(self, page_id: str, limit: int = 100) -> Iterable[dict]:
        params: dict[str, Any] = {"limit": limit}
        yield from self._paginate(f"{V2_PREFIX}/pages/{page_id}/attachments", params)

    # ---------- v1 CQL (delta prefilter only) ----------
    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def search_cql(
        self,
        cql: str,
        start: int = 0,
        limit: int = 50,
        expand: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"cql": cql, "start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        r = self._client.get("/rest/api/content/search", params=params)
        r.raise_for_status()
        return r.json()

    # helpers
    def absolute(self, rel_or_abs: str | None) -> str | None:
        if not rel_or_abs:
            return None
        return rel_or_abs if rel_or_abs.startswith("http") else urljoin(self.site_base + "/", rel_or_abs.lstrip("/"))

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(3))
    def get_page_labels(self, page_id: str) -> list[dict]:
        """Get labels for a specific page."""
        try:
            response = self._client.get(f"{V2_PREFIX}/pages/{page_id}/labels")
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except Exception:
            # Labels are optional - don't fail the whole ingest
            return []

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(3))
    def get_page_ancestors(self, page_id: str) -> list[dict]:
        """Get ancestor hierarchy for a page."""
        try:
            response = self._client.get(f"{V2_PREFIX}/pages/{page_id}", params={"expand": "ancestors"})
            response.raise_for_status()
            data = response.json()
            return data.get("ancestors", [])
        except Exception:
            # Ancestors are optional - don't fail the whole ingest
            return []

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(3))
    def get_space_details(self, space_key: str) -> dict:
        """Get detailed space information."""
        try:
            response = self._client.get(f"{V2_PREFIX}/spaces", params={"keys": space_key})
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            return results[0] if results else {}
        except Exception:
            # Space details are optional
            return {}
