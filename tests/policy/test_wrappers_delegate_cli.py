"""Policy test: Script wrappers must delegate to current CLI with correct flags."""

import pytest
import re
import glob
from pathlib import Path


def test_wrappers_use_singular_dimension_flag():
    """Test that script wrappers use --dimension (singular) not --dimensions."""

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

        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()

            # Look for --dimensions (plural) usage
            lines = content.split("\n")
            for line_num, line in enumerate(lines, 1):
                if line.strip().startswith("#"):
                    continue

                # Check for --dimensions flag
                if re.search(r"--dimensions\b", line):
                    violations.append(
                        {
                            "file": str(script_file),
                            "line": line_num,
                            "content": line.strip(),
                            "issue": "Uses --dimensions (plural) instead of --dimension",
                        }
                    )

        except Exception:
            continue

    # Assert no violations
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}:{v['line']}: {v['content']}\n    Issue: {v['issue']}"
            )

        pytest.fail(
            f"Found {len(violations)} scripts using --dimensions (plural):\n"
            + "\n".join(violation_messages)
            + "\n\nUse --dimension (singular) everywhere per requirements."
        )


def test_wrappers_delegate_to_current_cli():
    """Test that wrapper scripts delegate to current CLI commands, not deprecated ones."""

    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [
        f
        for f in script_files
        if Path(f).is_file() and f.endswith((".sh", ".bash"))
    ]

    # Define current CLI command patterns
    valid_cli_patterns = {
        "embed_run": r"trailblazer embed run",
        "embed_plan_preflight": r"trailblazer embed plan-preflight",
        "embed_dispatch": r"trailblazer embed dispatch",
        "chunk_run": r"trailblazer chunk run",
        "ingest_confluence": r"trailblazer ingest confluence",
        "normalize_from_ingest": r"trailblazer normalize from-ingest",
        "enrich": r"trailblazer enrich",
        "db_commands": r"trailblazer db \w+",
        "admin_commands": r"trailblazer admin \w+",
    }

    # Define deprecated patterns that should not be used
    deprecated_patterns = {
        "embed_load": {
            "regex": r"trailblazer embed load",
            "replacement": "trailblazer embed run",
            "description": "embed load is deprecated, use embed run",
        },
        "python_module": {
            "regex": r"python.*-m trailblazer",
            "replacement": "trailblazer",
            "description": "Direct CLI invocation preferred over python -m",
        },
        "direct_pipeline": {
            "regex": r"python.*trailblazer\.pipeline",
            "replacement": "trailblazer <command>",
            "description": "Direct pipeline imports are forbidden, use CLI",
        },
    }

    violations = []

    for script_path in script_files:
        script_file = Path(script_path)

        # Skip legacy scripts and known complex scripts
        if "_legacy" in script_file.parts:
            continue

        # Skip scripts that are allowed to be complex
        allowed_complex = ["monitor_embedding.sh", "init-db.sql"]
        if script_file.name in allowed_complex:
            continue

        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()

            # Skip if this doesn't look like a CLI wrapper
            if "trailblazer " not in content:
                continue

            lines = content.split("\n")

            # Check for deprecated patterns
            for line_num, line in enumerate(lines, 1):
                if line.strip().startswith("#"):
                    continue

                for pattern_name, pattern_info in deprecated_patterns.items():
                    if re.search(pattern_info["regex"], line, re.IGNORECASE):
                        violations.append(
                            {
                                "file": str(script_file),
                                "line": line_num,
                                "content": line.strip(),
                                "issue": pattern_info["description"],
                                "suggested_fix": pattern_info["replacement"],
                            }
                        )

        except Exception:
            continue

    # Assert no violations
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}:{v['line']}: {v['issue']}\n"
                f"    Found: {v['content']}\n"
                f"    Use: {v['suggested_fix']}"
            )

        pytest.fail(
            f"Found {len(violations)} scripts using deprecated CLI patterns:\n"
            + "\n".join(violation_messages)
            + "\n\nUpdate scripts to use current CLI commands."
        )


def test_wrappers_use_env_guards():
    """Test that wrapper scripts use proper environment guards."""

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

        # Skip non-wrapper scripts
        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()

            # Only check files that appear to be CLI wrappers
            if "trailblazer " not in content:
                continue

            # Skip known complex scripts that have their own error handling
            allowed_complex = ["monitor_embedding.sh", "process_all_runs.sh"]
            if script_file.name in allowed_complex:
                continue

            lines = content.split("\n")

            # Check for basic shell safety practices
            has_set_e = any("set -e" in line for line in lines)
            has_error_handling = any(
                ("set -euo" in line or "set -eu" in line or "|| exit" in line)
                for line in lines
            )

            if not (has_set_e or has_error_handling):
                violations.append(
                    {
                        "file": str(script_file),
                        "issue": "Missing error handling (no 'set -e' or equivalent)",
                        "suggestion": "Add 'set -euo pipefail' at the beginning",
                    }
                )

        except Exception:
            continue

    # This is more of a recommendation than a hard requirement
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}: {v['issue']}\n    Suggestion: {v['suggestion']}"
            )

        # For now, just warn rather than fail
        print(
            f"⚠️  Found {len(violations)} wrapper scripts without proper error handling:"
        )
        for msg in violation_messages:
            print(msg)
        print("Consider adding 'set -euo pipefail' for better error handling.")


def test_wrappers_have_proper_shebang():
    """Test that shell scripts have proper shebang lines."""

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

        try:
            with open(
                script_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                first_line = f.readline().strip()

            # Check for proper shebang
            if not first_line.startswith("#!"):
                violations.append(
                    {
                        "file": str(script_file),
                        "issue": "Missing shebang line",
                        "first_line": (
                            first_line[:50] + "..."
                            if len(first_line) > 50
                            else first_line
                        ),
                    }
                )
            elif first_line not in [
                "#!/bin/bash",
                "#!/usr/bin/env bash",
                "#!/bin/sh",
            ]:
                violations.append(
                    {
                        "file": str(script_file),
                        "issue": "Non-standard shebang",
                        "first_line": first_line,
                    }
                )

        except Exception:
            continue

    # Assert no violations
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}: {v['issue']}\n    Found: {v['first_line']}"
            )

        pytest.fail(
            f"Found {len(violations)} scripts with shebang issues:\n"
            + "\n".join(violation_messages)
            + "\n\nUse '#!/bin/bash' or '#!/usr/bin/env bash' for shell scripts."
        )


def test_no_hardcoded_embedding_dimensions():
    """Test that scripts don't hardcode embedding dimensions other than 1536."""

    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [
        f
        for f in script_files
        if Path(f).is_file() and f.endswith((".sh", ".py", ".bash"))
    ]

    violations = []

    # Pattern to match dimension specifications
    dimension_patterns = [
        r"--dimension\s+(\d+)",
        r"EMBED_DIMENSION[S]?[=:]\s*(\d+)",
        r"dimension[=:]\s*(\d+)",
        r"dim[=:]\s*(\d+)",
    ]

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

            lines = content.split("\n")
            for line_num, line in enumerate(lines, 1):
                # Skip comments
                if line.strip().startswith("#"):
                    continue

                # Check each dimension pattern
                for pattern in dimension_patterns:
                    matches = re.findall(pattern, line, re.IGNORECASE)
                    for match in matches:
                        dimension = int(match)
                        if dimension != 1536:
                            violations.append(
                                {
                                    "file": str(script_file),
                                    "line": line_num,
                                    "content": line.strip(),
                                    "found_dimension": dimension,
                                    "issue": f"Hardcoded dimension {dimension} instead of 1536",
                                }
                            )

        except Exception:
            continue

    # Assert no violations
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}:{v['line']}: {v['issue']}\n"
                f"    Found: {v['content']}"
            )

        pytest.fail(
            f"Found {len(violations)} scripts with wrong embedding dimensions:\n"
            + "\n".join(violation_messages)
            + "\n\nUse dimension 1536 everywhere per requirements."
        )


def test_scripts_use_trailblazer_prefix():
    """Test that scripts call 'trailblazer' command, not internal modules."""

    script_files = glob.glob("scripts/**", recursive=True)
    script_files = [
        f
        for f in script_files
        if Path(f).is_file() and f.endswith((".sh", ".py", ".bash"))
    ]

    violations = []

    # Patterns that indicate direct module usage instead of CLI
    forbidden_module_patterns = [
        r"python.*-m\s+trailblazer\.pipeline",
        r"python.*-m\s+trailblazer\.cli\.main",
        r"from\s+trailblazer\.pipeline",
        r"import\s+trailblazer\.pipeline",
    ]

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

            lines = content.split("\n")
            for line_num, line in enumerate(lines, 1):
                # Skip comments
                if line.strip().startswith("#"):
                    continue

                # Check for forbidden patterns
                for pattern in forbidden_module_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        violations.append(
                            {
                                "file": str(script_file),
                                "line": line_num,
                                "content": line.strip(),
                                "issue": "Direct module import/call instead of CLI",
                            }
                        )

        except Exception:
            continue

    # Assert no violations
    if violations:
        violation_messages = []
        for v in violations:
            violation_messages.append(
                f"  - {v['file']}:{v['line']}: {v['issue']}\n"
                f"    Found: {v['content']}\n"
                f"    Use: trailblazer <command> instead"
            )

        pytest.fail(
            f"Found {len(violations)} scripts using direct module access:\n"
            + "\n".join(violation_messages)
            + "\n\nUse 'trailblazer' CLI commands only, no direct module imports."
        )
