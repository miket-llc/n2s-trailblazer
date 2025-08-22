#!/usr/bin/env python3
"""
Comprehensive test runner for Trailblazer with proper environment configuration.
This script ensures all tests run with the correct database and embedding provider
settings.
"""

import os
import subprocess
import sys


def run_tests_with_env(env_vars, test_path, description):
    """Run tests with specific environment variables."""
    print(f"\n{'=' * 60}")
    print(f"Running {description}")
    print(f"{'=' * 60}")

    # Set environment variables
    env = os.environ.copy()
    env.update(env_vars)

    # Run pytest
    cmd = [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    # Parse results
    if "collected" in result.stdout:
        lines = result.stdout.split("\n")
        for line in lines:
            if "collected" in line and "items" in line:
                print(f"📊 {line.strip()}")
            elif "passed" in line and "failed" in line and "errors" in line:
                print(f"📈 {line.strip()}")
                break

    if result.returncode == 0:
        print(f"✅ {description} - All tests passed!")
    else:
        print(f"❌ {description} - Some tests failed")
        if result.stderr:
            print(f"Error output: {result.stderr[:500]}...")

    return result.returncode == 0


def main():
    """Run all test categories with proper configuration."""
    print("🧪 Trailblazer Comprehensive Test Suite")
    print("=" * 60)

    # Test categories and their configurations
    test_categories = [
        {"env": {"TB_TESTING_PGVECTOR": "1"}, "path": "tests/qa/", "desc": "QA Tests (PostgreSQL + Vector Search)"},
        {
            "env": {"TB_TESTING_PGVECTOR": "1"},
            "path": "tests/retrieval/",
            "desc": "Retrieval Tests (PostgreSQL + Vector Search)",
        },
        {
            "env": {"TB_TESTING_PGVECTOR": "1"},
            "path": "tests/embed/",
            "desc": "Embed Tests (PostgreSQL + Vector Search)",
        },
        {"env": {"TB_TESTING_PGVECTOR": "1"}, "path": "tests/cli/", "desc": "CLI Tests (PostgreSQL + Vector Search)"},
        {"env": {}, "path": "tests/unit/", "desc": "Unit Tests (No Database)"},
        {"env": {}, "path": "tests/policy/", "desc": "Policy Tests (No Database)"},
        {"env": {}, "path": "tests/lint/", "desc": "Lint Tests (No Database)"},
    ]

    results = []
    total_tests = 0
    passed_tests = 0

    for category in test_categories:
        success = run_tests_with_env(category["env"], category["path"], category["desc"])
        results.append((category["desc"], success))

        if success:
            passed_tests += 1
        total_tests += 1

    # Summary
    print(f"\n{'=' * 60}")
    print("📋 TEST SUMMARY")
    print(f"{'=' * 60}")

    for desc, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {desc}")

    print(f"\n📊 Overall: {passed_tests}/{total_tests} test categories passed")

    if passed_tests == total_tests:
        print("🎉 All test categories passed!")
        return 0
    else:
        print("⚠️  Some test categories failed. Check output above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
