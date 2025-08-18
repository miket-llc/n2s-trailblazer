from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List, Dict, Any
from pathlib import Path


class Settings(BaseSettings):
    # Confluence (Cloud v2 + Basic auth)
    CONFLUENCE_BASE_URL: str = "https://ellucian.atlassian.net/wiki"
    CONFLUENCE_EMAIL: Optional[str] = None
    CONFLUENCE_API_TOKEN: Optional[str] = None
    CONFLUENCE_BODY_FORMAT: str = "atlas_doc_format"  # or "storage"
    CONFLUENCE_SPACES: List[str] = []  # Default spaces to ingest
    CONFLUENCE_SINCE: Optional[str] = None  # Default since timestamp
    CONFLUENCE_AUTO_SINCE: bool = True  # Auto-read since from state
    CONFLUENCE_MAX_PAGES: Optional[int] = None  # Limit for testing
    CONFLUENCE_ALLOW_EMPTY: bool = False  # Allow zero pages without error

    # DITA configuration
    DITA_ROOT: str = "data/raw/dita/ellucian-documentation"
    DITA_INCLUDE: List[str] = []  # Default: **/*.dita, **/*.xml, **/*.ditamap
    DITA_EXCLUDE: List[str] = []  # Exclude patterns

    # Pipeline configuration
    PIPELINE_PHASES: List[str] = ["ingest", "normalize", "enrich", "embed"]
    PIPELINE_WORKERS: int = 2  # Default concurrency

    # Database (required for embed/ask)
    TRAILBLAZER_DB_URL: Optional[str] = None

    # Embedding configuration
    EMBED_PROVIDER: str = "openai"
    EMBED_MODEL: str = "text-embedding-3-small"
    EMBED_DIMENSIONS: int = 1536
    EMBED_BATCH_SIZE: int = 128
    EMBED_CHANGED_ONLY: bool = True  # Only embed changed documents
    EMBED_MAX_DOCS: Optional[int] = None  # Limit for testing
    EMBED_MAX_CHUNKS: Optional[int] = None  # Limit for testing
    EMBED_DRY_RUN_COST: bool = False  # Show cost estimates
    OPENAI_API_KEY: Optional[str] = None

    # Retrieval/Ask configuration
    ASK_TOP_K: int = 8  # Number of top chunks to retrieve
    ASK_MAX_CHUNKS_PER_DOC: int = 3  # Maximum chunks per document
    ASK_MAX_CHARS: int = 6000  # Maximum characters in context
    ASK_FORMAT: str = "text"  # Output format: text|json

    # Enrichment configuration
    ENRICH_LLM: bool = False  # Enable LLM-based enrichment
    ENRICH_MAX_DOCS: Optional[int] = None  # Limit for testing
    ENRICH_BUDGET: Optional[str] = None  # Budget limit for LLM usage

    # Workspace paths
    TRAILBLAZER_DATA_DIR: str = "data"  # Human-managed inputs
    TRAILBLAZER_WORKDIR: str = "var"  # Tool-managed artifacts

    # Observability & UI
    LOG_FORMAT: str = "auto"  # json|plain|auto
    PROGRESS: bool = True  # Show progress bars
    PROGRESS_EVERY: int = 10  # Progress output frequency
    QUIET_PRETTY: bool = False  # Suppress banners but keep progress
    NO_COLOR: bool = False  # Disable colored output

    # Operations
    OPS_PRUNE_KEEP: int = 10  # Number of runs to keep when pruning
    OPS_PRUNE_MIN_AGE_DAYS: int = 30  # Minimum age for deletion
    OPS_PRUNE_DRY_RUN: bool = True  # Default to dry run for safety

    # Backlog configuration
    BACKLOG_MODE: str = "default_all_unprocessed"  # Backlog processing mode
    BACKLOG_CLAIM_TTL_MINUTES: int = 45  # TTL for stale claim recovery

    # Logging configuration
    LOGS_ROTATION_MB: int = 512  # Max size before rotating events.ndjson
    LOGS_COMPRESS_AFTER_DAYS: int = 2  # Compress segments older than N days
    LOGS_RETENTION_DAYS: int = 14  # Delete logs older than N days

    # Testing environment flag
    TB_TESTING: bool = Field(
        default=False,
        description="Enable testing mode for database integration tests",
    )
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8"
    )

    @classmethod
    def load_config(cls, config_file: Optional[str] = None) -> "Settings":
        """Load settings with config file -> env -> CLI precedence."""
        config_data: Dict[str, Any] = {}

        # Find config file
        if config_file:
            config_path = Path(config_file)
        else:
            # Auto-discover .trailblazer.{yaml,yml,toml}
            for ext in ["yaml", "yml", "toml"]:
                config_path = Path(f".trailblazer.{ext}")
                if config_path.exists():
                    break
            else:
                config_path = None

        # Load config file if found
        if config_path and config_path.exists():
            if config_path.suffix in [".yaml", ".yml"]:
                import yaml  # type: ignore[import-untyped]

                with open(config_path) as f:
                    config_data = yaml.safe_load(f) or {}
            elif config_path.suffix == ".toml":
                import tomllib  # type: ignore[import-untyped]

                with open(config_path, "rb") as f:
                    config_data = tomllib.load(f)

        # Create settings with config data as defaults
        # Environment variables and CLI args will override these
        return cls(**config_data)


# Default settings - will be replaced by load_config() during CLI startup
SETTINGS = Settings()
