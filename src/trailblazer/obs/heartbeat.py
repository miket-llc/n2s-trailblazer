"""Heartbeat manager for ETA calculation and worker tracking."""

import json
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Any
from collections import deque


class EMACalculator:
    """Exponential Moving Average calculator for rate smoothing."""

    def __init__(self, alpha: float = 0.25):
        self.alpha = alpha
        self.value = 0.0
        self.initialized = False

    def update(self, new_value: float) -> float:
        """Update EMA with new value."""
        if not self.initialized:
            self.value = new_value
            self.initialized = True
        else:
            self.value = self.alpha * new_value + (1 - self.alpha) * self.value
        return self.value


class HeartbeatManager:
    """Manages heartbeats, ETA calculation, and worker tracking."""

    def __init__(
        self, run_id: str, phase: str, heartbeat_interval: float = 30.0
    ):
        self.run_id = run_id
        self.phase = phase
        self.heartbeat_interval = heartbeat_interval

        self.start_time = time.time()
        self.last_heartbeat = 0.0

        # Metrics tracking
        self.processed = 0
        self.total_planned = 0
        self.inserted = 0
        self.reembedded = 0
        self.skipped = 0
        self.errors = 0
        self.retries = 0
        self.backoff_429s = 0
        self.active_workers = 1

        # Rate calculation
        self.ema_1m = EMACalculator(alpha=0.1)  # 1-minute EMA
        self.ema_5m = EMACalculator(alpha=0.02)  # 5-minute EMA
        self.rate_history: deque[float] = deque(
            maxlen=60
        )  # Last 60 data points

        # Worker tracking
        self.worker_rates: Dict[str, float] = {}

        # Directories
        self.status_dir = Path("var/status")
        self.status_dir.mkdir(parents=True, exist_ok=True)

        # Status file
        self.status_file = self.status_dir / f"{run_id}.json"

        # Symlink to latest
        latest_link = self.status_dir / "latest.json"
        if latest_link.is_symlink():
            latest_link.unlink()
        try:
            latest_link.symlink_to(self.status_file.name)
        except (OSError, FileExistsError):
            pass

        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start heartbeat thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._thread.start()

    def stop(self):
        """Stop heartbeat thread."""
        self._stop_flag.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def update_metrics(
        self,
        processed: Optional[int] = None,
        inserted: Optional[int] = None,
        reembedded: Optional[int] = None,
        skipped: Optional[int] = None,
        errors: Optional[int] = None,
        retries: Optional[int] = None,
        backoff_429s: Optional[int] = None,
        active_workers: Optional[int] = None,
        total_planned: Optional[int] = None,
    ):
        """Update metrics counters."""
        if processed is not None:
            self.processed = processed
        if inserted is not None:
            self.inserted = inserted
        if reembedded is not None:
            self.reembedded = reembedded
        if skipped is not None:
            self.skipped = skipped
        if errors is not None:
            self.errors = errors
        if retries is not None:
            self.retries = retries
        if backoff_429s is not None:
            self.backoff_429s = backoff_429s
        if active_workers is not None:
            self.active_workers = active_workers
        if total_planned is not None:
            self.total_planned = total_planned

    def calculate_eta(self) -> Optional[str]:
        """Calculate ETA based on current rate and remaining items."""
        if self.total_planned <= 0 or self.processed <= 0:
            return None

        remaining = max(0, self.total_planned - self.processed)
        if remaining == 0:
            return "00:00:00"

        # Use 1-minute EMA rate if available
        rate = self.ema_1m.value if self.ema_1m.initialized else 0.0

        # Account for multiple workers
        effective_rate = rate * self.active_workers if rate > 0 else 0.0

        if effective_rate <= 0:
            return None

        eta_seconds = remaining / effective_rate
        eta_timedelta = timedelta(seconds=int(eta_seconds))

        # Format as ISO 8601 duration or simple time
        total_seconds = int(eta_timedelta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _calculate_current_rate(self) -> float:
        """Calculate current processing rate (items per second)."""
        current_time = time.time()
        elapsed = current_time - self.start_time

        if elapsed <= 0:
            return 0.0

        return self.processed / elapsed

    def _heartbeat_loop(self):
        """Main heartbeat loop running in thread."""
        while not self._stop_flag.wait(self.heartbeat_interval):
            self._emit_heartbeat()

    def _emit_heartbeat(self):
        """Emit heartbeat event and update status file."""
        current_time = time.time()

        # Calculate current rate
        current_rate = self._calculate_current_rate()

        # Update EMAs
        self.ema_1m.update(current_rate)
        self.ema_5m.update(current_rate)

        # Add to rate history
        self.rate_history.append(current_rate)

        # Calculate ETA
        eta = self.calculate_eta()
        eta_iso8601 = None
        if eta:
            # Convert to ISO8601 duration format
            now = datetime.now(timezone.utc)
            eta_datetime = now + timedelta(
                seconds=sum(
                    int(x) * 60**i
                    for i, x in enumerate(reversed(eta.split(":")))
                )
            )
            eta_iso8601 = eta_datetime.isoformat().replace("+00:00", "Z")

        # Create status snapshot
        status = {
            "run_id": self.run_id,
            "phase": self.phase,
            "timestamp": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "elapsed_seconds": int(current_time - self.start_time),
            "processed": self.processed,
            "inserted": self.inserted,
            "reembedded": self.reembedded,
            "skipped": self.skipped,
            "errors": self.errors,
            "retries": self.retries,
            "backoff_429s": self.backoff_429s,
            "active_workers": self.active_workers,
            "remaining": max(0, self.total_planned - self.processed)
            if self.total_planned > 0
            else None,
            "rate_current": round(current_rate, 2),
            "rate_ema_1m": round(self.ema_1m.value, 2),
            "rate_ema_5m": round(self.ema_5m.value, 2),
            "eta_human": eta,
            "eta_iso8601": eta_iso8601,
            "total_planned": self.total_planned
            if self.total_planned > 0
            else None,
        }

        # Write status file atomically
        try:
            temp_file = self.status_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.status_file)
        except Exception:
            pass  # Silently fail to avoid breaking main process

        self.last_heartbeat = current_time

    def force_heartbeat(self):
        """Force immediate heartbeat emission."""
        self._emit_heartbeat()

    def final_summary(self) -> Dict[str, Any]:
        """Generate final summary for banner display."""
        elapsed = time.time() - self.start_time
        avg_rate = self.processed / elapsed if elapsed > 0 else 0.0

        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "total_processed": self.processed,
            "total_inserted": self.inserted,
            "total_reembedded": self.reembedded,
            "total_skipped": self.skipped,
            "total_errors": self.errors,
            "total_retries": self.retries,
            "total_backoff_429s": self.backoff_429s,
            "elapsed_seconds": int(elapsed),
            "average_rate": round(avg_rate, 2),
            "final_worker_count": self.active_workers,
        }
