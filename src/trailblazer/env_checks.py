"""Environment checks and validations."""

import os
import platform
import sys
from typing import Optional


def assert_virtualenv_on_macos() -> None:
    """Assert virtual environment is active on macOS.
    
    Raises SystemExit with helpful message if not in venv on macOS.
    Can be bypassed with TB_ALLOW_SYSTEM_PYTHON=1.
    """
    # Allow explicit bypass for CI/automation
    if os.environ.get("TB_ALLOW_SYSTEM_PYTHON") == "1":
        return
    
    # Only enforce on macOS (Darwin)
    if platform.system() != "Darwin":
        return
    
    # Check if we're in a virtual environment
    if _is_in_virtualenv():
        return
    
    # Not in venv on macOS - fail with helpful message
    print(
        "❌ macOS venv check failed!\n"
        "\n"
        "On macOS (Darwin), all runtime commands must run inside a virtual environment.\n"
        "\n"
        "💡 To fix this:\n"
        "   • Activate your venv: source .venv/bin/activate\n" 
        "   • Or run: make setup\n"
        "   • Or set TB_ALLOW_SYSTEM_PYTHON=1 (CI only)\n",
        file=sys.stderr
    )
    sys.exit(1)


def _is_in_virtualenv() -> bool:
    """Check if running inside a virtual environment."""
    # Method 1: VIRTUAL_ENV environment variable (most common)
    if os.environ.get("VIRTUAL_ENV"):
        return True
    
    # Method 2: Poetry environment  
    if os.environ.get("POETRY_ACTIVE"):
        return True
    
    # Method 3: Conda environment
    if os.environ.get("CONDA_DEFAULT_ENV"):
        return True
    
    # Method 4: Check if sys.prefix differs from sys.base_prefix
    # This works for venv, virtualenv, and most other tools
    if hasattr(sys, 'base_prefix') and sys.prefix != sys.base_prefix:
        return True
        
    # Method 5: Check if sys.prefix differs from sys.exec_prefix (older Python)
    if hasattr(sys, 'real_prefix'):
        return True
    
    return False


def get_venv_info() -> Optional[str]:
    """Get information about the current virtual environment."""
    if not _is_in_virtualenv():
        return None
    
    # Try to identify the type and path
    if os.environ.get("VIRTUAL_ENV"):
        return f"venv: {os.environ['VIRTUAL_ENV']}"
    elif os.environ.get("POETRY_ACTIVE"):
        return f"poetry: {os.environ.get('POETRY_VENV_PATH', 'unknown path')}"
    elif os.environ.get("CONDA_DEFAULT_ENV"):
        return f"conda: {os.environ['CONDA_DEFAULT_ENV']}"
    elif hasattr(sys, 'base_prefix'):
        return f"virtualenv: {sys.prefix}"
    else:
        return "unknown virtualenv type"
