# N2S/Ellucian Expected Phrases Implementation Summary

## Overview

This document summarizes the implementation of changes to raise the "Expected Phrases" metric to ≥85% for N2S/Ellucian queries without re-embedding, by expanding process concept groups, adding doc-anchor hints, and adding an optional retrieval space whitelist.

## Changes Implemented

### 1. Process Concept Groups (Process Language)

**File: `prompts/qa/expectations/concepts.yaml`**

- Added `process_groups` section with N2S-specific process terminology
- Added `process_require_by_query` mapping for N2S queries
- Groups include: runbook_process, capability_driven_process, plan_stage_process, testing_strategy_process, continuous_testing_process, data_migration_process, integration_patterns_process, governance_process, sprint0_process, deploy_cutover_process, configuration_process

**File: `src/trailblazer/qa/expect.py`**

- Added minimal stemming for -ing/-ed suffixes
- Added STOPWORDS = {"experience", "solution", "issue"} to cut noise
- Implemented N-of-M concept scoring: query passes concept stage if at least 2 groups from its assigned set are present in packed contexts
- Added `expect_profile` parameter to support different expectation profiles
- Updated concept scoring to use process groups for N2S profile

### 2. Doc Anchors

**File: `prompts/qa/expectations/anchors.yaml`**

- Added `ask_n2s_*` blocks for N2S-specific queries
- Anchors reward the right pages (e.g., "Discovery Workshops" & "Sprint-0/AAW")
- Slug extractor lowercases and converts +/spaces to -

**File: `src/trailblazer/qa/expect.py`**

- Enhanced doc_slug function to handle Confluence URLs with plus signs
- Updated expectation evaluation to use N2S-specific anchors when `expect_profile="n2s"`

### 3. Retriever Space Scoping

**File: `src/trailblazer/retrieval/dense.py`**

- Added optional `space_whitelist` parameter to `search_postgres` method
- Added SQL predicate: `d.space_key = ANY(:space_whitelist)` when provided
- Default: no filter (maintains existing behavior)
- Maintained existing `ce.dimension = 1536` guard

**File: `src/trailblazer/qa/retrieval.py`**

- Added `space_whitelist` parameter to `run_retrieval_qa` and `run_single_query` functions
- Updated configuration record to include space_whitelist

### 4. CLI Integration

**File: `scripts/run_qa_retrieval.py`**

- Added `--expect-profile n2s` flag to use N2S anchors and process groups
- Added `--space-whitelist` CLI arg (comma-separated or space-separated)
- Added `--n2s-strict` flag that automatically sets `--expect-profile n2s` and `--space-whitelist MTDLANDTL`
- Updated script to pass all new parameters to the QA harness

### 5. Expectation Profile Support

**File: `src/trailblazer/qa/harness.py`**

- Added `expect_profile` parameter to `evaluate_expectations` function
- Updated function to pass profile to expectation evaluation

## Test Coverage

### New Test Files Created

1. **`tests/qa/test_process_groups_match.py`** - Tests process groups matching with hyphen/stem variants
1. **`tests/qa/test_space_whitelist_filter.py`** - Tests space whitelist filtering functionality
1. **`tests/qa/test_anchors_slug_extraction.py`** - Tests anchors slug extraction with special characters

### Test Results

- All 78 QA tests passing
- New functionality thoroughly tested
- Edge cases covered (hyphen variants, stemming, stopwords, space filtering)

## Usage Examples

### Basic N2S Profile Usage

```bash
python scripts/run_qa_retrieval.py \
  --queries-file prompts/qa/queries_n2s.yaml \
  --budgets 1500,4000,6000 \
  --expect-mode doc+concept \
  --expect-threshold 0.7 \
  --expect-profile n2s
```

### N2S Strict Mode (Recommended)

```bash
python scripts/run_qa_retrieval.py \
  --queries-file prompts/qa/queries_n2s.yaml \
  --budgets 1500,4000,6000 \
  --expect-mode doc+concept \
  --expect-threshold 0.7 \
  --n2s-strict
```

### Custom Space Whitelist

```bash
python scripts/run_qa_retrieval.py \
  --queries-file prompts/qa/queries_n2s.yaml \
  --budgets 1500,4000,6000 \
  --expect-mode doc+concept \
  --expect-threshold 0.7 \
  --expect-profile n2s \
  --space-whitelist MTDLANDTL,N2S,DEVELOPMENT
```

## Key Benefits

### 1. Process Language Coverage

- **Before**: Domain lexicon only covered product terms (Ellucian, FGAC, VBS, etc.)
- **After**: Process groups cover N2S methodology ("runbook", "cutover", "testing strategy", "capability-driven")

### 2. Document Anchoring

- **Before**: Generic concept matching that could miss N2S-specific documents
- **After**: N2S-specific anchors ensure right pages are rewarded (e.g., "Discovery Workshops", "Sprint-0")

### 3. Space Filtering

- **Before**: All content mixed together, PESD/PD docs could look "tech" but aren't N2S process
- **After**: Optional space whitelist reduces false positives from non-N2S content

### 4. N-of-M Scoring

- **Before**: All concept groups had to match (AND logic)
- **After**: At least 2 groups must match (N-of-M logic), more flexible for process language

## Guardrails Maintained

✅ **No changes to embedding code or schema**
✅ **EventEmitter logs preserved**
✅ **Dimension==1536 guard maintained**
✅ **Default behavior unchanged unless flags passed**
✅ **All new behavior flagged and OFF by default**

## Expected Impact

The implementation should move the "Expected Phrases" metric to ≥85% because:

1. **Anchors reward the right pages** - Independent of exact wording, rewards N2S-specific documents
1. **Process groups reward the right language** - Covers N2S methodology that truly differentiates from generic tech content
1. **Space whitelist reduces false positives** - Filters out PESD/PD/CS/RA content that looks "tech" but isn't N2S process
1. **N-of-M scoring is more flexible** - Allows for natural language variation in process descriptions

## Next Steps

1. **Run the full QA harness** with the new flags to verify metric improvement
1. **Monitor results** in `var/retrieval_qc/<TS>/readiness.json`
1. **Verify Expected Phrases ≥85%** with Traceability/Diversity/Duplication unchanged
1. **Commit changes** with message: `qa(expect): add process concept groups + anchors; optional space whitelist for N2S; N-of-M concept scoring; tests + docs`
