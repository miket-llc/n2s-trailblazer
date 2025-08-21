#!/usr/bin/env python3
"""Fix line length issues in test_db_dimension_guard.py"""


def fix_file():
    with open("tests/embed/test_db_dimension_guard.py") as f:
        lines = f.readlines()

    # Fix line 158 - docstring
    lines[157] = '    """Test dimension detection via test embedding when dim attribute missing."""\n'

    # Fix line 206 - comment
    lines[205] = "            # Should not raise exception (dimension detected via test embedding)\n"

    # Fix line 307 - comment
    lines[306] = "            # Should not raise exception (dimension detection failed, but continues)\n"

    # Fix line 311 - comment
    lines[310] = "            # Should process (dimension validation was skipped due to detection failure)\n"

    # Fix line 398 - comment
    lines[397] = "            # Should raise ValueError when creating embedder with wrong dimension\n"

    with open("tests/embed/test_db_dimension_guard.py", "w") as f:
        f.writelines(lines)


if __name__ == "__main__":
    fix_file()
    print("Fixed line length issues in test_db_dimension_guard.py")
