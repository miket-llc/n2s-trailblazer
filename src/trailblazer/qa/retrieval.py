"""
Retrieval QA harness for testing retrieval quality with domain queries.

This module provides functionality to:
- Run curated domain queries against the retrieval system
- Test multiple context budgets (character limits)
- Compute health metrics (diversity, tie rates, traceability)
- Generate readiness reports for operators
"""

from __future__ import annotations

import json
import math
import re
import yaml
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.logging import log
from ..retrieval.dense import DenseRetriever
from ..retrieval.pack import pack_context, group_by_doc


def load_queries(queries_file: str) -> List[Dict[str, Any]]:
    """
    Load queries from YAML file.

    Args:
        queries_file: Path to YAML file with queries

    Returns:
        List of query dictionaries with id, text, notes, expectations

    Raises:
        FileNotFoundError: If queries file doesn't exist
        yaml.YAMLError: If YAML is invalid
    """
    queries_path = Path(queries_file)
    if not queries_path.exists():
        raise FileNotFoundError(f"Queries file not found: {queries_file}")

    with open(queries_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Handle both list format and dict with queries key
    if isinstance(data, list):
        queries = data
    elif isinstance(data, dict) and "queries" in data:
        queries = data["queries"]
    else:
        raise ValueError(f"Invalid queries format in {queries_file}")

    # Validate query structure
    for i, query in enumerate(queries):
        if not isinstance(query, dict):
            raise ValueError(f"Query {i} must be a dictionary")
        if "id" not in query or "text" not in query:
            raise ValueError(f"Query {i} must have 'id' and 'text' fields")

    return queries


def create_query_slug(query_id: str) -> str:
    """
    Create a filesystem-safe slug from query ID.

    Args:
        query_id: Original query ID

    Returns:
        Filesystem-safe slug
    """
    # Replace non-alphanumeric characters with underscores
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", query_id)
    # Remove multiple consecutive underscores
    slug = re.sub(r"_+", "_", slug)
    # Remove leading/trailing underscores
    slug = slug.strip("_")
    return slug


def compute_doc_diversity(hits: List[Dict[str, Any]]) -> float:
    """
    Compute document diversity using Shannon entropy.

    Args:
        hits: List of hit dictionaries with doc_id

    Returns:
        Shannon entropy of document distribution (0 = no diversity, higher = more diverse)
    """
    if not hits:
        return 0.0

    # Count documents
    doc_counts = Counter(hit["doc_id"] for hit in hits)
    total = len(hits)

    # Compute Shannon entropy
    entropy = 0.0
    for count in doc_counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)

    return entropy


def compute_tie_rate(hits: List[Dict[str, Any]]) -> float:
    """
    Compute tie rate (frequency of identical scores).

    Args:
        hits: List of hit dictionaries with score

    Returns:
        Tie rate as fraction (0.0 = no ties, 1.0 = all tied)
    """
    if len(hits) <= 1:
        return 0.0

    # Count score frequencies
    scores = [hit["score"] for hit in hits]
    score_counts = Counter(scores)

    # Count tied scores (scores that appear more than once)
    tied_count = sum(count for count in score_counts.values() if count > 1)

    return tied_count / len(hits)


def compute_duplication_rate(hits: List[Dict[str, Any]]) -> float:
    """
    Compute duplication rate (repeated chunk_id/doc_id pairs).

    Args:
        hits: List of hit dictionaries with chunk_id and doc_id

    Returns:
        Duplication rate as fraction (0.0 = no duplicates, 1.0 = all duplicates)
    """
    if not hits:
        return 0.0

    # Count unique chunk_id/doc_id pairs
    pairs = [(hit["chunk_id"], hit["doc_id"]) for hit in hits]
    unique_pairs = set(pairs)

    return 1.0 - (len(unique_pairs) / len(pairs))


def check_traceability(hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Check traceability fields in hits.

    Args:
        hits: List of hit dictionaries

    Returns:
        Dictionary with traceability statistics
    """
    if not hits:
        return {
            "missing_title": 0,
            "missing_url": 0,
            "missing_source_system": 0,
            "total_hits": 0,
            "complete_hits": 0,
        }

    missing_title = 0
    missing_url = 0
    missing_source_system = 0
    complete_hits = 0

    for hit in hits:
        title = hit.get("title", "")
        url = hit.get("url", "")
        source_system = hit.get("source_system", "")

        if not title or title.strip() == "":
            missing_title += 1
        if not url or url.strip() == "":
            missing_url += 1
        if not source_system or source_system.strip() == "":
            missing_source_system += 1

        # Complete if all fields present
        if title and url:  # source_system might be optional
            complete_hits += 1

    return {
        "missing_title": missing_title,
        "missing_url": missing_url,
        "missing_source_system": missing_source_system,
        "total_hits": len(hits),
        "complete_hits": complete_hits,
    }


def evaluate_query_health(
    query: Dict[str, Any],
    hits_by_budget: Dict[int, List[Dict[str, Any]]],
    min_unique_docs: int,
    max_tie_rate: float,
    require_traceability: bool,
) -> Dict[str, Any]:
    """
    Evaluate health metrics for a single query across budgets.

    Args:
        query: Query dictionary
        hits_by_budget: Hits organized by budget
        min_unique_docs: Minimum unique documents threshold
        max_tie_rate: Maximum tie rate threshold
        require_traceability: Whether to require traceability fields

    Returns:
        Health evaluation dictionary
    """
    query_id = query["id"]
    results = {
        "query_id": query_id,
        "query_text": query["text"],
        "budgets": {},
        "overall_pass": True,
        "failure_reasons": [],
    }

    for budget, hits in hits_by_budget.items():
        # Compute metrics
        unique_docs = len(set(hit["doc_id"] for hit in hits))
        doc_diversity = compute_doc_diversity(hits)
        tie_rate = compute_tie_rate(hits)
        duplication_rate = compute_duplication_rate(hits)
        traceability = check_traceability(hits)

        budget_pass = True
        budget_failures = []

        # Check thresholds
        if unique_docs < min_unique_docs:
            budget_pass = False
            budget_failures.append(
                f"unique_docs={unique_docs} < {min_unique_docs}"
            )

        if tie_rate > max_tie_rate:
            budget_pass = False
            budget_failures.append(f"tie_rate={tie_rate:.3f} > {max_tie_rate}")

        if require_traceability:
            if traceability["missing_title"] > 0:
                budget_pass = False
                budget_failures.append(
                    f"missing_title={traceability['missing_title']}"
                )
            if traceability["missing_url"] > 0:
                budget_pass = False
                budget_failures.append(
                    f"missing_url={traceability['missing_url']}"
                )

        results["budgets"][budget] = {
            "total_hits": len(hits),
            "unique_docs": unique_docs,
            "doc_diversity": doc_diversity,
            "tie_rate": tie_rate,
            "duplication_rate": duplication_rate,
            "traceability": traceability,
            "pass": budget_pass,
            "failure_reasons": budget_failures,
        }

        if not budget_pass:
            results["overall_pass"] = False
            results["failure_reasons"].extend(
                [f"budget_{budget}: {reason}" for reason in budget_failures]
            )

    return results


def run_single_query(
    query: Dict[str, Any],
    budgets: List[int],
    retriever: DenseRetriever,
    top_k: int,
) -> Tuple[Dict[int, List[Dict[str, Any]]], Dict[int, str]]:
    """
    Run a single query across multiple budgets.

    Args:
        query: Query dictionary with id and text
        budgets: List of character budgets
        retriever: Dense retriever instance
        top_k: Number of top results to retrieve

    Returns:
        Tuple of (hits_by_budget, packed_contexts_by_budget)
    """
    query_text = query["text"]

    # Retrieve hits once
    hits = retriever.search(query_text, top_k=top_k)

    # Add source_system field (inferred from URL or set default)
    for hit in hits:
        url = hit.get("url", "")
        if "confluence" in url.lower():
            hit["source_system"] = "confluence"
        elif "dita" in url.lower() or ".xml" in url.lower():
            hit["source_system"] = "dita"
        else:
            hit["source_system"] = "unknown"

    # Pack contexts for each budget
    hits_by_budget = {}
    packed_contexts_by_budget = {}

    for budget in budgets:
        # Group by document to limit chunks per doc (max 3 chunks per doc)
        grouped_hits = group_by_doc(hits, max_chunks_per_doc=3)

        # Pack context within budget
        packed_context = pack_context(grouped_hits, max_chars=budget)

        hits_by_budget[budget] = grouped_hits
        packed_contexts_by_budget[budget] = packed_context

    return hits_by_budget, packed_contexts_by_budget


def save_query_artifacts(
    query: Dict[str, Any],
    hits_by_budget: Dict[int, List[Dict[str, Any]]],
    packed_contexts_by_budget: Dict[int, str],
    output_dir: Path,
) -> None:
    """
    Save per-query artifacts (ask_*.json files).

    Args:
        query: Query dictionary
        hits_by_budget: Hits organized by budget
        packed_contexts_by_budget: Packed contexts by budget
        output_dir: Output directory
    """
    query_slug = create_query_slug(query["id"])

    for budget in hits_by_budget:
        hits = hits_by_budget[budget]
        packed_context = packed_contexts_by_budget[budget]

        artifact = {
            "query": {
                "id": query["id"],
                "text": query["text"],
                "notes": query.get("notes", ""),
                "expectations": query.get("expectations", ""),
            },
            "budget": budget,
            "retrieved_hits": [
                {
                    "doc_id": hit["doc_id"],
                    "chunk_id": hit["chunk_id"],
                    "score": hit["score"],
                    "title": hit.get("title", ""),
                    "url": hit.get("url", ""),
                    "source_system": hit.get("source_system", ""),
                    "text_md": hit.get("text_md", ""),
                }
                for hit in hits
            ],
            "packed_context": packed_context,
            "metadata": {
                "total_hits": len(hits),
                "packed_chars": len(packed_context),
                "unique_docs": len(set(hit["doc_id"] for hit in hits)),
            },
        }

        # Save artifact
        artifact_file = output_dir / f"ask_{query_slug}_{budget}.json"
        with open(artifact_file, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2, ensure_ascii=False)


def compute_pack_stats(
    all_query_results: List[Dict[str, Any]], budgets: List[int]
) -> Dict[str, Any]:
    """
    Compute aggregate statistics across all queries and budgets.

    Args:
        all_query_results: List of query health evaluation results
        budgets: List of budgets tested

    Returns:
        Pack statistics dictionary
    """
    stats: Dict[str, Any] = {"budgets": {}}

    for budget in budgets:
        budget_stats = {
            "average_score": 0.0,
            "average_tie_rate": 0.0,
            "average_doc_diversity": 0.0,
            "average_unique_docs": 0.0,
            "queries": len(all_query_results),
        }

        if all_query_results:
            scores = []
            tie_rates = []
            doc_diversities = []
            unique_docs = []

            for result in all_query_results:
                budget_data = result["budgets"].get(budget, {})
                if budget_data:
                    # Average score from hits
                    hits = budget_data.get("total_hits", 0)
                    if hits > 0:
                        # We don't have individual scores here, so use tie_rate as proxy
                        scores.append(1.0 - budget_data.get("tie_rate", 0.0))
                    tie_rates.append(budget_data.get("tie_rate", 0.0))
                    doc_diversities.append(
                        budget_data.get("doc_diversity", 0.0)
                    )
                    unique_docs.append(budget_data.get("unique_docs", 0))

            if scores:
                budget_stats["average_score"] = sum(scores) / len(scores)
            if tie_rates:
                budget_stats["average_tie_rate"] = sum(tie_rates) / len(
                    tie_rates
                )
            if doc_diversities:
                budget_stats["average_doc_diversity"] = sum(
                    doc_diversities
                ) / len(doc_diversities)
            if unique_docs:
                budget_stats["average_unique_docs"] = sum(unique_docs) / len(
                    unique_docs
                )

        stats["budgets"][budget] = budget_stats

    return stats


def get_latest_manifest_info() -> Optional[Dict[str, Any]]:
    """
    Get information from the most recent embed manifest for provenance.

    Returns:
        Manifest info dictionary or None if not found
    """
    try:
        from ..core.paths import runs
        from ..pipeline.steps.embed.manifest import (
            find_last_manifest,
            load_manifest,
        )

        # Look for manifests in recent runs
        runs_dir = runs()
        if not runs_dir.exists():
            return None

        # Get most recent run directories
        run_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
        run_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        # Check recent runs for manifests
        for run_dir in run_dirs[:10]:  # Check last 10 runs
            manifest_path = find_last_manifest(run_dir.name)
            if manifest_path and manifest_path.exists():
                manifest_data = load_manifest(manifest_path)
                if manifest_data:
                    return {
                        "runId": manifest_data.get("runId"),
                        "timestamp": manifest_data.get("timestamp"),
                        "provider": manifest_data.get("provider"),
                        "model": manifest_data.get("model"),
                        "dimension": manifest_data.get("dimension"),
                        "chunksEmbedded": manifest_data.get("chunksEmbedded"),
                    }

        return None
    except Exception as e:
        log.warning("qa.manifest_info_failed", error=str(e))
        return None


def create_readiness_report(
    all_query_results: List[Dict[str, Any]],
    pack_stats: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create overall readiness report.

    Args:
        all_query_results: List of query health evaluation results
        pack_stats: Pack statistics
        config: Configuration used for the run

    Returns:
        Readiness report dictionary
    """
    total_queries = len(all_query_results)
    passed_queries = sum(
        1 for result in all_query_results if result["overall_pass"]
    )
    failed_queries = total_queries - passed_queries
    pass_rate = passed_queries / total_queries if total_queries > 0 else 0.0

    # Overall pass/fail decision
    overall_pass = pass_rate >= 0.8  # 80% pass rate threshold

    # Collect all failure reasons
    all_failures = []
    for result in all_query_results:
        if not result["overall_pass"]:
            all_failures.append(
                {
                    "query_id": result["query_id"],
                    "reasons": result["failure_reasons"],
                }
            )

    manifest_info = get_latest_manifest_info()

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "manifestInfo": manifest_info,
        "summary": {
            "total_queries": total_queries,
            "passed_queries": passed_queries,
            "failed_queries": failed_queries,
            "pass_rate": pass_rate,
            "overall_pass": overall_pass,
        },
        "thresholds": {
            "min_unique_docs": config["min_unique_docs"],
            "max_tie_rate": config["max_tie_rate"],
            "require_traceability": config["require_traceability"],
            "min_pass_rate": 0.8,
        },
        "pack_stats": pack_stats,
        "failures": all_failures,
        "query_results": all_query_results,
    }

    return report


def create_overview_markdown(
    readiness_report: Dict[str, Any], output_dir: Path
) -> str:
    """
    Create human-readable overview markdown report.

    Args:
        readiness_report: Readiness report dictionary
        output_dir: Output directory (for relative links)

    Returns:
        Markdown content
    """
    summary = readiness_report["summary"]
    config = readiness_report["config"]
    manifest_info = readiness_report.get("manifestInfo")

    # Status emoji
    status_emoji = "✅" if summary["overall_pass"] else "❌"

    md_lines = [
        f"# Retrieval QA Report {status_emoji}",
        "",
        f"**Generated:** {readiness_report['timestamp']}",
        f"**Status:** {'READY' if summary['overall_pass'] else 'BLOCKED'}",
        f"**Pass Rate:** {summary['pass_rate']:.1%} ({summary['passed_queries']}/{summary['total_queries']})",
        "",
        "## Configuration",
        "",
        f"- **Provider:** {config['provider']}",
        f"- **Model:** {config['model']}",
        f"- **Dimension:** {config['dimension']}",
        f"- **Budgets:** {', '.join(map(str, config['budgets']))}",
        f"- **Top-K:** {config['top_k']}",
        f"- **Min Unique Docs:** {config['min_unique_docs']}",
        f"- **Max Tie Rate:** {config['max_tie_rate']}",
        f"- **Require Traceability:** {config['require_traceability']}",
        "",
    ]

    # Manifest info
    if manifest_info:
        md_lines.extend(
            [
                "## Embedding Provenance",
                "",
                f"- **Run ID:** {manifest_info.get('runId', 'unknown')}",
                f"- **Embedded:** {manifest_info.get('timestamp', 'unknown')}",
                f"- **Chunks:** {manifest_info.get('chunksEmbedded', 0):,}",
                "",
            ]
        )

    # Query results tables
    passed_queries = [
        r for r in readiness_report["query_results"] if r["overall_pass"]
    ]
    failed_queries = [
        r for r in readiness_report["query_results"] if not r["overall_pass"]
    ]

    if passed_queries:
        md_lines.extend(
            [
                f"## ✅ PASSED Queries ({len(passed_queries)})",
                "",
                "| Query ID | Text | Budgets Tested |",
                "|----------|------|----------------|",
            ]
        )
        for result in passed_queries:
            query_id = result["query_id"]
            query_text = (
                result["query_text"][:60] + "..."
                if len(result["query_text"]) > 60
                else result["query_text"]
            )
            budgets = ", ".join(map(str, result["budgets"].keys()))
            md_lines.append(f"| `{query_id}` | {query_text} | {budgets} |")
        md_lines.append("")

    if failed_queries:
        md_lines.extend(
            [
                f"## ❌ FAILED Queries ({len(failed_queries)})",
                "",
                "| Query ID | Text | Reasons | Quick Fixes |",
                "|----------|------|---------|-------------|",
            ]
        )
        for result in failed_queries:
            query_id = result["query_id"]
            query_text = (
                result["query_text"][:40] + "..."
                if len(result["query_text"]) > 40
                else result["query_text"]
            )
            reasons = "; ".join(result["failure_reasons"][:2])  # Limit reasons

            # Generate quick fixes based on failure reasons
            fixes = []
            for reason in result["failure_reasons"]:
                if "unique_docs" in reason:
                    fixes.append("Add more diverse content")
                elif "tie_rate" in reason:
                    fixes.append("Check embedding quality")
                elif "missing_title" in reason:
                    fixes.append("Fix document metadata")
                elif "missing_url" in reason:
                    fixes.append("Fix URL references")

            quick_fixes = "; ".join(fixes[:2]) if fixes else "Review manually"
            md_lines.append(
                f"| `{query_id}` | {query_text} | {reasons} | {quick_fixes} |"
            )
        md_lines.append("")

    # Pack statistics
    pack_stats = readiness_report.get("pack_stats", {}).get("budgets", {})
    if pack_stats:
        md_lines.extend(
            [
                "## Pack Statistics by Budget",
                "",
                "| Budget | Avg Unique Docs | Avg Diversity | Avg Tie Rate |",
                "|--------|----------------|---------------|--------------|",
            ]
        )
        for budget, stats in pack_stats.items():
            avg_docs = stats.get("average_unique_docs", 0)
            avg_diversity = stats.get("average_doc_diversity", 0)
            avg_tie_rate = stats.get("average_tie_rate", 0)
            md_lines.append(
                f"| {budget} | {avg_docs:.1f} | {avg_diversity:.2f} | {avg_tie_rate:.3f} |"
            )
        md_lines.append("")

    # Artifacts section
    md_lines.extend(
        [
            "## Artifacts",
            "",
            "- [`readiness.json`](./readiness.json) - Machine-readable results",
            "- [`pack_stats.json`](./pack_stats.json) - Pack statistics",
            "- `ask_*.json` - Per-query results and packed contexts",
            "",
            "## Next Steps",
            "",
        ]
    )

    if summary["overall_pass"]:
        md_lines.extend(
            [
                "🎉 **System is READY for production retrieval.**",
                "",
                "- All queries meet quality thresholds",
                "- Traceability metadata is complete",
                "- Embedding diversity is sufficient",
            ]
        )
    else:
        md_lines.extend(
            [
                "⚠️ **System is BLOCKED - address failures before production.**",
                "",
                "Priority actions:",
            ]
        )

        # Generate specific recommendations
        all_failure_reasons = [
            r for result in failed_queries for r in result["failure_reasons"]
        ]
        reason_counts = Counter(
            reason.split(":")[0] for reason in all_failure_reasons
        )

        for reason_type, count in reason_counts.most_common(3):
            if "unique_docs" in reason_type:
                md_lines.append(
                    f"- **Diversity Issue ({count} queries):** Add more diverse content or adjust chunking strategy"
                )
            elif "tie_rate" in reason_type:
                md_lines.append(
                    f"- **Ranking Issue ({count} queries):** Review embedding quality or model selection"
                )
            elif (
                "missing_title" in reason_type or "missing_url" in reason_type
            ):
                md_lines.append(
                    f"- **Metadata Issue ({count} queries):** Fix document ingestion to include complete metadata"
                )

    return "\n".join(md_lines)


def run_retrieval_qa(
    queries_file: str,
    budgets: List[int],
    top_k: int,
    provider: str,
    model: str,
    dimension: int,
    output_dir: Path,
    min_unique_docs: int = 3,
    max_tie_rate: float = 0.35,
    require_traceability: bool = True,
) -> Dict[str, Any]:
    """
    Run the complete retrieval QA harness.

    Args:
        queries_file: Path to YAML file with queries
        budgets: List of character budgets to test
        top_k: Number of top results to retrieve
        provider: Embedding provider name
        model: Embedding model name
        dimension: Embedding dimension
        output_dir: Output directory for artifacts
        min_unique_docs: Minimum unique documents threshold
        max_tie_rate: Maximum tie rate threshold
        require_traceability: Whether to require traceability fields

    Returns:
        Summary results dictionary
    """
    log.info("qa.retrieval.start", queries_file=queries_file, budgets=budgets)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load queries
    queries = load_queries(queries_file)
    log.info("qa.retrieval.queries_loaded", count=len(queries))

    # Initialize retriever
    retriever = DenseRetriever(provider_name=provider, dim=dimension)

    # Process each query
    all_query_results = []

    for query in queries:
        log.info("qa.retrieval.query_start", query_id=query["id"])

        # Run query across budgets
        hits_by_budget, packed_contexts_by_budget = run_single_query(
            query, budgets, retriever, top_k
        )

        # Save query artifacts
        save_query_artifacts(
            query, hits_by_budget, packed_contexts_by_budget, output_dir
        )

        # Evaluate health
        health_result = evaluate_query_health(
            query,
            hits_by_budget,
            min_unique_docs,
            max_tie_rate,
            require_traceability,
        )
        all_query_results.append(health_result)

        log.info(
            "qa.retrieval.query_complete",
            query_id=query["id"],
            passed=health_result["overall_pass"],
        )

    # Compute pack statistics
    pack_stats = compute_pack_stats(all_query_results, budgets)

    # Save pack stats
    pack_stats_file = output_dir / "pack_stats.json"
    with open(pack_stats_file, "w", encoding="utf-8") as f:
        json.dump(pack_stats, f, indent=2, ensure_ascii=False)

    # Create configuration record
    config = {
        "queries_file": queries_file,
        "budgets": budgets,
        "top_k": top_k,
        "provider": provider,
        "model": model,
        "dimension": dimension,
        "min_unique_docs": min_unique_docs,
        "max_tie_rate": max_tie_rate,
        "require_traceability": require_traceability,
    }

    # Create readiness report
    readiness_report = create_readiness_report(
        all_query_results, pack_stats, config
    )

    # Save readiness report
    readiness_file = output_dir / "readiness.json"
    with open(readiness_file, "w", encoding="utf-8") as f:
        json.dump(readiness_report, f, indent=2, ensure_ascii=False)

    # Create overview markdown
    overview_md = create_overview_markdown(readiness_report, output_dir)
    overview_file = output_dir / "overview.md"
    with open(overview_file, "w", encoding="utf-8") as f:
        f.write(overview_md)

    # Log completion
    summary = readiness_report["summary"]
    log.info(
        "qa.retrieval.complete",
        total_queries=summary["total_queries"],
        pass_rate=summary["pass_rate"],
        overall_pass=summary["overall_pass"],
        output_dir=str(output_dir),
    )

    return {
        "total_queries": summary["total_queries"],
        "passed_queries": summary["passed_queries"],
        "failed_queries": summary["failed_queries"],
        "pass_rate": summary["pass_rate"],
        "overall_pass": summary["overall_pass"],
        "output_dir": str(output_dir),
    }
