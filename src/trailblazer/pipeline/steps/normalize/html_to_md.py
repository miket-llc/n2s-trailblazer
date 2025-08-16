from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from bs4 import BeautifulSoup
from markdownify import markdownify as md  # type: ignore

from ....core.logging import log


# ---------- DITA XML -> Markdown ----------


def _to_markdown_from_dita_xml(dita_xml: Optional[str]) -> str:
    """Convert DITA XML body to Markdown."""
    if not dita_xml:
        return ""

    try:
        from bs4 import BeautifulSoup, NavigableString

        soup = BeautifulSoup(dita_xml, "xml")

        def _convert_element(element) -> str:
            if isinstance(element, NavigableString):
                return str(element).strip()

            tag = element.name.lower() if element.name else ""
            content = ""

            # Get child content recursively
            children_content = []
            for child in element.children:
                child_md = _convert_element(child)
                if child_md.strip():
                    children_content.append(child_md)
            content = " ".join(children_content)

            # Convert DITA elements to Markdown
            if tag in ("title", "navtitle"):
                # Title elements - use ATX headers
                level = 1
                parent = element.parent
                while parent and parent.name:
                    if parent.name.lower() in (
                        "section",
                        "concept",
                        "task",
                        "reference",
                    ):
                        level += 1
                    parent = parent.parent
                level = min(level, 6)  # Max 6 levels
                return f"{'#' * level} {content}\n\n"

            elif tag in ("p", "shortdesc"):
                return f"{content}\n\n"

            elif tag in ("ul", "ol"):
                # Process list items
                items = []
                for li in element.find_all("li", recursive=False):
                    item_content = _convert_element(li).strip()
                    if tag == "ul":
                        items.append(f"- {item_content}")
                    else:
                        items.append(f"1. {item_content}")
                return "\n".join(items) + "\n\n"

            elif tag == "li":
                return content  # Content handled by parent ul/ol

            elif tag in ("codeblock", "codeph"):
                if tag == "codeblock":
                    return f"```\n{content}\n```\n\n"
                else:
                    return f"`{content}`"

            elif tag in ("note", "important", "warning", "caution"):
                return f"> **{tag.capitalize()}**: {content}\n\n"

            elif tag in ("b", "strong"):
                return f"**{content}**"

            elif tag in ("i", "em"):
                return f"*{content}*"

            elif tag == "u":
                return f"<u>{content}</u>"

            elif tag == "xref":
                href = element.get("href")
                keyref = element.get("keyref")
                if href:
                    return f"[{content or href}]({href})"
                elif keyref:
                    return f"[{content or keyref}]({keyref})"
                else:
                    return content

            elif tag == "link":
                href = element.get("href")
                if href:
                    return f"[{content or href}]({href})"
                return content

            elif tag == "image":
                href = element.get("href")
                alt = element.get("alt") or content or "image"
                if href:
                    return f"![{alt}]({href})"
                else:
                    return f"![{alt}](#)"

            elif tag in ("fig", "figure"):
                return f"{content}\n\n"

            elif tag in ("table", "simpletable"):
                # Basic table support - could be enhanced
                return f"{content}\n\n"

            elif tag in (
                "section",
                "concept",
                "task",
                "reference",
                "body",
                "conbody",
                "taskbody",
                "refbody",
            ):
                # Container elements - return content
                return content

            else:
                # Default: return content for unknown elements
                return content

        # Convert the root element
        result = _convert_element(soup)

        # Normalize whitespace
        result = re.sub(r"\r\n?", "\n", result)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    except Exception as e:
        log.warning("dita_xml_conversion_failed", error=str(e))
        # Fallback: strip XML tags and return plain text
        clean_text = re.sub(r"<[^>]+>", " ", dita_xml or "")
        clean_text = re.sub(r"\s+", " ", clean_text)
        return clean_text.strip()


def _extract_links_from_dita_xml(dita_xml: Optional[str]) -> List[str]:
    """Extract links from DITA XML."""
    if not dita_xml:
        return []

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(dita_xml, "xml")
        links = []

        # Extract from xref elements
        for xref in soup.find_all("xref"):
            if hasattr(xref, "get"):
                href = xref.get("href")
                if (
                    href
                    and isinstance(href, str)
                    and href.startswith(("http://", "https://"))
                ):
                    links.append(href)

        # Extract from link elements
        for link in soup.find_all("link"):
            if hasattr(link, "get"):
                href = link.get("href")
                if (
                    href
                    and isinstance(href, str)
                    and href.startswith(("http://", "https://"))
                ):
                    links.append(href)

        return sorted(
            dict.fromkeys([link for link in links if isinstance(link, str)])
        )

    except Exception:
        return []


# ---------- Storage (XHTML) -> Markdown ----------


def _to_markdown_from_storage(xhtml: Optional[str]) -> str:
    if not xhtml:
        return ""
    soup = BeautifulSoup(xhtml, "html.parser")
    # Drop non-content tags/macros (keep simple approach; advanced macro handling later)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    html2 = str(soup)
    text = md(
        html2, heading_style="ATX", strip=["script", "style", "noscript"]
    )
    # normalize whitespace deterministically
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _extract_links_from_storage(xhtml: Optional[str]) -> List[str]:
    if not xhtml:
        return []
    soup = BeautifulSoup(xhtml, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        if hasattr(a, "get"):
            href = a.get("href")
            if href and isinstance(href, str):
                links.append(href)
    return sorted(dict.fromkeys(links))


# ---------- ADF JSON -> Markdown (minimal converter) ----------


def _adf_text_with_marks(text: str, marks: Optional[List[dict]]) -> str:
    if not marks:
        return text
    # apply marks in a stable order: code, strong, em, strike, link
    out = text
    # links last so they wrap the final text
    order = {"code": 0, "strong": 1, "em": 2, "strike": 3, "link": 4}
    for m in sorted(marks, key=lambda m: order.get(m.get("type", ""), 99)):
        t = m.get("type")
        if t == "code":
            out = f"`{out}`"
        elif t == "strong":
            out = f"**{out}**"
        elif t == "em":
            out = f"*{out}*"
        elif t == "strike":
            out = f"~~{out}~~"
        elif t == "link":
            href = (m.get("attrs") or {}).get("href")
            if href:
                out = f"[{out}]({href})"
    return out


def _adf_inline(node: dict) -> str:
    t = node.get("type")
    if t == "text":
        return _adf_text_with_marks(node.get("text", ""), node.get("marks"))
    if t == "hardBreak":
        return "\n"
    # inlineCode sometimes represented as text+code mark; we've covered in marks
    return ""


def _adf_block(
    node: dict, bullets: Optional[str] = None, number: Optional[int] = None
) -> str:
    t = node.get("type")
    if t == "paragraph":
        parts = [_adf_inline(c) for c in node.get("content", [])]
        return "".join(parts).strip()
    elif t == "heading":
        level = max(1, min(6, int((node.get("attrs") or {}).get("level", 1))))
        inner = "".join(
            [_adf_inline(c) for c in node.get("content", [])]
        ).strip()
        return f"{'#' * level} {inner}".strip()
    elif t == "blockquote":
        inner = _adf_blocks(node.get("content", []))
        return (
            "\n".join([f"> {line}".rstrip() for line in inner.splitlines()])
            or "> "
        )
    elif t == "codeBlock":
        lang = (node.get("attrs") or {}).get("language") or ""
        code = "".join(
            [
                c.get("text", "")
                for c in node.get("content", [])
                if c.get("type") == "text"
            ]
        )
        return f"```{lang}\n{code}\n```"
    elif t == "bulletList":
        lines = []
        for li in node.get("content", []):
            # listItem → content → paragraph/blocks
            inner = _adf_blocks(li.get("content", []))
            for line in inner.splitlines():
                if line.strip():
                    lines.append(f"- {line}")
        return "\n".join(lines)
    elif t == "orderedList":
        lines = []
        n = int((node.get("attrs") or {}).get("order", 1))
        for li in node.get("content", []):
            inner = _adf_blocks(li.get("content", []))
            for line in inner.splitlines():
                if line.strip():
                    lines.append(f"{n}. {line}")
                    n += 1
        return "\n".join(lines)
    elif t == "panel":
        # simple rendering: treat as blockquote
        inner = _adf_blocks(node.get("content", []))
        return "\n".join([f"> {line}".rstrip() for line in inner.splitlines()])
    else:
        # tables/media/mentions not handled yet; can be added incrementally
        # unknown blocks -> flatten children
        return _adf_blocks(node.get("content", []))


def _adf_blocks(nodes: List[dict]) -> str:
    lines: List[str] = []
    for n in nodes:
        s = _adf_block(n)
        if s.strip():
            lines.append(s.strip())
    text = "\n\n".join(lines)
    # normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _to_markdown_from_adf(adf: Optional[dict]) -> str:
    if not adf or adf.get("type") != "doc":
        return ""
    return _adf_blocks(adf.get("content", []))


def _extract_links_from_adf(adf: Optional[dict]) -> List[str]:
    if not adf:
        return []
    links: List[str] = []

    def walk(n: dict):
        # collect from marks
        for c in n.get("content", []) or []:
            walk(c)
        if n.get("type") == "text":
            for m in n.get("marks", []) or []:
                if m.get("type") == "link":
                    href = (m.get("attrs") or {}).get("href")
                    if href:
                        links.append(href)

    walk(adf)
    # deterministic
    return sorted(dict.fromkeys(links))


# ---------- Orchestration ----------


def _derive_run_id(outdir: str) -> str:
    return Path(outdir).parent.name


def _default_ingest_path(run_id: str) -> Path:
    """Auto-detect ingest NDJSON file - try confluence.ndjson first, then dita.ndjson"""
    from ....core.paths import runs

    confluence_path = runs() / run_id / "ingest" / "confluence.ndjson"
    if confluence_path.exists():
        return confluence_path

    dita_path = runs() / run_id / "ingest" / "dita.ndjson"
    if dita_path.exists():
        return dita_path

    # Default to confluence for backwards compatibility
    return confluence_path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_from_ingest(
    outdir: str, input_file: Optional[str] = None, limit: Optional[int] = None
) -> Dict[str, Any]:
    out_dir = Path(outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = Path(outdir).parent.name
    inp = Path(input_file) if input_file else _default_ingest_path(run_id)
    if not inp.exists():
        raise FileNotFoundError(f"Ingest NDJSON not found: {inp}")

    nd_out = out_dir / "normalized.ndjson"
    metrics_path = out_dir / "metrics.json"
    manifest_path = out_dir / "manifest.json"

    # Load DITA metadata if available
    metadata_by_page_id = {}
    ingest_dir = Path(outdir).parent / "ingest"
    meta_path = ingest_dir / "meta.jsonl"
    if meta_path.exists():
        with meta_path.open("r", encoding="utf-8") as meta_file:
            for line in meta_file:
                if line.strip():
                    meta_rec = json.loads(line)
                    metadata_by_page_id[meta_rec["page_id"]] = meta_rec

    total = empty = chars = atts_count = 0

    with (
        inp.open("r", encoding="utf-8") as fin,
        nd_out.open("w", encoding="utf-8") as fout,
    ):
        for line in fin:
            if not line.strip():
                continue
            rec = json.loads(line)

            body_repr = rec.get("body_repr") or (
                "adf"
                if rec.get("body_adf")
                else (
                    "storage"
                    if rec.get("body_storage")
                    else (
                        "dita"
                        if rec.get("body_dita_xml") or rec.get("body_xml")
                        else None
                    )
                )
            )
            links: List[str] = []
            if body_repr == "storage":
                text_md = _to_markdown_from_storage(
                    rec.get("body_storage") or rec.get("body_html")
                )
                links = _extract_links_from_storage(
                    rec.get("body_storage") or rec.get("body_html")
                )
            elif body_repr == "adf":
                text_md = _to_markdown_from_adf(rec.get("body_adf"))
                links = _extract_links_from_adf(rec.get("body_adf"))
            elif body_repr == "dita":
                text_md = _to_markdown_from_dita_xml(
                    rec.get("body_dita_xml") or rec.get("body_xml")
                )
                links = _extract_links_from_dita_xml(
                    rec.get("body_dita_xml") or rec.get("body_xml")
                )
            else:
                text_md = ""

            # Handle attachments - can be strings (DITA) or objects (Confluence)
            raw_attachments = rec.get("attachments") or []
            attachments = []
            for a in raw_attachments:
                if isinstance(a, str):
                    # DITA attachment - just a file path string
                    attachments.append({"filename": a, "url": None})
                elif isinstance(a, dict):
                    # Confluence attachment - object with filename and download_url
                    attachments.append(
                        {
                            "filename": a.get("filename"),
                            "url": a.get("download_url"),
                        }
                    )
                else:
                    # Fallback for unexpected format
                    attachments.append({"filename": str(a), "url": None})

            # Get enhanced metadata for DITA records
            enhanced_meta = metadata_by_page_id.get(rec.get("id"), {})

            out_rec = {
                "id": rec.get("id"),
                "title": rec.get("title"),
                "space_key": rec.get("space_key"),
                "space_id": rec.get("space_id"),
                "url": rec.get("url"),
                "version": rec.get("version"),
                "created_at": rec.get("created_at"),
                "updated_at": rec.get("updated_at"),
                "body_repr": body_repr,
                "text_md": text_md,
                "links": sorted(dict.fromkeys(links)),
                "attachments": attachments,
                "source_system": rec.get("source_system", "confluence"),
                "source": rec.get(
                    "source_system", "confluence"
                ),  # Updated for DITA support
                # Enhanced traceability preservation
                "labels": enhanced_meta.get("labels", rec.get("labels", [])),
                "content_sha256": rec.get("content_sha256"),
            }

            # Add DITA-specific metadata fields if available
            if enhanced_meta:
                if enhanced_meta.get("collection"):
                    out_rec["collection"] = enhanced_meta["collection"]
                if enhanced_meta.get("path_tags"):
                    out_rec["path_tags"] = enhanced_meta["path_tags"]
                if enhanced_meta.get("meta"):
                    out_rec["meta"] = enhanced_meta["meta"]

            # Add breadcrumbs if available (optional)
            if rec.get("ancestors"):
                breadcrumbs = []
                space_name = rec.get("space_name")
                if space_name:
                    breadcrumbs.append(space_name)
                for ancestor in rec.get("ancestors", []):
                    breadcrumbs.append(ancestor.get("title", ""))
                breadcrumbs.append(rec.get("title", ""))
                out_rec["breadcrumbs"] = breadcrumbs

            if not text_md:
                empty += 1
            atts_count += len(attachments)
            chars += len(text_md)
            total += 1
            fout.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            if limit and total >= limit:
                break

    metrics = {
        "run_id": run_id,
        "input": str(inp),
        "output": str(nd_out),
        "pages": total,
        "empty_bodies": empty,
        "attachments": atts_count,
        "avg_chars": (chars // total) if total else 0,
        "completed_at": _now_iso(),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    manifest = {
        "phase": "normalize",
        "artifact": "normalized.ndjson",
        "run_id": run_id,
        "completed_at": _now_iso(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("normalize.done", **metrics)

    # Register in processed_runs backlog
    try:
        from ...backlog import upsert_normalized_run

        # Detect source from directory structure
        source = "mixed"  # Default fallback
        if "confluence" in str(inp).lower():
            source = "confluence"
        elif "dita" in str(inp).lower():
            source = "dita"

        upsert_normalized_run(run_id, source, total)
    except Exception as e:
        log.warning("normalize.backlog_failed", error=str(e))

    return metrics
