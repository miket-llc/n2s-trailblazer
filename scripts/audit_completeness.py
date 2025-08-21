#!/usr/bin/env python3
"""
Audit embedding completeness - find any missing data and fill gaps.
Ground truth = chunks.ndjson files on disk.
"""

import json
from pathlib import Path

import psycopg2

db_url = "postgresql://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer"


def audit_completeness():
    """Find all chunks on disk vs embeddings in database."""

    # Find all chunks files on disk
    chunks_on_disk = {}
    runs_dir = Path("var/runs")

    print("🔍 Scanning disk for chunks...")
    for run_dir in runs_dir.iterdir():
        if run_dir.is_dir():
            chunks_file = run_dir / "chunk" / "chunks.ndjson"
            if chunks_file.exists():
                chunk_count = 0
                chunk_ids = []
                try:
                    with open(chunks_file) as f:
                        for line in f:
                            if line.strip():
                                chunk = json.loads(line.strip())
                                chunk_ids.append(chunk["chunk_id"])
                                chunk_count += 1
                    chunks_on_disk[run_dir.name] = {
                        "count": chunk_count,
                        "chunk_ids": set(chunk_ids),
                    }
                except Exception as e:
                    print(f"❌ Error reading {chunks_file}: {e}")

    print(f"📊 Found {len(chunks_on_disk)} runs with chunks on disk")
    total_chunks_on_disk = sum(data["count"] for data in chunks_on_disk.values())
    print(f"📊 Total chunks on disk: {total_chunks_on_disk:,}")

    # Check what's in the database
    print("\n🔍 Checking database...")
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # Get all embedded chunk_ids
    cur.execute("SELECT chunk_id FROM chunk_embeddings WHERE provider='openai'")
    embedded_chunk_ids = set(row[0] for row in cur.fetchall())

    print(f"📊 Embedded chunks in database: {len(embedded_chunk_ids):,}")

    # Find missing chunks
    all_disk_chunk_ids = set()
    for run_data in chunks_on_disk.values():
        all_disk_chunk_ids.update(run_data["chunk_ids"])

    missing_chunk_ids = all_disk_chunk_ids - embedded_chunk_ids
    print(f"❌ Missing embeddings: {len(missing_chunk_ids):,}")

    # Find runs with missing chunks
    runs_with_gaps = []
    for run_id, run_data in chunks_on_disk.items():
        missing_in_run = run_data["chunk_ids"] - embedded_chunk_ids
        if missing_in_run:
            runs_with_gaps.append(
                {
                    "run_id": run_id,
                    "total_chunks": run_data["count"],
                    "missing_chunks": len(missing_in_run),
                    "completion_pct": ((run_data["count"] - len(missing_in_run)) / run_data["count"]) * 100,
                }
            )

    runs_with_gaps.sort(key=lambda x: x["missing_chunks"], reverse=True)

    print(f"\n📋 Runs with missing embeddings: {len(runs_with_gaps)}")
    for run_info in runs_with_gaps[:10]:  # Show top 10
        print(
            f"  {run_info['run_id']}: {run_info['missing_chunks']}/{run_info['total_chunks']} missing ({run_info['completion_pct']:.1f}% complete)"
        )

    if len(runs_with_gaps) > 10:
        print(f"  ... and {len(runs_with_gaps) - 10} more")

    # Summary
    print("\n📊 COMPLETENESS AUDIT:")
    print(f"  Chunks on disk: {total_chunks_on_disk:,}")
    print(f"  Chunks embedded: {len(embedded_chunk_ids):,}")
    print(f"  Missing: {len(missing_chunk_ids):,}")
    print(f"  Completion: {(len(embedded_chunk_ids) / total_chunks_on_disk) * 100:.1f}%")

    # Generate fill-gaps script
    if runs_with_gaps:
        print("\n🔧 To fill gaps, run:")
        print("source .venv/bin/activate")
        print('export OPENAI_API_KEY="your-key"')
        print(f'export TRAILBLAZER_DB_URL="{db_url}"')
        for run_info in runs_with_gaps:
            print(f"trailblazer embed run {run_info['run_id']}")

    cur.close()
    conn.close()

    return {
        "total_on_disk": total_chunks_on_disk,
        "total_embedded": len(embedded_chunk_ids),
        "missing": len(missing_chunk_ids),
        "runs_with_gaps": len(runs_with_gaps),
    }


if __name__ == "__main__":
    audit_completeness()
