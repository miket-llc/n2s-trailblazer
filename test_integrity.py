#!/usr/bin/env python3
"""Test data integrity and format validation."""

import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, "src")
from trailblazer.obs.integrity import run_data_integrity_check


def create_test_run():
    """Create test run with sample data."""
    run_id = "test-integrity-run"
    run_dir = Path(f"var/runs/{run_id}")

    # Create run directories
    for phase in ["ingest", "normalize", "enrich"]:
        (run_dir / phase).mkdir(parents=True, exist_ok=True)

    # Create test data with traceability
    ingest_data = [
        {
            "id": "page-1",
            "url": "https://example.com/page-1",
            "space_key": "TEST",
            "space_id": "12345",
            "title": "Test Page 1",
            "labels": ["test", "example"],
            "breadcrumbs": ["Home", "Test", "Page 1"],
            "content_sha256": "abc123",
            "attachments": [{"id": "att-1", "filename": "test.pdf"}],
        },
        {
            "id": "page-2",
            "url": "https://example.com/page-2",
            "space_key": "TEST",
            "space_id": "12345",
            "title": "Test Page 2",
            "labels": ["test"],
            "breadcrumbs": ["Home", "Test", "Page 2"],
            "content_sha256": "def456",
        },
    ]

    normalize_data = [
        {
            "id": "page-1",
            "url": "https://example.com/page-1",
            "space_key": "TEST",
            "title": "Test Page 1",
            "text_md": "# Test Page 1\nContent here",
            "labels": ["test", "example"],
            "breadcrumbs": ["Home", "Test", "Page 1"],
            "content_sha256": "abc123",
        },
        {
            "id": "page-2",
            "url": "https://example.com/page-2",
            "space_key": "TEST",
            "title": "Test Page 2",
            "text_md": "# Test Page 2\nMore content",
            "labels": ["test"],
            "breadcrumbs": ["Home", "Test", "Page 2"],
            "content_sha256": "def456",
        },
    ]

    # Missing page-2 in enrich to test broken chain
    enrich_data = [
        {
            "id": "page-1",
            "url": "https://example.com/page-1",
            "space_key": "TEST",
            "title": "Test Page 1",
            "collection": "test",
            "quality_flags": [],
            "labels": ["test", "example"],
            "breadcrumbs": ["Home", "Test", "Page 1"],
            "content_sha256": "abc123",
            # Missing some fields to test retention
        }
    ]

    # Write files
    files_data = [
        (run_dir / "ingest" / "confluence.ndjson", ingest_data),
        (run_dir / "normalize" / "normalized.ndjson", normalize_data),
        (run_dir / "enrich" / "enriched.jsonl", enrich_data),
    ]

    for file_path, data in files_data:
        with open(file_path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item) + "\n")

    # Create some markdown files for format checking
    compose_dir = run_dir / "compose"
    compose_dir.mkdir(exist_ok=True)

    (compose_dir / "test_output.md").write_text("""# Test Output

This is a test markdown file.

- Item 1
- Item 2
""")

    return run_id, run_dir


def test_integrity_checks():
    """Test the data integrity checking system."""
    print("🔍 Testing Data Integrity Checks")

    # Create test run
    run_id, run_dir = create_test_run()
    print(f"   ✓ Created test run: {run_id}")

    try:
        # Run integrity checks
        report, json_path, md_path = run_data_integrity_check(
            run_id, sample_size=5
        )

        print("   ✓ Completed integrity checks")
        print(f"   Status: {report['overall_status']}")
        print(
            f"   Issues: {report['issue_summary']['total']} total, {report['issue_summary']['errors']} errors"
        )

        # Show some details
        trace = report["checks"]["traceability"]
        print(
            f"   Traceability: {trace['valid_chains']} valid, {trace['broken_chains']} broken chains"
        )

        sampling = report["checks"]["sampling"]
        print(
            f"   Sampling: {sampling['samples_created']} sample files created"
        )

        print(f"   ✓ Reports written: {json_path}, {md_path}")

        # Assert test conditions instead of returning
        assert report["overall_status"] in ["passed", "failed"]
        assert isinstance(report["issue_summary"]["total"], int)
        assert json_path.exists()
        assert md_path.exists()

    except Exception as e:
        print(f"   ❌ Error: {e}")
        pytest.fail(f"Integrity check failed: {e}")


if __name__ == "__main__":
    print("🎯 Testing Data Integrity & Format Validation\n")

    try:
        test_integrity_checks()
        print("\n🎉 Data integrity testing completed!")
    except Exception as e:
        print(f"\n❌ Testing failed: {e}")
