from __future__ import annotations

import re
from typing import Dict, List, NamedTuple


class Chunk(NamedTuple):
    """A text chunk with metadata."""

    chunk_id: str
    text_md: str
    char_count: int
    token_count: int
    ord: int


def normalize_text(text: str) -> str:
    """Normalize text for consistent chunking."""
    # Normalize line endings CRLF -> LF
    text = re.sub(r"\r\n?", "\n", text)
    # Remove any triple+ blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_on_paragraphs_and_headings(text: str) -> List[str]:
    """Split text into paragraphs and headings while preserving code blocks."""
    # Normalize text first
    text = normalize_text(text)

    # Pattern to match fenced code blocks (``` or ~~~ with optional language)
    code_block_pattern = r"^(```|~~~).*?^\1"

    # Find all code blocks to preserve them
    code_blocks: List[str] = []
    code_placeholder = "___CODE_BLOCK_{}___"

    # Replace code blocks with placeholders
    def replace_code_block(match):
        idx = len(code_blocks)
        code_blocks.append(match.group(0))
        return code_placeholder.format(idx)

    text_with_placeholders = re.sub(
        code_block_pattern,
        replace_code_block,
        text,
        flags=re.MULTILINE | re.DOTALL,
    )

    # Split on double newlines (paragraph breaks) and headings
    parts = []
    current_part: List[str] = []

    for line in text_with_placeholders.split("\n"):
        # Check if line is a heading (starts with #)
        if re.match(r"^#+\s", line):
            # Finish current part if it has content
            if current_part:
                parts.append("\n".join(current_part).strip())
                current_part = []
            # Start new part with heading
            current_part = [line]
        elif line.strip() == "":
            # Empty line - check if we should break here
            if current_part:
                current_part.append(line)
                # If we have multiple empty lines, break the part
                if len(current_part) >= 2 and current_part[-2].strip() == "":
                    parts.append("\n".join(current_part[:-1]).strip())
                    current_part = []
        else:
            current_part.append(line)

    # Add final part
    if current_part:
        parts.append("\n".join(current_part).strip())

    # Restore code blocks in all parts
    restored_parts = []
    for part in parts:
        if part:
            for i, code_block in enumerate(code_blocks):
                part = part.replace(code_placeholder.format(i), code_block)
            restored_parts.append(part)

    return [p for p in restored_parts if p.strip()]


def chunk_document(
    doc_id: str,
    text_md: str,
    title: str = "",
    target_min: int = 800,
    target_max: int = 1200,
    overlap_pct: float = 0.15,
) -> List[Chunk]:
    """
    Chunk a document into overlapping pieces.

    Args:
        doc_id: Document identifier
        text_md: Markdown text content
        title: Document title (prepended to first chunk)
        target_min: Minimum chunk size in characters
        target_max: Maximum chunk size in characters
        overlap_pct: Overlap percentage (0.15 = 15%)

    Returns:
        List of Chunk objects with stable chunk_ids
    """
    # Normalize and prepare text
    full_text = normalize_text(text_md)
    if title and title.strip():
        if full_text.strip():
            full_text = f"# {title.strip()}\n\n{full_text}"
        else:
            full_text = f"# {title.strip()}"

    if not full_text.strip():
        return []

    # Split into logical paragraphs/sections
    sections = split_on_paragraphs_and_headings(full_text)

    chunks = []
    current_chunk = ""
    ord_num = 0

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # If adding this section would exceed target_max, finalize current chunk
        if (
            current_chunk
            and len(current_chunk) + len(section) + 2 > target_max
        ):
            if len(current_chunk) >= target_min:
                # Create chunk
                chunk_id = f"{doc_id}:{ord_num:04d}"
                token_count = len(current_chunk.split())
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        text_md=current_chunk.strip(),
                        char_count=len(current_chunk),
                        token_count=token_count,
                        ord=ord_num,
                    )
                )
                ord_num += 1

                # Start new chunk with overlap
                overlap_chars = int(len(current_chunk) * overlap_pct)
                if overlap_chars > 0:
                    # Take last N characters for overlap, try to break at word boundary
                    overlap_text = current_chunk[-overlap_chars:]
                    # Find last space for cleaner break
                    last_space = overlap_text.rfind(" ")
                    if last_space > overlap_chars // 2:
                        overlap_text = overlap_text[last_space + 1 :]
                    current_chunk = overlap_text + "\n\n" + section
                else:
                    current_chunk = section
            else:
                # Current chunk is too small, just add the section
                current_chunk += "\n\n" + section
        else:
            # Add section to current chunk
            if current_chunk:
                current_chunk += "\n\n" + section
            else:
                current_chunk = section

    # Add final chunk if it has content
    if current_chunk.strip():
        chunk_id = f"{doc_id}:{ord_num:04d}"
        token_count = len(current_chunk.split())
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                text_md=current_chunk.strip(),
                char_count=len(current_chunk),
                token_count=token_count,
                ord=ord_num,
            )
        )

    return chunks


def chunk_normalized_record(record: Dict) -> List[Chunk]:
    """
    Chunk a normalized record from the normalize phase.

    Args:
        record: Normalized record with id, title, text_md fields

    Returns:
        List of Chunk objects
    """
    doc_id = record.get("id", "")
    title = record.get("title", "")
    text_md = record.get("text_md", "")

    if not doc_id:
        raise ValueError("Record missing required 'id' field")

    return chunk_document(doc_id, text_md, title)
