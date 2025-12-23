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

    # LLM configuration (optional)
    llm_type: str | None = None  # "openai", "anthropic", or "ollama"
    llm_api_url: str | None = None  # API URL (required for ollama, optional for others)
    llm_api_token: str | None = None  # API token (not needed for ollama)
    llm_model: str | None = (
        None  # Model name (e.g., "gpt-5-mini", "claude-3-haiku-20240307", "llama3")
    )
    llm_language: str = "English"  # Language for LLM responses

    @property
    def llm_enabled(self) -> bool:
        """Check if LLM is configured."""
        if not self.llm_type:
            return False
        if self.llm_type == "ollama":
            return bool(self.llm_api_url)
        return bool(self.llm_api_token)

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
