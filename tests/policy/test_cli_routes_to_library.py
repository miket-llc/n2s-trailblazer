"""Policy test: Ensure CLI routes to library functions, not shell commands."""

import ast
from pathlib import Path


def test_preflight_routes_to_library():
    """Test that preflight CLI command routes to library functions."""
    cli_main = Path("src/trailblazer/cli/main.py")
    if not cli_main.exists():
        return

    with open(cli_main, "r", encoding="utf-8") as f:
        content = f.read()

    tree = ast.parse(content)

    # Find the preflight command function
    preflight_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and "preflight_cmd" in node.name:
            preflight_func = node
            break

    if preflight_func:
        # Check that it imports and calls run_preflight_check
        has_library_import = False
        has_library_call = False

        for node in ast.walk(preflight_func):
            if isinstance(node, ast.ImportFrom):
                if (
                    node.module
                    and "preflight" in node.module
                    and any(
                        alias.name == "run_preflight_check"
                        for alias in node.names
                    )
                ):
                    has_library_import = True

            elif isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "run_preflight_check"
                ):
                    has_library_call = True

        assert (
            has_library_import
        ), "Preflight command must import run_preflight_check from library"
        assert (
            has_library_call
        ), "Preflight command must call run_preflight_check function"


def test_plan_preflight_routes_to_library():
    """Test that plan-preflight CLI command routes to library functions."""
    cli_main = Path("src/trailblazer/cli/main.py")
    if not cli_main.exists():
        return

    with open(cli_main, "r", encoding="utf-8") as f:
        content = f.read()

    tree = ast.parse(content)

    # Find the plan-preflight command function
    plan_preflight_func = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and "plan_preflight_cmd" in node.name
        ):
            plan_preflight_func = node
            break

    if plan_preflight_func:
        # Check that it imports and calls run_plan_preflight
        has_library_import = False
        has_library_call = False

        for node in ast.walk(plan_preflight_func):
            if isinstance(node, ast.ImportFrom):
                if (
                    node.module
                    and "preflight" in node.module
                    and any(
                        alias.name == "run_plan_preflight"
                        for alias in node.names
                    )
                ):
                    has_library_import = True

            elif isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "run_plan_preflight"
                ):
                    has_library_call = True

        assert (
            has_library_import
        ), "Plan-preflight command must import run_plan_preflight from library"
        assert (
            has_library_call
        ), "Plan-preflight command must call run_plan_preflight function"
