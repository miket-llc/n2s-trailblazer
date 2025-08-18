from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, NamedTuple, Optional, Tuple

try:
    import tiktoken  # type: ignore
except ImportError:
    tiktoken = None  # type: ignore

try:
    from ....obs.events import emit_event  # type: ignore
except ImportError:
    # Fallback for testing - create a no-op function
    def emit_event(*args, **kwargs):  # type: ignore
        pass


class ChunkType(Enum):
    """Types of content chunks for specialized handling."""

    TEXT = "text"
    CODE = "code"
    TABLE = "table"
    MACRO = "macro"
    DIGEST = "digest"


class Chunk(NamedTuple):
    """A text chunk with metadata."""

    chunk_id: str
    text_md: str
    char_count: int
    token_count: int
    ord: int
    chunk_type: str = ChunkType.TEXT.value
    meta: Optional[Dict] = None


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


def count_tokens(text: str, model: str = "text-embedding-3-small") -> int:
    """Count tokens using tiktoken for accurate OpenAI token counting."""
    if tiktoken is None:
        # Fallback to rough estimation: 4 chars per token
        return len(text) // 4  # type: ignore[unreachable]

    try:
        encoding = tiktoken.encoding_for_model(model)  # type: ignore[attr-defined]
        return len(encoding.encode(text))
    except Exception:
        # Fallback if model not found
        encoding = tiktoken.get_encoding("cl100k_base")  # type: ignore[attr-defined]
        return len(encoding.encode(text))


def detect_content_type(text: str) -> Tuple[ChunkType, Dict]:
    """Detect content type and extract metadata."""
    text_stripped = text.strip()

    # Tables (markdown or HTML) - check before code blocks
    table_patterns = [
        r"\|.*\|.*\|",  # Markdown table with pipes
        r"<table[\s\S]*?</table>",  # HTML table
    ]

    for pattern in table_patterns:
        if re.search(pattern, text_stripped, re.IGNORECASE):
            # Count rows/columns
            table_rows = len(re.findall(r"\|.*\|", text_stripped))
            return ChunkType.TABLE, {"estimated_rows": table_rows}

    # Detect structured data that looks like tables (common in AWS/config data)
    # Look for patterns like repeated column headers followed by data rows
    lines = text_stripped.split("\n")
    if len(lines) > 10:  # Must have enough lines to be a data table
        # Check for repeated patterns that indicate tabular data
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        if len(non_empty_lines) > 20:  # Lots of data rows
            # Look for consistent field patterns (like AWS config dumps)
            field_counts: Dict[str, int] = {}
            for line in non_empty_lines[:50]:  # Sample first 50 lines
                if len(line.split()) == 1 and not line.startswith(
                    "#"
                ):  # Single field per line
                    field_counts[line] = field_counts.get(line, 0) + 1

            # If we see repeated field names, this is likely structured data
            repeated_fields = [
                field for field, count in field_counts.items() if count > 2
            ]
            if len(repeated_fields) > 3:  # Multiple repeated field patterns
                return ChunkType.TABLE, {
                    "estimated_rows": len(non_empty_lines),
                    "data_format": "structured",
                }

    # Code blocks - check after tables to avoid false positives
    if re.search(r"^```\w*\n[\s\S]*?^```$", text_stripped, re.MULTILINE):
        # Extract language if present
        match = re.search(r"^```(\w+)", text_stripped, re.MULTILINE)
        language = match.group(1) if match else "unknown"
        return ChunkType.CODE, {"language": language}

    # Confluence macros and boilerplate
    macro_patterns = [
        r"\{[^}]+\}",  # {macro-name}
        r"<ac:[^>]+[/>]",  # <ac:structured-macro>
        r"\[\w+:[^\]]+\]",  # [info:text]
        r"<!-- .* -->",  # HTML comments
    ]

    macro_count = sum(
        len(re.findall(pattern, text_stripped, re.IGNORECASE))
        for pattern in macro_patterns
    )
    if macro_count > 3:  # Threshold for macro-heavy content
        return ChunkType.MACRO, {"macro_count": macro_count}

    return ChunkType.TEXT, {}


def create_table_digest(text: str, max_rows: int = 5) -> str:
    """Create a digest of a large table showing schema + sample rows."""
    lines = text.split("\n")

    # Handle traditional markdown tables with pipes
    table_lines = [line for line in lines if "|" in line and line.strip()]
    if table_lines:
        # Take header + separator + sample rows
        digest_lines = []
        if len(table_lines) >= 2:
            digest_lines.extend(table_lines[:2])  # header + separator

        if len(table_lines) > 2:
            sample_rows = table_lines[2 : min(2 + max_rows, len(table_lines))]
            digest_lines.extend(sample_rows)

            if len(table_lines) > 2 + max_rows:
                remaining = len(table_lines) - 2 - max_rows
                digest_lines.append(f"| ... ({remaining} more rows) ... |")

        return "\n".join(digest_lines)

    # Handle structured data (like AWS config dumps)
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    if len(non_empty_lines) > max_rows * 2:
        # For structured data, show the pattern and sample
        digest_lines = []

        # Add header showing this is structured data
        digest_lines.append("# Structured Data Table")
        digest_lines.append(f"# Total entries: {len(non_empty_lines)}")
        digest_lines.append("")

        # Show first few entries to establish pattern
        digest_lines.extend(non_empty_lines[:max_rows])
        digest_lines.append("")
        digest_lines.append(
            f"... ({len(non_empty_lines) - max_rows} more entries)"
        )

        return "\n".join(digest_lines)

    # Fallback - just truncate
    return text


def create_code_digest(text: str) -> str:
    """Create a digest of large code blocks with language + key symbols."""
    # Extract language
    match = re.search(r"^```(\w+)", text.strip(), re.MULTILINE)
    language = match.group(1) if match else "code"

    # Extract code content
    code_match = re.search(
        r"^```\w*\n([\s\S]*?)^```$", text.strip(), re.MULTILINE
    )
    if not code_match:
        return text

    code_content = code_match.group(1)

    # Extract key symbols (functions, classes, etc.)
    symbols = []

    # Function definitions
    symbols.extend(re.findall(r"def\s+(\w+)", code_content))
    symbols.extend(re.findall(r"function\s+(\w+)", code_content))

    # Class definitions
    symbols.extend(re.findall(r"class\s+(\w+)", code_content))

    # Variable assignments (top-level)
    symbols.extend(re.findall(r"^(\w+)\s*=", code_content, re.MULTILINE))

    # Limit symbols
    symbols = symbols[:10]

    digest = f"```{language}\n# Code digest\n"
    if symbols:
        digest += f"# Key symbols: {', '.join(symbols[:5])}\n"

    # Include first few lines
    code_lines = code_content.split("\n")[:3]
    digest += "\n".join(code_lines)

    if len(code_content.split("\n")) > 3:
        remaining_lines = len(code_content.split("\n")) - 3
        digest += f"\n# ... ({remaining_lines} more lines)"

    digest += "\n```"

    return digest


def _create_safe_chunk(
    doc_id: str,
    chunk_text: str,
    ord_num: int,
    max_tokens: int,
    model: str,
) -> Chunk:
    """Create a single chunk with guaranteed max_tokens compliance."""
    chunk_id = f"{doc_id}:{ord_num:04d}"
    chunk_type, chunk_meta = detect_content_type(chunk_text)

    # Always check token limit
    final_tokens = count_tokens(chunk_text, model)

    if final_tokens > max_tokens:
        # Apply digest/truncation logic
        if chunk_type == ChunkType.CODE:
            digest_text = create_code_digest(chunk_text)
            chunk_text = digest_text
            chunk_type = ChunkType.DIGEST
            chunk_meta["original_type"] = "code"
            chunk_meta["token_savings"] = final_tokens - count_tokens(
                digest_text, model
            )
            final_tokens = count_tokens(digest_text, model)
        elif chunk_type == ChunkType.TABLE:
            digest_text = create_table_digest(chunk_text)
            chunk_text = digest_text
            chunk_type = ChunkType.DIGEST
            chunk_meta["original_type"] = "table"
            chunk_meta["token_savings"] = final_tokens - count_tokens(
                digest_text, model
            )
            final_tokens = count_tokens(digest_text, model)
        else:
            # For TEXT or other types, truncate with warning
            max_chars = int(max_tokens * 3.5)  # Rough chars-to-tokens ratio
            chunk_text = (
                chunk_text[:max_chars]
                + "\n\n[Content truncated - exceeded token limit]"
            )
            final_tokens = count_tokens(chunk_text, model)
            chunk_meta["truncated"] = True
            chunk_meta["original_tokens"] = final_tokens

        # CRITICAL FIX: If we're STILL over the limit after digest/truncation, force truncate
        if final_tokens > max_tokens:
            # Binary search to find the right length
            low, high = 0, len(chunk_text)
            while low < high:
                mid = (low + high + 1) // 2
                test_text = chunk_text[:mid] + "\n[TRUNCATED]"
                test_tokens = count_tokens(test_text, model)
                if test_tokens <= max_tokens:
                    low = mid
                else:
                    high = mid - 1

            chunk_text = chunk_text[:low] + "\n[TRUNCATED]"
            final_tokens = count_tokens(chunk_text, model)
            chunk_meta["force_truncated"] = True
            chunk_meta["final_tokens"] = final_tokens

        # Emit digest event if we created one
        emit_event(
            "chunk.digest",
            source=chunk_type.value
            if isinstance(chunk_type, ChunkType)
            else chunk_type,
            token_savings=chunk_meta.get("token_savings", 0),
        )

    chunk = Chunk(
        chunk_id=chunk_id,
        text_md=chunk_text.strip(),
        char_count=len(chunk_text),
        token_count=final_tokens,
        ord=ord_num,
        chunk_type=chunk_type.value
        if isinstance(chunk_type, ChunkType)
        else chunk_type,
        meta=chunk_meta,
    )

    emit_event(
        "chunk.emit",
        chunk_id=chunk_id,
        type=chunk.chunk_type,
        token_count=final_tokens,
    )

    return chunk


def chunk_document(
    doc_id: str,
    text_md: str,
    title: str = "",
    target_tokens: int = 700,
    max_tokens: int = 8000,
    overlap_pct: float = 0.15,
    model: str = "text-embedding-3-small",
) -> List[Chunk]:
    """
    Chunk a document into token-budgeted, type-aware pieces.

    Args:
        doc_id: Document identifier
        text_md: Markdown text content
        title: Document title (prepended to first chunk)
        target_tokens: Target chunk size in tokens
        max_tokens: Maximum tokens allowed (hard limit)
        overlap_pct: Overlap percentage (0.15 = 15%)
        model: Model name for token counting

    Returns:
        List of Chunk objects with stable chunk_ids and types
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

        # Detect content type for this section
        content_type, type_meta = detect_content_type(section)

        # Handle large code blocks and tables with digests
        section_tokens = count_tokens(section, model)

        if section_tokens > max_tokens:
            # Create digest for oversized content
            if content_type == ChunkType.CODE:
                digest_text = create_code_digest(section)
                section = digest_text
                content_type = ChunkType.DIGEST
                type_meta["original_type"] = "code"
                type_meta["token_savings"] = section_tokens - count_tokens(
                    digest_text, model
                )
            elif content_type == ChunkType.TABLE:
                digest_text = create_table_digest(section)
                section = digest_text
                content_type = ChunkType.DIGEST
                type_meta["original_type"] = "table"
                type_meta["token_savings"] = section_tokens - count_tokens(
                    digest_text, model
                )

            # Emit chunk.digest event
            emit_event(
                "chunk.digest",
                source=content_type.value,
                token_savings=type_meta.get("token_savings", 0),
            )

        # Skip macro-heavy content if it's mostly boilerplate
        if content_type == ChunkType.MACRO and section_tokens > target_tokens:
            # Check if it's mostly empty after cleaning
            cleaned = re.sub(r"\{[^}]+\}|<[^>]+>|\[\w+:[^\]]+\]", "", section)
            if len(cleaned.strip()) < 50:  # Threshold for empty content
                emit_event("chunk.skip", reason="empty_after_macro_cleanup")
                continue

        # Check if adding this section would exceed token budget
        current_tokens = (
            count_tokens(current_chunk, model) if current_chunk else 0
        )
        combined_tokens = (
            count_tokens(current_chunk + "\n\n" + section, model)
            if current_chunk
            else section_tokens
        )

        if current_chunk and combined_tokens > target_tokens:
            if (
                current_tokens >= target_tokens // 4
            ):  # Minimum chunk size (25% of target)
                # Create chunk using safe function
                chunk = _create_safe_chunk(
                    doc_id, current_chunk, ord_num, max_tokens, model
                )
                chunks.append(chunk)

                ord_num += 1

                # Start new chunk with overlap (token-based)
                if overlap_pct > 0:
                    overlap_tokens = int(chunk.token_count * overlap_pct)
                    words = current_chunk.split()
                    # Estimate words needed for overlap tokens
                    overlap_words = min(
                        len(words), max(1, int(overlap_tokens // 1.3))
                    )  # ~1.3 tokens per word
                    overlap_text = " ".join(words[-overlap_words:])
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
        # For very large final chunks, split them up
        if (
            count_tokens(current_chunk, model) > max_tokens * 2
        ):  # Much larger than limit
            # Split into sections and create multiple chunks
            text_sections = current_chunk.split("\n\n")
            for section in text_sections:
                section = section.strip()
                if not section:
                    continue

                chunk = _create_safe_chunk(
                    doc_id, section, ord_num, max_tokens, model
                )
                chunks.append(chunk)
                ord_num += 1
        else:
            # Normal final chunk - use safe function
            chunk = _create_safe_chunk(
                doc_id, current_chunk, ord_num, max_tokens, model
            )
            chunks.append(chunk)

    return chunks


def inject_media_placeholders(text_md: str, attachments: List[Dict]) -> str:
    """
    Inject media placeholders for attachments to make them chunk-addressable.

    Args:
        text_md: Original markdown text
        attachments: List of attachment objects with 'filename' field

    Returns:
        Text with ![media: <filename>] placeholders injected
    """
    if not attachments:
        return text_md

    # Add media placeholders at the end if they aren't already referenced
    media_section_lines = []
    for attachment in attachments:
        filename = attachment.get("filename", "")
        if filename:
            placeholder = f"![media: {filename}]"
            # Only add if not already present in text
            if placeholder not in text_md:
                media_section_lines.append(placeholder)

    if media_section_lines:
        if text_md.strip():
            return f"{text_md}\n\n## Media\n\n" + "\n".join(
                media_section_lines
            )
        else:
            return "## Media\n\n" + "\n".join(media_section_lines)

    return text_md


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
    attachments = record.get("attachments", [])

    if not doc_id:
        raise ValueError("Record missing required 'id' field")

    # Inject media placeholders to make media chunk-addressable
    text_with_media = inject_media_placeholders(text_md, attachments)

    return chunk_document(doc_id, text_with_media, title)


def chunk_document_with_hints(
    doc_id: str,
    text_md: str,
    title: str = "",
    max_tokens: int = 800,
    min_tokens: int = 120,
    prefer_headings: bool = True,
    soft_boundaries: Optional[List[int]] = None,
    section_map: Optional[List[Dict]] = None,
    model: str = "text-embedding-3-small",
) -> List[Chunk]:
    """
    Chunk a document using enrichment hints for heading-aware, token-bounded splits.

    Args:
        doc_id: Document identifier
        text_md: Markdown text content
        title: Document title (prepended to first chunk)
        max_tokens: Maximum tokens allowed (hard limit)
        min_tokens: Minimum tokens preferred for chunks
        prefer_headings: Whether to prefer heading-aligned splits
        soft_boundaries: Character positions that are good split points
        section_map: List of heading sections with positions
        model: Model name for token counting

    Returns:
        List of Chunk objects with heading-aware splitting
    """
    if soft_boundaries is None:
        soft_boundaries = []
    if section_map is None:
        section_map = []

    # Normalize and prepare text
    full_text = normalize_text(text_md)
    if title and title.strip():
        if full_text.strip():
            full_text = f"# {title.strip()}\n\n{full_text}"
        else:
            full_text = f"# {title.strip()}"

    if not full_text.strip():
        return []

    if prefer_headings and section_map:
        # Use section-aware chunking
        chunks = _chunk_by_sections(
            doc_id, full_text, section_map, max_tokens, min_tokens, model
        )
    else:
        # Fall back to soft boundary chunking
        chunks = _chunk_by_soft_boundaries(
            doc_id, full_text, soft_boundaries, max_tokens, min_tokens, model
        )

    return chunks


def _chunk_by_sections(
    doc_id: str,
    text: str,
    section_map: List[Dict],
    max_tokens: int,
    min_tokens: int,
    model: str,
) -> List[Chunk]:
    """Chunk by sections, respecting heading boundaries."""
    chunks: List[Chunk] = []
    current_chunk = ""
    ord_num = 0

    # Sort sections by start position
    sorted_sections = sorted(section_map, key=lambda s: s.get("startChar", 0))

    if not sorted_sections:
        # No sections found, fall back to paragraph splitting
        return _chunk_by_paragraphs(
            doc_id, text, max_tokens, min_tokens, model
        )

    # Process text section by section
    last_pos = 0

    for section in sorted_sections:
        start_char = section.get("startChar", 0)

        # Add any text before this section to current chunk
        if start_char > last_pos:
            before_section = text[last_pos:start_char].strip()
            if before_section:
                current_chunk += before_section + "\n"

        # Check if adding this section would exceed max tokens
        section_text = text[
            start_char : section.get("endChar", len(text))
        ].strip()
        combined_text = current_chunk + section_text
        combined_tokens = count_tokens(combined_text, model)

        if combined_tokens > max_tokens and current_chunk.strip():
            # Emit current chunk and start new one with this section
            if count_tokens(current_chunk, model) >= min_tokens or not chunks:
                chunk = _create_safe_chunk(
                    doc_id, current_chunk.strip(), ord_num, max_tokens, model
                )
                chunks.append(chunk)
                ord_num += 1

            current_chunk = section_text + "\n"
        else:
            # Add section to current chunk
            current_chunk += section_text + "\n"

        last_pos = section.get("endChar", start_char + len(section_text))

    # Add any remaining text
    if last_pos < len(text):
        remaining = text[last_pos:].strip()
        if remaining:
            current_chunk += remaining

    # Emit final chunk
    if current_chunk.strip():
        chunk = _create_safe_chunk(
            doc_id, current_chunk.strip(), ord_num, max_tokens, model
        )
        chunks.append(chunk)

    return chunks


def _chunk_by_soft_boundaries(
    doc_id: str,
    text: str,
    soft_boundaries: List[int],
    max_tokens: int,
    min_tokens: int,
    model: str,
) -> List[Chunk]:
    """Chunk using soft boundaries as preferred split points."""
    if not soft_boundaries:
        return _chunk_by_paragraphs(
            doc_id, text, max_tokens, min_tokens, model
        )

    chunks: List[Chunk] = []
    current_chunk = ""
    ord_num = 0
    last_pos = 0

    # Sort boundaries
    sorted_boundaries = sorted(set(soft_boundaries))

    for boundary in sorted_boundaries:
        if boundary > len(text):
            continue

        # Get text up to this boundary
        segment = text[last_pos:boundary].strip()
        if not segment:
            continue

        # Check if adding this segment would exceed max tokens
        combined_text = (
            current_chunk + "\n" + segment if current_chunk else segment
        )
        combined_tokens = count_tokens(combined_text, model)

        if combined_tokens > max_tokens and current_chunk.strip():
            # Emit current chunk and start new one
            if count_tokens(current_chunk, model) >= min_tokens or not chunks:
                chunk = _create_safe_chunk(
                    doc_id, current_chunk.strip(), ord_num, max_tokens, model
                )
                chunks.append(chunk)
                ord_num += 1

            current_chunk = segment
        else:
            # Add segment to current chunk
            current_chunk = combined_text

        last_pos = boundary

    # Add any remaining text
    if last_pos < len(text):
        remaining = text[last_pos:].strip()
        if remaining:
            combined_text = (
                current_chunk + "\n" + remaining
                if current_chunk
                else remaining
            )
            current_chunk = combined_text

    # Emit final chunk
    if current_chunk.strip():
        chunk = _create_safe_chunk(
            doc_id, current_chunk.strip(), ord_num, max_tokens, model
        )
        chunks.append(chunk)

    return chunks


def _chunk_by_paragraphs(
    doc_id: str, text: str, max_tokens: int, min_tokens: int, model: str
) -> List[Chunk]:
    """Fallback chunking by paragraphs and headings."""
    sections = split_on_paragraphs_and_headings(text)
    chunks: List[Chunk] = []
    current_chunk = ""
    ord_num = 0

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Check if adding this section would exceed token budget
        current_tokens = (
            count_tokens(current_chunk, model) if current_chunk else 0
        )
        combined_tokens = (
            count_tokens(current_chunk + "\n" + section, model)
            if current_chunk
            else count_tokens(section, model)
        )

        if combined_tokens > max_tokens and current_chunk.strip():
            # Emit current chunk and start new one
            if current_tokens >= min_tokens or not chunks:
                chunk = _create_safe_chunk(
                    doc_id, current_chunk.strip(), ord_num, max_tokens, model
                )
                chunks.append(chunk)
                ord_num += 1

            current_chunk = section
        else:
            # Add section to current chunk
            current_chunk = (
                current_chunk + "\n" + section if current_chunk else section
            )

    # Emit final chunk
    if current_chunk.strip():
        chunk = _create_safe_chunk(
            doc_id, current_chunk.strip(), ord_num, max_tokens, model
        )
        chunks.append(chunk)

    return chunks


def chunk_enriched_record(record: Dict) -> List[Chunk]:
    """
    Chunk an enriched record from the enrich phase.

    This version respects chunk_hints and section_map for heading-aligned splits.

    Args:
        record: Enriched record with id, title, text_md fields plus enrichment data

    Returns:
        List of Chunk objects with heading-aware splitting
    """
    doc_id = record.get("id", "")
    title = record.get("title", "")
    text_md = record.get("text_md", "")
    attachments = record.get("attachments", [])

    # Get enrichment data
    chunk_hints = record.get("chunk_hints", {})
    section_map = record.get("section_map", [])

    if not doc_id:
        raise ValueError("Record missing required 'id' field")

    # Extract chunk parameters from hints
    max_tokens = chunk_hints.get("maxTokens", 800)
    min_tokens = chunk_hints.get("minTokens", 120)
    prefer_headings = chunk_hints.get("preferHeadings", True)
    soft_boundaries = chunk_hints.get("softBoundaries", [])

    # Inject media placeholders to make media chunk-addressable
    text_with_media = inject_media_placeholders(text_md, attachments)

    return chunk_document_with_hints(
        doc_id=doc_id,
        text_md=text_with_media,
        title=title,
        max_tokens=max_tokens,
        min_tokens=min_tokens,
        prefer_headings=prefer_headings,
        soft_boundaries=soft_boundaries,
        section_map=section_map,
    )
