from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider: Literal["gigachat", "openrouter"] = Field(
        "gigachat", env="LLM_PROVIDER", description="Default LLM provider"
    )
    openrouter_key: str = Field(
        ..., env="OPENROUTER_KEY", description="OpenRouter API key"
    )
    gigachat_key: str = Field(
        ..., env="GIGACHAT_KEY", description="GigaChat authorization key"
    )
    gigachat_model: str = Field(
        "GigaChat", env="GIGACHAT_MODEL", description="GigaChat model"
    )
    gigachat_url: str = Field(
        "https://api.giga.chat/v1/chat/completions",
        env="GIGACHAT_URL",
        description="GigaChat chat completions URL",
    )
    gigachat_verify_ssl_certs: bool = Field(
        False,
        env="GIGACHAT_VERIFY_SSL_CERTS",
        description="Verify TLS certificates for GigaChat requests",
    )

    postgres_user: str = Field(
        ..., env="POSTGRES_USER", description="Postgres user name"
    )
    postgres_password: str = Field(
        ..., env="POSTGRES_PASSWORD", description="Postgres password"
    )
    postgres_host: str = Field(
        ..., env="POSTGRES_HOST", description="Postgres host name"
    )
    postgres_port: int = Field(..., env="POSTGRES_PORT", description="Postgres port")
    postgres_db: str = Field(
        ..., env="POSTGRES_DB", description="Postgres database name"
    )
    jwt_secret: str = Field(..., min_length=32, env="JWT_SECRET")
    jwt_expire_minutes: int = Field(480, env="JWT_EXPIRE_MINUTES")
    resume_retention_days: int = Field(30, ge=1, env="RESUME_RETENTION_DAYS")
    resume_cleanup_interval_minutes: int = Field(
        60, ge=1, env="RESUME_CLEANUP_INTERVAL_MINUTES"
    )

    @field_validator("llm_provider", mode="before")
    @classmethod
    def normalize_llm_provider(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("openrouter_key", "gigachat_key", "jwt_secret", mode="before")
    @classmethod
    def strip_secret_quotes(cls, value: str) -> str:
        """Docker env files may preserve quotes as part of a secret value."""
        value = str(value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @property
    def postgres_url(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=f"{self.postgres_db}",
            )
        )


cfg = Settings()
