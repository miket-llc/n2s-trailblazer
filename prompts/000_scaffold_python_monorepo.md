# PROMPT 000 (Rev A) — Scaffold the Trailblazer Python Monorepo (Confluence v2 + Basic Auth)
Save this prompt file as: prompts/000_scaffold_python_monorepo.md

You are: a senior platform engineer setting up the Trailblazer Python monorepo for RAG + doc generation. We've learned: CLI-first, explicit phases (no numeric modules), idempotent steps, persisted artifacts, clean interfaces. Confluence integration must use Cloud v2 endpoints and Basic auth (email + API token). Use v1 only where v2 lacks an equivalent (CQL search).

Repo target: miket-llc/n2s-trailblazer (currently empty).
If not connected, create files locally and stop before pushing. If connected, commit on a branch and push.

Objectives
Create a production-minded Python monorepo with:

Installable package trailblazer (core, adapters, pipeline, cli).

Typer CLI: trailblazer …

Phase folders under pipeline/steps/: ingest, normalize, enrich, classify, embed, retrieve, compose, create, audit.

Confluence adapter using v2 (/wiki/api/v2) for spaces/pages/attachments, Basic auth (email + API token), and v1 CQL for search until v2 supports it.

Data workspace (data/) and run artifacts (runs/) that are gitignored.

Config via Pydantic Settings; logs via structlog.

Minimal DAG/runner + no-op pipeline that materializes artifacts.

Tooling: ruff, black, mypy, pytest, pre-commit.

Save this prompt to prompts/.

Idempotent, extendable:

Stable phase names; order handled in code.

Run IDs (YYYY-MM-DD_HHMMSS_xxxx).

Small, typed I/O between steps.

Commit on branch scaffold/python-monorepo-v2-confluence.

Directory Tree (exact)
.gitignore

README.md

LICENSE

pyproject.toml

ruff.toml

mypy.ini

.pre-commit-config.yaml

Makefile

prompts/

000_scaffold_python_monorepo.md (this prompt)

configs/

dev.env.example

pipeline.yaml

data/ (gitignored)

raw/ staged/ processed/ generated/

runs/ (gitignored)

src/

trailblazer/

__init__.py

cli/

__init__.py

main.py

core/

__init__.py

config.py

logging.py

artifacts.py

db.py

models.py

adapters/

__init__.py

confluence_api.py

pipeline/

__init__.py

dag.py

runner.py

steps/

__init__.py

ingest/

__init__.py

confluence.py

normalize/

__init__.py

html_to_md.py

enrich/

__init__.py

structure.py

classify/

__init__.py

classifier.py

embed/

__init__.py

embedder.py

retrieve/

__init__.py

retriever.py

compose/

__init__.py

composer.py

create/

__init__.py

creator.py

audit/

__init__.py

validators.py

tests/

test_cli.py

test_run_id.py

File Contents
Create these files exactly (verbatim unless noted).

.gitignore
gitignore
Copy
Edit
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.venv*/
.env
.env.*
.cache/
.mypy_cache/
.pytest_cache/
.DS_Store

data/
runs/
logs/
dist/
build/
.coverage
coverage.xml

.idea/
.vscode/
README.md
md
Copy
Edit
# N2S Trailblazer (Python)

CLI-first monorepo for Navigate to SaaS (N2S) RAG + document generation.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

trailblazer --help
trailblazer run --phases ingest normalize --dry-run
Principles
CLI-first, explicit phases (no numeric module names).

Idempotent steps; artifacts under runs/<run_id>/<phase>/.

Config via env / configs/pipeline.yaml.

Confluence
API base: https://ellucian.atlassian.net/wiki/api/v2

Auth: Basic (email + API token)

Use v2 for spaces/pages/attachments; use v1 CQL endpoint for search until v2 adds it.

makefile
Copy
Edit

### `pyproject.toml`
```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "n2s-trailblazer"
version = "0.1.0"
description = "Trailblazer monorepo (Python) for N2S RAG + doc generation"
readme = "README.md"
requires-python = ">=3.10"
authors = [{ name = "Mike Thompson" }]
dependencies = [
  "typer[all]>=0.12.0",
  "pydantic>=2.7.0",
  "pydantic-settings>=2.2.1",
  "httpx>=0.27.0",
  "tenacity>=8.2.3",
  "structlog>=24.1.0",
  "rich>=13.7.0",
  "markdownify>=0.12.0",
  "beautifulsoup4>=4.12.0",
  "SQLAlchemy>=2.0.25",
  "psycopg[binary]>=3.1.18",
  "pgvector>=0.2.5"
]

[project.optional-dependencies]
dev = [
  "ruff>=0.4.0",
  "black>=24.3.0",
  "mypy>=1.9.0",
  "pytest>=8.1.0",
  "pre-commit>=3.7.0"
]

[project.scripts]
trailblazer = "trailblazer.cli.main:app"

[tool.black]
line-length = 100
target-version = ["py310"]

[tool.ruff]
line-length = 100
target-version = "py310"
select = ["E","F","I","B","UP","ANN","C90"]
ignore = ["ANN101","ANN102"]

[tool.mypy]
python_version = "3.10"
warn_unused_ignores = true
warn_redundant_casts = true
strict_optional = true
ruff.toml
toml
Copy
Edit
line-length = 100
target-version = "py310"
mypy.ini
ini
Copy
Edit
[mypy]
python_version = 3.10
strict = False
warn_unreachable = True
.pre-commit-config.yaml
yaml
Copy
Edit
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.7
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/psf/black
    rev: 24.8.0
    hooks:
      - id: black
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.1
    hooks:
      - id: mypy
Makefile
make
Copy
Edit
.PHONY: setup lint test fmt precommit

setup:
\tpython -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pre-commit install

lint:
\truff check .
\tmypy src

fmt:
\truff check . --fix
\tblack src tests

test:
\tpytest -q
configs/dev.env.example
dotenv
Copy
Edit
# Copy to .env and adjust for local dev
CONFLUENCE_BASE_URL=https://ellucian.atlassian.net/wiki
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your_api_token_here
# Optional: default body format for page fetches: storage | atlas_doc_format
CONFLUENCE_BODY_FORMAT=storage

TRAILBLAZER_DB_URL=postgresql+psycopg://postgres:postgres@localhost:5432/trailblazer
configs/pipeline.yaml
yaml
Copy
Edit
phases:
  - ingest
  - normalize
  - enrich
  - classify
  - embed
  - retrieve
  - compose
  - create
  - audit
defaults:
  ingest:
    since: null   # ISO timestamp for deltas
    spaces: []    # space keys or ids (strings); keys auto-resolve to ids
src/trailblazer/__init__.py
python
Copy
Edit
__all__ = ["__version__"]
__version__ = "0.1.0"
src/trailblazer/core/config.py
python
Copy
Edit
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List

class Settings(BaseSettings):
    # Confluence (Cloud v2 + Basic auth)
    CONFLUENCE_BASE_URL: str = "https://ellucian.atlassian.net/wiki"
    CONFLUENCE_EMAIL: Optional[str] = None
    CONFLUENCE_API_TOKEN: Optional[str] = None
    CONFLUENCE_BODY_FORMAT: str = "storage"  # or "atlas_doc_format"

    # Pipeline
    PIPELINE_PHASES: List[str] = []

    # Database (optional at scaffold time)
    TRAILBLAZER_DB_URL: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

SETTINGS = Settings()
src/trailblazer/core/logging.py
python
Copy
Edit
import structlog
import sys

def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

log = structlog.get_logger()
src/trailblazer/core/artifacts.py
python
Copy
Edit
from datetime import datetime
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[3]  # repo root
RUNS = ROOT / "runs"

def new_run_id() -> str:
    return f"{datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

def phase_dir(run_id: str, phase: str) -> Path:
    p = RUNS / run_id / phase
    p.mkdir(parents=True, exist_ok=True)
    return p
src/trailblazer/core/db.py (stub)
python
Copy
Edit
from typing import Optional
from sqlalchemy import text
from sqlalchemy.engine import create_engine
from .config import SETTINGS

_engine = None

def get_engine():
    global _engine
    if _engine is None and SETTINGS.TRAILBLAZER_DB_URL:
        _engine = create_engine(SETTINGS.TRAILBLAZER_DB_URL, future=True)
    return _engine

def ping() -> Optional[bool]:
    eng = get_engine()
    if not eng:
        return None
    with eng.connect() as c:
        c.execute(text("SELECT 1"))
    return True
src/trailblazer/core/models.py
python
Copy
Edit
from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Optional

class Page(BaseModel):
    id: str
    title: str
    space: Optional[str] = None
    space_id: Optional[str] = None
    version: int
    body_html: Optional[str] = None
    last_modified: Optional[datetime] = None
    attachments: List[str] = []
    url: Optional[str] = None
    metadata: Dict = {}
src/trailblazer/adapters/confluence_api.py
python
Copy
Edit
from typing import Dict, Iterable, Optional, List
from datetime import datetime
import httpx
from httpx import BasicAuth
from tenacity import retry, wait_exponential, stop_after_attempt
from ..core.config import SETTINGS
from ..core.logging import log

V2_PREFIX = "/api/v2"  # appended to CONFLUENCE_BASE_URL path (which already includes /wiki)

class ConfluenceClient:
    def __init__(self, base_url: Optional[str] = None, email: Optional[str] = None, token: Optional[str] = None):
        base = (base_url or SETTINGS.CONFLUENCE_BASE_URL).rstrip("/")
        if not base.endswith("/wiki"):
            # normalize to include /wiki for Cloud
            base = base + "/wiki"
        self.base_url = base  # e.g., https://ellucian.atlassian.net/wiki
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=30.0,
            auth=BasicAuth(email or SETTINGS.CONFLUENCE_EMAIL or "", token or SETTINGS.CONFLUENCE_API_TOKEN or ""),
            headers={"Accept": "application/json"},
        )

    # -------- v2 endpoints (cursor pagination) --------

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_spaces(self, keys: Optional[List[str]] = None, limit: int = 100) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/spaces?keys=KEY1,KEY2&limit=100
        Yields space objects; follow Link/_links.next for pagination.
        """
        params = {"limit": limit}
        if keys:
            params["keys"] = ",".join(keys)
        url = f"{V2_PREFIX}/spaces"
        while url:
            r = self._client.get(url, params=params if "cursor=" not in url else None)
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                yield item
            url = data.get("_links", {}).get("next")

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_pages(self, space_id: Optional[str] = None, body_format: Optional[str] = None, limit: int = 100) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/pages?space-id=<id>&body-format=storage|atlas_doc_format&limit=100
        """
        params = {"limit": limit}
        if space_id:
            params["space-id"] = space_id
        params["body-format"] = (body_format or SETTINGS.CONFLUENCE_BODY_FORMAT)
        url = f"{V2_PREFIX}/pages"
        while url:
            r = self._client.get(url, params=params if "cursor=" not in url else None)
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                yield item
            url = data.get("_links", {}).get("next")

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_page_by_id(self, page_id: str, body_format: Optional[str] = None) -> Dict:
        """
        GET /wiki/api/v2/pages/{id}?body-format=...
        """
        params = {"body-format": (body_format or SETTINGS.CONFLUENCE_BODY_FORMAT)}
        r = self._client.get(f"{V2_PREFIX}/pages/{page_id}", params=params)
        r.raise_for_status()
        return r.json()

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_attachments_for_page(self, page_id: str, limit: int = 100) -> Iterable[Dict]:
        """
        GET /wiki/api/v2/pages/{id}/attachments?limit=...
        """
        params = {"limit": limit}
        url = f"{V2_PREFIX}/pages/{page_id}/attachments"
        while url:
            r = self._client.get(url, params=params if "cursor=" not in url else None)
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                yield item
            url = data.get("_links", {}).get("next")

    # -------- v1 CQL search (until v2 offers equivalent) --------

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def search_cql(self, cql: str, start: int = 0, limit: int = 50, expand: Optional[str] = None) -> Dict:
        """
        GET /wiki/rest/api/content/search?cql=...&start=...&limit=...
        Note: server-side caps may apply when expanding bodies.
        """
        url = "/rest/api/content/search"
        params = {"cql": cql, "start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        r = self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()
src/trailblazer/pipeline/dag.py
python
Copy
Edit
from typing import List

DEFAULT_PHASES: List[str] = [
    "ingest", "normalize", "enrich", "classify", "embed", "retrieve", "compose", "create", "audit"
]

def validate_phases(phases: List[str]) -> List[str]:
    bad = [p for p in phases if p not in DEFAULT_PHASES]
    if bad:
        raise ValueError(f"Unknown phases: {bad}")
    return phases
src/trailblazer/pipeline/runner.py
python
Copy
Edit
from typing import List, Optional
from .dag import DEFAULT_PHASES, validate_phases
from ..core.artifacts import new_run_id, phase_dir
from ..core.logging import log

def run(phases: Optional[List[str]] = None, dry_run: bool = False, run_id: Optional[str] = None) -> str:
    phases = validate_phases(phases or DEFAULT_PHASES)
    rid = run_id or new_run_id()
    log.info("pipeline.run.start", run_id=rid, phases=phases, dry_run=dry_run)

    for phase in phases:
        outdir = phase_dir(rid, phase)
        log.info("phase.start", phase=phase, out=str(outdir), run_id=rid)
        if not dry_run:
            _execute_phase(phase, out=str(outdir))
        log.info("phase.end", phase=phase, run_id=rid)

    log.info("pipeline.run.end", run_id=rid)
    return rid

def _execute_phase(phase: str, out: str) -> None:
    if phase == "ingest":
        from .steps.ingest.confluence import ingest_confluence_minimal
        ingest_confluence_minimal(out)
    # other phases: placeholders
src/trailblazer/pipeline/steps/ingest/confluence.py
python
Copy
Edit
from pathlib import Path
from ....core.logging import log

def ingest_confluence_minimal(outdir: str) -> None:
    """
    Minimal placeholder that writes an empty NDJSON to prove pathing works.
    """
    p = Path(outdir) / "confluence.ndjson"
    p.write_text("", encoding="utf-8")
    log.info("ingest.confluence.wrote", file=str(p))
Placeholders for other step modules
python
Copy
Edit
# placeholder for HTML->Markdown normalization
(repeat simple # placeholder in each remaining step file)

src/trailblazer/cli/main.py
python
Copy
Edit
import typer
from typing import List, Optional
from ..core.logging import setup_logging, log
from ..core.config import SETTINGS
from ..pipeline.runner import run as run_pipeline

app = typer.Typer(add_completion=False, help="Trailblazer CLI")

@app.callback()
def _init() -> None:
    setup_logging()

@app.command()
def version() -> None:
    from .. import __version__
    typer.echo(__version__)

@app.command()
def run(
    phases: Optional[List[str]] = typer.Option(None, help="Subset of phases to run, in order"),
    dry_run: bool = typer.Option(False, help="Do not execute; just scaffold outputs"),
) -> None:
    rid = run_pipeline(phases=phases, dry_run=dry_run)
    log.info("cli.run.done", run_id=rid)

@app.command()
def config(mask_secrets: bool = typer.Option(True, help="Mask secrets in output")) -> None:
    for k, v in SETTINGS.model_dump().items():
        if mask_secrets and "TOKEN" in k:
            v = "***"
        typer.echo(f"{k}={v}")

if __name__ == "__main__":
    app()
tests/test_cli.py
python
Copy
Edit
def test_placeholder():
    assert 1 == 1
tests/test_run_id.py
python
Copy
Edit
from trailblazer.core.artifacts import new_run_id

def test_run_id_shape():
    rid = new_run_id()
    assert "_" in rid and len(rid.split("_")[-1]) == 4
Actions to Perform
Create all files above and save this prompt to prompts/000_scaffold_python_monorepo.md.

Install:

bash
Copy
Edit
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
Sanity checks:

bash
Copy
Edit
trailblazer --help
trailblazer run --dry-run --phases ingest normalize
pytest -q
ruff check .
black --check src tests
Git workflow (only if connected):

bash
Copy
Edit
git checkout -b scaffold/python-monorepo-v2-confluence
git add -A
git commit -m "scaffold: python monorepo + Confluence v2 (Basic auth), CLI, phases, tooling"
git push -u origin scaffold/python-monorepo-v2-confluence
Acceptance Criteria
trailblazer run --dry-run --phases ingest creates runs/<run_id>/ingest/confluence.ndjson.

trailblazer version prints 0.1.0.

ruff, black --check, and pytest -q succeed.

data/ and runs/ are untracked by git.

Confluence client defaults: https://ellucian.atlassian.net/wiki/api/v2, Basic auth, cursor pagination, and v1 CQL helper present.

Prompt saved in prompts/.

Notes
Do not number Python module names. Use nouns; order is in the DAG/runner.

All external calls are stubs—no network access in this scaffold.

Keep re-runs idempotent.

End of Prompt 000 (Rev A).

What this changes for later prompts (heads-up)
001_ingest_confluence: implement real v2 fetch (spaces→ids via /wiki/api/v2/spaces?keys=..., pages via /wiki/api/v2/pages?space-id=...&body-format=..., attachments via /wiki/api/v2/pages/{id}/attachments); use Basic auth. Use v1 /wiki/rest/api/content/search?cql=... for targeted deltas until a v2 search is public. Handle cursor pagination via Link header / _links.next. 
Atlassian Developer
+2
Atlassian Developer
+2

002_normalize_html_to_md and onward remain the same architecture-wise.

Quick flags for you
Mind file: now's the time. Create docs/trailblazer-mindfile.md to capture: "Confluence v2 + Basic auth," "v1 CQL for search," cursor-pagination rules, and invariants.

When to use Pro/MAX: for large multi-file writes/refactors and long prompts (like this scaffold), use MAX for better context retention. If Cursor starts truncating diffs or drops files from the edit set, switching to MAX will help.

Sources (for the v2 + Basic decisions)
Confluence Cloud REST v2 reference; shows /wiki/api/v2/... and cursor pagination. 
Atlassian Developer

Page endpoints (GET /pages, GET /spaces/{id}/pages) & body-format param. 
Atlassian Developer

Attachment endpoints (/pages/{id}/attachments) with downloadLink. 
Atlassian Developer

Basic auth (email + API token) for Cloud REST APIs. 
Atlassian Developer

CQL search (v1) usage + limits; use /wiki/rest/api/content/search?cql=..., be aware of 50-result quirks on expansions. 
Atlassian Developer
Atlassian Support
