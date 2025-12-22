"""Application configuration from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Required
    paperless_url: str
    paperless_api_token: str

    # Optional
    port: int = 8000
    log_level: str = "info"
    exclude_patterns: str = "new,inbox,todo,review"

    @property
    def exclude_pattern_list(self) -> list[str]:
        """Get exclusion patterns as a list."""
        return [p.strip() for p in self.exclude_patterns.split(",") if p.strip()]

    @property
    def paperless_base_url(self) -> str:
        """Get the Paperless URL with trailing slash removed."""
        return self.paperless_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
