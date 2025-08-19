import structlog
import sys
import os
from typing import Literal, List, Any


LogFormat = Literal["json", "plain", "auto"]


def _should_use_json_format() -> bool:
    """Determine if JSON format should be used based on environment."""
    # Check if running in CI
    ci_vars = ["CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "JENKINS_URL"]
    if any(os.environ.get(var) for var in ci_vars):
        return True

    # Check if stdout is redirected (not a TTY)
    if not sys.stdout.isatty():
        return True

    return False


def setup_logging(format_type: LogFormat = "auto") -> None:
    """
    Setup structured logging with format control.

    Args:
        format_type: "json" for JSON output, "plain" for human-readable,
                "auto" to auto-detect based on TTY/CI.
    """
    use_json = format_type == "json" or (
        format_type == "auto" and _should_use_json_format()
    )

    if use_json:
        processors: List[Any] = [
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


class LoggerWithEventHook:
    """Wrapper around structlog logger that can optionally emit events."""

    def __init__(self, logger):
        self._logger = logger
        self._event_hook_enabled = os.environ.get("TB_EMIT_EVENTS") == "1"

    def __getattr__(self, name):
        """Delegate all other attributes to the underlying logger."""
        return getattr(self._logger, name)

    def _emit_if_enabled(self, level: str, *args, **kwargs):
        """Emit event if hook is enabled and we can determine context."""
        if not self._event_hook_enabled:
            return

        # Try to import emit functions (avoid circular import)
        try:
            from ..obs.events import emit_info, emit_warn, emit_error

            # Extract run_id and stage from kwargs or context
            # This is a best-effort attempt - in practice, the calling code
            # should provide these fields
            run_id = kwargs.get(
                "run_id", os.environ.get("TB_RUN_ID", "unknown")
            )
            stage = kwargs.get("stage", "logging")
            op = kwargs.get("op", "log")

            # Create fields for event emission
            event_fields = {
                k: v
                for k, v in kwargs.items()
                if k not in ["run_id", "stage", "op"]
            }

            # Add log message to fields
            if args:
                event_fields["message"] = str(args[0])

            # Emit appropriate event
            if level == "info":
                emit_info(stage, run_id, op, **event_fields)
            elif level == "warning":
                emit_warn(stage, run_id, op, **event_fields)
            elif level == "error":
                emit_error(stage, run_id, op, **event_fields)
        except Exception:
            # Silently fail to avoid breaking logging
            pass

    def info(self, *args, **kwargs):
        """Log info message and optionally emit event."""
        self._emit_if_enabled("info", *args, **kwargs)
        return self._logger.info(*args, **kwargs)

    def warning(self, *args, **kwargs):
        """Log warning message and optionally emit event."""
        self._emit_if_enabled("warning", *args, **kwargs)
        return self._logger.warning(*args, **kwargs)

    def warn(self, *args, **kwargs):
        """Alias for warning."""
        return self.warning(*args, **kwargs)

    def error(self, *args, **kwargs):
        """Log error message and optionally emit event."""
        self._emit_if_enabled("error", *args, **kwargs)
        return self._logger.error(*args, **kwargs)

    def debug(self, *args, **kwargs):
        """Log debug message (no event emission)."""
        return self._logger.debug(*args, **kwargs)


# Create logger with event hook
_base_logger = structlog.get_logger()
log = LoggerWithEventHook(_base_logger)
