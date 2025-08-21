"""DITA ingest step.

Scans a directory tree for DITA files, parses topics and maps,
and writes graph-ready artifacts to outdir.
"""

import fnmatch
import hashlib
import json
import os
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....adapters.dita import (
    MapDoc,
    TopicDoc,
    compute_file_sha256,
    is_dita_file,
    parse_map,
    parse_topic,
)
from ....core.logging import log


def _iso(dt: datetime | None) -> str | None:
    """Convert datetime to ISO string."""
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def _should_include_file(
    file_path: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> bool:
    """Check if file should be included based on glob patterns."""
    filename = file_path.name
    rel_path = str(file_path)

    # Check exclude patterns first
    if exclude_patterns:
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(rel_path, pattern):
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
        elif fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(rel_path, pattern):
            return True

    return False


def _find_dita_files(
    root_dir: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
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
        if not _should_include_file(rel_path, include_patterns, exclude_patterns):
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
) -> dict[str, Any]:
    """Create canonical DITA record for NDJSON output."""
    rel_path = str(file_path.relative_to(root_dir))

    # Common fields
    record: dict[str, Any] = {
        "source_system": "dita",
        "id": doc.id,
        "title": doc.title,
        "source_path": rel_path,
        "source_file_sha256": file_sha256,
        "body_repr": "dita",
        "labels": doc.labels,
        "created_at": _iso(datetime.fromtimestamp(file_stats.st_ctime, tz=timezone.utc)),
        "updated_at": _iso(datetime.fromtimestamp(file_stats.st_mtime, tz=timezone.utc)),
    }

    # Type-specific fields
    if isinstance(doc, TopicDoc):
        record.update(
            {
                "doctype": doc.doctype,
                "body_dita_xml": (
                    doc.body_xml[:10000] if len(doc.body_xml) > 10000 else doc.body_xml
                ),  # Truncate if huge
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
    record["content_sha256"] = hashlib.sha256(content_for_hash.encode()).hexdigest()

    return record


def _write_media_sidecars(outdir: Path, topics: list[TopicDoc], topic_records: list[dict[str, Any]]) -> int:
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
    maps: list[MapDoc],
    topics: list[TopicDoc],
    topic_records: list[dict[str, Any]],
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
                            record["ancestors"] = breadcrumbs[:-1]  # Exclude self
                            record["ancestor_count"] = len(record["ancestors"])
                            ancestors_total += 1
                            break

    return ancestors_total


def _compute_directory_context(source_path: str, root_dir: Path) -> dict[str, Any]:
    """Compute collection and path_tags from source_path under ellucian-documentation."""
    context: dict[str, Any] = {"collection": None, "path_tags": []}

    try:
        # Convert to Path and make relative to root
        path = Path(source_path)
        rel_path = path.relative_to(root_dir) if path.is_absolute() else path

        # Find ellucian-documentation in the path
        parts = rel_path.parts
        ellucian_idx = None
        for i, part in enumerate(parts):
            if "ellucian-documentation" in part:
                ellucian_idx = i
                break

        if ellucian_idx is not None and ellucian_idx + 1 < len(parts):
            # Collection is the first subfolder after ellucian-documentation
            context["collection"] = parts[ellucian_idx + 1]
        elif len(parts) > 1:
            # If no ellucian-documentation found but we have multiple parts,
            # use the first directory as collection
            context["collection"] = parts[0]

        # Path tags are unique lowercased segments, excluding stopwords
        stopwords = {
            "docs",
            "images",
            "assets",
            "common",
            "master",
            "dita",
            "xml",
            "content",
        }
        path_tags = set()

        for part in parts:
            # Remove file extension from the last part (filename)
            part_name = Path(part).stem if "." in part else part
            # Split on common separators and lowercase
            segments = re.split(r"[-_\s]+", part_name.lower())
            for segment in segments:
                if segment and segment not in stopwords and len(segment) > 2:
                    path_tags.add(segment)

        context["path_tags"] = sorted(list(path_tags))

    except Exception:
        # If path parsing fails, return empty context
        pass

    return context


def _aggregate_labels_and_metadata(
    doc: TopicDoc | MapDoc,
    source_path: str,
    root_dir: Path,
    map_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate labels and metadata from XML prolog, map context, and directory hints."""

    # Start with enhanced metadata
    metadata = doc.enhanced_metadata.copy()

    # Compute directory context
    dir_context = _compute_directory_context(source_path, root_dir)
    if dir_context["collection"]:
        metadata["collection"] = dir_context["collection"]

    # Combine all labels
    labels = set(doc.labels)  # Start with XML-derived labels

    # Add directory-based path tags as labels
    for tag in dir_context["path_tags"]:
        labels.add(tag)

    # Add collection as label if present
    if dir_context["collection"]:
        labels.add(dir_context["collection"])

    # Add metadata values as labels where appropriate
    if metadata.get("audience"):
        labels.add(f"audience:{metadata['audience']}")
    if metadata.get("product"):
        labels.add(f"product:{metadata['product']}")
    if metadata.get("platform"):
        labels.add(f"platform:{metadata['platform']}")

    # Add keywords as labels
    for keyword in metadata.get("keywords", []):
        labels.add(keyword)

    # Add otherprops as labels
    for key, value in metadata.get("otherprops", {}).items():
        labels.add(f"{key}:{value}")

    # Add map context if provided
    if map_context:
        metadata["map_titles"] = map_context.get("map_titles", [])
        # Add map titles as potential labels
        for title in metadata["map_titles"]:
            labels.add(f"map:{title.lower().replace(' ', '-')}")

    return {
        "labels": sorted(list(labels)),
        "meta": metadata,
        "collection": dir_context["collection"],
        "path_tags": dir_context["path_tags"],
    }


def _write_links_sidecar(outdir: Path, all_docs: list[TopicDoc | MapDoc], root_dir: Path) -> dict[str, int]:
    """Write links.jsonl with classified and normalized links."""
    links_path = outdir / "links.jsonl"

    stats = {
        "total": 0,
        "external": 0,
        "dita": 0,
        "confluence": 0,
        "conrefs": 0,
    }

    with open(links_path, "w") as f:
        for doc in all_docs:
            # Extract source path for relative path calculation (unused for now)
            # source_path = None
            # if hasattr(doc, 'id'):
            #     if doc.id.startswith("topic:"):
            #         source_path = doc.id[6:] + ".dita"
            #     elif doc.id.startswith("map:"):
            #         source_path = doc.id[4:] + ".ditamap"

            for link in doc.links:
                stats["total"] += 1

                # Count by type
                if link.element_type in ("conref", "conkeyref"):
                    stats["conrefs"] += 1
                else:
                    stats[link.target_type] += 1

                # Create link record
                link_record = {
                    "from_page_id": doc.id,
                    "from_url": None,
                    "target_type": link.target_type,
                    "target_page_id": link.target_page_id,
                    "target_url": link.target_url,
                    "anchor": link.anchor,
                    "text": link.text,
                    "rel": ("CONREFS" if link.element_type in ("conref", "conkeyref") else "links_to"),
                }

                f.write(json.dumps(link_record) + "\n")

    return stats


def _write_metadata_sidecar(
    outdir: Path,
    all_docs: list[TopicDoc | MapDoc],
    aggregated_metadata: list[dict[str, Any]],
    root_dir: Path,
) -> int:
    """Write meta.jsonl with compact metadata records."""
    meta_path = outdir / "meta.jsonl"

    with open(meta_path, "w") as f:
        for doc, meta_data in zip(all_docs, aggregated_metadata, strict=False):
            record = {
                "page_id": doc.id,
                "collection": meta_data["collection"],
                "path_tags": meta_data["path_tags"],
                "labels": meta_data["labels"],
                "meta": meta_data["meta"],
            }
            f.write(json.dumps(record) + "\n")

    return len(all_docs)


def _write_labels_and_edges(outdir: Path, all_docs: list[TopicDoc | MapDoc]) -> int:
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
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    progress: bool = False,
    progress_every: int = 1,
    run_id: str | None = None,
) -> dict[str, Any]:
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
    topics: list[TopicDoc] = []
    maps: list[MapDoc] = []
    topic_records: list[dict[str, Any]] = []
    map_records: list[dict[str, Any]] = []

    processed_count = 0

    for file_path in dita_files:
        try:
            # Update relative path in adapter for stable IDs
            rel_path = str(file_path.relative_to(root_dir))
            file_stats = file_path.stat()
            file_sha256 = compute_file_sha256(file_path)

            if file_path.suffix.lower() == ".ditamap" or "map" in file_path.stem.lower():
                # Parse as map
                map_doc = parse_map(file_path)
                # Update ID with correct relative path
                map_doc.id = f"map:{Path(rel_path).with_suffix('').as_posix().lower()}"

                # Update link resolution with correct root_dir context
                for link in map_doc.links:
                    if link.target_type == "dita" and link.href and not link.target_page_id:
                        from ....adapters.dita import _resolve_dita_reference

                        link.target_page_id = _resolve_dita_reference(link.href, file_path, root_dir)

                maps.append(map_doc)

                record = _create_dita_record(map_doc, file_path, root_dir, file_stats, file_sha256)
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

                # Update link resolution with correct root_dir context
                for link in topic_doc.links:
                    if link.target_type == "dita" and link.href and not link.target_page_id:
                        from ....adapters.dita import _resolve_dita_reference

                        link.target_page_id = _resolve_dita_reference(link.href, file_path, root_dir)

                topics.append(topic_doc)

                record = _create_dita_record(topic_doc, file_path, root_dir, file_stats, file_sha256)
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

    # Aggregate metadata for all documents
    all_docs = topics + maps
    aggregated_metadata = []

    # Build map context for topics (map titles from breadcrumbs)
    map_context_by_topic: dict[str, Any] = {}
    for map_doc in maps:
        for ref in map_doc.hierarchy:
            if ref.href:
                # Try to match with topic paths
                href_path = str(Path(ref.href).with_suffix("")).lower()
                for topic in topics:
                    topic_path = topic.id.replace("topic:", "")
                    if "#" in topic_path:
                        topic_path = topic_path.split("#")[0]
                    if topic_path == href_path:
                        if topic.id not in map_context_by_topic:
                            map_context_by_topic[topic.id] = {"map_titles": []}
                        map_context_by_topic[topic.id]["map_titles"].append(map_doc.title)

    # Aggregate metadata for each document
    for doc in all_docs:
        source_path = None
        if doc.id.startswith("topic:"):
            source_path = doc.id[6:] + ".dita"
        elif doc.id.startswith("map:"):
            source_path = doc.id[4:] + ".ditamap"

        map_context = map_context_by_topic.get(doc.id, None)
        meta_data = _aggregate_labels_and_metadata(doc, source_path or "", root_dir, map_context)
        aggregated_metadata.append(meta_data)

    # Write sidecar files
    media_refs_total = _write_media_sidecars(outdir_path, topics, topic_records)
    ancestors_total = _build_hierarchy_and_write_edges(outdir_path, maps, topics, topic_records, root_dir)

    # Write enhanced links sidecar
    links_stats = _write_links_sidecar(outdir_path, all_docs, root_dir)

    # Write metadata sidecar
    meta_records = _write_metadata_sidecar(outdir_path, all_docs, aggregated_metadata, root_dir)

    # Update labels to use aggregated labels
    labels_total = 0
    labels_path = outdir_path / "labels.jsonl"
    edges_path = outdir_path / "edges.jsonl"

    with (
        open(labels_path, "w") as labels_f,
        open(edges_path, "a") as edges_f,
    ):  # Append to edges file
        for doc, meta_data in zip(all_docs, aggregated_metadata, strict=False):
            page_id = doc.id
            for label in meta_data["labels"]:
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
        "meta_records": meta_records,
        "links_total": links_stats["total"],
        "links_external": links_stats["external"],
        "links_dita": links_stats["dita"],
        "links_confluence": links_stats["confluence"],
        "links_conrefs": links_stats["conrefs"],
        "sources": ["dita"],
        "topics": len(topics),
        "maps": len(maps),
        "files_processed": processed_count,
        "files_found": len(dita_files),
    }

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Count top 10 label terms for summary
    from collections import Counter

    all_labels = []
    for meta_data in aggregated_metadata:
        all_labels.extend(meta_data["labels"])

    top_labels = Counter(all_labels).most_common(10)

    # Emit structured log event for metadata summary
    log.info(
        "ingest.dita_meta_summary",
        run_id=run_id,
        meta_records=meta_records,
        labels_total=labels_total,
        top_labels=[{"label": label, "count": count} for label, count in top_labels],
        links_total=links_stats["total"],
        links_by_type=links_stats,
    )

    log.info(
        "dita.ingest.complete",
        run_id=run_id,
        topics=len(topics),
        maps=len(maps),
        media_refs=media_refs_total,
        labels=labels_total,
        meta_records=meta_records,
        links_total=links_stats["total"],
    )

    return summary
