"""DITA ingest step.

Scans a directory tree for DITA files, parses topics and maps,
and writes graph-ready artifacts to outdir.
"""

from pathlib import Path
from datetime import datetime, timezone
import json
import hashlib
import os
import fnmatch
from typing import Dict, List, Optional, Any, Iterator
from ....adapters.dita import (
    parse_topic,
    parse_map,
    is_dita_file,
    compute_file_sha256,
    TopicDoc,
    MapDoc,
)
from ....core.logging import log


def _iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO string."""
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def _should_include_file(
    file_path: Path,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> bool:
    """Check if file should be included based on glob patterns."""
    filename = file_path.name
    rel_path = str(file_path)

    # Check exclude patterns first
    if exclude_patterns:
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(
                rel_path, pattern
            ):
                return False

    # If no include patterns specified, use defaults
    if not include_patterns:
        include_patterns = ["*.dita", "*.xml", "*.ditamap"]

    # Check include patterns
    for pattern in include_patterns:
        # Handle ** patterns by checking if pattern applies to filename or path
        if pattern.startswith("**/"):
            simple_pattern = pattern[3:]
            if fnmatch.fnmatch(filename, simple_pattern):
                return True
        elif fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(
            rel_path, pattern
        ):
            return True

    return False


def _find_dita_files(
    root_dir: Path,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> Iterator[Path]:
    """Find DITA files in directory tree."""
    if not root_dir.exists():
        log.warning("dita.scan.root_not_found", root=str(root_dir))
        return

    archive_count = 0

    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue

        # Skip archives and warn
        if file_path.suffix.lower() in [".zip", ".tar", ".gz", ".7z"]:
            archive_count += 1
            continue

        # Check include/exclude patterns
        rel_path = file_path.relative_to(root_dir)
        if not _should_include_file(
            rel_path, include_patterns, exclude_patterns
        ):
            continue

        # Check if it's actually a DITA file
        if is_dita_file(file_path):
            yield file_path

    if archive_count > 0:
        log.warning("dita.scan.archives_skipped", count=archive_count)


def _create_dita_record(
    doc: TopicDoc | MapDoc,
    file_path: Path,
    root_dir: Path,
    file_stats: os.stat_result,
    file_sha256: str,
) -> Dict[str, Any]:
    """Create canonical DITA record for NDJSON output."""
    rel_path = str(file_path.relative_to(root_dir))

    # Common fields
    record: Dict[str, Any] = {
        "source_system": "dita",
        "id": doc.id,
        "title": doc.title,
        "source_path": rel_path,
        "source_file_sha256": file_sha256,
        "body_repr": "dita",
        "labels": doc.labels,
        "created_at": _iso(
            datetime.fromtimestamp(file_stats.st_ctime, tz=timezone.utc)
        ),
        "updated_at": _iso(
            datetime.fromtimestamp(file_stats.st_mtime, tz=timezone.utc)
        ),
    }

    # Type-specific fields
    if isinstance(doc, TopicDoc):
        record.update(
            {
                "doctype": doc.doctype,
                "body_dita_xml": doc.body_xml[:10000]
                if len(doc.body_xml) > 10000
                else doc.body_xml,  # Truncate if huge
                "ancestors": [],  # Will be populated from maps
                "attachments": [ref.filename for ref in doc.images],
            }
        )
        record["attachment_count"] = len(doc.images)
        record["label_count"] = len(doc.labels)
        record["ancestor_count"] = 0  # Will be updated from hierarchy
    elif isinstance(doc, MapDoc):
        record.update(
            {
                "doctype": "map",
                "body_dita_xml": "",  # Maps don't have body content
                "ancestors": [],
                "attachments": [],
            }
        )
        record["attachment_count"] = 0
        record["label_count"] = len(doc.labels)
        record["ancestor_count"] = 0

    # Compute content hash
    content_for_hash = f"{doc.title}{json.dumps(doc.labels, sort_keys=True)}"
    if isinstance(doc, TopicDoc):
        content_for_hash += doc.body_xml
    record["content_sha256"] = hashlib.sha256(
        content_for_hash.encode()
    ).hexdigest()

    return record


def _write_media_sidecars(
    outdir: Path, topics: List[TopicDoc], topic_records: List[Dict[str, Any]]
) -> int:
    """Write media-related sidecar files."""
    media_jsonl_path = outdir / "ingest_media.jsonl"
    attachments_manifest_path = outdir / "attachments_manifest.jsonl"

    media_refs_total = 0

    with (
        open(media_jsonl_path, "w") as media_f,
        open(attachments_manifest_path, "w") as manifest_f,
    ):
        for topic in topics:
            page_id = topic.id

            # Write media references
            for media_ref in topic.images:
                media_entry = {
                    "page_id": page_id,
                    "order": media_ref.order,
                    "type": media_ref.media_type,
                    "filename": media_ref.filename,
                    "attachment_id": None,  # No attachment IDs in DITA
                    "download_url": None,  # No download URLs in local ingest
                    "context": {
                        "xml_path": media_ref.xml_path,
                        "alt": media_ref.alt,
                    },
                }
                media_f.write(json.dumps(media_entry) + "\n")
                media_refs_total += 1

                # Write attachment manifest entry
                manifest_entry = {
                    "page_id": page_id,
                    "filename": media_ref.filename,
                    "media_type": media_ref.media_type,
                    "file_size": None,  # Unknown for local references
                    "download_url": None,  # No download URLs
                    "sha256": None,  # File hash not computed in ingest
                }
                manifest_f.write(json.dumps(manifest_entry) + "\n")

    return media_refs_total


def _build_hierarchy_and_write_edges(
    outdir: Path,
    maps: List[MapDoc],
    topics: List[TopicDoc],
    topic_records: List[Dict[str, Any]],
    root_dir: Path,
) -> int:
    """Build hierarchy from maps and write edges/breadcrumbs."""
    edges_path = outdir / "edges.jsonl"
    breadcrumbs_path = outdir / "breadcrumbs.jsonl"

    # Create topic lookup by relative path
    topic_by_path = {}
    for topic in topics:
        # Extract relative path from topic ID
        topic_path = topic.id.replace("topic:", "")
        if "#" in topic_path:
            topic_path = topic_path.split("#")[0]
        topic_by_path[topic_path] = topic

    ancestors_total = 0

    with (
        open(edges_path, "w") as edges_f,
        open(breadcrumbs_path, "w") as breadcrumbs_f,
    ):
        for map_doc in maps:
            map_id = map_doc.id

            # Process each reference in the map
            for ref in map_doc.hierarchy:
                if not ref.href:
                    continue

                # Resolve href to topic
                href_path = str(Path(ref.href).with_suffix("")).lower()
                if href_path in topic_by_path:
                    topic = topic_by_path[href_path]

                    # Write hierarchy edge
                    edge = {
                        "type": "PARENT_OF",
                        "src": map_id,
                        "dst": topic.id,
                    }
                    edges_f.write(json.dumps(edge) + "\n")

                    # Build breadcrumb
                    breadcrumbs = [map_doc.title]
                    if ref.navtitle:
                        breadcrumbs.append(ref.navtitle)
                    else:
                        breadcrumbs.append(topic.title)

                    breadcrumb_entry = {
                        "page_id": topic.id,
                        "breadcrumbs": breadcrumbs,
                    }
                    breadcrumbs_f.write(json.dumps(breadcrumb_entry) + "\n")

                    # Update topic record with ancestors
                    for record in topic_records:
                        if record["id"] == topic.id:
                            record["ancestors"] = breadcrumbs[
                                :-1
                            ]  # Exclude self
                            record["ancestor_count"] = len(record["ancestors"])
                            ancestors_total += 1
                            break

    return ancestors_total


def _write_labels_and_edges(
    outdir: Path, all_docs: List[TopicDoc | MapDoc]
) -> int:
    """Write label entries and label edges."""
    labels_path = outdir / "labels.jsonl"
    edges_path = outdir / "edges.jsonl"

    labels_total = 0

    with (
        open(labels_path, "w") as labels_f,
        open(edges_path, "a") as edges_f,
    ):  # Append to edges file
        for doc in all_docs:
            page_id = doc.id

            for label in doc.labels:
                # Write label entry
                label_entry = {"page_id": page_id, "label": label}
                labels_f.write(json.dumps(label_entry) + "\n")
                labels_total += 1

                # Write label edge
                edge = {
                    "type": "LABELED_AS",
                    "src": page_id,
                    "dst": f"label:{label}",
                }
                edges_f.write(json.dumps(edge) + "\n")

    return labels_total


def ingest_dita(
    outdir: str,
    root: str,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    progress: bool = False,
    progress_every: int = 1,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest DITA topics and maps from filesystem."""
    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)

    root_dir = Path(root)
    if not root_dir.exists():
        raise ValueError(f"Root directory does not exist: {root}")

    started_at = datetime.now(timezone.utc)

    # Output files
    ndjson_path = outdir_path / "dita.ndjson"
    summary_path = outdir_path / "summary.json"

    log.info("dita.ingest.start", run_id=run_id, root=root, outdir=outdir)

    # Collect all DITA files
    dita_files = list(_find_dita_files(root_dir, include, exclude))
    log.info("dita.scan.complete", files_found=len(dita_files))

    if not dita_files:
        log.warning("dita.scan.no_files", root=root)

    # Parse files
    topics: List[TopicDoc] = []
    maps: List[MapDoc] = []
    topic_records: List[Dict[str, Any]] = []
    map_records: List[Dict[str, Any]] = []

    processed_count = 0

    for file_path in dita_files:
        try:
            # Update relative path in adapter for stable IDs
            rel_path = str(file_path.relative_to(root_dir))
            file_stats = file_path.stat()
            file_sha256 = compute_file_sha256(file_path)

            if (
                file_path.suffix.lower() == ".ditamap"
                or "map" in file_path.stem.lower()
            ):
                # Parse as map
                map_doc = parse_map(file_path)
                # Update ID with correct relative path
                map_doc.id = (
                    f"map:{Path(rel_path).with_suffix('').as_posix().lower()}"
                )
                maps.append(map_doc)

                record = _create_dita_record(
                    map_doc, file_path, root_dir, file_stats, file_sha256
                )
                map_records.append(record)

            else:
                # Parse as topic
                topic_doc = parse_topic(file_path)
                # Update ID with correct relative path
                base_id = f"topic:{Path(rel_path).with_suffix('').as_posix().lower()}"
                if "#" in topic_doc.id:
                    element_id = topic_doc.id.split("#")[1]
                    topic_doc.id = f"{base_id}#{element_id}"
                else:
                    topic_doc.id = base_id
                topics.append(topic_doc)

                record = _create_dita_record(
                    topic_doc, file_path, root_dir, file_stats, file_sha256
                )
                topic_records.append(record)

            processed_count += 1

            if progress and (processed_count % progress_every == 0):
                log.info(
                    "dita.progress",
                    processed=processed_count,
                    total=len(dita_files),
                )

        except Exception as e:
            log.error("dita.parse.error", file=str(file_path), error=str(e))
            continue

    # Write main NDJSON file
    all_records = topic_records + map_records
    with open(ndjson_path, "w") as f:
        for record in all_records:
            f.write(json.dumps(record) + "\n")

    # Write sidecar files
    media_refs_total = _write_media_sidecars(
        outdir_path, topics, topic_records
    )
    ancestors_total = _build_hierarchy_and_write_edges(
        outdir_path, maps, topics, topic_records, root_dir
    )
    labels_total = _write_labels_and_edges(outdir_path, topics + maps)

    # Write summary
    ended_at = datetime.now(timezone.utc)
    summary = {
        "started_at": _iso(started_at),
        "ended_at": _iso(ended_at),
        "duration_seconds": (ended_at - started_at).total_seconds(),
        "pages": len(all_records),
        "attachments": sum(len(topic.images) for topic in topics),
        "media_refs_total": media_refs_total,
        "labels_total": labels_total,
        "ancestors_total": ancestors_total,
        "sources": ["dita"],
        "topics": len(topics),
        "maps": len(maps),
        "files_processed": processed_count,
        "files_found": len(dita_files),
    }

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    log.info(
        "dita.ingest.complete",
        run_id=run_id,
        topics=len(topics),
        maps=len(maps),
        media_refs=media_refs_total,
        labels=labels_total,
    )

    return summary
