"""Extended assurance and quality gates for all pipeline phases."""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Tuple
from sqlalchemy import text


class QualityGateError(Exception):
    """Raised when quality gates fail."""

    pass


class PhaseAssurance:
    """Base class for phase-specific assurance checks."""

    def __init__(self, run_id: str, phase: str):
        self.run_id = run_id
        self.phase = phase
        self.report_dir = Path(f"var/reports/{run_id}")
        self.report_dir.mkdir(parents=True, exist_ok=True)

        self.issues: List[Dict[str, Any]] = []
        self.metrics: Dict[str, Any] = {}
        self.quality_passed = True

    def add_issue(
        self, issue_type: str, message: str, severity: str = "error", **context
    ):
        """Add quality issue."""
        self.issues.append(
            {
                "type": issue_type,
                "message": message,
                "severity": severity,
                "context": context,
                "timestamp": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
        if severity == "error":
            self.quality_passed = False

    def check_quality_gates(self) -> bool:
        """Override in subclasses to implement quality gates."""
        return self.quality_passed

    def write_reports(self) -> Tuple[Path, Path]:
        """Write JSON and Markdown assurance reports."""
        json_path = self.report_dir / f"{self.phase}_assurance.json"
        md_path = self.report_dir / f"{self.phase}_assurance.md"

        # JSON report
        report_data = {
            "run_id": self.run_id,
            "phase": self.phase,
            "generated_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "quality_passed": self.quality_passed,
            "metrics": self.metrics,
            "issues": self.issues,
            "issue_summary": Counter(issue["type"] for issue in self.issues),
            "error_count": len(
                [i for i in self.issues if i["severity"] == "error"]
            ),
            "warning_count": len(
                [i for i in self.issues if i["severity"] == "warning"]
            ),
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        # Markdown report
        md_content = self._generate_markdown_report(report_data)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return json_path, md_path

    def _generate_markdown_report(self, data: Dict[str, Any]) -> str:
        """Generate human-readable markdown report."""
        lines = [
            f"# {self.phase.title()} Assurance Report",
            "",
            f"**Run ID:** {self.run_id}",
            f"**Phase:** {self.phase}",
            f"**Generated:** {data['generated_at']}",
            f"**Quality Status:** {'✅ PASSED' if data['quality_passed'] else '❌ FAILED'}",
            "",
            "## Summary",
            "",
            f"- **Errors:** {data['error_count']}",
            f"- **Warnings:** {data['warning_count']}",
            f"- **Total Issues:** {len(self.issues)}",
            "",
        ]

        # Metrics
        if self.metrics:
            lines.extend(
                [
                    "## Metrics",
                    "",
                ]
            )
            for key, value in self.metrics.items():
                lines.append(
                    f"- **{key.replace('_', ' ').title()}:** {value:,}"
                    if isinstance(value, int)
                    else f"- **{key.replace('_', ' ').title()}:** {value}"
                )
            lines.append("")

        # Issues by type
        if self.issues:
            lines.extend(
                [
                    "## Issues",
                    "",
                ]
            )

            issues_by_type: dict[str, list] = {}
            for issue in self.issues:
                issue_type = issue["type"]
                if issue_type not in issues_by_type:
                    issues_by_type[issue_type] = []
                issues_by_type[issue_type].append(issue)

            for issue_type, type_issues in issues_by_type.items():
                lines.extend(
                    [
                        f"### {issue_type.replace('_', ' ').title()}",
                        "",
                    ]
                )
                for issue in type_issues[:10]:  # Limit to top 10
                    severity_icon = (
                        "🔴" if issue["severity"] == "error" else "🟡"
                    )
                    lines.append(f"- {severity_icon} {issue['message']}")
                    if issue["context"]:
                        for k, v in issue["context"].items():
                            lines.append(f"  - {k}: `{v}`")
                if len(type_issues) > 10:
                    lines.append(f"  - ... and {len(type_issues) - 10} more")
                lines.append("")

        # Reproduction command
        lines.extend(
            [
                "## Reproduction",
                "",
                "```bash",
                f"# Re-run {self.phase} phase",
                f"trailblazer {self.phase} {self.run_id}",
                "```",
                "",
            ]
        )

        return "\n".join(lines)


class EnrichAssurance(PhaseAssurance):
    """Assurance checks for enrichment phase."""

    def __init__(self, run_id: str):
        super().__init__(run_id, "enrich")

    def check_enrichment_quality(
        self, input_file: Path, output_file: Path, fingerprints_file: Path
    ):
        """Check enrichment quality and coverage."""
        if not input_file.exists():
            self.add_issue(
                "missing_input", f"Input file not found: {input_file}"
            )
            return

        if not output_file.exists():
            self.add_issue(
                "missing_output", f"Output file not found: {output_file}"
            )
            return

        # Count inputs and outputs
        input_count = sum(1 for _ in open(input_file, "r"))
        output_count = sum(1 for _ in open(output_file, "r"))

        self.metrics.update(
            {
                "input_documents": input_count,
                "enriched_documents": output_count,
                "coverage_percent": round(
                    (
                        (output_count / input_count * 100)
                        if input_count > 0
                        else 0
                    ),
                    1,
                ),
            }
        )

        # Check coverage
        if output_count < input_count:
            self.add_issue(
                "incomplete_coverage",
                f"Missing enriched documents: {input_count - output_count} of {input_count}",
            )

        # Check fingerprints
        if fingerprints_file.exists():
            fingerprint_count = sum(1 for _ in open(fingerprints_file, "r"))
            self.metrics["fingerprints_generated"] = fingerprint_count

            if fingerprint_count != output_count:
                self.add_issue(
                    "fingerprint_mismatch",
                    f"Fingerprint count ({fingerprint_count}) != output count ({output_count})",
                )
        else:
            self.add_issue(
                "missing_fingerprints",
                f"Fingerprints file not found: {fingerprints_file}",
            )

    def check_quality_gates(self) -> bool:
        """Check enrichment quality gates."""
        # Gate: Coverage must be 100%
        coverage = self.metrics.get("coverage_percent", 0)
        if coverage < 100:
            self.add_issue(
                "quality_gate_failed",
                f"Coverage {coverage}% below required 100%",
            )

        return super().check_quality_gates()


class ChunkAssurance(PhaseAssurance):
    """Assurance checks for chunking phase."""

    def __init__(self, run_id: str):
        super().__init__(run_id, "chunk")

    def check_chunking_quality(self, input_file: Path, output_file: Path):
        """Check chunking quality and completeness."""
        if not input_file.exists():
            self.add_issue(
                "missing_input", f"Input file not found: {input_file}"
            )
            return

        if not output_file.exists():
            self.add_issue(
                "missing_output", f"Output file not found: {output_file}"
            )
            return

        # Analyze chunks
        doc_chunks = {}
        orphan_chunks = []
        token_counts = []

        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                chunk = json.loads(line.strip())
                doc_id = chunk.get("document_id")
                chunk_id = chunk.get("chunk_id")
                tokens = chunk.get("token_count", 0)

                if not doc_id:
                    orphan_chunks.append(chunk_id or "unknown")
                else:
                    if doc_id not in doc_chunks:
                        doc_chunks[doc_id] = 0
                    doc_chunks[doc_id] += 1

                if tokens > 0:
                    token_counts.append(tokens)

        total_chunks = len(doc_chunks) + len(orphan_chunks)
        avg_chunks_per_doc = (
            sum(doc_chunks.values()) / len(doc_chunks) if doc_chunks else 0
        )
        avg_tokens = (
            sum(token_counts) / len(token_counts) if token_counts else 0
        )

        self.metrics.update(
            {
                "total_chunks": total_chunks,
                "documents_chunked": len(doc_chunks),
                "orphan_chunks": len(orphan_chunks),
                "avg_chunks_per_doc": round(avg_chunks_per_doc, 2),
                "avg_tokens_per_chunk": round(avg_tokens, 1),
                "max_tokens": max(token_counts) if token_counts else 0,
                "min_tokens": min(token_counts) if token_counts else 0,
            }
        )

        # Check for issues
        if orphan_chunks:
            self.add_issue(
                "orphan_chunks",
                f"Found {len(orphan_chunks)} orphan chunks without document_id",
            )

        # Check for extreme outliers (>10x average)
        if token_counts:
            outlier_threshold = avg_tokens * 10
            outliers = [t for t in token_counts if t > outlier_threshold]
            if outliers:
                self.add_issue(
                    "token_outliers",
                    f"Found {len(outliers)} chunks with >10x average tokens ({outlier_threshold:.0f})",
                )

    def check_quality_gates(self) -> bool:
        """Check chunking quality gates."""
        # Gate: No orphan chunks
        if self.metrics.get("orphan_chunks", 0) > 0:
            self.add_issue("quality_gate_failed", "Orphan chunks found")

        return super().check_quality_gates()


class EmbedAssurance(PhaseAssurance):
    """Assurance checks for embedding phase."""

    def __init__(self, run_id: str):
        super().__init__(run_id, "embed")

    def check_embedding_quality(self, db_url: str):
        """Check embedding quality in database."""
        try:
            from ..db.engine import create_engine

            engine = create_engine(db_url)

            with engine.connect() as conn:
                # Check coverage
                result = conn.execute(
                    text("SELECT COUNT(*) FROM chunk_embeddings")
                )
                total_embeddings = result.scalar()

                # Check vector dimensions consistency
                result = conn.execute(
                    text(
                        "SELECT DISTINCT vector_dims(embedding) FROM chunk_embeddings LIMIT 10"
                    )
                )
                dims = [row[0] for row in result]

                # Check for HNSW index
                result = conn.execute(
                    text(
                        """
                    SELECT indexname FROM pg_indexes
                    WHERE tablename = 'chunk_embeddings'
                    AND indexdef LIKE '%hnsw%'
                """
                    )
                )
                hnsw_indexes = [row[0] for row in result]

                self.metrics.update(
                    {
                        "total_embeddings": total_embeddings,
                        "vector_dimensions": (
                            dims[0] if len(set(dims)) == 1 else "inconsistent"
                        ),
                        "dimension_variations": len(set(dims)),
                        "hnsw_indexes": len(hnsw_indexes),
                        "hnsw_index_names": hnsw_indexes,
                    }
                )

                # Check for issues
                if total_embeddings == 0:
                    self.add_issue(
                        "no_embeddings", "No embeddings found in database"
                    )

                if len(set(dims)) > 1:
                    self.add_issue(
                        "inconsistent_dimensions",
                        f"Found {len(set(dims))} different vector dimensions: {sorted(set(dims))}",
                    )

                if not hnsw_indexes:
                    self.add_issue(
                        "missing_hnsw_index",
                        "No HNSW index found for vector search",
                    )

        except Exception as e:
            self.add_issue(
                "database_check_failed", f"Failed to check database: {e}"
            )

    def check_quality_gates(self) -> bool:
        """Check embedding quality gates."""
        # Gate: Must have embeddings
        if self.metrics.get("total_embeddings", 0) == 0:
            self.add_issue("quality_gate_failed", "No embeddings found")

        # Gate: Must have HNSW index
        if self.metrics.get("hnsw_indexes", 0) == 0:
            self.add_issue(
                "quality_gate_failed", "Missing HNSW index for performance"
            )

        return super().check_quality_gates()


def run_phase_assurance(
    run_id: str, phase: str, **kwargs
) -> Tuple[bool, Path, Path]:
    """Run assurance checks for a specific phase.

    Args:
        run_id: Run identifier
        phase: Phase name (enrich, chunk, embed, etc.)
        **kwargs: Phase-specific arguments

    Returns:
        Tuple of (quality_passed, json_report_path, md_report_path)

    Raises:
        QualityGateError: If quality gates fail
    """

    if phase == "enrich":
        input_file = kwargs.get("input_file")
        output_file = kwargs.get("output_file")
        fingerprints_file = kwargs.get("fingerprints_file")

        if (
            input_file is None
            or output_file is None
            or fingerprints_file is None
        ):
            raise ValueError(
                "enrich phase requires input_file, output_file, and fingerprints_file"
            )

        assurance = EnrichAssurance(run_id)
        assurance.check_enrichment_quality(
            input_file, output_file, fingerprints_file
        )
    elif phase == "chunk":
        input_file = kwargs.get("input_file")
        output_file = kwargs.get("output_file")

        if input_file is None or output_file is None:
            raise ValueError("chunk phase requires input_file and output_file")

        chunk_assurance = ChunkAssurance(run_id)
        chunk_assurance.check_chunking_quality(input_file, output_file)
        quality_passed = chunk_assurance.check_quality_gates()
        json_path, md_path = chunk_assurance.write_reports()
        return quality_passed, json_path, md_path
    elif phase == "embed":
        db_url = kwargs.get("db_url")

        if db_url is None:
            raise ValueError("embed phase requires db_url")

        embed_assurance = EmbedAssurance(run_id)
        embed_assurance.check_embedding_quality(db_url)
        quality_passed = embed_assurance.check_quality_gates()
        json_path, md_path = embed_assurance.write_reports()
        return quality_passed, json_path, md_path
    else:
        raise ValueError(f"Unknown phase: {phase}")

    quality_passed = assurance.check_quality_gates()
    json_path, md_path = assurance.write_reports()

    if not quality_passed:
        raise QualityGateError(
            f"Quality gates failed for {phase} phase. See report: {md_path}"
        )

    return quality_passed, json_path, md_path
