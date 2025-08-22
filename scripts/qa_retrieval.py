#!/usr/bin/env python3
"""
Standalone N2S Retrieval QA Harness

A read-only script that exercises the existing Trailblazer retriever over curated
N2S questions and produces QA artifacts with health metrics.

Key invariants:
- Read-only database access (no writes)
- Uses existing retriever (no reimplementation)
- Filters on provider="openai" and dimension=1536 by default
- No production code changes
- Standalone script (not a CLI command)
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

# Load .env file if it exists (same approach as Trailblazer scripts)
env_file = Path(".env")
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key] = value

# Import existing Trailblazer components
try:
    from trailblazer.retrieval.dense import (
        create_retriever,  # type: ignore[import-untyped]
    )
    from trailblazer.retrieval.pack import (  # type: ignore[import-untyped]
        pack_context,
    )
except ImportError as e:
    print(f"Error: Could not import Trailblazer components: {e}")
    print("Make sure you're running from the project root with the virtual environment activated.")
    sys.exit(1)


def _canon(phrase: str) -> str:
    """Canonicalize a phrase for matching."""
    return phrase.lower().strip()


def expand_expect_phrase(phrase: str, lexicon: dict[str, list[str]]) -> list[str]:
    """Expand a phrase using the domain lexicon."""
    # Check if phrase is a key in the lexicon
    if phrase in lexicon:
        return lexicon[phrase]

    # Check if phrase matches any lexicon values
    expanded = [phrase]  # Always include original
    for _key, variants in lexicon.items():
        if phrase in variants:
            expanded.extend(variants)
            break

    return list(set(expanded))  # Remove duplicates


def expect_ok(
    hits: list[dict[str, Any]], expect_phrases: list[str], lexicon: dict[str, list[str]] | None = None
) -> tuple[bool, list[str]]:
    """Check if expected phrases are present in hits, using lexicon expansion."""
    if not expect_phrases:
        return True, []

    if not hits:
        return False, ["No hits returned"]

    notes = []
    all_text = " ".join(hit.get("text_md", "") for hit in hits).lower()

    for phrase in expect_phrases:
        phrase_found = False

        # Check original phrase
        if _canon(phrase) in all_text:
            phrase_found = True
        else:
            # Try lexicon expansion if available
            if lexicon:
                expanded_phrases = expand_expect_phrase(phrase, lexicon)
                for expanded in expanded_phrases:
                    if _canon(expanded) in all_text:
                        phrase_found = True
                        break

        if not phrase_found:
            notes.append(f"Expected phrase not found: '{phrase}'")
            return False, notes

    return True, notes


def load_lexicon(lexicon_file: str | None = None) -> dict[str, list[str]] | None:
    """Load domain lexicon for phrase matching."""
    if not lexicon_file:
        return None

    try:
        with open(lexicon_file, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Warning: Could not load lexicon {lexicon_file}: {e}")
        return None


def load_queries(queries_file: str) -> list[dict[str, Any]]:
    """Load queries from YAML file."""
    queries_path = Path(queries_file)
    if not queries_path.exists():
        raise FileNotFoundError(f"Queries file not found: {queries_file}")

    with open(queries_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Handle both list format and dict with queries key
    if isinstance(data, list):
        queries = data
    elif isinstance(data, dict) and "queries" in data:
        queries = data["queries"]
    else:
        raise ValueError("YAML file must contain a list of queries or a dict with 'queries' key")

    # Normalize query format: ensure 'text' field exists (map from 'q' if needed)
    normalized_queries = []
    for query in queries:
        if "text" not in query and "q" in query:
            query["text"] = query["q"]
        if "text" not in query:
            raise ValueError(f"Query missing 'text' field: {query}")
        normalized_queries.append(query)

    return normalized_queries


def compute_metrics(
    hits: list[dict[str, Any]], expect_phrases: list[str] | None = None, lexicon: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """Compute health metrics for retrieval results."""
    if not hits:
        return {
            "diversity": 0,
            "traceability_ok": True,
            "duplication_ok": True,
            "tie_rate_ok": True,
            "expect_ok": bool(not expect_phrases),
            "notes": ["No hits returned"],
        }

    notes = []

    # Diversity: unique doc_id count
    unique_docs = set(hit.get("doc_id", "") for hit in hits)
    diversity = len(unique_docs)

    # Traceability: all hits have non-empty title and url
    traceability_ok = all(hit.get("title", "").strip() and hit.get("url", "").strip() for hit in hits)
    if not traceability_ok:
        notes.append("Some hits missing title or url")

    # Duplication: no repeated (doc_id, chunk_id) pairs
    seen_pairs = set()
    duplication_ok = True
    for hit in hits:
        pair = (hit.get("doc_id", ""), hit.get("chunk_id", ""))
        if pair in seen_pairs:
            duplication_ok = False
            break
        seen_pairs.add(pair)
    if not duplication_ok:
        notes.append("Duplicate (doc_id, chunk_id) pairs found")

    # Tie rate: percentage of identical scores
    scores = [hit.get("score", 0.0) for hit in hits]
    if len(scores) > 1:
        score_counts = Counter(scores)
        max_ties = max(score_counts.values())
        tie_rate = max_ties / len(scores)
        tie_rate_ok = tie_rate <= 0.30
        if not tie_rate_ok:
            notes.append(f"High tie rate: {tie_rate:.1%}")
    else:
        tie_rate_ok = True

    # Expect: use improved lexicon-based matching
    expect_ok_result, expect_notes = expect_ok(hits, expect_phrases or [], lexicon)
    notes.extend(expect_notes)

    return {
        "diversity": diversity,
        "traceability_ok": traceability_ok,
        "duplication_ok": duplication_ok,
        "tie_rate_ok": tie_rate_ok,
        "expect_ok": expect_ok_result,
        "notes": notes,
    }


def run_single_query(
    query: dict[str, Any],
    retriever: Any,
    top_k: int,
    budgets: list[int] | None = None,
    enable_expansion: bool = False,
    lexicon: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Run a single query and return hits plus packed contexts."""
    query_text = query["text"]

    try:
        # Retrieve hits
        if enable_expansion and lexicon:
            hits = retrieve_with_expansion(query_text, retriever, top_k, lexicon)
        else:
            hits = retriever.search(query_text, top_k=top_k)

        # Convert hits to serializable format and add source_system inference
        serializable_hits = []
        for hit in hits:
            # Infer source_system from URL
            url = hit.get("url", "")
            if "confluence" in url.lower():
                source_system = "confluence"
            elif "dita" in url.lower() or ".xml" in url.lower():
                source_system = "dita"
            else:
                source_system = "unknown"

            serializable_hit = {
                "chunk_id": hit.get("chunk_id", ""),
                "doc_id": hit.get("doc_id", ""),
                "title": hit.get("title", ""),
                "url": hit.get("url", ""),
                "text_md": hit.get("text_md", ""),
                "score": float(hit.get("score", 0.0)),
                "source_system": source_system,
            }
            serializable_hits.append(serializable_hit)

        # Pack contexts if budgets specified
        packed_contexts = {}
        if budgets:
            for budget in budgets:
                packed_contexts[budget] = pack_context(serializable_hits, budget)

        return serializable_hits, packed_contexts

    except Exception as e:
        print(f"Error processing query '{query_text}': {e}")
        return [], {}


def retrieve_with_expansion(
    query: str, retriever: Any, top_k: int, lexicon: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """Retrieve with query expansion using domain lexicon."""
    # Generate 2-4 query variants
    variants = [query]  # Always include original

    # Find lexicon terms that match the query
    query_lower = query.lower()
    for _term_group, synonyms in lexicon.items():
        if any(syn.lower() in query_lower for syn in synonyms):
            # Add some synonyms as variants
            for syn in synonyms[:2]:  # Limit to 2 variants per term
                if syn.lower() not in query_lower:
                    variants.append(f"{query} {syn}")
                    if len(variants) >= 4:  # Max 4 variants
                        break
            if len(variants) >= 4:
                break

    # Retrieve from all variants
    all_hits = []
    for variant in variants:
        try:
            variant_hits = retriever.search(variant, top_k=top_k * 2)
            all_hits.extend(variant_hits)
        except Exception as e:
            print(f"Warning: Failed to retrieve variant '{variant}': {e}")

    # Dedupe by (doc_id, chunk_id) and re-rank deterministically
    seen_pairs = set()
    unique_hits = []

    for hit in all_hits:
        pair = (hit.get("doc_id", ""), hit.get("chunk_id", ""))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            unique_hits.append(hit)

    # Sort by score descending, then doc_id, chunk_id for deterministic ordering
    unique_hits.sort(key=lambda x: (-x.get("score", 0.0), x.get("doc_id", ""), x.get("chunk_id", "")))

    return unique_hits[:top_k]


def save_query_artifacts(
    query: dict[str, Any],
    hits: list[dict[str, Any]],
    packed_contexts: dict[int, str],
    output_dir: Path,
) -> None:
    """Save query artifacts to files."""
    query_id = query["id"]

    # Save raw hits
    hits_file = output_dir / f"ask_{query_id}.json"
    with open(hits_file, "w", encoding="utf-8") as f:
        json.dump(hits, f, indent=2, ensure_ascii=False)

    # Save packed contexts for each budget
    for budget, context in packed_contexts.items():
        context_file = output_dir / f"context_{query_id}_{budget}.txt"
        with open(context_file, "w", encoding="utf-8") as f:
            f.write(context)


def create_readiness_report(
    queries: list[dict[str, Any]],
    query_results: list[dict[str, Any]],
    provider: str,
    dimension: int,
    top_k: int,
    budgets: list[int] | None = None,
) -> dict[str, Any]:
    """Create overall readiness report."""
    # Count passes for overall assessment
    traceability_passes = sum(1 for r in query_results if r["traceability_ok"])
    duplication_passes = sum(1 for r in query_results if r["duplication_ok"])
    diversity_passes = sum(1 for r in query_results if r["diversity"] >= 6)  # Target >= 6 of 12
    expect_passes = sum(1 for r in query_results if r["expect_ok"])

    total_queries = len(query_results)

    # Overall pass: all queries pass traceability_ok and duplication_ok,
    # and at least 80% pass diversity and expect_ok when present
    overall_pass = (
        traceability_passes == total_queries
        and duplication_passes == total_queries
        and (diversity_passes / total_queries >= 0.8 if total_queries > 0 else True)
        and (expect_passes / total_queries >= 0.8 if total_queries > 0 else True)
    )

    report = {
        "overall_pass": overall_pass,
        "provider": provider,
        "dimension": dimension,
        "top_k": top_k,
        "queries": query_results,
        "summary": {
            "total_queries": total_queries,
            "traceability_passes": traceability_passes,
            "duplication_passes": duplication_passes,
            "diversity_passes": diversity_passes,
            "expect_passes": expect_passes,
        },
    }

    if budgets:
        report["budgets"] = budgets

    return report


def create_overview_markdown(report: dict[str, Any]) -> str:
    """Create human-readable overview in Markdown format."""
    lines = [
        "# Retrieval QA Overview",
        "",
        f"**Overall Pass:** {report['overall_pass']}",
        f"**Provider:** {report['provider']}",
        f"**Dimension:** {report['dimension']}",
        f"**Top-K:** {report['top_k']}",
        "",
    ]

    if "budgets" in report:
        lines.extend([f"**Budgets:** {', '.join(map(str, report['budgets']))}", ""])

    lines.extend(
        [
            "## Query Results",
            "",
            "| ID | Diversity | Traceability | Duplication | Tie Rate | Expect | Notes |",
            "|----|-----------|--------------|-----------|---------|---------|----|",
        ]
    )

    for query_result in report["queries"]:
        query_id = query_result["id"]
        diversity = query_result["diversity"]
        traceability = "✓" if query_result["traceability_ok"] else "✗"
        duplication = "✓" if query_result["duplication_ok"] else "✗"
        tie_rate = "✓" if query_result["tie_rate_ok"] else "✗"
        expect = "✓" if query_result["expect_ok"] else "✗"
        notes = "; ".join(query_result["notes"]) if query_result["notes"] else ""

        lines.append(f"| {query_id} | {diversity} | {traceability} | {duplication} | {tie_rate} | {expect} | {notes} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="N2S Retrieval QA Harness - Test retrieval quality with curated questions"
    )
    parser.add_argument(
        "--queries-file",
        default="prompts/qa/queries_n2s.yaml",
        help="Path to YAML file with queries (default: prompts/qa/queries_n2s.yaml)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=12,
        help="Number of top results to retrieve (default: 12)",
    )
    parser.add_argument(
        "--budgets",
        help="Comma-separated character limits for context packing (optional)",
    )
    parser.add_argument(
        "--out",
        help="Output directory (default: var/retrieval_qc/<timestamp>/)",
    )
    parser.add_argument("--db-url", help="Database URL (optional; uses default if omitted)")
    parser.add_argument(
        "--provider",
        default="openai",
        help="Embedding provider (default: openai)",
    )
    parser.add_argument(
        "--dimension",
        type=int,
        default=1536,
        help="Embedding dimension (default: 1536)",
    )
    parser.add_argument(
        "--query-expansion",
        action="store_true",
        help="Enable query expansion using domain lexicon (default: False)",
    )

    args = parser.parse_args()

    # Parse budgets if provided
    budgets = None
    if args.budgets:
        try:
            budgets = [int(b.strip()) for b in args.budgets.split(",")]
        except ValueError:
            print("Error: Invalid budgets format. Use comma-separated integers.")
            sys.exit(1)

    # Set output directory
    if args.out:
        output_dir = Path(args.out)
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = Path("var") / "retrieval_qc" / timestamp

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Load queries
        queries = load_queries(args.queries_file)
        print(f"Loaded {len(queries)} queries from {args.queries_file}")

        # Load domain lexicon for improved phrase matching
        lexicon_file = Path("prompts/qa/domain_lexicon.yaml")
        lexicon = None
        if lexicon_file.exists():
            lexicon = load_lexicon(str(lexicon_file))
            print(f"Loaded domain lexicon with {len(lexicon) if lexicon else 0} term groups")
        else:
            print("Warning: Domain lexicon not found, using basic phrase matching")

        # Initialize retriever using the same factory as the ask command
        retriever = create_retriever(db_url=args.db_url, provider_name=args.provider, dim=args.dimension)

        # Process each query
        query_results = []

        for query in queries:
            query_id = query["id"]
            print(f"Processing query: {query_id}")

            # Run the query
            hits, packed_contexts = run_single_query(
                query, retriever, args.top_k, budgets, args.query_expansion, lexicon
            )

            # Compute metrics with lexicon
            expect_phrases = query.get("expect", [])
            metrics = compute_metrics(hits, expect_phrases, lexicon)

            # Save artifacts
            save_query_artifacts(query, hits, packed_contexts, output_dir)

            # Collect results
            query_result = {"id": query_id, **metrics}
            query_results.append(query_result)

        # Create readiness report
        report = create_readiness_report(
            queries,
            query_results,
            args.provider,
            args.dimension,
            args.top_k,
            budgets,
        )

        # Save readiness report
        readiness_file = output_dir / "readiness.json"
        with open(readiness_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Save overview markdown
        overview_md = create_overview_markdown(report)
        overview_file = output_dir / "overview.md"
        with open(overview_file, "w", encoding="utf-8") as f:
            f.write(overview_md)

        # Print summary
        print("\nSummary:")
        print(f"  Total queries: {len(queries)}")
        print(f"  Overall pass: {report['overall_pass']}")
        print(f"  Output directory: {output_dir}")

        # Exit with appropriate code
        sys.exit(0 if report["overall_pass"] else 1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
