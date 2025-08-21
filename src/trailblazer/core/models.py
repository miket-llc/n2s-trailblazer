from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Attachment(BaseModel):
    id: str
    filename: str | None = None
    media_type: str | None = None
    file_size: int | None = None
    download_url: str | None = None  # absolute URL
    sha256: str | None = None  # file hash if computed
    width: int | None = None  # image dimensions if available
    height: int | None = None


class ConfluenceUser(BaseModel):
    account_id: str
    display_name: str | None = None


class PageAncestor(BaseModel):
    id: str
    title: str
    url: str | None = None


class Page(BaseModel):
    id: str
    title: str
    space_key: str | None = None
    space_id: str | None = None
    space_name: str | None = None  # space display name
    space_type: str | None = None  # personal, team, etc.
    created_at: datetime | None = None
    updated_at: datetime | None = None  # from version.createdAt
    version: int | None = None
    body_html: str | None = None  # from v2 body (storage|adf)
    url: str | None = None  # _links.webui full URL
    attachments: list[Attachment] = []
    source_system: str = "confluence"  # traceability field

    # Enhanced traceability fields
    created_by: ConfluenceUser | None = None
    updated_by: ConfluenceUser | None = None
    labels: list[str] = []  # Confluence labels
    ancestors: list[PageAncestor] = []  # ordered root→parent
    content_sha256: str | None = None  # content hash
    attachment_count: int = 0
    label_count: int = 0
    ancestor_count: int = 0

    metadata: dict[str, Any] = {}
