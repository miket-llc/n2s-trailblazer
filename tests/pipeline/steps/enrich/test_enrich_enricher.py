# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

"""Tests for document enrichment functionality."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from trailblazer.pipeline.steps.enrich.enricher import (
    DocumentEnricher,
    enrich_from_normalized,
)

# Mark all tests as integration tests (need database)
pytestmark = pytest.mark.integration


class TestDocumentEnricher:
    """Test the DocumentEnricher class."""

    def test_init_with_defaults(self):
        """Test enricher initialization with default values."""
        enricher = DocumentEnricher()
        assert enricher.llm_enabled is False
        assert enricher.max_docs is None
        assert enricher.budget is None
        assert enricher.enrichment_version == "v1"
        assert enricher.docs_processed == 0
        assert enricher.docs_llm == 0
        assert enricher.suggested_edges_count == 0
        assert enricher.quality_flags_counts == {}

    def test_init_with_parameters(self):
        """Test enricher initialization with custom parameters."""
        enricher = DocumentEnricher(llm_enabled=True, max_docs=100, budget="1000")
        assert enricher.llm_enabled is True
        assert enricher.max_docs == 100
        assert enricher.budget == "1000"

    def test_init_with_quality_parameters(self):
        """Test enricher initialization with quality parameters."""
        enricher = DocumentEnricher(min_quality=0.70, max_below_threshold_pct=0.15)
        assert enricher.min_quality == 0.70
        assert enricher.max_below_threshold_pct == 0.15
        assert enricher.quality_scores == []


class TestRuleBasedEnrichment:
    """Test rule-based enrichment features."""

    def test_extract_collection_from_existing(self):
        """Test collection extraction when already present."""
        enricher = DocumentEnricher()
        doc = {"collection": "my-collection", "source_system": "dita"}

        collection = enricher._extract_collection(doc)
        assert collection == "my-collection"

    def test_extract_collection_from_space_key(self):
        """Test collection extraction from space_key."""
        enricher = DocumentEnricher()
        doc = {"space_key": "DEV", "source_system": "confluence"}

        collection = enricher._extract_collection(doc)
        assert collection == "dev"

    def test_extract_collection_fallback(self):
        """Test collection extraction fallback to source_system."""
        enricher = DocumentEnricher()
        doc = {"source_system": "confluence"}

        collection = enricher._extract_collection(doc)
        assert collection == "confluence"

    def test_extract_path_tags_from_existing(self):
        """Test path tags extraction when already present."""
        enricher = DocumentEnricher()
        doc = {"path_tags": ["tag1", "tag2"], "source_system": "dita"}

        tags = enricher._extract_path_tags(doc)
        assert tags == ["tag1", "tag2"]

    def test_extract_path_tags_from_breadcrumbs(self):
        """Test path tags extraction from breadcrumbs."""
        enricher = DocumentEnricher()
        doc = {
            "breadcrumbs": ["Parent Space", "Sub Section", "Page Title"],
            "source_system": "confluence",
        }

        tags = enricher._extract_path_tags(doc)
        assert "parent-space" in tags
        assert "sub-section" in tags
        assert "page-title" not in tags  # Excludes the page title itself

    def test_extract_path_tags_from_url(self):
        """Test path tags extraction from URL."""
        enricher = DocumentEnricher()
        doc = {
            "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/123/title",
            "source_system": "confluence",
        }

        tags = enricher._extract_path_tags(doc)
        assert "dev" in tags

    def test_extract_path_tags_from_content(self):
        """Test path tags extraction from content analysis."""
        enricher = DocumentEnricher()
        doc = {
            "text_md": "# API Documentation\n\n## Installation Guide\n\n## Configuration",
            "source_system": "confluence",
        }

        tags = enricher._extract_path_tags(doc)
        assert "api" in tags
        assert "installation" in tags
        assert "configuration" in tags

    def test_compute_readability_empty(self):
        """Test readability computation for empty text."""
        enricher = DocumentEnricher()

        readability = enricher._compute_readability("")
        assert readability["chars_per_word"] == 0.0
        assert readability["words_per_paragraph"] == 0.0
        assert readability["heading_ratio"] == 0.0

    def test_compute_readability_normal(self):
        """Test readability computation for normal text."""
        enricher = DocumentEnricher()
        text = "# Heading\n\nThis is a paragraph with several words.\n\nAnother paragraph here."

        readability = enricher._compute_readability(text)
        assert readability["chars_per_word"] > 0
        assert readability["words_per_paragraph"] > 0
        assert readability["heading_ratio"] > 0

    def test_compute_media_density(self):
        """Test media density computation."""
        enricher = DocumentEnricher()
        text = "![image1](url1) Some text ![image2](url2)"
        attachments = [{"filename": "doc.pdf"}]

        density = enricher._compute_media_density(text, attachments)
        assert density > 0  # Should detect 2 images + 1 attachment

    def test_compute_link_density(self):
        """Test link density computation."""
        enricher = DocumentEnricher()
        text = "Visit [example](http://example.com) and [other](http://other.com)"
        links = ["http://example.com", "http://other.com"]

        density = enricher._compute_link_density(text, links)
        assert density > 0

    def test_determine_quality_flags_empty_body(self):
        """Test quality flag detection for empty body."""
        enricher = DocumentEnricher()
        doc = {"id": "test", "source_system": "confluence"}

        flags = enricher._determine_quality_flags(doc, "", [])
        assert "empty_body" in flags

    def test_determine_quality_flags_too_short(self):
        """Test quality flag detection for too short content."""
        enricher = DocumentEnricher()
        doc = {"id": "test", "source_system": "confluence"}

        flags = enricher._determine_quality_flags(doc, "Short", [])
        assert "too_short" in flags

    def test_determine_quality_flags_too_long(self):
        """Test quality flag detection for too long content."""
        enricher = DocumentEnricher()
        doc = {"id": "test", "source_system": "confluence"}
        long_text = "word " * 10001  # Over 10000 words

        flags = enricher._determine_quality_flags(doc, long_text, [])
        assert "too_long" in flags

    def test_determine_quality_flags_image_only(self):
        """Test quality flag detection for image-only content."""
        enricher = DocumentEnricher()
        doc = {"id": "test", "source_system": "confluence"}
        text = "![image](url)"
        attachments = [{"filename": "image.jpg"}]

        flags = enricher._determine_quality_flags(doc, text, attachments)
        assert "image_only" in flags

    def test_determine_quality_flags_no_structure(self):
        """Test quality flag detection for no structure."""
        enricher = DocumentEnricher()
        doc = {"id": "test", "source_system": "confluence"}
        text = "This is a long text without any headings. " * 50  # Over 200 words

        flags = enricher._determine_quality_flags(doc, text, [])
        assert "no_structure" in flags

    def test_determine_quality_flags_broken_links(self):
        """Test quality flag detection for broken links."""
        enricher = DocumentEnricher()
        doc = {"id": "test", "source_system": "confluence"}
        text = "Visit [broken link]() or [another](#)"

        flags = enricher._determine_quality_flags(doc, text, [])
        assert "broken_links" in flags


class TestLLMEnrichment:
    """Test LLM-based enrichment features (mocked)."""

    def test_apply_llm_enrichment_disabled(self):
        """Test that LLM enrichment returns empty when disabled."""
        enricher = DocumentEnricher(llm_enabled=False)
        doc = {"text_md": "Some content", "source_system": "confluence"}

        result = enricher._apply_llm_enrichment(doc)
        assert result == {}

    def test_apply_llm_enrichment_empty_text(self):
        """Test LLM enrichment with empty text."""
        enricher = DocumentEnricher(llm_enabled=True)
        doc = {"text_md": "", "source_system": "confluence"}

        result = enricher._apply_llm_enrichment(doc)
        assert result == {}

    def test_apply_llm_enrichment_normal(self):
        """Test LLM enrichment with normal text."""
        enricher = DocumentEnricher(llm_enabled=True)
        doc = {
            "text_md": "This is API documentation for REST endpoints.",
            "source_system": "confluence",
        }

        result = enricher._apply_llm_enrichment(doc)
        assert "summary" in result
        assert "keywords" in result
        assert "taxonomy_labels" in result

    def test_generate_summary(self):
        """Test summary generation."""
        enricher = DocumentEnricher()
        text = "This is the first sentence. This is the second sentence."

        summary = enricher._generate_summary(text)
        assert "This is the first sentence" in summary
        assert len(summary) <= 300

    def test_extract_keywords(self):
        """Test keyword extraction."""
        enricher = DocumentEnricher()
        text = "This API uses JSON and HTTP requests to REST endpoints."

        keywords = enricher._extract_keywords(text)
        assert len(keywords) <= 8
        # Should find some tech terms
        tech_terms = [k for k in keywords if k.upper() in ["API", "JSON", "HTTP", "REST"]]
        assert len(tech_terms) > 0

    def test_classify_taxonomy(self):
        """Test taxonomy classification."""
        enricher = DocumentEnricher()
        text = "This is API documentation for REST endpoints."
        doc = {"source_system": "confluence"}

        labels = enricher._classify_taxonomy(text, doc)
        assert len(labels) <= 5
        assert "api-documentation" in labels
        assert "source-confluence" in labels


class TestSuggestedEdges:
    """Test suggested edge generation."""

    def test_generate_suggested_edges_disabled(self):
        """Test that no edges are generated when LLM is disabled."""
        enricher = DocumentEnricher(llm_enabled=False)
        docs = [
            {"id": "1", "text_md": "Content 1"},
            {"id": "2", "text_md": "Content 2"},
        ]

        edges = enricher.generate_suggested_edges(docs)
        assert edges == []

    def test_generate_suggested_edges_too_few_docs(self):
        """Test that no edges are generated with too few docs."""
        enricher = DocumentEnricher(llm_enabled=True)
        docs = [{"id": "1", "text_md": "Content 1"}]

        edges = enricher.generate_suggested_edges(docs)
        assert edges == []

    def test_suggest_edge_references(self):
        """Test edge suggestion based on title references."""
        enricher = DocumentEnricher(llm_enabled=True)
        doc1 = {
            "id": "1",
            "text_md": "See Installation Guide for details.",
            "title": "API Docs",
        }
        doc2 = {
            "id": "2",
            "text_md": "How to install the software.",
            "title": "Installation Guide",
        }

        edge = enricher._suggest_edge_between_docs(doc1, doc2)
        assert edge is not None
        assert edge["from"] == "1"
        assert edge["to"] == "2"
        assert edge["type"] == "REFERENCES"
        assert edge["confidence"] == 0.8

    def test_suggest_edge_similarity(self):
        """Test edge suggestion based on content similarity."""
        enricher = DocumentEnricher(llm_enabled=True)
        doc1 = {
            "id": "1",
            "text_md": "This document covers authentication configuration setup procedures",
            "title": "Auth Setup",
        }
        doc2 = {
            "id": "2",
            "text_md": "Authentication configuration requires these setup steps",
            "title": "Auth Config",
        }

        edge = enricher._suggest_edge_between_docs(doc1, doc2)
        assert edge is not None
        assert edge["type"] == "RELATES_TO"
        assert 0 < edge["confidence"] <= 0.7

    def test_suggest_edge_same_document(self):
        """Test that no edge is suggested for the same document."""
        enricher = DocumentEnricher(llm_enabled=True)
        doc = {"id": "1", "text_md": "Content", "title": "Title"}

        edge = enricher._suggest_edge_between_docs(doc, doc)
        assert edge is None


class TestEnrichmentFingerprint:
    """Test enrichment fingerprint computation."""

    def test_compute_fingerprint_deterministic(self):
        """Test that fingerprints are deterministic."""
        enricher = DocumentEnricher()
        enriched_doc = {
            "collection": "test-collection",
            "path_tags": ["tag1", "tag2"],
            "readability": {"chars_per_word": 5.0},
            "quality_flags": ["flag1"],
        }

        fingerprint1 = enricher.compute_enrichment_fingerprint(enriched_doc)
        fingerprint2 = enricher.compute_enrichment_fingerprint(enriched_doc)

        assert fingerprint1 == fingerprint2
        assert len(fingerprint1) == 64  # SHA256 hex length

    def test_compute_fingerprint_changes_with_content(self):
        """Test that fingerprints change when content changes."""
        enricher = DocumentEnricher()

        doc1 = {
            "collection": "test-collection",
            "path_tags": ["tag1"],
            "readability": {"chars_per_word": 5.0},
        }

        doc2 = {
            "collection": "test-collection",
            "path_tags": ["tag2"],  # Different tag
            "readability": {"chars_per_word": 5.0},
        }

        fingerprint1 = enricher.compute_enrichment_fingerprint(doc1)
        fingerprint2 = enricher.compute_enrichment_fingerprint(doc2)

        assert fingerprint1 != fingerprint2

    def test_compute_fingerprint_includes_llm_fields(self):
        """Test that fingerprints include LLM fields when present."""
        enricher = DocumentEnricher()

        doc_without_llm = {
            "collection": "test-collection",
            "path_tags": ["tag1"],
        }

        doc_with_llm = {
            "collection": "test-collection",
            "path_tags": ["tag1"],
            "summary": "Test summary",
            "keywords": ["keyword1"],
        }

        fingerprint1 = enricher.compute_enrichment_fingerprint(doc_without_llm)
        fingerprint2 = enricher.compute_enrichment_fingerprint(doc_with_llm)

        assert fingerprint1 != fingerprint2


class TestDocumentEnrichmentIntegration:
    """Integration tests for document enrichment."""

    def test_enrich_document_rule_based_only(self):
        """Test document enrichment with rule-based only."""
        enricher = DocumentEnricher(llm_enabled=False)
        doc = {
            "id": "test-doc",
            "source_system": "confluence",
            "space_key": "DEV",
            "text_md": "# API Guide\n\nThis is documentation.",
            "attachments": [],
            "links": [],
        }

        enriched = enricher.enrich_document(doc)

        assert enriched["id"] == "test-doc"
        assert enriched["source_system"] == "confluence"
        assert enriched["collection"] == "dev"
        assert "api" in enriched["path_tags"]
        assert "readability" in enriched
        assert "quality_flags" in enriched
        assert enricher.docs_processed == 1
        assert enricher.docs_llm == 0

    def test_enrich_document_with_llm(self):
        """Test document enrichment with LLM enabled."""
        enricher = DocumentEnricher(llm_enabled=True)
        doc = {
            "id": "test-doc",
            "source_system": "confluence",
            "text_md": "This API documentation covers REST endpoints.",
            "attachments": [],
            "links": [],
        }

        enriched = enricher.enrich_document(doc)

        assert "summary" in enriched
        assert "keywords" in enriched
        assert "taxonomy_labels" in enriched
        assert enricher.docs_processed == 1
        assert enricher.docs_llm == 1


class TestEnrichFromNormalized:
    """Test the main enrich_from_normalized function."""

    def test_enrich_from_normalized_missing_file(self):
        """Test error handling when normalized file is missing."""
        with pytest.raises(FileNotFoundError, match="Normalized file not found"):
            enrich_from_normalized("nonexistent-run-id")

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_from_normalized_success(self, mock_phase_dir):
        """Test successful enrichment from normalized file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup mock paths
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            mock_phase_dir.side_effect = lambda run_id, phase: {
                "normalize": normalize_dir,
                "enrich": enrich_dir,
            }[phase]

            # Create test normalized file
            normalized_file = normalize_dir / "normalized.ndjson"
            test_docs = [
                {
                    "id": "doc1",
                    "source_system": "confluence",
                    "text_md": "# API Documentation\n\nREST API guide.",
                    "attachments": [],
                    "links": [],
                },
                {
                    "id": "doc2",
                    "source_system": "dita",
                    "text_md": "Short text",
                    "attachments": [],
                    "links": [],
                },
            ]

            with open(normalized_file, "w", encoding="utf-8") as f:
                for doc in test_docs:
                    f.write(json.dumps(doc) + "\n")

            # Track events
            events = []

            def track_event(event_type, **kwargs):
                events.append({"type": event_type, **kwargs})

            # Run enrichment
            stats = enrich_from_normalized(
                run_id="test-run",
                llm_enabled=False,
                max_docs=None,
                emit_event=track_event,
            )

            # Verify output files exist
            assert (enrich_dir / "enriched.jsonl").exists()
            assert (enrich_dir / "fingerprints.jsonl").exists()

            # Verify statistics
            assert stats["run_id"] == "test-run"
            assert stats["docs_total"] == 2
            assert stats["docs_llm"] == 0
            assert stats["llm_enabled"] is False
            assert "duration_seconds" in stats
            assert "completed_at" in stats

            # Verify events were emitted
            event_types = [e["type"] for e in events]
            assert "enrich.begin" in event_types
            assert "enrich.end" in event_types

            # Verify enriched content
            with open(enrich_dir / "enriched.jsonl", encoding="utf-8") as f:
                enriched_lines = f.readlines()

            assert len(enriched_lines) == EXPECTED_COUNT_2

            enriched1 = json.loads(enriched_lines[0])
            assert enriched1["id"] == "doc1"
            assert enriched1["source_system"] == "confluence"
            assert "api" in enriched1["path_tags"]

            # Verify fingerprints
            with open(enrich_dir / "fingerprints.jsonl", encoding="utf-8") as f:
                fingerprint_lines = f.readlines()

            assert len(fingerprint_lines) == EXPECTED_COUNT_2

            fingerprint1 = json.loads(fingerprint_lines[0])
            assert fingerprint1["id"] == "doc1"
            assert fingerprint1["enrichment_version"] == "v1"
            assert len(fingerprint1["fingerprint_sha256"]) == 64

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_from_normalized_with_llm(self, mock_phase_dir):
        """Test enrichment with LLM enabled creates suggested edges."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup mock paths
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            mock_phase_dir.side_effect = lambda run_id, phase: {
                "normalize": normalize_dir,
                "enrich": enrich_dir,
            }[phase]

            # Create test normalized file
            normalized_file = normalize_dir / "normalized.ndjson"
            test_docs = [
                {
                    "id": "doc1",
                    "source_system": "confluence",
                    "text_md": "API authentication configuration setup",
                    "title": "API Auth",
                    "attachments": [],
                    "links": [],
                },
                {
                    "id": "doc2",
                    "source_system": "confluence",
                    "text_md": "Authentication setup configuration guide",
                    "title": "Auth Setup",
                    "attachments": [],
                    "links": [],
                },
            ]

            with open(normalized_file, "w", encoding="utf-8") as f:
                for doc in test_docs:
                    f.write(json.dumps(doc) + "\n")

            # Run enrichment with LLM
            stats = enrich_from_normalized(run_id="test-run", llm_enabled=True)

            # Verify LLM files exist
            assert (enrich_dir / "enriched.jsonl").exists()
            assert (enrich_dir / "suggested_edges.jsonl").exists()

            # Verify statistics
            assert stats["docs_llm"] == 2
            assert stats["llm_enabled"] is True
            assert stats["suggested_edges_total"] >= 0

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_from_normalized_max_docs(self, mock_phase_dir):
        """Test enrichment respects max_docs limit."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup mock paths
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            mock_phase_dir.side_effect = lambda run_id, phase: {
                "normalize": normalize_dir,
                "enrich": enrich_dir,
            }[phase]

            # Create test normalized file with 3 docs
            normalized_file = normalize_dir / "normalized.ndjson"
            test_docs = [
                {
                    "id": f"doc{i}",
                    "source_system": "confluence",
                    "text_md": f"Content {i}",
                }
                for i in range(1, 4)
            ]

            with open(normalized_file, "w", encoding="utf-8") as f:
                for doc in test_docs:
                    f.write(json.dumps(doc) + "\n")

            # Run enrichment with max_docs=2
            stats = enrich_from_normalized(run_id="test-run", max_docs=2)

            # Should only process 2 docs
            assert stats["docs_total"] == 2

            # Verify only 2 lines in output files
            with open(enrich_dir / "enriched.jsonl", encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == EXPECTED_COUNT_2


class TestNewSchemaFields:
    """Test the new enricher schema fields."""

    def test_enriched_document_has_new_fields(self):
        """Test that enriched documents contain all new schema fields."""
        enricher = DocumentEnricher()
        doc = {
            "id": "test-doc",
            "title": "Test Document",
            "text_md": "# Introduction\n\nThis is a test document with some content.\n\n## Section 1\n\nMore content here.",
            "source_system": "confluence",
            "attachments": [],
        }

        enriched = enricher.enrich_document(doc)

        # Check that all new fields are present
        assert "fingerprint" in enriched
        assert "section_map" in enriched
        assert "chunk_hints" in enriched
        assert "quality" in enriched
        assert "quality_score" in enriched

        # Check fingerprint structure
        fingerprint = enriched["fingerprint"]
        assert isinstance(fingerprint, dict)
        assert "doc" in fingerprint
        assert "version" in fingerprint
        assert fingerprint["version"] == "v1"

        # Check section_map structure
        section_map = enriched["section_map"]
        assert isinstance(section_map, list)
        if section_map:  # Should have sections for our test doc
            section = section_map[0]
            assert "heading" in section
            assert "level" in section
            assert "startChar" in section
            assert "endChar" in section
            assert "tokenStart" in section
            assert "tokenEnd" in section

        # Check chunk_hints structure
        chunk_hints = enriched["chunk_hints"]
        assert isinstance(chunk_hints, dict)
        assert "maxTokens" in chunk_hints
        assert "minTokens" in chunk_hints
        assert "preferHeadings" in chunk_hints
        assert "softBoundaries" in chunk_hints
        assert chunk_hints["maxTokens"] == 800
        assert chunk_hints["minTokens"] == 120
        assert chunk_hints["preferHeadings"] is True

        # Check quality metrics structure
        quality = enriched["quality"]
        assert isinstance(quality, dict)
        assert "word_count" in quality
        assert "char_count" in quality
        assert "heading_count" in quality

        # Check quality score
        quality_score = enriched["quality_score"]
        assert isinstance(quality_score, float)
        assert 0.0 <= quality_score <= 1.0

    def test_quality_score_stable_for_same_input(self):
        """Test that quality scoring is stable for the same input."""
        enricher = DocumentEnricher()
        doc = {
            "id": "test-doc",
            "title": "Test Document",
            "text_md": "# Introduction\n\nThis is a well-structured document with multiple sections.\n\n## Features\n\n- Good structure\n- Reasonable length\n- Clear headings",
            "source_system": "confluence",
            "attachments": [],
        }

        # Enrich the same document multiple times
        enriched1 = enricher.enrich_document(doc)
        enriched2 = enricher.enrich_document(doc)

        # Quality scores should be identical
        assert enriched1["quality_score"] == enriched2["quality_score"]

        # Quality metrics should be identical
        assert enriched1["quality"] == enriched2["quality"]

    def test_fingerprint_unchanged_for_whitespace_changes(self):
        """Test that fingerprint is unchanged for whitespace-only changes."""
        enricher = DocumentEnricher()

        doc1 = {
            "id": "test-doc",
            "title": "Test Document",
            "text_md": "# Introduction\n\nThis is a test document.",
            "source_system": "confluence",
        }

        doc2 = {
            "id": "test-doc",
            "title": "Test Document",
            "text_md": "# Introduction\n\n\nThis is a test document.\n",  # Extra whitespace
            "source_system": "confluence",
        }

        enriched1 = enricher.enrich_document(doc1)
        enriched2 = enricher.enrich_document(doc2)

        # Content fingerprints should be the same (whitespace normalized)
        assert enriched1["fingerprint"]["doc"] == enriched2["fingerprint"]["doc"]

    def test_quality_distribution_calculation(self):
        """Test quality distribution statistics calculation."""
        enricher = DocumentEnricher(min_quality=0.60, max_below_threshold_pct=0.20)

        # Create documents with different quality levels
        docs = [
            {
                "id": "good-doc",
                "title": "Good",
                "text_md": "# Title\n\nWell structured content with good length and headings.\n\n## Section\n\nMore content here.",
                "source_system": "confluence",
                "attachments": [],
            },
            {
                "id": "bad-doc",
                "title": "Bad",
                "text_md": "Short",
                "source_system": "confluence",
                "attachments": [],
            },
            {
                "id": "medium-doc",
                "title": "Medium",
                "text_md": "Some content but not great structure.",
                "source_system": "confluence",
                "attachments": [],
            },
            {
                "id": "empty-doc",
                "title": "Empty",
                "text_md": "",
                "source_system": "confluence",
                "attachments": [],
            },
        ]

        # Enrich all documents
        for doc in docs:
            enricher.enrich_document(doc)

        # Get quality distribution
        distribution = enricher.get_quality_distribution()

        assert isinstance(distribution, dict)
        assert "p50" in distribution
        assert "p90" in distribution
        assert "belowThresholdPct" in distribution
        assert "minQuality" in distribution
        assert "maxBelowThresholdPct" in distribution

        # Should have processed 4 documents
        assert len(enricher.quality_scores) == EXPECTED_COUNT_4

        # At least one document should be below threshold (the empty one)
        assert distribution["belowThresholdPct"] > 0.0

    def test_section_map_extraction(self):
        """Test section map extraction from markdown."""
        enricher = DocumentEnricher()
        text_md = """# Main Title

Some introduction text.

## Section 1

Content for section 1.

### Subsection 1.1

More detailed content.

## Section 2

Final section content.
"""

        section_map = enricher._extract_section_map(text_md)

        assert len(section_map) == 4  # Should find 4 headings

        # Check first heading
        first_section = section_map[0]
        assert first_section["heading"] == "Main Title"
        assert first_section["level"] == 1
        assert first_section["startChar"] == 0

        # Check second heading
        second_section = section_map[1]
        assert second_section["heading"] == "Section 1"
        assert second_section["level"] == 2

        # Check subsection
        third_section = section_map[2]
        assert third_section["heading"] == "Subsection 1.1"
        assert third_section["level"] == 3

    def test_chunk_hints_generation(self):
        """Test chunk hints generation."""
        enricher = DocumentEnricher()
        doc = {"id": "test"}
        text_md = """# Title

Introduction paragraph.

## Section 1

- List item 1
- List item 2

Some more content.

## Section 2

Final content.
"""

        chunk_hints = enricher._generate_chunk_hints(doc, text_md)

        assert chunk_hints["maxTokens"] == 800
        assert chunk_hints["minTokens"] == 120
        assert chunk_hints["preferHeadings"] is True

        # Should have found soft boundaries (headings and list items)
        soft_boundaries = chunk_hints["softBoundaries"]
        assert isinstance(soft_boundaries, list)
        assert len(soft_boundaries) > 0  # Should find at least some boundaries
