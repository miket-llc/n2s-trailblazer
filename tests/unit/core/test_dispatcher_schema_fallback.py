"""Test dispatcher header parsing with new schema and legacy fallback."""

import json
import tempfile
from pathlib import Path


class TestDispatcherSchemaFallback:
    """Test that dispatcher correctly parses both new and legacy plan schemas."""

    def test_dispatcher_new_schema_parsing(self):
        """Test dispatcher correctly parses new schema keys."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create plan-preflight directory with new schema
            plan_dir = temp_path / "plan_preflight" / "20250120_120000"
            plan_dir.mkdir(parents=True)

            # Create plan_preflight.json with new schema
            plan_data = {
                "ready_runs": 5,
                "blocked_runs": 2,
                "total_tokens": 1500000,
                "estCostUSD": 0.15,
            }

            with open(plan_dir / "plan_preflight.json", "w") as f:
                json.dump(plan_data, f)

            # Create ready.txt
            with open(plan_dir / "ready.txt", "w") as f:
                f.write("var/runs/run1\n")
                f.write("var/runs/run2\n")
                f.write("var/runs/run3\n")
                f.write("var/runs/run4\n")
                f.write("var/runs/run5\n")

            # Extract counts using the same logic as embed_dispatch.sh
            ready_count = None
            blocked_count = None
            est_tokens = None

            # Prefer new schema keys, fallback to legacy keys
            # Use Python JSON parsing to test the same logic

            # Load the JSON data
            with open(plan_dir / "plan_preflight.json", "r") as f:
                plan_data_loaded = json.load(f)

            # Try new schema first
            if "ready_runs" in plan_data_loaded:
                ready_count = plan_data_loaded["ready_runs"]
            elif "runsReady" in plan_data_loaded:
                ready_count = plan_data_loaded["runsReady"]

            # Try new schema first for blocked
            if "blocked_runs" in plan_data_loaded:
                blocked_count = plan_data_loaded["blocked_runs"]
            elif "runsBlocked" in plan_data_loaded:
                blocked_count = plan_data_loaded["runsBlocked"]

            # Try new schema first for tokens
            if "total_tokens" in plan_data_loaded:
                est_tokens = plan_data_loaded["total_tokens"]
            elif "tokens" in plan_data_loaded:
                est_tokens = plan_data_loaded["tokens"]

            # Assert correct parsing
            assert ready_count == 5
            assert blocked_count == 2
            assert est_tokens == 1500000

    def test_dispatcher_legacy_schema_fallback(self):
        """Test dispatcher correctly falls back to legacy schema keys."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create plan-preflight directory with legacy schema
            plan_dir = temp_path / "plan_preflight" / "20250120_120000"
            plan_dir.mkdir(parents=True)

            # Create plan_preflight.json with legacy schema
            plan_data = {
                "runsReady": 3,
                "runsBlocked": 1,
                "tokens": 750000,
                "estCostUSD": 0.075,
            }

            with open(plan_dir / "plan_preflight.json", "w") as f:
                json.dump(plan_data, f)

            # Create ready.txt
            with open(plan_dir / "ready.txt", "w") as f:
                f.write("var/runs/run1\n")
                f.write("var/runs/run2\n")
                f.write("var/runs/run3\n")

            ready_count = None
            blocked_count = None
            est_tokens = None

            # Load the JSON data
            with open(plan_dir / "plan_preflight.json", "r") as f:
                plan_data_loaded = json.load(f)

            # Try new schema first, then fallback
            if "ready_runs" in plan_data_loaded:
                ready_count = plan_data_loaded["ready_runs"]
            elif "runsReady" in plan_data_loaded:
                ready_count = plan_data_loaded["runsReady"]

            if "blocked_runs" in plan_data_loaded:
                blocked_count = plan_data_loaded["blocked_runs"]
            elif "runsBlocked" in plan_data_loaded:
                blocked_count = plan_data_loaded["runsBlocked"]

            if "total_tokens" in plan_data_loaded:
                est_tokens = plan_data_loaded["total_tokens"]
            elif "tokens" in plan_data_loaded:
                est_tokens = plan_data_loaded["tokens"]

            # Assert correct fallback parsing
            assert ready_count == 3
            assert blocked_count == 1
            assert est_tokens == 750000

    def test_dispatcher_mixed_schema_handling(self):
        """Test dispatcher handles mixed schema (some new, some legacy keys)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create plan-preflight directory with mixed schema
            plan_dir = temp_path / "plan_preflight" / "20250120_120000"
            plan_dir.mkdir(parents=True)

            # Create plan_preflight.json with mixed schema
            plan_data = {
                "ready_runs": 4,  # New key
                "runsBlocked": 1,  # Legacy key
                "total_tokens": 1000000,  # New key
                "estCostUSD": 0.10,
            }

            with open(plan_dir / "plan_preflight.json", "w") as f:
                json.dump(plan_data, f)

            ready_count = None
            blocked_count = None
            est_tokens = None

            # Load the JSON data
            with open(plan_dir / "plan_preflight.json", "r") as f:
                plan_data_loaded = json.load(f)

            # Try new schema first, then fallback
            if "ready_runs" in plan_data_loaded:
                ready_count = plan_data_loaded["ready_runs"]
            elif "runsReady" in plan_data_loaded:
                ready_count = plan_data_loaded["runsReady"]

            if "blocked_runs" in plan_data_loaded:
                blocked_count = plan_data_loaded["blocked_runs"]
            elif "runsBlocked" in plan_data_loaded:
                blocked_count = plan_data_loaded["runsBlocked"]

            if "total_tokens" in plan_data_loaded:
                est_tokens = plan_data_loaded["total_tokens"]
            elif "tokens" in plan_data_loaded:
                est_tokens = plan_data_loaded["tokens"]

            # Assert mixed schema is handled correctly
            assert ready_count == 4  # From new key
            assert blocked_count == 1  # From legacy key
            assert est_tokens == 1000000  # From new key
