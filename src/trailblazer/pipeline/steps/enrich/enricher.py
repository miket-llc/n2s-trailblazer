"""
Document enrichment module for adding rule-based and LLM-optional metadata.

This module processes normalized documents and adds:
- Rule-based fields (collections, path_tags, readability metrics, quality flags)
- LLM-optional fields (summaries, keywords, taxonomy labels, suggested edges)
- Enrichment fingerprints for selective re-embedding
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ....core.logging import log


class DocumentEnricher:
    """Enriches normalized documents with metadata and quality signals."""

    def __init__(
        self,
        llm_enabled: bool = False,
        max_docs: Optional[int] = None,
        budget: Optional[str] = None,
    ):
        self.llm_enabled = llm_enabled
        self.max_docs = max_docs
        self.budget = budget
        self.enrichment_version = "v1"

        # Statistics
        self.docs_processed = 0
        self.docs_llm = 0
        self.suggested_edges_count = 0
        self.quality_flags_counts: Dict[str, int] = {}

    def enrich_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich a single document with rule-based and optional LLM metadata."""
        enriched = self._apply_rule_based_enrichment(doc)

        if self.llm_enabled:
            llm_enrichment = self._apply_llm_enrichment(doc)
            enriched.update(llm_enrichment)
            if llm_enrichment:
                self.docs_llm += 1

        self.docs_processed += 1
        return enriched

    def _apply_rule_based_enrichment(
        self, doc: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply fast, deterministic rule-based enrichment."""
        source_system = doc.get("source_system", "unknown")
        text_md = doc.get("text_md", "")
        attachments = doc.get("attachments", [])
        links = doc.get("links", [])

        # Extract or compute collection and path_tags
        collection = self._extract_collection(doc)
        path_tags = self._extract_path_tags(doc)

        # Compute readability metrics
        readability = self._compute_readability(text_md)

        # Compute media and link densities
        media_density = self._compute_media_density(text_md, attachments)
        link_density = self._compute_link_density(text_md, links)

        # Determine quality flags
        quality_flags = self._determine_quality_flags(
            doc, text_md, attachments
        )

        # Update statistics
        for flag in quality_flags:
            self.quality_flags_counts[flag] = (
                self.quality_flags_counts.get(flag, 0) + 1
            )

        return {
            "id": doc.get("id"),
            "source_system": source_system,
            "collection": collection,
            "path_tags": path_tags,
            "readability": readability,
            "media_density": media_density,
            "link_density": link_density,
            "quality_flags": quality_flags,
        }

    def _apply_llm_enrichment(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Apply LLM-based enrichment (mocked for now)."""
        if not self.llm_enabled:
            return {}

        text_md = doc.get("text_md", "")

        if not text_md.strip():
            return {}

        # Mock LLM responses for now - in real implementation would call LLM APIs
        summary = self._generate_summary(text_md)
        keywords = self._extract_keywords(text_md)
        taxonomy_labels = self._classify_taxonomy(text_md, doc)

        return {
            "summary": summary,
            "keywords": keywords,
            "taxonomy_labels": taxonomy_labels,
        }

    def _extract_collection(self, doc: Dict[str, Any]) -> Optional[str]:
        """Extract or infer document collection."""
        # Use existing collection if available (from DITA)
        if doc.get("collection"):
            return doc["collection"]

        # Infer collection from space_key or source patterns
        space_key = doc.get("space_key")
        if space_key:
            return space_key.lower()

        # Fallback to source system
        return doc.get("source_system", "unknown")

    def _extract_path_tags(self, doc: Dict[str, Any]) -> List[str]:
        """Extract or generate path-based tags."""
        # Use existing path_tags if available (from DITA)
        if doc.get("path_tags"):
            return doc["path_tags"]

        tags = []

        # Add tags based on breadcrumbs
        breadcrumbs = doc.get("breadcrumbs", [])
        if breadcrumbs:
            # Convert breadcrumbs to tags (lowercase, no spaces)
            for crumb in breadcrumbs[:-1]:  # Exclude the page title itself
                tag = re.sub(r"[^\w\-]", "", crumb.lower().replace(" ", "-"))
                if tag and len(tag) > 2:
                    tags.append(tag)

        # Add tags based on URL structure
        url = doc.get("url", "")
        if url and "/pages/" in url:
            # Extract meaningful parts from URL
            if "/spaces/" in url:
                parts = url.split("/spaces/")[1].split("/")
                if len(parts) > 2:  # space_key/pages/page_id/title
                    space_part = parts[0]
                    if space_part and space_part.lower() not in tags:
                        tags.append(space_part.lower())

        # Add tags based on content analysis
        text_md = doc.get("text_md", "")
        if "# API" in text_md or "## API" in text_md:
            tags.append("api")
        if "# Installation" in text_md or "## Installation" in text_md:
            tags.append("installation")
        if "# Configuration" in text_md or "## Configuration" in text_md:
            tags.append("configuration")

        return list(dict.fromkeys(tags))  # Remove duplicates, preserve order

    def _compute_readability(self, text_md: str) -> Dict[str, float]:
        """Compute readability metrics."""
        if not text_md or not text_md.strip():
            return {
                "chars_per_word": 0.0,
                "words_per_paragraph": 0.0,
                "heading_ratio": 0.0,
            }

        # Remove markdown formatting for word/char counting
        clean_text = re.sub(r"[#*`\[\]()_]", "", text_md)
        clean_text = re.sub(r"\n+", " ", clean_text)

        words = clean_text.split()
        word_count = len(words)
        char_count = len("".join(words))

        # Count paragraphs (double newlines or headings)
        paragraphs = re.split(r"\n\s*\n|^#", text_md)
        paragraph_count = len([p for p in paragraphs if p.strip()])

        # Count headings
        heading_count = len(re.findall(r"^#+\s", text_md, re.MULTILINE))

        # Ensure we don't divide by zero
        chars_per_word = char_count / word_count if word_count > 0 else 0.0
        words_per_paragraph = (
            word_count / paragraph_count if paragraph_count > 0 else 0.0
        )
        heading_ratio = (
            heading_count / paragraph_count if paragraph_count > 0 else 0.0
        )

        return {
            "chars_per_word": round(chars_per_word, 2),
            "words_per_paragraph": round(words_per_paragraph, 2),
            "heading_ratio": round(heading_ratio, 3),
        }

    def _compute_media_density(
        self, text_md: str, attachments: List[Dict]
    ) -> float:
        """Compute media density (media refs per 1000 chars)."""
        if not text_md:
            return 0.0

        # Count image references in markdown
        image_refs = len(re.findall(r"!\[.*?\]", text_md))

        # Add attachment count
        media_count = image_refs + len(attachments)

        chars = len(text_md)
        density = (media_count * 1000) / chars if chars > 0 else 0.0

        return round(density, 2)

    def _compute_link_density(self, text_md: str, links: List[str]) -> float:
        """Compute link density (links per 1000 chars)."""
        if not text_md:
            return 0.0

        # Count markdown link references
        link_refs = len(re.findall(r"\[.*?\]\(.*?\)", text_md))

        # Use the higher of detected links or provided links
        link_count = max(link_refs, len(links))

        chars = len(text_md)
        density = (link_count * 1000) / chars if chars > 0 else 0.0

        return round(density, 2)

    def _determine_quality_flags(
        self, doc: Dict[str, Any], text_md: str, attachments: List[Dict]
    ) -> List[str]:
        """Determine quality flags for the document."""
        flags = []

        # Empty body check
        if not text_md.strip():
            flags.append("empty_body")

        # Length checks
        word_count = len(text_md.split()) if text_md else 0
        if word_count < 10:
            flags.append("too_short")
        elif word_count > 10000:
            flags.append("too_long")

        # Image-only check
        if attachments and word_count < 50:
            # Check if most content is just image references
            image_refs = len(re.findall(r"!\[.*?\]", text_md))
            if image_refs >= len(attachments) and word_count < 100:
                flags.append("image_only")

        # No content structure
        if text_md and not re.search(r"^#+\s", text_md, re.MULTILINE):
            if word_count > 200:  # Only flag longer docs without headings
                flags.append("no_structure")

        # Broken links (basic check)
        broken_link_patterns = [r"\[.*?\]\(\s*\)", r"\[.*?\]\(#\)"]
        for pattern in broken_link_patterns:
            if re.search(pattern, text_md):
                flags.append("broken_links")
                break

        return flags

    def _generate_summary(self, text_md: str) -> str:
        """Generate a short summary (mocked)."""
        # Mock summary generation - in real implementation would use LLM
        sentences = re.split(r"[.!?]\s+", text_md)
        first_sentence = sentences[0].strip() if sentences else ""

        # Truncate to 300 chars
        if len(first_sentence) > 300:
            first_sentence = first_sentence[:297] + "..."

        return first_sentence

    def _extract_keywords(self, text_md: str) -> List[str]:
        """Extract keywords (mocked)."""
        # Mock keyword extraction - in real implementation would use LLM
        # Simple heuristic: find capitalized words and common tech terms
        words = re.findall(r"\b[A-Z][a-z]+\b", text_md)
        tech_terms = re.findall(
            r"\b(?:API|JSON|XML|HTML|CSS|JavaScript|Python|Java|SQL|REST|HTTP|HTTPS|URL|ID|UUID)\b",
            text_md,
            re.IGNORECASE,
        )

        keywords = list(dict.fromkeys(words + tech_terms))  # Remove duplicates
        return keywords[:8]  # Limit to 8 keywords

    def _classify_taxonomy(
        self, text_md: str, doc: Dict[str, Any]
    ) -> List[str]:
        """Classify document into taxonomy labels (mocked)."""
        # Mock taxonomy classification - in real implementation would use LLM
        labels = []

        text_lower = text_md.lower()

        # Technical documentation categories
        if any(
            term in text_lower for term in ["api", "endpoint", "rest", "json"]
        ):
            labels.append("api-documentation")

        if any(
            term in text_lower
            for term in ["install", "setup", "configuration", "config"]
        ):
            labels.append("setup-guide")

        if any(
            term in text_lower
            for term in ["tutorial", "how to", "step by step", "guide"]
        ):
            labels.append("tutorial")

        if any(
            term in text_lower
            for term in ["release", "changelog", "version", "update"]
        ):
            labels.append("release-notes")

        if any(
            term in text_lower
            for term in ["troubleshoot", "error", "issue", "problem"]
        ):
            labels.append("troubleshooting")

        # Source system specific
        source_system = doc.get("source_system")
        if source_system:
            labels.append(f"source-{source_system}")

        return labels[:5]  # Limit to 5 labels

    def generate_suggested_edges(
        self, docs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Generate suggested edges between documents (mocked LLM)."""
        if not self.llm_enabled or len(docs) < 2:
            return []

        edges = []

        # Simple heuristic-based edge suggestions
        for i, doc1 in enumerate(docs):
            for doc2 in docs[i + 1 :]:
                edge = self._suggest_edge_between_docs(doc1, doc2)
                if edge:
                    edges.append(edge)
                    self.suggested_edges_count += 1

        return edges

    def _suggest_edge_between_docs(
        self, doc1: Dict[str, Any], doc2: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Suggest an edge between two documents."""
        # Skip if same document
        if doc1.get("id") == doc2.get("id"):
            return None

        text1 = doc1.get("text_md", "").lower()
        text2 = doc2.get("text_md", "").lower()

        # Check for explicit references
        doc2_title = doc2.get("title", "").lower()
        if doc2_title and doc2_title in text1:
            return {
                "from": doc1.get("id"),
                "to": doc2.get("id"),
                "type": "REFERENCES",
                "confidence": 0.8,
                "evidence": f"Document mentions '{doc2.get('title')}'",
            }

        # Check for topical similarity (simple keyword overlap)
        words1 = set(re.findall(r"\b\w{4,}\b", text1))
        words2 = set(re.findall(r"\b\w{4,}\b", text2))

        overlap = words1.intersection(words2)
        if len(overlap) >= 3:  # Lower threshold for testing
            confidence = min(0.7, len(overlap) / 20)
            return {
                "from": doc1.get("id"),
                "to": doc2.get("id"),
                "type": "RELATES_TO",
                "confidence": round(confidence, 2),
                "evidence": f"Shared keywords: {', '.join(sorted(list(overlap))[:5])}",
            }

        return None

    def compute_enrichment_fingerprint(
        self, enriched_doc: Dict[str, Any]
    ) -> str:
        """Compute a stable SHA256 fingerprint for enrichment state."""
        # Select fields that should trigger re-embedding if changed
        fingerprint_fields = {
            "enrichment_version": self.enrichment_version,
            "collection": enriched_doc.get("collection"),
            "path_tags": enriched_doc.get("path_tags", []),
            "readability": enriched_doc.get("readability", {}),
            "quality_flags": enriched_doc.get("quality_flags", []),
        }

        # Include LLM fields if they exist
        if "summary" in enriched_doc:
            fingerprint_fields["summary"] = enriched_doc["summary"]
        if "keywords" in enriched_doc:
            fingerprint_fields["keywords"] = enriched_doc["keywords"]
        if "taxonomy_labels" in enriched_doc:
            fingerprint_fields["taxonomy_labels"] = enriched_doc[
                "taxonomy_labels"
            ]

        # Create canonical JSON representation
        canonical_json = json.dumps(
            fingerprint_fields, sort_keys=True, ensure_ascii=False
        )

        # Compute SHA256
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def enrich_from_normalized(
    run_id: str,
    llm_enabled: bool = False,
    max_docs: Optional[int] = None,
    budget: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    emit_event: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Enrich normalized documents with metadata and quality signals.

    Args:
        run_id: The run ID to process
        llm_enabled: Whether to use LLM for enrichment
        max_docs: Maximum number of documents to process
        budget: Budget limit for LLM usage (soft limit)
        progress_callback: Optional callback for progress updates
        emit_event: Optional callback for NDJSON events

    Returns:
        Dict with enrichment statistics
    """
    from ....core.artifacts import phase_dir

    # Setup paths
    normalize_dir = phase_dir(run_id, "normalize")
    enrich_dir = phase_dir(run_id, "enrich")
    enrich_dir.mkdir(parents=True, exist_ok=True)

    input_file = normalize_dir / "normalized.ndjson"
    if not input_file.exists():
        raise FileNotFoundError(f"Normalized file not found: {input_file}")

    # Output files
    enriched_file = enrich_dir / "enriched.jsonl"
    fingerprints_file = enrich_dir / "fingerprints.jsonl"
    suggested_edges_file = enrich_dir / "suggested_edges.jsonl"

    # Initialize enricher
    enricher = DocumentEnricher(
        llm_enabled=llm_enabled,
        max_docs=max_docs,
        budget=budget,
    )

    start_time = time.time()

    if emit_event:
        emit_event(
            "enrich.begin",
            run_id=run_id,
            llm_enabled=llm_enabled,
            max_docs=max_docs,
        )

    # Process documents
    docs_for_edges: List[Dict[str, Any]] = []

    with (
        open(input_file, "r", encoding="utf-8") as fin,
        open(enriched_file, "w", encoding="utf-8") as fout_enriched,
        open(fingerprints_file, "w", encoding="utf-8") as fout_fingerprints,
    ):
        for line_num, line in enumerate(fin, 1):
            if max_docs and line_num > max_docs:
                break

            doc = json.loads(line.strip())

            # Enrich document
            enriched = enricher.enrich_document(doc)

            # Compute fingerprint
            fingerprint = enricher.compute_enrichment_fingerprint(enriched)

            # Write enriched document
            fout_enriched.write(
                json.dumps(enriched, ensure_ascii=False) + "\n"
            )

            # Write fingerprint
            fingerprint_rec = {
                "id": doc.get("id"),
                "enrichment_version": enricher.enrichment_version,
                "fingerprint_sha256": fingerprint,
            }
            fout_fingerprints.write(
                json.dumps(fingerprint_rec, ensure_ascii=False) + "\n"
            )

            # Collect docs for edge generation
            if (
                llm_enabled and len(docs_for_edges) < 1000
            ):  # Limit for performance
                docs_for_edges.append(doc)

            # Emit progress
            if emit_event and line_num % 100 == 0:
                emit_event(
                    "enrich.doc",
                    doc_id=doc.get("id"),
                    docs_processed=line_num,
                    quality_flags=enriched.get("quality_flags", []),
                )

            if progress_callback and line_num % 50 == 0:
                elapsed = time.time() - start_time
                rate = line_num / elapsed if elapsed > 0 else 0
                progress_callback(line_num, rate, elapsed, enricher.docs_llm)

    # Generate suggested edges if LLM is enabled
    if llm_enabled:
        if emit_event:
            emit_event("enrich.edges_begin", total_docs=len(docs_for_edges))

        edges = enricher.generate_suggested_edges(docs_for_edges)

        with open(suggested_edges_file, "w", encoding="utf-8") as fout_edges:
            for edge in edges:
                fout_edges.write(json.dumps(edge, ensure_ascii=False) + "\n")
                if emit_event:
                    emit_event("enrich.suggested_edge", **edge)

    duration = time.time() - start_time

    # Generate statistics
    stats = {
        "run_id": run_id,
        "docs_total": enricher.docs_processed,
        "docs_llm": enricher.docs_llm,
        "suggested_edges_total": enricher.suggested_edges_count,
        "quality_flags_counts": enricher.quality_flags_counts,
        "duration_seconds": round(duration, 2),
        "llm_enabled": llm_enabled,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    if emit_event:
        emit_event("enrich.end", **stats)

    log.info("enrich.complete", **stats)
    return stats
