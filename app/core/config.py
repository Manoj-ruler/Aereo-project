"""Application configuration, loaded from environment variables / ``.env``."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BYTES_PER_MB = 1024 * 1024


class Settings(BaseSettings):
    """Runtime settings. Every field can be overridden by an environment variable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./data/app.db"
    storage_dir: Path = Path("./storage")
    max_upload_size_mb: int = Field(default=25, gt=0)
    max_zip_files: int = Field(default=100, gt=0)
    max_zip_uncompressed_mb: int = Field(default=200, gt=0)
    log_level: str = "INFO"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * BYTES_PER_MB

    @property
    def max_zip_uncompressed_bytes(self) -> int:
        return self.max_zip_uncompressed_mb * BYTES_PER_MB


@lru_cache
def get_settings() -> Settings:
    return Settings()
