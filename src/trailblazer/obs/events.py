"""Enhanced event emitters with typed schemas and standard field names."""

import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, TextIO
from pydantic import BaseModel, Field
from enum import Enum


class EventLevel(str, Enum):
    """Event levels for structured logging."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"


class EventAction(str, Enum):
    """Standard event actions."""

    START = "start"
    TICK = "tick"
    COMPLETE = "complete"
    ERROR = "error"
    WARNING = "warning"
    HEARTBEAT = "heartbeat"


class ObservabilityEvent(BaseModel):
    """Typed schema for all observability events."""

    # Required fields (exact names as specified)
    ts: str = Field(..., description="ISO 8601 timestamp with Z suffix")
    run_id: str = Field(..., description="Unique run identifier")
    phase: str = Field(
        ..., description="Pipeline phase (ingest, normalize, enrich, etc.)"
    )
    component: str = Field(
        ..., description="Component name (confluence, dita, embedder, etc.)"
    )
    pid: int = Field(..., description="Process ID")
    worker_id: str = Field(..., description="Worker identifier")
    level: EventLevel = Field(..., description="Event level")
    action: EventAction = Field(..., description="Event action")
    duration_ms: Optional[int] = Field(
        None, description="Duration in milliseconds"
    )

    # Context fields (relevant to the phase)
    space_key: Optional[str] = None
    space_id: Optional[str] = None
    page_id: Optional[str] = None
    node_id: Optional[str] = None
    chunk_id: Optional[str] = None
    sourcefile: Optional[str] = None
    bytes: Optional[int] = None
    embedding_dims: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    confidence: Optional[float] = None

    # Additional metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventEmitter:
    """Enhanced event emitter with typed schemas and standardized logging convention."""

    def __init__(
        self,
        run_id: str,
        phase: str,
        component: str,
        log_dir: Optional[str] = None,
    ):
        self.run_id = run_id
        self.phase = phase
        self.component = component
        self.pid = os.getpid()
        self.worker_id = f"{self.component}-{self.pid}"

        # Standard logging convention: var/logs/<run_id>/events.ndjson
        self.log_dir = Path(log_dir) if log_dir else Path("var/logs")
        self.run_log_dir = self.log_dir / run_id
        self.run_log_dir.mkdir(parents=True, exist_ok=True)

        # Primary event log and stderr log
        self.events_path = self.run_log_dir / "events.ndjson"
        self.stderr_path = self.run_log_dir / "stderr.log"

        # Create stderr.log file if it doesn't exist
        self.stderr_path.touch(exist_ok=True)

        # Symlinks for convenience
        self._create_symlinks()

        self._file: Optional[TextIO] = None
        self._start_time = time.time()

    def _create_symlinks(self):
        """Create and update symlinks per logging convention."""
        # Run-specific symlink: var/logs/<run_id>.ndjson -> var/logs/<run_id>/events.ndjson
        run_symlink = self.log_dir / f"{self.run_id}.ndjson"
        if run_symlink.exists() or run_symlink.is_symlink():
            run_symlink.unlink()
        try:
            run_symlink.symlink_to(f"{self.run_id}/events.ndjson")
        except (OSError, FileExistsError):
            pass

        # Latest symlinks
        latest_ndjson = self.log_dir / "latest.ndjson"
        latest_stderr = self.log_dir / "latest.stderr.log"

        for link, target in [
            (latest_ndjson, f"{self.run_id}/events.ndjson"),
            (latest_stderr, f"{self.run_id}/stderr.log"),
        ]:
            if link.exists() or link.is_symlink():
                link.unlink()
            try:
                link.symlink_to(target)
            except (OSError, FileExistsError):
                pass

    def _rotate_if_needed(self):
        """Check if events.ndjson needs rotation and rotate if needed."""
        try:
            from ..core.config import SETTINGS

            max_size_bytes = SETTINGS.LOGS_ROTATION_MB * 1024 * 1024

            if (
                self.events_path.exists()
                and self.events_path.stat().st_size > max_size_bytes
            ):
                # Find next rotation number
                rotation_num = 1
                while (
                    self.run_log_dir / f"events.ndjson.{rotation_num}"
                ).exists():
                    rotation_num += 1

                # Rotate current file
                rotated_path = (
                    self.run_log_dir / f"events.ndjson.{rotation_num}"
                )
                self.events_path.rename(rotated_path)

                # Create new events.ndjson
                self.events_path.touch()

        except Exception:
            pass  # Silently continue if rotation fails

    def __enter__(self):
        # Check for rotation before opening
        self._rotate_if_needed()
        self._file = open(self.events_path, "a", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()

    def _emit(
        self,
        action: EventAction,
        level: EventLevel = EventLevel.INFO,
        duration_ms: Optional[int] = None,
        **kwargs,
    ) -> None:
        """Emit a structured event."""
        if not self._file:
            return

        # Separate direct fields from metadata
        direct_fields = {
            k: v
            for k, v in kwargs.items()
            if k in ObservabilityEvent.model_fields and k != "metadata"
        }

        # Handle metadata - combine explicit metadata with other kwargs
        explicit_metadata = kwargs.get("metadata", {})
        extra_metadata = {
            k: v
            for k, v in kwargs.items()
            if k not in ObservabilityEvent.model_fields
        }
        combined_metadata = {**explicit_metadata, **extra_metadata}

        event = ObservabilityEvent(
            ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            run_id=self.run_id,
            phase=self.phase,
            component=self.component,
            pid=self.pid,
            worker_id=self.worker_id,
            level=level,
            action=action,
            duration_ms=duration_ms,
            **direct_fields,
            metadata=combined_metadata,
        )

        try:
            self._file.write(event.model_dump_json(exclude_none=True) + "\n")
            self._file.flush()
        except Exception:
            pass  # Silently fail to avoid breaking the main process

    # Phase-specific events
    def ingest_start(
        self,
        space_key: Optional[str] = None,
        sourcefile: Optional[str] = None,
        **kwargs,
    ):
        """Emit ingest.start event."""
        self._emit(
            EventAction.START,
            space_key=space_key,
            sourcefile=sourcefile,
            **kwargs,
        )

    def ingest_tick(self, processed: int, **kwargs):
        """Emit ingest.tick event."""
        self._emit(
            EventAction.TICK, metadata={"processed": processed}, **kwargs
        )

    def ingest_complete(
        self, total_processed: int, duration_ms: int, **kwargs
    ):
        """Emit ingest.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            metadata={"total_processed": total_processed},
            **kwargs,
        )

    def normalize_start(self, input_file: Optional[str] = None, **kwargs):
        """Emit normalize.start event."""
        self._emit(EventAction.START, sourcefile=input_file, **kwargs)

    def normalize_tick(self, processed: int, **kwargs):
        """Emit normalize.tick event."""
        self._emit(
            EventAction.TICK, metadata={"processed": processed}, **kwargs
        )

    def normalize_complete(
        self, total_processed: int, duration_ms: int, **kwargs
    ):
        """Emit normalize.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            metadata={"total_processed": total_processed},
            **kwargs,
        )

    def enrich_start(self, input_file: Optional[str] = None, **kwargs):
        """Emit enrich.start event."""
        self._emit(EventAction.START, sourcefile=input_file, **kwargs)

    def enrich_tick(self, processed: int, **kwargs):
        """Emit enrich.tick event."""
        self._emit(
            EventAction.TICK, metadata={"processed": processed}, **kwargs
        )

    def enrich_complete(
        self, total_processed: int, duration_ms: int, **kwargs
    ):
        """Emit enrich.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            metadata={"total_processed": total_processed},
            **kwargs,
        )

    def chunk_start(self, input_file: Optional[str] = None, **kwargs):
        """Emit chunk.start event."""
        self._emit(EventAction.START, sourcefile=input_file, **kwargs)

    def chunk_tick(self, chunk_id: str, processed: int, **kwargs):
        """Emit chunk.tick event."""
        self._emit(
            EventAction.TICK,
            chunk_id=chunk_id,
            metadata={"processed": processed},
            **kwargs,
        )

    def chunk_complete(self, total_chunks: int, duration_ms: int, **kwargs):
        """Emit chunk.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            metadata={"total_chunks": total_chunks},
            **kwargs,
        )

    def embed_start(
        self, provider: str, model: str, embedding_dims: int, **kwargs
    ):
        """Emit embed.start event."""
        self._emit(
            EventAction.START,
            provider=provider,
            model=model,
            embedding_dims=embedding_dims,
            **kwargs,
        )

    def embed_chunk(self, chunk_id: str, embedding_dims: int, **kwargs):
        """Emit embed.chunk event."""
        self._emit(
            EventAction.TICK,
            chunk_id=chunk_id,
            embedding_dims=embedding_dims,
            **kwargs,
        )

    def embed_tick(self, processed: int, **kwargs):
        """Emit embed.tick event."""
        self._emit(
            EventAction.TICK, metadata={"processed": processed}, **kwargs
        )

    def embed_complete(self, total_embedded: int, duration_ms: int, **kwargs):
        """Emit embed.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            metadata={"total_embedded": total_embedded},
            **kwargs,
        )

    def retrieve_start(self, query: str, **kwargs):
        """Emit retrieve.start event."""
        self._emit(EventAction.START, metadata={"query": query}, **kwargs)

    def retrieve_tick(self, results_found: int, **kwargs):
        """Emit retrieve.tick event."""
        self._emit(
            EventAction.TICK,
            metadata={"results_found": results_found},
            **kwargs,
        )

    def retrieve_complete(
        self, total_results: int, duration_ms: int, **kwargs
    ):
        """Emit retrieve.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            metadata={"total_results": total_results},
            **kwargs,
        )

    def compose_start(self, template: Optional[str] = None, **kwargs):
        """Emit compose.start event."""
        self._emit(
            EventAction.START, metadata={"template": template}, **kwargs
        )

    def compose_section(self, section_name: str, **kwargs):
        """Emit compose.section event."""
        self._emit(
            EventAction.TICK, metadata={"section_name": section_name}, **kwargs
        )

    def compose_complete(
        self, total_sections: int, duration_ms: int, **kwargs
    ):
        """Emit compose.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            metadata={"total_sections": total_sections},
            **kwargs,
        )

    def playbook_start(self, playbook_type: str, **kwargs):
        """Emit playbook.start event."""
        self._emit(
            EventAction.START,
            metadata={"playbook_type": playbook_type},
            **kwargs,
        )

    def playbook_file(self, filename: str, **kwargs):
        """Emit playbook.file event."""
        self._emit(EventAction.TICK, sourcefile=filename, **kwargs)

    def playbook_complete(self, total_files: int, duration_ms: int, **kwargs):
        """Emit playbook.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            metadata={"total_files": total_files},
            **kwargs,
        )

    # Standard events
    def warning(self, message: str, **kwargs):
        """Emit warning event."""
        self._emit(
            EventAction.WARNING,
            level=EventLevel.WARNING,
            metadata={"message": message},
            **kwargs,
        )

    def error(self, message: str, error_type: Optional[str] = None, **kwargs):
        """Emit error event."""
        self._emit(
            EventAction.ERROR,
            level=EventLevel.ERROR,
            metadata={"message": message, "error_type": error_type},
            **kwargs,
        )

    def heartbeat(
        self,
        processed: int,
        rate: float,
        eta_seconds: Optional[float] = None,
        active_workers: int = 1,
        **kwargs,
    ):
        """Emit heartbeat event."""
        self._emit(
            EventAction.HEARTBEAT,
            metadata={
                "processed": processed,
                "rate": rate,
                "eta_seconds": eta_seconds,
                "active_workers": active_workers,
                **kwargs,
            },
        )


# Global event emitter instance for thin adapter functions
_global_emitter: Optional[EventEmitter] = None


def set_global_emitter(emitter: EventEmitter) -> None:
    """Set the global event emitter for thin adapter functions."""
    global _global_emitter
    _global_emitter = emitter


def get_global_emitter() -> Optional[EventEmitter]:
    """Get the global event emitter instance."""
    return _global_emitter


def emit_info(stage: str, run_id: str, op: str, **fields) -> None:
    """Thin adapter: emit info-level event using global emitter."""
    emitter = _global_emitter
    if not emitter:
        # Create temporary emitter if none exists
        emitter = EventEmitter(run_id=run_id, phase=stage, component=op)
        with emitter:
            emitter._emit(EventAction.TICK, level=EventLevel.INFO, **fields)
    else:
        # Use existing emitter context
        if emitter._file:
            emitter._emit(EventAction.TICK, level=EventLevel.INFO, **fields)


def emit_warn(stage: str, run_id: str, op: str, **fields) -> None:
    """Thin adapter: emit warning-level event using global emitter."""
    emitter = _global_emitter
    if not emitter:
        # Create temporary emitter if none exists
        emitter = EventEmitter(run_id=run_id, phase=stage, component=op)
        with emitter:
            emitter._emit(
                EventAction.WARNING, level=EventLevel.WARNING, **fields
            )
    else:
        # Use existing emitter context
        if emitter._file:
            emitter._emit(
                EventAction.WARNING, level=EventLevel.WARNING, **fields
            )


def emit_error(stage: str, run_id: str, op: str, **fields) -> None:
    """Thin adapter: emit error-level event using global emitter."""
    emitter = _global_emitter
    if not emitter:
        # Create temporary emitter if none exists
        emitter = EventEmitter(run_id=run_id, phase=stage, component=op)
        with emitter:
            emitter._emit(EventAction.ERROR, level=EventLevel.ERROR, **fields)
    else:
        # Use existing emitter context
        if emitter._file:
            emitter._emit(EventAction.ERROR, level=EventLevel.ERROR, **fields)


def emit_event(event_type: str, **kwargs) -> None:
    """Generic event emission function for backward compatibility.

    This function provides a generic interface for emitting events that
    can be used by components that don't know the specific stage/run_id context.

    Args:
        event_type: Type of event (e.g., 'chunk.begin', 'chunk.doc', 'chunk.end')
        **kwargs: Event data
    """
    emitter = get_global_emitter()
    if emitter and emitter._file:
        # Map event types to appropriate EventEmitter methods
        if event_type.startswith("chunk."):
            if event_type == "chunk.begin":
                # Use chunk_start with appropriate parameters
                input_file = kwargs.get("input_file")
                emitter.chunk_start(input_file=input_file)
            elif event_type == "chunk.doc":
                # Use generic _emit for chunk.doc events with chunk-specific data
                emitter._emit(EventAction.TICK, **kwargs)
            elif event_type == "chunk.end":
                # Use chunk_complete with appropriate parameters
                total_chunks = kwargs.get("total_chunks", 0)
                duration_ms = kwargs.get("duration_ms", 0)
                emitter.chunk_complete(
                    total_chunks=total_chunks, duration_ms=duration_ms
                )
            elif event_type in [
                "chunk.force_truncate",
                "chunk.coverage_warning",
            ]:
                message = kwargs.get("message", event_type)
                emitter.warning(message, **kwargs)
            else:
                # Generic chunk event
                emitter._emit(EventAction.TICK, **kwargs)
        else:
            # Generic event
            emitter._emit(EventAction.TICK, **kwargs)


@contextmanager
def stage_run(stage: str, run_id: str, op: str, **start_fields):
    """Context manager that emits START/END events with duration tracking.

    Args:
        stage: Pipeline stage name (e.g., 'ingest', 'normalize', 'chunk')
        run_id: Unique run identifier
        op: Operation name (e.g., 'confluence', 'dita', 'embedder')
        **start_fields: Additional fields for the START event

    Usage:
        with stage_run('ingest', run_id, 'confluence', space_key='DEV') as ctx:
            # do work
            ctx.update(pages_processed=42)  # Add fields to END event
    """
    start_time = time.time()

    # Create or use existing emitter
    emitter = _global_emitter
    temp_emitter = None
    if not emitter:
        temp_emitter = EventEmitter(run_id=run_id, phase=stage, component=op)
        emitter = temp_emitter

    class StageContext:
        def __init__(self):
            self.end_fields = {}

        def update(self, **fields):
            """Add fields that will be included in the END event."""
            self.end_fields.update(fields)

    ctx = StageContext()

    # Emit START event
    if temp_emitter:
        with temp_emitter:
            temp_emitter._emit(
                EventAction.START, level=EventLevel.INFO, **start_fields
            )
    else:
        if emitter._file:
            emitter._emit(
                EventAction.START, level=EventLevel.INFO, **start_fields
            )

    try:
        yield ctx
    finally:
        # Calculate duration
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)

        # Emit END event with duration
        end_fields = {**ctx.end_fields, "status": "complete"}

        if temp_emitter:
            with temp_emitter:
                temp_emitter._emit(
                    EventAction.COMPLETE,
                    level=EventLevel.INFO,
                    duration_ms=duration_ms,
                    **end_fields,
                )
        else:
            if emitter._file:
                emitter._emit(
                    EventAction.COMPLETE,
                    level=EventLevel.INFO,
                    duration_ms=duration_ms,
                    **end_fields,
                )
