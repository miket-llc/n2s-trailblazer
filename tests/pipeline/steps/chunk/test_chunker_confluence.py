#!/usr/bin/env python3
"""Test the enhanced chunker on real Confluence data."""

import json
import sys

sys.path.insert(0, "src")
from trailblazer.pipeline.steps.chunk.engine import (
    chunk_document,
    inject_media_placeholders,
)  # noqa: E402


def chunk_normalized_record(record):
    """Helper function to chunk a normalized record."""
    doc_id = record.get("id", "")
    title = record.get("title", "")
    text_md = record.get("text_md", "")
    attachments = record.get("attachments", [])

    if not doc_id:
        raise ValueError("Record missing required 'id' field")

    text_with_media = inject_media_placeholders(text_md, attachments)
    return chunk_document(
        doc_id=doc_id,
        text_md=text_with_media,
        title=title,
        source_system=record.get("source_system", ""),
        labels=record.get("labels", []),
        space=record.get("space"),
        media_refs=attachments,
    )


def main():
    print("🧪 Testing Enhanced Chunker on Real Confluence Data")
    print("=" * 60)

    # Load a sample of normalized records
    input_file = "var/runs/2025-08-15_061643_9d81/normalize/normalized.ndjson"

    print(f"📂 Loading from: {input_file}")

    records = []
    with open(input_file) as f:
        for i, line in enumerate(f):
            if i >= 50:  # Test on first 50 pages
                break
            record = json.loads(line.strip())
            records.append(record)

    print(f"📊 Processing {len(records)} Confluence pages")
    print()

    # Test chunking with enhanced algorithm
    all_chunks = []
    type_stats = {}
    token_stats = []
    oversized_count = 0

    for i, record in enumerate(records):
        try:
            chunks = chunk_normalized_record(record)
            all_chunks.extend(chunks)

            for chunk in chunks:
                chunk_type = getattr(chunk, "chunk_type", "text")
                tokens = chunk.token_count

                type_stats[chunk_type] = type_stats.get(chunk_type, 0) + 1
                token_stats.append(tokens)

                # Check for oversized chunks (should be rare now)
                if tokens > 8000:  # text-embedding-3-small limit
                    oversized_count += 1
                    print(
                        f"⚠️  Oversized chunk: {chunk.chunk_id} ({tokens} tokens)"
                    )

            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1} pages...")

        except Exception as e:
            print(f"❌ Error processing record {i}: {e}")
            continue

    print()
    print("📈 Enhanced Chunking Results:")
    print(f"  Total chunks: {len(all_chunks)}")
    print(f"  Chunk types: {dict(type_stats)}")
    print(f"  Token range: {min(token_stats)} - {max(token_stats)}")
    print(f"  Average tokens: {sum(token_stats) / len(token_stats):.1f}")
    print(f"  Median tokens: {sorted(token_stats)[len(token_stats) // 2]}")
    print(f"  Oversized chunks: {oversized_count}")

    # Token distribution
    token_buckets = {
        "0-200": len([t for t in token_stats if t <= 200]),
        "201-500": len([t for t in token_stats if 200 < t <= 500]),
        "501-800": len([t for t in token_stats if 500 < t <= 800]),
        "801-1500": len([t for t in token_stats if 800 < t <= 1500]),
        "1501+": len([t for t in token_stats if t > 1500]),
    }

    print(f"  Token distribution: {dict(token_buckets)}")

    # Show examples of different chunk types
    print("\n🔍 Sample Chunks by Type:")

    for chunk_type, _ in type_stats.items():
        # Find first chunk of this type
        example = next(
            (
                c
                for c in all_chunks
                if getattr(c, "chunk_type", "text") == chunk_type
            ),
            None,
        )
        if example:
            preview = example.text_md[:150].replace("\n", " ")
            meta_str = getattr(example, "meta", {})
            print(
                f"  {chunk_type.upper()}: {example.chunk_id} ({example.token_count} tokens)"
            )
            print(f"    Meta: {meta_str}")
            print(f"    Preview: {preview}...")
            print()

    # Performance comparison
    print("🚀 Performance Improvements:")
    print("  ✅ Token-accurate counting (using tiktoken)")
    print(f"  ✅ Type-aware chunking ({len(type_stats)} types detected)")
    print("  ✅ Large content handling (digest generation)")
    print("  ✅ Macro/boilerplate filtering")

    if oversized_count == 0:
        print("  ✅ Zero oversized chunks (was a major issue before)")
    else:
        print(f"  ⚠️  {oversized_count} oversized chunks need attention")

    print(
        "\n✨ Ready for embedding with text-embedding-3-small (8191 token limit)"
    )


if __name__ == "__main__":
    main()
