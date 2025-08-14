from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List


class Settings(BaseSettings):
    # Confluence (Cloud v2 + Basic auth)
    CONFLUENCE_BASE_URL: str = "https://ellucian.atlassian.net/wiki"
    CONFLUENCE_EMAIL: Optional[str] = None
    CONFLUENCE_API_TOKEN: Optional[str] = None
    CONFLUENCE_BODY_FORMAT: str = "atlas_doc_format"  # or "storage"

    # Pipeline
    PIPELINE_PHASES: List[str] = []

    # Database (optional at scaffold time)
    TRAILBLAZER_DB_URL: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8"
    )


SETTINGS = Settings()
