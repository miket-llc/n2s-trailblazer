"""DITA XML parser for topics and maps.

Parses DITA topics (concept, task, reference) and ditamaps to extract:
- Topic content and metadata
- Map hierarchy and references
- Media references (images, objects)
- Keywords and metadata for labels
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
import hashlib
from lxml import etree  # type: ignore
from dataclasses import dataclass
from ..core.logging import log


@dataclass
class MediaRef:
    """Media reference extracted from DITA content."""

    filename: str
    media_type: str
    xml_path: str
    alt: Optional[str] = None
    order: int = 0


@dataclass
class TopicDoc:
    """Parsed DITA topic document."""

    id: str
    title: str
    doctype: str  # topic, concept, task, reference
    body_xml: str
    prolog_metadata: Dict[str, Any]
    images: List[MediaRef]
    xrefs: List[str]
    keyrefs: List[str]
    conrefs: List[str]
    labels: List[str]


@dataclass
class MapRef:
    """Reference within a DITA map."""

    href: Optional[str]
    navtitle: Optional[str]
    type: Optional[str]
    scope: Optional[str]
    processing_role: Optional[str]


@dataclass
class MapDoc:
    """Parsed DITA map document."""

    id: str
    title: str
    keydefs: Dict[str, str]
    hierarchy: List[MapRef]
    labels: List[str]


def _normalize_path(path: str) -> str:
    """Normalize path separators to forward slashes and lowercase."""
    return str(Path(path).as_posix()).lower()


def _generate_topic_id(relpath: str, element_id: Optional[str] = None) -> str:
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
        text_parts.append(element.text)

    for child in element:
        text_parts.append(_extract_text_content(child))
        if child.tail:
            text_parts.append(child.tail)

    return " ".join(text_parts).strip()


def _extract_media_from_element(
    element: etree._Element,
    xml_path: str,
    media_list: List[MediaRef],
    order_counter: List[int],
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
        _extract_media_from_element(
            child, child_path, media_list, order_counter
        )


def _extract_labels_from_prolog(prolog: Optional[etree._Element]) -> List[str]:
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
    for meta in prolog.xpath(
        ".//*[@audience or @product or @platform or @otherprops]"
    ):
        for attr in ["audience", "product", "platform", "otherprops"]:
            value = meta.get(attr)
            if value:
                # Handle space-separated values
                for val in value.split():
                    labels.add(f"{attr}:{val}")

    return sorted(list(labels))


def _parse_map_hierarchy(map_element: etree._Element) -> List[MapRef]:
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
        relpath = (
            file_path.name
        )  # Will be updated by caller with full relative path

        # Generate stable ID
        doc_id = _generate_topic_id(relpath, topic_id)

        # Extract title
        title_elem = root.find(".//title")
        title = (
            _extract_text_content(title_elem)
            if title_elem is not None
            else file_path.stem
        )

        # Extract prolog metadata
        prolog = root.find("prolog")
        prolog_metadata = {}
        if prolog is not None:
            # Extract metadata elements
            for meta in prolog.xpath(".//metadata/*"):
                prolog_metadata[meta.tag] = _extract_text_content(meta)

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
            body_xml = etree.tostring(
                body, encoding="unicode", pretty_print=True
            )

        # Extract media references
        media_list: List[MediaRef] = []
        order_counter = [1]  # Use list to allow mutation in nested function
        if body is not None:
            _extract_media_from_element(
                body, "/topic/body", media_list, order_counter
            )

        # Extract cross-references
        xrefs = []
        for xref in root.xpath(".//xref[@href]"):
            href = xref.get("href")
            if href:
                xrefs.append(href)

        # Extract key references
        keyrefs = []
        for elem in root.xpath(".//*[@keyref]"):
            keyref = elem.get("keyref")
            if keyref:
                keyrefs.append(keyref)

        # Extract content references
        conrefs = []
        for elem in root.xpath(".//*[@conref]"):
            conref = elem.get("conref")
            if conref:
                conrefs.append(conref)

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
        relpath = (
            file_path.name
        )  # Will be updated by caller with full relative path
        doc_id = _generate_map_id(relpath)

        # Extract title
        title_elem = root.find(".//title")
        title = (
            _extract_text_content(title_elem)
            if title_elem is not None
            else file_path.stem
        )

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

        return MapDoc(
            id=doc_id,
            title=title,
            keydefs=keydefs,
            hierarchy=hierarchy,
            labels=labels,
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
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read(1024)  # Read first 1KB

            # Check for DITA DOCTYPE
            if "<!DOCTYPE" in content and any(
                dt in content
                for dt in ["topic", "concept", "task", "reference", "map"]
            ):
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
