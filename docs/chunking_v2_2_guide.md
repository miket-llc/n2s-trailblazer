# Chunking v2.2: Bottom-End Glue, Coverage, and Verification Guide

## Overview

Chunking v2.2 extends the existing v2 chunker with bottom-end controls, coverage tracking, and comprehensive verification to ensure high-quality chunks suitable for embedding.

## New Features

### Bottom-End Glue Pass

The glue pass merges small chunks to improve semantic coherence while respecting hard token limits:

- **Soft Minimum Tokens** (default: 200): Target minimum after glue pass
- **Hard Minimum Tokens** (default: 80): Absolute minimum for any chunk
- **Orphan Heading Merge**: Automatically merges standalone headings with neighbors
- **Small Tail Merge**: Merges small final chunks when possible

### Coverage Tracking

Every chunk now includes character span information for coverage verification:

- `char_start` and `char_end`: Character positions relative to normalized document
- `token_start` and `token_end`: Token positions (when available)
- Coverage verification ensures ≥99.5% document coverage

### Enhanced Verification

The verification system now checks multiple quality dimensions:

- Token cap compliance (no chunks > `max_tokens`)
- Coverage gaps (missing document portions)
- Traceability completeness (required: `source_system` + (`title` OR `url`))
- Small chunk analysis with reason categorization

## Configuration

### Environment Variables

Add to your `.trailblazer.yaml`:

```yaml
# Chunking v2.2 bottom-end controls
CHUNK_SOFT_MIN_TOKENS: 200    # Target minimum after glue
CHUNK_HARD_MIN_TOKENS: 80     # Absolute minimum for any chunk
CHUNK_HARD_MAX_TOKENS: 800    # Absolute maximum (unchanged)
CHUNK_OVERLAP_TOKENS: 60      # Overlap tokens when splitting
CHUNK_ORPHAN_HEADING_MERGE: true   # Merge orphan headings
CHUNK_SMALL_TAIL_MERGE: true       # Merge small tail chunks
```

### CLI Parameters

All chunking commands now accept v2.2 parameters:

```bash
trailblazer chunk RUN_ID \
  --max-tokens 800 \
  --soft-min-tokens 200 \
  --hard-min-tokens 80 \
  --overlap-tokens 60 \
  --orphan-heading-merge \
  --small-tail-merge
```

## Usage Examples

### Basic v2.2 Chunking

```bash
# Chunk with v2.2 defaults
trailblazer chunk RUN_ID_HERE

# Custom v2.2 parameters
trailblazer chunk RUN_ID_HERE \
  --soft-min-tokens 250 \
  --hard-min-tokens 100 \
  --no-orphan-heading-merge
```

### Verification Workflow

```bash
# 1. Verify chunks after processing
trailblazer chunk verify \
  --runs-glob 'var/runs/*' \
  --max-tokens 800 \
  --soft-min 200 \
  --hard-min 80 \
  --require-traceability true

# 2. If issues found, audit specific problems
trailblazer chunk audit \
  --runs-glob 'var/runs/*' \
  --max-tokens 800

# 3. Re-chunk problematic documents
trailblazer chunk rechunk \
  --targets-file var/chunk_audit/20240119_120000/rechunk_targets.txt \
  --max-tokens 800 \
  --min-tokens 120 \
  --overlap-tokens 60

# 4. Re-verify after fixes
trailblazer chunk verify \
  --runs-glob 'var/runs/*' \
  --max-tokens 800 \
  --soft-min 200 \
  --hard-min 80
```

### Troubleshooting Common Issues

#### Small Chunks Below Hard Minimum

If verification reports chunks below `hard_min_tokens`:

```bash
# Check the reasons in small_chunks.json
cat var/chunk_verify/20240119_120000/small_chunks.json

# Common reasons and solutions:
# - tiny_doc: Source document is very small (acceptable)
# - fence_forced: Code block couldn't be split (acceptable)  
# - table_forced: Table structure prevented splitting (acceptable)
# - tail_small: Small final chunk that couldn't merge (review chunking params)
```

#### Coverage Gaps

If verification reports coverage gaps:

```bash
# Check gap details
cat var/chunk_verify/20240119_120000/gaps.json

# Review the specific documents with gaps
# May indicate issues with text normalization or chunk boundary calculation
```

#### Missing Traceability

If chunks lack required traceability fields:

```bash
# Check missing fields
cat var/chunk_verify/20240119_120000/missing_traceability.json

# Ensure source documents provide:
# - source_system (required)
# - title OR url (at least one required)
```

## Output Files

### Chunk Assurance (per run)

`var/runs/{run_id}/chunk/chunk_assurance.json` now includes:

```json
{
  "bottoms": {
    "softMinTokens": 200,
    "hardMinTokens": 80,
    "pctBelowSoftMin": 5.2,
    "belowSoftMinExamples": ["doc:0003", "doc:0011"],
    "hardMinExceptions": {
      "count": 2,
      "reasons": {
        "tiny_doc": 1,
        "fence_forced": 1,
        "table_forced": 0
      }
    }
  },
  "coverage": {
    "docsWithGaps": 0,
    "avgCoveragePct": 100.0,
    "gapsExamples": []
  }
}
```

### Verification Reports (corpus-wide)

`var/chunk_verify/{timestamp}/` contains:

- `report.json` - Complete verification results
- `report.md` - Human-readable summary
- `breaches.json` - Oversize chunks (if any)
- `small_chunks.json` - Chunks below hard minimum with reasons
- `gaps.json` - Documents with coverage gaps (if any)
- `missing_traceability.json` - Chunks missing required fields (if any)
- `log.out` - Processing log

## Quality Thresholds

### Recommended Settings

For most use cases:

- **soft_min_tokens**: 200 (good semantic coherence)
- **hard_min_tokens**: 80 (absolute floor)
- **hard_max_tokens**: 800 (embedding model limit)
- **overlap_tokens**: 60 (context continuity)

### Conservative Settings

For critical applications requiring maximum quality:

- **soft_min_tokens**: 250
- **hard_min_tokens**: 100
- **hard_max_tokens**: 600
- **overlap_tokens**: 80

### Performance Settings

For faster processing with larger chunks:

- **soft_min_tokens**: 300
- **hard_min_tokens**: 120
- **hard_max_tokens**: 1000
- **overlap_tokens**: 40

## Migration from v2.0/v2.1

Existing chunks remain compatible. To upgrade:

1. **Re-chunk with v2.2**: Apply glue pass and coverage tracking
1. **Verify quality**: Run verification to identify any issues
1. **Fix violations**: Use audit/rechunk workflow for problem documents
1. **Update configs**: Set v2.2 parameters in your configuration

```bash
# Upgrade workflow
trailblazer chunk verify --runs-glob 'var/runs/*' --max-tokens 800 --soft-min 200 --hard-min 80
# Review results and re-chunk as needed
```

## Advanced Usage

### Custom Glue Strategies

Disable specific glue behaviors:

```bash
# Disable orphan heading merging (preserve document structure)
trailblazer chunk RUN_ID --no-orphan-heading-merge

# Disable small tail merging (preserve chunk boundaries)
trailblazer chunk RUN_ID --no-small-tail-merge

# Minimal glue (only apply hard minimum enforcement)
trailblazer chunk RUN_ID --soft-min-tokens 0
```

### Integration with Embedding Pipeline

v2.2 chunks work seamlessly with existing embedding workflows:

```bash
# Standard pipeline with v2.2 chunking
trailblazer run --phases ingest,normalize,enrich,chunk,embed

# Verify before embedding
trailblazer chunk verify --runs-glob 'var/runs/*' --max-tokens 800
trailblazer embed plan-preflight --plan-file var/ready_runs.txt
```

## Monitoring and Observability

### Key Metrics

Monitor these v2.2-specific metrics:

- **Glue rate**: Percentage of chunks modified by glue pass
- **Coverage quality**: Average document coverage percentage
- **Small chunk rate**: Percentage below soft minimum
- **Exception rate**: Hard minimum violations by category

### Alerting Thresholds

Set alerts for:

- Coverage < 99% (investigate normalization issues)
- Small chunks > 20% (review chunking parameters)
- Hard minimum exceptions > 5% (check document quality)

This completes the comprehensive guide for Chunking v2.2. The new bottom-end controls ensure higher semantic quality while maintaining the hard token guarantees that make chunks suitable for embedding.
