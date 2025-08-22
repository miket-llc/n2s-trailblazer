"""
Expectation Harness v2 for deterministic query scoring.

This module provides simple, deterministic scoring using:
- Doc Anchors: Check if retrieved items contain expected document slugs
- Concept Groups: Check if retrieved contexts contain expected synonym groups
"""

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from ..core.logging import log

# Stopwords to filter out noise
STOPWORDS = {"experience", "solution", "issue"}


def stem_word(word: str) -> str:
    """
    Apply minimal stemming for -ing and -ed suffixes.

    Args:
        word: Input word to stem

    Returns:
        Stemmed word
    """
    if not word:
        return ""

    # Remove -ing suffix
    if word.endswith("ing") and len(word) > 4:
        word = word[:-3]
    # Remove -ed suffix
    elif word.endswith("ed") and len(word) > 3:
        word = word[:-2]

    return word


def canon(text: str) -> str:
    """
    Canonicalize text for consistent matching.

    Lowercase, strip accents, collapse whitespace, replace
    hyphen/emdash/underscore with space, drop punctuation.

    Args:
        text: Input text to canonicalize

    Returns:
        Canonicalized text
    """
    if not text:
        return ""

    # Convert to lowercase
    text = text.lower()

    # Remove accents
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    # Replace hyphens, emdashes, underscores with spaces
    text = re.sub(r"[-–—_]", " ", text)

    # Remove punctuation but preserve spaces
    text = re.sub(r"[^\w\s]", " ", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def contains_any(text: str, terms: list[str]) -> bool:
    """
    Check if text contains any of the given terms after canonicalization.

    Supports uni/bi-grams from any_of lists with token-boundary search.
    Applies minimal stemming and filters stopwords.

    Args:
        text: Text to search in
        terms: List of terms to search for

    Returns:
        True if any term is found, False otherwise
    """
    if not text or not terms:
        return False

    canon_text = canon(text)
    canon_terms = [canon(term) for term in terms if term]

    for term in canon_terms:
        if not term:
            continue

        # Skip stopwords
        if term in STOPWORDS:
            continue

        # Check if term is a complete word
        if re.search(rf"\b{re.escape(term)}\b", canon_text):
            return True

        # Check stemmed version
        stemmed_term = stem_word(term)
        if stemmed_term and stemmed_term != term:
            if re.search(rf"\b{re.escape(stemmed_term)}\b", canon_text):
                return True

    return False


def doc_slug(url: str, title: str) -> str:
    """
    Build document slug from URL or title.

    If URL is Confluence or Git, use trailing path/title.
    Otherwise, derive from title.

    Args:
        url: Document URL
        title: Document title

    Returns:
        Normalized slug
    """
    if not url and not title:
        return ""

    # Try to extract from URL first
    if url:
        # Confluence URLs: extract space key and title
        confluence_match = re.search(r"/pages/(\d+)/([^/?]+)", url)
        if confluence_match:
            return canon(confluence_match.group(2))

        # Git URLs: extract filename without extension
        git_match = re.search(r"/([^/]+?)(?:\.(?:md|txt|rst))?/?$", url)
        if git_match:
            return canon(git_match.group(1))

        # Generic URLs: extract last path component
        path_match = re.search(r"/([^/?]+)/?$", url)
        if path_match:
            return canon(path_match.group(1))

    # Fall back to title
    if title:
        return canon(title)

    return ""


def load_expectations() -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Load expectation data files.

    Returns:
        Tuple of (anchors, concepts) expectation data
    """
    expectations_dir = Path("prompts/qa/expectations")

    # Load anchors
    anchors_file = expectations_dir / "anchors.yaml"
    if not anchors_file.exists():
        log.warning("anchors.yaml not found, using empty anchors", file=str(anchors_file))
        anchors: dict[str, Any] = {}
    else:
        with open(anchors_file, encoding="utf-8") as f:
            anchors = yaml.safe_load(f) or {}

    # Load concepts
    concepts_file = expectations_dir / "concepts.yaml"
    if not concepts_file.exists():
        log.warning("concepts.yaml not found, using empty concepts", file=str(concepts_file))
        concepts: dict[str, Any] = {}
    else:
        with open(concepts_file, encoding="utf-8") as f:
            concepts = yaml.safe_load(f) or {}

    return anchors, concepts


def evaluate_query_expectations(
    query_id: str,
    retrieved_items: list[dict[str, Any]],
    top_k: int = 12,
    threshold: float = 0.7,
    mode: str = "doc+concept",
    expect_profile: str = "default",
) -> dict[str, Any]:
    """
    Evaluate query expectations using Doc Anchors and Concept Groups.

    Args:
        query_id: Query identifier
        retrieved_items: List of retrieved items with url, title, snippet fields
        top_k: Number of top items to consider (default: 12)
        threshold: Pass threshold for final score (default: 0.7)
        mode: Scoring mode: "doc+concept", "doc-only", or "concept-only"
        expect_profile: Expectation profile: "default", "n2s", etc.

    Returns:
        Dictionary with evaluation results
    """
    # Load expectations once
    anchors, concepts = load_expectations()

    # Get top-K items
    top_items = retrieved_items[:top_k] if retrieved_items else []

    # Extract document slugs from top items
    doc_slugs = []
    for item in top_items:
        url = item.get("url", "")
        title = item.get("title", "")
        slug = doc_slug(url, title)
        if slug:
            doc_slugs.append(slug)

    # Score A: Doc Anchors (1.0 if any slug matches, else 0.0)
    anchors_score = 0.0
    anchors_hit = []

    if mode in ["doc+concept", "doc-only"]:
        # Try N2S-specific anchors first if using n2s profile
        if expect_profile == "n2s" and f"ask_{query_id}" in anchors:
            expected_slugs = anchors[f"ask_{query_id}"].get("any_doc_slugs", [])
        elif query_id in anchors:
            expected_slugs = anchors[query_id].get("any_doc_slugs", [])
        else:
            expected_slugs = []

        for slug in doc_slugs:
            if slug in expected_slugs:
                anchors_score = 1.0
                anchors_hit.append(slug)
                break

    # Score B: Concept Groups (N-of-M scoring for N2S profile)
    concepts_score = 0.0
    missing_groups = []
    hit_groups = []

    if mode in ["doc+concept", "concept-only"]:
        if expect_profile == "n2s":
            # Use process groups for N2S queries
            if query_id in concepts.get("process_require_by_query", {}):
                required_groups = concepts["process_require_by_query"][query_id]
                groups_data = concepts.get("process_groups", {})

                if required_groups:
                    # N-of-M scoring: need at least 2 groups to pass
                    min_required = max(2, len(required_groups) // 2)
                    group_scores = []

                    for group_id in required_groups:
                        if group_id in groups_data:
                            group_terms = groups_data[group_id].get("any_of", [])

                            # Check if any term appears in concatenated contexts
                            all_context = " ".join(
                                [f"{item.get('title', '')} {item.get('snippet', '')}" for item in top_items]
                            )

                            if contains_any(all_context, group_terms):
                                group_scores.append(1.0)
                                hit_groups.append(group_id)
                            else:
                                group_scores.append(0.0)
                                missing_groups.append(group_id)
                        else:
                            # Group not found, count as 0.0
                            group_scores.append(0.0)
                            missing_groups.append(group_id)

                    if group_scores:
                        # Pass if at least min_required groups are present
                        concepts_score = 1.0 if sum(group_scores) >= min_required else 0.0
                else:
                    # Empty list of required groups, default to 1.0
                    concepts_score = 1.0
            else:
                # Query not in process_require_by_query, default to 1.0
                concepts_score = 1.0
        else:
            # Default profile: use original concept scoring
            if query_id in concepts.get("require_by_query", {}):
                required_groups = concepts["require_by_query"][query_id]
                groups_data = concepts.get("groups", {})

                if required_groups:
                    group_scores = []
                    for group_id in required_groups:
                        if group_id in groups_data:
                            group_terms = groups_data[group_id].get("any_of", [])

                            # Check if any term appears in concatenated contexts
                            all_context = " ".join(
                                [f"{item.get('title', '')} {item.get('snippet', '')}" for item in top_items]
                            )

                            if contains_any(all_context, group_terms):
                                group_scores.append(1.0)
                                hit_groups.append(group_id)
                            else:
                                group_scores.append(0.0)
                                missing_groups.append(group_id)
                        else:
                            # Group not found, count as 0.0
                            group_scores.append(0.0)
                            missing_groups.append(group_id)

                    if group_scores:
                        concepts_score = sum(group_scores) / len(group_scores)
                else:
                    # Empty list of required groups, default to 1.0
                    concepts_score = 1.0
            else:
                # Query not in require_by_query, default to 1.0
                concepts_score = 1.0

    # Calculate final score based on mode
    if mode == "doc-only":
        final_score = anchors_score
    elif mode == "concept-only":
        final_score = concepts_score
    else:  # doc+concept
        final_score = 0.6 * anchors_score + 0.4 * concepts_score

    # Determine pass/fail
    passed = final_score >= threshold

    return {
        "passed": passed,
        "score": final_score,
        "threshold": threshold,
        "mode": mode,
        "expect_profile": expect_profile,
        "anchors_score": anchors_score,
        "concepts_score": concepts_score,
        "anchors_hit": anchors_hit,
        "missing_groups": missing_groups,
        "hit_groups": hit_groups,
        "top_doc_slugs": doc_slugs,
        "top_k": top_k,
    }
