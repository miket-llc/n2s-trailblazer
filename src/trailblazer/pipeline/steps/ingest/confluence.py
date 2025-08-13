from pathlib import Path
from datetime import datetime
import json
from typing import Dict, List, Optional, Tuple
from ....adapters.confluence_api import ConfluenceClient
from ....core.models import Page, Attachment
from ....core.logging import log


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def _body_html_from_v2(page_obj: Dict) -> Optional[str]:
    # Defensive parsing: v2 may nest body by requested format
    body = page_obj.get("body") or {}
    # Try storage first
    storage = body.get("storage") or {}
    if storage.get("value"):
        return storage["value"]
    # Fallback: atlas_doc_format may be under "atlas_doc_format" as rendered HTML or JSON; leave None if not rendered
    adf = body.get("atlas_doc_format") or {}
    if isinstance(adf.get("value"), str):
        return adf["value"]
    return None


def _page_url(site_base: str, page_obj: Dict) -> Optional[str]:
    webui = (page_obj.get("_links") or {}).get("webui")
    if not webui:
        return None
    from urllib.parse import urljoin

    return urljoin(site_base + "/", webui.lstrip("/"))


def _map_attachment(site_base: str, att: Dict) -> Attachment:
    dl = (att.get("_links") or {}).get("download") or att.get("downloadLink")
    from urllib.parse import urljoin

    return Attachment(
        id=str(att.get("id")),
        filename=att.get("title") or att.get("filename"),
        media_type=att.get("mediaType") or att.get("type"),
        file_size=att.get("fileSize") or att.get("size"),
        download_url=urljoin(site_base + "/", dl.lstrip("/")) if dl else None,
    )


def _map_page(
    site_base: str, space_key_by_id: Dict[str, str], obj: Dict
) -> Page:
    version = obj.get("version") or {}
    page = Page(
        id=str(obj.get("id")),
        title=obj.get("title") or "",
        space_id=(
            str(obj.get("spaceId")) if obj.get("spaceId") is not None else None
        ),
        space_key=(
            space_key_by_id.get(str(obj.get("spaceId")))
            if obj.get("spaceId")
            else None
        ),
        version=version.get("number"),
        updated_at=(
            datetime.fromisoformat(version["createdAt"].replace("Z", "+00:00"))
            if version.get("createdAt")
            else None
        ),
        created_at=(
            datetime.fromisoformat(obj["createdAt"].replace("Z", "+00:00"))
            if obj.get("createdAt")
            else None
        ),
        body_html=_body_html_from_v2(obj),
        url=_page_url(site_base, obj),
        attachments=[],
        metadata={"raw_links": obj.get("_links", {})},
    )
    return page


def _resolve_space_map(
    client: ConfluenceClient,
    space_keys: Optional[List[str]],
    space_ids: Optional[List[str]],
) -> Tuple[List[str], Dict[str, str]]:
    space_id_list: List[str] = []
    space_key_by_id: Dict[str, str] = {}

    # Resolve keys -> ids via v2
    if space_keys:
        for s in client.get_spaces(keys=space_keys):
            sid = str(s.get("id"))
            skey = s.get("key")
            if sid:
                space_id_list.append(sid)
                if skey:
                    space_key_by_id[sid] = skey

    # Include any provided ids explicitly
    if space_ids:
        for sid in space_ids:
            if sid not in space_id_list:
                space_id_list.append(sid)

    return space_id_list, space_key_by_id


def _cql_for_since(space_keys: List[str], since: datetime) -> str:
    # lastModified uses Confluence time fields; ensure Z
    iso = _iso(since) or ""
    if space_keys:
        keys = " OR ".join([f'space="{k}"' for k in space_keys])
        return f'type=page AND lastModified > "{iso}" AND ({keys}) ORDER BY lastmodified ASC'
    return f'type=page AND lastModified > "{iso}" ORDER BY lastmodified ASC'


def ingest_confluence(
    outdir: str,
    space_keys: Optional[List[str]] = None,
    space_ids: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    body_format: str = "storage",
    max_pages: Optional[int] = None,
) -> Dict:
    """
    Fetch pages via v2 (bodies + attachments). If since is provided, prefilter ids with v1 CQL.
    Write one Page per line to confluence.ndjson and emit metrics/manifest.
    """
    Path(outdir).mkdir(parents=True, exist_ok=True)
    ndjson_path = Path(outdir) / "confluence.ndjson"
    metrics_path = Path(outdir) / "metrics.json"
    manifest_path = Path(outdir) / "manifest.json"

    client = ConfluenceClient()
    site_base = client.site_base

    # Resolve spaces
    space_id_list, space_key_by_id = _resolve_space_map(
        client, space_keys, space_ids
    )
    num_spaces = len(space_id_list) if (space_id_list or space_keys) else 0

    # Determine candidate page IDs if since provided
    candidate_ids: Optional[List[str]] = None
    if since:
        cql = _cql_for_since(
            space_keys or list(space_key_by_id.values()), since
        )
        start, ids = 0, []
        while True:
            data = client.search_cql(cql=cql, start=start, limit=50)
            results = data.get("results", [])
            if not results:
                break
            ids.extend(
                [str(r.get("id")) for r in results if r.get("id") is not None]
            )
            if len(results) < 50:
                break
            start += 50
        candidate_ids = ids

    # Iterate pages
    written_pages = 0
    written_attachments = 0

    with ndjson_path.open("w", encoding="utf-8") as out:

        def write_page_obj(p: Page):
            nonlocal written_pages, written_attachments
            d = p.model_dump()
            out.write(json.dumps(d, ensure_ascii=False) + "\n")
            written_pages += 1
            written_attachments += len(p.attachments)

        if candidate_ids is not None:
            for pid in candidate_ids:
                obj = client.get_page_by_id(pid, body_format=body_format)
                page = _map_page(site_base, space_key_by_id, obj)
                # attachments
                for att in client.get_attachments_for_page(page.id):
                    page.attachments.append(_map_attachment(site_base, att))
                write_page_obj(page)
                if max_pages and written_pages >= max_pages:
                    break
        else:
            # full space scans
            if space_id_list:
                target_spaces: List[Optional[str]] = list(space_id_list)
            else:
                target_spaces = [None]  # None => all pages
            for sid in target_spaces:
                for obj in client.get_pages(
                    space_id=sid, body_format=body_format
                ):
                    page = _map_page(site_base, space_key_by_id, obj)
                    for att in client.get_attachments_for_page(page.id):
                        page.attachments.append(
                            _map_attachment(site_base, att)
                        )
                    write_page_obj(page)
                    if max_pages and written_pages >= max_pages:
                        break
                if max_pages and written_pages >= max_pages:
                    break

    # metrics + manifest
    metrics = {
        "spaces": num_spaces,
        "pages": written_pages,
        "attachments": written_attachments,
        "since": _iso(since),
        "body_format": body_format,
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    manifest = {
        "phase": "ingest",
        "artifact": "confluence.ndjson",
        "completed_at": _iso(datetime.utcnow()),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log.info("ingest.confluence.done", **metrics, out=str(ndjson_path))
    return metrics


def ingest_confluence_minimal(outdir: str) -> None:
    """
    Minimal placeholder that writes an empty NDJSON to prove pathing works.
    """
    p = Path(outdir) / "confluence.ndjson"
    p.write_text("", encoding="utf-8")
    log.info("ingest.confluence.wrote", file=str(p))
