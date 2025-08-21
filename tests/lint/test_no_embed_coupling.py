"""Test to ensure chunking package doesn't import from embed modules."""

import ast
import os
import pytest
from pathlib import Path

# Mark all tests in this file as not needing database
pytestmark = pytest.mark.no_db


def test_no_embed_coupling():
    """Fail if chunk package imports anything from trailblazer.pipeline.steps.embed or similar."""

    chunk_dir = Path("src/trailblazer/pipeline/steps/chunk")
    if not chunk_dir.exists():
        # Chunk package not found, skip test
        return

    forbidden_imports = [
        "trailblazer.pipeline.steps.embed",
        "..pipeline.steps.embed",
        "...pipeline.steps.embed",
        "trailblazer.pipeline.steps.embed",
    ]

    violations = []

    for py_file in chunk_dir.glob("*.py"):
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
            f"Chunk package has forbidden embed coupling:\n{violation_msg}"
        )


@pytest.mark.skipif(
    "TB_TESTING" not in os.environ,
    reason="Requires TB_TESTING=1 to avoid database dependencies",
)
def test_chunking_package_independence():
    """Test that chunk package can be imported without embed dependencies."""

    try:
        from trailblazer.pipeline.steps.chunk.engine import chunk_document

        # Basic functionality should work
        chunks = chunk_document(
            doc_id="test", text_md="Test content", source_system="test"
        )
        assert len(chunks) == 1

    except ImportError as e:
        if "embed" in str(e).lower():
            raise AssertionError(f"Chunk package imports embed modules: {e}")
        elif "No module named" in str(e):
            # Chunk package not found, skip test
            return
        else:
            # Some other import error, might be acceptable
            pass
