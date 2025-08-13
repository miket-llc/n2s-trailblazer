from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Optional


class Page(BaseModel):
    id: str
    title: str
    space: Optional[str] = None
    space_id: Optional[str] = None
    version: int
    body_html: Optional[str] = None
    last_modified: Optional[datetime] = None
    attachments: List[str] = []
    url: Optional[str] = None
    metadata: Dict = {}
