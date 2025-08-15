"""Enhanced event emitters with typed schemas and standard field names."""

import os
import time
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
    """Enhanced event emitter with typed schemas and file-based logging."""

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

        # Create logs directory
        self.log_dir = Path(log_dir) if log_dir else Path("var/logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Main event log
        self.log_path = self.log_dir / f"{run_id}.ndjson"

        # Create symlink to latest
        latest_link = self.log_dir / "latest.ndjson"
        if latest_link.is_symlink():
            latest_link.unlink()
        try:
            latest_link.symlink_to(self.log_path.name)
        except (OSError, FileExistsError):
            pass  # Ignore symlink failures

        self._file: Optional[TextIO] = None
        self._start_time = time.time()

    def __enter__(self):
        self._file = open(self.log_path, "a", encoding="utf-8")
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
