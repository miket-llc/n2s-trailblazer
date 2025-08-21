import os
import sys
from typing import Any, Literal

import structlog

LogFormat = Literal["json", "plain", "auto"]


def _should_use_json_format() -> bool:
    """Determine if JSON format should be used based on environment."""
    # Check if running in CI
    ci_vars = ["CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "JENKINS_URL"]
    if any(os.environ.get(var) for var in ci_vars):
        return True

    # Check if stdout is redirected (not a TTY)
    return bool(not sys.stdout.isatty())


def setup_logging(format_type: LogFormat = "auto") -> None:
    """
    Setup structured logging with format control.

    Args:
        format_type: "json" for JSON output, "plain" for human-readable,
                "auto" to auto-detect based on TTY/CI.
    """
    use_json = format_type == "json" or (format_type == "auto" and _should_use_json_format())

    if use_json:
        processors: list[Any] = [
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=False),
        ]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()
