"""Enhanced event emitters with typed schemas and standard field names."""

import os
import time
import json
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

        # Symlinks for convenience
        self._create_symlinks()

        self._file: Optional[TextIO] = None
        self._start_time = time.time()

    def __enter__(self):
        # Check for rotation before opening
        self._rotate_if_needed()
        self._file = open(self.events_path, "a", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()

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

    # Compatibility shim and global context for legacy emitters
    _global_context: Dict[str, Any] = {}

    @classmethod
    def set_event_context(
        cls, run_id: str, stage: str, component: str = "runner"
    ) -> None:
        """Set global event context for modules that import emit_event directly."""
        cls._global_context = {
            "run_id": run_id,
            "stage": stage,
            "component": component,
        }

    @classmethod
    def clear_event_context(cls) -> None:
        """Clear global event context."""
        cls._global_context = {}

    def _emit(
        self,
        action: EventAction,
        level: EventLevel = EventLevel.INFO,
        duration_ms: Optional[int] = None,
        **kwargs,
    ) -> None:
        """Emit a structured event using the canonical schema."""
        if not self._file:
            return

        # Map action to canonical status
        status_map = {
            EventAction.START: "START",
            EventAction.COMPLETE: "END",
            EventAction.ERROR: "FAIL",
            EventAction.WARNING: "OK",
            EventAction.TICK: "OK",
            EventAction.HEARTBEAT: "OK",
        }
        status = status_map.get(action, "OK")

        # Build counts if provided
        counts = kwargs.get("counts") or {
            "docs": int(kwargs.get("docs", 0) or 0),
            "chunks": int(kwargs.get("chunks", 0) or 0),
            "tokens": int(kwargs.get("tokens", 0) or 0),
        }

        # Operation name: prefer explicit op, else derive from component/action
        op = kwargs.get("op") or f"{self.component}.{action.value}"

        canonical_event = {
            "ts": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": str(level).split(".")[-1].upper(),
            "stage": self.phase,
            "rid": self.run_id,
            "op": op,
            "status": status,
            "duration_ms": duration_ms,
            "counts": counts,
            "doc_id": kwargs.get("doc_id"),
            "chunk_id": kwargs.get("chunk_id"),
            "provider": kwargs.get("provider"),
            "model": kwargs.get("model"),
            "dimension": kwargs.get("dimension")
            or kwargs.get("embedding_dims"),
            "reason": kwargs.get("reason"),
        }

        try:
            self._file.write(
                json.dumps(
                    {k: v for k, v in canonical_event.items() if v is not None}
                )
                + "\n"
            )
            self._file.flush()
        except Exception:
            pass  # Silently fail to avoid breaking the main process

    # Phase-specific events
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

    def embed_tick(self, processed: int, **kwargs):
        """Emit embed.tick event."""
        self._emit(EventAction.TICK, counts={"chunks": processed}, **kwargs)

    def embed_complete(self, total_embedded: int, duration_ms: int, **kwargs):
        """Emit embed.complete event."""
        self._emit(
            EventAction.COMPLETE,
            duration_ms=duration_ms,
            counts={"chunks": total_embedded},
            **kwargs,
        )

    def warning(self, message: str, **kwargs):
        """Emit warning event."""
        self._emit(
            EventAction.WARNING,
            level=EventLevel.WARNING,
            reason=message,
            **kwargs,
        )

    def error(self, message: str, error_type: Optional[str] = None, **kwargs):
        """Emit error event."""
        self._emit(
            EventAction.ERROR,
            level=EventLevel.ERROR,
            reason=message,
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
            counts={"chunks": processed},
            **kwargs,
        )


# Free function expected by chunk engine and other legacy call sites
def emit_event(event_type: str, **kwargs) -> None:
    """Emit a standardized event line using a global context."""
    try:
        ctx = EventEmitter._global_context
        run_id = ctx.get("run_id") or kwargs.get("run_id") or "unknown"
        stage = (
            (event_type.split(".")[0] if "." in event_type else None)
            or ctx.get("stage")
            or "runner"
        )
        op = event_type.split(".")[1] if "." in event_type else event_type

        # Map level/status heuristically from kwargs
        level = kwargs.get("level", "INFO").upper()
        status = kwargs.get("status")
        if not status:
            if any(k in op for k in ["error", "fail"]):
                status = "FAIL"
                level = "ERROR"
            elif any(k in op for k in ["start", "begin"]):
                status = "START"
            elif any(k in op for k in ["complete", "done", "end"]):
                status = "END"
            else:
                status = "OK"

        # Build counts
        counts = kwargs.get("counts") or {
            "docs": int(kwargs.get("docs", 0) or 0),
            "chunks": int(kwargs.get("chunks", 0) or 0),
            "tokens": int(kwargs.get("tokens", 0) or 0),
        }

        event = {
            "ts": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": level,
            "stage": stage,
            "rid": run_id,
            "op": op,
            "status": status,
            "duration_ms": kwargs.get("duration_ms"),
            "counts": counts,
            "doc_id": kwargs.get("doc_id"),
            "chunk_id": kwargs.get("chunk_id"),
            "provider": kwargs.get("provider"),
            "model": kwargs.get("model"),
            "dimension": kwargs.get("dimension")
            or kwargs.get("embedding_dims"),
            "reason": kwargs.get("reason"),
        }

        # Write to primary stream path
        log_dir = Path("var/logs") / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        events_path = log_dir / "events.ndjson"
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps({k: v for k, v in event.items() if v is not None})
                + "\n"
            )
    except Exception:
        # Never break main flow on observability errors
        pass
