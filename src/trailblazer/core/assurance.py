"""Assurance report generation for ingest observability."""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.logging import log


class AssuranceReportGenerator:
    """Generate comprehensive assurance reports for ingest runs."""

    def __init__(
        self,
        run_id: str,
        source: str,
        outdir: Path,
        event_log_path: Path | None = None,
    ):
        """Initialize assurance report generator.

        Args:
            run_id: Run identifier
            source: Source system (confluence, dita)
            outdir: Output directory (e.g., var/runs/<run_id>/<source>/)
            event_log_path: Path to NDJSON event log for analysis
        """
        self.run_id = run_id
        self.source = source
        self.outdir = Path(outdir)
        self.event_log_path = event_log_path

        # Report data
        self.report_data: dict[str, Any] = {
            "run_id": run_id,
            "source": source,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "totals": {},
            "spaces": {},
            "quality_issues": {
                "zero_body_pages": [],
                "non_adf_bodies": [],
                "missing_attachments": [],
                "failed_attachments": [],
                "large_pages": [],
            },
            "performance": {
                "top_10_largest_pages": [],
                "slowest_spaces": [],
                "retry_stats": {},
            },
            "errors": {
                "summary": {},
                "by_type": {},
                "by_space": {},
            },
            "repro_command": "",
        }

    def analyze_run_artifacts(self):
        """Analyze run artifacts to populate report data."""
        # Load main data files
        self._analyze_main_data()
        self._analyze_summary_data()
        self._analyze_event_log()
        self._generate_repro_command()

    def _analyze_main_data(self):
        """Analyze main NDJSON output file."""
        main_file = self.outdir / f"{self.source}.ndjson"
        if not main_file.exists():
            log.warning("assurance.main_file_missing", file=str(main_file))
            return

        records = []
        try:
            with open(main_file, encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        records.append(json.loads(line.strip()))
                    except json.JSONDecodeError as e:
                        log.warning(
                            "assurance.json_decode_error",
                            file=str(main_file),
                            line=line_num,
                            error=str(e),
                        )
        except Exception as e:
            log.error("assurance.read_error", file=str(main_file), error=str(e))
            return

        # Analyze records
        self._analyze_records(records)

    def _analyze_records(self, records: list[dict]):
        """Analyze individual records for quality issues."""
        space_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "pages": 0,
                "attachments": 0,
                "total_chars": 0,
                "zero_body": 0,
                "non_adf": 0,
                "errors": 0,
            }
        )

        total_pages = len(records)
        total_attachments = 0
        total_chars = 0

        for record in records:
            space_key = record.get("space_key", "unknown")
            page_id = record.get("id") or record.get("page_id", "unknown")
            title = record.get("title", "")

            # Update space stats
            space_stats[space_key]["pages"] += 1
            attachment_count = record.get("attachment_count", 0)
            space_stats[space_key]["attachments"] += attachment_count
            total_attachments += attachment_count

            # Analyze body content
            body_repr = record.get("body_repr", "")
            body_content = ""

            if body_repr == "adf":
                body_adf = record.get("body_adf")
                if body_adf:
                    # Estimate text length from ADF
                    body_content = json.dumps(body_adf) if isinstance(body_adf, dict) else str(body_adf)
                else:
                    space_stats[space_key]["zero_body"] += 1
                    self.report_data["quality_issues"]["zero_body_pages"].append(
                        {
                            "page_id": page_id,
                            "title": title,
                            "space_key": space_key,
                            "url": record.get("url"),
                        }
                    )
            elif body_repr == "storage":
                body_content = record.get("body_storage", "")
                if not body_content:
                    space_stats[space_key]["zero_body"] += 1
                    self.report_data["quality_issues"]["zero_body_pages"].append(
                        {
                            "page_id": page_id,
                            "title": title,
                            "space_key": space_key,
                            "url": record.get("url"),
                        }
                    )
            else:
                # Non-ADF/storage body
                space_stats[space_key]["non_adf"] += 1
                self.report_data["quality_issues"]["non_adf_bodies"].append(
                    {
                        "page_id": page_id,
                        "title": title,
                        "space_key": space_key,
                        "body_repr": body_repr,
                    }
                )

            # Track content size
            char_count = len(body_content)
            space_stats[space_key]["total_chars"] += char_count
            total_chars += char_count

            # Large pages (>50KB content)
            if char_count > 50000:
                self.report_data["performance"]["top_10_largest_pages"].append(
                    {
                        "page_id": page_id,
                        "title": title,
                        "space_key": space_key,
                        "char_count": char_count,
                        "url": record.get("url"),
                    }
                )

            # Attachment completeness check
            attachments = record.get("attachments", [])
            if attachment_count != len(attachments):
                self.report_data["quality_issues"]["missing_attachments"].append(
                    {
                        "page_id": page_id,
                        "title": title,
                        "space_key": space_key,
                        "expected": attachment_count,
                        "actual": len(attachments),
                    }
                )

        # Sort and limit largest pages
        self.report_data["performance"]["top_10_largest_pages"].sort(key=lambda x: x["char_count"], reverse=True)
        self.report_data["performance"]["top_10_largest_pages"] = self.report_data["performance"][
            "top_10_largest_pages"
        ][:10]

        # Store totals
        self.report_data["totals"] = {
            "pages": total_pages,
            "attachments": total_attachments,
            "total_chars": total_chars,
            "avg_chars_per_page": (total_chars / total_pages if total_pages > 0 else 0),
            "spaces": len(space_stats),
        }

        # Store per-space stats
        for space_key, stats in space_stats.items():
            avg_chars = stats["total_chars"] / stats["pages"] if stats["pages"] > 0 else 0
            self.report_data["spaces"][space_key] = {
                "pages": stats["pages"],
                "attachments": stats["attachments"],
                "avg_chars": round(avg_chars, 2),
                "zero_body_pages": stats["zero_body"],
                "non_adf_pages": stats["non_adf"],
                "errors": stats["errors"],
            }

    def _analyze_summary_data(self):
        """Analyze summary.json if available."""
        summary_file = self.outdir / "summary.json"
        if not summary_file.exists():
            return

        try:
            with open(summary_file) as f:
                summary = json.load(f)

            # Extract performance metrics
            elapsed = summary.get("elapsed_seconds", 0)
            pages = summary.get("total_pages", 0)
            rate = pages / elapsed if elapsed > 0 else 0

            self.report_data["performance"]["rate_pages_per_second"] = round(rate, 2)
            self.report_data["performance"]["elapsed_seconds"] = elapsed

            # Check for warnings
            if "warnings" in summary:
                self.report_data["quality_issues"]["warnings"] = summary["warnings"]

        except Exception as e:
            log.warning("assurance.summary_read_error", error=str(e))

    def _analyze_event_log(self):
        """Analyze NDJSON event log for errors and performance."""
        if not self.event_log_path or not self.event_log_path.exists():
            return

        error_counts = Counter()
        retry_counts = Counter()
        space_timings = {}

        try:
            with open(self.event_log_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        event_type = event.get("event_type", "")

                        # Track errors
                        if event_type == "error":
                            error_type = event.get("error_type", "unknown")
                            space_key = event.get("space_key", "unknown")
                            error_counts[error_type] += 1

                            if space_key not in self.report_data["errors"]["by_space"]:
                                self.report_data["errors"]["by_space"][space_key] = []
                            self.report_data["errors"]["by_space"][space_key].append(
                                {
                                    "error_type": error_type,
                                    "message": event.get("message", ""),
                                    "timestamp": event.get("timestamp", ""),
                                }
                            )

                        # Track retries
                        retry_count = event.get("retry_count", 0)
                        if retry_count > 0:
                            retry_counts[event_type] += retry_count

                        # Track space performance
                        if event_type == "space.end":
                            space_key = event.get("space_key", "")
                            elapsed = event.get("elapsed_seconds", 0)
                            pages = event.get("pages_processed", 0)
                            if space_key and elapsed > 0:
                                space_timings[space_key] = {
                                    "elapsed_seconds": elapsed,
                                    "pages": pages,
                                    "rate": pages / elapsed,
                                }

                    except json.JSONDecodeError:
                        continue  # Skip malformed lines

        except Exception as e:
            log.warning("assurance.event_log_read_error", error=str(e))
            return

        # Store error analysis
        self.report_data["errors"]["summary"] = {
            "total_errors": sum(error_counts.values()),
            "error_types": len(error_counts),
        }
        self.report_data["errors"]["by_type"] = dict(error_counts)

        # Store retry analysis
        self.report_data["performance"]["retry_stats"] = dict(retry_counts)

        # Store slowest spaces
        slowest_spaces = sorted(
            space_timings.items(),
            key=lambda x: x[1]["rate"] if x[1]["rate"] > 0 else float("inf"),
        )[:5]

        self.report_data["performance"]["slowest_spaces"] = [
            {
                "space_key": space_key,
                "elapsed_seconds": timing["elapsed_seconds"],
                "pages": timing["pages"],
                "rate": round(timing["rate"], 2),
            }
            for space_key, timing in slowest_spaces
        ]

    def _generate_repro_command(self):
        """Generate reproduction command."""
        # Basic command structure
        cmd_parts = [
            "trailblazer",
            "ingest",
            self.source,
        ]

        # Add common flags
        cmd_parts.extend(
            [
                "--progress",
                "--progress-every",
                "10",
                "--log-format",
                "auto",
            ]
        )

        # Source-specific flags
        if self.source == "confluence":
            # Add space flags if we can determine them
            spaces = list(self.report_data["spaces"].keys())
            if len(spaces) == 1 and spaces[0] != "unknown":
                cmd_parts.extend(["--space", spaces[0]])
            cmd_parts.extend(["--body-format", "atlas_doc_format"])
        elif self.source == "dita":
            cmd_parts.extend(["--root", "data/raw/dita/ellucian-documentation"])

        self.report_data["repro_command"] = " ".join(cmd_parts)

    def write_reports(self) -> tuple[Path, Path]:
        """Write both JSON and Markdown assurance reports.

        Returns:
            Tuple of (json_path, markdown_path)
        """
        # Write JSON report
        json_path = self.outdir / "assurance.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.report_data, f, indent=2, sort_keys=True)

        # Write Markdown report
        md_path = self.outdir / "assurance.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._generate_markdown())

        return json_path, md_path

    def _generate_markdown(self) -> str:
        """Generate Markdown assurance report."""
        lines = [
            f"# Assurance Report: {self.source.title()} Ingest",
            "",
            f"**Run ID:** `{self.run_id}`  ",
            f"**Source:** {self.source}  ",
            f"**Generated:** {self.report_data['generated_at']}  ",
            "",
            "## 📊 Summary",
            "",
        ]

        # Totals
        totals = self.report_data["totals"]
        lines.extend(
            [
                f"- **Total Pages:** {totals.get('pages', 0):,}",
                f"- **Total Attachments:** {totals.get('attachments', 0):,}",
                f"- **Total Characters:** {totals.get('total_chars', 0):,}",
                f"- **Average Chars/Page:** {totals.get('avg_chars_per_page', 0):,.0f}",
                f"- **Spaces Processed:** {totals.get('spaces', 0)}",
                "",
            ]
        )

        # Performance
        perf = self.report_data["performance"]
        if "rate_pages_per_second" in perf:
            lines.extend(
                [
                    "## ⚡ Performance",
                    "",
                    f"- **Processing Rate:** {perf['rate_pages_per_second']:.2f} pages/second",
                    f"- **Total Duration:** {perf.get('elapsed_seconds', 0):.1f} seconds",
                    "",
                ]
            )

        # Quality Issues
        lines.extend(
            [
                "## 🔍 Quality Issues",
                "",
            ]
        )

        issues = self.report_data["quality_issues"]

        # Zero body pages
        zero_body = issues.get("zero_body_pages", [])
        if zero_body:
            lines.extend(
                [
                    f"### Zero-Body Pages ({len(zero_body)})",
                    "",
                    "| Page ID | Title | Space | URL |",
                    "|---------|--------|-------|-----|",
                ]
            )
            for page in zero_body[:10]:  # Limit to first 10
                title = page.get("title", "")[:50] + "..." if len(page.get("title", "")) > 50 else page.get("title", "")
                url = page.get("url", "")
                url_display = f"[Link]({url})" if url else ""
                lines.append(f"| `{page['page_id']}` | {title} | {page['space_key']} | {url_display} |")

            if len(zero_body) > 10:
                lines.append(f"\n*... and {len(zero_body) - 10} more*")
            lines.append("")

        # Non-ADF bodies
        non_adf = issues.get("non_adf_bodies", [])
        if non_adf:
            lines.extend(
                [
                    f"### Non-ADF Bodies ({len(non_adf)})",
                    "",
                    "| Page ID | Title | Space | Body Format |",
                    "|---------|--------|-------|-------------|",
                ]
            )
            for page in non_adf[:5]:  # Limit to first 5
                title = page.get("title", "")[:40] + "..." if len(page.get("title", "")) > 40 else page.get("title", "")
                lines.append(f"| `{page['page_id']}` | {title} | {page['space_key']} | {page.get('body_repr', '')} |")

            if len(non_adf) > 5:
                lines.append(f"\n*... and {len(non_adf) - 5} more*")
            lines.append("")

        # Missing attachments
        missing_att = issues.get("missing_attachments", [])
        if missing_att:
            lines.extend(
                [
                    f"### Attachment Count Mismatches ({len(missing_att)})",
                    "",
                    "| Page ID | Title | Space | Expected | Actual |",
                    "|---------|--------|-------|----------|--------|",
                ]
            )
            for page in missing_att[:5]:
                title = page.get("title", "")[:40] + "..." if len(page.get("title", "")) > 40 else page.get("title", "")
                lines.append(
                    f"| `{page['page_id']}` | {title} | {page['space_key']} | {page['expected']} | {page['actual']} |"
                )

            if len(missing_att) > 5:
                lines.append(f"\n*... and {len(missing_att) - 5} more*")
            lines.append("")

        # Top 10 largest pages
        largest = self.report_data["performance"].get("top_10_largest_pages", [])
        if largest:
            lines.extend(
                [
                    "## 📈 Top 10 Largest Pages",
                    "",
                    "| Page ID | Title | Space | Size (chars) | URL |",
                    "|---------|--------|-------|--------------|-----|",
                ]
            )
            for page in largest:
                title = page.get("title", "")[:40] + "..." if len(page.get("title", "")) > 40 else page.get("title", "")
                url = page.get("url", "")
                url_display = f"[Link]({url})" if url else ""
                lines.append(
                    f"| `{page['page_id']}` | {title} | {page['space_key']} | {page['char_count']:,} | {url_display} |"
                )
            lines.append("")

        # Errors
        errors = self.report_data["errors"]
        if errors.get("summary", {}).get("total_errors", 0) > 0:
            lines.extend(
                [
                    "## ❌ Errors",
                    "",
                    f"**Total Errors:** {errors['summary']['total_errors']}  ",
                    f"**Error Types:** {errors['summary']['error_types']}  ",
                    "",
                ]
            )

            # Error breakdown by type
            error_types = errors.get("by_type", {})
            if error_types:
                lines.extend(
                    [
                        "### By Error Type",
                        "",
                    ]
                )
                for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"- **{error_type}:** {count}")
                lines.append("")

        # Per-space stats
        spaces = self.report_data["spaces"]
        if spaces:
            lines.extend(
                [
                    "## 🏢 Per-Space Breakdown",
                    "",
                    "| Space | Pages | Attachments | Avg Chars | Zero Bodies | Errors |",
                    "|-------|-------|-------------|-----------|-------------|--------|",
                ]
            )

            # Sort by page count descending
            sorted_spaces = sorted(spaces.items(), key=lambda x: x[1]["pages"], reverse=True)
            for space_key, stats in sorted_spaces:
                lines.append(
                    f"| {space_key} | {stats['pages']:,} | {stats['attachments']:,} | "
                    f"{stats['avg_chars']:,.0f} | {stats.get('zero_body_pages', 0)} | "
                    f"{stats.get('errors', 0)} |"
                )
            lines.append("")

        # Reproduction command
        lines.extend(
            [
                "## 🔄 Reproduction Command",
                "",
                "```bash",
                f"{self.report_data['repro_command']}",
                "```",
                "",
            ]
        )

        return "\n".join(lines)


def generate_assurance_report(
    run_id: str,
    source: str,
    outdir: str | Path,
    event_log_path: str | Path | None = None,
) -> tuple[Path, Path]:
    """Generate assurance reports for an ingest run.

    Args:
        run_id: Run identifier
        source: Source system (confluence, dita)
        outdir: Output directory (e.g., var/runs/<run_id>/<source>/)
        event_log_path: Optional path to NDJSON event log

    Returns:
        Tuple of (json_path, markdown_path)
    """
    generator = AssuranceReportGenerator(
        run_id=run_id,
        source=source,
        outdir=Path(outdir),
        event_log_path=Path(event_log_path) if event_log_path else None,
    )

    generator.analyze_run_artifacts()
    return generator.write_reports()
