from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Optional


class Attachment(BaseModel):
    id: str
    filename: Optional[str] = None
    media_type: Optional[str] = None
    file_size: Optional[int] = None
    download_url: Optional[str] = None  # absolute URL


class Page(BaseModel):
    id: str
    title: str
    space_key: Optional[str] = None
    space_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None  # from version.createdAt
    version: Optional[int] = None
    body_html: Optional[str] = None  # from v2 body (storage|adf)
    url: Optional[str] = None  # _links.webui full URL
    attachments: List[Attachment] = []
    metadata: Dict = {}
