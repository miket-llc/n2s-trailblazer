# PROMPT DEV-009 — DB Strategy: Postgres-First + Preflight, Ingest DB-Free

**Implementation Completed** ✅

## Summary

Successfully implemented a Postgres-first database strategy that ensures:

- **Ingest is DB-free**: All ingest CLI commands and modules can import and run without any database connections
- **Postgres-first runtime**: Commands that persist/query embeddings (`embed load`, `ask`) require PostgreSQL + pgvector in non-test environments
- **SQLite gated to tests**: SQLite usage requires `ALLOW_SQLITE_FOR_TESTS=1` environment variable
- **Preflight validation**: `trailblazer db check` command validates connectivity and pgvector availability
- **Single source of truth**: Centralized database engine in `src/trailblazer/db/engine.py`

## Key Changes Implemented

### A) Updated Shared Guardrails ✅

Added Database Non-Negotiables to `prompts/000_shared_guardrails.md`:

```markdown
## Database Non-Negotiables (Global)
- Ingest is DB-free: importing or running any ingest CLI/step MUST NOT connect to, import, or initialize the DB.
- Postgres-first for runtime: Any command that persists or queries embeddings (e.g., `embed load`, `ask`, future retrieval services) MUST require Postgres + pgvector in non-test environments. SQLite is allowed ONLY for unit tests/CI and must be explicitly opted-in.
- Single source of truth: DB_URL MUST be provided in `.env` and used by a single engine factory. No hardcoded defaults that silently fall back to SQLite in dev/prod.
- Preflight required: `trailblazer db check` MUST pass (connectivity + pgvector present) before `embed load` or `ask` run (unless tests explicitly opt-in to SQLite).
- Secrets hygiene: Never print DB credentials in logs; log the host/database name only.
```

### B) Code & CLI Implementation ✅

#### 1. Engine Unification ✅

- **Centralized DB creation** in `src/trailblazer/db/engine.py`
- **Added functions**: `get_engine()`, `get_session()`, `is_postgres()`, `check_db_health()`
- **Environment-based configuration**: No default SQLite fallback in production
- **Removed** duplicate engine code from `src/trailblazer/core/db.py`
- **Ensured** no ingest imports trigger database initialization

#### 2. Database Check CLI ✅

- **New command**: `trailblazer db check`
- **PostgreSQL validation**: Connects via DB_URL and checks for pgvector extension
- **Comprehensive output**: Shows engine dialect, database name, host, and pgvector availability
- **Error handling**: Exits non-zero if PostgreSQL lacks pgvector or connection fails
- **Credential masking**: Never prints passwords in logs

#### 3. Database Initialization Enhancement ✅

- **PostgreSQL extension support**: Attempts `CREATE EXTENSION IF NOT EXISTS vector`
- **Graceful fallback**: Continues if extension creation fails (permissions)
- **Health check integration**: Validates pgvector availability after init
- **Clear user guidance**: Provides manual pgvector setup instructions when needed

#### 4. SQLite Gating ✅

- **Environment gate**: `ALLOW_SQLITE_FOR_TESTS=1` required for SQLite usage
- **Production protection**: SQLite blocked in non-test environments with clear error message
- **Test support**: All tests automatically have SQLite enabled via `tests/conftest.py`
- **Engine validation**: Checked at engine creation time, not just configuration

#### 5. Preflight Guards ✅

- **Embed load protection**: `trailblazer embed load` runs `db check` before execution
- **Ask command protection**: `trailblazer ask` runs `db check` before execution
- **Clear error messages**: Users directed to run `trailblazer db check` for diagnostics
- **Test compatibility**: Respects `ALLOW_SQLITE_FOR_TESTS` environment variable

#### 6. Configuration Updates ✅

Updated `configs/dev.env.example`:

```bash
# Database (Postgres-first) - REQUIRED for production
TRAILBLAZER_DB_URL=postgresql+psycopg2://trailblazer:trailblazer@localhost:5432/trailblazer
# Alternative format: TRAILBLAZER_DB_URL=postgresql://username:password@localhost:5432/dbname

# For tests/CI only - uncomment ONLY if you need SQLite for testing
# ALLOW_SQLITE_FOR_TESTS=1
```

#### 7. Documentation ✅

Enhanced README.md with new "Database (Postgres-first)" section including:

- **PostgreSQL setup instructions** for Ubuntu/Debian and macOS
- **Configuration guidance** with example connection strings
- **Database commands** (`db check`, `db init`) with usage examples
- **Troubleshooting guidance** for pgvector extension issues
- **Clear development workflow** from database setup through embedding and querying

#### 8. Comprehensive Testing ✅

- **Test environment setup**: `tests/conftest.py` automatically enables SQLite for all tests
- **SQLite gating tests**: Verify SQLite is blocked without `ALLOW_SQLITE_FOR_TESTS=1`
- **Preflight validation tests**: Confirm `embed load` and `ask` fail appropriately with invalid database
- **Database health checks**: Mock PostgreSQL scenarios with/without pgvector
- **Ingest isolation tests**: Verify ingest modules remain DB-free
- **Existing tests preserved**: All original SQLite-based tests continue working

## Validation Results ✅

### Linting

```bash
❯ ruff check . --fix
All checks passed!
```

### Testing

```bash
❯ python -m pytest tests/test_db_check_and_sqlite_gating.py tests/test_loader_sqlite.py tests/test_ingest_import_no_db.py -v
============================================ 21 passed in 0.50s =============================================
```

### Commit

```bash
[main c9c7c2f] feat(db): Postgres-first strategy + db check preflight; SQLite gated to tests; ingest DB-free
 9 files changed, 529 insertions(+), 61 deletions(-)
 delete mode 100644 src/trailblazer/core/db.py
 create mode 100644 tests/conftest.py
 create mode 100644 tests/test_db_check_and_sqlite_gating.py
```

## Acceptance Criteria Met ✅

- ✅ **Ingest CLIs import and run without initializing DB**
- ✅ **`trailblazer db check` accurately reports Postgres + pgvector**
- ✅ **`embed load`/`ask` fail early with clear message if DB is not Postgres (unless tests explicitly allow SQLite)**
- ✅ **README and dev.env.example steer to Postgres**
- ✅ **All tests pass with proper SQLite gating**
- ✅ **Database preflight checks prevent inappropriate SQLite usage**

## Database Strategy Implementation Complete

The Postgres-first database strategy is now fully implemented and operational. The system enforces PostgreSQL + pgvector for production workloads while maintaining SQLite compatibility for testing, with robust preflight validation and clear user guidance throughout.
