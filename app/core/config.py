from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SECRET_KEY: str

    ENVIRONMENT: Literal["local", "test", "production"] = "local"

    POSTGRES_USER: str
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_DB: str
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DB_ECHO: bool = False

    JWT_SECRET: SecretStr = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    # iss/aud claims: a token minted by another service that happens to share
    # the secret (or a token meant for a different API) is rejected.
    JWT_ISSUER: str = "pantrio"
    JWT_AUDIENCE: str = "pantrio-api"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 30
    SESSION_SECRET: SecretStr = Field(min_length=32)

    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: SecretStr | None = None
    YANDEX_CLIENT_ID: str | None = None
    YANDEX_CLIENT_SECRET: SecretStr | None = None
    VK_CLIENT_ID: str | None = None
    VK_CLIENT_SECRET: SecretStr | None = None

    @property
    def DATABASE_ASYNC_URL(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )

    @property
    def DATABASE_SYNC_URL(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()