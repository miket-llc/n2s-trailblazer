# PROMPT 014 — Ingest & Normalize Stabilization + Test Fixes (Confluence & DITA)

**Branch policy**: Push directly to main (no feature branches)\
**Status**: ✅ COMPLETED

## What Was Done

### 0. Shared Guardrails Update ✅

- Updated `prompts/000_shared_guardrails.md` with new global rules:
  - Tests: No merges with failing tests
  - DB policy: Ingest/normalize must not require DB
  - Body format: Confluence default is ADF
  - Traceability: Persist all required fields throughout pipeline
  - Observability: Stream clean progress with run_id
  - No regression: Read modules before editing, prefer minimal deltas

### 1. Test Failures Fixed ✅

**Console Observability Tests:**

- Fixed mock decorator argument issues in test methods
- Corrected `setup_logging()` API calls (`format_type` not `format`)
- Improved stream separation test to handle test suite state

**Ask CLI Tests:**

- Fixed DB preflight check for `ask` command when `--db-url` provided
- Modified ask command to skip preflight when custom db_url specified
- All ask CLI tests now pass

**DB Doctor Test:**

- Fixed assertion to check correct output stream (stdout vs stderr)

**Final Result:** All 231 tests pass ✅

### 2. Confluence Ingest Schema Verified ✅

- Confirmed all required traceability fields preserved:
  - `id`, `url`, `space_id/key/name`, `version`, `created_at`, `updated_at`
  - `labels`, `ancestors/breadcrumbs`, `attachments` (with filename + download_url)
  - `content_sha256`, `links`
- Enhanced test to verify all fields present in output
- Confirmed sidecars: `metrics.json`, `manifest.json`, CSV exports, etc.

### 3. Normalize Coverage Enhanced ✅

- Verified ADF default preference in auto-detection
- Confirmed storage fallback works correctly
- Verified all outputs: `normalized.ndjson`, `metrics.json`, `manifest.json`
- All normalize tests pass (ADF, storage, traceability)

### 4. CLI Defaults & UX Polished ✅

- **ADF Default**: Set `atlas_doc_format` as default in CLI parameter (not just fallback)
- **Help Text**: Clearly shows ADF as default in `--body-format` help
- **Progress**: Verified progress system working correctly
- **Observability**: Confirmed run_id printed, structured progress

### 5. Postgres Separation Confirmed ✅

- **Ingest/Normalize**: Confirmed NO `_run_db_preflight_check()` calls
- **Embed/Ask**: Confirmed DO call preflight checks (ask conditional on `--db-url`)
- **Test Verification**: Normalize works without DB, embed fails without DB
- **Policy Enforced**: DB only required for retrieval/indexing phases

### 6. DITA Stabilization Completed ✅

- **Source System**: DITA records include `"source_system": "dita"`
- **File Separation**: DITA writes to `dita.ndjson`, Confluence to `confluence.ndjson`
- **Normalize Handshake**: Fixed field mapping (`body_dita_xml` vs `body_xml`)
- **Integration Test**: Verified DITA → normalize pipeline works end-to-end

### 7. Delta Correctness Verified ✅

- **Diff-deletions**: Confirmed produces `deleted_ids.json` correctly
- **Auto-since**: Verified state file read/write functionality
- **Incremental**: Confirmed --since filtering works as expected
- **All Tests Pass**: Delta functionality comprehensive test coverage

### 8. Documentation Updated ✅

**README.md:**

- Added "Golden Path" section with complete workflow
- Clearly states ingest/normalize work without DB
- Emphasizes ADF as default body format
- Shows where to find artifacts (`var/runs/<run_id>/<phase>/`)

**New Runbook**: `docs/runbooks/ingest_normalize.md`

- Copy-paste commands for all common workflows
- Expected console output examples
- File structure documentation
- Troubleshooting guide

### 9. Final Validation ✅

**CI Pipeline Results:**

```bash
make fmt && make lint && make test && make check-md && make ci
```

- ✅ **Format**: All files properly formatted
- ✅ **Lint**: No errors (ruff, mypy, markdownlint)
- ✅ **Test**: 231 passed, 0 failures
- ✅ **Markdown**: All markdown files pass

## Acceptance Criteria Met

✅ **All tests pass** (make ci green)\
✅ **Confluence ingest** continues to emit full traceability fields and sidecars\
✅ **Normalization** preserves links, attachments, labels, content_sha256, breadcrumbs\
✅ **ADF default** body format in CLI help/behavior\
✅ **Ingest/normalize** run without DB; DB checks remain for DB-dependent commands\
✅ **Console UX** readable and observable (banners/progress + run_id)\
✅ **README and runbook** document golden path with copy-paste commands

## Validation Commands Used

```bash
# Pre-work validation
make setup
make fmt && make lint && make test && make check-md

# Test specific functionality  
python -m pytest tests/test_console_observability.py -v
python -m pytest tests/test_ask_cli_smoke.py -v
python -m pytest tests/test_ingest_confluence_smoke.py -v
python -m pytest tests/test_normalize_adf.py tests/test_normalize_storage.py -v
python -m pytest tests/test_dita_ingest.py tests/test_dita_adapter.py -v
python -m pytest tests/test_diff_deletions.py -v
python -m pytest tests/test_auto_since_state.py -v

# CLI validation
trailblazer --help
trailblazer ingest --help  
trailblazer ingest confluence --help
trailblazer normalize from-ingest --help
trailblazer confluence spaces --help

# Integration validation  
# (Tested DITA normalize integration)
# (Tested ask command with/without DB)
# (Tested normalize without DB)

# Final validation
make ci  # All green ✅
```

**Commit**: `feat(014): stabilize ingest→normalize; fix tests; ADF default; docs`
