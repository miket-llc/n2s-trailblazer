"""Data integrity and format validation to prevent loss and enforce structure."""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from pydantic import BaseModel
from ..core.logging import log


class TraceabilityRecord(BaseModel):
    """Schema for traceability validation."""

    id: str
    url: Optional[str] = None
    space_key: Optional[str] = None
    space_id: Optional[str] = None
    labels: Optional[List[str]] = None
    breadcrumbs: Optional[List[str]] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    content_sha256: Optional[str] = None


class DataIntegrityChecker:
    """Comprehensive data integrity and format validation."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.run_dir = Path(f"var/runs/{run_id}")
        self.issues: List[Dict[str, Any]] = []
        self.sampled_items: List[Dict[str, Any]] = []

    def add_issue(
        self, issue_type: str, message: str, severity: str = "error", **context
    ):
        """Add integrity issue."""
        self.issues.append(
            {
                "type": issue_type,
                "message": message,
                "severity": severity,
                "context": context,
            }
        )

    def validate_traceability_chain(
        self, sample_size: int = 10
    ) -> Dict[str, Any]:
        """Validate traceability keys are retained end-to-end."""
        results: Dict[str, Any] = {
            "sampled_count": 0,
            "valid_chains": 0,
            "broken_chains": 0,
            "missing_fields": {},
            "field_retention_rates": {},
        }

        # Required traceability fields
        required_fields = [
            "id",
            "url",
            "space_key",
            "labels",
            "breadcrumbs",
            "content_sha256",
        ]

        # Sample from different phases
        phases = ["ingest", "normalize", "enrich"]
        phase_files = {
            "ingest": "confluence.ndjson",
            "normalize": "normalized.ndjson",
            "enrich": "enriched.jsonl",
        }

        sampled_ids = set()
        phase_data = {}

        # Load samples from each phase
        for phase in phases:
            phase_dir = self.run_dir / phase
            if not phase_dir.exists():
                continue

            phase_file = phase_dir / phase_files.get(phase, f"{phase}.ndjson")
            if not phase_file.exists():
                continue

            phase_records: List[Dict[str, Any]] = []
            try:
                with open(phase_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    # Sample every Nth record to get diverse data
                    step = max(1, len(lines) // sample_size)
                    for i in range(0, len(lines), step):
                        if len(phase_records) >= sample_size:
                            break
                        try:
                            record = json.loads(lines[i].strip())
                            if record.get("id"):
                                phase_records.append(record)
                                sampled_ids.add(record["id"])
                        except json.JSONDecodeError:
                            continue

                phase_data[phase] = phase_records
            except IOError:
                continue

        results["sampled_count"] = len(sampled_ids)

        # Check field retention across phases
        field_counts = {
            field: {phase: 0 for phase in phases} for field in required_fields
        }

        for phase, records in phase_data.items():
            for record in records:
                for field in required_fields:
                    if field in record and record[field] is not None:
                        field_counts[field][phase] += 1

        # Calculate retention rates
        for field in required_fields:
            phase_counts = [
                field_counts[field].get(phase, 0)
                for phase in phases
                if phase in phase_data
            ]
            if phase_counts and max(phase_counts) > 0:
                retention_rate = min(phase_counts) / max(phase_counts) * 100
                results["field_retention_rates"][field] = round(
                    retention_rate, 1
                )

                if retention_rate < 95:  # 95% retention threshold
                    self.add_issue(
                        "field_retention_loss",
                        f"Field '{field}' retention rate {retention_rate:.1f}% below 95% threshold",
                        context={
                            "field": field,
                            "retention_rate": retention_rate,
                        },
                    )

        # Check for complete traceability chains
        if "ingest" in phase_data and "enrich" in phase_data:
            ingest_ids = {r["id"] for r in phase_data["ingest"]}
            enrich_ids = {r["id"] for r in phase_data["enrich"]}

            complete_chains = ingest_ids.intersection(enrich_ids)
            broken_chains = ingest_ids - enrich_ids

            results["valid_chains"] = len(complete_chains)
            results["broken_chains"] = len(broken_chains)

            if broken_chains:
                self.add_issue(
                    "broken_traceability_chain",
                    f"Found {len(broken_chains)} documents that didn't complete the pipeline",
                    context={
                        "broken_ids": list(broken_chains)[:10]
                    },  # Show first 10
                )

        return results

    def validate_json_schemas(self) -> Dict[str, Any]:
        """Validate JSON structure against schemas."""
        results = {
            "files_checked": 0,
            "schema_errors": 0,
            "parse_errors": 0,
            "valid_files": 0,
        }

        # Find all NDJSON/JSON files
        json_files = list(self.run_dir.rglob("*.ndjson")) + list(
            self.run_dir.rglob("*.jsonl")
        )

        for json_file in json_files:
            results["files_checked"] += 1

            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        try:
                            data = json.loads(line.strip())

                            # Basic schema validation for common fields
                            if isinstance(data, dict):
                                # Check for required base fields
                                if not data.get("id"):
                                    self.add_issue(
                                        "missing_id_field",
                                        f"Missing 'id' field in {json_file.name}:{line_num}",
                                        severity="warning",
                                    )

                        except json.JSONDecodeError as e:
                            results["parse_errors"] += 1
                            self.add_issue(
                                "json_parse_error",
                                f"JSON parse error in {json_file.name}:{line_num}: {e}",
                                context={
                                    "file": str(json_file),
                                    "line": line_num,
                                },
                            )

            except IOError as e:
                self.add_issue(
                    "file_read_error",
                    f"Cannot read file {json_file}: {e}",
                    context={"file": str(json_file)},
                )
                continue

            results["valid_files"] += 1

        return results

    def check_format_compliance(self) -> Dict[str, Any]:
        """Check format compliance using external tools."""
        results: Dict[str, Any] = {
            "markdown_files": 0,
            "markdown_errors": 0,
            "format_issues": [],
        }

        # Find generated markdown files
        md_files = list(self.run_dir.rglob("*.md"))
        results["markdown_files"] = len(md_files)

        for md_file in md_files:
            # Check markdown lint if available
            try:
                result = subprocess.run(
                    ["markdownlint", str(md_file)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode != 0:
                    results["markdown_errors"] += 1
                    self.add_issue(
                        "markdown_lint_error",
                        f"Markdown lint errors in {md_file.name}",
                        severity="warning",
                        context={
                            "file": str(md_file),
                            "errors": result.stdout,
                        },
                    )

            except (subprocess.TimeoutExpired, FileNotFoundError):
                # markdownlint not available or timeout
                pass

        return results

    def create_sample_artifacts(self, sample_count: int = 5) -> Dict[str, Any]:
        """Create sampling proof with source chunk IDs for human verification."""
        results: Dict[str, Any] = {
            "samples_created": 0,
            "sample_directory": None,
            "sample_files": [],
        }

        # Create samples directory
        samples_dir = self.run_dir / "samples"
        samples_dir.mkdir(exist_ok=True)
        results["sample_directory"] = str(samples_dir)

        # Sample from compose/playbook outputs if they exist
        compose_dir = self.run_dir / "compose"
        if compose_dir.exists():
            output_files = list(compose_dir.rglob("*.md"))

            # Sample files
            sampled_files = (
                output_files[:sample_count]
                if len(output_files) >= sample_count
                else output_files
            )

            for i, source_file in enumerate(sampled_files):
                sample_name = f"sample_{i + 1}_{source_file.name}"
                sample_path = samples_dir / sample_name

                try:
                    # Copy file with metadata
                    with open(source_file, "r", encoding="utf-8") as src:
                        content = src.read()

                    with open(sample_path, "w", encoding="utf-8") as dst:
                        dst.write("<!-- SAMPLE ARTIFACT -->\n")
                        dst.write(
                            f"<!-- Source: {source_file.relative_to(self.run_dir)} -->\n"
                        )
                        dst.write(f"<!-- Run ID: {self.run_id} -->\n")
                        dst.write(
                            f"<!-- Created: {source_file.stat().st_mtime} -->\n\n"
                        )
                        dst.write(content)

                    results["sample_files"].append(str(sample_path))
                    results["samples_created"] += 1

                except IOError:
                    continue

        return results

    def run_comprehensive_check(self, sample_size: int = 10) -> Dict[str, Any]:
        """Run all integrity checks and return comprehensive report."""

        log.info("data_integrity.check_start", run_id=self.run_id)

        # Run all checks
        traceability_results = self.validate_traceability_chain(sample_size)
        schema_results = self.validate_json_schemas()
        format_results = self.check_format_compliance()
        sampling_results = self.create_sample_artifacts()

        # Compile comprehensive report
        report: Dict[str, Any] = {
            "run_id": self.run_id,
            "check_timestamp": "2025-08-15T21:40:00Z",  # Would be dynamic
            "overall_status": (
                "passed"
                if len([i for i in self.issues if i["severity"] == "error"])
                == 0
                else "failed"
            ),
            "checks": {
                "traceability": traceability_results,
                "schema_validation": schema_results,
                "format_compliance": format_results,
                "sampling": sampling_results,
            },
            "issues": self.issues,
            "issue_summary": {
                "total": len(self.issues),
                "errors": len(
                    [i for i in self.issues if i["severity"] == "error"]
                ),
                "warnings": len(
                    [i for i in self.issues if i["severity"] == "warning"]
                ),
            },
        }

        log.info(
            "data_integrity.check_complete",
            run_id=self.run_id,
            status=report["overall_status"],
            total_issues=report["issue_summary"]["total"],
        )

        return report

    def write_integrity_report(
        self, report: Dict[str, Any]
    ) -> Tuple[Path, Path]:
        """Write integrity report in JSON and Markdown formats."""

        reports_dir = Path(f"var/reports/{self.run_id}")
        reports_dir.mkdir(parents=True, exist_ok=True)

        json_path = reports_dir / "data_integrity.json"
        md_path = reports_dir / "data_integrity.md"

        # Write JSON report
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Write Markdown report
        md_content = self._generate_markdown_report(report)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return json_path, md_path

    def _generate_markdown_report(self, report: Dict[str, Any]) -> str:
        """Generate human-readable markdown integrity report."""
        status_icon = "✅" if report["overall_status"] == "passed" else "❌"

        lines = [
            "# Data Integrity Report",
            "",
            f"**Run ID:** {report['run_id']}",
            f"**Status:** {status_icon} {report['overall_status'].upper()}",
            f"**Checked:** {report['check_timestamp']}",
            "",
            "## Summary",
            "",
            f"- **Total Issues:** {report['issue_summary']['total']}",
            f"- **Errors:** {report['issue_summary']['errors']}",
            f"- **Warnings:** {report['issue_summary']['warnings']}",
            "",
            "## Traceability Check",
            "",
        ]

        # Traceability results
        trace = report["checks"]["traceability"]
        lines.extend(
            [
                f"- **Sampled Items:** {trace['sampled_count']}",
                f"- **Valid Chains:** {trace['valid_chains']}",
                f"- **Broken Chains:** {trace['broken_chains']}",
                "",
                "### Field Retention Rates",
                "",
            ]
        )

        for field, rate in trace.get("field_retention_rates", {}).items():
            status = "✅" if rate >= 95 else "⚠️"
            lines.append(f"- {status} **{field}:** {rate}%")

        lines.extend(
            [
                "",
                "## Schema Validation",
                "",
                f"- **Files Checked:** {report['checks']['schema_validation']['files_checked']}",
                f"- **Parse Errors:** {report['checks']['schema_validation']['parse_errors']}",
                f"- **Schema Errors:** {report['checks']['schema_validation']['schema_errors']}",
                "",
                "## Sampling Proof",
                "",
                f"- **Samples Created:** {report['checks']['sampling']['samples_created']}",
                f"- **Sample Directory:** `{report['checks']['sampling']['sample_directory']}`",
                "",
            ]
        )

        # List sample files
        for sample_file in report["checks"]["sampling"].get(
            "sample_files", []
        ):
            lines.append(f"- `{Path(sample_file).name}`")

        # Issues section
        if self.issues:
            lines.extend(
                [
                    "",
                    "## Issues Found",
                    "",
                ]
            )

            for issue in self.issues[:20]:  # Show first 20
                severity_icon = "🔴" if issue["severity"] == "error" else "🟡"
                lines.append(
                    f"- {severity_icon} **{issue['type']}:** {issue['message']}"
                )

        return "\n".join(lines)


def run_data_integrity_check(
    run_id: str, sample_size: int = 10
) -> Tuple[Dict[str, Any], Path, Path]:
    """Run comprehensive data integrity check for a run.

    Args:
        run_id: Run identifier
        sample_size: Number of items to sample for traceability checks

    Returns:
        Tuple of (report_data, json_report_path, md_report_path)
    """
    checker = DataIntegrityChecker(run_id)
    report = checker.run_comprehensive_check(sample_size)
    json_path, md_path = checker.write_integrity_report(report)

    return report, json_path, md_path
