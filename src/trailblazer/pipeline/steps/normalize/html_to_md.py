from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from bs4 import BeautifulSoup
from markdownify import markdownify as md  # type: ignore

from ....core.logging import log
from ....core.artifacts import ROOT

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
    return ROOT / "runs" / run_id / "ingest" / "confluence.ndjson"


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
                else ("storage" if rec.get("body_storage") else None)
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
            else:
                text_md = ""

            attachments = [
                {"filename": a.get("filename"), "url": a.get("download_url")}
                for a in (rec.get("attachments") or [])
            ]

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
                "source_system": rec.get(
                    "source_system", "confluence"
                ),  # Traceability field
                "source": "confluence",  # Keep for backward compatibility
                # Enhanced traceability preservation
                "labels": rec.get("labels", []),
                "content_sha256": rec.get("content_sha256"),
            }

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
    return metrics
