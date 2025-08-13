"""Progress rendering for TTY and CLI output separation."""

import sys
import os
import time
from typing import Optional, TextIO, Dict, Any


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
    """Pretty progress renderer that outputs to stderr only."""

    def __init__(
        self,
        enabled: Optional[bool] = None,
        quiet_pretty: bool = False,
        file: Optional[TextIO] = None,
    ):
        """
        Initialize progress renderer.

        Args:
            enabled: Whether to show progress. Auto-detected if None.
            quiet_pretty: Suppress banners but keep progress bars.
            file: Output file, defaults to stderr.
        """
        self.enabled = enabled if enabled is not None else should_use_pretty()
        self.quiet_pretty = quiet_pretty
        self.file = file or sys.stderr
        self.start_time: Optional[float] = None
        self.last_update: float = 0
        self.page_count = 0
        self.attachment_count = 0
        self.space_count = 0

    def start_banner(
        self,
        run_id: str,
        spaces: int,
        since_mode: str = "none",
        max_pages: Optional[int] = None,
    ):
        """Print start banner with run details."""
        if not self.enabled or self.quiet_pretty:
            return

        self.start_time = time.time()
        self.space_count = spaces

        print(f"🚀 Starting ingest run: {run_id}", file=self.file)
        print(f"   Spaces targeted: {spaces}", file=self.file)
        print(f"   Mode: {since_mode}", file=self.file)
        if max_pages:
            print(f"   Max pages: {max_pages}", file=self.file)
        print("", file=self.file)

    def finish_banner(
        self,
        run_id: str,
        space_stats: Dict[str, Dict[str, Any]],
        elapsed: float,
    ):
        """Print finish banner with summary stats."""
        if not self.enabled or self.quiet_pretty:
            return

        print("", file=self.file)
        print(f"✅ Completed ingest run: {run_id}", file=self.file)
        print(f"   Elapsed: {elapsed:.1f}s", file=self.file)

        total_pages = sum(
            stats.get("pages", 0) for stats in space_stats.values()
        )
        total_attachments = sum(
            stats.get("attachments", 0) for stats in space_stats.values()
        )
        total_empty = sum(
            stats.get("empty_bodies", 0) for stats in space_stats.values()
        )

        print(
            f"   Total: {total_pages} pages, {total_attachments} attachments",
            file=self.file,
        )
        if total_empty > 0:
            print(f"   Empty bodies: {total_empty}", file=self.file)

        if len(space_stats) > 1:
            print("   Per space:", file=self.file)
            for space_key, stats in sorted(space_stats.items()):
                print(
                    f"     {space_key}: {stats.get('pages', 0)} pages, "
                    f"{stats.get('attachments', 0)} attachments",
                    file=self.file,
                )

    def spaces_table(self, spaces: list[Dict[str, Any]]):
        """Print compact table of spaces being ingested."""
        if not self.enabled or self.quiet_pretty or not spaces:
            return

        print("📋 Spaces to ingest:", file=self.file)
        print("   ID       | KEY      | NAME", file=self.file)
        print(
            "   ---------|----------|----------------------------------",
            file=self.file,
        )

        for space in spaces:
            space_id = str(space.get("id", ""))[:8]
            space_key = space.get("key", "")[:8]
            space_name = space.get("name", "")[:32]
            print(
                f"   {space_id:<8} | {space_key:<8} | {space_name}",
                file=self.file,
            )
        print("", file=self.file)

    def progress_update(
        self,
        space_key: str,
        page_id: str,
        title: str,
        attachments: int,
        updated_at: Optional[str] = None,
        throttle_every: int = 1,
    ):
        """Show progress update for a page."""
        if not self.enabled:
            return

        self.page_count += 1
        self.attachment_count += attachments

        # Throttle updates
        if self.page_count % throttle_every != 0:
            return

        current_time = time.time()

        # Rate calculation
        if self.start_time:
            elapsed = current_time - self.start_time
            rate = self.page_count / elapsed if elapsed > 0 else 0
            rate_str = f" ({rate:.1f}/s)" if rate > 0 else ""
        else:
            rate_str = ""

        # Truncate long titles
        title_display = title[:40] + "..." if len(title) > 43 else title
        updated_display = updated_at or "unknown"

        print(
            f'{space_key} | p={page_id} | "{title_display}" | att={attachments} | {updated_display}{rate_str}',
            file=self.file,
        )

        self.last_update = current_time

    def resume_indicator(self, last_page: str, timestamp: str):
        """Show resume indicator when continuing from previous run."""
        if not self.enabled:
            return

        print(
            f"↪️  Resuming from page {last_page} (last update: {timestamp})",
            file=self.file,
        )

    def one_line_summary(
        self, run_id: str, pages: int, attachments: int, elapsed: float
    ) -> str:
        """Generate one-line human-readable summary."""
        rate = pages / elapsed if elapsed > 0 else 0
        return f"{run_id}: {pages} pages, {attachments} attachments in {elapsed:.1f}s ({rate:.1f} pages/s)"


# Global progress renderer instance
_progress: Optional[ProgressRenderer] = None


def get_progress() -> ProgressRenderer:
    """Get the global progress renderer instance."""
    global _progress
    if _progress is None:
        _progress = ProgressRenderer()
    return _progress


def init_progress(
    enabled: Optional[bool] = None, quiet_pretty: bool = False
) -> ProgressRenderer:
    """Initialize the global progress renderer."""
    global _progress
    _progress = ProgressRenderer(enabled=enabled, quiet_pretty=quiet_pretty)
    return _progress
