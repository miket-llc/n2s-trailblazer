"""Content hashing utilities for traceability."""

import hashlib
import json
from typing import Any


def compute_content_sha256(body_adf: dict[str, Any] | None, body_storage: str | None) -> str | None:
    """
    Compute SHA256 hash of page content for deduplication.

    Prefers ADF if available, falls back to Storage format.

    Args:
        body_adf: ADF content structure
        body_storage: Storage format HTML

    Returns:
        SHA256 hex string or None if no content
    """
    content = None

    if body_adf:
        # Normalize ADF JSON for consistent hashing
        content = json.dumps(body_adf, sort_keys=True, separators=(",", ":"))
    elif body_storage:
        # Use storage HTML directly
        content = body_storage

    if content:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    return None
