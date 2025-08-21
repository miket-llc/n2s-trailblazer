"""DITA XML parser for topics and maps.

Parses DITA topics (concept, task, reference) and ditamaps to extract:
- Topic content and metadata
- Map hierarchy and references
- Media references (images, objects)
- Keywords and metadata for labels
"""

import hashlib
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore

from ..core.logging import log


@dataclass
class MediaRef:
    """Media reference extracted from DITA content."""

    filename: str
    media_type: str
    xml_path: str
    alt: str | None = None
    order: int = 0


@dataclass
class LinkRef:
    """Link reference extracted from DITA content."""

    href: str | None
    keyref: str | None
    conref: str | None
    target_type: str  # "external", "dita", "confluence"
    target_page_id: str | None
    target_url: str | None
    anchor: str | None
    text: str | None
    element_type: str  # "xref", "link", "conref", "conkeyref"


@dataclass
class TopicDoc:
    """Parsed DITA topic document."""

    id: str
    title: str
    doctype: str  # topic, concept, task, reference
    body_xml: str
    prolog_metadata: dict[str, Any]
    images: list[MediaRef]
    xrefs: list[str]
    keyrefs: list[str]
    conrefs: list[str]
    labels: list[str]
    links: list[LinkRef]  # Enhanced link extraction
    enhanced_metadata: dict[str, Any]  # Structured metadata from prolog


@dataclass
class MapRef:
    """Reference within a DITA map."""

    href: str | None
    navtitle: str | None
    type: str | None
    scope: str | None
    processing_role: str | None


@dataclass
class MapDoc:
    """Parsed DITA map document."""

    id: str
    title: str
    keydefs: dict[str, str]
    hierarchy: list[MapRef]
    labels: list[str]
    links: list[LinkRef]  # Enhanced link extraction
    enhanced_metadata: dict[str, Any]  # Structured metadata from prolog


def _normalize_path(path: str) -> str:
    """Normalize path separators to forward slashes and lowercase."""
    return str(Path(path).as_posix()).lower()


def _normalize_url(url: str) -> str:
    """Normalize URL by removing tracking parameters and fragments."""
    if not url:
        return url

    # Parse URL
    parsed = urllib.parse.urlparse(url)

    # Remove common tracking parameters
    tracking_params = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "msclkid",
        "_ga",
        "_gac",
        "mc_cid",
        "mc_eid",
    }

    if parsed.query:
        query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        filtered_params = {k: v for k, v in query_params.items() if k not in tracking_params}
        new_query = urllib.parse.urlencode(filtered_params, doseq=True)
    else:
        new_query = ""

    # Reconstruct URL without tracking params but keep fragment/anchor
    normalized = urllib.parse.urlunparse(
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


def _classify_link_type(href: str, is_keyref: bool = False) -> str:
    """Classify link as external, dita internal, or confluence."""
    if not href:
        return "external"

    # If it's a keyref, treat as DITA internal for now
    if is_keyref:
        return "dita"

    # Check if it's an external URL
    if href.startswith(("http://", "https://", "ftp://", "mailto:")):
        if "confluence" in href.lower() or "atlassian" in href.lower():
            return "confluence"
        return "external"

    # If it ends with DITA extensions, it's internal DITA
    if href.endswith((".dita", ".ditamap", ".xml")):
        return "dita"

    # If it's a relative path without extension, likely DITA
    if not href.startswith("/") and "." not in Path(href).suffix:
        return "dita"

    # Default to external for other cases
    return "external"


def _resolve_dita_reference(href: str, current_file_path: Path, root_dir: Path) -> str | None:
    """Resolve DITA internal reference to our standard ID format."""
    if not href or href.startswith(("http://", "https://")):
        return None

    try:
        # Extract anchor if present in href
        anchor = None
        clean_href = href
        if "#" in href:
            clean_href, anchor = href.split("#", 1)

        # Handle relative paths
        if not clean_href.startswith("/"):
            # Resolve relative to current file directory
            resolved_path = current_file_path.parent / clean_href
        else:
            # Absolute path relative to root
            resolved_path = root_dir / clean_href.lstrip("/")

        # Get relative path from root (don't require file to exist)
        try:
            if resolved_path.is_absolute():
                rel_path = resolved_path.relative_to(root_dir)
            else:
                rel_path = resolved_path
        except ValueError:
            # Path is outside root directory, try as relative
            rel_path = Path(clean_href)

        # Normalize path and create ID
        path_str = str(rel_path)
        normalized_path = Path(path_str).with_suffix("").as_posix().lower()

        # Determine if it's a map or topic
        if path_str.endswith(".ditamap") or "map" in Path(path_str).stem.lower():
            page_id = f"map:{normalized_path}"
        else:
            page_id = f"topic:{normalized_path}"
            if anchor:
                page_id += f"#{anchor}"

        return page_id

    except Exception:
        return None


def _generate_topic_id(relpath: str, element_id: str | None = None) -> str:
    """Generate stable topic ID from relative path and optional element ID."""
    # Remove extension and normalize
    base = Path(relpath).with_suffix("").as_posix().lower()
    if element_id:
        return f"topic:{base}#{element_id}"
    return f"topic:{base}"


def _generate_map_id(relpath: str) -> str:
    """Generate stable map ID from relative path."""
    base = Path(relpath).with_suffix("").as_posix().lower()
    return f"map:{base}"


def _extract_text_content(element: etree._Element) -> str:
    """Extract text content from XML element, handling nested elements."""
    if element is None:
        return ""

    # Get all text content, including from child elements
    text_parts = []
    if element.text:
        text_parts.append(element.text.strip())

    for child in element:
        child_text = _extract_text_content(child)
        if child_text:
            text_parts.append(child_text)
        if child.tail:
            text_parts.append(child.tail.strip())

    # Join with single spaces and normalize whitespace
    result = " ".join(text_parts)
    # Replace multiple whitespace with single space
    import re

    result = re.sub(r"\s+", " ", result)
    return result.strip()


def _extract_media_from_element(
    element: etree._Element,
    xml_path: str,
    media_list: list[MediaRef],
    order_counter: list[int],
) -> None:
    """Recursively extract media references from XML element."""
    tag = element.tag

    # Handle image elements
    if tag == "image":
        href = element.get("href")
        alt = element.get("alt") or _extract_text_content(element)
        if href:
            media_list.append(
                MediaRef(
                    filename=href,
                    media_type="image",
                    xml_path=f"{xml_path}/{tag}[{order_counter[0]}]",
                    alt=alt,
                    order=order_counter[0],
                )
            )
            order_counter[0] += 1

    # Handle object elements (files, media)
    elif tag == "object":
        data = element.get("data")
        type_attr = element.get("type", "file")
        if data:
            media_list.append(
                MediaRef(
                    filename=data,
                    media_type=type_attr,
                    xml_path=f"{xml_path}/{tag}[{order_counter[0]}]",
                    order=order_counter[0],
                )
            )
            order_counter[0] += 1

    # Recursively process child elements
    for i, child in enumerate(element, 1):
        child_path = f"{xml_path}/{child.tag}[{i}]"
        _extract_media_from_element(child, child_path, media_list, order_counter)


def _extract_enhanced_metadata_from_prolog(
    prolog: etree._Element | None,
) -> dict[str, Any]:
    """Extract enhanced structured metadata from DITA prolog."""
    metadata: dict[str, Any] = {
        "audience": None,
        "product": None,
        "platform": None,
        "keywords": [],
        "otherprops": {},
        "resource_app": None,
        "critdates": {"created": None, "modified": None},
        "authors": [],
        "data_pairs": {},
    }
    keywords_list = metadata["keywords"]  # type: List[str]
    authors_list = metadata["authors"]  # type: List[str]

    if prolog is None:
        return metadata

    # Extract keywords
    for keywords in prolog.xpath(".//keywords"):
        for keyword in keywords.xpath(".//keyword"):
            text = _extract_text_content(keyword)
            if text:
                keywords_list.append(text)

    # Extract audience, product, platform from various elements
    for meta in prolog.xpath(".//*[@audience or @product or @platform or @otherprops]"):
        if meta.get("audience"):
            metadata["audience"] = meta.get("audience")
        if meta.get("product"):
            metadata["product"] = meta.get("product")
        if meta.get("platform"):
            metadata["platform"] = meta.get("platform")
        if meta.get("otherprops"):
            # Parse otherprops as key=value pairs
            otherprops_str = meta.get("otherprops", "")
            for prop in otherprops_str.split():
                if "=" in prop:
                    key, value = prop.split("=", 1)
                    metadata["otherprops"][key] = value
                else:
                    metadata["otherprops"][prop] = "true"

    # Extract resourceid/@appname
    for resourceid in prolog.xpath(".//resourceid[@appname]"):
        metadata["resource_app"] = resourceid.get("appname")

    # Extract critdates
    for critdates in prolog.xpath(".//critdates"):
        created = critdates.get("created")
        modified = critdates.get("modified")
        if created:
            metadata["critdates"]["created"] = created
        if modified:
            metadata["critdates"]["modified"] = modified

    # Extract authors
    for author in prolog.xpath(".//author"):
        author_text = _extract_text_content(author)
        if author_text:
            authors_list.append(author_text)

    for authorinfo in prolog.xpath(".//authorinformation"):
        for personname in authorinfo.xpath(".//personname"):
            name_text = _extract_text_content(personname)
            if name_text:
                authors_list.append(name_text)

    # Extract data pairs
    for data in prolog.xpath(".//data[@name and @value]"):
        name = data.get("name")
        value = data.get("value")
        if name and value:
            metadata["data_pairs"][name] = value

    return metadata


def _extract_links_from_element(element: etree._Element, current_file_path: Path, root_dir: Path) -> list[LinkRef]:
    """Extract and classify links from XML element."""
    links = []

    # Extract xref elements with href
    for xref in element.xpath(".//xref[@href]"):
        href = xref.get("href")
        text = _extract_text_content(xref)

        # Extract anchor from href
        anchor = None
        if "#" in href:
            href_parts = href.split("#", 1)
            href = href_parts[0]
            anchor = href_parts[1]

        target_type = _classify_link_type(href)
        target_page_id = None
        target_url = href

        if target_type == "dita":
            target_page_id = _resolve_dita_reference(href, current_file_path, root_dir)
            target_url = None
        else:
            target_url = _normalize_url(href)

        links.append(
            LinkRef(
                href=href,
                keyref=None,
                conref=None,
                target_type=target_type,
                target_page_id=target_page_id,
                target_url=target_url,
                anchor=anchor,
                text=text,
                element_type="xref",
            )
        )

    # Extract xref elements with keyref
    for xref in element.xpath(".//xref[@keyref]"):
        keyref = xref.get("keyref")
        text = _extract_text_content(xref)

        links.append(
            LinkRef(
                href=None,
                keyref=keyref,
                conref=None,
                target_type="dita",
                target_page_id=None,  # Will be resolved later with keydef context
                target_url=None,
                anchor=None,
                text=text,
                element_type="xref",
            )
        )

    # Extract link elements with href
    for link in element.xpath(".//link[@href]"):
        href = link.get("href")
        text = _extract_text_content(link)

        # Extract anchor from href
        anchor = None
        if "#" in href:
            href_parts = href.split("#", 1)
            href = href_parts[0]
            anchor = href_parts[1]

        target_type = _classify_link_type(href)
        target_page_id = None
        target_url = href

        if target_type == "dita":
            target_page_id = _resolve_dita_reference(href, current_file_path, root_dir)
            target_url = None
        else:
            target_url = _normalize_url(href)

        links.append(
            LinkRef(
                href=href,
                keyref=None,
                conref=None,
                target_type=target_type,
                target_page_id=target_page_id,
                target_url=target_url,
                anchor=anchor,
                text=text,
                element_type="link",
            )
        )

    # Extract conref elements (structural references)
    for elem in element.xpath(".//*[@conref]"):
        conref = elem.get("conref")

        # Extract anchor from conref
        anchor = None
        if "#" in conref:
            conref_parts = conref.split("#", 1)
            conref = conref_parts[0]
            anchor = conref_parts[1]

        target_page_id = _resolve_dita_reference(conref, current_file_path, root_dir)

        links.append(
            LinkRef(
                href=None,
                keyref=None,
                conref=conref,
                target_type="dita",
                target_page_id=target_page_id,
                target_url=None,
                anchor=anchor,
                text=None,
                element_type="conref",
            )
        )

    # Extract conkeyref elements (structural key references)
    for elem in element.xpath(".//*[@conkeyref]"):
        conkeyref = elem.get("conkeyref")

        links.append(
            LinkRef(
                href=None,
                keyref=conkeyref,
                conref=None,
                target_type="dita",
                target_page_id=None,  # Will be resolved later with keydef context
                target_url=None,
                anchor=None,
                text=None,
                element_type="conkeyref",
            )
        )

    # Extract topicref elements with href (for maps)
    for topicref in element.xpath(".//topicref[@href]"):
        href = topicref.get("href")
        navtitle = topicref.get("navtitle")
        scope = topicref.get("scope", "local")

        # Extract anchor from href
        anchor = None
        if "#" in href:
            href_parts = href.split("#", 1)
            href = href_parts[0]
            anchor = href_parts[1]

        # Determine target type based on scope and href
        if scope == "external" or href.startswith(("http://", "https://")):
            target_type = _classify_link_type(href)
            target_page_id = None
            target_url = _normalize_url(href)
        else:
            target_type = "dita"
            target_page_id = _resolve_dita_reference(href, current_file_path, root_dir)
            target_url = None

        links.append(
            LinkRef(
                href=href,
                keyref=None,
                conref=None,
                target_type=target_type,
                target_page_id=target_page_id,
                target_url=target_url,
                anchor=anchor,
                text=navtitle,
                element_type="topicref",
            )
        )

    return links


def _extract_labels_from_prolog(prolog: etree._Element | None) -> list[str]:
    """Extract labels from DITA prolog metadata."""
    labels = set()

    if prolog is None:
        return []

    # Extract from metadata/keywords
    for keywords in prolog.xpath(".//keywords"):
        for keyword in keywords.xpath(".//keyword"):
            text = _extract_text_content(keyword)
            if text:
                labels.add(text)

    # Extract from metadata/othermeta
    for othermeta in prolog.xpath(".//othermeta"):
        name = othermeta.get("name", "")
        content = othermeta.get("content", "")
        if name and content:
            labels.add(f"{name}:{content}")

    # Extract common attributes that act as labels
    for meta in prolog.xpath(".//*[@audience or @product or @platform or @otherprops]"):
        for attr in ["audience", "product", "platform", "otherprops"]:
            value = meta.get(attr)
            if value:
                # Handle space-separated values
                for val in value.split():
                    labels.add(f"{attr}:{val}")

    return sorted(list(labels))


def _parse_map_hierarchy(map_element: etree._Element) -> list[MapRef]:
    """Parse map hierarchy into list of references."""
    refs = []

    def _process_topicref(topicref: etree._Element) -> None:
        href = topicref.get("href")
        navtitle = topicref.get("navtitle")
        type_attr = topicref.get("type")
        scope = topicref.get("scope")
        processing_role = topicref.get("processing-role")

        # Try to get navtitle from child navtitle element if not in attribute
        if not navtitle:
            navtitle_elem = topicref.find("navtitle")
            if navtitle_elem is not None:
                navtitle = _extract_text_content(navtitle_elem)

        refs.append(
            MapRef(
                href=href,
                navtitle=navtitle,
                type=type_attr,
                scope=scope,
                processing_role=processing_role,
            )
        )

        # Recursively process nested topicrefs
        for child_ref in topicref.xpath(".//topicref"):
            _process_topicref(child_ref)

    # Process all topicref elements
    for topicref in map_element.xpath(".//topicref"):
        _process_topicref(topicref)

    return refs


def parse_topic(file_path: Path) -> TopicDoc:
    """Parse a DITA topic file."""
    try:
        # Parse XML
        parser = etree.XMLParser(ns_clean=True, recover=True)
        tree = etree.parse(str(file_path), parser)
        root = tree.getroot()

        # Determine doctype from root element
        doctype = root.tag
        if doctype not in ["topic", "concept", "task", "reference"]:
            doctype = "topic"  # fallback

        # Extract ID (use @id if present, otherwise derive from filename)
        topic_id = root.get("id")
        relpath = file_path.name  # Will be updated by caller with full relative path

        # Generate stable ID
        doc_id = _generate_topic_id(relpath, topic_id)

        # Extract title
        title_elem = root.find(".//title")
        title = _extract_text_content(title_elem) if title_elem is not None else file_path.stem

        # Extract prolog metadata
        prolog = root.find("prolog")
        prolog_metadata = {}
        if prolog is not None:
            # Extract metadata elements
            for meta in prolog.xpath(".//metadata/*"):
                prolog_metadata[meta.tag] = _extract_text_content(meta)

        # Extract enhanced metadata from prolog
        enhanced_metadata = _extract_enhanced_metadata_from_prolog(prolog)

        # Extract labels from prolog
        labels = _extract_labels_from_prolog(prolog)

        # Extract body content as XML string
        body = root.find("body")
        if body is None:
            body = root.find("conbody")  # For concept topics
        if body is None:
            body = root.find("taskbody")  # For task topics
        if body is None:
            body = root.find("refbody")  # For reference topics
        body_xml = ""
        if body is not None:
            body_xml = etree.tostring(body, encoding="unicode", pretty_print=True)

        # Extract media references
        media_list: list[MediaRef] = []
        order_counter = [1]  # Use list to allow mutation in nested function
        if body is not None:
            _extract_media_from_element(body, "/topic/body", media_list, order_counter)

        # Extract cross-references (backward compatibility)
        xrefs = []
        for xref in root.xpath(".//xref[@href]"):
            href = xref.get("href")
            if href:
                xrefs.append(href)

        # Extract key references (backward compatibility)
        keyrefs = []
        for elem in root.xpath(".//*[@keyref]"):
            keyref = elem.get("keyref")
            if keyref:
                keyrefs.append(keyref)

        # Extract content references (backward compatibility)
        conrefs = []
        for elem in root.xpath(".//*[@conref]"):
            conref = elem.get("conref")
            if conref:
                conrefs.append(conref)

        # Extract enhanced links from entire document
        # Need to provide root_dir context which will be set by caller
        root_dir = file_path.parent  # Temporary, will be updated by caller
        links = _extract_links_from_element(root, file_path, root_dir)

        return TopicDoc(
            id=doc_id,
            title=title,
            doctype=doctype,
            body_xml=body_xml,
            prolog_metadata=prolog_metadata,
            images=media_list,
            xrefs=xrefs,
            keyrefs=keyrefs,
            conrefs=conrefs,
            labels=labels,
            links=links,
            enhanced_metadata=enhanced_metadata,
        )

    except Exception as e:
        log.error("dita.parse_topic.error", file=str(file_path), error=str(e))
        raise


def parse_map(file_path: Path) -> MapDoc:
    """Parse a DITA map file."""
    try:
        # Parse XML
        parser = etree.XMLParser(ns_clean=True, recover=True)
        tree = etree.parse(str(file_path), parser)
        root = tree.getroot()

        # Generate stable ID
        relpath = file_path.name  # Will be updated by caller with full relative path
        doc_id = _generate_map_id(relpath)

        # Extract title
        title_elem = root.find(".//title")
        title = _extract_text_content(title_elem) if title_elem is not None else file_path.stem

        # Extract key definitions
        keydefs = {}
        for keydef in root.xpath(".//keydef"):
            keys = keydef.get("keys", "")
            href = keydef.get("href", "")
            if keys and href:
                for key in keys.split():
                    keydefs[key] = href

        # Extract hierarchy
        hierarchy = _parse_map_hierarchy(root)

        # Extract labels (from map metadata)
        labels = []
        prolog = root.find("prolog")
        if prolog is not None:
            labels = _extract_labels_from_prolog(prolog)

        # Extract enhanced metadata from prolog
        enhanced_metadata = _extract_enhanced_metadata_from_prolog(prolog)

        # Extract enhanced links from entire document
        # Need to provide root_dir context which will be set by caller
        root_dir = file_path.parent  # Temporary, will be updated by caller
        links = _extract_links_from_element(root, file_path, root_dir)

        return MapDoc(
            id=doc_id,
            title=title,
            keydefs=keydefs,
            hierarchy=hierarchy,
            labels=labels,
            links=links,
            enhanced_metadata=enhanced_metadata,
        )

    except Exception as e:
        log.error("dita.parse_map.error", file=str(file_path), error=str(e))
        raise


def is_dita_file(file_path: Path) -> bool:
    """Check if a file is a DITA document by examining its content."""
    if not file_path.exists() or not file_path.is_file():
        return False

    # Check file extension
    if file_path.suffix.lower() in [".dita", ".ditamap"]:
        return True

    # For .xml files, check if they have DITA doctype or root elements
    if file_path.suffix.lower() == ".xml":
        try:
            # Read first few lines to check for DITA indicators
            with open(file_path, encoding="utf-8") as f:
                content = f.read(1024)  # Read first 1KB

            # Check for DITA DOCTYPE
            if "<!DOCTYPE" in content and any(dt in content for dt in ["topic", "concept", "task", "reference", "map"]):
                return True

            # Check for DITA root elements (basic XML parsing)
            try:
                parser = etree.XMLParser(ns_clean=True, recover=True)
                tree = etree.parse(str(file_path), parser)
                root = tree.getroot()
                return root.tag in [
                    "topic",
                    "concept",
                    "task",
                    "reference",
                    "map",
                    "bookmap",
                ]
            except Exception:
                return False
        except Exception:
            return False

    return False


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of file contents."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()
