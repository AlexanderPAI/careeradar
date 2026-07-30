from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_MARKERS = (
    "changeme",
    "replacewith",
    "placeholder",
    "example",
    "demosecret",
    "defaultsecret",
    "yourjwtsecret",
)
_KNOWN_WEAK_SECRETS = {
    "password",
    "postgres",
    "careeradar",
    "secret",
    "jwtsecret",
    "testsecret",
}


def _normalized_secret(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _is_repeated_pattern(value: str) -> bool:
    for pattern_length in range(1, len(value) // 2 + 1):
        if len(value) % pattern_length == 0:
            pattern = value[:pattern_length]
            if pattern * (len(value) // pattern_length) == value:
                return True
    return False


def _validate_production_secret(
    name: str,
    value: str,
    *,
    minimum_length: int,
    minimum_unique_characters: int,
) -> None:
    normalized = _normalized_secret(value)
    if (
        len(value) < minimum_length
        or len(set(value)) < minimum_unique_characters
        or _is_repeated_pattern(value)
        or normalized in _KNOWN_WEAK_SECRETS
        or any(marker in normalized for marker in _PLACEHOLDER_MARKERS)
    ):
        raise ValueError(
            f"{name} небезопасен для production: используйте случайное значение "
            f"длиной не менее {minimum_length} символов"
        )


class Settings(BaseSettings):
    def __init__(self, **values: object) -> None:
        super().__init__(**values)
        self._validate_production_security()

    app_env: Literal["development", "test", "production"] = Field(
        "development", env="APP_ENV"
    )
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
        True,
        env="GIGACHAT_VERIFY_SSL_CERTS",
        description="Verify TLS certificates for GigaChat requests",
    )
    gigachat_root_ca_file: str = Field(
        "backend/certs/russian_trusted_root_ca.pem",
        env="GIGACHAT_ROOT_CA_FILE",
    )
    gigachat_sub_ca_file: str = Field(
        "backend/certs/russian_trusted_sub_ca.pem",
        env="GIGACHAT_SUB_CA_FILE",
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
    auth_rate_limit_window_seconds: int = Field(
        900, ge=60, env="AUTH_RATE_LIMIT_WINDOW_SECONDS"
    )
    auth_rate_limit_username_attempts: int = Field(
        5, ge=1, env="AUTH_RATE_LIMIT_USERNAME_ATTEMPTS"
    )
    auth_rate_limit_ip_attempts: int = Field(
        20, ge=1, env="AUTH_RATE_LIMIT_IP_ATTEMPTS"
    )
    auth_failure_delay_base_seconds: float = Field(
        0.25, ge=0.0, env="AUTH_FAILURE_DELAY_BASE_SECONDS"
    )
    auth_failure_delay_max_seconds: float = Field(
        4.0, ge=0.0, env="AUTH_FAILURE_DELAY_MAX_SECONDS"
    )
    resume_upload_max_bytes: int = Field(
        10 * 1024 * 1024, ge=1024, env="RESUME_UPLOAD_MAX_BYTES"
    )
    resume_docx_max_entries: int = Field(2000, ge=10, env="RESUME_DOCX_MAX_ENTRIES")
    resume_docx_max_uncompressed_bytes: int = Field(
        25 * 1024 * 1024,
        ge=1024,
        env="RESUME_DOCX_MAX_UNCOMPRESSED_BYTES",
    )
    resume_docx_max_compression_ratio: float = Field(
        100.0, ge=1.0, env="RESUME_DOCX_MAX_COMPRESSION_RATIO"
    )
    resume_retention_days: int = Field(30, ge=1, env="RESUME_RETENTION_DAYS")
    resume_cleanup_interval_minutes: int = Field(
        60, ge=1, env="RESUME_CLEANUP_INTERVAL_MINUTES"
    )

    @field_validator("llm_provider", mode="before")
    @classmethod
    def normalize_llm_provider(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator(
        "openrouter_key",
        "gigachat_key",
        "jwt_secret",
        "postgres_password",
        mode="before",
    )
    @classmethod
    def strip_secret_quotes(cls, value: str) -> str:
        """Docker env files may preserve quotes as part of a secret value."""
        value = str(value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        return value

    def _validate_production_security(self) -> None:
        if self.app_env != "production":
            return
        if not self.gigachat_verify_ssl_certs:
            raise ValueError(
                "GIGACHAT_VERIFY_SSL_CERTS=false запрещён при APP_ENV=production"
            )
        _validate_production_secret(
            "JWT_SECRET",
            self.jwt_secret,
            minimum_length=48,
            minimum_unique_characters=12,
        )
        _validate_production_secret(
            "POSTGRES_PASSWORD",
            self.postgres_password,
            minimum_length=20,
            minimum_unique_characters=10,
        )
        if self.postgres_password == self.jwt_secret:
            raise ValueError(
                "JWT_SECRET и POSTGRES_PASSWORD должны быть разными значениями"
            )
        provider_key = (
            self.gigachat_key
            if self.llm_provider == "gigachat"
            else self.openrouter_key
        )
        normalized_key = _normalized_secret(provider_key)
        if (
            len(provider_key) < 16
            or not normalized_key
            or normalized_key.startswith(("your", "replacewith", "changeme"))
        ):
            raise ValueError(
                f"Ключ провайдера {self.llm_provider} не задан или является шаблоном"
            )

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
