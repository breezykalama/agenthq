from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(database_url: str) -> str:
    for prefix in ("postgres://", "postgresql://"):
        if database_url.startswith(prefix):
            return database_url.replace(prefix, "postgresql+psycopg://", 1)
    return database_url


class CorsSettings(BaseSettings):
    backend_cors_origins: str = Field(default="", alias="BACKEND_CORS_ORIGINS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_cors_origins() -> list[str]:
    origins = CorsSettings().backend_cors_origins
    return [origin.strip().rstrip("/") for origin in origins.split(",") if origin.strip()]


class Settings(BaseSettings):
    app_name: str = "AgentHQ"
    environment: str = "development"
    database_url: PostgresDsn = Field(alias="DATABASE_URL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_uri(self) -> str:
        return normalize_database_url(str(self.database_url))


@lru_cache
def get_settings() -> Settings:
    return Settings()
