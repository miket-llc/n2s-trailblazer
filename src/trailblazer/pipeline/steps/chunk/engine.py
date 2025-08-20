"""
Main chunking engine with layered splitting strategy and hard token caps.
"""

from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Tuple

try:
    import tiktoken  # type: ignore
except ImportError:
    tiktoken = None  # type: ignore

try:
    from ...obs.events import emit_event  # type: ignore
except ImportError:
    # Fallback for testing - create a no-op function
    def emit_event(*args, **kwargs):  # type: ignore
        pass


from .boundaries import (
    split_by_headings,
    split_by_paragraphs,
    split_by_sentences,
    split_code_fence_by_lines,
    split_table_by_rows,
    split_by_token_window,
    detect_content_type,
    normalize_text,
    count_tokens,
    ChunkType,
)


class Chunk(NamedTuple):
    """A text chunk with complete traceability metadata."""

    chunk_id: str
    text_md: str
    char_count: int
    token_count: int
    ord: int
    chunk_type: str = ChunkType.TEXT.value
    meta: Optional[Dict] = None
    split_strategy: str = "paragraph"

    # Character spans for coverage tracking (v2.2)
    char_start: int = 0
    char_end: int = 0
    token_start: int = 0
    token_end: int = 0

    # Required traceability fields per spec
    doc_id: str = ""
    title: str = ""
    url: str = ""
    source_system: str = ""
    labels: List[str] = []
    space: Optional[Dict] = None
    media_refs: List[Dict] = []


def split_with_layered_strategy(
    text: str,
    hard_max_tokens: int,
    overlap_tokens: int,
    min_tokens: int,
    model: str,
    section_map: Optional[List[Dict]] = None,
    prefer_headings: bool = True,
) -> List[Tuple[str, str, int, int]]:
    """
    Split text using layered strategy with hard token cap guarantee.

    Strategy order:
    1. Headings using section_map if available
    2. Paragraph/list boundaries
    3. Sentence boundaries
    4. Code fence line blocks (for code)
    5. Table row groups (for tables)
    6. Token window fallback

    Args:
        text: Text to split
        hard_max_tokens: Absolute ceiling for tokens
        overlap_tokens: Tokens to overlap when splitting
        min_tokens: Minimum preferred tokens (can go down to 80 when forced)
        model: Model for token counting
        section_map: Optional section map from enrichment
        prefer_headings: Whether to prefer heading-aligned splits

    Returns:
        List of (chunk_text, split_strategy, char_start, char_end) tuples
    """
    if count_tokens(text, model) <= hard_max_tokens:
        return [(text, "no-split", 0, len(text))]

    # Detect content type first
    content_type, _ = detect_content_type(text)

    # Strategy 1: Headings using section_map
    if prefer_headings and section_map:
        try:
            chunks = []
            sorted_sections = sorted(
                section_map, key=lambda s: s.get("startChar", 0)
            )
            last_pos = 0

            for section in sorted_sections:
                start_char = section.get("startChar", 0)
                end_char = section.get("endChar", len(text))

                # Get section text
                section_text = text[start_char:end_char].strip()
                if not section_text:
                    continue

                # If section fits within cap, use it
                if count_tokens(section_text, model) <= hard_max_tokens:
                    chunks.append(
                        (section_text, "heading", start_char, end_char)
                    )
                else:
                    # Section too large, recursively split it
                    sub_chunks = split_with_layered_strategy(
                        section_text,
                        hard_max_tokens,
                        overlap_tokens,
                        min_tokens,
                        model,
                        section_map=None,
                        prefer_headings=False,
                    )
                    # Adjust char positions for sub-chunks
                    for (
                        sub_text,
                        sub_strategy,
                        sub_start,
                        sub_end,
                    ) in sub_chunks:
                        chunks.append(
                            (
                                sub_text,
                                sub_strategy,
                                start_char + sub_start,
                                start_char + sub_end,
                            )
                        )

                last_pos = end_char

            # Handle any remaining text after last section
            if last_pos < len(text):
                remaining = text[last_pos:].strip()
                if remaining:
                    if count_tokens(remaining, model) <= hard_max_tokens:
                        chunks.append(
                            (remaining, "heading", last_pos, len(text))
                        )
                    else:
                        sub_chunks = split_with_layered_strategy(
                            remaining,
                            hard_max_tokens,
                            overlap_tokens,
                            min_tokens,
                            model,
                            section_map=None,
                            prefer_headings=False,
                        )
                        # Adjust char positions for sub-chunks
                        for (
                            sub_text,
                            sub_strategy,
                            sub_start,
                            sub_end,
                        ) in sub_chunks:
                            chunks.append(
                                (
                                    sub_text,
                                    sub_strategy,
                                    last_pos + sub_start,
                                    last_pos + sub_end,
                                )
                            )

            if chunks:
                return chunks

        except Exception:
            pass  # Fall through to next strategy

    # Strategy 2: Try heading-based splitting without section_map
    if prefer_headings:
        try:
            heading_chunks = split_by_headings(text)
            if len(heading_chunks) > 1:  # Only if we actually split
                result_chunks = []
                current_pos = 0

                for chunk_text, strategy in heading_chunks:
                    # Find the position of this chunk in the original text
                    chunk_start = text.find(chunk_text, current_pos)
                    if chunk_start == -1:
                        chunk_start = current_pos
                    chunk_end = chunk_start + len(chunk_text)

                    if count_tokens(chunk_text, model) <= hard_max_tokens:
                        result_chunks.append(
                            (chunk_text, strategy, chunk_start, chunk_end)
                        )
                    else:
                        # Recursively split oversized heading chunks
                        sub_chunks = split_with_layered_strategy(
                            chunk_text,
                            hard_max_tokens,
                            overlap_tokens,
                            min_tokens,
                            model,
                            section_map=None,
                            prefer_headings=False,
                        )
                        # Adjust char positions for sub-chunks
                        for (
                            sub_text,
                            sub_strategy,
                            sub_start,
                            sub_end,
                        ) in sub_chunks:
                            result_chunks.append(
                                (
                                    sub_text,
                                    sub_strategy,
                                    chunk_start + sub_start,
                                    chunk_start + sub_end,
                                )
                            )

                    current_pos = chunk_end

                return result_chunks
        except Exception:
            pass  # Fall through to next strategy

    # Strategy 3: Special handling for code fences
    if content_type == ChunkType.CODE and re.search(
        r"^```\w*\n.*\n```$", text, re.DOTALL
    ):
        try:
            code_chunks = split_code_fence_by_lines(
                text, hard_max_tokens, overlap_tokens, model
            )
            # Add char positions for code chunks
            result_chunks = []
            current_pos = 0
            for chunk_text, strategy in code_chunks:
                chunk_start = text.find(chunk_text, current_pos)
                if chunk_start == -1:
                    chunk_start = current_pos
                chunk_end = chunk_start + len(chunk_text)
                result_chunks.append(
                    (chunk_text, strategy, chunk_start, chunk_end)
                )
                current_pos = chunk_end
            return result_chunks
        except Exception:
            pass  # Fall through to next strategy

    # Strategy 4: Special handling for tables
    if content_type == ChunkType.TABLE:
        try:
            table_chunks = split_table_by_rows(
                text, hard_max_tokens, overlap_tokens, model
            )
            # Add char positions for table chunks
            result_chunks = []
            current_pos = 0
            for chunk_text, strategy in table_chunks:
                chunk_start = text.find(chunk_text, current_pos)
                if chunk_start == -1:
                    chunk_start = current_pos
                chunk_end = chunk_start + len(chunk_text)
                result_chunks.append(
                    (chunk_text, strategy, chunk_start, chunk_end)
                )
                current_pos = chunk_end
            return result_chunks
        except Exception:
            pass  # Fall through to next strategy

    # Strategy 5: Paragraph boundaries
    try:
        paragraph_chunks = split_by_paragraphs(text)
        if len(paragraph_chunks) > 1:  # Only if we actually split
            result_chunks = []
            current_paragraphs: List[str] = []
            current_text = ""
            text_start_pos = 0

            for para_text, strategy in paragraph_chunks:
                test_text = (
                    current_text + "\n\n" + para_text
                    if current_text
                    else para_text
                )
                if (
                    count_tokens(test_text, model) > hard_max_tokens
                    and current_text
                ):
                    # Emit current chunk with position
                    chunk_end_pos = text_start_pos + len(current_text)
                    result_chunks.append(
                        (
                            current_text,
                            "paragraph",
                            text_start_pos,
                            chunk_end_pos,
                        )
                    )

                    # Start new chunk with overlap
                    if overlap_tokens > 0 and len(current_paragraphs) > 1:
                        overlap_count = min(
                            len(current_paragraphs),
                            max(1, overlap_tokens // 100),
                        )  # ~100 tokens per paragraph estimate
                        overlap_paragraphs = current_paragraphs[
                            -overlap_count:
                        ]
                        current_text = (
                            "\n\n".join(overlap_paragraphs)
                            + "\n\n"
                            + para_text
                        )
                        current_paragraphs = overlap_paragraphs + [para_text]
                        # Update start position for overlapped chunk
                        overlap_text = "\n\n".join(overlap_paragraphs)
                        text_start_pos = max(
                            0, chunk_end_pos - len(overlap_text) - 2
                        )
                    else:
                        current_text = para_text
                        current_paragraphs = [para_text]
                        text_start_pos = text.find(para_text, text_start_pos)
                        if text_start_pos == -1:
                            text_start_pos = chunk_end_pos
                else:
                    if not current_text:
                        text_start_pos = text.find(para_text, 0)
                        if text_start_pos == -1:
                            text_start_pos = 0
                    current_text = test_text
                    current_paragraphs.append(para_text)

            # Add final chunk
            if current_text:
                chunk_end_pos = text_start_pos + len(current_text)
                result_chunks.append(
                    (current_text, "paragraph", text_start_pos, chunk_end_pos)
                )

            return result_chunks
    except Exception:
        pass  # Fall through to next strategy

    # Strategy 6: Sentence boundaries
    try:
        sentence_chunks = split_by_sentences(text)
        if len(sentence_chunks) > 1:  # Only if we actually split
            result_chunks = []
            current_sentences: List[str] = []
            current_text = ""
            text_start_pos = 0

            for sentence_text, strategy in sentence_chunks:
                test_text = (
                    current_text + " " + sentence_text
                    if current_text
                    else sentence_text
                )
                if (
                    count_tokens(test_text, model) > hard_max_tokens
                    and current_text
                ):
                    # Emit current chunk
                    chunk_end_pos = text_start_pos + len(current_text)
                    result_chunks.append(
                        (
                            current_text,
                            "sentence",
                            text_start_pos,
                            chunk_end_pos,
                        )
                    )

                    # Start new chunk with overlap
                    if overlap_tokens > 0 and len(current_sentences) > 1:
                        overlap_count = min(
                            len(current_sentences),
                            max(1, overlap_tokens // 50),
                        )  # ~50 tokens per sentence estimate
                        overlap_sentences = current_sentences[-overlap_count:]
                        current_text = (
                            " ".join(overlap_sentences) + " " + sentence_text
                        )
                        current_sentences = overlap_sentences + [sentence_text]
                        # Update start position for overlapped chunk
                        overlap_text = " ".join(overlap_sentences)
                        text_start_pos = max(
                            0, chunk_end_pos - len(overlap_text) - 1
                        )
                    else:
                        current_text = sentence_text
                        current_sentences = [sentence_text]
                        text_start_pos = text.find(
                            sentence_text, text_start_pos
                        )
                        if text_start_pos == -1:
                            text_start_pos = chunk_end_pos
                else:
                    if not current_text:
                        text_start_pos = text.find(sentence_text, 0)
                        if text_start_pos == -1:
                            text_start_pos = 0
                    current_text = test_text
                    current_sentences.append(sentence_text)

            # Add final chunk
            if current_text:
                chunk_end_pos = text_start_pos + len(current_text)
                result_chunks.append(
                    (current_text, "sentence", text_start_pos, chunk_end_pos)
                )

            return result_chunks
    except Exception:
        pass  # Fall through to final strategy

    # Strategy 7: Final fallback - token window
    token_chunks = split_by_token_window(
        text, hard_max_tokens, overlap_tokens, model
    )
    result_chunks = []
    current_pos = 0
    for chunk_text, strategy in token_chunks:
        chunk_start = text.find(chunk_text, current_pos)
        if chunk_start == -1:
            chunk_start = current_pos
        chunk_end = chunk_start + len(chunk_text)
        result_chunks.append((chunk_text, strategy, chunk_start, chunk_end))
        current_pos = chunk_end
    return result_chunks


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
    split_strategy: str = "paragraph",
    char_start: int = 0,
    char_end: int = 0,
    token_start: int = 0,
    token_end: int = 0,
    title: str = "",
    url: str = "",
    source_system: str = "",
    labels: Optional[List[str]] = None,
    space: Optional[Dict] = None,
    media_refs: Optional[List[Dict]] = None,
) -> Chunk:
    """Create a single chunk with guaranteed max_tokens compliance and full traceability."""
    if labels is None:
        labels = []
    if media_refs is None:
        media_refs = []

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
            source=(
                chunk_type.value
                if isinstance(chunk_type, ChunkType)
                else chunk_type
            ),
            token_savings=chunk_meta.get("token_savings", 0),
        )

    # Update char_end if text was truncated
    if char_end > char_start:
        actual_char_count = len(chunk_text)
        original_char_count = char_end - char_start
        if actual_char_count < original_char_count:
            char_end = char_start + actual_char_count

    chunk = Chunk(
        chunk_id=chunk_id,
        text_md=chunk_text.strip(),
        char_count=len(chunk_text),
        token_count=final_tokens,
        ord=ord_num,
        chunk_type=(
            chunk_type.value
            if isinstance(chunk_type, ChunkType)
            else chunk_type
        ),
        meta=chunk_meta,
        split_strategy=split_strategy,
        char_start=char_start,
        char_end=char_end,
        token_start=token_start,
        token_end=token_end,
        doc_id=doc_id,
        title=title,
        url=url,
        source_system=source_system,
        labels=labels,
        space=space,
        media_refs=media_refs,
    )

    emit_event(
        "chunk.emit",
        chunk_id=chunk_id,
        type=chunk.chunk_type,
        token_count=final_tokens,
    )

    return chunk


def apply_glue_pass(
    chunks: List[Chunk],
    soft_min_tokens: int,
    hard_min_tokens: int,
    hard_max_tokens: int,
    orphan_heading_merge: bool,
    small_tail_merge: bool,
    model: str,
) -> List[Chunk]:
    """
    Apply glue pass to merge small chunks according to v2.2 bottom-end controls.

    Args:
        chunks: List of chunks to process
        soft_min_tokens: Target minimum tokens after glue
        hard_min_tokens: Absolute minimum tokens for any chunk
        hard_max_tokens: Absolute maximum tokens (never exceed)
        orphan_heading_merge: Whether to merge orphan headings
        small_tail_merge: Whether to merge small tail chunks
        model: Model name for token counting

    Returns:
        List of chunks after glue pass
    """
    if not chunks:
        return chunks

    glued_chunks: List[Chunk] = []
    i = 0

    while i < len(chunks):
        current_chunk = chunks[i]
        current_tokens = current_chunk.token_count

        # Check if chunk needs gluing
        needs_glue = current_tokens < soft_min_tokens

        # Check for orphan headings (just a heading or ultra-short boilerplate)
        is_orphan_heading = orphan_heading_merge and _is_orphan_heading(
            current_chunk.text_md
        )

        if needs_glue or is_orphan_heading:
            # Try to merge with next chunk first
            merged_chunk = None
            if i + 1 < len(chunks):
                next_chunk = chunks[i + 1]
                merged_tokens = current_tokens + next_chunk.token_count
                if merged_tokens <= hard_max_tokens:
                    merged_chunk = _merge_chunks(
                        current_chunk, next_chunk, model
                    )
                    i += 2  # Skip both chunks
                else:
                    # Try merging with previous chunk
                    if i > 0 and glued_chunks:
                        prev_chunk = glued_chunks[-1]
                        merged_tokens = prev_chunk.token_count + current_tokens
                        if merged_tokens <= hard_max_tokens:
                            # Replace the last chunk in glued_chunks with merged version
                            glued_chunks[-1] = _merge_chunks(
                                prev_chunk, current_chunk, model
                            )
                            i += 1
                            continue

                    # Can't merge, keep as is but flag if it's a small tail
                    if (
                        small_tail_merge
                        and i == len(chunks) - 1
                        and current_tokens < hard_min_tokens
                    ):
                        # Mark as small tail
                        meta = (
                            dict(current_chunk.meta)
                            if current_chunk.meta
                            else {}
                        )
                        meta["tail_small"] = True
                        merged_chunk = current_chunk._replace(meta=meta)
                    else:
                        merged_chunk = current_chunk
                    i += 1
            else:
                # Last chunk - try to merge with previous
                if i > 0 and glued_chunks:
                    prev_chunk = glued_chunks[-1]
                    merged_tokens = prev_chunk.token_count + current_tokens
                    if merged_tokens <= hard_max_tokens:
                        glued_chunks[-1] = _merge_chunks(
                            prev_chunk, current_chunk, model
                        )
                        i += 1
                        continue

                # Can't merge, mark as small tail if needed
                if small_tail_merge and current_tokens < hard_min_tokens:
                    meta = (
                        dict(current_chunk.meta) if current_chunk.meta else {}
                    )
                    meta["tail_small"] = True
                    merged_chunk = current_chunk._replace(meta=meta)
                else:
                    merged_chunk = current_chunk
                i += 1

            if merged_chunk:
                glued_chunks.append(merged_chunk)
        else:
            # Chunk is fine as is
            glued_chunks.append(current_chunk)
            i += 1

    return glued_chunks


def _is_orphan_heading(text_md: str) -> bool:
    """Check if text is just a heading or ultra-short boilerplate."""
    text = text_md.strip()
    if not text:
        return True

    lines = text.split("\n")
    non_empty_lines = [line.strip() for line in lines if line.strip()]

    if len(non_empty_lines) <= 1:
        # Single line - check if it's just a heading
        if non_empty_lines and non_empty_lines[0].startswith("#"):
            return True
        # Check for common boilerplate
        if text.lower() in ["references", "see also", "notes", "todo", "tbd"]:
            return True

    return False


def _merge_chunks(chunk1: Chunk, chunk2: Chunk, model: str) -> Chunk:
    """Merge two chunks into one, updating all metadata appropriately."""
    # Combine text
    combined_text = chunk1.text_md + "\n\n" + chunk2.text_md
    combined_tokens = count_tokens(combined_text, model)

    # Update split strategy
    new_strategy = chunk1.split_strategy + "+glue"

    # Combine metadata
    meta1 = chunk1.meta or {}
    meta2 = chunk2.meta or {}
    combined_meta = dict(meta1)
    combined_meta.update(meta2)
    combined_meta["glued_from"] = [chunk1.chunk_id, chunk2.chunk_id]

    # Create merged chunk (use chunk1 as base)
    return chunk1._replace(
        text_md=combined_text,
        char_count=len(combined_text),
        token_count=combined_tokens,
        split_strategy=new_strategy,
        char_end=chunk2.char_end,  # Extend to end of second chunk
        token_end=chunk2.token_end,
        meta=combined_meta,
    )


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


def calculate_coverage(
    chunks: List[Chunk], original_text_length: int
) -> Tuple[float, List[Tuple[int, int]]]:
    """
    Calculate text coverage from chunks and identify gaps.

    Args:
        chunks: List of chunks with char_start/char_end
        original_text_length: Length of the original document text

    Returns:
        Tuple of (coverage_percentage, list_of_gaps)
        where gaps are (start, end) tuples of uncovered ranges
    """
    if not chunks or original_text_length == 0:
        return 0.0, [(0, original_text_length)]

    # Create a list of covered ranges
    covered_ranges = []
    for chunk in chunks:
        if chunk.char_start < chunk.char_end:
            covered_ranges.append((chunk.char_start, chunk.char_end))

    if not covered_ranges:
        return 0.0, [(0, original_text_length)]

    # Sort ranges by start position
    covered_ranges.sort(key=lambda x: x[0])

    # Merge overlapping ranges
    merged_ranges = []
    current_start, current_end = covered_ranges[0]

    for start, end in covered_ranges[1:]:
        if start <= current_end:  # Overlapping or adjacent
            current_end = max(current_end, end)
        else:
            merged_ranges.append((current_start, current_end))
            current_start, current_end = start, end

    merged_ranges.append((current_start, current_end))

    # Calculate covered characters
    covered_chars = sum(end - start for start, end in merged_ranges)
    coverage_pct = (covered_chars / original_text_length) * 100

    # Find gaps
    gaps = []
    last_end = 0

    for start, end in merged_ranges:
        if start > last_end:
            gaps.append((last_end, start))
        last_end = end

    # Check if there's a gap at the end
    if last_end < original_text_length:
        gaps.append((last_end, original_text_length))

    return coverage_pct, gaps


def chunk_document(
    doc_id: str,
    text_md: str,
    title: str = "",
    url: str = "",
    source_system: str = "",
    labels: Optional[List[str]] = None,
    space: Optional[Dict] = None,
    media_refs: Optional[List[Dict]] = None,
    hard_max_tokens: int = 800,
    min_tokens: int = 120,
    overlap_tokens: int = 60,
    soft_min_tokens: int = 200,
    hard_min_tokens: int = 80,
    orphan_heading_merge: bool = True,
    small_tail_merge: bool = True,
    prefer_headings: bool = True,
    soft_boundaries: Optional[List[int]] = None,
    section_map: Optional[List[Dict]] = None,
    model: str = "text-embedding-3-small",
) -> List[Chunk]:
    """
    Chunk a document using layered splitting with guaranteed hard token cap and full traceability.

    Args:
        doc_id: Document identifier
        text_md: Markdown text content
        title: Document title (prepended to first chunk)
        url: Document URL for traceability
        source_system: Source system (confluence, dita, etc.) for traceability
        labels: Document labels for traceability
        space: Confluence space info for traceability
        media_refs: Media references for traceability
        hard_max_tokens: Absolute ceiling for tokens (default 800)
        min_tokens: Minimum tokens preferred (can go down to 80 when forced)
        overlap_tokens: Tokens to overlap when splitting (default 60)
        soft_min_tokens: Target minimum tokens after glue pass (default 200)
        hard_min_tokens: Absolute minimum tokens for any chunk (default 80)
        orphan_heading_merge: Whether to merge orphan headings (default True)
        small_tail_merge: Whether to merge small tail chunks (default True)
        prefer_headings: Whether to prefer heading-aligned splits
        soft_boundaries: Character positions that are good split points
        section_map: List of heading sections with positions
        model: Model name for token counting

    Returns:
        List of Chunk objects with guaranteed token cap compliance and full traceability
    """
    if labels is None:
        labels = []
    if media_refs is None:
        media_refs = []
    if soft_boundaries is None:
        soft_boundaries = []
    if section_map is None:
        section_map = []

    # Normalize and prepare text
    full_text = normalize_text(text_md)
    original_text_length = len(full_text)

    if title and title.strip():
        if full_text.strip():
            full_text = f"# {title.strip()}\n\n{full_text}"
        else:
            full_text = f"# {title.strip()}"

    if not full_text.strip():
        return []

    # Use layered splitting strategy with char positions
    chunk_tuples = split_with_layered_strategy(
        full_text,
        hard_max_tokens,
        overlap_tokens,
        min_tokens,
        model,
        section_map,
        prefer_headings,
    )

    # Convert to Chunk objects
    chunks = []
    for ord_num, (
        chunk_text,
        split_strategy,
        char_start,
        char_end,
    ) in enumerate(chunk_tuples):
        if not chunk_text.strip():
            continue

        # Final safety check - if still over limit, force truncate
        token_count = count_tokens(chunk_text, model)
        if token_count > hard_max_tokens:
            # This should never happen with layered strategy, but safety first
            # Binary search to find the right length
            low, high = 0, len(chunk_text)
            while low < high:
                mid = (low + high + 1) // 2
                test_text = (
                    chunk_text[:mid] + "\n[TRUNCATED - EXCEEDED HARD CAP]"
                )
                test_tokens = count_tokens(test_text, model)
                if test_tokens <= hard_max_tokens:
                    low = mid
                else:
                    high = mid - 1

            chunk_text = chunk_text[:low] + "\n[TRUNCATED - EXCEEDED HARD CAP]"
            split_strategy = "force-truncate"
            # Update char_end for truncated text
            char_end = char_start + len(chunk_text)

            emit_event(
                "chunk.force_truncate",
                chunk_id=f"{doc_id}:{ord_num:04d}",
                original_tokens=token_count,
                final_tokens=count_tokens(chunk_text, model),
            )

        chunk = _create_safe_chunk(
            doc_id=doc_id,
            chunk_text=chunk_text,
            ord_num=ord_num,
            max_tokens=hard_max_tokens,
            model=model,
            split_strategy=split_strategy,
            char_start=char_start,
            char_end=char_end,
            title=title,
            url=url,
            source_system=source_system,
            labels=labels,
            space=space,
            media_refs=media_refs,
        )
        chunks.append(chunk)

    # Apply glue pass for v2.2 bottom-end controls
    if soft_min_tokens > 0:
        chunks = apply_glue_pass(
            chunks,
            soft_min_tokens,
            hard_min_tokens,
            hard_max_tokens,
            orphan_heading_merge,
            small_tail_merge,
            model,
        )

    # Verify coverage (should be >= 99.5%)
    coverage_pct, gaps = calculate_coverage(chunks, original_text_length)
    if coverage_pct < 99.5 and gaps:
        emit_event(
            "chunk.coverage_warning",
            doc_id=doc_id,
            coverage_pct=coverage_pct,
            gaps_count=len(gaps),
            gaps=gaps[:5],  # Limit to first 5 gaps for logging
        )

    return chunks
