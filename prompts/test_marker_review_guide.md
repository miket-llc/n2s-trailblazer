# 🧪 **Test Marker Review Guide for Trailblazer**

## 📋 **Overview**
This guide ensures all new tests are properly marked with the correct pytest markers to run in the appropriate test environment. Proper marking is **CRITICAL** for test isolation, performance, and CI/CD pipeline success.

## 🏷️ **Available Test Markers**

### 1. **`@pytest.mark.unit`** - Unit Tests (Fastest)
- **Purpose**: Test business logic, data validation, utility functions
- **Database**: SQLite in-memory (fast, isolated)
- **Speed**: 5-10 seconds for full suite
- **Use When**: Testing pure functions, classes, or modules without external dependencies
- **Environment**: No special environment variables needed

```python
@pytest.mark.unit
def test_business_logic():
    """Test business logic without database."""
    result = calculate_something(input_data)
    assert result == expected_value
```

### 2. **`@pytest.mark.integration`** - Integration Tests (Medium)
- **Purpose**: Test database operations, schema, basic CRUD, API interactions
- **Database**: PostgreSQL (real database, no pgvector)
- **Speed**: 15-30 seconds for full suite
- **Use When**: Testing database operations, external API calls, or component interactions
- **Environment**: Requires `TB_TESTING_INTEGRATION=1`

```python
@pytest.mark.integration
def test_database_operations():
    """Test with real database."""
    # Test actual database operations
    result = db.create_record(data)
    assert result.id is not None
```

### 3. **`@pytest.mark.pgvector`** - Vector Search Tests (Slowest)
- **Purpose**: Test vector operations, similarity search, embeddings
- **Database**: PostgreSQL + pgvector extension
- **Speed**: 1-2 minutes for full suite
- **Use When**: Testing vector similarity, embedding operations, or AI/ML features
- **Environment**: Requires `TB_TESTING_PGVECTOR=1`

```python
@pytest.mark.pgvector
def test_vector_similarity():
    """Test vector operations with pgvector."""
    query_vec = embed_query("test query")
    results = search_similar(query_vec, top_k=5)
    assert len(results) > 0
```

### 4. **`@pytest.mark.no_db`** - No Database Tests (Fastest)
- **Purpose**: Test pure functions, utilities, or static analysis
- **Database**: None (fastest possible)
- **Speed**: 1-5 seconds for full suite
- **Use When**: Testing static analysis, linting rules, or pure computational functions
- **Environment**: No special requirements

```python
@pytest.mark.no_db
def test_utility_function():
    """Test utility function without any database."""
    result = format_string("hello world")
    assert result == "HELLO WORLD"
```

## 📁 **Test Directory Structure & Default Markers**

### **Automatic Database Tests** (No marker needed)
These directories automatically run with PostgreSQL + pgvector:
- `tests/qa/` - QA evaluation tests
- `tests/retrieval/` - Vector retrieval tests
- `tests/embed/` - Embedding pipeline tests
- `tests/cli/` - Command-line interface tests

### **Unit Tests** (Should be marked)
- `tests/unit/` - Core business logic tests
- `tests/policy/` - Code quality and architecture tests
- `tests/lint/` - Static analysis tests

### **Special Cases**
- `tests/utils/` - Utility function tests
- `tests/runner/` - Pipeline execution tests
- `tests/pipeline/` - Pipeline step tests

## 🔧 **Implementation Rules**

### **Rule 1: Always Mark Unit Tests**
```python
# ❌ WRONG - No marker
def test_something():
    pass

# ✅ CORRECT - Properly marked
@pytest.mark.unit
def test_something():
    pass
```

### **Rule 2: Use `no_db` for Pure Functions**
```python
# ❌ WRONG - Using unit for pure function
@pytest.mark.unit
def test_string_formatting():
    pass

# ✅ CORRECT - Using no_db for pure function
@pytest.mark.no_db
def test_string_formatting():
    pass
```

### **Rule 3: Mark Integration Tests Explicitly**
```python
# ❌ WRONG - No marker for database test
def test_database_connection():
    pass

# ✅ CORRECT - Marked as integration
@pytest.mark.integration
def test_database_connection():
    pass
```

### **Rule 4: Use `pgvector` for Vector Operations**
```python
# ❌ WRONG - Using integration for vector test
@pytest.mark.integration
def test_embedding_similarity():
    pass

# ✅ CORRECT - Using pgvector for vector test
@pytest.mark.pgvector
def test_embedding_similarity():
    pass
```

## 📝 **File-Level Marking**

### **For Entire Test Files**
Use `pytestmark` at the top of the file when all tests share the same requirements:

```python
# Mark entire file as unit tests
pytestmark = pytest.mark.unit

def test_one():
    pass

def test_two():
    pass
```

```python
# Mark entire file as no database
pytestmark = pytest.mark.no_db

def test_utility():
    pass

def test_validation():
    pass
```

## 🚨 **Common Mistakes to Avoid**

### **Mistake 1: Unmarked Tests**
```python
# ❌ WRONG - Test will try to use database by default
def test_business_logic():
    # This might fail if database isn't available
    pass
```

### **Mistake 2: Wrong Marker for Database Tests**
```python
# ❌ WRONG - Unit test trying to access database
@pytest.mark.unit
def test_database_operation():
    # This will fail because unit tests use SQLite
    db.create_table()
```

### **Mistake 3: Missing Environment Variables**
```python
# ❌ WRONG - pgvector test without proper environment
@pytest.mark.pgvector
def test_vector_search():
    # This will fail if TB_TESTING_PGVECTOR=1 not set
    pass
```

## ✅ **Review Checklist**

Before committing any new test, ensure:

1. **Every test function has a marker** (or file has `pytestmark`)
2. **Unit tests use `@pytest.mark.unit`** for business logic
3. **Pure functions use `@pytest.mark.no_db`** for utilities
4. **Database tests use `@pytest.mark.integration`** for basic DB ops
5. **Vector tests use `@pytest.mark.pgvector`** for AI/ML features
6. **No unmarked tests** that might accidentally use database
7. **Environment variables documented** for integration/pgvector tests

## 📊 **Examples by Test Type**

### **Business Logic Test**
```python
@pytest.mark.unit
def test_calculate_discount():
    """Test discount calculation logic."""
    discount = calculate_discount(100, 0.1)
    assert discount == 10
```

### **Utility Function Test**
```python
@pytest.mark.no_db
def test_sanitize_filename():
    """Test filename sanitization."""
    result = sanitize_filename("file name with spaces.txt")
    assert result == "file_name_with_spaces.txt"
```

### **Database Schema Test**
```python
@pytest.mark.integration
def test_table_creation():
    """Test database table creation."""
    engine = create_engine(test_db_url)
    Base.metadata.create_all(engine)
    # Verify tables exist
```

### **Vector Search Test**
```python
@pytest.mark.pgvector
def test_similarity_search():
    """Test vector similarity search."""
    query_vec = embed_text("search query")
    results = find_similar(query_vec, top_k=5)
    assert len(results) > 0
```

## 📊 **Performance Impact**

| Marker | Database | Speed | Use Case |
|--------|----------|-------|----------|
| `no_db` | None | Fastest | Pure functions, utilities |
| `unit` | SQLite | Fast | Business logic, validation |
| `integration` | PostgreSQL | Medium | Database ops, APIs |
| `pgvector` | PostgreSQL + pgvector | Slowest | AI/ML, vector operations |

## 🎯 **Remember**
- **Always mark your tests** - no exceptions
- **Choose the right marker** for the test's needs
- **Consider performance** - use fastest marker possible
- **Document environment requirements** for integration tests
- **Test isolation is critical** - don't break other tests

This ensures your tests run efficiently, in the right environment, and don't interfere with other test categories! 🚀
