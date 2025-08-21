"""
Embed manifest functionality for tracking embedding state and detecting changes.

This module provides:
- Manifest creation after successful embedding
- Diff calculation between current state and previous manifests
- Change detection for conditional re-embedding
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tiktoken  # type: ignore
except ImportError:
    tiktoken = None  # type: ignore

from ....core.logging import log


def get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "unknown"


def get_tokenizer_info() -> dict[str, str]:
    """Get tokenizer name and version."""
    try:
        if tiktoken is not None:
            return {"name": "tiktoken", "version": tiktoken.__version__}
    except (AttributeError, NameError):
        pass

    return {"name": "unknown", "version": "unknown"}


def get_component_versions() -> dict[str, str]:
    """Get enricher and chunker versions."""
    # These versions should be bumped when the algorithms change
    return {
        "enricherVersion": "v1",  # From DocumentEnricher.enrichment_version
        "chunkerVersion": "v1",  # Stable chunking algorithm
    }


def compute_chunk_set_hash(chunks: list[dict[str, Any]]) -> str:
    """
    Compute SHA256 hash over ordered chunk data.

    Args:
        chunks: List of chunk dictionaries with chunk_id, token_count, content_hash

    Returns:
        SHA256 hex digest of the chunk set
    """
    # Sort chunks by chunk_id for deterministic ordering
    sorted_chunks = sorted(chunks, key=lambda x: x.get("chunk_id", ""))

    # Create stable representation for hashing
    chunk_tuples = []
    for chunk in sorted_chunks:
        chunk_tuple = (
            chunk.get("chunk_id", ""),
            chunk.get("token_count", 0),
            chunk.get("content_hash", ""),
        )
        chunk_tuples.append(chunk_tuple)

    # Create canonical JSON representation
    canonical_json = json.dumps(chunk_tuples, sort_keys=True, ensure_ascii=False)

    # Compute SHA256
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def get_doc_fingerprints_from_enrich(run_id: str) -> list[str]:
    """
    Get document fingerprints from enrich phase for docs actually embedded.

    Args:
        run_id: The run ID

    Returns:
        List of document fingerprint hashes (doc field from fingerprints.jsonl)
    """
    from ....core.paths import runs

    fingerprints_file = runs() / run_id / "enrich" / "fingerprints.jsonl"
    if not fingerprints_file.exists():
        log.warning("embed.manifest.no_fingerprints", run_id=run_id)
        return []

    doc_fingerprints = []
    try:
        with open(fingerprints_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    fingerprint_rec = json.loads(line.strip())
                    # Extract the 'doc' field from the fingerprint record
                    if "fingerprint_sha256" in fingerprint_rec:
                        doc_fingerprints.append(fingerprint_rec["fingerprint_sha256"])
    except Exception as e:
        log.error(
            "embed.manifest.fingerprints_read_error",
            run_id=run_id,
            error=str(e),
        )
        return []

    return doc_fingerprints


def get_chunk_config_from_run(run_id: str) -> dict[str, Any]:
    """
    Get chunk configuration from enriched documents.

    Args:
        run_id: The run ID

    Returns:
        Dictionary with maxTokens, minTokens, preferHeadings
    """
    from ....core.paths import runs

    enriched_file = runs() / run_id / "enrich" / "enriched.jsonl"
    if not enriched_file.exists():
        log.warning("embed.manifest.no_enriched", run_id=run_id)
        return {"maxTokens": 800, "minTokens": 120, "preferHeadings": True}

    try:
        # Read first document to get chunk hints
        with open(enriched_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    doc = json.loads(line.strip())
                    chunk_hints = doc.get("chunk_hints", {})
                    return {
                        "maxTokens": chunk_hints.get("maxTokens", 800),
                        "minTokens": chunk_hints.get("minTokens", 120),
                        "preferHeadings": chunk_hints.get("preferHeadings", True),
                    }
    except Exception as e:
        log.error("embed.manifest.chunk_config_error", run_id=run_id, error=str(e))

    # Default configuration
    return {"maxTokens": 800, "minTokens": 120, "preferHeadings": True}


def load_chunks_for_manifest(run_id: str) -> list[dict[str, Any]]:
    """
    Load chunk data for manifest generation.

    Args:
        run_id: The run ID

    Returns:
        List of chunk dictionaries with chunk_id, token_count, content_hash
    """
    from ....core.paths import runs

    chunks_file = runs() / run_id / "chunk" / "chunks.ndjson"
    if not chunks_file.exists():
        log.warning("embed.manifest.no_chunks", run_id=run_id)
        return []

    chunks = []
    try:
        with open(chunks_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    chunk = json.loads(line.strip())
                    chunks.append(
                        {
                            "chunk_id": chunk.get("chunk_id", ""),
                            "token_count": chunk.get("token_count", 0),
                            "content_hash": chunk.get("content_hash", ""),
                        }
                    )
    except Exception as e:
        log.error("embed.manifest.chunks_read_error", run_id=run_id, error=str(e))
        return []

    return chunks


def create_embed_manifest(
    run_id: str,
    provider: str,
    model: str,
    dimension: int,
    chunks_embedded: int = 0,
) -> dict[str, Any]:
    """
    Create embed manifest for a successful embedding run.

    Args:
        run_id: The run ID
        provider: Embedding provider name
        model: Model name
        dimension: Embedding dimension
        chunks_embedded: Number of chunks actually embedded

    Returns:
        Manifest dictionary
    """
    # Get all required data
    git_commit = get_git_commit()
    tokenizer_info = get_tokenizer_info()
    component_versions = get_component_versions()
    doc_fingerprints = get_doc_fingerprints_from_enrich(run_id)
    chunk_config = get_chunk_config_from_run(run_id)
    chunks = load_chunks_for_manifest(run_id)
    chunk_set_hash = compute_chunk_set_hash(chunks)

    manifest = {
        "runId": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gitCommit": git_commit,
        "provider": provider,
        "model": model,
        "dimension": dimension,
        "tokenizer": tokenizer_info,
        "enricherVersion": component_versions["enricherVersion"],
        "chunkerVersion": component_versions["chunkerVersion"],
        "chunkConfig": chunk_config,
        "docFingerprints": doc_fingerprints,
        "chunkSetHash": chunk_set_hash,
        "chunksEmbedded": chunks_embedded,
        "totalChunks": len(chunks),
    }

    return manifest


def write_embed_manifest(
    run_id: str,
    provider: str,
    model: str,
    dimension: int,
    chunks_embedded: int = 0,
) -> Path:
    """
    Write embed manifest to var/runs/<RID>/embed/manifest.json.

    Args:
        run_id: The run ID
        provider: Embedding provider name
        model: Model name
        dimension: Embedding dimension
        chunks_embedded: Number of chunks actually embedded

    Returns:
        Path to the written manifest file
    """
    from ....core.paths import runs

    manifest = create_embed_manifest(run_id, provider, model, dimension, chunks_embedded)

    # Ensure embed directory exists
    embed_dir = runs() / run_id / "embed"
    embed_dir.mkdir(parents=True, exist_ok=True)

    # Write manifest
    manifest_file = embed_dir / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    log.info(
        "embed.manifest.written",
        run_id=run_id,
        manifest_file=str(manifest_file),
    )

    return manifest_file


def find_last_manifest(run_id: str) -> Path | None:
    """
    Find the most recent manifest for a run.

    Args:
        run_id: The run ID

    Returns:
        Path to the most recent manifest, or None if not found
    """
    from ....core.paths import runs

    manifest_file = runs() / run_id / "embed" / "manifest.json"
    if manifest_file.exists():
        return manifest_file

    return None


def load_manifest(manifest_path: Path) -> dict[str, Any] | None:
    """
    Load manifest from file.

    Args:
        manifest_path: Path to manifest file

    Returns:
        Manifest dictionary, or None if loading failed
    """
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("embed.manifest.load_error", path=str(manifest_path), error=str(e))
        return None


def compute_current_state(run_id: str, provider: str, model: str, dimension: int) -> dict[str, Any]:
    """
    Compute current embedding state for comparison.

    Args:
        run_id: The run ID
        provider: Embedding provider name
        model: Model name
        dimension: Embedding dimension

    Returns:
        Current state dictionary (same structure as manifest)
    """
    return create_embed_manifest(run_id, provider, model, dimension)


ChangeReason = str

# Change reason constants
CONTENT_CHANGE = "CONTENT_CHANGE"
PROVIDER_CHANGE = "PROVIDER_CHANGE"
MODEL_CHANGE = "MODEL_CHANGE"
DIMENSION_CHANGE = "DIMENSION_CHANGE"
TOKENIZER_CHANGE = "TOKENIZER_CHANGE"
CHUNKER_CHANGE = "CHUNKER_CHANGE"
CHUNK_CONFIG_CHANGE = "CHUNK_CONFIG_CHANGE"


def compare_manifests(current: dict[str, Any], previous: dict[str, Any]) -> tuple[bool, list[ChangeReason]]:
    """
    Compare current state with previous manifest to detect changes.

    Args:
        current: Current state dictionary
        previous: Previous manifest dictionary

    Returns:
        Tuple of (has_changes, list_of_change_reasons)
    """
    reasons = []

    # Check provider changes
    if current.get("provider") != previous.get("provider"):
        reasons.append(PROVIDER_CHANGE)

    # Check model changes
    if current.get("model") != previous.get("model"):
        reasons.append(MODEL_CHANGE)

    # Check dimension changes
    if current.get("dimension") != previous.get("dimension"):
        reasons.append(DIMENSION_CHANGE)

    # Check tokenizer changes
    current_tokenizer = current.get("tokenizer", {})
    previous_tokenizer = previous.get("tokenizer", {})
    if current_tokenizer.get("name") != previous_tokenizer.get("name") or current_tokenizer.get(
        "version"
    ) != previous_tokenizer.get("version"):
        reasons.append(TOKENIZER_CHANGE)

    # Check chunker version changes
    if current.get("chunkerVersion") != previous.get("chunkerVersion"):
        reasons.append(CHUNKER_CHANGE)

    # Check chunk config changes
    current_config = current.get("chunkConfig", {})
    previous_config = previous.get("chunkConfig", {})
    if current_config != previous_config:
        reasons.append(CHUNK_CONFIG_CHANGE)

    # Check content changes (via chunkSetHash)
    if current.get("chunkSetHash") != previous.get("chunkSetHash"):
        reasons.append(CONTENT_CHANGE)

    has_changes = len(reasons) > 0
    return has_changes, reasons


def create_diff_report(
    run_id: str,
    current: dict[str, Any],
    previous: dict[str, Any],
    has_changes: bool,
    reasons: list[ChangeReason],
) -> dict[str, Any]:
    """
    Create a diff report comparing current state with previous manifest.

    Args:
        run_id: The run ID
        current: Current state dictionary
        previous: Previous manifest dictionary
        has_changes: Whether changes were detected
        reasons: List of change reasons

    Returns:
        Diff report dictionary
    """
    return {
        "runId": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "changed": has_changes,
        "reasons": reasons,
        "current": {
            "provider": current.get("provider"),
            "model": current.get("model"),
            "dimension": current.get("dimension"),
            "tokenizer": current.get("tokenizer"),
            "chunkerVersion": current.get("chunkerVersion"),
            "chunkConfig": current.get("chunkConfig"),
            "chunkSetHash": current.get("chunkSetHash"),
            "totalChunks": current.get("totalChunks"),
        },
        "previous": {
            "provider": previous.get("provider"),
            "model": previous.get("model"),
            "dimension": previous.get("dimension"),
            "tokenizer": previous.get("tokenizer"),
            "chunkerVersion": previous.get("chunkerVersion"),
            "chunkConfig": previous.get("chunkConfig"),
            "chunkSetHash": previous.get("chunkSetHash"),
            "totalChunks": previous.get("totalChunks"),
            "timestamp": previous.get("timestamp"),
        },
    }


def format_diff_as_markdown(diff_report: dict[str, Any]) -> str:
    """
    Format diff report as Markdown.

    Args:
        diff_report: Diff report dictionary

    Returns:
        Markdown-formatted diff report
    """
    lines = []
    lines.append(f"# Embed Diff Report: {diff_report['runId']}")
    lines.append("")
    lines.append(f"**Timestamp:** {diff_report['timestamp']}")
    lines.append(f"**Changed:** {diff_report['changed']}")

    if diff_report["reasons"]:
        lines.append(f"**Reasons:** {', '.join(diff_report['reasons'])}")

    lines.append("")
    lines.append("## Current State")
    current = diff_report["current"]
    lines.append(f"- **Provider:** {current['provider']}")
    lines.append(f"- **Model:** {current['model']}")
    lines.append(f"- **Dimension:** {current['dimension']}")
    lines.append(f"- **Tokenizer:** {current['tokenizer']['name']} v{current['tokenizer']['version']}")
    lines.append(f"- **Chunker Version:** {current['chunkerVersion']}")
    lines.append(f"- **Chunk Config:** {json.dumps(current['chunkConfig'])}")
    lines.append(f"- **Chunk Set Hash:** {current['chunkSetHash'][:12]}...")
    lines.append(f"- **Total Chunks:** {current['totalChunks']}")

    lines.append("")
    lines.append("## Previous State")
    previous = diff_report["previous"]
    lines.append(f"- **Provider:** {previous['provider']}")
    lines.append(f"- **Model:** {previous['model']}")
    lines.append(f"- **Dimension:** {previous['dimension']}")
    lines.append(f"- **Tokenizer:** {previous['tokenizer']['name']} v{previous['tokenizer']['version']}")
    lines.append(f"- **Chunker Version:** {previous['chunkerVersion']}")
    lines.append(f"- **Chunk Config:** {json.dumps(previous['chunkConfig'])}")
    lines.append(f"- **Chunk Set Hash:** {previous['chunkSetHash'][:12]}...")
    lines.append(f"- **Total Chunks:** {previous['totalChunks']}")
    lines.append(f"- **Timestamp:** {previous['timestamp']}")

    return "\n".join(lines)
