#!/usr/bin/env python3
"""
Script to run N2S retrieval QA harness.
This script calls the retrieval QA function directly since the CLI command may not be implemented yet.
"""

import sys
from datetime import datetime
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from trailblazer.qa.retrieval import run_retrieval_qa


def main():
    # Create timestamped output directory
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(f"var/retrieval_qc/{timestamp}")

    # QA parameters
    queries_file = "prompts/qa/queries_n2s.yaml"
    budgets = [1500, 4000, 6000]
    top_k = 12
    provider = "openai"
    model = "text-embedding-3-small"
    dimension = 1536

    print("🔍 Running N2S Retrieval QA")
    print(f"📁 Output: {output_dir}")
    print(f"📋 Queries: {queries_file}")
    print(f"💰 Budgets: {budgets}")
    print(f"🧠 Provider: {provider} ({model}, dim={dimension})")
    print(f"🎯 Top-k: {top_k}")

    try:
        # Run the QA harness
        results = run_retrieval_qa(
            queries_file=queries_file,
            budgets=budgets,
            top_k=top_k,
            provider=provider,
            model=model,
            dimension=dimension,
            output_dir=output_dir,
            min_unique_docs=6,  # Pass criteria: ≥6 unique docs in top-12
            max_tie_rate=0.35,
            require_traceability=True,
            expect_mode="doc+concept",  # Expectation scoring mode
            expect_threshold=0.7,  # Expectation pass threshold
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
