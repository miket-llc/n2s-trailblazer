"""Status tracking and banner management."""

import sys
import time
from datetime import datetime, timezone
from typing import Optional, TextIO, Dict, Any
from rich.console import Console
from rich.panel import Panel
from rich.text import Text


class StatusTracker:
    """Tracks status and prints banners for observability."""

    def __init__(
        self,
        run_id: str,
        phase: str,
        component: str,
        no_color: bool = False,
        file: Optional[TextIO] = None,
    ):
        self.run_id = run_id
        self.phase = phase
        self.component = component
        self.start_time = time.time()

        # Rich console for pretty output (stderr only)
        self.console = Console(
            file=file or sys.stderr,
            color_system=None if no_color else "auto",
            force_terminal=not no_color,
        )

    def start_banner(self, title: Optional[str] = None, **metadata):
        """Print start banner with run info."""
        title = title or f"{self.phase.title()} Starting"

        # Create banner content
        content = Text()
        content.append(f"🚀 {title}\n", style="bold cyan")
        content.append(f"Run ID: {self.run_id}\n", style="white")
        content.append(f"Phase: {self.phase}\n", style="yellow")
        content.append(f"Component: {self.component}\n", style="green")
        content.append(
            f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n",
            style="dim",
        )

        # Add metadata
        if metadata:
            content.append("\nConfiguration:\n", style="bold white")
            for key, value in metadata.items():
                content.append(f"  {key}: {value}\n", style="dim")

        panel = Panel(
            content,
            title=f"[bold cyan]Trailblazer {self.phase.title()}[/bold cyan]",
            border_style="cyan",
            expand=False,
        )

        self.console.print(panel)
        self.console.print()  # Add spacing

    def progress_banner(
        self,
        processed: int,
        total: Optional[int] = None,
        rate: Optional[float] = None,
        eta: Optional[str] = None,
        status_message: str = "Processing",
        **metrics,
    ):
        """Print progress banner (throttled)."""

        # Create progress text
        content = Text()
        content.append(f"📊 {status_message}\n", style="bold blue")

        # Progress numbers
        if total and total > 0:
            percentage = (processed / total) * 100
            content.append(
                f"Progress: {processed:,} / {total:,} ({percentage:.1f}%)\n",
                style="white",
            )
        else:
            content.append(f"Processed: {processed:,}\n", style="white")

        # Rate and ETA
        if rate is not None:
            content.append(f"Rate: {rate:.1f} items/sec\n", style="green")
        if eta:
            content.append(f"ETA: {eta}\n", style="yellow")

        # Additional metrics
        if metrics:
            content.append("\nMetrics:\n", style="bold white")
            for key, value in metrics.items():
                if isinstance(value, (int, float)):
                    content.append(f"  {key}: {value:,}\n", style="dim")
                else:
                    content.append(f"  {key}: {value}\n", style="dim")

        panel = Panel(
            content,
            title=f"[bold blue]{self.component} Status[/bold blue]",
            border_style="blue",
            expand=False,
        )

        self.console.print(panel)
        self.console.print()

    def warning_banner(self, message: str, **context):
        """Print warning banner."""
        content = Text()
        content.append("⚠️  Warning\n", style="bold yellow")
        content.append(f"{message}\n", style="white")

        if context:
            content.append("\nContext:\n", style="bold white")
            for key, value in context.items():
                content.append(f"  {key}: {value}\n", style="dim")

        panel = Panel(
            content,
            title="[bold yellow]Warning[/bold yellow]",
            border_style="yellow",
            expand=False,
        )

        self.console.print(panel)

    def error_banner(
        self, message: str, error_type: Optional[str] = None, **context
    ):
        """Print error banner."""
        content = Text()
        content.append("❌ Error\n", style="bold red")
        if error_type:
            content.append(f"Type: {error_type}\n", style="red")
        content.append(f"{message}\n", style="white")

        if context:
            content.append("\nContext:\n", style="bold white")
            for key, value in context.items():
                content.append(f"  {key}: {value}\n", style="dim")

        panel = Panel(
            content,
            title="[bold red]Error[/bold red]",
            border_style="red",
            expand=False,
        )

        self.console.print(panel)

    def completion_banner(self, summary: Dict[str, Any]):
        """Print completion banner with final summary."""
        elapsed = time.time() - self.start_time

        content = Text()
        content.append("✅ Completed Successfully\n", style="bold green")
        content.append(f"Run ID: {self.run_id}\n", style="white")
        content.append(f"Total time: {elapsed:.1f} seconds\n", style="cyan")

        # Summary metrics
        if summary:
            content.append("\nSummary:\n", style="bold white")
            for key, value in summary.items():
                if key.startswith("total_") or key in [
                    "processed",
                    "inserted",
                    "errors",
                ]:
                    content.append(
                        f"  {key.replace('_', ' ').title()}: {value:,}\n",
                        style="white",
                    )
                elif isinstance(value, (int, float)):
                    content.append(
                        f"  {key.replace('_', ' ').title()}: {value}\n",
                        style="dim",
                    )
                else:
                    content.append(
                        f"  {key.replace('_', ' ').title()}: {value}\n",
                        style="dim",
                    )

        panel = Panel(
            content,
            title=f"[bold green]{self.phase.title()} Complete[/bold green]",
            border_style="green",
            expand=False,
        )

        self.console.print(panel)

        # Final one-line summary
        if summary.get("total_processed"):
            rate = summary.get("average_rate", 0)
            self.console.print(
                f"📋 Final: Run {self.run_id} | {summary['total_processed']:,} items | "
                f"{elapsed:.1f}s | {rate:.1f} items/sec",
                style="bold white",
            )

    def simple_line(self, message: str, style: str = "white"):
        """Print simple status line."""
        self.console.print(message, style=style)
