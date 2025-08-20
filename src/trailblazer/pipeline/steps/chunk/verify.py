"""
Corpus-wide chunk verification utilities.
"""

import glob
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .boundaries import count_tokens
from .engine import calculate_coverage, Chunk


def verify_chunks(
    runs_glob: str,
    max_tokens: int = 800,
    soft_min: int = 200,
    hard_min: int = 80,
    require_traceability: bool = True,
    out_dir: str = "var/chunk_verify",
    tokenizer: str = "text-embedding-3-small",
) -> Dict:
    """
    Verify all chunks across multiple runs for token cap compliance and traceability.

    Args:
        runs_glob: Glob pattern for run directories
        max_tokens: Maximum token limit to check against
        soft_min: Soft minimum token threshold for v2.2
        hard_min: Hard minimum token threshold for v2.2
        require_traceability: Whether to require traceability fields
        out_dir: Output directory for reports
        tokenizer: Tokenizer model name

    Returns:
        Verification results dictionary
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    verify_dir = Path(out_dir) / timestamp
    verify_dir.mkdir(parents=True, exist_ok=True)

    # Find all chunk files
    run_dirs = glob.glob(runs_glob)

    all_chunks = []
    oversize_chunks = []
    missing_traceability_chunks = []
    small_chunks = []
    gaps_by_doc: List[Dict] = []
    run_count = 0
    coverage_percentages = []

    # Group chunks by document for coverage analysis
    chunks_by_doc: Dict[str, Dict] = {}

    for run_dir_str in run_dirs:
        run_dir = Path(run_dir_str)
        chunks_file = run_dir / "chunk" / "chunks.ndjson"

        if not chunks_file.exists():
            continue

        run_count += 1

        with open(chunks_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue

                chunk = json.loads(line)
                all_chunks.append(chunk)

                # Group by document for coverage analysis
                doc_id = chunk.get("doc_id", "")
                if doc_id:
                    if doc_id not in chunks_by_doc:
                        chunks_by_doc[doc_id] = {
                            "run_id": run_dir.name,
                            "chunks": [],
                        }
                    chunks_by_doc[doc_id]["chunks"].append(chunk)

                # Re-tokenize to verify
                text_md = chunk.get("text_md", "")
                actual_tokens = count_tokens(text_md, tokenizer)

                # Check for oversize
                if actual_tokens > max_tokens:
                    oversize_chunks.append(
                        {
                            "chunk_id": chunk.get("chunk_id", ""),
                            "run_id": run_dir.name,
                            "token_count": actual_tokens,
                            "reported_token_count": chunk.get(
                                "token_count", 0
                            ),
                            "char_count": chunk.get("char_count", 0),
                            "split_strategy": chunk.get(
                                "split_strategy", "unknown"
                            ),
                        }
                    )

                # Check for small chunks (v2.2)
                if actual_tokens < hard_min:
                    reason = "unknown"
                    meta = chunk.get("meta", {})
                    if meta.get("tail_small"):
                        reason = "tail_small"
                    elif len(text_md.strip()) < 50:
                        reason = "tiny_doc"
                    elif "fence" in chunk.get("split_strategy", ""):
                        reason = "fence_forced"
                    elif "table" in chunk.get("split_strategy", ""):
                        reason = "table_forced"

                    small_chunks.append(
                        {
                            "chunk_id": chunk.get("chunk_id", ""),
                            "run_id": run_dir.name,
                            "token_count": actual_tokens,
                            "reason": reason,
                            "split_strategy": chunk.get(
                                "split_strategy", "unknown"
                            ),
                        }
                    )

                # Check traceability if required
                if require_traceability:
                    has_title = bool(chunk.get("title", "").strip())
                    has_url = bool(chunk.get("url", "").strip())
                    has_source_system = bool(
                        chunk.get("source_system", "").strip()
                    )

                    if not has_source_system or (
                        not has_title and not has_url
                    ):
                        missing_traceability_chunks.append(
                            {
                                "chunk_id": chunk.get("chunk_id", ""),
                                "run_id": run_dir.name,
                                "missing_fields": {
                                    "source_system": not has_source_system,
                                    "title": not has_title,
                                    "url": not has_url,
                                },
                            }
                        )

    # Analyze coverage for each document
    for doc_id, doc_data in chunks_by_doc.items():
        doc_chunks = doc_data["chunks"]
        run_id = doc_data["run_id"]

        if not doc_chunks:
            continue

        # Convert chunks to Chunk objects for coverage calculation
        chunk_objects = []
        for chunk_data in doc_chunks:
            chunk_obj = Chunk(
                chunk_id=chunk_data.get("chunk_id", ""),
                text_md=chunk_data.get("text_md", ""),
                char_count=chunk_data.get("char_count", 0),
                token_count=chunk_data.get("token_count", 0),
                ord=chunk_data.get("ord", 0),
                char_start=chunk_data.get("char_start", 0),
                char_end=chunk_data.get("char_end", 0),
            )
            chunk_objects.append(chunk_obj)

        # Estimate original document length
        max_char_end = max(
            (chunk.get("char_end", 0) for chunk in doc_chunks), default=0
        )
        if max_char_end == 0:
            # Fallback: estimate from chunk char counts
            max_char_end = sum(
                chunk.get("char_count", 0) for chunk in doc_chunks
            )

        if max_char_end > 0:
            coverage_pct, gaps = calculate_coverage(
                chunk_objects, max_char_end
            )
            coverage_percentages.append(coverage_pct)

            if coverage_pct < 99.5:
                gaps_by_doc.append(
                    {
                        "doc_id": doc_id,
                        "run_id": run_id,
                        "coverage_pct": coverage_pct,
                        "gaps": gaps[:10],  # Limit to first 10 gaps
                        "gaps_count": len(gaps),
                        "original_length": max_char_end,
                    }
                )

    # Calculate statistics
    token_counts = []
    for chunk in all_chunks:
        actual_tokens = count_tokens(chunk.get("text_md", ""), tokenizer)
        token_counts.append(actual_tokens)

    stats: Dict = {
        "total_runs": run_count,
        "total_chunks": len(all_chunks),
        "total_documents": len(chunks_by_doc),
        "token_stats": {
            "min": min(token_counts) if token_counts else 0,
            "median": (
                int(statistics.median(token_counts)) if token_counts else 0
            ),
            "p95": (
                int(statistics.quantiles(token_counts, n=20)[18])
                if len(token_counts) > 20
                else (max(token_counts) if token_counts else 0)
            ),
            "max": max(token_counts) if token_counts else 0,
            "mean": int(statistics.mean(token_counts)) if token_counts else 0,
        },
        "coverage_stats": {
            "avg_coverage_pct": (
                statistics.mean(coverage_percentages)
                if coverage_percentages
                else 100.0
            ),
            "min_coverage_pct": (
                min(coverage_percentages) if coverage_percentages else 100.0
            ),
            "docs_with_gaps": len(gaps_by_doc),
            "docs_analyzed": len(chunks_by_doc),
        },
        "violations": {
            "oversize_count": len(oversize_chunks),
            "missing_traceability_count": len(missing_traceability_chunks),
            "small_chunks_count": len(small_chunks),
            "docs_with_gaps": len(gaps_by_doc),
        },
    }

    # Write detailed reports
    if oversize_chunks:
        breaches_file = verify_dir / "breaches.json"
        with open(breaches_file, "w") as f:
            json.dump(oversize_chunks, f, indent=2)

    if missing_traceability_chunks:
        missing_file = verify_dir / "missing_traceability.json"
        with open(missing_file, "w") as f:
            json.dump(missing_traceability_chunks, f, indent=2)

    if small_chunks:
        small_file = verify_dir / "small_chunks.json"
        with open(small_file, "w") as f:
            json.dump(small_chunks, f, indent=2)

    if gaps_by_doc:
        gaps_file = verify_dir / "gaps.json"
        with open(gaps_file, "w") as f:
            json.dump(gaps_by_doc, f, indent=2)

    # Create report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "runs_glob": runs_glob,
            "max_tokens": max_tokens,
            "soft_min": soft_min,
            "hard_min": hard_min,
            "require_traceability": require_traceability,
            "tokenizer": tokenizer,
        },
        "statistics": stats,
        "violations": {
            "oversize_chunks": len(oversize_chunks),
            "missing_traceability": len(missing_traceability_chunks),
            "small_chunks": len(small_chunks),
            "docs_with_gaps": len(gaps_by_doc),
        },
        "status": (
            "PASS"
            if (
                len(oversize_chunks) == 0
                and len(missing_traceability_chunks) == 0
                and len(gaps_by_doc) == 0
            )
            else "FAIL"
        ),
    }

    # Write JSON report
    report_file = verify_dir / "report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    # Write markdown summary
    md_lines = [
        "# Chunk Verification Report",
        "",
        f"**Generated:** {report['timestamp']}",
        f"**Runs Processed:** {stats['total_runs']}",
        f"**Total Chunks:** {stats['total_chunks']}",
        f"**Total Documents:** {stats['total_documents']}",
        f"**Max Token Limit:** {max_tokens}",
        f"**Soft Min Tokens:** {soft_min}",
        f"**Hard Min Tokens:** {hard_min}",
        "",
        "## Token Statistics",
        "",
        f"- **Min:** {stats['token_stats']['min']} tokens",
        f"- **Median:** {stats['token_stats']['median']} tokens",
        f"- **Mean:** {stats['token_stats']['mean']} tokens",
        f"- **95th percentile:** {stats['token_stats']['p95']} tokens",
        f"- **Max:** {stats['token_stats']['max']} tokens",
        "",
        "## Coverage Statistics",
        "",
        f"- **Documents Analyzed:** {stats['coverage_stats']['docs_analyzed']}",
        f"- **Average Coverage:** {stats['coverage_stats']['avg_coverage_pct']:.1f}%",
        f"- **Minimum Coverage:** {stats['coverage_stats']['min_coverage_pct']:.1f}%",
        f"- **Documents with Gaps:** {stats['coverage_stats']['docs_with_gaps']}",
        "",
        "## Violations",
        "",
        f"- **Oversize chunks:** {len(oversize_chunks)}",
        f"- **Missing traceability:** {len(missing_traceability_chunks)}",
        f"- **Small chunks (< {hard_min} tokens):** {len(small_chunks)}",
        f"- **Documents with coverage gaps:** {len(gaps_by_doc)}",
        "",
        f"**Overall Status:** {'✅ PASS' if report['status'] == 'PASS' else '❌ FAIL'}",
    ]

    if oversize_chunks:
        md_lines.extend(["", "### Oversize Chunks (Top 10)", ""])
        for chunk in oversize_chunks[:10]:
            md_lines.append(
                f"- `{chunk['chunk_id']}` ({chunk['run_id']}): {chunk['token_count']} tokens"
            )

    if missing_traceability_chunks:
        md_lines.extend(["", "### Missing Traceability (Top 10)", ""])
        for chunk in missing_traceability_chunks[:10]:
            missing = [k for k, v in chunk["missing_fields"].items() if v]
            md_lines.append(
                f"- `{chunk['chunk_id']}` ({chunk['run_id']}): missing {', '.join(missing)}"
            )

    if small_chunks:
        md_lines.extend(["", "### Small Chunks (Top 10)", ""])
        for chunk in small_chunks[:10]:
            md_lines.append(
                f"- `{chunk['chunk_id']}` ({chunk['run_id']}): {chunk['token_count']} tokens, reason: {chunk['reason']}"
            )

    if gaps_by_doc:
        md_lines.extend(["", "### Coverage Gaps (Top 10)", ""])
        for doc_gap in gaps_by_doc[:10]:
            md_lines.append(
                f"- `{doc_gap['doc_id']}` ({doc_gap['run_id']}): {doc_gap['coverage_pct']:.1f}% coverage, {doc_gap['gaps_count']} gaps"
            )
            # Show first few gaps
            for i, (gap_start, gap_end) in enumerate(doc_gap["gaps"][:3]):
                md_lines.append(
                    f"  - Gap {i + 1}: chars {gap_start}-{gap_end} ({gap_end - gap_start} chars)"
                )

    report_md_file = verify_dir / "report.md"
    with open(report_md_file, "w") as f:
        f.write("\n".join(md_lines))

    # Write log
    log_file = verify_dir / "log.out"
    with open(log_file, "w") as f:
        f.write(f"Chunk verification completed at {report['timestamp']}\n")
        f.write(
            f"Processed {stats['total_runs']} runs with {stats['total_chunks']} total chunks across {stats['total_documents']} documents\n"
        )
        f.write(f"Found {len(oversize_chunks)} oversize chunks\n")
        f.write(
            f"Found {len(missing_traceability_chunks)} chunks with missing traceability\n"
        )
        f.write(
            f"Found {len(small_chunks)} small chunks (< {hard_min} tokens)\n"
        )
        f.write(f"Found {len(gaps_by_doc)} documents with coverage gaps\n")
        f.write(
            f"Average coverage: {stats['coverage_stats']['avg_coverage_pct']:.1f}%\n"
        )
        f.write(f"Status: {report['status']}\n")

    return report
