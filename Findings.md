# EMBED Rebuild Findings

**Analysis Date:** 2025-01-27  
**Scope:** Preflight, Plan Aggregator, EventEmitter, Embed Path, Plan Parsing

## 🚨 Critical Issues Found

### ❌ 1. EventEmitter Not Used Consistently in Preflight/Embed
- **src/trailblazer/pipeline/steps/embed/preflight.py:167,267**: Uses `emit_event()` but inconsistently
- **src/trailblazer/pipeline/steps/embed/loader.py**: Uses EventEmitter context manager properly 
- **Issue**: Preflight should use EventEmitter context manager for proper progress tracking

### ❌ 2. Run-Level QUALITY_GATE Still Used (src/trailblazer/pipeline/steps/embed/preflight.py)
- **Line 206**: `reasons.append("QUALITY_GATE")` - BLOCKS entire runs
- **Line 205**: `if quality_hard_gate and below_threshold_pct > max_below_threshold_pct:`
- **Issue**: Violates requirement that runs should only be BLOCKED for structural reasons or EMBEDDABLE_DOCS=0

### ❌ 3. Embed Loader Missing Skiplist Honor (src/trailblazer/pipeline/steps/embed/loader.py)
- **Lines 287-300**: Loads skiplist but filtering logic is incomplete
- **Issue**: Code reads `doc_skiplist.json` but doesn't properly filter chunks by skipped doc_ids

### ❌ 4. Plural `--dimensions` Still Used (src/trailblazer/cli/main.py)
- **Lines 3185, 3187**: Still using `dimensions` (plural) instead of `dimension`
- **Line 2710**: Legacy script generation uses `"${EMBED_DIMENSIONS:-1536}"`
- **Issue**: Violates requirement to use singular `--dimension` everywhere

### ❌ 5. Subprocess Usage in CLI (src/trailblazer/cli/main.py)
- **Lines 1568, 1823, 1861, 1934, 2722, 2794**: Multiple subprocess calls
- **Lines 2539**: `os.system("clear")` usage
- **Issue**: Violates requirement of "No subprocess, os.system, pexpect, pty, shlex workarounds"

### ❌ 6. Plan Parsing Inconsistency (src/trailblazer/pipeline/steps/embed/preflight.py)
- **Lines 325-360**: Plan parsing supports both formats but has edge cases
- **Issue**: Line parsing could fail on malformed input, needs robust error handling

## ✅ Good Patterns Found

### ✅ 1. Embed Guards Against On-the-Fly Chunking
- **src/trailblazer/pipeline/steps/embed/loader.py:37-53**: Proper validation against chunk imports
- **Lines 55-85**: Validates materialized chunks exist before proceeding

### ✅ 2. EventEmitter Schema (src/trailblazer/obs/events.py)
- **Lines 33-68**: Well-defined ObservabilityEvent schema with all required fields
- **Lines 314-378**: Free function `emit_event()` provides backward compatibility

### ✅ 3. Plan-Preflight Output Structure (src/trailblazer/pipeline/steps/embed/preflight.py)
- **Lines 474-568**: Comprehensive output bundle with JSON, CSV, MD, ready.txt, blocked.txt
- **Lines 550-559**: Proper ready.txt format using `var/runs/<RID>` paths

## 🔧 Fix Plan

### Phase 0: Analysis Complete ✓

### Phase 1: Purge Bad Preflight Artifacts
1. **Add `trailblazer embed clean-preflight` CLI command**
2. **Scan for bad bundles** with QUALITY_GATE reasons or count mismatches
3. **Archive (not delete)** bad bundles to `var/archive/bad_plan_preflight/<TS>/`

### Phase 2: Fix Preflight & Plan-Preflight (Advisory Quality)
1. **Remove run-level QUALITY_GATE logic** - only use for advisory, never block runs
2. **READY condition**: `embeddable_docs >= min_embed_docs` + artifacts OK
3. **BLOCKED reasons**: Only structural (MISSING_ENRICH, MISSING_CHUNKS, TOKENIZER_MISSING, CONFIG_INVALID, EMBEDDABLE_DOCS=0)
4. **Quality advisory**: Write to preflight.json but never block

### Phase 3: Fix Embed Loader End-to-End
1. **Honor skiplist**: Properly filter chunks by skipped doc_ids from `preflight/doc_skiplist.json`
2. **Document bootstrap**: Create minimal Document records when enriched.jsonl missing
3. **Hard guards**: Fail fast on missing chunks.ndjson or dimension mismatches
4. **Transaction safety**: Proper rollback + EventEmitter error handling

### Phase 4: Script Audit & Legacy Removal
1. **Add `trailblazer admin script-audit` command**
2. **Detect forbidden patterns**: `--dimensions`, embed-time chunking, deprecated paths
3. **Remove/upgrade scripts**: Move to `scripts/_legacy/` or rewrite as thin CLI wrappers

### Phase 5: EventEmitter Consistency
1. **Wrap preflight with EventEmitter context manager**
2. **Update progress JSON atomically** in var/progress/
3. **Standardize event emission** across all embed operations

### Phase 6: Singular `--dimension` Everywhere
1. **Replace `--dimensions` with `--dimension`** in CLI
2. **Update script generation** to use singular form
3. **Runtime dimension validation** before DB operations

## Expected Outcomes

- **READY count**: 1,780 runs (±0) after preflight rebuild
- **BLOCKED reasons**: Only structural or EMBEDDABLE_DOCS=0, no QUALITY_GATE
- **Embed operations**: Honor skiplists, proper DB inserts, no 0-insert failures
- **Script compliance**: All scripts use Python CLI delegation, no legacy patterns
- **Event consistency**: Uniform EventEmitter usage with proper progress tracking
