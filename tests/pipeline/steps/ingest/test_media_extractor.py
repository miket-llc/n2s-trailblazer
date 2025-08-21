"""Tests for media extraction from ADF and Storage formats."""

import pytest
from trailblazer.pipeline.steps.ingest.media_extractor import (
    extract_media_from_adf,
    extract_media_from_storage,
    resolve_attachment_ids,
)

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


class TestMediaExtractionFromAdf:
    """Test media extraction from ADF format."""

    def test_extract_media_single_with_mediasingle(self):
        """Test extracting a single media item from mediaSingle node."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "mediaSingle",
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                "id": "media123",
                                "type": "file",
                                "collection": "contentId-123",
                                "url": "/download/attachments/123/image.png",
                                "alt": "Test image",
                                "width": 400,
                                "height": 300,
                            },
                        }
                    ],
                }
            ],
        }

        media_items = extract_media_from_adf(adf)

        assert len(media_items) == 1
        media = media_items[0]
        assert media.order == 0
        assert media.media_type == "image"
        assert media.filename == "image.png"
        assert media.attachment_id == "media123"
        assert media.download_url == "/download/attachments/123/image.png"
        assert media.context["adf_path"] == "0"
        assert media.context["alt"] == "Test image"

    def test_extract_media_multiple_in_order(self):
        """Test extracting multiple media items in document order."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "First paragraph"}],
                },
                {
                    "type": "mediaSingle",
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                "id": "media1",
                                "url": "/download/first.jpg",
                            },
                        }
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Second paragraph"}],
                },
                {
                    "type": "mediaSingle",
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                "id": "media2",
                                "url": "/download/second.pdf",
                            },
                        }
                    ],
                },
            ],
        }

        media_items = extract_media_from_adf(adf)

        assert len(media_items) == 2
        assert media_items[0].order == 0
        assert media_items[0].filename == "first.jpg"
        assert media_items[1].order == 1
        assert media_items[1].filename == "second.pdf"

    def test_extract_media_empty_adf(self):
        """Test handling empty or missing ADF."""
        assert extract_media_from_adf(None) == []
        assert extract_media_from_adf({}) == []
        assert extract_media_from_adf({"type": "doc", "content": []}) == []


class TestMediaExtractionFromStorage:
    """Test media extraction from Storage format."""

    def test_extract_ac_image_with_attachment(self):
        """Test extracting ac:image with ri:attachment."""
        storage_html = """
        <p>Some text</p>
        <ac:image ac:width="300" ac:height="200" ac:alt="Test image">
            <ri:attachment ri:filename="screenshot.png" ri:content-id="att123"/>
        </ac:image>
        <p>More text</p>
        """

        media_items = extract_media_from_storage(storage_html)

        assert len(media_items) == 1
        media = media_items[0]
        assert media.order == 0
        assert media.media_type == "image"
        assert media.filename == "screenshot.png"
        assert media.attachment_id == "att123"
        assert media.context["alt"] == "Test image"
        assert media.context["width"] == "300"
        assert media.context["height"] == "200"

    def test_extract_standard_img_tag(self):
        """Test extracting standard HTML img tags."""
        storage_html = """
        <p>Check out this image:</p>
        <img src="/download/attachments/123/photo.jpg" alt="Photo" width="400"/>
        """

        media_items = extract_media_from_storage(storage_html)

        assert len(media_items) == 1
        media = media_items[0]
        assert media.order == 0
        assert media.media_type == "image"
        assert media.filename == "photo.jpg"
        assert media.download_url == "/download/attachments/123/photo.jpg"
        assert media.context["alt"] == "Photo"
        assert media.context["width"] == "400"

    def test_extract_ri_attachment_direct(self):
        """Test extracting direct ri:attachment references."""
        storage_html = """
        <p>Download this file:</p>
        <ri:attachment ri:filename="document.pdf" ri:content-id="doc456"/>
        """

        media_items = extract_media_from_storage(storage_html)

        assert len(media_items) == 1
        media = media_items[0]
        assert media.order == 0
        assert media.media_type == "file"  # PDF is classified as file
        assert media.filename == "document.pdf"
        assert media.attachment_id == "doc456"

    def test_extract_empty_storage(self):
        """Test handling empty or missing storage content."""
        assert extract_media_from_storage(None) == []
        assert extract_media_from_storage("") == []
        assert extract_media_from_storage("<p>No media here</p>") == []


class TestAttachmentIdResolution:
    """Test resolving attachment IDs by filename matching."""

    def test_resolve_attachment_ids_by_filename(self):
        """Test resolving attachment IDs when filenames match."""
        media_items = [
            extract_media_from_storage('<img src="/path/image1.jpg"/>')[0],
            extract_media_from_storage('<img src="/path/image2.png"/>')[0],
        ]

        # Mock attachment list
        attachments = [
            {
                "id": "att1",
                "filename": "image1.jpg",
                "download_url": "/download/att1",
            },
            {
                "id": "att2",
                "filename": "image2.png",
                "download_url": "/download/att2",
            },
            {
                "id": "att3",
                "filename": "other.pdf",
                "download_url": "/download/att3",
            },
        ]

        resolved_media = resolve_attachment_ids(media_items, attachments)

        assert len(resolved_media) == 2
        assert resolved_media[0].attachment_id == "att1"
        assert (
            resolved_media[0].download_url == "/path/image1.jpg"
        )  # Original URL preserved
        assert resolved_media[1].attachment_id == "att2"
        assert (
            resolved_media[1].download_url == "/path/image2.png"
        )  # Original URL preserved

    def test_resolve_no_matches(self):
        """Test when no filenames match."""
        media_items = [
            extract_media_from_storage('<img src="/path/nomatch.jpg"/>')[0]
        ]

        attachments = [
            {
                "id": "att1",
                "filename": "different.png",
                "download_url": "/download/att1",
            }
        ]

        resolved_media = resolve_attachment_ids(media_items, attachments)

        assert len(resolved_media) == 1
        assert resolved_media[0].attachment_id is None
        assert (
            resolved_media[0].download_url == "/path/nomatch.jpg"
        )  # Original URL preserved

    def test_resolve_empty_lists(self):
        """Test handling empty media or attachment lists."""
        assert resolve_attachment_ids([], []) == []

        media_items = [
            extract_media_from_storage('<img src="/path/image.jpg"/>')[0]
        ]
        assert resolve_attachment_ids(media_items, []) == media_items
        assert resolve_attachment_ids([], [{"id": "att1"}]) == []
