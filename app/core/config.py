from functools import lru_cache
from typing import Literal

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

    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "relaydesk"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    password_reset_ttl_minutes: int = 30
    login_max_failed_attempts: int = 5
    login_lockout_minutes: int = 15
    rate_limit_per_minute: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
