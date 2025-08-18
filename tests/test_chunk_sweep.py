"""Tests for chunk sweep CLI command."""

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from typer.testing import CliRunner

from trailblazer.cli.main import app

runner = CliRunner()


class TestChunkSweepCLI:
    """Test the chunk sweep CLI command."""

    def test_chunk_sweep_help(self):
        """Test chunk sweep command help text."""
        result = runner.invoke(app, ["chunk-sweep", "--help"])
        assert result.exit_code == 0
        assert "Chunk sweep over runs listed in input file" in result.output
        assert "--input-file" in result.output
        assert "--max-tokens" in result.output
        assert "--min-tokens" in result.output
        assert "--max-workers" in result.output
        assert "--force" in result.output
        assert "--dry-run" in result.output
        assert "--out-dir" in result.output

    def test_chunk_sweep_missing_input_file(self):
        """Test chunk sweep when input file doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = runner.invoke(
                app,
                [
                    "chunk-sweep",
                    "--input-file",
                    "nonexistent.txt",
                    "--out-dir",
                    temp_dir,
                ],
            )

            assert result.exit_code == 1
            assert "Input file not found" in result.output

    def test_chunk_sweep_dry_run(self):
        """Test chunk sweep dry run functionality."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file
            input_file = temp_path / "input.txt"
            input_file.write_text("run1\nrun2\nrun3\n")

            # Create test run directories with enrich data
            for run_name in ["run1", "run2"]:
                run_dir = temp_path / run_name
                run_dir.mkdir()
                (run_dir / "enrich").mkdir()
                (run_dir / "enrich" / "enriched.jsonl").write_text(
                    '{"id": "doc1"}\n'
                )

            # run3 has no enrich data (blocked)
            run3_dir = temp_path / "run3"
            run3_dir.mkdir()

            output_dir = temp_path / "output"

            with patch(
                "trailblazer.core.artifacts.runs_dir", return_value=temp_path
            ):
                result = runner.invoke(
                    app,
                    [
                        "chunk-sweep",
                        "--input-file",
                        str(input_file),
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
            assert "run3,MISSING_ENRICH" in blocked

    @patch("subprocess.run")
    def test_chunk_sweep_execution_success(self, mock_subprocess):
        """Test chunk sweep execution with successful chunking."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file
            input_file = temp_path / "input.txt"
            input_file.write_text("run1\n")

            # Create test run directory with enrich data
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "enrich").mkdir()
            (run1_dir / "enrich" / "enriched.jsonl").write_text(
                '{"id": "doc1"}\n'
            )

            # Create chunk directory and files (to simulate successful chunking)
            (run1_dir / "chunk").mkdir()
            chunks_file = run1_dir / "chunk" / "chunks.ndjson"
            chunks_file.write_text('{"id": "chunk1", "tokens": 100}\n')

            assurance_file = run1_dir / "chunk" / "chunk_assurance.json"
            assurance_data = {
                "docCount": 1,
                "chunkCount": 1,
                "tokenStats": {"total": 100, "p95": 100, "median": 100},
            }
            assurance_file.write_text(json.dumps(assurance_data))

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
                        "chunk-sweep",
                        "--input-file",
                        str(input_file),
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
            assert call_args[1] == "chunk"
            assert call_args[2] == "run1"
            assert "--max-tokens" in call_args
            assert "800" in call_args

            # Check output files
            timestamp_dirs = list(output_dir.glob("*"))
            assert len(timestamp_dirs) == 1

            sweep_dir = timestamp_dirs[0]

            # Verify all expected files exist
            expected_files = [
                "sweep.json",
                "sweep.csv",
                "overview.md",
                "ready_for_preflight.txt",
                "blocked.txt",
                "failures.txt",
                "log.out",
            ]
            for filename in expected_files:
                assert (sweep_dir / filename).exists(), (
                    f"{filename} should exist"
                )

            # Check ready_for_preflight.txt
            ready_content = (
                (sweep_dir / "ready_for_preflight.txt").read_text().strip()
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
    def test_chunk_sweep_execution_failure(self, mock_subprocess):
        """Test chunk sweep execution with failed chunking."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file
            input_file = temp_path / "input.txt"
            input_file.write_text("run1\n")

            # Create test run directory with enrich data
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "enrich").mkdir()
            (run1_dir / "enrich" / "enriched.jsonl").write_text(
                '{"id": "doc1"}\n'
            )

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
                        "chunk-sweep",
                        "--input-file",
                        str(input_file),
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
            assert "run1,CHUNK_ERROR:" in failures_content

            # Check sweep.json structure
            with open(sweep_dir / "sweep.json") as f:
                sweep_data = json.load(f)

            assert sweep_data["summary"]["passed"] == 0
            assert sweep_data["summary"]["failed"] == 1

    @patch("subprocess.run")
    def test_chunk_sweep_mixed_results(self, mock_subprocess):
        """Test chunk sweep with mixed results (pass, fail, blocked)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file
            input_file = temp_path / "input.txt"
            input_file.write_text("run_pass\nrun_fail\nrun_blocked\n")

            # Setup run_pass (will succeed)
            run_pass = temp_path / "run_pass"
            run_pass.mkdir()
            (run_pass / "enrich").mkdir()
            (run_pass / "enrich" / "enriched.jsonl").write_text(
                '{"id": "doc1"}\n'
            )
            (run_pass / "chunk").mkdir()
            (run_pass / "chunk" / "chunks.ndjson").write_text(
                '{"id": "chunk1"}\n'
            )
            (run_pass / "chunk" / "chunk_assurance.json").write_text(
                '{"docCount": 1, "tokenStats": {"total": 100}}'
            )

            # Setup run_fail (will fail chunking)
            run_fail = temp_path / "run_fail"
            run_fail.mkdir()
            (run_fail / "enrich").mkdir()
            (run_fail / "enrich" / "enriched.jsonl").write_text(
                '{"id": "doc2"}\n'
            )

            # Setup run_blocked (missing enrich)
            run_blocked = temp_path / "run_blocked"
            run_blocked.mkdir()

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
                        "chunk-sweep",
                        "--input-file",
                        str(input_file),
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

            # Check ready_for_preflight.txt
            ready_content = (
                (sweep_dir / "ready_for_preflight.txt").read_text().strip()
            )
            assert "run_pass" in ready_content
            assert "run_fail" not in ready_content

            # Check blocked.txt
            blocked_content = (sweep_dir / "blocked.txt").read_text().strip()
            assert "run_blocked,MISSING_ENRICH" in blocked_content

            # Check failures.txt
            failures_content = (sweep_dir / "failures.txt").read_text().strip()
            assert "run_fail,CHUNK_ERROR:" in failures_content

            # Check sweep.json
            with open(sweep_dir / "sweep.json") as f:
                sweep_data = json.load(f)

            assert sweep_data["summary"]["total_targets"] == 3
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
            assert "CHUNK_ERROR" in fail_row["reason"]

    def test_chunk_sweep_custom_parameters(self):
        """Test chunk sweep with custom parameters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file
            input_file = temp_path / "input.txt"
            input_file.write_text("run1\n")

            # Create test run directory with enrich data
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "enrich").mkdir()
            (run1_dir / "enrich" / "enriched.jsonl").write_text(
                '{"id": "doc1"}\n'
            )

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
                            "chunk-sweep",
                            "--input-file",
                            str(input_file),
                            "--out-dir",
                            str(output_dir),
                            "--max-tokens",
                            "1000",
                            "--min-tokens",
                            "200",
                            "--max-workers",
                            "4",
                        ],
                    )

                assert result.exit_code == 0

                # Check that custom parameters were passed
                call_args = mock_subprocess.call_args[0][0]
                assert "1000" in call_args
                assert "200" in call_args

    def test_chunk_sweep_input_file_parsing(self):
        """Test input file parsing with comments and blank lines."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file with comments and blank lines
            input_file = temp_path / "input.txt"
            input_file.write_text("""# This is a comment
run1

# Another comment
run2
run3

# Final comment""")

            # Create test run directories with enrich data
            for run_name in ["run1", "run2", "run3"]:
                run_dir = temp_path / run_name
                run_dir.mkdir()
                (run_dir / "enrich").mkdir()
                (run_dir / "enrich" / "enriched.jsonl").write_text(
                    '{"id": "doc1"}\n'
                )

            output_dir = temp_path / "output"

            with patch(
                "trailblazer.core.artifacts.runs_dir", return_value=temp_path
            ):
                result = runner.invoke(
                    app,
                    [
                        "chunk-sweep",
                        "--input-file",
                        str(input_file),
                        "--out-dir",
                        str(output_dir),
                        "--dry-run",
                    ],
                )

            assert result.exit_code == 0
            assert "Loaded 3 target runs" in result.output
            assert "Candidates: 3, Blocked: 0" in result.output

    def test_chunk_sweep_overview_markdown_generation(self):
        """Test that overview.md is generated with correct content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file
            input_file = temp_path / "input.txt"
            input_file.write_text("run1\n")

            # Create test run directory with enrich and chunk data
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "enrich").mkdir()
            (run1_dir / "enrich" / "enriched.jsonl").write_text(
                '{"id": "doc1"}\n'
            )
            (run1_dir / "chunk").mkdir()
            (run1_dir / "chunk" / "chunks.ndjson").write_text(
                '{"id": "chunk1"}\n'
            )
            (run1_dir / "chunk" / "chunk_assurance.json").write_text(
                '{"docCount": 1, "tokenStats": {"total": 100}}'
            )

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
                            "chunk-sweep",
                            "--input-file",
                            str(input_file),
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

                assert "# Chunk Sweep Overview" in content
                assert "**Total Targets:** 1" in content
                assert "**Passed Chunking:** 1" in content
                assert "**Failed Chunking:** 0" in content
                assert "**Blocked (missing enrich):** 0" in content
                assert "## Chunk Statistics" in content
                assert "## Parameters" in content
                assert "## Results by Status" in content
                assert "## Next Steps" in content
                assert "## Files Generated" in content

    def test_chunk_sweep_empty_enrich_file_blocked(self):
        """Test that runs with empty enriched.jsonl are blocked."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file
            input_file = temp_path / "input.txt"
            input_file.write_text("run1\n")

            # Create test run directory with empty enrich file
            run1_dir = temp_path / "run1"
            run1_dir.mkdir()
            (run1_dir / "enrich").mkdir()
            (run1_dir / "enrich" / "enriched.jsonl").write_text(
                ""
            )  # Empty file

            output_dir = temp_path / "output"

            with patch(
                "trailblazer.core.artifacts.runs_dir", return_value=temp_path
            ):
                result = runner.invoke(
                    app,
                    [
                        "chunk-sweep",
                        "--input-file",
                        str(input_file),
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
                assert "run1,MISSING_ENRICH" in blocked_content

    def test_chunk_sweep_deterministic_ordering(self):
        """Test that runs are processed in deterministic order."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file with unsorted runs
            input_file = temp_path / "input.txt"
            input_file.write_text("run_z\nrun_a\nrun_m\n")

            # Create test run directories with enrich data
            for run_name in ["run_z", "run_a", "run_m"]:
                run_dir = temp_path / run_name
                run_dir.mkdir()
                (run_dir / "enrich").mkdir()
                (run_dir / "enrich" / "enriched.jsonl").write_text(
                    '{"id": "doc"}\n'
                )

            output_dir = temp_path / "output"

            with patch(
                "trailblazer.core.artifacts.runs_dir", return_value=temp_path
            ):
                result = runner.invoke(
                    app,
                    [
                        "chunk-sweep",
                        "--input-file",
                        str(input_file),
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


class TestChunkSweepIntegration:
    """Integration tests for chunk sweep functionality."""

    def test_chunk_sweep_creates_timestamped_directory(self):
        """Test that chunk sweep creates properly timestamped output directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create empty input file
            input_file = temp_path / "input.txt"
            input_file.write_text("")

            output_dir = temp_path / "sweep_output"

            result = runner.invoke(
                app,
                [
                    "chunk-sweep",
                    "--input-file",
                    str(input_file),
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

    @patch("subprocess.run")
    def test_chunk_sweep_token_statistics(self, mock_subprocess):
        """Test that chunk sweep correctly calculates token statistics."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create input file
            input_file = temp_path / "input.txt"
            input_file.write_text("run1\nrun2\n")

            # Create test run directories with chunk data
            for i, run_name in enumerate(["run1", "run2"], 1):
                run_dir = temp_path / run_name
                run_dir.mkdir()
                (run_dir / "enrich").mkdir()
                (run_dir / "enrich" / "enriched.jsonl").write_text(
                    '{"id": "doc1"}\n'
                )
                (run_dir / "chunk").mkdir()
                (run_dir / "chunk" / "chunks.ndjson").write_text(
                    f'{{"id": "chunk{i}"}}\n'
                )

                # Different token stats for each run
                assurance_data = {
                    "docCount": 1,
                    "chunkCount": 1,
                    "tokenStats": {
                        "total": i * 100,
                        "p95": i * 95,
                        "median": i * 50,
                    },
                }
                (run_dir / "chunk" / "chunk_assurance.json").write_text(
                    json.dumps(assurance_data)
                )

            # Mock successful subprocess calls
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
                        "chunk-sweep",
                        "--input-file",
                        str(input_file),
                        "--out-dir",
                        str(output_dir),
                        "--max-workers",
                        "1",
                    ],
                )

            assert result.exit_code == 0

            # Check sweep.json for correct totals
            timestamp_dirs = list(output_dir.glob("*"))
            sweep_dir = timestamp_dirs[0]

            with open(sweep_dir / "sweep.json") as f:
                sweep_data = json.load(f)

            assert (
                sweep_data["summary"]["total_chunks"] == 2
            )  # 1 chunk per run
            assert sweep_data["summary"]["total_tokens"] == 300  # 100 + 200

            # Check CSV has token data
            with open(sweep_dir / "sweep.csv") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            run1_row = next(row for row in rows if row["rid"] == "run1")
            run2_row = next(row for row in rows if row["rid"] == "run2")

            assert run1_row["tokens_total"] == "100"
            assert run1_row["tokens_p95"] == "95"
            assert run2_row["tokens_total"] == "200"
            assert run2_row["tokens_p95"] == "190"
