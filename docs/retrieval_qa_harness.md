# Retrieval QA Harness

The Retrieval QA Harness is a standalone script that exercises the existing Trailblazer retriever over curated Navigate to SaaS (N2S) questions and produces quality assessment artifacts.

## Overview

The harness runs a set of curated N2S questions through the retrieval system, computes health metrics, and generates readiness reports. It operates in read-only mode without modifying any production code or database state.

## How to Run the Retrieval QA Harness

### Basic Usage

```bash
# Activate the virtual environment
source scripts/activate.sh

# Run with default settings
python scripts/qa_retrieval.py

# Run with specific parameters
python scripts/qa_retrieval.py \
  --queries-file prompts/qa/queries_n2s.yaml \
  --top-k 12 \
  --budgets 1500,4000,6000 \
  --provider openai \
  --dimension 1536
```

### Command Line Options

- `--queries-file`: Path to YAML file with queries (default: `prompts/qa/queries_n2s.yaml`)
- `--top-k`: Number of top results to retrieve (default: 12)
- `--budgets`: Comma-separated character limits for context packing (optional)
- `--out`: Output directory (default: `var/retrieval_qc/<timestamp>/`)
- `--db-url`: Database URL (optional; uses default configuration if omitted)
- `--provider`: Embedding provider (default: openai)
- `--dimension`: Embedding dimension (default: 1536)

### Prerequisites

1. **Database**: Ensure PostgreSQL is running with embeddings data:

   ```bash
   make db.up
   trailblazer db doctor  # Verify health
   ```

1. **Environment**: Use the project's virtual environment:

   ```bash
   source scripts/activate.sh
   ```

## Output Artifacts

The harness creates a timestamped directory under `var/retrieval_qc/` with the following files:

### Per-Query Artifacts

- **`ask_<query_id>.json`**: Raw retrieval hits for each query

  - Contains: chunk_id, doc_id, title, url, text snippet, score, source_system
  - Ordered by relevance score (descending)

- **`context_<query_id>_<budget>.txt`**: Packed context text (if budgets specified)

  - Context text limited to specified character budget
  - Includes separators with metadata (score, title, URL)
  - Respects document diversity (max 3 chunks per document)

### Summary Reports

- **`readiness.json`**: Machine-readable overall assessment
- **`overview.md`**: Human-readable summary table

## How to Read readiness.json

The `readiness.json` file contains the complete assessment results:

```json
{
  "overall_pass": true,
  "provider": "openai", 
  "dimension": 1536,
  "top_k": 12,
  "budgets": [1500, 4000, 6000],
  "queries": [
    {
      "id": "lifecycle_overview",
      "diversity": 8,
      "traceability_ok": true,
      "duplication_ok": true,
      "tie_rate_ok": true,
      "expect_ok": true,
      "notes": []
    }
  ],
  "summary": {
    "total_queries": 24,
    "traceability_passes": 24,
    "duplication_passes": 24,
    "diversity_passes": 20,
    "expect_passes": 18
  }
}
```

### Key Fields

- **`overall_pass`**: Boolean indicating if the retrieval system passes all quality gates
- **`queries`**: Array of per-query assessments with metrics
- **`summary`**: Aggregate statistics across all queries

### Per-Query Metrics

- **`diversity`**: Number of unique documents in top-k results (target: ≥6 of 12)
- **`traceability_ok`**: All hits have non-empty title and url
- **`duplication_ok`**: No repeated (doc_id, chunk_id) pairs in results
- **`tie_rate_ok`**: Low percentage of identical scores (≤30%)
- **`expect_ok`**: Expected phrases found in results (if specified in query)
- **`notes`**: Array of issues or observations

### Overall Pass Criteria

The system passes if:

- **100%** of queries pass `traceability_ok` and `duplication_ok`
- **≥80%** of queries pass `diversity` (≥6 unique docs)
- **≥80%** of queries with expectations pass `expect_ok`

## How to Read overview.md

The `overview.md` file provides a human-readable table format:

```markdown
# Retrieval QA Overview

**Overall Pass:** true
**Provider:** openai
**Dimension:** 1536
**Top-K:** 12

## Query Results

| ID | Diversity | Traceability | Duplication | Tie Rate | Expect | Notes |
|----|-----------|--------------|-------------|----------|--------|-------|
| lifecycle_overview | 8 | ✓ | ✓ | ✓ | ✓ | |
| sprint0_scope | 6 | ✓ | ✓ | ✓ | ✓ | |
| plan_governance | 4 | ✓ | ✓ | ✓ | ✗ | Expected phrase not found: 'governance checkpoints' |
```

### Reading the Table

- **Diversity**: Number (target ≥6)
- **Traceability/Duplication/Tie Rate/Expect**: ✓ (pass) or ✗ (fail)
- **Notes**: Specific issues or observations

## Query File Format

Queries are defined in YAML format at `prompts/qa/queries_n2s.yaml`:

```yaml
- id: lifecycle_overview
  text: "Summarize the Navigate to SaaS lifecycle: phases, stages, iteration in Build."
  expect:
    - "Discovery, Build, Optimize"
    - "Start, Prepare, Sprint 0, Plan, Configure, Test, Deploy, Go-Live, Post Go-Live (Care)"

- id: sprint0_scope
  text: "Define Sprint 0 objectives and outputs."
  # expect is optional
```

### Required Fields

- **`id`**: Unique identifier for the query
- **`text`**: The actual question/query text

### Optional Fields

- **`expect`**: List of phrases that should appear in the results (case-insensitive)

## Exit Codes

The script exits with:

- **0**: Overall assessment passes
- **1**: Overall assessment fails or error occurred

This makes it suitable for CI/CD integration.

## Troubleshooting

### Import Errors

```bash
# Ensure virtual environment is activated
source scripts/activate.sh

# Verify Python path includes src/
python -c "import sys; print('src' in ' '.join(sys.path))"
```

### Database Connection Issues

```bash
# Check database health
trailblazer db doctor

# Start database if needed
make db.up
```

### No Results Returned

- Verify embeddings exist for the specified provider/dimension
- Check that documents have been ingested and embedded
- Review query text for potential issues

### Low Diversity Scores

- May indicate over-chunking or insufficient document variety
- Review chunking strategy and document corpus
- Consider adjusting similarity thresholds
