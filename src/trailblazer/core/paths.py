"""Centralized workspace path management.

All tool-managed artifacts go under var/ (configurable via TRAILBLAZER_WORKDIR).
Human-managed inputs go under data/ (configurable via TRAILBLAZER_DATA_DIR).
"""

from pathlib import Path
from .config import SETTINGS

# Repo root (3 levels up from this file)
ROOT = Path(__file__).resolve().parents[3]


def data() -> Path:
    """Human-managed inputs directory (default: data/)"""
    return ROOT / SETTINGS.TRAILBLAZER_DATA_DIR


def workdir() -> Path:
    """Tool-managed workspace directory (default: var/)"""
    return ROOT / SETTINGS.TRAILBLAZER_WORKDIR


def runs() -> Path:
    """Runs artifact directory (default: var/runs/)"""
    return workdir() / "runs"


def state() -> Path:
    """State files directory (default: var/state/)"""
    return workdir() / "state"


def logs() -> Path:
    """Log files directory (default: var/logs/)"""
    return workdir() / "logs"


def cache() -> Path:
    """Cache directory (default: var/cache/)"""
    return workdir() / "cache"


def tmp() -> Path:
    """Temporary files directory (default: var/tmp/)"""
    return workdir() / "tmp"


def ensure_all() -> None:
    """Create all workspace directories if they don't exist."""
    dirs_to_create = [
        data(),
        workdir(),
        runs(),
        state(),
        logs(),
        cache(),
        tmp(),
    ]

    for dir_path in dirs_to_create:
        dir_path.mkdir(parents=True, exist_ok=True)
