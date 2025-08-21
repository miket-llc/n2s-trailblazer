# Testing Strategy

## Test Categories

### 🚀 Unit Tests (Fastest)

- **Database**: SQLite in-memory
- **Scope**: Business logic, data validation, utility functions
- **Speed**: 5-10 seconds for full suite
- **Command**: `make test-unit`

### 🏃 Integration Tests (Medium)

- **Database**: PostgreSQL (no pgvector)
- **Scope**: Database operations, schema, basic CRUD
- **Speed**: 15-30 seconds for full suite
- **Command**: `make test-integration`

### 🐌 pgvector Tests (Slowest)

- **Database**: PostgreSQL + pgvector extension
- **Scope**: Vector operations, similarity search, embeddings
- **Speed**: 1-2 minutes for full suite
- **Command**: `make test-pgvector`

### ⚡ Fast Tests (Recommended for Development)

- **Database**: SQLite + mocks
- **Scope**: Everything except pgvector operations
- **Speed**: 10-20 seconds for full suite
- **Command**: `make test-fast`

## Development Workflow

### During Development

```bash
# Fast feedback loop
make test-fast      # 10-20 seconds
make lint           # Code quality
```

### Before Commit

```bash
# Full validation
make test-all       # All tests including pgvector
make fmt            # Format code
make lint           # Lint code
```

### CI/CD

```bash
# Run in parallel
make test-unit      # Unit tests
make test-integration  # Integration tests  
make test-pgvector     # pgvector tests
```

## Adding Test Markers

### Unit Tests

```python
@pytest.mark.unit
def test_business_logic():
    # Test logic without database
    pass
```

### Integration Tests

```python
@pytest.mark.integration
def test_database_operations():
    # Test with real database
    pass
```

### pgvector Tests

```python
@pytest.mark.pgvector
def test_vector_similarity():
    # Test vector operations
    pass
```

### No Database Tests

```python
@pytest.mark.no_db
def test_utility_functions():
    # Test pure functions
    pass
```

## Environment Variables

- `TB_TESTING=1` - Enable database testing
- `TB_TESTING_PGVECTOR=1` - Use PostgreSQL + pgvector
- `TB_TESTING_INTEGRATION=1` - Use PostgreSQL (no pgvector)
- `TB_TESTING_UNIT_DB=1` - Allow unit tests to use database if needed
