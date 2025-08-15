"""Monitor CLI for live visibility of running processes."""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout


class TrailblazerMonitor:
    """Live monitor for Trailblazer processes with TUI and JSON modes."""

    def __init__(
        self,
        run_id: Optional[str] = None,
        json_mode: bool = False,
        refresh_interval: float = 2.0,
    ):
        self.run_id = run_id or self._get_latest_run_id()
        self.json_mode = json_mode
        self.refresh_interval = refresh_interval

        self.console = Console() if not json_mode else None
        self.status_file = (
            Path(f"var/status/{self.run_id}.json") if self.run_id else None
        )
        self.log_file = (
            Path(f"var/logs/{self.run_id}.ndjson") if self.run_id else None
        )

        # Tracking data
        self.last_events: List[Dict[str, Any]] = []
        self.error_history: List[Dict[str, Any]] = []
        self.rate_history: List[float] = []

    def _get_latest_run_id(self) -> Optional[str]:
        """Get the latest run ID from symlink."""
        latest_status = Path("var/status/latest.json")
        if latest_status.exists() and latest_status.is_symlink():
            target = latest_status.readlink()
            return target.stem
        return None

    def _read_status(self) -> Optional[Dict[str, Any]]:
        """Read current status from status file."""
        if not self.status_file or not self.status_file.exists():
            return None

        try:
            with open(self.status_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _read_recent_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Read recent events from log file."""
        if not self.log_file or not self.log_file.exists():
            return []

        events = []
        try:
            with open(self.log_file, "r") as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        events.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue
        except IOError:
            pass

        return events

    def _create_status_panel(self, status: Dict[str, Any]) -> Panel:
        """Create status panel for TUI."""
        content = Text()

        # Header
        content.append(
            f"🎯 {status.get('phase', 'unknown').title()} Monitor\n",
            style="bold cyan",
        )
        content.append(
            f"Run ID: {status.get('run_id', 'unknown')}\n", style="white"
        )
        content.append(
            f"Updated: {status.get('timestamp', 'unknown')[:19]}\n",
            style="dim",
        )
        content.append(
            f"Elapsed: {status.get('elapsed_seconds', 0):,}s\n", style="yellow"
        )

        # Progress
        processed = status.get("processed", 0)
        total = status.get("total_planned")
        if total and total > 0:
            percentage = (processed / total) * 100
            content.append(
                f"Progress: {processed:,} / {total:,} ({percentage:.1f}%)\n",
                style="green",
            )
        else:
            content.append(f"Processed: {processed:,}\n", style="green")

        # Rates and ETA
        rate_1m = status.get("rate_ema_1m", 0)
        eta = status.get("eta_human", "unknown")
        content.append(f"Rate: {rate_1m:.1f} items/sec\n", style="blue")
        content.append(f"ETA: {eta}\n", style="magenta")

        # Workers
        workers = status.get("active_workers", 1)
        content.append(f"Workers: {workers}\n", style="cyan")

        return Panel(
            content, title="[bold blue]Status[/bold blue]", border_style="blue"
        )

    def _create_metrics_table(self, status: Dict[str, Any]) -> Table:
        """Create metrics table."""
        table = Table(
            title="Metrics", show_header=True, header_style="bold yellow"
        )
        table.add_column("Metric", style="white")
        table.add_column("Count", style="green", justify="right")

        metrics = [
            ("Processed", status.get("processed", 0)),
            ("Inserted", status.get("inserted", 0)),
            ("Reembedded", status.get("reembedded", 0)),
            ("Skipped", status.get("skipped", 0)),
            ("Errors", status.get("errors", 0)),
            ("Retries", status.get("retries", 0)),
            ("Rate Limit (429s)", status.get("backoff_429s", 0)),
        ]

        for metric, value in metrics:
            table.add_row(metric, f"{value:,}")

        return table

    def _create_events_panel(self, events: List[Dict[str, Any]]) -> Panel:
        """Create recent events panel."""
        content = Text()

        if not events:
            content.append("No recent events", style="dim")
        else:
            for event in events[-5:]:  # Last 5 events
                ts = event.get("ts", "")[:19].replace("T", " ")
                action = event.get("action", "unknown")
                level = event.get("level", "info")

                # Style based on level
                if level == "error":
                    style = "red"
                elif level == "warning":
                    style = "yellow"
                else:
                    style = "white"

                content.append(f"{ts} ", style="dim")
                content.append(f"{action:<12} ", style=style)

                # Add context
                if "space_key" in event:
                    content.append(
                        f"space={event['space_key']} ", style="cyan"
                    )
                if "page_id" in event:
                    content.append(
                        f"page={event['page_id'][:12]}... ", style="blue"
                    )
                if event.get("metadata", {}).get("message"):
                    content.append(
                        f"msg={event['metadata']['message'][:30]}...",
                        style="white",
                    )

                content.append("\n")

        return Panel(
            content,
            title="[bold green]Recent Events[/bold green]",
            border_style="green",
        )

    def _create_ascii_sparkline(
        self, values: List[float], width: int = 40
    ) -> str:
        """Create simple ASCII sparkline."""
        if not values or len(values) < 2:
            return "█" * width

        min_val = min(values)
        max_val = max(values)

        if max_val == min_val:
            return "█" * width

        # Normalize values to 0-7 range for block characters
        blocks = "▁▂▃▄▅▆▇█"

        sparkline = ""
        for i in range(width):
            if i < len(values):
                normalized = (values[i] - min_val) / (max_val - min_val)
                block_index = min(7, int(normalized * 7))
                sparkline += blocks[block_index]
            else:
                sparkline += " "

        return sparkline

    def display_tui(self):
        """Display TUI monitor."""
        if not self.run_id:
            self.console.print("❌ No active run found", style="red")
            return

        self.console.print(f"🎯 Monitoring run: {self.run_id}")
        self.console.print("Press Ctrl+C to stop\n")

        layout = Layout()
        layout.split_column(
            Layout(name="top", size=12),
            Layout(name="middle", size=8),
            Layout(name="bottom"),
        )
        layout["middle"].split_row(
            Layout(name="metrics"), Layout(name="trend")
        )

        try:
            with Live(layout, console=self.console, refresh_per_second=1):
                while True:
                    status = self._read_status()
                    events = self._read_recent_events()

                    if status:
                        # Update rate history for sparkline
                        current_rate = status.get("rate_ema_1m", 0)
                        self.rate_history.append(current_rate)
                        if (
                            len(self.rate_history) > 60
                        ):  # Keep last 60 data points
                            self.rate_history.pop(0)

                        # Update layout
                        layout["top"].update(self._create_status_panel(status))
                        layout["metrics"].update(
                            self._create_metrics_table(status)
                        )
                        layout["bottom"].update(
                            self._create_events_panel(events)
                        )

                        # Trend sparkline
                        sparkline = self._create_ascii_sparkline(
                            self.rate_history
                        )
                        trend_content = Text()
                        trend_content.append(
                            "Rate Trend (1m EMA)\n", style="bold white"
                        )
                        trend_content.append(f"{sparkline}\n", style="green")
                        trend_content.append(
                            f"Range: {min(self.rate_history):.1f} - {max(self.rate_history):.1f}",
                            style="dim",
                        )

                        layout["trend"].update(
                            Panel(
                                trend_content,
                                title="Trend",
                                border_style="yellow",
                            )
                        )
                    else:
                        layout["top"].update(
                            Panel("No status data available", style="red")
                        )

                    time.sleep(self.refresh_interval)

        except KeyboardInterrupt:
            self.console.print("\n👋 Monitor stopped")

    def display_json(self):
        """Display JSON summary for CI/dashboards."""
        status = self._read_status()
        events = self._read_recent_events(5)

        if not status:
            summary = {
                "error": "No status data available",
                "run_id": self.run_id,
            }
        else:
            summary = {
                "run_id": status.get("run_id"),
                "phase": status.get("phase"),
                "timestamp": status.get("timestamp"),
                "status": "running"
                if status.get("remaining", 0) > 0
                else "completed",
                "progress": {
                    "processed": status.get("processed", 0),
                    "total_planned": status.get("total_planned"),
                    "remaining": status.get("remaining", 0),
                    "percentage": round(
                        (
                            status.get("processed", 0)
                            / status.get("total_planned", 1)
                        )
                        * 100,
                        1,
                    )
                    if status.get("total_planned")
                    else None,
                },
                "performance": {
                    "rate_current": status.get("rate_current", 0),
                    "rate_ema_1m": status.get("rate_ema_1m", 0),
                    "rate_ema_5m": status.get("rate_ema_5m", 0),
                    "eta_human": status.get("eta_human"),
                    "eta_iso8601": status.get("eta_iso8601"),
                    "active_workers": status.get("active_workers", 1),
                },
                "metrics": {
                    "inserted": status.get("inserted", 0),
                    "reembedded": status.get("reembedded", 0),
                    "skipped": status.get("skipped", 0),
                    "errors": status.get("errors", 0),
                    "retries": status.get("retries", 0),
                    "backoff_429s": status.get("backoff_429s", 0),
                },
                "recent_events": [
                    {
                        "timestamp": event.get("ts"),
                        "action": event.get("action"),
                        "level": event.get("level"),
                        "component": event.get("component"),
                    }
                    for event in events
                ],
            }

        print(json.dumps(summary, indent=2))

    def run(self):
        """Run the monitor in appropriate mode."""
        if self.json_mode:
            self.display_json()
        else:
            self.display_tui()
