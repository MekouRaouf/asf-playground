from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-based configuration. No defaults for secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "RelayDesk"
    environment: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    database_url: str
    secret_key: SecretStr
    db_connect_timeout: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
