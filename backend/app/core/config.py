"""Backend settings loaded from environment variables and computed helpers."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE_PATH = REPO_ROOT / ".env"


def _read_backend_version() -> str:
    """Read the backend package version from `backend/pyproject.toml`."""
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"

    try:
        with pyproject_path.open("rb") as pyproject_file:
            project_data = tomllib.load(pyproject_file)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return "0.1.0"

    version = project_data.get("project", {}).get("version")
    if isinstance(version, str) and version:
        return version
    return "0.1.0"


class Settings(BaseSettings):
    """Runtime configuration for the backend application."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_ignore_empty=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "app"
    APP_VERSION: str = _read_backend_version()
    APP_BUILD: str | None = None
    APP_COMMIT_SHA: str | None = None
    APP_BRANCH: str | None = None
    ENVIRONMENT: Literal["local", "dev", "staging", "production"] = "local"
    APP_LOG_LEVEL: str = "INFO"
    BACKEND_CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # PostgreSQL
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    # Authentication (app-local users + JWT in an httpOnly cookie)
    APP_SECRET: str = "dev-insecure-secret-change-in-production-please"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    AUTH_COOKIE_NAME: str = "catalogai_session"
    AUTH_COOKIE_SECURE: bool = False  # set True behind HTTPS in prod
    # Optional first user, created by `python -m app.initial_data`.
    FIRST_SUPERUSER: str = ""
    FIRST_SUPERUSER_PASSWORD: str = ""

    # Xano (Tillin REST API — first destination adapter; read path for now)
    XANO_BASE_URL: str = ""
    XANO_SERVICE_TOKEN: str = ""
    XANO_TIMEOUT_SECONDS: float = 30.0

    @property
    def xano_configured(self) -> bool:
        """Whether the Xano read path has the base URL and token it needs."""
        return bool(self.XANO_BASE_URL and self.XANO_SERVICE_TOKEN)

    @property
    def BACKEND_CORS_ORIGIN_LIST(self) -> list[str]:
        """Parse allowed CORS origins as a de-duplicated ordered list."""
        seen: set[str] = set()
        origins: list[str] = []
        for value in self.BACKEND_CORS_ORIGINS.split(","):
            origin = value.strip()
            if origin and origin not in seen:
                seen.add(origin)
                origins.append(origin)
        return origins

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        """Assemble the SQLAlchemy DSN from PostgreSQL settings."""
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )


settings = Settings()  # type: ignore[call-arg]
