from pathlib import Path
from datetime import datetime, timezone
import json
import csv
import re
from typing import Dict, List, Optional, Tuple, Set, Any
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


def _detect_body_repr(obj: dict) -> str:
    body = obj.get("body") or {}
    if "storage" in body:
        return "storage"
    if "atlas_doc_format" in body:
        return "adf"
    return "unknown"


def _extract_body_storage(obj: dict) -> str | None:
    body = obj.get("body") or {}
    storage = body.get("storage") or {}
    val = storage.get("value")
    return val if isinstance(val, str) else None


def _extract_body_adf(obj: dict) -> dict | None:
    body = obj.get("body") or {}
    adf = body.get("atlas_doc_format") or {}
    val = adf.get("value")
    # v2 may return already-parsed JSON or a stringified JSON; handle both
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            import json

            return json.loads(val)
        except Exception:
            return None
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
    site_base: str,
    space_key_by_id: Dict[str, str],
    obj: Dict,
    client: Optional[ConfluenceClient] = None,
    space_key_unknown_count: Optional[Dict[str, int]] = None,
) -> Page:
    version = obj.get("version") or {}
    space_id = (
        str(obj.get("spaceId")) if obj.get("spaceId") is not None else None
    )
    page_url = _page_url(site_base, obj)

    # Resolve space_key using the new logic
    space_key: Optional[str]
    if space_id and client and space_key_unknown_count is not None:
        space_key = _resolve_space_key(
            client,
            space_key_by_id,
            space_id,
            page_url,
            space_key_unknown_count,
        )
    else:
        # Fallback to old logic for backward compatibility
        space_key = space_key_by_id.get(space_id) if space_id else None

    page = Page(
        id=str(obj.get("id")),
        title=obj.get("title") or "",
        space_id=space_id,
        space_key=space_key,
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
        url=page_url,
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


def _resolve_space_key(
    client: ConfluenceClient,
    space_key_cache: Dict[str, str],
    space_id: Optional[str],
    page_url: Optional[str],
    space_key_unknown_count: Dict[str, int],
) -> str:
    """
    Resolve space_key for a page using memoized cache, API lookup, URL fallback.
    Returns "__unknown__" as last resort and increments counter.
    """
    if not space_id:
        space_key_unknown_count["__missing_space_id__"] = (
            space_key_unknown_count.get("__missing_space_id__", 0) + 1
        )
        return "__unknown__"

    # Check cache first
    if space_id in space_key_cache:
        return space_key_cache[space_id]

    # Try API lookup
    try:
        # Add a method to ConfluenceClient to get space by ID
        r = client._client.get(f"/api/v2/spaces/{space_id}")
        if r.status_code == 200:
            space_data = r.json()
            space_key = space_data.get("key")
            if space_key:
                space_key_cache[space_id] = space_key
                return space_key
    except Exception as e:
        log.debug(
            "space_key_api_lookup_failed", space_id=space_id, error=str(e)
        )

    # Fallback to URL parsing
    if page_url:
        match = re.search(r"/spaces/([A-Z0-9]+)/pages/", page_url)
        if match:
            space_key = match.group(1)
            space_key_cache[space_id] = space_key
            log.debug(
                "space_key_from_url",
                space_id=space_id,
                space_key=space_key,
                url=page_url,
            )
            return space_key

    # Last resort
    space_key_unknown_count[space_id] = (
        space_key_unknown_count.get(space_id, 0) + 1
    )
    # Log warning once per space_id
    if space_key_unknown_count[space_id] == 1:
        log.warning(
            "space_key_resolution_failed", space_id=space_id, url=page_url
        )

    return "__unknown__"


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
    auto_since: bool = False,
    body_format: str = "storage",
    max_pages: Optional[int] = None,
    progress: bool = False,
    progress_every: int = 1,
    run_id: Optional[str] = None,
) -> Dict:
    """
    Fetch pages via v2 (bodies + attachments). If since is provided, prefilter ids with v1 CQL.
    Write one Page per line to confluence.ndjson and emit metrics/manifest.
    Enhanced with progress logging, sidecars, auto-since, and seen IDs tracking.
    """
    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)
    ndjson_path = outdir_path / "confluence.ndjson"
    metrics_path = outdir_path / "metrics.json"
    manifest_path = outdir_path / "manifest.json"

    # Sidecar files
    pages_csv_path = outdir_path / "pages.csv"
    attachments_csv_path = outdir_path / "attachments.csv"
    summary_json_path = outdir_path / "summary.json"

    # Progress checkpoint file
    progress_json_path = outdir_path / "progress.json"
    final_summary_path = outdir_path / "final_summary.txt"

    started_at = datetime.now(timezone.utc)

    client = ConfluenceClient()
    site_base = client.site_base

    # Import progress system
    from ....core.progress import get_progress

    progress_renderer = get_progress()

    # Resolve spaces
    space_id_list, space_key_by_id = _resolve_space_map(
        client, space_keys, space_ids
    )
    num_spaces = len(space_id_list) if (space_id_list or space_keys) else 0

    # Show spaces table if we have space info
    if space_id_list:
        spaces_info = []
        for space_id in space_id_list:
            try:
                # Get space details for the table
                r = client._client.get(f"/api/v2/spaces/{space_id}")
                if r.status_code == 200:
                    space_data = r.json()
                    spaces_info.append(
                        {
                            "id": space_id,
                            "key": space_data.get("key", ""),
                            "name": space_data.get("name", ""),
                        }
                    )
            except Exception:
                # Fallback if API call fails
                spaces_info.append(
                    {
                        "id": space_id,
                        "key": space_key_by_id.get(space_id, ""),
                        "name": "",
                    }
                )
        progress_renderer.spaces_table(spaces_info)

    # Check for previous progress checkpoint
    if auto_since and progress_json_path.exists():
        try:
            with open(progress_json_path) as f:
                progress_data = json.load(f)
                last_page_id = progress_data.get("last_page_id", "")
                last_timestamp = progress_data.get("timestamp", "")
                if last_page_id and last_timestamp:
                    progress_renderer.resume_indicator(
                        last_page_id, last_timestamp
                    )
        except Exception as e:
            log.warning(
                "ingest.confluence.progress_resume.failed",
                error=str(e),
            )

    # Handle auto-since
    effective_since = since
    if auto_since and (space_keys or space_ids):
        from pathlib import Path as StatePath

        state_base = StatePath("state/confluence")
        # Use first space for auto-since (could be enhanced to handle multiple)
        first_space_key = (
            space_keys[0]
            if space_keys
            else list(space_key_by_id.values())[0]
            if space_key_by_id
            else None
        )
        if first_space_key:
            state_file = state_base / f"{first_space_key}_state.json"
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        state_data = json.load(f)
                        if "last_highwater" in state_data:
                            effective_since = datetime.fromisoformat(
                                state_data["last_highwater"].replace(
                                    "Z", "+00:00"
                                )
                            )
                            log.info(
                                "ingest.confluence.auto_since",
                                space=first_space_key,
                                since=_iso(effective_since),
                            )
                except Exception as e:
                    log.warning(
                        "ingest.confluence.auto_since.failed",
                        space=first_space_key,
                        error=str(e),
                    )
            else:
                log.warning(
                    "ingest.confluence.auto_since.missing_state",
                    space=first_space_key,
                    state_file=str(state_file),
                )

    # Determine candidate page IDs if since provided
    candidate_ids: Optional[List[str]] = None
    if effective_since:
        cql = _cql_for_since(
            space_keys or list(space_key_by_id.values()), effective_since
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

    # Initialize tracking data
    written_pages = 0
    written_attachments = 0
    seen_page_ids: Dict[str, Set[str]] = {}  # space_key -> set of page IDs
    pages_data = []  # For CSV export
    attachments_data = []  # For CSV export
    space_stats: Dict[str, Dict] = {}  # space_key -> stats
    last_highwater: Optional[datetime] = None
    space_key_unknown_count: Dict[
        str, int
    ] = {}  # Track failed space_key resolutions

    # Open CSV writers
    with (
        ndjson_path.open("w", encoding="utf-8") as out,
        pages_csv_path.open(
            "w", newline="", encoding="utf-8"
        ) as pages_csv_file,
        attachments_csv_path.open(
            "w", newline="", encoding="utf-8"
        ) as att_csv_file,
    ):
        pages_csv = csv.DictWriter(
            pages_csv_file,
            fieldnames=[
                "space_key",
                "page_id",
                "title",
                "version",
                "updated_at",
                "attachments_count",
                "url",
            ],
        )
        pages_csv.writeheader()

        attachments_csv = csv.DictWriter(
            att_csv_file,
            fieldnames=[
                "page_id",
                "filename",
                "media_type",
                "file_size",
                "download_url",
            ],
        )
        attachments_csv.writeheader()

        def write_page_obj(p: Page, obj: Dict):
            nonlocal written_pages, written_attachments, last_highwater
            page_dict = p.model_dump(mode="json")

            # Add new body representation fields
            repr_ = _detect_body_repr(obj)
            page_dict["body_repr"] = repr_
            if repr_ == "storage":
                page_dict["body_storage"] = _extract_body_storage(obj)
            elif repr_ == "adf":
                page_dict["body_adf"] = _extract_body_adf(obj)

            # Write NDJSON
            out.write(
                json.dumps(page_dict, ensure_ascii=False, sort_keys=True)
                + "\n"
            )

            # Track seen IDs
            space_key = p.space_key or "__unknown__"
            if space_key not in seen_page_ids:
                seen_page_ids[space_key] = set()
            seen_page_ids[space_key].add(p.id)

            # Track stats
            if space_key not in space_stats:
                space_stats[space_key] = {
                    "pages": 0,
                    "attachments": 0,
                    "empty_bodies": 0,
                    "total_chars": 0,
                }
            space_stats[space_key]["pages"] += 1
            space_stats[space_key]["attachments"] += len(p.attachments)

            body_content = p.body_html or ""
            if not body_content.strip():
                space_stats[space_key]["empty_bodies"] += 1
            space_stats[space_key]["total_chars"] += len(body_content)

            # Track highwater mark
            if p.updated_at:
                if last_highwater is None or p.updated_at > last_highwater:
                    last_highwater = p.updated_at

            # CSV data
            pages_data.append(
                {
                    "space_key": space_key,
                    "page_id": p.id,
                    "title": p.title,
                    "version": str(p.version) if p.version else "",
                    "updated_at": _iso(p.updated_at) if p.updated_at else "",
                    "attachments_count": len(p.attachments),
                    "url": p.url or "",
                }
            )

            for att in p.attachments:
                attachments_data.append(
                    {
                        "page_id": p.id,
                        "filename": att.filename or "",
                        "media_type": att.media_type or "",
                        "file_size": (
                            str(att.file_size) if att.file_size else ""
                        ),
                        "download_url": att.download_url or "",
                    }
                )

            # Structured logging
            log.info(
                "confluence.page",
                space_key=space_key,
                space_id=p.space_id,
                page_id=p.id,
                title=p.title,
                version=p.version,
                updated_at=_iso(p.updated_at) if p.updated_at else None,
                url=p.url,
                body_repr=repr_,
                attachments_count=len(p.attachments),
            )

            if p.attachments:
                filenames = [
                    att.filename for att in p.attachments if att.filename
                ]
                log.info(
                    "confluence.attachments",
                    page_id=p.id,
                    count=len(p.attachments),
                    filenames=filenames,
                )

            # Progress output via renderer
            progress_renderer.progress_update(
                space_key=space_key,
                page_id=p.id,
                title=p.title,
                attachments=len(p.attachments),
                updated_at=_iso(p.updated_at) if p.updated_at else None,
                throttle_every=progress_every,
            )

            written_pages += 1
            written_attachments += len(p.attachments)

            # Write progress checkpoint every progress_every pages
            if written_pages % progress_every == 0:
                checkpoint_data = {
                    "last_page_id": p.id,
                    "pages_processed": written_pages,
                    "attachments_processed": written_attachments,
                    "timestamp": _iso(datetime.now(timezone.utc)),
                    "progress_checkpoints": written_pages // progress_every,
                }
                try:
                    with open(progress_json_path, "w") as f:
                        json.dump(checkpoint_data, f, indent=2, sort_keys=True)
                except Exception as e:
                    log.warning(
                        "ingest.confluence.checkpoint_write.failed",
                        error=str(e),
                    )

        if candidate_ids is not None:
            for pid in candidate_ids:
                obj = client.get_page_by_id(pid, body_format=body_format)
                page = _map_page(
                    site_base,
                    space_key_by_id,
                    obj,
                    client,
                    space_key_unknown_count,
                )
                # attachments
                for att in client.get_attachments_for_page(page.id):
                    page.attachments.append(_map_attachment(site_base, att))
                write_page_obj(page, obj)
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
                    page = _map_page(
                        site_base,
                        space_key_by_id,
                        obj,
                        client,
                        space_key_unknown_count,
                    )
                    for att in client.get_attachments_for_page(page.id):
                        page.attachments.append(
                            _map_attachment(site_base, att)
                        )
                    write_page_obj(page, obj)
                    if max_pages and written_pages >= max_pages:
                        break
                if max_pages and written_pages >= max_pages:
                    break

    # Write deterministic CSV data
    pages_data.sort(key=lambda x: (x["space_key"], x["page_id"]))
    attachments_data.sort(key=lambda x: (x["page_id"], x["filename"]))

    with pages_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "space_key",
                "page_id",
                "title",
                "version",
                "updated_at",
                "attachments_count",
                "url",
            ],
        )
        writer.writeheader()
        writer.writerows(pages_data)

    with attachments_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "page_id",
                "filename",
                "media_type",
                "file_size",
                "download_url",
            ],
        )
        writer.writeheader()
        writer.writerows(attachments_data)

    # Write seen page IDs per space
    for space_key, page_ids in seen_page_ids.items():
        seen_ids_file = outdir_path / f"{space_key}_seen_page_ids.json"
        with open(seen_ids_file, "w") as f:
            json.dump(sorted(list(page_ids)), f, indent=2, sort_keys=True)

    completed_at = datetime.now(timezone.utc)
    elapsed_seconds = (completed_at - started_at).total_seconds()

    # Show finish banner
    progress_renderer.finish_banner(
        run_id=run_id or "unknown",
        space_stats=space_stats,
        elapsed=elapsed_seconds,
    )

    # Create summary.json with per-space stats
    total_unknown_count = sum(space_key_unknown_count.values())
    summary_data: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "total_pages": written_pages,
        "total_attachments": written_attachments,
        "space_key_unknown_count": total_unknown_count,
        "progress_checkpoints": written_pages // progress_every
        if progress_every > 0
        else 0,
        "spaces": {},
    }

    # Add warnings if needed
    if total_unknown_count > 0:
        summary_data["warnings"] = ["space_key_unknown_detected"]

    for space_key, stats in space_stats.items():
        avg_chars = (
            stats["total_chars"] / stats["pages"] if stats["pages"] > 0 else 0
        )
        summary_data["spaces"][space_key] = {
            "pages": stats["pages"],
            "attachments": stats["attachments"],
            "empty_bodies": stats["empty_bodies"],
            "avg_chars": round(avg_chars, 2),
        }

    with open(summary_json_path, "w") as f:
        json.dump(summary_data, f, indent=2, sort_keys=True)

    # Write final one-line summary for humans
    final_summary = progress_renderer.one_line_summary(
        run_id=run_id or "unknown",
        pages=written_pages,
        attachments=written_attachments,
        elapsed=elapsed_seconds,
    )
    final_summary_path.write_text(final_summary + "\n", encoding="utf-8")

    # Print console warning if space_key resolution failed
    if total_unknown_count > 0:
        print(
            f"⚠️  Warning: Failed to resolve space_key for {total_unknown_count} pages. Check summary.json for details."
        )

    # Update state files with auto-since
    if auto_since and last_highwater and (space_keys or space_ids):
        from pathlib import Path as StatePath

        state_base = StatePath("state/confluence")
        state_base.mkdir(parents=True, exist_ok=True)

        spaces_to_update = space_keys or list(space_key_by_id.values())
        for space_key in spaces_to_update:
            state_file = state_base / f"{space_key}_state.json"
            state_data = {
                "last_highwater": _iso(last_highwater),
                "last_run_id": run_id,
                "updated_at": _iso(completed_at),
            }
            with open(state_file, "w") as f:
                json.dump(state_data, f, indent=2, sort_keys=True)
            log.info(
                "ingest.confluence.state_updated",
                space=space_key,
                last_highwater=_iso(last_highwater),
                run_id=run_id,
            )

    # metrics + manifest
    metrics = {
        "spaces": num_spaces,
        "pages": written_pages,
        "attachments": written_attachments,
        "since": _iso(effective_since),
        "body_format": body_format,
        "space_key_unknown_count": total_unknown_count,
    }
    metrics_path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8"
    )
    manifest = {
        "phase": "ingest",
        "artifact": "confluence.ndjson",
        "completed_at": _iso(completed_at),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    log.info("ingest.confluence.done", **metrics, out=str(ndjson_path))
    return metrics


def ingest_confluence_minimal(outdir: str) -> None:
    """
    Minimal placeholder that writes an empty NDJSON to prove pathing works.
    """
    p = Path(outdir) / "confluence.ndjson"
    p.write_text("", encoding="utf-8")
    log.info("ingest.confluence.wrote", file=str(p))
