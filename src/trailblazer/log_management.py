"""Log management utilities for rotation, compression, retention, and maintenance."""

import gzip
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, TypedDict

from .core.config import SETTINGS


class RunInfo(TypedDict):
    run_id: str
    size_bytes: int
    segments: int
    compressed_segments: int
    last_modified: Optional[str]
    has_stderr: bool
    status: str


class LogManager:
    """Manages log rotation, compression, retention, and maintenance."""

    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = Path(log_dir) if log_dir else Path("var/logs")
        self.status_dir = Path("var/status")

    def get_run_directories(self) -> List[Path]:
        """Get all run directories in the log directory."""
        if not self.log_dir.exists():
            return []

        return [
            d
            for d in self.log_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]

    def get_log_segments(self, run_dir: Path) -> List[Path]:
        """Get all log segments for a run (events.ndjson, events.ndjson.1, etc.)."""
        segments = []

        # Main events.ndjson
        events_path = run_dir / "events.ndjson"
        if events_path.exists():
            segments.append(events_path)

        # Rotated segments
        i = 1
        while True:
            segment_path = run_dir / f"events.ndjson.{i}"
            if segment_path.exists():
                segments.append(segment_path)
                i += 1
            else:
                break

        return segments

    def compress_old_segments(self, dry_run: bool = True) -> Dict[str, Any]:
        """Compress segments older than LOGS_COMPRESS_AFTER_DAYS."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(
            days=SETTINGS.LOGS_COMPRESS_AFTER_DAYS
        )
        compressed = []
        errors = []

        for run_dir in self.get_run_directories():
            segments = self.get_log_segments(run_dir)

            for segment in segments:
                if segment.name.endswith(".gz"):
                    continue  # Already compressed

                try:
                    mtime = datetime.fromtimestamp(
                        segment.stat().st_mtime, tz=timezone.utc
                    )
                    if mtime < cutoff_time:
                        compressed_path = segment.with_suffix(
                            segment.suffix + ".gz"
                        )

                        if not dry_run:
                            # Compress the file
                            with open(segment, "rb") as f_in:
                                with gzip.open(compressed_path, "wb") as f_out:
                                    shutil.copyfileobj(f_in, f_out)

                            # Remove original
                            segment.unlink()

                        compressed.append(str(segment))

                except Exception as e:
                    errors.append(f"{segment}: {e}")

        return {"compressed": compressed, "errors": errors, "dry_run": dry_run}

    def prune_old_logs(self, dry_run: bool = True) -> Dict[str, Any]:
        """Delete logs older than LOGS_RETENTION_DAYS."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(
            days=SETTINGS.LOGS_RETENTION_DAYS
        )
        deleted_runs = []
        deleted_files = []
        errors = []

        for run_dir in self.get_run_directories():
            try:
                # Check if this is an active run (has recent activity)
                if self._is_active_run(run_dir):
                    continue

                # Check if run directory is old enough
                dir_mtime = datetime.fromtimestamp(
                    run_dir.stat().st_mtime, tz=timezone.utc
                )
                if dir_mtime < cutoff_time:
                    if not dry_run:
                        # Delete the entire run directory
                        shutil.rmtree(run_dir)

                        # Also clean up run-specific symlink
                        run_symlink = self.log_dir / f"{run_dir.name}.ndjson"
                        if run_symlink.exists() or run_symlink.is_symlink():
                            run_symlink.unlink()

                    deleted_runs.append(run_dir.name)
                    deleted_files.extend(
                        [str(f) for f in run_dir.rglob("*") if f.is_file()]
                    )

            except Exception as e:
                errors.append(f"{run_dir}: {e}")

        return {
            "deleted_runs": deleted_runs,
            "deleted_files": deleted_files,
            "errors": errors,
            "dry_run": dry_run,
        }

    def _is_active_run(self, run_dir: Path) -> bool:
        """Check if a run is currently active (has recent heartbeat)."""
        try:
            status_file = self.status_dir / f"{run_dir.name}.json"
            if not status_file.exists():
                return False

            with open(status_file) as f:
                status = json.load(f)

            # Consider active if last heartbeat was within 1 hour
            last_heartbeat_str = status.get("last_heartbeat")
            if last_heartbeat_str:
                last_heartbeat = datetime.fromisoformat(
                    last_heartbeat_str.replace("Z", "+00:00")
                )
                age = datetime.now(timezone.utc) - last_heartbeat
                return age < timedelta(hours=1)

            return False

        except Exception:
            return False  # Assume inactive if we can't determine

    def doctor_logs(self) -> Dict[str, Any]:
        """Validate log structure and fix symlinks."""
        issues = []
        fixed = []

        # Check main log directory exists
        if not self.log_dir.exists():
            issues.append(f"Log directory {self.log_dir} does not exist")
            self.log_dir.mkdir(parents=True, exist_ok=True)
            fixed.append(f"Created log directory {self.log_dir}")

        # Check status directory exists
        if not self.status_dir.exists():
            issues.append(f"Status directory {self.status_dir} does not exist")
            self.status_dir.mkdir(parents=True, exist_ok=True)
            fixed.append(f"Created status directory {self.status_dir}")

        # Validate run directories and fix symlinks
        for run_dir in self.get_run_directories():
            # Check events.ndjson exists
            events_path = run_dir / "events.ndjson"
            if not events_path.exists():
                issues.append(f"{run_dir.name}: missing events.ndjson")
                events_path.touch()
                fixed.append(f"{run_dir.name}: created events.ndjson")

            # Check stderr.log exists
            stderr_path = run_dir / "stderr.log"
            if not stderr_path.exists():
                issues.append(f"{run_dir.name}: missing stderr.log")
                stderr_path.touch()
                fixed.append(f"{run_dir.name}: created stderr.log")

            # Fix run-specific symlink
            run_symlink = self.log_dir / f"{run_dir.name}.ndjson"
            expected_target = f"{run_dir.name}/events.ndjson"

            if not run_symlink.exists() or (
                run_symlink.is_symlink()
                and str(run_symlink.readlink()) != expected_target
            ):
                if run_symlink.exists():
                    run_symlink.unlink()
                try:
                    run_symlink.symlink_to(expected_target)
                    fixed.append(f"Fixed symlink {run_symlink.name}")
                except OSError as e:
                    issues.append(
                        f"Could not create symlink {run_symlink.name}: {e}"
                    )

        # Fix latest symlinks
        latest_targets = [
            ("latest.ndjson", "events.ndjson"),
            ("latest.stderr.log", "stderr.log"),
        ]

        # Find most recent run for latest symlinks
        run_dirs = self.get_run_directories()
        if run_dirs:
            latest_run = max(run_dirs, key=lambda d: d.stat().st_mtime)

            for link_name, target_file in latest_targets:
                link_path = self.log_dir / link_name
                expected_target = f"{latest_run.name}/{target_file}"

                if not link_path.exists() or (
                    link_path.is_symlink()
                    and str(link_path.readlink()) != expected_target
                ):
                    if link_path.exists():
                        link_path.unlink()
                    try:
                        link_path.symlink_to(expected_target)
                        fixed.append(f"Fixed latest symlink {link_name}")
                    except OSError as e:
                        issues.append(
                            f"Could not create latest symlink {link_name}: {e}"
                        )

        return {
            "issues": issues,
            "fixed": fixed,
            "health": "healthy" if not issues else "issues_found",
        }

    def get_index_summary(self) -> Dict[str, Any]:
        """Get summary of all log runs with sizes and timestamps."""
        runs: List[RunInfo] = []
        total_size = 0

        for run_dir in self.get_run_directories():
            run_info: RunInfo = {
                "run_id": run_dir.name,
                "size_bytes": 0,
                "segments": 0,
                "compressed_segments": 0,
                "last_modified": None,
                "has_stderr": False,
                "status": "unknown",
            }

            # Check stderr.log
            stderr_path = run_dir / "stderr.log"
            if stderr_path.exists():
                run_info["has_stderr"] = True

            # Sum up all segments
            segments = self.get_log_segments(run_dir)
            last_modified_dt: Optional[datetime] = None

            for segment in segments:
                if segment.exists():
                    size = segment.stat().st_size
                    run_info["size_bytes"] += size  # type: ignore[operator]
                    total_size += size

                    if segment.name.endswith(".gz"):
                        run_info["compressed_segments"] += 1  # type: ignore[operator]
                    else:
                        run_info["segments"] += 1  # type: ignore[operator]

                    # Track most recent modification
                    mtime = datetime.fromtimestamp(
                        segment.stat().st_mtime, tz=timezone.utc
                    )
                    if not last_modified_dt or mtime > last_modified_dt:
                        last_modified_dt = mtime
                        run_info["last_modified"] = mtime.isoformat()

            # Check if active
            if self._is_active_run(run_dir):
                run_info["status"] = "active"
            else:
                run_info["status"] = "inactive"

            runs.append(run_info)

        # Sort by last modified (most recent first)
        runs.sort(key=lambda r: str(r["last_modified"] or ""), reverse=True)

        return {
            "total_runs": len(runs),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "runs": runs,
        }
