"""Media extraction from ADF and Storage formats."""

from typing import Dict, List, Optional, Union
from bs4 import BeautifulSoup, Tag, PageElement


class MediaInfo:
    """Information about extracted media."""

    def __init__(
        self,
        order: int,
        media_type: str,  # image|file|media
        filename: Optional[str] = None,
        attachment_id: Optional[str] = None,
        download_url: Optional[str] = None,
        context: Optional[Dict] = None,
    ):
        self.order = order
        self.media_type = media_type
        self.filename = filename
        self.attachment_id = attachment_id
        self.download_url = download_url
        self.context = context or {}


def extract_media_from_adf(adf: Optional[dict]) -> List[MediaInfo]:
    """
    Extract media from ADF format with position awareness.

    Args:
        adf: ADF document structure

    Returns:
        List of MediaInfo objects in document order
    """
    if not adf:
        return []

    media_items = []
    order_counter = 0

    def walk_adf(node: dict, path: List[int]):
        """Walk ADF tree and extract media nodes."""
        nonlocal order_counter

        node_type = node.get("type")

        # Handle mediaSingle (ADF media container)
        if node_type == "mediaSingle":
            media_node = None
            # Find the actual media node inside mediaSingle
            for child in node.get("content", []):
                if child.get("type") == "media":
                    media_node = child
                    break

            if media_node:
                attrs = media_node.get("attrs", {})
                filename = None
                attachment_id = attrs.get("id")

                # Try to extract filename from collection or url
                if "url" in attrs:
                    url = attrs["url"]
                    # Extract filename from URL
                    if "/" in url:
                        filename = url.split("/")[-1]

                media_items.append(
                    MediaInfo(
                        order=order_counter,
                        media_type="image"
                        if attrs.get("type") == "file"
                        else "media",
                        filename=filename,
                        attachment_id=attachment_id,
                        download_url=attrs.get("url"),
                        context={
                            "adf_path": "/".join(map(str, path)),
                            "title": attrs.get("alt", ""),
                            "alt": attrs.get("alt", ""),
                            "width": attrs.get("width"),
                            "height": attrs.get("height"),
                        },
                    )
                )
                order_counter += 1

            # Don't recurse into mediaSingle content since we already processed it
            return

        # Handle direct media nodes (only if not inside mediaSingle)
        elif node_type == "media":
            attrs = node.get("attrs", {})
            filename = None
            attachment_id = attrs.get("id")

            if "collection" in attrs and "url" in attrs:
                url = attrs["url"]
                if "/" in url:
                    filename = url.split("/")[-1]

            media_items.append(
                MediaInfo(
                    order=order_counter,
                    media_type="image"
                    if attrs.get("type") == "file"
                    else "media",
                    filename=filename,
                    attachment_id=attachment_id,
                    download_url=attrs.get("url"),
                    context={
                        "adf_path": "/".join(map(str, path)),
                        "title": attrs.get("alt", ""),
                        "alt": attrs.get("alt", ""),
                    },
                )
            )
            order_counter += 1

        # Recurse into content
        content = node.get("content", [])
        if isinstance(content, list):
            for i, child in enumerate(content):
                if isinstance(child, dict):
                    walk_adf(child, path + [i])

    walk_adf(adf, [])
    return media_items


def extract_media_from_storage(storage_html: Optional[str]) -> List[MediaInfo]:
    """
    Extract media from Storage format HTML.

    Args:
        storage_html: Storage format HTML content

    Returns:
        List of MediaInfo objects in document order
    """
    if not storage_html:
        return []

    soup = BeautifulSoup(storage_html, "html.parser")
    media_items = []
    order_counter = 0

    # Find all media elements in document order
    # Note: We need to be careful not to double-count ri:attachment inside ac:image
    media_elements: List[Union[Tag, PageElement]] = []

    # First, find all ac:image elements (these may contain ri:attachment)
    ac_images = soup.find_all("ac:image")
    media_elements.extend(
        [elem for elem in ac_images if isinstance(elem, (Tag, PageElement))]
    )

    # Then find ri:attachment that are NOT inside ac:image
    all_attachments = soup.find_all("ri:attachment")
    for attachment in all_attachments:
        if isinstance(attachment, (Tag, PageElement)):
            # Check if this attachment is inside an ac:image
            parent_image = (
                attachment.find_parent("ac:image")
                if hasattr(attachment, "find_parent")
                else None
            )
            if not parent_image:
                media_elements.append(attachment)

    # Finally, add all img elements
    img_elements = soup.find_all("img")
    media_elements.extend(
        [elem for elem in img_elements if isinstance(elem, (Tag, PageElement))]
    )

    for element in media_elements:
        # Only process Tag elements
        if not isinstance(element, Tag):
            continue

        filename = None
        attachment_id = None
        download_url = None
        context = {}

        if element.name == "ac:image":
            # Confluence image macro
            # Look for ri:attachment child
            attachment_elem = element.find("ri:attachment")
            if attachment_elem and isinstance(attachment_elem, Tag):
                filename_val = attachment_elem.get("ri:filename")
                attachment_id_val = attachment_elem.get("ri:content-id")
                filename = str(filename_val) if filename_val else None
                attachment_id = (
                    str(attachment_id_val) if attachment_id_val else None
                )

            context = {
                "title": str(element.get("ac:title", "")),
                "alt": str(element.get("ac:alt", "")),
                "width": element.get("ac:width"),
                "height": element.get("ac:height"),
            }

        elif element.name == "ri:attachment":
            # Direct attachment reference
            filename_val = element.get("ri:filename")
            attachment_id_val = element.get("ri:content-id")
            filename = str(filename_val) if filename_val else None
            attachment_id = (
                str(attachment_id_val) if attachment_id_val else None
            )

        elif element.name == "img":
            # Standard HTML img tag
            src_val = element.get("src", "")
            src = str(src_val) if src_val else ""
            filename = src.split("/")[-1] if "/" in src else None
            download_url = src

            context = {
                "title": str(element.get("title", "")),
                "alt": str(element.get("alt", "")),
                "width": element.get("width"),
                "height": element.get("height"),
            }

        # Determine media type
        media_type = "image"
        if filename:
            ext = filename.lower().split(".")[-1] if "." in filename else ""
            if ext in [
                "pdf",
                "doc",
                "docx",
                "xls",
                "xlsx",
                "ppt",
                "pptx",
                "txt",
            ]:
                media_type = "file"

        media_items.append(
            MediaInfo(
                order=order_counter,
                media_type=media_type,
                filename=filename,
                attachment_id=attachment_id,
                download_url=download_url,
                context=context,
            )
        )
        order_counter += 1

    return media_items


def resolve_attachment_ids(
    media_items: List[MediaInfo], attachments: List[Dict]
) -> List[MediaInfo]:
    """
    Resolve attachment IDs by matching filenames to attachment list.

    Args:
        media_items: List of MediaInfo objects
        attachments: List of attachment dicts from page

    Returns:
        Updated media_items with resolved attachment_ids
    """
    # Create filename → attachment mapping
    filename_to_attachment = {}
    for att in attachments:
        filename = att.get("filename")
        if filename:
            filename_to_attachment[filename] = att

    # Update media items
    for media in media_items:
        if media.filename and not media.attachment_id:
            matching_attachment = filename_to_attachment.get(media.filename)
            if matching_attachment:
                media.attachment_id = matching_attachment.get("id")
                if not media.download_url:
                    media.download_url = matching_attachment.get(
                        "download_url"
                    )

    return media_items
