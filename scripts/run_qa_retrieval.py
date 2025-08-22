#!/usr/bin/env python3
"""
Script to run N2S retrieval QA harness.
This script calls the retrieval QA function directly since the CLI command may not be implemented yet.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from trailblazer.qa.retrieval import run_retrieval_qa


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run N2S Retrieval QA Harness")
    parser.add_argument("--queries-file", default="prompts/qa/queries_n2s.yaml", help="Path to queries YAML file")
    parser.add_argument("--budgets", nargs="+", type=int, default=[1500, 4000, 6000], help="Character budgets to test")
    parser.add_argument("--top-k", type=int, default=12, help="Number of top results to retrieve")
    parser.add_argument("--provider", default="openai", help="Embedding provider name")
    parser.add_argument("--model", default="text-embedding-3-small", help="Embedding model name")
    parser.add_argument("--dimension", type=int, default=1536, help="Embedding dimension")
    parser.add_argument(
        "--expect-mode",
        default="doc+concept",
        choices=["doc+concept", "doc-only", "concept-only"],
        help="Expectation scoring mode",
    )
    parser.add_argument("--expect-threshold", type=float, default=0.7, help="Expectation pass threshold")
    parser.add_argument(
        "--expect-profile", default="default", choices=["default", "n2s"], help="Expectation profile to use"
    )
    parser.add_argument(
        "--space-whitelist", nargs="+", help="Space keys to whitelist (comma-separated or space-separated)"
    )
    parser.add_argument("--n2s-strict", action="store_true", help="Use strict N2S mode with MTDLANDTL space whitelist")
    parser.add_argument("--trace-dir", type=Path, help="Directory to save per-query JSON traces")

    args = parser.parse_args()

    # Handle N2S strict mode
    if args.n2s_strict:
        args.expect_profile = "n2s"
        if not args.space_whitelist:
            args.space_whitelist = ["MTDLANDTL"]

    # Handle space whitelist parsing
    space_whitelist = None
    if args.space_whitelist:
        # Handle both comma-separated and space-separated formats
        space_whitelist = []
        for item in args.space_whitelist:
            space_whitelist.extend(item.split(","))
        space_whitelist = [s.strip() for s in space_whitelist if s.strip()]

    # Create timestamped output directory
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(f"var/retrieval_qc/{timestamp}")

    print("🔍 Running N2S Retrieval QA")
    print(f"📁 Output: {output_dir}")
    print(f"📋 Queries: {args.queries_file}")
    print(f"💰 Budgets: {args.budgets}")
    print(f"🧠 Provider: {args.provider} ({args.model}, dim={args.dimension})")
    print(f"🎯 Top-k: {args.top_k}")
    print(f"📊 Expect Mode: {args.expect_mode}")
    print(f"📊 Expect Profile: {args.expect_profile}")
    print(f"📊 Expect Threshold: {args.expect_threshold}")
    if space_whitelist:
        print(f"🔒 Space Whitelist: {space_whitelist}")

    try:
        # Run the QA harness
        results = run_retrieval_qa(
            queries_file=args.queries_file,
            budgets=args.budgets,
            top_k=args.top_k,
            provider=args.provider,
            model=args.model,
            dimension=args.dimension,
            output_dir=output_dir,
            min_unique_docs=6,  # Pass criteria: ≥6 unique docs in top-12
            max_tie_rate=0.35,
            require_traceability=True,
            expect_mode=args.expect_mode,
            expect_threshold=args.expect_threshold,
            space_whitelist=space_whitelist,
            expect_profile=args.expect_profile,
            trace_dir=args.trace_dir,
        )

        print("\n✅ QA harness completed successfully!")
        print(f"📊 Results saved to: {output_dir}")
        print(f"📈 Summary: {results}")

        return output_dir

    except Exception as e:
        print(f"❌ Error running QA harness: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
