"""
Chunk assurance and quality reporting.
"""

import json
import statistics
from pathlib import Path
from typing import Dict

from .boundaries import count_tokens


def build_chunk_assurance(
    run_dir: Path, cfg: Dict, tokenizer: str = "text-embedding-3-small"
) -> Dict:
    """
    Build chunk assurance report for a run directory.

    Args:
        run_dir: Path to run directory
        cfg: Chunking configuration
        tokenizer: Tokenizer model name

    Returns:
        Assurance report dictionary
    """
    chunks_file = run_dir / "chunk" / "chunks.ndjson"
    if not chunks_file.exists():
        return {
            "tokenCap": {
                "maxTokens": cfg.get("max_tokens", 800),
                "hardMaxTokens": cfg.get("hard_max_tokens", 800),
                "overlapTokens": cfg.get("overlap_tokens", 60),
            },
            "tokenStats": {
                "min": 0,
                "median": 0,
                "p95": 0,
                "max": 0,
                "total": 0,
            },
            "charStats": {"min": 0, "median": 0, "p95": 0, "max": 0},
            "splitStrategies": {
                "heading": 0,
                "paragraph": 0,
                "sentence": 0,
                "code-fence-lines": 0,
                "table-rows": 0,
                "token-window": 0,
            },
            "breaches": {"count": 0, "examples": []},
            "traceability": {"missingCount": 0},
            "bottoms": {
                "softMinTokens": cfg.get("soft_min_tokens", 200),
                "hardMinTokens": cfg.get("hard_min_tokens", 80),
                "pctBelowSoftMin": 0.0,
                "belowSoftMinExamples": [],
                "hardMinExceptions": {
                    "count": 0,
                    "reasons": {
                        "tiny_doc": 0,
                        "fence_forced": 0,
                        "table_forced": 0,
                    },
                },
            },
            "coverage": {
                "docsWithGaps": 0,
                "avgCoveragePct": 100.0,
                "gapsExamples": [],
            },
            "status": "FAIL",
        }

    # Load all chunks
    chunks = []
    with open(chunks_file, "r") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))

    if not chunks:
        return {
            "tokenCap": {
                "maxTokens": cfg.get("max_tokens", 800),
                "hardMaxTokens": cfg.get("hard_max_tokens", 800),
                "overlapTokens": cfg.get("overlap_tokens", 60),
            },
            "tokenStats": {
                "min": 0,
                "median": 0,
                "p95": 0,
                "max": 0,
                "total": 0,
            },
            "charStats": {"min": 0, "median": 0, "p95": 0, "max": 0},
            "splitStrategies": {
                "heading": 0,
                "paragraph": 0,
                "sentence": 0,
                "code-fence-lines": 0,
                "table-rows": 0,
                "token-window": 0,
            },
            "breaches": {"count": 0, "examples": []},
            "traceability": {"missingCount": 0},
            "bottoms": {
                "softMinTokens": cfg.get("soft_min_tokens", 200),
                "hardMinTokens": cfg.get("hard_min_tokens", 80),
                "pctBelowSoftMin": 0.0,
                "belowSoftMinExamples": [],
                "hardMinExceptions": {
                    "count": 0,
                    "reasons": {
                        "tiny_doc": 0,
                        "fence_forced": 0,
                        "table_forced": 0,
                    },
                },
            },
            "coverage": {
                "docsWithGaps": 0,
                "avgCoveragePct": 100.0,
                "gapsExamples": [],
            },
            "status": "FAIL",
        }

    # Analyze token counts
    token_counts = []
    char_counts = []
    split_strategies = {
        "heading": 0,
        "paragraph": 0,
        "sentence": 0,
        "code-fence-lines": 0,
        "table-rows": 0,
        "token-window": 0,
        "no-split": 0,
        "force-truncate": 0,
    }

    breaches = []
    missing_traceability = 0
    hard_max_tokens = cfg.get("hard_max_tokens", 800)

    # v2.2 bottom-end tracking
    soft_min_tokens = cfg.get("soft_min_tokens", 200)
    hard_min_tokens = cfg.get("hard_min_tokens", 80)
    below_soft_min = []
    below_hard_min = []
    hard_min_exceptions = {"tiny_doc": 0, "fence_forced": 0, "table_forced": 0}

    for chunk in chunks:
        # Re-tokenize to verify token count
        actual_tokens = count_tokens(chunk.get("text_md", ""), tokenizer)
        token_counts.append(actual_tokens)
        char_counts.append(chunk.get("char_count", 0))

        # Track split strategy
        strategy = chunk.get("split_strategy", "unknown")
        if strategy in split_strategies:
            split_strategies[strategy] += 1

        # Check for breaches
        if actual_tokens > hard_max_tokens:
            breaches.append(
                {
                    "chunk_id": chunk.get("chunk_id", ""),
                    "token_count": actual_tokens,
                    "strategy": strategy,
                    "char_count": chunk.get("char_count", 0),
                }
            )

        # Check traceability
        has_title = bool(chunk.get("title", "").strip())
        has_url = bool(chunk.get("url", "").strip())
        has_source_system = bool(chunk.get("source_system", "").strip())

        if not has_source_system or (not has_title and not has_url):
            missing_traceability += 1

        # v2.2 bottom-end tracking
        if actual_tokens < soft_min_tokens:
            below_soft_min.append(chunk.get("chunk_id", ""))

        if actual_tokens < hard_min_tokens:
            below_hard_min.append(chunk.get("chunk_id", ""))
            # Determine reason for hard minimum violation
            text_md = chunk.get("text_md", "")
            meta = chunk.get("meta", {})
            if meta.get("tail_small"):
                # Already flagged as small tail, acceptable
                pass
            elif len(text_md.strip()) < 50:
                hard_min_exceptions["tiny_doc"] += 1
            elif "fence" in strategy:
                hard_min_exceptions["fence_forced"] += 1
            elif "table" in strategy:
                hard_min_exceptions["table_forced"] += 1

    # Calculate statistics
    token_stats = {
        "min": min(token_counts) if token_counts else 0,
        "median": int(statistics.median(token_counts)) if token_counts else 0,
        "p95": int(statistics.quantiles(token_counts, n=20)[18])
        if len(token_counts) > 20
        else (max(token_counts) if token_counts else 0),
        "max": max(token_counts) if token_counts else 0,
        "total": sum(token_counts),
    }

    char_stats = {
        "min": min(char_counts) if char_counts else 0,
        "median": int(statistics.median(char_counts)) if char_counts else 0,
        "p95": int(statistics.quantiles(char_counts, n=20)[18])
        if len(char_counts) > 20
        else (max(char_counts) if char_counts else 0),
        "max": max(char_counts) if char_counts else 0,
    }

    # Determine status
    status = (
        "PASS" if len(breaches) == 0 and missing_traceability == 0 else "FAIL"
    )

    return {
        "tokenCap": {
            "maxTokens": cfg.get("max_tokens", 800),
            "hardMaxTokens": hard_max_tokens,
            "overlapTokens": cfg.get("overlap_tokens", 60),
        },
        "tokenStats": token_stats,
        "charStats": char_stats,
        "splitStrategies": split_strategies,
        "breaches": {
            "count": len(breaches),
            "examples": breaches[:10],  # Limit examples
        },
        "traceability": {"missingCount": missing_traceability},
        "bottoms": {
            "softMinTokens": soft_min_tokens,
            "hardMinTokens": hard_min_tokens,
            "pctBelowSoftMin": (len(below_soft_min) / len(chunks)) * 100
            if chunks
            else 0.0,
            "belowSoftMinExamples": below_soft_min[:10],  # Limit examples
            "hardMinExceptions": {
                "count": len(below_hard_min),
                "reasons": hard_min_exceptions,
            },
        },
        "coverage": {
            "docsWithGaps": 0,  # TODO: Implement coverage calculation
            "avgCoveragePct": 100.0,  # TODO: Implement coverage calculation
            "gapsExamples": [],  # TODO: Implement coverage calculation
        },
        "status": status,
    }
