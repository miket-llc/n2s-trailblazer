"""
Boundary detection and splitting strategies for chunking.
"""

import re
from enum import Enum
from typing import Dict, List, Tuple

try:
    import tiktoken  # type: ignore
except ImportError:
    tiktoken = None  # type: ignore


class ChunkType(Enum):
    """Types of content chunks for specialized handling."""

    TEXT = "text"
    CODE = "code"
    TABLE = "table"
    MACRO = "macro"
    DIGEST = "digest"


def normalize_text(text: str) -> str:
    """Normalize text for consistent chunking."""
    # Normalize line endings CRLF -> LF
    text = re.sub(r"\r\n?", "\n", text)
    # Remove any triple+ blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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


def split_by_headings(text: str) -> List[Tuple[str, str]]:
    """Split text by headings, returning (content, strategy) tuples."""
    lines = text.split("\n")
    chunks = []
    current_chunk: List[str] = []

    for line in lines:
        if re.match(r"^#+\s", line) and current_chunk:
            # Found a heading, finish current chunk
            chunks.append(("\n".join(current_chunk).strip(), "heading"))
            current_chunk = [line]
        else:
            current_chunk.append(line)

    # Add final chunk
    if current_chunk:
        chunks.append(("\n".join(current_chunk).strip(), "heading"))

    return [(chunk, strategy) for chunk, strategy in chunks if chunk.strip()]


def split_by_paragraphs(text: str) -> List[Tuple[str, str]]:
    """Split text by paragraph boundaries."""
    # Split on double newlines (paragraph breaks)
    paragraphs = re.split(r"\n\s*\n", text)
    return [(p.strip(), "paragraph") for p in paragraphs if p.strip()]


def split_by_sentences(text: str) -> List[Tuple[str, str]]:
    """Split text by sentence boundaries using simple heuristics."""
    # Simple sentence splitting on period, question mark, exclamation
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [(s.strip(), "sentence") for s in sentences if s.strip()]


def split_code_fence_by_lines(
    text: str, hard_max_tokens: int, overlap_tokens: int, model: str
) -> List[Tuple[str, str]]:
    """Split code fences by line blocks, never cutting mid-line."""
    # Extract language and code content
    match = re.match(r"^```(\w*)\n(.*?)\n```$", text, re.DOTALL)
    if not match:
        return [(text, "code-fence-lines")]

    language = match.group(1)
    code_content = match.group(2)
    code_lines = code_content.split("\n")

    chunks = []
    current_lines: List[str] = []

    for line in code_lines:
        # Test if adding this line would exceed the cap
        test_chunk = (
            f"```{language}\n" + "\n".join(current_lines + [line]) + "\n```"
        )
        if count_tokens(test_chunk, model) > hard_max_tokens and current_lines:
            # Emit current chunk
            chunk_text = (
                f"```{language}\n" + "\n".join(current_lines) + "\n```"
            )
            chunks.append((chunk_text, "code-fence-lines"))

            # Start new chunk with overlap
            if overlap_tokens > 0 and len(current_lines) > 1:
                # Estimate lines needed for overlap
                overlap_lines = min(
                    len(current_lines), max(1, overlap_tokens // 20)
                )  # ~20 tokens per line estimate
                current_lines = current_lines[-overlap_lines:] + [line]
            else:
                current_lines = [line]
        else:
            current_lines.append(line)

    # Add final chunk
    if current_lines:
        chunk_text = f"```{language}\n" + "\n".join(current_lines) + "\n```"
        chunks.append((chunk_text, "code-fence-lines"))

    return chunks


def split_table_by_rows(
    text: str, hard_max_tokens: int, overlap_tokens: int, model: str
) -> List[Tuple[str, str]]:
    """Split tables by row groups, never cutting mid-cell."""
    lines = text.split("\n")
    table_lines = [line for line in lines if "|" in line]

    if len(table_lines) < 2:
        return [(text, "table-rows")]

    chunks = []
    current_rows = []
    header_rows = (
        table_lines[:2] if len(table_lines) >= 2 else table_lines[:1]
    )  # Header + separator

    # Always include header rows
    current_rows = header_rows[:]

    for row in table_lines[len(header_rows) :]:
        test_chunk = "\n".join(current_rows + [row])
        if count_tokens(test_chunk, model) > hard_max_tokens and len(
            current_rows
        ) > len(header_rows):
            # Emit current chunk
            chunks.append(("\n".join(current_rows), "table-rows"))

            # Start new chunk with header + overlap rows
            overlap_row_count = min(
                len(current_rows) - len(header_rows),
                max(1, overlap_tokens // 30),
            )  # ~30 tokens per row estimate
            if overlap_row_count > 0:
                overlap_rows = current_rows[-overlap_row_count:]
                current_rows = header_rows + overlap_rows + [row]
            else:
                current_rows = header_rows + [row]
        else:
            current_rows.append(row)

    # Add final chunk
    if len(current_rows) > len(header_rows):
        chunks.append(("\n".join(current_rows), "table-rows"))

    return chunks if chunks else [(text, "table-rows")]


def split_by_token_window(
    text: str, hard_max_tokens: int, overlap_tokens: int, model: str
) -> List[Tuple[str, str]]:
    """Final fallback: greedy token slicing with overlap."""
    if count_tokens(text, model) <= hard_max_tokens:
        return [(text, "token-window")]

    chunks = []
    words = text.split()
    current_words: List[str] = []

    for word in words:
        test_text = " ".join(current_words + [word])
        if count_tokens(test_text, model) > hard_max_tokens and current_words:
            # Emit current chunk
            chunk_text = " ".join(current_words)
            chunks.append((chunk_text, "token-window"))

            # Start new chunk with overlap
            if overlap_tokens > 0 and len(current_words) > 1:
                overlap_word_count = min(
                    len(current_words), max(1, overlap_tokens // 2)
                )  # ~2 tokens per word estimate
                current_words = current_words[-overlap_word_count:] + [word]
            else:
                current_words = [word]
        else:
            current_words.append(word)

    # Add final chunk
    if current_words:
        chunks.append((" ".join(current_words), "token-window"))

    return chunks


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
