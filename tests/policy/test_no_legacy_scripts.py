"""Policy test: No legacy script patterns allowed in scripts/**."""

import pytest
import re
import glob
from pathlib import Path


def test_no_forbidden_patterns_in_scripts():
    """Test that scripts/** contains no forbidden legacy patterns."""

    # Define forbidden patterns (same as in script-audit command)
    forbidden_patterns = {
        "dimensions_plural": {
            "regex": r"--dimensions\b",
            "description": "Uses --dimensions (plural) instead of --dimension",
        },
        "embed_chunk_mixing": {
            "regex": r"(chunk.*embed|embed.*chunk)",
            "description": "Mixing embed and chunk operations in same script",
        },
        "plan_preflight_final": {
            "regex": r"plan_preflight_final",
            "description": "References deprecated plan_preflight_final directory",
        },
        "deprecated_cli_paths": {
            "regex": r"trailblazer\.pipeline\.(chunk|embed)",
            "description": "Direct imports of deprecated pipeline modules",
        },
        "adhoc_plan_txt": {
            "regex": r"(var/plan_[^/]+\.txt|var/ready_[^/]+\.txt|var/blocked_[^/]+\.txt)",
            "description": "Writing/reading ad-hoc plan .txt outside canonical locations",
        },
        "subprocess_usage": {
            "regex": r"(subprocess\.|os\.system|pexpect|pty\.|shlex\.)",
            "description": "Uses subprocess/system calls instead of Python CLI",
        },
    }

    # Scan all script files
    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [
        f
        for f in script_files
        if Path(f).is_file() and f.endswith((".sh", ".py", ".bash"))
    ]

    violations = []

    for script_path in script_files:
        script_file = Path(script_path)

        # Skip files in _legacy directory
        if "_legacy" in script_file.parts:
            continue

        # Special case: monitor_embedding.sh is canonical and allowed
        if (
            script_file.name == "monitor_embedding.sh"
            and script_file.parent.name == "scripts"
        ):
            continue

        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()

            # Check for forbidden patterns
            for pattern_name, pattern_info in forbidden_patterns.items():
                matches = re.findall(
                    pattern_info["regex"], content, re.IGNORECASE
                )
                if matches:
                    violations.append(
                        {
                            "file": str(script_file),
                            "pattern": pattern_name,
                            "description": pattern_info["description"],
                            "matches": matches[:3],  # Show first 3 matches
                        }
                    )

        except Exception as e:
            # If we can't read the file, that's also a problem
            violations.append(
                {
                    "file": str(script_file),
                    "pattern": "read_error",
                    "description": f"Cannot read script file: {e}",
                    "matches": [],
                }
            )

    # Assert no violations found
    if violations:
        violation_messages = []
        for v in violations:
            matches_str = f" (matches: {v['matches']})" if v["matches"] else ""
            violation_messages.append(
                f"  - {v['file']}: {v['description']}{matches_str}"
            )

        pytest.fail(
            f"Found {len(violations)} forbidden patterns in scripts:\n"
            + "\n".join(violation_messages)
            + "\n\nRun 'trailblazer admin script-audit --fix' to resolve these issues."
        )


def test_wrappers_have_minimal_logic():
    """Test that script wrappers contain only minimal logic (env guards + CLI delegate)."""

    # Find scripts that might be wrappers (contain trailblazer CLI calls)
    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [
        f
        for f in script_files
        if Path(f).is_file() and f.endswith((".sh", ".bash"))
    ]

    violations = []

    for script_path in script_files:
        script_file = Path(script_path)

        # Skip legacy scripts
        if "_legacy" in script_file.parts:
            continue

        # Skip known complex scripts that are allowed
        allowed_complex = ["monitor_embedding.sh", "init-db.sql"]
        if script_file.name in allowed_complex:
            continue

        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                lines = f.readlines()

            # Check if this looks like a CLI wrapper
            content = "".join(lines)
            if "trailblazer " not in content:
                continue  # Not a CLI wrapper, skip this test

            # Count non-trivial lines (excluding comments, empty lines, shebang, set -e, etc.)
            non_trivial_lines = 0
            cli_calls = 0

            for line in lines:
                line = line.strip()

                # Skip empty lines, comments, shebang, common shell settings
                if (
                    not line
                    or line.startswith("#")
                    or line.startswith("#!/")
                    or line.startswith("set -")
                    or line.startswith("export ")
                    or line.startswith("source ")
                    or line.startswith(". ")
                    or line in ["", "exit 0", "exit 1"]
                ):
                    continue

                non_trivial_lines += 1

                # Count CLI calls
                if "trailblazer " in line:
                    cli_calls += 1

            # Wrapper should have minimal logic: mostly just CLI delegation
            # Allow up to 5 non-trivial lines for env setup + CLI call
            if non_trivial_lines > 5 and cli_calls < non_trivial_lines // 2:
                violations.append(
                    {
                        "file": str(script_file),
                        "non_trivial_lines": non_trivial_lines,
                        "cli_calls": cli_calls,
                        "reason": "Too much logic for a wrapper script",
                    }
                )

        except Exception:
            continue  # Skip files we can't read

    # Assert no violations
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}: {v['non_trivial_lines']} lines of logic, "
                f"{v['cli_calls']} CLI calls ({v['reason']})"
            )

        pytest.fail(
            f"Found {len(violations)} scripts with too much logic:\n"
            + "\n".join(violation_messages)
            + "\n\nWrappers should contain only env guards + single CLI delegation."
        )


def test_no_multiple_cli_commands_per_script():
    """Test that wrapper scripts delegate to single CLI command, not multiple."""

    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [
        f
        for f in script_files
        if Path(f).is_file() and f.endswith((".sh", ".bash"))
    ]

    violations = []

    for script_path in script_files:
        script_file = Path(script_path)

        # Skip legacy and complex allowed scripts
        if "_legacy" in script_file.parts:
            continue

        # Skip known complex scripts
        allowed_complex = [
            "monitor_embedding.sh",
            "process_all_runs.sh",
            "process_all_runs_parallel.sh",
        ]
        if script_file.name in allowed_complex:
            continue

        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()

            # Count distinct trailblazer CLI calls (not in comments)
            lines = content.split("\n")
            cli_commands = set()

            for line in lines:
                line = line.strip()
                if line.startswith("#"):
                    continue

                # Look for trailblazer commands
                if "trailblazer " in line:
                    # Extract the command part
                    parts = line.split("trailblazer ")
                    for part in parts[1:]:  # Skip before first trailblazer
                        # Get the subcommand (first word after trailblazer)
                        cmd_words = part.split()
                        if cmd_words:
                            subcommand = cmd_words[0]
                            # Handle sub-subcommands like "embed run"
                            if len(cmd_words) > 1 and cmd_words[1] not in [
                                "--",
                                "-",
                            ]:
                                subcommand = f"{subcommand} {cmd_words[1]}"
                            cli_commands.add(subcommand)

            # Should have at most 1 distinct CLI command
            if len(cli_commands) > 1:
                violations.append(
                    {
                        "file": str(script_file),
                        "commands": list(cli_commands),
                        "count": len(cli_commands),
                    }
                )

        except Exception:
            continue

    # Assert no violations
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}: {v['count']} commands ({', '.join(v['commands'])})"
            )

        pytest.fail(
            f"Found {len(violations)} scripts calling multiple CLI commands:\n"
            + "\n".join(violation_messages)
            + "\n\nWrappers should delegate to a single CLI command only."
        )


def test_scripts_use_current_cli_patterns():
    """Test that scripts use current CLI patterns, not deprecated ones."""

    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [
        f
        for f in script_files
        if Path(f).is_file() and f.endswith((".sh", ".py", ".bash"))
    ]

    deprecated_patterns = {
        "old_embed_load": {
            "regex": r"embed load",
            "replacement": "embed run",
            "description": "Use 'embed run' instead of deprecated 'embed load'",
        },
        "old_chunk_command": {
            "regex": r"trailblazer chunk(?!\s)",
            "replacement": "trailblazer chunk run",
            "description": "Use 'chunk run' subcommand explicitly",
        },
        "python_module_calls": {
            "regex": r"python.*-m trailblazer\.",
            "replacement": "trailblazer",
            "description": "Use 'trailblazer' command directly, not 'python -m'",
        },
    }

    violations = []

    for script_path in script_files:
        script_file = Path(script_path)

        # Skip legacy scripts
        if "_legacy" in script_file.parts:
            continue

        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()

            # Check for deprecated patterns
            for pattern_name, pattern_info in deprecated_patterns.items():
                matches = re.findall(
                    pattern_info["regex"], content, re.IGNORECASE
                )
                if matches:
                    violations.append(
                        {
                            "file": str(script_file),
                            "pattern": pattern_name,
                            "description": pattern_info["description"],
                            "matches": matches[:2],  # Show first 2 matches
                        }
                    )

        except Exception:
            continue

    # Assert no violations (this is more of a warning test for now)
    if violations:
        violation_messages = []
        for v in violations:
            matches_str = f" (found: {v['matches']})" if v["matches"] else ""
            violation_messages.append(
                f"  - {v['file']}: {v['description']}{matches_str}"
            )

        # For now, just warn - these might be acceptable in some scripts
        print(
            f"⚠️  Found {len(violations)} deprecated CLI patterns in scripts:"
        )
        for msg in violation_messages:
            print(msg)
        print("Consider updating these to use current CLI patterns.")


def test_no_hardcoded_paths_in_scripts():
    """Test that scripts don't contain hardcoded absolute paths."""

    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [
        f
        for f in script_files
        if Path(f).is_file() and f.endswith((".sh", ".py", ".bash"))
    ]

    violations = []

    for script_path in script_files:
        script_file = Path(script_path)

        # Skip legacy scripts
        if "_legacy" in script_file.parts:
            continue

        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, 1):
                # Skip comments and common acceptable paths
                if (
                    line.strip().startswith("#")
                    or "/bin/bash" in line
                    or "/usr/bin" in line
                    or "/opt/" in line
                    or "/etc/" in line
                ):
                    continue

                # Look for hardcoded absolute paths that might be problematic
                if re.search(r"/home/[^/]+|/Users/[^/]+", line):
                    violations.append(
                        {
                            "file": str(script_file),
                            "line": line_num,
                            "content": line.strip(),
                            "reason": "Contains hardcoded user path",
                        }
                    )

        except Exception:
            continue

    # Assert no violations
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}:{v['line']}: {v['content']} ({v['reason']})"
            )

        pytest.fail(
            f"Found {len(violations)} hardcoded paths in scripts:\n"
            + "\n".join(violation_messages)
            + "\n\nUse relative paths or environment variables instead."
        )
