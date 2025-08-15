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
    OPENAI_API_KEY: Optional[str] = None

    # Workspace paths
    TRAILBLAZER_DATA_DIR: str = "data"  # Human-managed inputs
    TRAILBLAZER_WORKDIR: str = "var"  # Tool-managed artifacts

    # Observability
    LOG_FORMAT: str = "auto"  # json|plain|auto
    PROGRESS: bool = True
    QUIET_PRETTY: bool = False
    NO_COLOR: bool = False

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
                import tomllib

                with open(config_path, "rb") as f:
                    config_data = tomllib.load(f)

        # Create settings with config data as defaults
        # Environment variables and CLI args will override these
        return cls(**config_data)


# Default settings - will be replaced by load_config() during CLI startup
SETTINGS = Settings()
