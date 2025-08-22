"""
Expectation Harness v2 integration for QA system.

This module integrates the expectation-based scoring with the existing QA harness.
"""

from pathlib import Path
from typing import Any

from .expect import evaluate_query_expectations


def evaluate_expectations(
    query_id: str,
    retrieved_items: list[dict[str, Any]],
    top_k: int = 12,
    threshold: float = 0.7,
    mode: str = "doc+concept",
    expect_profile: str = "default",
) -> dict[str, Any]:
    """
    Evaluate query expectations using the Expectation Harness v2.

    Args:
        query_id: Query identifier
        retrieved_items: List of retrieved items with url, title, snippet fields
        top_k: Number of top items to consider (default: 12)
        threshold: Pass threshold for final score (default: 0.7)
        mode: Scoring mode: "doc+concept", "doc-only", or "concept-only"
        expect_profile: Expectation profile to use (default: "default")

    Returns:
        Dictionary with evaluation results including passed, score, anchors_hit,
        missing_groups, etc.
    """
    return evaluate_query_expectations(
        query_id=query_id,
        retrieved_items=retrieved_items,
        top_k=top_k,
        threshold=threshold,
        mode=mode,
        expect_profile=expect_profile,
    )


def create_explanation_file(output_dir: Path, query_id: str, evaluation_result: dict[str, Any]) -> None:
    """
    Create explanation file for failed queries.

    Args:
        output_dir: Output directory for QA artifacts
        query_id: Query identifier
        evaluation_result: Result from evaluate_expectations
    """
    explain_dir = output_dir / "explain"
    explain_dir.mkdir(exist_ok=True)

    explain_file = explain_dir / f"{query_id}.md"

    with open(explain_file, "w", encoding="utf-8") as f:
        f.write(f"# Query: {query_id}\n\n")
        f.write(f"**Score**: {evaluation_result['score']:.3f}\n")
        f.write(f"**Threshold**: {evaluation_result['threshold']:.3f}\n")
        f.write(f"**Mode**: {evaluation_result['mode']}\n\n")

        # Doc Anchors section
        f.write("## Doc Anchors\n\n")
        f.write(f"**Score**: {evaluation_result['anchors_score']:.3f}\n")
        if evaluation_result["anchors_hit"]:
            f.write(f"**Hit**: {', '.join(evaluation_result['anchors_hit'])}\n")
        else:
            f.write("**Hit**: None\n")
        f.write(f"**Top Slugs**: {', '.join(evaluation_result['top_doc_slugs'][:5])}\n\n")

        # Concept Groups section
        f.write("## Concept Groups\n\n")
        f.write(f"**Score**: {evaluation_result['concepts_score']:.3f}\n")
        if evaluation_result["hit_groups"]:
            f.write(f"**Hit Groups**: {', '.join(evaluation_result['hit_groups'])}\n")
        if evaluation_result["missing_groups"]:
            f.write(f"**Missing Groups**: {', '.join(evaluation_result['missing_groups'])}\n")
        f.write("\n")

        # Recommendations
        f.write("## Recommendations\n\n")
        if evaluation_result["anchors_score"] == 0.0:
            f.write("- Consider adding expected document slugs to anchors.yaml\n")
        if evaluation_result["concepts_score"] < 1.0:
            f.write("- Review concept group definitions in concepts.yaml\n")
            f.write("- Check if retrieved content contains expected terminology\n")


def extend_readiness_report(
    readiness_report: dict[str, Any],
    expectation_results: list[dict[str, Any]],
    mode: str = "doc+concept",
    threshold: float = 0.7,
) -> dict[str, Any]:
    """
    Extend readiness report with expectation results.

    Args:
        readiness_report: Existing readiness report
        expectation_results: List of expectation evaluation results
        mode: Expectation scoring mode used
        threshold: Pass threshold used

    Returns:
        Extended readiness report with expectation section
    """
    if not expectation_results:
        return readiness_report

    # Calculate expectation pass rate
    passed_count = sum(1 for r in expectation_results if r.get("passed", False))
    total_count = len(expectation_results)
    pass_rate = passed_count / total_count if total_count > 0 else 0.0

    # Add expectation section
    readiness_report["expect"] = {
        "mode": mode,
        "threshold": threshold,
        "pass_rate": pass_rate,
        "passed_queries": passed_count,
        "total_queries": total_count,
        "results": expectation_results,
    }

    return readiness_report
