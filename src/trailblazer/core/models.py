from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Optional, Any


class Attachment(BaseModel):
    id: str
    filename: Optional[str] = None
    media_type: Optional[str] = None
    file_size: Optional[int] = None
    download_url: Optional[str] = None  # absolute URL
    sha256: Optional[str] = None  # file hash if computed
    width: Optional[int] = None  # image dimensions if available
    height: Optional[int] = None


class ConfluenceUser(BaseModel):
    account_id: str
    display_name: Optional[str] = None


class PageAncestor(BaseModel):
    id: str
    title: str
    url: Optional[str] = None


class Page(BaseModel):
    id: str
    title: str
    space_key: Optional[str] = None
    space_id: Optional[str] = None
    space_name: Optional[str] = None  # space display name
    space_type: Optional[str] = None  # personal, team, etc.
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None  # from version.createdAt
    version: Optional[int] = None
    body_html: Optional[str] = None  # from v2 body (storage|adf)
    url: Optional[str] = None  # _links.webui full URL
    attachments: List[Attachment] = []
    source_system: str = "confluence"  # traceability field

    # Enhanced traceability fields
    created_by: Optional[ConfluenceUser] = None
    updated_by: Optional[ConfluenceUser] = None
    labels: List[str] = []  # Confluence labels
    ancestors: List[PageAncestor] = []  # ordered root→parent
    content_sha256: Optional[str] = None  # content hash
    attachment_count: int = 0
    label_count: int = 0
    ancestor_count: int = 0

    metadata: Dict[str, Any] = {}
