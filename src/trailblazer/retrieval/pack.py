"""Context packing utilities for retrieval results."""

from __future__ import annotations

import re
from typing import Dict, List, Any


def group_by_doc(
    hits: List[Dict[str, Any]], max_chunks_per_doc: int
) -> List[Dict[str, Any]]:
    """
    Group hits by document and limit chunks per document.

    Args:
        hits: List of hit dictionaries with doc_id, chunk_id, score, etc.
        max_chunks_per_doc: Maximum number of chunks to include per document

    Returns:
        List of hits grouped and limited by document, maintaining score order
    """
    if not hits:
        return []

    # Track seen docs and their counts
    doc_counts: Dict[str, int] = {}
    result = []

    # Process hits in original order, limiting per doc
    for hit in hits:
        doc_id = hit["doc_id"]
        current_count = doc_counts.get(doc_id, 0)

        if current_count < max_chunks_per_doc:
            result.append(hit)
            doc_counts[doc_id] = current_count + 1

    return result


def _is_inside_code_block(text: str, position: int) -> bool:
    """
    Check if a position is inside a fenced code block.

    Args:
        text: The text to check
        position: Character position to check

    Returns:
        True if position is inside a code block
    """
    # Find all code block boundaries (```...```)
    code_block_pattern = r"```.*?```"

    for match in re.finditer(code_block_pattern, text, re.DOTALL):
        start, end = match.span()
        if start <= position <= end:
            return True

    return False


def pack_context(hits: List[Dict[str, Any]], max_chars: int = 6000) -> str:
    """
    Pack hit results into a context string respecting character budget.

    Args:
        hits: List of hit dictionaries with text_md, title, url, score, etc.
        max_chars: Maximum character budget for the context

    Returns:
        Packed context string with separators and metadata
    """
    if not hits:
        return ""

    context_parts: List[str] = []
    current_chars = 0

    for i, hit in enumerate(hits):
        text_md = hit.get("text_md", "")
        title = hit.get("title", "")
        url = hit.get("url", "")
        score = hit.get("score", 0.0)

        # Create separator with metadata
        separator = f"\n\n--- Chunk {i + 1} (score: {score:.3f}) ---\n"
        if title:
            separator += f"Title: {title}\n"
        if url:
            separator += f"URL: {url}\n"
        separator += "\n"

        # Calculate space needed for this chunk
        chunk_content = separator + text_md
        chunk_chars = len(chunk_content)

        # Check if adding this chunk would exceed budget
        if current_chars + chunk_chars > max_chars:
            # If we have no context yet, try to fit at least some of this chunk
            if not context_parts:
                remaining_budget = max_chars
            else:
                remaining_budget = max_chars - current_chars

            # Try to find a safe truncation point outside code blocks
            if (
                remaining_budget > len(separator) + 50
            ):  # Minimum useful content
                # Add separator first
                safe_separator = separator
                remaining_after_sep = remaining_budget - len(separator)

                # Find safe truncation point in text
                truncated_text = text_md[:remaining_after_sep]

                # Don't truncate inside code blocks
                for pos in range(len(truncated_text) - 1, -1, -1):
                    if not _is_inside_code_block(text_md, pos):
                        truncated_text = text_md[:pos]
                        break

                # Add truncated content if meaningful
                if len(truncated_text.strip()) > 20:
                    context_parts.append(
                        safe_separator + truncated_text + "\n[... truncated]"
                    )

            break

        # Add the full chunk
        context_parts.append(chunk_content)
        current_chars += chunk_chars

    return "".join(context_parts)


def create_context_summary(
    query: str,
    hits: List[Dict[str, Any]],
    provider: str,
    timing_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a summary dictionary for the retrieval results.

    Args:
        query: Original query string
        hits: List of retrieval hits
        provider: Embedding provider used
        timing_info: Dictionary with timing information

    Returns:
        Summary dictionary with metadata and statistics
    """
    # Group by document to get unique docs
    doc_ids = set(hit["doc_id"] for hit in hits)

    # Calculate basic statistics
    total_chars = sum(len(hit.get("text_md", "")) for hit in hits)
    scores = [hit.get("score", 0.0) for hit in hits]

    summary = {
        "query": query,
        "provider": provider,
        "total_hits": len(hits),
        "unique_documents": len(doc_ids),
        "total_characters": total_chars,
        "score_stats": {
            "min": min(scores) if scores else 0.0,
            "max": max(scores) if scores else 0.0,
            "avg": sum(scores) / len(scores) if scores else 0.0,
        },
        "timing": timing_info,
    }

    return summary
