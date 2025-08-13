from ....adapters.confluence_api import ConfluenceClient
from ....core.models import Page, Attachment
from ....core.logging import log
from datetime import datetime
from pathlib import Path
import json
import time
from typing import Dict, List, Optional


def ingest_confluence(
    outdir: str,
    space_keys: Optional[List[str]] = None,
    space_ids: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    body_format: str = "storage",
    max_pages: Optional[int] = None,
) -> Dict:
    """
    Ingest pages from Confluence Cloud using v2 API.

    Args:
        outdir: Output directory for artifacts
        space_keys: List of space keys to ingest from
        space_ids: List of space IDs to ingest from
        since: Only fetch pages modified since this datetime
        body_format: Body format to request (storage or atlas_doc_format)
        max_pages: Maximum number of pages to process (for testing)

    Returns:
        Dictionary with metrics
    """
    start_time = time.time()
    log.info(
        "ingest.confluence.start",
        outdir=outdir,
        space_keys=space_keys,
        space_ids=space_ids,
        since=since.isoformat() if since else None,
        body_format=body_format,
        max_pages=max_pages,
    )

    # Ensure output directory exists
    out_path = Path(outdir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Initialize client
    client = ConfluenceClient()

    # Resolve space IDs from keys if needed
    resolved_space_ids = list(space_ids or [])
    if space_keys:
        log.info("ingest.confluence.resolving_spaces", space_keys=space_keys)
        for space in client.get_spaces(keys=space_keys):
            if space.get("key") in space_keys:
                resolved_space_ids.append(space["id"])
                log.info("ingest.confluence.resolved_space", key=space.get("key"), id=space["id"])

    if not resolved_space_ids:
        log.warning("ingest.confluence.no_spaces", space_keys=space_keys, space_ids=space_ids)
        resolved_space_ids = [None]  # Fetch from all spaces

    # Collect page IDs to process
    page_ids_to_fetch = []

    if since:
        # Use CQL search to find pages modified since timestamp
        log.info("ingest.confluence.cql_search", since=since.isoformat())
        cql_parts = ["type=page", f'lastModified > "{since.isoformat()}"']
        if resolved_space_ids and resolved_space_ids != [None]:
            # Map space IDs back to keys for CQL (CQL uses space keys)
            space_keys_for_cql = []
            for space in client.get_spaces():
                if space["id"] in resolved_space_ids:
                    space_keys_for_cql.append(space["key"])
            if space_keys_for_cql:
                cql_parts.append(f"space in ({','.join(space_keys_for_cql)})")

        cql = " AND ".join(cql_parts)
        log.info("ingest.confluence.cql_query", cql=cql)

        search_result = client.search_cql(cql, limit=1000)
        for item in search_result.get("results", []):
            page_ids_to_fetch.append(item["id"])

        log.info("ingest.confluence.cql_results", count=len(page_ids_to_fetch))
    else:
        # Iterate through pages in each space
        for space_id in resolved_space_ids:
            log.info("ingest.confluence.fetching_pages", space_id=space_id)
            for page in client.get_pages(space_id=space_id, body_format=body_format):
                page_ids_to_fetch.append(page["id"])
                # Stop early if max_pages limit reached
                if max_pages and len(page_ids_to_fetch) >= max_pages:
                    break
            if max_pages and len(page_ids_to_fetch) >= max_pages:
                break

    # Process pages and write to NDJSON
    ndjson_path = out_path / "confluence.ndjson"
    pages_processed = 0
    attachments_processed = 0
    spaces_processed = len([sid for sid in resolved_space_ids if sid is not None])

    with open(ndjson_path, "w", encoding="utf-8") as f:
        for page_id in page_ids_to_fetch:
            if max_pages and pages_processed >= max_pages:
                break

            try:
                # Fetch full page data with body
                page_data = client.get_page_by_id(page_id, body_format=body_format)

                # Build absolute URL
                webui_link = page_data.get("_links", {}).get("webui", "")
                if webui_link.startswith("/"):
                    # Relative URL, make it absolute
                    base_without_wiki = client.base_url.rstrip("/wiki")
                    page_url = base_without_wiki + webui_link
                else:
                    # Already absolute or empty
                    page_url = webui_link

                # Fetch attachments
                attachments = []
                for att_data in client.get_attachments_for_page(page_id):
                    download_link = att_data.get("downloadLink", "")
                    if download_link.startswith("/"):
                        download_url = client.base_url.rstrip("/wiki") + download_link
                    else:
                        download_url = download_link

                    attachment = Attachment(
                        id=att_data["id"],
                        filename=att_data.get("title"),
                        media_type=att_data.get("mediaType"),
                        file_size=att_data.get("fileSize"),
                        download_url=download_url,
                    )
                    attachments.append(attachment)
                    attachments_processed += 1

                # Parse version and dates
                version_info = page_data.get("version", {})
                created_at = None
                updated_at = None
                version_num = None

                if version_info:
                    version_num = version_info.get("number")
                    created_date = version_info.get("createdAt")
                    if created_date:
                        # Handle timezone info
                        if created_date.endswith("Z"):
                            created_date = created_date.replace("Z", "+00:00")
                        try:
                            updated_at = datetime.fromisoformat(created_date)
                        except ValueError:
                            log.warning(
                                "ingest.confluence.date_parse_error",
                                page_id=page_id,
                                date=created_date,
                            )

                # Get space info
                space_info = page_data.get("space", {})
                space_key = space_info.get("key")
                space_id = space_info.get("id")

                # Build Page model
                page = Page(
                    id=page_data["id"],
                    title=page_data["title"],
                    space_key=space_key,
                    space_id=space_id,
                    created_at=created_at,
                    updated_at=updated_at,
                    version=version_num,
                    body_html=(
                        page_data.get("body", {}).get("storage", {}).get("value")
                        or page_data.get("body", {}).get("atlas_doc_format", {}).get("value")
                    ),
                    url=page_url,
                    attachments=attachments,
                    metadata={
                        "body_format": body_format,
                        "status": page_data.get("status"),
                    },
                )

                # Write as NDJSON line
                f.write(page.model_dump_json() + "\n")
                pages_processed += 1

                if pages_processed % 10 == 0:
                    log.info("ingest.confluence.progress", pages=pages_processed)

            except Exception as e:
                log.error("ingest.confluence.page_error", page_id=page_id, error=str(e))
                continue

    # Calculate metrics
    end_time = time.time()
    duration = end_time - start_time

    metrics = {
        "spaces": spaces_processed,
        "pages": pages_processed,
        "attachments": attachments_processed,
        "since": since.isoformat() if since else None,
        "duration_seconds": duration,
        "body_format": body_format,
    }

    # Write metrics
    metrics_path = out_path / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    # Write manifest
    manifest = {
        "run_id": out_path.parent.name,
        "phase": "ingest",
        "step": "confluence",
        "started_at": datetime.fromtimestamp(start_time).isoformat(),
        "completed_at": datetime.fromtimestamp(end_time).isoformat(),
        "artifacts": {
            "confluence.ndjson": str(ndjson_path),
            "metrics.json": str(metrics_path),
        },
    }

    manifest_path = out_path / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    log.info("ingest.confluence.done", **metrics)
    return metrics


def ingest_confluence_minimal(outdir: str) -> None:
    """
    Minimal placeholder that writes an empty NDJSON to prove pathing works.
    """
    p = Path(outdir) / "confluence.ndjson"
    p.write_text("", encoding="utf-8")
    log.info("ingest.confluence.wrote", file=str(p))
