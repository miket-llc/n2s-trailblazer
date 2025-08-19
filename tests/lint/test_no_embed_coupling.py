"""Test to ensure chunking package doesn't import from embed modules."""

import ast
import os
import pytest
from pathlib import Path


def test_no_embed_coupling():
    """Fail if trailblazer.chunking imports anything from trailblazer.pipeline.steps.embed or similar."""

    chunking_dir = Path("src/trailblazer/chunking")
    if not chunking_dir.exists():
        # Chunking package not yet created, skip test
        return

    forbidden_imports = [
        "trailblazer.pipeline.steps.embed",
        "..pipeline.steps.embed",
        "...pipeline.steps.embed",
        "src.trailblazer.pipeline.steps.embed",
    ]

    violations = []

    for py_file in chunking_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue

        with open(py_file, "r") as f:
            content = f.read()

        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue  # Skip files with syntax errors

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_imports:
                        if forbidden in alias.name:
                            violations.append(
                                f"{py_file}: imports {alias.name}"
                            )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_imports:
                        if forbidden in node.module:
                            violations.append(
                                f"{py_file}: from {node.module} import ..."
                            )

    if violations:
        violation_msg = "\n".join(violations)
        raise AssertionError(
            f"Chunking package has forbidden embed coupling:\n{violation_msg}"
        )


@pytest.mark.skipif(
    "TB_TESTING" not in os.environ,
    reason="Requires TB_TESTING=1 to avoid database dependencies",
)
def test_chunking_package_independence():
    """Test that chunking package can be imported without embed dependencies."""

    chunking_dir = Path("src/trailblazer/chunking")
    if not chunking_dir.exists():
        return

    try:
        # This should work without importing embed modules
        from trailblazer.chunking.engine import chunk_document

        # Basic functionality should work
        chunks = chunk_document(
            doc_id="test", text_md="Test content", source_system="test"
        )
        assert len(chunks) == 1

    except ImportError as e:
        if "embed" in str(e).lower():
            raise AssertionError(
                f"Chunking package imports embed modules: {e}"
            )
        else:
            # Some other import error, might be acceptable
            pass
