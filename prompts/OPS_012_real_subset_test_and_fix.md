## Shared Guardrails

**Overview**
Each prompt in this monorepo follows a standard workflow and set of constraints. Read this document fully before starting any prompt.

**Working on main ONLY**

- All work happens on the main branch
- No feature branches, forks, or detours
- `git rev-parse --abbrev-ref HEAD` must show `main`
- If not on main, stop and switch to main before proceeding

**Quality gates (run before and after changes)**

- `make setup` – install dependencies, configure environment
- `make fmt` – format all code (black, ruff, etc.)
- `make lint` – lint all code (ruff, mypy, etc.)
- `make test` – run all tests (pytest)
- `make check-md` – validate markdown documents

**Zero test failures**

- If any test fails, fix it before proceeding
- Tests must pass both before and after your changes
- This includes unit tests, integration tests, and linting

**Database strategy**

- Postgres is the primary database for production
- SQLite is used for testing and development
- All database operations should work with both engines
- Use `trailblazer db doctor` to verify database health

**Code changes**

- Be surgical: minimal, focused changes
- Preserve existing behavior unless explicitly changing it
- Add tests for new functionality
- Update documentation when adding new features
- Follow existing code patterns and conventions

**Artifacts and state**

- All pipeline artifacts go to `runs/{run_id}/`
- State files go to `state/`
- Logs go to `logs/`
- Raw data goes to `data/raw/`
- Never commit large files or sensitive data

**CLI conventions**

- Use `--progress` for user-visible operations
- Use `--no-color` for logs and CI
- Use `--dry-run` when available for testing
- Progress output goes to stderr, data to stdout

**Error handling**

- Fail fast on unrecoverable errors
- Provide clear, actionable error messages
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR)
- Use structured logging for programmatic consumption

**Performance**

- Batch operations when possible
- Use connection pooling for database operations
- Respect rate limits for external APIs
- Monitor memory usage for large datasets

**Security**

- Never log sensitive data (tokens, passwords)
- Use environment variables for configuration
- Validate all inputs
- Follow principle of least privilege

______________________________________________________________________

# PROMPT OPS-012 — Real-World Subset Test (Confluence & DITA) → Verify → Fix Utterly → Re-run

**Work on**: MAIN ONLY (no feature branches)

**Your job**: RUN it, don't describe it. Show live, readable progress in the terminal. If anything is wrong, fix it utterly (code + tests), then re-run the same subsets and prove it.

## To-Dos (max 9)

### 1. Sanity & toolchain (ingest/normalize are DB-free)

```bash
git rev-parse --abbrev-ref HEAD
make setup && make fmt && make lint && make test && make check-md
trailblazer ingest confluence --help | grep -i body-format   # default must be atlas_doc_format
```

### 2. Confluence subset — run ~300–500 pages (observable)

```bash
mkdir -p logs
SPACE=PM                 # choose a real space with hundreds of pages
RID_C="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_subset"
trailblazer ingest confluence \
  --space "$SPACE" \
  --progress --progress-every 5 --no-color \
  --max-pages 500 \
  1> "logs/ingest-$RID_C-$SPACE.jsonl" \
  2> >(tee -a "logs/ingest-$RID_C-$SPACE.out")
```

Pretty progress must be visible in your terminal (stderr). JSON events go to the \*.jsonl file.

### 3. DITA subset — run a couple of real subfolders (~300–500 topics)

```bash
DITA_ROOT="data/raw/dita/ellucian-documentation"
ls -1 "$DITA_ROOT" | sed -n '1,40p'     # choose 1–2 dirs (e.g., gen_help, esm_release)
SUB1=gen_help
RID_D="$(date -u +'%Y%m%dT%H%M%SZ')_${SUB1}_subset"
trailblazer ingest dita \
  --root "$DITA_ROOT/$SUB1" \
  --progress --progress-every 5 --no-color \
  1> "logs/ingest-$RID_D-dita.jsonl" \
  2> >(tee -a "logs/ingest-$RID_D-dita.out")
```

### 4. Verify ingest artifacts exist & are traceable (both runs)

```bash
# Confluence
test -f "runs/$RID_C/ingest/confluence.ndjson"
test -f "runs/$RID_C/ingest/links.jsonl"
test -f "runs/$RID_C/ingest/edges.jsonl"
test -f "runs/$RID_C/ingest/attachments_manifest.jsonl"
test -f "runs/$RID_C/ingest/ingest_media.jsonl"
test -f "runs/$RID_C/ingest/labels.jsonl"
test -f "runs/$RID_C/ingest/breadcrumbs.jsonl"
test -f "runs/$RID_C/ingest/summary.json"

# DITA
test -f "runs/$RID_D/ingest/dita.ndjson"
test -f "runs/$RID_D/ingest/links.jsonl"
test -f "runs/$RID_D/ingest/edges.jsonl"
test -f "runs/$RID_D/ingest/attachments_manifest.jsonl"
test -f "runs/$RID_D/ingest/ingest_media.jsonl"
test -f "runs/$RID_D/ingest/labels.jsonl"
test -f "runs/$RID_D/ingest/breadcrumbs.jsonl"
test -f "runs/$RID_D/ingest/summary.json"
```

### 5. Spot-check structure & traceability (fields present, edges typed)

```bash
# Confluence: one document line (ID/URL/body/labels/breadcrumbs)
head -n1 "runs/$RID_C/ingest/confluence.ndjson" | jq '{source_system,id,title,url,body_repr,label_count,ancestor_count,attachment_count}'
# Confluence: link edges and hierarchy edges
sed -n '1,3p' "runs/$RID_C/ingest/links.jsonl" | jq '{from_page_id,target_type,target_page_id,target_url}'
sed -n '1,3p' "runs/$RID_C/ingest/edges.jsonl" | jq '.'

# DITA: one document line (ID/path/doctype/labels)
head -n1 "runs/$RID_D/ingest/dita.ndjson" | jq '{source_system,id,source_path,doctype,label_count,attachment_count}'
# DITA: link edges (internal/external) + conrefs in edges
sed -n '1,3p' "runs/$RID_D/ingest/links.jsonl" | jq '{from_page_id,target_type,target_page_id,target_url}'
jq -r 'select(.type=="CONREFS")' "runs/$RID_D/ingest/edges.jsonl" | head

# Roll-ups (both)
jq -C '. | {pages, attachments, links_total, links_internal, links_external, media_refs_total, labels_total, ancestors_total}' "runs/$RID_C/ingest/summary.json"
jq -C '. | {pages, attachments, links_total, links_internal, links_external, media_refs_total, labels_total, ancestors_total}' "runs/$RID_D/ingest/summary.json"
```

### 6. Normalize both runs & verify preservation (no DB)

```bash
trailblazer normalize from-ingest --run-id "$RID_C"
head -n1 "runs/$RID_C/normalize/normalized.ndjson" | jq '{id,source_system,body_repr,url,text_md: (.text_md[:100]),links: (.links[0:3]),attachments: (.attachments[0:3]),labels: (.labels[0:5]),breadcrumbs: (.breadcrumbs[0:5])}'

trailblazer normalize from-ingest --run-id "$RID_D"
head -n1 "runs/$RID_D/normalize/normalized.ndjson" | jq '{id,source_system,body_repr,url,text_md: (.text_md[:100]),links: (.links[0:3]),attachments: (.attachments[0:3]),labels: (.labels[0:5]),breadcrumbs: (.breadcrumbs[0:5])}'
```

### 7. If ANY discrepancy/error occurs → fix utterly (code + tests), then re-run the failing subset

**Typical fixes:**

- Missing space_key/labels/ancestors/attachments in records → populate additively (don't rename).
- Links unresolved count unexpectedly high → tighten DITA keyref/xref & Confluence URL resolvers.
- Normalized record dropped fields → ensure preservation (url, links, attachments, labels, breadcrumbs, meta).

**Non-negotiables**: review the module first, be surgical unless a tiny refactor reduces risk; ZERO test failures after changes:

```bash
make fmt && make lint && make test && make check-md
# Re-run only the failing subset and re-verify the same checks as above
```

### 8. Re-run both subsets end-to-end (post-fix)

```bash
# Confluence re-run (smaller cap just to confirm)
RID_C2="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_subset_fix"
trailblazer ingest confluence --space "$SPACE" --progress --progress-every 5 --no-color --max-pages 200 \
  1> "logs/ingest-$RID_C2-$SPACE.jsonl" \
  2> >(tee -a "logs/ingest-$RID_C2-$SPACE.out")
trailblazer normalize from-ingest --run-id "$RID_C2"

# DITA re-run (same subfolder)
RID_D2="$(date -u +'%Y%m%dT%H%M%SZ')_${SUB1}_subset_fix"
trailblazer ingest dita --root "$DITA_ROOT/$SUB1" --progress --progress-every 5 --no-color \
  1> "logs/ingest-$RID_D2-dita.jsonl" \
  2> >(tee -a "logs/ingest-$RID_D2-dita.out")
trailblazer normalize from-ingest --run-id "$RID_D2"
```

### 9. Proof-of-work to paste back

- The two ingest commands you ran (Confluence & DITA).
- The last ~30 lines of each \*.out (progress + [DONE] summary).
- The jq snippets showing expected fields in confluence.ndjson, dita.ndjson, both summary.json roll-ups, and the first line of each normalized.ndjson.
- If you fixed anything: the failing symptom, the minimal code change, and the post-fix re-run results.

## Acceptance

1. You executed both subset runs (Confluence & DITA), saw live progress in the terminal, and produced all artifacts.
1. normalized.ndjson preserves url, links, attachments, labels, breadcrumbs for both sources.
1. Any discrepancy was fixed with code+tests (zero test failures) and the subsets were re-run successfully.
1. We're now safe to proceed with the full ingest + normalize.
