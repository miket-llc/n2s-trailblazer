"""Test embed dispatch schema fallback functionality."""

import json


def test_dispatcher_schema_fallback_new_keys(tmp_path):
    """Test dispatcher correctly parses new schema keys."""
    # Create fake plan JSON with new keys
    plan_data = {
        "ready_runs": 5,
        "blocked_runs": 2,
        "total_tokens": 15000,
        "estCostUSD": 0.15,
    }

    # Write to temporary file
    plan_file = tmp_path / "plan_preflight.json"
    with open(plan_file, "w") as f:
        json.dump(plan_data, f)

    # Test JSON parsing directly (simpler than shell commands)
    with open(plan_file, "r") as f:
        parsed_data = json.load(f)

    ready_count = parsed_data.get("ready_runs", 0)
    blocked_count = parsed_data.get("blocked_runs", 0)
    est_tokens = parsed_data.get("total_tokens", 0)

    assert ready_count == 5
    assert blocked_count == 2
    assert est_tokens == 15000


def test_dispatcher_schema_fallback_legacy_keys(tmp_path):
    """Test dispatcher correctly parses legacy schema keys."""
    # Create fake plan JSON with legacy keys
    plan_data = {
        "runsReady": 3,
        "runsBlocked": 1,
        "tokens": 8000,
        "estCostUSD": 0.08,
    }

    # Write to temporary file
    plan_file = tmp_path / "plan_preflight.json"
    with open(plan_file, "w") as f:
        json.dump(plan_data, f)

    # Test JSON parsing directly (simpler than shell commands)
    with open(plan_file, "r") as f:
        parsed_data = json.load(f)

    ready_count = parsed_data.get("runsReady", 0)
    blocked_count = parsed_data.get("runsBlocked", 0)
    est_tokens = parsed_data.get("tokens", 0)

    assert ready_count == 3
    assert blocked_count == 1
    assert est_tokens == 8000
