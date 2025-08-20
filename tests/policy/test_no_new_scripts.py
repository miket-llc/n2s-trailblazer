"""Policy test: Prevent new shell scripts for preflight/plan-preflight/embed logic."""

import subprocess
from pathlib import Path


def test_no_new_preflight_scripts():
    """Fail if any new script files contain preflight logic."""
    scripts_dir = Path("scripts")
    if not scripts_dir.exists():
        return  # No scripts directory

    # Check for any shell scripts that mention preflight, plan-preflight, or embed logic
    forbidden_terms = [
        "preflight",
        "plan-preflight",
        "embed_preflight",
        "doc_skiplist",
    ]

    for script_file in scripts_dir.rglob("*.sh"):
        if script_file.exists():
            content = script_file.read_text()
            for term in forbidden_terms:
                if term in content:
                    # Allow existing scripts but check git status
                    result = subprocess.run(
                        ["git", "status", "--porcelain", str(script_file)],
                        capture_output=True,
                        text=True,
                    )
                    if result.stdout.strip():  # File is modified or new
                        assert (
                            False
                        ), f"Script {script_file} contains forbidden term '{term}' and has been modified/added"


def test_no_bash_zsh_files_for_preflight():
    """Fail if any new .bash or .zsh files are created for preflight logic."""
    forbidden_terms = ["preflight", "plan-preflight", "doc_skiplist"]

    for ext in ["*.bash", "*.zsh"]:
        for script_file in Path(".").rglob(ext):
            if script_file.exists():
                content = script_file.read_text()
                for term in forbidden_terms:
                    if term in content:
                        assert (
                            False
                        ), f"Shell script {script_file} contains forbidden preflight logic: '{term}'"
