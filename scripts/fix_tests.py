#!/usr/bin/env python3
"""Script to help systematically fix failing tests."""

import subprocess
from collections import defaultdict
from pathlib import Path


def run_tests_and_categorize():
    """Run tests and categorize failures by type."""
    print("🔍 Running tests to categorize failures...")

    try:
        # Run tests with minimal output
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "--tb=no", "-q"],
            check=False,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        # Parse failures
        failures = []
        for line in result.stdout.split("\n"):
            if "FAILED" in line:
                failures.append(line.strip())

        return failures

    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return []


def categorize_failures(failures):
    """Categorize failures by type for systematic fixing."""
    categories = defaultdict(list)

    for failure in failures:
        if "test_embed_preflight.py" in failure:
            categories["CLI_COMMAND_CHANGES"].append(failure)
        elif "test_embed_loader.py" in failure:
            categories["API_INTERFACE_CHANGES"].append(failure)
        elif "test_chunk_sweep.py" in failure or "test_enrich_sweep.py" in failure:
            categories["CLI_COMMAND_CHANGES"].append(failure)
        elif "test_policy" in failure:
            categories["POLICY_EXPECTATION_CHANGES"].append(failure)
        elif "test_preflight" in failure or ("test_chunk_" in failure and "CLI" in failure):
            categories["CLI_COMMAND_CHANGES"].append(failure)
        else:
            categories["OTHER"].append(failure)

    return categories


def print_fix_plan(categories):
    """Print a systematic fix plan."""
    print("\n📋 SYSTEMATIC TEST FIX PLAN")
    print("=" * 50)

    total_failures = sum(len(failures) for failures in categories.values())
    print(f"Total failing tests: {total_failures}")

    print("\n🎯 PRIORITY 1: CLI Command Changes (Quick Wins)")
    print("-" * 40)
    cli_failures = categories["CLI_COMMAND_CHANGES"]
    print(f"Tests to fix: {len(cli_failures)}")
    print("Strategy: Update test fixtures to use new CLI commands")
    print("Files to update: tests/conftest.py (already started)")
    print("Estimated effort: 1-2 days")

    print("\n🎯 PRIORITY 2: API Interface Changes (Medium Effort)")
    print("-" * 40)
    api_failures = categories["API_INTERFACE_CHANGES"]
    print(f"Tests to fix: {len(api_failures)}")
    print("Strategy: Use compatibility layer in tests/compat/")
    print("Files to update: tests/compat/embed_loader_compat.py (already started)")
    print("Estimated effort: 2-3 days")

    print("\n🎯 PRIORITY 3: Policy & Other Changes (Lower Priority)")
    print("-" * 40)
    other_failures = categories["OTHER"] + categories["POLICY_EXPECTATION_CHANGES"]
    print(f"Tests to fix: {len(other_failures)}")
    print("Strategy: Update test expectations to match current behavior")
    print("Estimated effort: 3-4 days")

    print("\n💡 QUICK WIN EXAMPLES:")
    print("1. Update test_embed_preflight.py to use 'plan-preflight' instead of 'preflight'")
    print("2. Use cli_runner fixture from conftest.py for CLI tests")
    print("3. Use EmbedLoaderCompat for embed loader tests")

    print("\n🚀 RECOMMENDED APPROACH:")
    print("1. Start with CLI compatibility (conftest.py) - fixes ~40 tests")
    print("2. Add API compatibility layer - fixes ~50 tests")
    print("3. Update remaining test expectations - fixes ~37 tests")
    print("4. Run tests incrementally to verify fixes")


def main():
    """Main function."""
    print("🔧 Trailblazer Test Fix Helper")
    print("=" * 40)

    # Run tests and categorize failures
    failures = run_tests_and_categorize()

    if not failures:
        print("✅ No test failures found!")
        return

    # Categorize and print plan
    categories = categorize_failures(failures)
    print_fix_plan(categories)

    print("\n📊 FAILURE BREAKDOWN:")
    for category, category_failures in categories.items():
        print(f"  {category}: {len(category_failures)} tests")

    print("\n💻 To start fixing, run:")
    print(f"  cd {Path(__file__).parent.parent}")
    print("  source scripts/activate.sh")
    print("  python scripts/fix_tests.py")


if __name__ == "__main__":
    main()
