"""
Preflight validation for embedding with advisory quality gates and doc skiplists.
"""

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Any

from ....core.logging import log
from ....core.paths import runs
from ....obs.events import emit_event


def validate_preflight_artifacts(run_id: str) -> Tuple[bool, List[str]]:
    """
    Validate that all required artifacts exist for embedding.

    Args:
        run_id: Run identifier

    Returns:
        Tuple of (artifacts_valid, missing_artifacts)
    """
    run_dir = runs() / run_id
    missing = []

    # Check enriched.jsonl
    enriched_file = run_dir / "enrich" / "enriched.jsonl"
    if not enriched_file.exists() or enriched_file.stat().st_size == 0:
        missing.append("enriched.jsonl")

    # Check chunks.ndjson
    chunks_file = run_dir / "chunk" / "chunks.ndjson"
    if not chunks_file.exists() or chunks_file.stat().st_size == 0:
        missing.append("chunks.ndjson")

    return len(missing) == 0, missing


def validate_tokenizer_config(
    provider: str, model: str, dimension: int
) -> Tuple[bool, List[str]]:
    """
    Validate tokenizer and embedding configuration.

    Args:
        provider: Embedding provider name
        model: Model name
        dimension: Embedding dimension

    Returns:
        Tuple of (config_valid, config_issues)
    """
    issues = []

    # Check tokenizer availability
    try:
        import tiktoken

        tiktoken.encoding_for_model("text-embedding-3-small")
    except Exception as e:
        issues.append(f"tokenizer_unavailable: {e}")

    # Validate provider/model combination
    if provider == "openai" and not model.startswith("text-embedding"):
        issues.append(
            f"invalid_model_for_provider: {model} not valid for {provider}"
        )

    # Validate dimension
    if dimension <= 0 or dimension > 8192:
        issues.append(f"invalid_dimension: {dimension}")

    return len(issues) == 0, issues


def compute_embeddable_docs(
    run_id: str,
    min_quality: float = 0.60,
    max_below_threshold_pct: float = 0.20,
) -> Tuple[int, int, List[str], Dict[str, Any]]:
    """
    Compute embeddable vs skippable documents based on quality thresholds.

    Args:
        run_id: Run identifier
        min_quality: Minimum quality score threshold
        max_below_threshold_pct: Maximum percentage of docs below threshold

    Returns:
        Tuple of (total_docs, embeddable_docs, skipped_doc_ids, quality_stats)
    """
    run_dir = runs() / run_id
    enriched_file = run_dir / "enrich" / "enriched.jsonl"

    if not enriched_file.exists():
        return 0, 0, [], {}

    all_docs = []
    skipped_doc_ids = []

    # Load enriched documents
    with open(enriched_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                doc = json.loads(line.strip())
                all_docs.append(doc)

                # Check if doc should be skipped based on quality
                quality_score = doc.get("quality_score", 1.0)
                if quality_score < min_quality:
                    skipped_doc_ids.append(doc.get("id", ""))

    total_docs = len(all_docs)
    embeddable_docs = total_docs - len(skipped_doc_ids)

    # Compute quality statistics
    quality_scores = [doc.get("quality_score", 1.0) for doc in all_docs]
    quality_stats = {}

    if quality_scores:
        quality_stats = {
            "p50": statistics.median(quality_scores),
            "p90": (
                statistics.quantiles(quality_scores, n=10)[8]
                if len(quality_scores) >= 10
                else max(quality_scores)
            ),
            "belowThresholdPct": (
                len(skipped_doc_ids) / total_docs if total_docs > 0 else 0.0
            ),
            "minQuality": min_quality,
            "maxBelowThresholdPct": max_below_threshold_pct,
        }

    return total_docs, embeddable_docs, skipped_doc_ids, quality_stats


def run_preflight_check(
    run_id: str,
    provider: str = "openai",
    model: str = "text-embedding-3-small",
    dimension: int = 1536,
    min_embed_docs: int = 1,
    quality_advisory: bool = True,
    min_quality: float = 0.60,
    max_below_threshold_pct: float = 0.20,
) -> Dict[str, Any]:
    """
    Run preflight validation for a single run with advisory quality gates.

    Args:
        run_id: Run identifier
        provider: Embedding provider
        model: Model name
        dimension: Embedding dimension
        min_embed_docs: Minimum embeddable docs required
        quality_advisory: Whether quality is advisory only (always True now)
        min_quality: Minimum quality threshold
        max_below_threshold_pct: Maximum below threshold percentage

    Returns:
        Preflight validation results
    """
    emit_event(
        "preflight.start",
        run_id=run_id,
        provider=provider,
        model=model,
        dimension=dimension,
    )

    # Validate artifacts
    artifacts_valid, missing_artifacts = validate_preflight_artifacts(run_id)

    # Validate config
    config_valid, config_issues = validate_tokenizer_config(
        provider, model, dimension
    )

    # Compute embeddable docs
    total_docs, embeddable_docs, skipped_doc_ids, quality_stats = (
        compute_embeddable_docs(run_id, min_quality, max_below_threshold_pct)
    )

    # Determine status and reasons
    reasons = []

    if not artifacts_valid:
        reasons.extend(
            [
                f"MISSING_{artifact.upper().replace('.', '_')}"
                for artifact in missing_artifacts
            ]
        )

    if not config_valid:
        reasons.extend(config_issues)

    # Quality is now advisory only - never blocks runs
    # QUALITY_GATE is forbidden as a run-level blocking reason per requirements
    # below_threshold_pct = quality_stats.get("belowThresholdPct", 0.0)  # Advisory only

    # Only block for structural reasons or zero embeddable docs
    if embeddable_docs < min_embed_docs:
        reasons.append("EMBEDDABLE_DOCS=0")

    # Status determination
    if reasons:
        status = "BLOCKED"
    else:
        status = "READY"

    # Create preflight result
    result = {
        "status": status,
        "reasons": reasons,
        "docTotals": {
            "all": total_docs,
            "embeddable": embeddable_docs,
            "skipped": len(skipped_doc_ids),
        },
        "quality": quality_stats,
        "advisory": {"quality": quality_advisory},
        "artifacts": {
            "enriched": "enriched.jsonl" not in missing_artifacts,
            "chunks": "chunks.ndjson" not in missing_artifacts,
            "tokenizer": len([i for i in config_issues if "tokenizer" in i])
            == 0,
            "config": len([i for i in config_issues if "tokenizer" not in i])
            == 0,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "provider": provider,
        "model": model,
        "dimension": dimension,
    }

    # Write preflight results
    run_dir = runs() / run_id
    preflight_dir = run_dir / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)

    # Write preflight.json
    preflight_file = preflight_dir / "preflight.json"
    with open(preflight_file, "w") as f:
        json.dump(result, f, indent=2)

    # Write doc_skiplist.json if there are skipped docs
    if skipped_doc_ids:
        skiplist = {
            "skip": skipped_doc_ids,
            "reason": "quality_below_min",
            "min_quality": min_quality,
            "total_docs": total_docs,
            "skipped_count": len(skipped_doc_ids),
        }

        skiplist_file = preflight_dir / "doc_skiplist.json"
        with open(skiplist_file, "w") as f:
            json.dump(skiplist, f, indent=2)

    emit_event(
        "preflight.complete",
        run_id=run_id,
        status=status,
        total_docs=total_docs,
        embeddable_docs=embeddable_docs,
        skipped_docs=len(skipped_doc_ids),
    )

    return result


def run_plan_preflight(
    plan_file: str,
    provider: str = "openai",
    model: str = "text-embedding-3-small",
    dimension: int = 1536,
    min_embed_docs: int = 1,
    quality_advisory: bool = True,
    out_dir: str = "var/plan_preflight/",
) -> Dict[str, Any]:
    """
    Run plan-preflight validation for all runs in a plan file.

    Args:
        plan_file: Path to plan file
        provider: Embedding provider
        model: Model name
        dimension: Embedding dimension
        min_embed_docs: Minimum embeddable docs required
        quality_advisory: Whether quality is advisory only (always True now)
        out_dir: Output directory

    Returns:
        Plan preflight results
    """
    emit_event(
        "plan_preflight.start",
        plan_file=plan_file,
        provider=provider,
        model=model,
        dimension=dimension,
    )

    # Parse plan file
    plan_path = Path(plan_file)
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found: {plan_file}")

    run_entries = []
    with open(plan_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Support both formats: run_id:chunk_count and var/runs/run_id
            if ":" in line:
                run_id, chunk_count_str = line.split(":", 1)
                run_id = run_id.strip()
                try:
                    chunk_count = int(chunk_count_str.strip())
                except ValueError:
                    log.warning(
                        "plan_preflight.invalid_line",
                        line_num=line_num,
                        line=line,
                    )
                    continue
            elif line.startswith("var/runs/"):
                run_id = Path(line).name
                # Auto-detect chunk count
                chunks_file = runs() / run_id / "chunk" / "chunks.ndjson"
                if chunks_file.exists():
                    try:
                        with open(chunks_file, "r") as cf:
                            chunk_count = sum(
                                1 for cline in cf if cline.strip()
                            )
                    except Exception:
                        chunk_count = 0
                else:
                    chunk_count = 0
            else:
                log.warning(
                    "plan_preflight.unsupported_format",
                    line_num=line_num,
                    line=line,
                )
                continue

            run_entries.append((run_id, chunk_count))

    if not run_entries:
        raise ValueError(f"No valid runs found in plan file: {plan_file}")

    # Create output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(out_dir) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process each run
    ready_runs = []
    blocked_runs = []
    runs_data = []
    total_embeddable_docs = 0
    total_skipped_docs = 0
    total_tokens = 0

    for run_id, expected_chunk_count in run_entries:
        # Run preflight for this run
        preflight_result = run_preflight_check(
            run_id=run_id,
            provider=provider,
            model=model,
            dimension=dimension,
            min_embed_docs=min_embed_docs,
            quality_advisory=quality_advisory,
        )

        # Aggregate results
        doc_totals = preflight_result["docTotals"]
        embeddable_docs = doc_totals["embeddable"]
        skipped_docs = doc_totals["skipped"]

        total_embeddable_docs += embeddable_docs
        total_skipped_docs += skipped_docs

        # Calculate tokens for this run
        chunks_file = runs() / run_id / "chunk" / "chunks.ndjson"
        run_tokens = 0
        if chunks_file.exists():
            try:
                with open(chunks_file, "r") as f:
                    for line in f:
                        if line.strip():
                            chunk = json.loads(line.strip())
                            run_tokens += chunk.get("token_count", 0)
            except Exception:
                pass

        total_tokens += run_tokens

        # Classify run
        if preflight_result["status"] == "READY":
            ready_runs.append(run_id)
        else:
            blocked_runs.append(run_id)

        # Store detailed data
        runs_data.append(
            {
                "rid": run_id,
                "status": preflight_result["status"],
                "reason": (
                    ", ".join(preflight_result["reasons"])
                    if preflight_result["reasons"]
                    else ""
                ),
                "docs_total": doc_totals["all"],
                "docs_embeddable": embeddable_docs,
                "docs_skipped": skipped_docs,
                "tokens": run_tokens,
                "quality_p50": preflight_result["quality"].get("p50", 0),
                "quality_below_threshold_pct": preflight_result["quality"].get(
                    "belowThresholdPct", 0
                ),
            }
        )

    # Create plan result
    plan_result = {
        "timestamp": timestamp,
        "provider": provider,
        "model": model,
        "dimension": dimension,
        "total_runs_planned": len(run_entries),
        "ready_runs": len(ready_runs),
        "blocked_runs": len(blocked_runs),
        "total_embeddable_docs": total_embeddable_docs,
        "total_skipped_docs": total_skipped_docs,
        "total_tokens": total_tokens,
        "runs_detail": runs_data,
        "parameters": {
            "min_embed_docs": min_embed_docs,
            "quality_advisory": quality_advisory,
        },
    }

    # Write outputs
    _write_plan_preflight_outputs(
        output_dir, plan_result, ready_runs, blocked_runs, runs_data
    )

    emit_event(
        "plan_preflight.complete",
        ready_runs=len(ready_runs),
        blocked_runs=len(blocked_runs),
        total_embeddable_docs=total_embeddable_docs,
        output_dir=str(output_dir),
    )

    return plan_result


def _write_plan_preflight_outputs(
    output_dir: Path,
    plan_result: Dict[str, Any],
    ready_runs: List[str],
    blocked_runs: List[str],
    runs_data: List[Dict[str, Any]],
) -> None:
    """Write all plan-preflight output files."""

    # Write plan_preflight.json
    with open(output_dir / "plan_preflight.json", "w") as f:
        json.dump(plan_result, f, indent=2)

    # Write plan_preflight.csv
    import csv

    with open(output_dir / "plan_preflight.csv", "w", newline="") as f:
        if runs_data:
            writer = csv.DictWriter(f, fieldnames=runs_data[0].keys())
            writer.writeheader()
            writer.writerows(runs_data)

    # Write plan_preflight.md
    with open(output_dir / "plan_preflight.md", "w") as f:
        f.write(
            f"""# Plan Preflight Report

**Timestamp:** {plan_result["timestamp"]}
**Provider:** {plan_result["provider"]}
**Model:** {plan_result["model"]}
**Dimension:** {plan_result["dimension"]}

## Summary

- **Total Runs Planned:** {plan_result["total_runs_planned"]}
- **Ready Runs:** {plan_result["ready_runs"]}
- **Blocked Runs:** {plan_result["blocked_runs"]}
- **Total Embeddable Docs:** {plan_result["total_embeddable_docs"]:,}
- **Total Skipped Docs:** {plan_result["total_skipped_docs"]:,}
- **Total Tokens:** {plan_result["total_tokens"]:,}

## Quality Mode

- **Advisory Mode:** {plan_result["parameters"]["quality_advisory"]} (quality never blocks runs)

## Status

{"✅ READY" if plan_result["blocked_runs"] == 0 else f"⚠️  {plan_result['blocked_runs']} BLOCKED"} - Runs validated for embedding

## Ready Runs ({len(ready_runs)})

"""
        )

        if ready_runs:
            f.write("| Run ID | Embeddable Docs | Skipped Docs | Tokens |\n")
            f.write("|--------|-----------------|--------------|--------|\n")
            for run_data in runs_data:
                if run_data["status"] == "READY":
                    f.write(
                        f"| {run_data['rid']} | {run_data['docs_embeddable']} | {run_data['docs_skipped']} | {run_data['tokens']:,} |\n"
                    )
        else:
            f.write("*No ready runs*\n")

        f.write(f"\n## Blocked Runs ({len(blocked_runs)})\n\n")
        if blocked_runs:
            f.write("| Run ID | Reason | Embeddable Docs |\n")
            f.write("|--------|--------|----------------|\n")
            for run_data in runs_data:
                if run_data["status"] == "BLOCKED":
                    f.write(
                        f"| {run_data['rid']} | {run_data['reason']} | {run_data['docs_embeddable']} |\n"
                    )
        else:
            f.write("*No blocked runs*\n")

    # Write ready.txt
    with open(output_dir / "ready.txt", "w") as f:
        for run_id in ready_runs:
            f.write(f"var/runs/{run_id}\n")

    # Write blocked.txt
    with open(output_dir / "blocked.txt", "w") as f:
        for run_data in runs_data:
            if run_data["status"] == "BLOCKED":
                f.write(f"var/runs/{run_data['rid']} # {run_data['reason']}\n")

    # Write log.out
    with open(output_dir / "log.out", "w") as f:
        f.write(f"Plan preflight completed at {plan_result['timestamp']}\n")
        f.write(f"Ready: {len(ready_runs)}, Blocked: {len(blocked_runs)}\n")
        f.write(
            f"Total embeddable docs: {plan_result['total_embeddable_docs']}\n"
        )
