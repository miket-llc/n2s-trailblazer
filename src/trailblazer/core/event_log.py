"""Structured NDJSON event logging for observability and traceability."""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Union
from ..core.logging import log
from ..obs.events import EventAction, EventLevel, get_global_emitter

# Deprecation warning for this module
warnings.warn(
    "trailblazer.core.event_log is deprecated. Use trailblazer.obs.events.EventEmitter instead.",
    DeprecationWarning,
    stacklevel=2,
)


class EventLogger:
    """NDJSON event logger for structured observability."""

    def __init__(self, log_path: Union[str, Path], run_id: str):
        """Initialize event logger.

        Args:
            log_path: Path to write NDJSON events (e.g., var/logs/<run_id>.ndjson)
            run_id: Run identifier for all events
        """
        self.log_path = Path(log_path)
        self.run_id = run_id
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # Open file in append mode for continuous writing
        self._file = open(self.log_path, "w", encoding="utf-8")

        # Track metrics for rollup
        self.metrics = {
            "events_written": 0,
            "warnings": 0,
            "errors": 0,
            "retries": 0,
        }

    def close(self):
        """Close the event log file."""
        if hasattr(self, "_file") and self._file:
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _write_event(self, event_type: str, **kwargs):
        """Write a structured event to the NDJSON log.

        DEPRECATED: This method now delegates to EventEmitter for consistency.
        Use EventEmitter directly for new code.
        """
        # Try to delegate to global EventEmitter if available
        emitter = get_global_emitter()
        if emitter and emitter._file:
            # Map event_type to EventAction and determine level
            action_mapping = {
                "space.begin": EventAction.START,
                "space.end": EventAction.COMPLETE,
                "page.fetch": EventAction.TICK,
                "page.write": EventAction.TICK,
                "attachment.fetch": EventAction.TICK,
                "attachment.write": EventAction.TICK,
                "heartbeat": EventAction.HEARTBEAT,
                "metrics.snapshot": EventAction.TICK,
                "warning": EventAction.WARNING,
                "error": EventAction.ERROR,
                "delta.skip": EventAction.TICK,
                "delta.fetch": EventAction.TICK,
            }

            level_mapping = {
                "warning": EventLevel.WARNING,
                "error": EventLevel.ERROR,
            }

            action = action_mapping.get(event_type, EventAction.TICK)
            level = level_mapping.get(event_type, EventLevel.INFO)

            # Convert legacy fields to EventEmitter format
            emitter_kwargs = {}

            # Map common fields
            field_mapping = {
                "space_key": "space_key",
                "space_id": "space_id",
                "page_id": "page_id",
                "attachment_id": "node_id",  # Map to node_id
                "bytes": "bytes",
                "phase": "phase",
                "processed": "processed",
                "sourcefile": "sourcefile",
            }

            for old_key, new_key in field_mapping.items():
                if old_key in kwargs:
                    emitter_kwargs[new_key] = kwargs[old_key]

            # Put remaining fields in metadata
            metadata_fields = {
                k: v
                for k, v in kwargs.items()
                if k not in field_mapping
                and k not in ["timestamp", "event_type", "run_id"]
            }
            if metadata_fields:
                emitter_kwargs["metadata"] = metadata_fields

            # Emit via EventEmitter
            emitter._emit(action, level=level, **emitter_kwargs)
            self.metrics["events_written"] += 1
            return

        # Fallback to original implementation if no EventEmitter available
        timestamp = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

        event = {
            "timestamp": timestamp,
            "event_type": event_type,
            "run_id": self.run_id,
            **kwargs,
        }

        try:
            self._file.write(
                json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            )
            self._file.flush()  # Ensure immediate write
            self.metrics["events_written"] += 1
        except Exception as e:
            log.error(
                "event_log.write_failed", error=str(e), event_type=event_type
            )

    # Space-level events
    def space_begin(
        self,
        source: str,
        space_key: str,
        space_id: Optional[str] = None,
        space_name: Optional[str] = None,
        estimated_pages: Optional[int] = None,
    ):
        """Log space ingest begin event."""
        self._write_event(
            "space.begin",
            source=source,
            space_key=space_key,
            space_id=space_id,
            space_name=space_name,
            estimated_pages=estimated_pages,
        )

    def space_end(
        self,
        source: str,
        space_key: str,
        space_id: Optional[str] = None,
        pages_processed: int = 0,
        attachments_processed: int = 0,
        elapsed_seconds: float = 0.0,
        errors: int = 0,
    ):
        """Log space ingest completion event."""
        self._write_event(
            "space.end",
            source=source,
            space_key=space_key,
            space_id=space_id,
            pages_processed=pages_processed,
            attachments_processed=attachments_processed,
            elapsed_seconds=elapsed_seconds,
            errors=errors,
        )

    # Page-level events
    def page_fetch(
        self,
        source: str,
        space_key: str,
        space_id: Optional[str] = None,
        page_id: Optional[str] = None,
        title: Optional[str] = None,
        url: Optional[str] = None,
        version: Optional[int] = None,
        since_mode: bool = False,
    ):
        """Log page fetch attempt event."""
        self._write_event(
            "page.fetch",
            source=source,
            space_key=space_key,
            space_id=space_id,
            page_id=page_id,
            title=title,
            url=url,
            version=version,
            since_mode=since_mode,
        )

    def page_write(
        self,
        source: str,
        space_key: str,
        space_id: Optional[str] = None,
        page_id: Optional[str] = None,
        title: Optional[str] = None,
        url: Optional[str] = None,
        version: Optional[int] = None,
        content_sha256: Optional[str] = None,
        body_repr: Optional[str] = None,
        attachment_count: int = 0,
        bytes_written: Optional[int] = None,
    ):
        """Log page write success event."""
        self._write_event(
            "page.write",
            source=source,
            space_key=space_key,
            space_id=space_id,
            page_id=page_id,
            title=title,
            url=url,
            version=version,
            content_sha256=content_sha256,
            body_repr=body_repr,
            attachment_count=attachment_count,
            bytes_written=bytes_written,
        )

    # Attachment events
    def attachment_fetch(
        self,
        source: str,
        page_id: str,
        attachment_id: Optional[str] = None,
        attachment_title: Optional[str] = None,
        mime: Optional[str] = None,
        download_url: Optional[str] = None,
        file_size: Optional[int] = None,
    ):
        """Log attachment fetch attempt event."""
        self._write_event(
            "attachment.fetch",
            source=source,
            page_id=page_id,
            attachment_id=attachment_id,
            attachment_title=attachment_title,
            mime=mime,
            download_url=download_url,
            file_size=file_size,
        )

    def attachment_write(
        self,
        source: str,
        page_id: str,
        attachment_id: Optional[str] = None,
        attachment_title: Optional[str] = None,
        mime: Optional[str] = None,
        sha256: Optional[str] = None,
        bytes: Optional[int] = None,
        local_path: Optional[str] = None,
    ):
        """Log attachment write success event."""
        self._write_event(
            "attachment.write",
            source=source,
            page_id=page_id,
            attachment_id=attachment_id,
            attachment_title=attachment_title,
            mime=mime,
            sha256=sha256,
            bytes=bytes,
            local_path=local_path,
        )

    # System events
    def heartbeat(
        self,
        phase: str,
        processed: int,
        rate: float,
        elapsed: float,
        eta: Optional[float] = None,
        last_api_status: Optional[str] = None,
        retries: int = 0,
        memory_mb: Optional[float] = None,
    ):
        """Log periodic heartbeat event."""
        self._write_event(
            "heartbeat",
            phase=phase,
            processed=processed,
            rate=rate,
            elapsed=elapsed,
            eta=eta,
            last_api_status=last_api_status,
            retries=retries,
            memory_mb=memory_mb,
        )

    def metrics_snapshot(self, phase: str, **metrics: Union[int, float, str]):
        """Log metrics snapshot event."""
        self._write_event(
            "metrics.snapshot",
            phase=phase,
            metrics=metrics,
        )

    def warning(
        self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs
    ):
        """Log warning event."""
        self.metrics["warnings"] += 1
        self._write_event(
            "warning", message=message, context=context or {}, **kwargs
        )

    def error(
        self,
        message: str,
        error_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
        **kwargs,
    ):
        """Log error event."""
        self.metrics["errors"] += 1
        if retry_count > 0:
            self.metrics["retries"] += retry_count

        self._write_event(
            "error",
            message=message,
            error_type=error_type,
            context=context or {},
            retry_count=retry_count,
            **kwargs,
        )

    def delta_skip(
        self,
        source: str,
        space_key: str,
        page_id: str,
        reason: str,
        last_modified: Optional[str] = None,
        current_version: Optional[int] = None,
    ):
        """Log delta mode skip event (unchanged content)."""
        self._write_event(
            "delta.skip",
            source=source,
            space_key=space_key,
            page_id=page_id,
            reason=reason,
            last_modified=last_modified,
            current_version=current_version,
        )

    def delta_fetch(
        self,
        source: str,
        space_key: str,
        page_id: str,
        reason: str,
        last_modified: Optional[str] = None,
        current_version: Optional[int] = None,
        previous_version: Optional[int] = None,
    ):
        """Log delta mode fetch event (content changed)."""
        self._write_event(
            "delta.fetch",
            source=source,
            space_key=space_key,
            page_id=page_id,
            reason=reason,
            last_modified=last_modified,
            current_version=current_version,
            previous_version=previous_version,
        )


# Global event logger instance
_event_logger: Optional[EventLogger] = None


def init_event_logger(log_path: Union[str, Path], run_id: str) -> EventLogger:
    """Initialize global event logger."""
    global _event_logger
    if _event_logger:
        _event_logger.close()
    _event_logger = EventLogger(log_path, run_id)
    return _event_logger


def get_event_logger() -> Optional[EventLogger]:
    """Get the global event logger instance."""
    return _event_logger


def close_event_logger():
    """Close the global event logger."""
    global _event_logger
    if _event_logger:
        _event_logger.close()
        _event_logger = None
