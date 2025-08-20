"""
Diagnostic utilities for plan-preflight blocked runs.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from ....obs.events import emit_event


def diagnose_blocked_runs(plan_bundle_dir: str) -> Dict[str, Any]:
    """
    Diagnose why runs are blocked in a plan-preflight bundle.

    Args:
        plan_bundle_dir: Path to plan-preflight bundle directory

    Returns:
        Diagnostic results with blocked reasons and counts
    """
    emit_event("plan_diagnose.start", plan_bundle_dir=plan_bundle_dir)

    bundle_dir = Path(plan_bundle_dir)
    if not bundle_dir.exists():
        raise FileNotFoundError(
            f"Plan bundle directory not found: {plan_bundle_dir}"
        )

    # Read the plan preflight results
    plan_file = bundle_dir / "plan_preflight.json"
    if not plan_file.exists():
        raise FileNotFoundError(f"Plan preflight file not found: {plan_file}")

    with open(plan_file, "r") as f:
        json.load(f)  # Validate JSON format

    # Read blocked runs
    blocked_file = bundle_dir / "blocked.txt"
    blocked_runs = []
    if blocked_file.exists():
        with open(blocked_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Format: "run_id: reason" or "var/runs/run_id # reason"
                    if ":" in line:
                        run_id = line.split(":")[0].strip()
                    elif "#" in line:
                        run_id = Path(line.split("#")[0].strip()).name
                    else:
                        run_id = (
                            Path(line).name
                            if line.startswith("var/runs/")
                            else line
                        )
                    blocked_runs.append(run_id)

    # Analyze each blocked run
    blocked_reasons = []
    reason_counts = {}
    reason_examples: dict[str, str] = {}

    for run_id in blocked_runs:
        # Check if preflight.json exists for this run
        from ....core.paths import runs

        preflight_file = runs() / run_id / "preflight" / "preflight.json"

        if preflight_file.exists():
            try:
                with open(preflight_file, "r") as f:
                    preflight_data = json.load(f)

                reasons = preflight_data.get("reasons", [])
                status = preflight_data.get("status", "UNKNOWN")

                if status == "BLOCKED" and reasons:
                    primary_reason = reasons[0]  # Use first reason as primary
                else:
                    primary_reason = "UNKNOWN_BLOCK"

            except Exception as e:
                primary_reason = f"PREFLIGHT_READ_ERROR: {e}"
        else:
            # No preflight.json - diagnose manually
            run_dir = runs() / run_id
            if not run_dir.exists():
                primary_reason = "RUN_NOT_FOUND"
            elif not (run_dir / "enrich" / "enriched.jsonl").exists():
                primary_reason = "MISSING_ENRICH"
            elif not (run_dir / "chunk" / "chunks.ndjson").exists():
                primary_reason = "MISSING_CHUNKS"
            else:
                primary_reason = "NO_PREFLIGHT_RUN"

        # Normalize reason for grouping
        normalized_reason = primary_reason.split(":")[0].strip()

        blocked_reasons.append(
            {
                "rid": run_id,
                "reason": normalized_reason,
                "details": primary_reason,
            }
        )

        # Count reasons
        if normalized_reason not in reason_counts:
            reason_counts[normalized_reason] = 0
            reason_examples[normalized_reason] = []

        reason_counts[normalized_reason] += 1
        if len(reason_examples[normalized_reason]) < 5:  # Keep top 5 examples
            reason_examples[normalized_reason].append(run_id)

    # Create diagnostic result
    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "plan_bundle_dir": plan_bundle_dir,
        "total_blocked": len(blocked_runs),
        "reason_counts": reason_counts,
        "reason_examples": reason_examples,
        "blocked_details": blocked_reasons,
    }

    emit_event(
        "plan_diagnose.complete",
        total_blocked=len(blocked_runs),
        reason_counts=reason_counts,
    )

    return result


def write_diagnostic_pack(
    result: Dict[str, Any], out_dir: str = "var/plan_diagnose"
) -> Path:
    """
    Write diagnostic pack with blocked run analysis.

    Args:
        result: Diagnostic results from diagnose_blocked_runs
        out_dir: Output directory

    Returns:
        Path to created diagnostic directory
    """
    # Create output directory
    timestamp = result["timestamp"]
    output_dir = Path(out_dir) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write blocked_reasons.json
    with open(output_dir / "blocked_reasons.json", "w") as f:
        json.dump(result["blocked_details"], f, indent=2)

    # Write individual reason files
    reason_files = {
        "MISSING_ENRICH": "missing_enrich.txt",
        "MISSING_CHUNKS": "missing_chunks.txt",
        "TOKENIZER_MISSING": "tokenizer_missing.txt",
        "CONFIG_INVALID": "config_invalid.txt",
        "EMBEDDABLE_DOCS=0": "zero_embeddable.txt",
    }

    for reason, filename in reason_files.items():
        runs_with_reason = [
            item["rid"]
            for item in result["blocked_details"]
            if item["reason"] == reason
        ]

        with open(output_dir / filename, "w") as f:
            for run_id in runs_with_reason:
                f.write(f"var/runs/{run_id}\n")

    # Write reasons.md histogram
    with open(output_dir / "reasons.md", "w") as f:
        f.write(
            f"""# Plan Preflight Diagnostic Report

**Timestamp:** {result["timestamp"]}
**Plan Bundle:** {result["plan_bundle_dir"]}
**Total Blocked Runs:** {result["total_blocked"]}

## Reason Histogram

"""
        )

        # Sort reasons by count (descending)
        sorted_reasons = sorted(
            result["reason_counts"].items(), key=lambda x: x[1], reverse=True
        )

        for reason, count in sorted_reasons:
            f.write(f"### {reason}: {count} runs\n\n")

            examples = result["reason_examples"].get(reason, [])
            if examples:
                f.write("**Example runs:**\n")
                for example in examples:
                    f.write(f"- {example}\n")
                f.write("\n")

            # Add fix guidance
            if reason == "MISSING_ENRICH":
                f.write(
                    "**Fix:** Run `trailblazer enrich <RID>` for each run\n\n"
                )
            elif reason == "MISSING_CHUNKS":
                f.write(
                    "**Fix:** Run `trailblazer chunk <RID>` for each run\n\n"
                )
            elif reason == "TOKENIZER_MISSING":
                f.write(
                    "**Fix:** Install tiktoken: `pip install tiktoken`\n\n"
                )
            elif reason == "CONFIG_INVALID":
                f.write(
                    "**Fix:** Check provider/model/dimension configuration\n\n"
                )
            elif reason == "EMBEDDABLE_DOCS=0":
                f.write(
                    "**Status:** Legitimate block - no quality documents available\n\n"
                )
            else:
                f.write("**Status:** Needs investigation\n\n")

    return output_dir
