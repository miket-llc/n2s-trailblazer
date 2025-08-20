"""Tests for enrichment sweep CLI command."""

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from typer.testing import CliRunner

from trailblazer.cli.main import app

runner = CliRunner()


class TestEnrichSweepCLI:
    """Test the enrich sweep CLI command."""

    def test_enrich_sweep_help(self):
        """Test enrich sweep command help text."""
        result = runner.invoke(app, ["enrich-sweep", "--help"])
        assert result.exit_code == 0
        assert "Enrichment sweep over all runs" in result.output
        assert "--runs-glob" in result.output
        assert "--min-quality" in result.output
        assert "--max-below-threshold-pct" in result.output
        assert "--max-workers" in result.output
        assert "--force" in result.output
        assert "--dry-run" in result.output
        assert "--out-dir" in result.output

    @patch("glob.glob")
    def test_enrich_sweep_no_runs_found(self, mock_glob):
        """Test enrich sweep when no runs are found."""
        mock_glob.return_value = []

        with tempfile.TemporaryDirectory() as temp_dir:
            result = runner.invoke(
                app,
                [
                    "enrich-sweep",
                    "--runs-glob",
                    "nonexistent/*",
                    "--out-dir",
                    temp_dir,
                    "--dry-run",
                ],
            )

            assert result.exit_code == 0
            assert "Found 0 run directories" in result.output

    @patch("glob.glob")
    def test_enrich_sweep_dry_run(self, mock_glob):
        """Test enrich sweep dry run functionality."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test run directories
            run1_dir = temp_path / "run1"
            run2_dir = temp_path / "run2"
            run3_dir = temp_path / "run3"

            run1_dir.mkdir()
            run2_dir.mkdir()
            run3_dir.mkdir()

            # Create normalize directories and files
            (run1_dir / "normalize").mkdir()
            (run1_dir / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc1"}\n'
            )

            (run2_dir / "normalize").mkdir()
            (run2_dir / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc2"}\n'
            )

            # run3 has no normalize file (blocked)

            mock_glob.return_value = [
                str(run1_dir),
                str(run2_dir),
                str(run3_dir),
            ]

            output_dir = temp_path / "output"

            result = runner.invoke(
                app,
                [
                    "enrich-sweep",
                    "--runs-glob",
                    f"{temp_path}/*",
                    "--out-dir",
                    str(output_dir),
                    "--dry-run",
                ],
            )

            assert result.exit_code == 0
            assert "Candidates: 2, Blocked: 1" in result.output

            # Check output files exist
            timestamp_dirs = list(output_dir.glob("*"))
            assert len(timestamp_dirs) == 1

            sweep_dir = timestamp_dirs[0]
            candidates_file = sweep_dir / "candidates.txt"
            blocked_file = sweep_dir / "blocked.txt"

            assert candidates_file.exists()
            assert blocked_file.exists()

            # Check candidates file content
            candidates = candidates_file.read_text().strip().split("\n")
            assert len(candidates) == 2
            assert "run1" in candidates
            assert "run2" in candidates

            # Check blocked file content
            blocked = blocked_file.read_text().strip().split("\n")
            assert len(blocked) == 1
            assert "run3,MISSING_NORMALIZE" in blocked

    @patch("subprocess.run")
    @patch("glob.glob")
    def test_enrich_sweep_execution_success(self, mock_glob, mock_subprocess):
        """Test enrich sweep execution with successful enrichment."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test run directory
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()

            # Create normalize directory and file
            (run1_dir / "normalize").mkdir()
            (run1_dir / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc1"}\n'
            )

            # Create enrich directory and file (to simulate successful enrichment)
            (run1_dir / "enrich").mkdir()
            enriched_file = run1_dir / "enrich" / "enriched.jsonl"
            enriched_file.write_text('{"id": "doc1", "enriched": true}\n')

            mock_glob.return_value = [str(run1_dir)]

            # Mock successful subprocess call
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_subprocess.return_value = mock_result

            output_dir = temp_path / "output"

            with patch(
                "trailblazer.core.artifacts.runs_dir", return_value=temp_path
            ):
                result = runner.invoke(
                    app,
                    [
                        "enrich-sweep",
                        "--runs-glob",
                        f"{temp_path}/*",
                        "--out-dir",
                        str(output_dir),
                        "--max-workers",
                        "1",
                    ],
                )

            assert result.exit_code == 0

            # Check that subprocess was called with correct command
            mock_subprocess.assert_called()
            call_args = mock_subprocess.call_args[0][
                0
            ]  # First positional arg is the command list
            assert call_args[0] == "trailblazer"
            assert call_args[1] == "enrich"
            assert call_args[2] == "run1"
            assert "--min-quality" in call_args
            assert "0.6" in call_args

            # Check output files
            timestamp_dirs = list(output_dir.glob("*"))
            assert len(timestamp_dirs) == 1

            sweep_dir = timestamp_dirs[0]

            # Verify all expected files exist
            expected_files = [
                "sweep.json",
                "sweep.csv",
                "overview.md",
                "ready_for_chunk.txt",
                "blocked.txt",
                "failures.txt",
                "log.out",
            ]
            for filename in expected_files:
                assert (
                    sweep_dir / filename
                ).exists(), f"{filename} should exist"

            # Check ready_for_chunk.txt
            ready_content = (
                (sweep_dir / "ready_for_chunk.txt").read_text().strip()
            )
            assert "run1" in ready_content

            # Check sweep.json structure
            with open(sweep_dir / "sweep.json") as f:
                sweep_data = json.load(f)

            assert "timestamp" in sweep_data
            assert "parameters" in sweep_data
            assert "summary" in sweep_data
            assert "results" in sweep_data
            assert sweep_data["summary"]["passed"] == 1
            assert sweep_data["summary"]["failed"] == 0
            assert sweep_data["summary"]["blocked"] == 0

    @patch("subprocess.run")
    @patch("glob.glob")
    def test_enrich_sweep_execution_failure(self, mock_glob, mock_subprocess):
        """Test enrich sweep execution with failed enrichment."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test run directory
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()

            # Create normalize directory and file
            (run1_dir / "normalize").mkdir()
            (run1_dir / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc1"}\n'
            )

            mock_glob.return_value = [str(run1_dir)]

            # Mock failed subprocess call
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_subprocess.return_value = mock_result

            output_dir = temp_path / "output"

            with patch(
                "trailblazer.core.artifacts.runs_dir", return_value=temp_path
            ):
                result = runner.invoke(
                    app,
                    [
                        "enrich-sweep",
                        "--runs-glob",
                        f"{temp_path}/*",
                        "--out-dir",
                        str(output_dir),
                        "--max-workers",
                        "1",
                    ],
                )

            assert (
                result.exit_code == 0
            )  # Sweep itself should succeed even if individual runs fail

            # Check output files
            timestamp_dirs = list(output_dir.glob("*"))
            assert len(timestamp_dirs) == 1

            sweep_dir = timestamp_dirs[0]

            # Check failures.txt
            failures_content = (sweep_dir / "failures.txt").read_text().strip()
            assert "run1,ENRICH_ERROR:" in failures_content

            # Check sweep.json structure
            with open(sweep_dir / "sweep.json") as f:
                sweep_data = json.load(f)

            assert sweep_data["summary"]["passed"] == 0
            assert sweep_data["summary"]["failed"] == 1

    @patch("subprocess.run")
    @patch("glob.glob")
    def test_enrich_sweep_mixed_results(self, mock_glob, mock_subprocess):
        """Test enrich sweep with mixed results (pass, fail, blocked)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test run directories
            run_pass = temp_path / "run_pass"
            run_fail = temp_path / "run_fail"
            run_blocked = temp_path / "run_blocked"

            run_pass.mkdir()
            run_fail.mkdir()
            run_blocked.mkdir()

            # Setup run_pass (will succeed)
            (run_pass / "normalize").mkdir()
            (run_pass / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc1"}\n'
            )
            (run_pass / "enrich").mkdir()
            (run_pass / "enrich" / "enriched.jsonl").write_text(
                '{"id": "doc1"}\n'
            )

            # Setup run_fail (will fail enrichment)
            (run_fail / "normalize").mkdir()
            (run_fail / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc2"}\n'
            )

            # Setup run_blocked (missing normalize)
            # No normalize directory

            mock_glob.return_value = [
                str(run_pass),
                str(run_fail),
                str(run_blocked),
            ]

            # Mock subprocess calls - success for run_pass, failure for run_fail
            def mock_subprocess_side_effect(cmd, **kwargs):
                if "run_pass" in cmd:
                    result = MagicMock()
                    result.returncode = 0
                    return result
                else:  # run_fail
                    result = MagicMock()
                    result.returncode = 1
                    return result

            mock_subprocess.side_effect = mock_subprocess_side_effect

            output_dir = temp_path / "output"

            with patch(
                "trailblazer.core.artifacts.runs_dir", return_value=temp_path
            ):
                result = runner.invoke(
                    app,
                    [
                        "enrich-sweep",
                        "--runs-glob",
                        f"{temp_path}/*",
                        "--out-dir",
                        str(output_dir),
                        "--max-workers",
                        "1",
                    ],
                )

            assert result.exit_code == 0

            # Check output files
            timestamp_dirs = list(output_dir.glob("*"))
            assert len(timestamp_dirs) == 1

            sweep_dir = timestamp_dirs[0]

            # Check ready_for_chunk.txt
            ready_content = (
                (sweep_dir / "ready_for_chunk.txt").read_text().strip()
            )
            assert "run_pass" in ready_content
            assert "run_fail" not in ready_content

            # Check blocked.txt
            blocked_content = (sweep_dir / "blocked.txt").read_text().strip()
            assert "run_blocked,MISSING_NORMALIZE" in blocked_content

            # Check failures.txt
            failures_content = (sweep_dir / "failures.txt").read_text().strip()
            assert "run_fail,ENRICH_ERROR:" in failures_content

            # Check sweep.json
            with open(sweep_dir / "sweep.json") as f:
                sweep_data = json.load(f)

            assert sweep_data["summary"]["total_discovered"] == 3
            assert sweep_data["summary"]["candidates"] == 2
            assert sweep_data["summary"]["blocked"] == 1
            assert sweep_data["summary"]["passed"] == 1
            assert sweep_data["summary"]["failed"] == 1

            # Check sweep.csv
            with open(sweep_dir / "sweep.csv") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 2  # Only candidates are in CSV (not blocked)

            pass_row = next(row for row in rows if row["rid"] == "run_pass")
            fail_row = next(row for row in rows if row["rid"] == "run_fail")

            assert pass_row["status"] == "PASS"
            assert fail_row["status"] == "FAIL"
            assert "ENRICH_ERROR" in fail_row["reason"]

    def test_enrich_sweep_force_flag_behavior(self):
        """Test that --force flag is accepted but doesn't affect the enrich command (since enrich has no --force flag)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test run directory
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "normalize").mkdir()
            (run1_dir / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc1"}\n'
            )

            with patch("glob.glob", return_value=[str(run1_dir)]):
                with patch("subprocess.run") as mock_subprocess:
                    mock_result = MagicMock()
                    mock_result.returncode = 0
                    mock_subprocess.return_value = mock_result

                    output_dir = temp_path / "output"

                    with patch(
                        "trailblazer.core.artifacts.runs_dir",
                        return_value=temp_path,
                    ):
                        result = runner.invoke(
                            app,
                            [
                                "enrich-sweep",
                                "--runs-glob",
                                f"{temp_path}/*",
                                "--out-dir",
                                str(output_dir),
                                "--force",
                                "--max-workers",
                                "1",
                            ],
                        )

                    assert result.exit_code == 0

                    # Check that --force was NOT passed to enrich command (since enrich doesn't support it)
                    mock_subprocess.assert_called()
                    call_args = mock_subprocess.call_args[0][0]
                    assert "--force" not in call_args

    def test_enrich_sweep_custom_parameters(self):
        """Test enrich sweep with custom parameters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test run directory
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "normalize").mkdir()
            (run1_dir / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc1"}\n'
            )

            with patch("glob.glob", return_value=[str(run1_dir)]):
                with patch("subprocess.run") as mock_subprocess:
                    mock_result = MagicMock()
                    mock_result.returncode = 0
                    mock_subprocess.return_value = mock_result

                    output_dir = temp_path / "output"

                    with patch(
                        "trailblazer.core.artifacts.runs_dir",
                        return_value=temp_path,
                    ):
                        result = runner.invoke(
                            app,
                            [
                                "enrich-sweep",
                                "--runs-glob",
                                f"{temp_path}/*",
                                "--out-dir",
                                str(output_dir),
                                "--min-quality",
                                "0.8",
                                "--max-below-threshold-pct",
                                "0.1",
                                "--max-workers",
                                "4",
                            ],
                        )

                    assert result.exit_code == 0

                    # Check that custom parameters were passed
                    call_args = mock_subprocess.call_args[0][0]
                    assert "0.8" in call_args
                    assert "0.1" in call_args

    def test_enrich_sweep_overview_markdown_generation(self):
        """Test that overview.md is generated with correct content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test run directory
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "normalize").mkdir()
            (run1_dir / "normalize" / "normalized.ndjson").write_text(
                '{"id": "doc1"}\n'
            )
            (run1_dir / "enrich").mkdir()
            (run1_dir / "enrich" / "enriched.jsonl").write_text(
                '{"id": "doc1"}\n'
            )

            with patch("glob.glob", return_value=[str(run1_dir)]):
                with patch("subprocess.run") as mock_subprocess:
                    mock_result = MagicMock()
                    mock_result.returncode = 0
                    mock_subprocess.return_value = mock_result

                    output_dir = temp_path / "output"

                    with patch(
                        "trailblazer.core.artifacts.runs_dir",
                        return_value=temp_path,
                    ):
                        result = runner.invoke(
                            app,
                            [
                                "enrich-sweep",
                                "--runs-glob",
                                f"{temp_path}/*",
                                "--out-dir",
                                str(output_dir),
                                "--max-workers",
                                "1",
                            ],
                        )

                    assert result.exit_code == 0

                    # Check overview.md content
                    timestamp_dirs = list(output_dir.glob("*"))
                    sweep_dir = timestamp_dirs[0]
                    overview_file = sweep_dir / "overview.md"

                    assert overview_file.exists()
                    content = overview_file.read_text()

                    assert "# Enrichment Sweep Overview" in content
                    assert "**Total Runs Discovered:** 1" in content
                    assert "**Passed Enrichment:** 1" in content
                    assert "**Failed Enrichment:** 0" in content
                    assert "**Blocked (missing normalize):** 0" in content
                    assert "## Parameters" in content
                    assert "## Results by Status" in content
                    assert "## Next Steps" in content
                    assert "## Files Generated" in content

    def test_enrich_sweep_empty_normalize_file_blocked(self):
        """Test that runs with empty normalized.ndjson are blocked."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test run directory with empty normalize file
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "normalize").mkdir()
            (run1_dir / "normalize" / "normalized.ndjson").write_text(
                ""
            )  # Empty file

            with patch("glob.glob", return_value=[str(run1_dir)]):
                output_dir = temp_path / "output"

                result = runner.invoke(
                    app,
                    [
                        "enrich-sweep",
                        "--runs-glob",
                        f"{temp_path}/*",
                        "--out-dir",
                        str(output_dir),
                        "--dry-run",
                    ],
                )

                assert result.exit_code == 0
                assert "Candidates: 0, Blocked: 1" in result.output

                # Check blocked file
                timestamp_dirs = list(output_dir.glob("*"))
                sweep_dir = timestamp_dirs[0]
                blocked_content = (
                    (sweep_dir / "blocked.txt").read_text().strip()
                )
                assert "run1,MISSING_NORMALIZE" in blocked_content


class TestEnrichSweepIntegration:
    """Integration tests for enrich sweep functionality."""

    def test_enrich_sweep_creates_timestamped_directory(self):
        """Test that enrich sweep creates properly timestamped output directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "sweep_output"

            with patch("glob.glob", return_value=[]):
                result = runner.invoke(
                    app,
                    [
                        "enrich-sweep",
                        "--runs-glob",
                        "nonexistent/*",
                        "--out-dir",
                        str(output_dir),
                        "--dry-run",
                    ],
                )

                assert result.exit_code == 0

                # Check that timestamped directory was created
                timestamp_dirs = list(output_dir.glob("*"))
                assert len(timestamp_dirs) == 1

                # Verify timestamp format (YYYYMMDD_HHMMSS)
                dir_name = timestamp_dirs[0].name
                assert len(dir_name) == 15  # YYYYMMDD_HHMMSS
                assert dir_name[8] == "_"
                assert dir_name[:8].isdigit()
                assert dir_name[9:].isdigit()

    def test_enrich_sweep_deterministic_run_ordering(self):
        """Test that runs are processed in deterministic order."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create runs in non-alphabetical order
            for run_name in ["run_z", "run_a", "run_m"]:
                run_dir = temp_path / run_name
                run_dir.mkdir()
                (run_dir / "normalize").mkdir()
                (run_dir / "normalize" / "normalized.ndjson").write_text(
                    '{"id": "doc"}\n'
                )

            # Mock glob to return unsorted results
            unsorted_paths = [
                str(temp_path / name) for name in ["run_z", "run_a", "run_m"]
            ]

            with patch("glob.glob", return_value=unsorted_paths):
                output_dir = temp_path / "output"

                result = runner.invoke(
                    app,
                    [
                        "enrich-sweep",
                        "--runs-glob",
                        f"{temp_path}/*",
                        "--out-dir",
                        str(output_dir),
                        "--dry-run",
                    ],
                )

                assert result.exit_code == 0

                # Check that candidates are in sorted order
                timestamp_dirs = list(output_dir.glob("*"))
                sweep_dir = timestamp_dirs[0]
                candidates_content = (
                    (sweep_dir / "candidates.txt").read_text().strip()
                )
                candidates = candidates_content.split("\n")

                # Should be sorted alphabetically
                assert candidates == ["run_a", "run_m", "run_z"]
