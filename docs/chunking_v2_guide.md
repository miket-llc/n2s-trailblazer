# Chunking v2 Guide

## Overview

Chunking v2 addresses token limit violations observed in the original chunker by implementing a guaranteed hard token cap with layered splitting strategy and overlap support.

## Key Features

### Hard Token Cap

- **Guaranteed compliance**: No emitted chunk will ever exceed `hard_max_tokens`
- **Default limit**: 800 tokens (configurable)
- **Fallback protection**: Binary search truncation if all strategies fail

### Layered Splitting Strategy

Chunks are split using this priority order:

1. **Headings** - Uses `section_map` from enrichment when available
1. **Paragraph boundaries** - Double newlines and list breaks
1. **Sentence boundaries** - Simple heuristics (`.!?` + whitespace)
1. **Code fence lines** - Never cuts mid-line, preserves syntax
1. **Table row groups** - Never cuts mid-cell, preserves headers
1. **Token window** - Final fallback with word-level splitting

### Overlap Support

- **Configurable overlap**: Default 60 tokens between split segments
- **Context continuity**: Maintains reading flow across chunk boundaries
- **Smart application**: Only applied when content must be split

### Content-Aware Processing

- **Code blocks**: Preserved with language tags, line-level splitting
- **Tables**: Header preservation, row-group splitting
- **Structured data**: Handles AWS config dumps and similar formats

## CLI Usage

### New Chunking (v2 by default)

```bash
# Use v2 with defaults (800/120/60 tokens)
trailblazer chunk RUN_ID_HERE

# Custom limits with v2
trailblazer chunk RUN_ID_HERE --max-tokens 1000 --overlap-tokens 80

# Use legacy v1 chunker
trailblazer chunk RUN_ID_HERE --v1
```

### Audit Existing Chunks

```bash
# Find all oversize chunks
trailblazer chunk audit --runs-glob 'var/runs/*' --max-tokens 800

# Output: var/chunk_audit/<timestamp>/
#   - oversize.json          # Detailed oversize chunk list
#   - rechunk_targets.txt     # (rid,doc_id) pairs to fix
#   - hist.json              # Token statistics
#   - overview.md            # Human-readable summary
```

### Targeted Re-chunking

```bash
# Re-chunk only problematic documents
trailblazer chunk rechunk \
  --targets-file var/chunk_audit/<TS>/rechunk_targets.txt \
  --max-tokens 800 --min-tokens 120 --overlap-tokens 60

# Output: var/chunk_fix/<timestamp>/
#   - rechunk_summary.json   # Operation summary
#   - skipped_docs.jsonl     # Documents that couldn't be fixed
```

### Verification Workflow

```bash
# 1) Initial audit
trailblazer chunk audit --runs-glob 'var/runs/*' --max-tokens 800

# 2) Fix oversize chunks
trailblazer chunk rechunk \
  --targets-file var/chunk_audit/<TS>/rechunk_targets.txt \
  --max-tokens 800 --min-tokens 120 --overlap-tokens 60

# 3) Verify fixes
trailblazer chunk audit --runs-glob 'var/runs/*' --max-tokens 800
# Should show 0 oversize chunks
```

## Configuration Parameters

### Core Parameters

- `hard_max_tokens` (800): Absolute ceiling, never exceeded
- `min_tokens` (120): Preferred minimum, can go down to 80 when forced
- `overlap_tokens` (60): Overlap when content must be split

### Legacy Parameters (v1 only)

- `max_tokens` (8000): Soft limit with digest fallback
- `target_tokens` (700): Preferred chunk size

## Assurance Enhancements

Chunking v2 extends `chunk_assurance.json` with:

```json
{
  "version": "v2",
  "status": "PASS",
  "tokenCap": {
    "maxTokens": 800,
    "hardMaxTokens": 800,
    "overlapTokens": 60,
    "breaches": {
      "count": 0,
      "examples": []
    }
  },
  "charStats": {
    "min": 45,
    "median": 1205,
    "p95": 3890,
    "max": 4200
  },
  "splitStrategies": {
    "heading": 45,
    "paragraph": 123,
    "sentence": 12,
    "token-window": 3
  }
}
```

### Status Determination

- **PASS**: `breaches.count == 0`
- **FAIL**: Any chunks exceed `hard_max_tokens`

## Error Handling

### Document-Level Skipping

When a document cannot be properly chunked:

- Skip that document only
- Log to `skipped_docs.jsonl`
- Never fail the entire run
- Continue processing other documents

### Fallback Behavior

1. Try layered splitting strategies in order
1. If all fail, apply binary search truncation
1. Emit `force-truncate` event for monitoring
1. Guarantee compliance with hard cap

## Performance Considerations

### Chunking Speed

- v2 is ~10-15% slower due to layered strategy
- Token counting overhead for validation
- Overlap calculation adds processing time

### Memory Usage

- Minimal increase from strategy tracking
- Overlap buffers are small and temporary
- No significant memory impact

## Migration Notes

### Backward Compatibility

- v1 chunking remains available with `--v1` flag
- Existing chunk files remain valid
- No automatic migration required

### Recommended Approach

1. Audit existing chunks to identify problems
1. Use targeted rechunking for oversize documents
1. Switch new runs to v2 (default behavior)
1. Monitor assurance files for breach counts

## Troubleshooting

### Common Issues

**"Still oversize after v2 rechunking"**

- Document may have indivisible content (single giant table cell, etc.)
- Check `skipped_docs.jsonl` for specific reasons
- Consider manual content editing if necessary

**"Too many small chunks"**

- Increase `min_tokens` parameter
- Reduce `overlap_tokens` to minimize overhead
- Check if content has excessive paragraph breaks

**"Performance degradation"**

- v2 is inherently slower due to validation
- Consider running targeted rechunking rather than full corpus
- Monitor token counting overhead in profiling

### Monitoring

Check these files for operational health:

- `chunk_assurance.json` - Look for `status: "FAIL"` or high breach counts
- `skipped_docs.jsonl` - Documents that couldn't be fixed
- Split strategy distribution - Ensure reasonable variety

## Implementation Details

### Split Strategy Recording

Each chunk records how it was created:

- `heading`: Split at heading boundaries
- `paragraph`: Split at paragraph breaks
- `sentence`: Split at sentence boundaries
- `code-fence-lines`: Code block split by lines
- `table-rows`: Table split by row groups
- `token-window`: Fallback word-level splitting
- `no-split`: Fit within limits without splitting
- `force-truncate`: Binary search truncation applied

### Overlap Implementation

- Calculated in tokens, not characters
- Applied only when splitting occurs
- Uses heuristics for word/line/row estimation
- Preserves context across boundaries

### Token Counting

- Uses `tiktoken` for OpenAI models
- Fallback to 4-char-per-token estimation
- Consistent with embedding model expectations
- Validated against recorded counts in audit
