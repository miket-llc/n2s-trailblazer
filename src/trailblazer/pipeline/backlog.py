"""
Processed runs backlog management for default selection and claim/mark operations.
"""

import os
import socket
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2  # type: ignore[import-untyped]
from psycopg2.extras import RealDictCursor  # type: ignore[import-untyped]

from ..core.config import SETTINGS


@contextmanager
def get_db_connection():
    """Get database connection using trailblazer settings."""
    # Parse the DB URL from settings
    db_url = SETTINGS.TRAILBLAZER_DB_URL
    if not db_url:
        # Fallback to development default
        db_url = "postgresql://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer"
    elif db_url.startswith("postgresql+psycopg2://"):
        # Convert SQLAlchemy URL to psycopg2 format
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql://")

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.close()


def emit_backlog_event(action: str, **kwargs):
    """Emit NDJSON backlog event to stdout."""
    import json

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "action": action,
        "component": "backlog",
        "pid": os.getpid(),
        **kwargs,
    }
    print(json.dumps(event), flush=True)


def upsert_normalized_run(
    run_id: str,
    source: str,
    total_docs: int,
    code_version: str | None = None,
) -> None:
    """
    UPSERT a run in processed_runs table after successful normalization.

    Args:
        run_id: The run identifier
        source: Source type (confluence|dita|mixed)
        total_docs: Number of documents normalized
        code_version: Code version string
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        normalized_at = datetime.now(timezone.utc)
        updated_at = normalized_at

        cursor.execute(
            """
            INSERT INTO processed_runs (
                run_id, source, normalized_at, status, total_docs, code_version, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
                source = EXCLUDED.source,
                normalized_at = EXCLUDED.normalized_at,
                status = 'normalized',
                total_docs = EXCLUDED.total_docs,
                code_version = EXCLUDED.code_version,
                updated_at = EXCLUDED.updated_at
        """,
            (
                run_id,
                source,
                normalized_at,
                "normalized",
                total_docs,
                code_version,
                updated_at,
            ),
        )

        conn.commit()
        emit_backlog_event(
            "runs.normalized",
            run_id=run_id,
            source=source,
            total_docs=total_docs,
        )


def claim_run_for_chunking(
    claim_ttl_minutes: int | None = None,
) -> dict[str, Any] | None:
    """
    Claim a run for chunking using SELECT ... FOR UPDATE SKIP LOCKED.

    Args:
        claim_ttl_minutes: TTL for stale claim recovery

    Returns:
        Run record if claimed, None if no runs available
    """
    if claim_ttl_minutes is None:
        claim_ttl_minutes = SETTINGS.BACKLOG_CLAIM_TTL_MINUTES

    hostname = socket.gethostname()
    pid = os.getpid()
    claimed_by = f"{hostname}-{pid}"
    claimed_at = datetime.now(timezone.utc)

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # First, recover stale claims
        stale_threshold = claimed_at - timedelta(minutes=claim_ttl_minutes)
        cursor.execute(
            """
            UPDATE processed_runs
            SET status = 'normalized', claimed_by = NULL, claimed_at = NULL
            WHERE status = 'chunking'
              AND claimed_at < %s
        """,
            (stale_threshold,),
        )

        if cursor.rowcount > 0:
            emit_backlog_event("runs.claim.recovered", count=cursor.rowcount)

        # Claim next available run
        cursor.execute(
            """
            SELECT run_id, source, normalized_at, total_docs
            FROM processed_runs
            WHERE status IN ('normalized', 'reset')
            ORDER BY normalized_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        """
        )

        run = cursor.fetchone()
        if not run:
            return None

        # Mark as chunking
        cursor.execute(
            """
            UPDATE processed_runs
            SET status = 'chunking',
                claimed_by = %s,
                claimed_at = %s,
                chunk_started_at = %s,
                updated_at = %s
            WHERE run_id = %s
        """,
            (claimed_by, claimed_at, claimed_at, claimed_at, run["run_id"]),
        )

        conn.commit()

        run_dict = dict(run)
        emit_backlog_event(
            "runs.claim",
            run_id=run_dict["run_id"],
            phase="chunk",
            claimed_by=claimed_by,
        )

        return run_dict


def mark_chunking_complete(run_id: str, total_chunks: int) -> None:
    """
    Mark a run as chunking complete.

    Args:
        run_id: The run identifier
        total_chunks: Number of chunks created
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        completed_at = datetime.now(timezone.utc)

        cursor.execute(
            """
            UPDATE processed_runs
            SET status = 'chunked',
                chunk_completed_at = %s,
                total_chunks = %s,
                claimed_by = NULL,
                claimed_at = NULL,
                updated_at = %s
            WHERE run_id = %s
        """,
            (completed_at, total_chunks, completed_at, run_id),
        )

        conn.commit()
        emit_backlog_event(
            "runs.complete",
            run_id=run_id,
            phase="chunk",
            total_chunks=total_chunks,
        )


def claim_run_for_embedding(
    claim_ttl_minutes: int | None = None,
) -> dict[str, Any] | None:
    """
    Claim a run for embedding using SELECT ... FOR UPDATE SKIP LOCKED.

    Args:
        claim_ttl_minutes: TTL for stale claim recovery

    Returns:
        Run record if claimed, None if no runs available
    """
    if claim_ttl_minutes is None:
        claim_ttl_minutes = SETTINGS.BACKLOG_CLAIM_TTL_MINUTES

    hostname = socket.gethostname()
    pid = os.getpid()
    claimed_by = f"{hostname}-{pid}"
    claimed_at = datetime.now(timezone.utc)

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # First, recover stale claims
        stale_threshold = claimed_at - timedelta(minutes=claim_ttl_minutes)
        cursor.execute(
            """
            UPDATE processed_runs
            SET status = 'chunked', claimed_by = NULL, claimed_at = NULL
            WHERE status = 'embedding'
              AND claimed_at < %s
        """,
            (stale_threshold,),
        )

        if cursor.rowcount > 0:
            emit_backlog_event("runs.claim.recovered", count=cursor.rowcount)

        # Claim next available run
        cursor.execute(
            """
            SELECT run_id, source, normalized_at, total_docs, total_chunks
            FROM processed_runs
            WHERE status IN ('chunked', 'reset')
            ORDER BY normalized_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        """
        )

        run = cursor.fetchone()
        if not run:
            return None

        # Mark as embedding
        cursor.execute(
            """
            UPDATE processed_runs
            SET status = 'embedding',
                claimed_by = %s,
                claimed_at = %s,
                embed_started_at = %s,
                updated_at = %s
            WHERE run_id = %s
        """,
            (claimed_by, claimed_at, claimed_at, claimed_at, run["run_id"]),
        )

        conn.commit()

        run_dict = dict(run)
        emit_backlog_event(
            "runs.claim",
            run_id=run_dict["run_id"],
            phase="embed",
            claimed_by=claimed_by,
        )

        return run_dict


def mark_embedding_complete(run_id: str, embedded_chunks: int) -> None:
    """
    Mark a run as embedding complete.

    Args:
        run_id: The run identifier
        embedded_chunks: Number of chunks embedded
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        completed_at = datetime.now(timezone.utc)

        cursor.execute(
            """
            UPDATE processed_runs
            SET status = 'embedded',
                embed_completed_at = %s,
                embedded_chunks = %s,
                claimed_by = NULL,
                claimed_at = NULL,
                updated_at = %s
            WHERE run_id = %s
        """,
            (completed_at, embedded_chunks, completed_at, run_id),
        )

        conn.commit()
        emit_backlog_event(
            "runs.complete",
            run_id=run_id,
            phase="embed",
            embedded_chunks=embedded_chunks,
        )


def get_backlog_summary(phase: str) -> dict[str, Any]:
    """
    Get backlog summary for a specific phase.

    Args:
        phase: 'chunk' or 'embed'

    Returns:
        Summary with total, sample run_ids, and date range
    """
    if phase == "chunk":
        status_filter = "('normalized', 'reset')"
    elif phase == "embed":
        status_filter = "('chunked', 'reset')"
    else:
        raise ValueError(f"Invalid phase: {phase}")

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get summary statistics
        cursor.execute(
            f"""
            SELECT
                COUNT(*) as total,
                MIN(normalized_at) as earliest,
                MAX(normalized_at) as latest
            FROM processed_runs
            WHERE status IN {status_filter}
        """
        )

        summary = dict(cursor.fetchone())

        # Get sample run_ids
        cursor.execute(
            f"""
            SELECT run_id
            FROM processed_runs
            WHERE status IN {status_filter}
            ORDER BY normalized_at ASC
            LIMIT 10
        """
        )

        sample_runs = [row["run_id"] for row in cursor.fetchall()]

        summary["sample_run_ids"] = sample_runs
        summary["phase"] = phase

        # Convert datetimes to ISO strings for JSON serialization
        if summary["earliest"]:
            summary["earliest"] = summary["earliest"].isoformat()
        if summary["latest"]:
            summary["latest"] = summary["latest"].isoformat()

        emit_backlog_event("runs.scan.complete", **summary)

        return summary


def reset_runs(
    run_ids: list[str] | None = None,
    scope: str = "processed",
    filters: dict[str, Any] | None = None,
    dry_run: bool = False,
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Reset runs in the backlog.

    Args:
        run_ids: Specific run IDs to reset (None = all matching filters)
        scope: 'processed', 'embeddings', or 'all'
        filters: Additional filters (source, date_from, date_to, limit)
        dry_run: Show what would be reset without doing it
        confirmed: Whether user confirmed the operation

    Returns:
        Reset statistics
    """
    if not confirmed and scope in ("embeddings", "all"):
        raise ValueError("Destructive reset operations require confirmed=True")

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Build WHERE clause and parameters
        where_conditions = []
        params = []

        if run_ids:
            where_conditions.append("run_id = ANY(%s)")
            params.append(run_ids)

        if filters:
            if filters.get("source"):
                where_conditions.append("source = %s")
                params.append(filters["source"])

            if filters.get("date_from"):
                where_conditions.append("normalized_at >= %s")
                params.append(filters["date_from"])

            if filters.get("date_to"):
                where_conditions.append("normalized_at <= %s")
                params.append(filters["date_to"])

        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        limit_clause = f"LIMIT {filters['limit']}" if filters and filters.get("limit") else ""

        if dry_run:
            # Count what would be affected
            cursor.execute(
                f"""
                SELECT COUNT(*) FROM processed_runs
                {where_clause}
                {limit_clause}
            """,
                params,
            )
            reset_count = cursor.fetchone()[0]
        else:
            if scope == "processed":
                # Only reset status and claim fields
                update_params = [datetime.now(timezone.utc), *params]
                cursor.execute(
                    f"""
                    UPDATE processed_runs
                    SET status = 'reset',
                        chunk_started_at = NULL,
                        chunk_completed_at = NULL,
                        embed_started_at = NULL,
                        embed_completed_at = NULL,
                        claimed_by = NULL,
                        claimed_at = NULL,
                        updated_at = %s
                    {where_clause}
                    {limit_clause}
                """,
                    update_params,
                )

            # TODO: Add embeddings and all scope handling when needed
            # This would require integration with the embedding deletion logic

            reset_count = cursor.rowcount
            conn.commit()

        result = {
            "scope": scope,
            "reset_count": reset_count,
            "run_ids": run_ids or "filtered" if filters else "all",
            "dry_run": dry_run,
        }

        emit_backlog_event("runs.reset.complete", **result)

        return result
