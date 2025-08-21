"""Progress rendering for TTY and CLI output separation with Rich observability."""

import os
import sys
import time
from datetime import datetime
from typing import Any, TextIO

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table


def is_tty() -> bool:
    """Check if stdout is a TTY (interactive terminal)."""
    return sys.stdout.isatty()


def is_ci() -> bool:
    """Check if running in CI environment."""
    ci_vars = ["CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "JENKINS_URL"]
    return any(os.environ.get(var) for var in ci_vars)


def should_use_pretty() -> bool:
    """Determine if pretty output should be used based on TTY and CI detection."""
    return is_tty() and not is_ci()


class ProgressRenderer:
    """Enhanced progress renderer with Rich observability features."""

    def __init__(
        self,
        enabled: bool | None = None,
        quiet_pretty: bool = False,
        file: TextIO | None = None,
        no_color: bool = False,
    ):
        """
        Initialize progress renderer.

        Args:
            enabled: Whether to show progress. Auto-detected if None.
            quiet_pretty: Suppress banners but keep progress bars.
            file: Output file, defaults to stderr.
            no_color: Disable color output for Rich console.
        """
        self.enabled = enabled if enabled is not None else should_use_pretty()
        self.quiet_pretty = quiet_pretty
        self.file = file or sys.stderr
        self.no_color = no_color

        # Rich console for enhanced output
        self.console = Console(
            file=self.file,
            color_system=None if no_color else "auto",
            force_terminal=self.enabled,
        )

        # Progress tracking
        self.start_time: float | None = None
        self.last_heartbeat: float = 0
        self.last_update: float = 0
        self.page_count = 0
        self.attachment_count = 0
        self.space_count = 0
        self.current_space: str | None = None
        self.spaces_completed = 0
        self.error_count = 0
        self.retry_count = 0
        self.last_api_status: str | None = None

        # Rich progress bars
        self.overall_progress: Progress | None = None
        self.space_progress: Progress | None = None
        self.overall_task = None
        self.space_task = None

        # Live display
        self.live_display: Live | None = None

        # Heartbeat interval (30 seconds)
        self.heartbeat_interval = 30.0

    def start_banner(
        self,
        run_id: str,
        spaces: int,
        since_mode: str = "none",
        max_pages: int | None = None,
        estimated_pages: int | None = None,
    ):
        """Print enhanced start banner with Rich formatting."""
        if not self.enabled or self.quiet_pretty:
            return

        self.start_time = time.time()
        self.space_count = spaces
        self.last_heartbeat = self.start_time

        # Create Rich banner
        banner_content = [
            f"[bold blue]🚀 Starting ingest run:[/bold blue] [cyan]{run_id}[/cyan]",
            f"[bold]Spaces targeted:[/bold] {spaces}",
            f"[bold]Mode:[/bold] {since_mode}",
        ]

        if max_pages:
            banner_content.append(f"[bold]Max pages:[/bold] {max_pages}")
        if estimated_pages:
            banner_content.append(f"[bold]Estimated pages:[/bold] ~{estimated_pages}")

        banner_content.append(f"[bold]Started:[/bold] {datetime.now().strftime('%H:%M:%S')}")

        panel = Panel(
            "\n".join(banner_content),
            title="[bold green]Ingest Configuration[/bold green]",
            border_style="blue",
        )

        self.console.print(panel)
        self.console.print()

        # Initialize Rich progress bars for multi-space ingests
        if spaces > 1:
            self._setup_progress_bars()

    def _setup_progress_bars(self):
        """Setup Rich progress bars for overall and per-space tracking."""
        if not self.enabled:
            return

        self.overall_progress = Progress(
            TextColumn("[bold blue]Overall Progress"),
            BarColumn(bar_width=40),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "•",
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
        )

        self.space_progress = Progress(
            TextColumn("[bold green]Current Space"),
            BarColumn(bar_width=30),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "•",
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        )

    def resumability_evidence(
        self,
        since: str | None = None,
        spaces: int = 0,
        pages_known: int = 0,
        estimated_to_fetch: int = 0,
        skipped_unchanged: int = 0,
    ):
        """Display resumability evidence with delta mode details."""
        if not self.enabled:
            return

        since_display = since or "none"
        evidence_lines = [
            f"[bold]Resuming Confluence since:[/bold] [yellow]{since_display}[/yellow]",
            f"[bold]Spaces:[/bold] {spaces}",
            f"[bold]Pages known:[/bold] {pages_known}",
            f"[bold]Estimated to fetch:[/bold] ≈{estimated_to_fetch}",
        ]

        if skipped_unchanged > 0:
            evidence_lines.append(f"[dim]Skipped unchanged:[/dim] {skipped_unchanged}")

        panel = Panel(
            "\n".join(evidence_lines),
            title="[bold yellow]📊 Resumability Evidence[/bold yellow]",
            border_style="yellow",
        )

        self.console.print(panel)

    def heartbeat(
        self,
        phase: str,
        processed: int,
        rate: float,
        elapsed: float,
        eta: float | None = None,
        last_api_status: str | None = None,
        retries: int = 0,
    ):
        """Display heartbeat line every 30 seconds."""
        current_time = time.time()
        if current_time - self.last_heartbeat < self.heartbeat_interval:
            return

        if not self.enabled:
            return

        self.last_heartbeat = current_time
        self.last_api_status = last_api_status
        self.retry_count = retries

        eta_str = f", ETA: {eta:.0f}s" if eta else ""
        api_str = f", API: {last_api_status}" if last_api_status else ""
        retry_str = f", retries: {retries}" if retries > 0 else ""

        heartbeat_text = (
            f"💓 [bold]{phase}[/bold] | "
            f"processed: [green]{processed}[/green] | "
            f"rate: [cyan]{rate:.1f}/s[/cyan] | "
            f"elapsed: [yellow]{elapsed:.0f}s[/yellow]"
            f"{eta_str}{api_str}{retry_str}"
        )

        self.console.print(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] {heartbeat_text}")

    def attachment_verification_error(self, page_id: str, expected: int, actual: int):
        """Display attachment count mismatch error."""
        if not self.enabled:
            return

        self.error_count += 1
        error_text = (
            f"[bold red]❌ Attachment mismatch[/bold red] | "
            f"page: [yellow]{page_id}[/yellow] | "
            f"expected: [green]{expected}[/green] | "
            f"actual: [red]{actual}[/red]"
        )
        self.console.print(error_text)

    def finish_banner(
        self,
        run_id: str,
        space_stats: dict[str, dict[str, Any]],
        elapsed: float,
    ):
        """Print enhanced finish banner with Rich formatting."""
        if not self.enabled or self.quiet_pretty:
            return

        total_pages = sum(stats.get("pages", 0) for stats in space_stats.values())
        total_attachments = sum(stats.get("attachments", 0) for stats in space_stats.values())
        total_empty = sum(stats.get("empty_bodies", 0) for stats in space_stats.values())

        # Calculate rate
        rate = total_pages / elapsed if elapsed > 0 else 0

        # Summary content
        summary_lines = [
            f"[bold green]✅ Completed ingest run:[/bold green] [cyan]{run_id}[/cyan]",
            f"[bold]Elapsed:[/bold] {elapsed:.1f}s",
            f"[bold]Total:[/bold] [green]{total_pages}[/green] pages, [blue]{total_attachments}[/blue] attachments",
            f"[bold]Rate:[/bold] [cyan]{rate:.1f}[/cyan] pages/s",
        ]

        if total_empty > 0:
            summary_lines.append(f"[bold yellow]Empty bodies:[/bold yellow] {total_empty}")

        if self.error_count > 0:
            summary_lines.append(f"[bold red]Errors:[/bold red] {self.error_count}")

        if self.retry_count > 0:
            summary_lines.append(f"[bold orange]Retries:[/bold orange] {self.retry_count}")

        panel = Panel(
            "\n".join(summary_lines),
            title="[bold green]🎉 Ingest Complete[/bold green]",
            border_style="green",
        )

        self.console.print()
        self.console.print(panel)

        # Per-space breakdown table if multiple spaces
        if len(space_stats) > 1:
            table = Table(
                title="Per-Space Breakdown",
                show_header=True,
                header_style="bold blue",
            )
            table.add_column("Space", style="cyan", width=12)
            table.add_column("Pages", justify="right", style="green")
            table.add_column("Attachments", justify="right", style="blue")
            table.add_column("Empty", justify="right", style="yellow")
            table.add_column("Avg Chars", justify="right", style="magenta")

            for space_key, stats in sorted(space_stats.items()):
                pages = stats.get("pages", 0)
                attachments = stats.get("attachments", 0)
                empty = stats.get("empty_bodies", 0)
                avg_chars = stats.get("avg_chars", 0)

                table.add_row(
                    space_key,
                    str(pages),
                    str(attachments),
                    str(empty),
                    f"{avg_chars:.0f}" if avg_chars > 0 else "0",
                )

            self.console.print(table)

    def spaces_table(self, spaces: list[dict[str, Any]]):
        """Print Rich table of spaces being ingested."""
        if not self.enabled or self.quiet_pretty or not spaces:
            return

        table = Table(
            title="📋 Spaces to Ingest",
            show_header=True,
            header_style="bold blue",
        )
        table.add_column("ID", style="dim", width=12)
        table.add_column("Key", style="cyan", width=10)
        table.add_column("Name", style="white", min_width=20)
        table.add_column("Type", style="yellow", width=8)

        for space in spaces:
            space_id = str(space.get("id", ""))
            space_key = space.get("key", "")
            space_name = space.get("name", "")
            space_type = space.get("type", "")

            table.add_row(space_id, space_key, space_name, space_type)

        self.console.print(table)
        self.console.print()

    def progress_update(
        self,
        space_key: str,
        page_id: str,
        title: str,
        attachments: int,
        updated_at: str | None = None,
        throttle_every: int = 1,
        _content_bytes: int | None = None,
    ):
        """Show enhanced progress update for a page with Rich formatting."""
        if not self.enabled:
            return

        self.page_count += 1
        self.attachment_count += attachments
        self.current_space = space_key

        # Throttle updates
        if self.page_count % throttle_every != 0:
            return

        current_time = time.time()

        # Rate calculation
        if self.start_time:
            elapsed = current_time - self.start_time
            rate = self.page_count / elapsed if elapsed > 0 else 0
        else:
            rate = 0

        # Truncate long titles and IDs for display
        title_display = title[:40] + "..." if len(title) > 43 else title
        page_id_display = page_id[:12] + "..." if len(page_id) > 15 else page_id
        updated_display = updated_at[:19] if updated_at else "unknown"

        # Create progress line with Rich formatting
        progress_text = (
            f"[cyan]{space_key}[/cyan] | "
            f"[dim]p=[/dim][yellow]{page_id_display}[/yellow] | "
            f'[white]"{title_display}"[/white] | '
            f"[blue]att={attachments}[/blue] | "
            f"[dim]{updated_display}[/dim] "
            f"[green]({rate:.1f}/s)[/green]"
        )

        self.console.print(progress_text)
        self.last_update = current_time

        # Show heartbeat periodically
        if self.start_time:
            elapsed = current_time - self.start_time
            self.heartbeat(
                phase="ingesting",
                processed=self.page_count,
                rate=rate,
                elapsed=elapsed,
                last_api_status="200 OK",  # TODO: get actual API status
            )

    def resume_indicator(self, last_page: str, timestamp: str):
        """Show enhanced resume indicator with Rich formatting."""
        if not self.enabled:
            return

        resume_text = (
            f"[bold yellow]↪️  Resuming[/bold yellow] from page "
            f"[cyan]{last_page}[/cyan] ([dim]last update: {timestamp}[/dim])"
        )
        self.console.print(resume_text)

    def one_line_summary(self, run_id: str, pages: int, attachments: int, elapsed: float) -> str:
        """Generate one-line human-readable summary."""
        rate = pages / elapsed if elapsed > 0 else 0
        return f"{run_id}: {pages} pages, {attachments} attachments in {elapsed:.1f}s ({rate:.1f} pages/s)"


# Global progress renderer instance
_progress: ProgressRenderer | None = None


def get_progress() -> ProgressRenderer:
    """Get the global progress renderer instance."""
    global _progress
    if _progress is None:
        _progress = ProgressRenderer()
    return _progress


def init_progress(
    enabled: bool | None = None,
    quiet_pretty: bool = False,
    no_color: bool = False,
) -> ProgressRenderer:
    """Initialize the global progress renderer with Rich observability features."""
    global _progress
    _progress = ProgressRenderer(enabled=enabled, quiet_pretty=quiet_pretty, no_color=no_color)
    return _progress
