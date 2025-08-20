"""Policy test: Prevent subprocess/shell usage in preflight/plan-preflight/embed."""

import ast
from pathlib import Path


def test_no_subprocess_in_embed_steps():
    """AST scan embed pipeline steps for forbidden subprocess imports."""
    forbidden_imports = ["subprocess", "os.system", "shlex", "pty", "pexpect"]

    embed_dir = Path("src/trailblazer/pipeline/steps/embed")
    if not embed_dir.exists():
        return

    for py_file in embed_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue

        try:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in forbidden_imports:
                            assert (
                                False
                            ), f"Forbidden import '{alias.name}' found in {py_file}"

                elif isinstance(node, ast.ImportFrom):
                    if node.module in forbidden_imports:
                        assert (
                            False
                        ), f"Forbidden import 'from {node.module}' found in {py_file}"

                    # Check for specific functions
                    if node.module == "os" and any(
                        alias.name == "system" for alias in node.names
                    ):
                        assert (
                            False
                        ), f"Forbidden import 'from os import system' found in {py_file}"

        except Exception:
            # If we can't parse the file, that's a different issue
            pass


def test_no_subprocess_in_cli_main():
    """Check that CLI main doesn't use subprocess for preflight/embed logic."""
    cli_main = Path("src/trailblazer/cli/main.py")
    if not cli_main.exists():
        return

    try:
        with open(cli_main, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)

        # Find preflight and plan-preflight functions
        preflight_functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if "preflight" in node.name.lower():
                    preflight_functions.append(node)

        # Check each preflight function for subprocess usage
        for func_node in preflight_functions:
            for node in ast.walk(func_node):
                if isinstance(node, ast.Call):
                    # Check for subprocess.run, os.system, etc.
                    if isinstance(node.func, ast.Attribute):
                        if (
                            isinstance(node.func.value, ast.Name)
                            and node.func.value.id in ["subprocess", "os"]
                            and node.func.attr in ["run", "system", "popen"]
                        ):
                            assert (
                                False
                            ), f"Forbidden subprocess call in {func_node.name}: {node.func.value.id}.{node.func.attr}"

                    elif isinstance(node.func, ast.Name):
                        if node.func.id in ["system", "popen"]:
                            assert (
                                False
                            ), f"Forbidden shell call in {func_node.name}: {node.func.id}"

    except Exception:
        # If we can't parse, that's a different issue
        pass
