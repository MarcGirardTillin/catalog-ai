"""Backend settings loaded from environment variables and computed helpers."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]
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
    # libpq sslmode, appended to the DSN when set. Empty = libpq's default
    # ("prefer": TLS when the server offers it, plaintext otherwise) — fine for
    # the local Docker database. Managed databases reached over the network
    # (Scaleway) must set "require" so a downgrade to plaintext fails loudly.
    POSTGRES_SSLMODE: str = ""

    # Authentication (app-local users + JWT in an httpOnly cookie)
    APP_SECRET: str = "dev-insecure-secret-change-in-production-please"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    AUTH_COOKIE_NAME: str = "catalogai_session"
    AUTH_COOKIE_SECURE: bool = False  # set True behind HTTPS in prod
    # Optional first user, created by `python -m app.initial_data`.
    FIRST_SUPERUSER: str = ""
    FIRST_SUPERUSER_PASSWORD: str = ""

    # Xano (Tillin REST API — first destination adapter; read path for now).
    # Auth is email/password login -> a bearer `authToken` (JWT); there is no
    # static service token on this workspace.
    XANO_BASE_URL: str = ""
    XANO_LOGIN_EMAIL: str = ""
    XANO_LOGIN_PASSWORD: str = ""
    # Xano datasource selector: empty = live/default, "test" = the seeded test
    # datasource (sent as the `X-Data-Source` header on every call).
    XANO_DATA_SOURCE: str = ""
    XANO_TIMEOUT_SECONDS: float = 30.0

    # Where uploaded supplier files (imports) are stored. Created on demand.
    UPLOAD_DIR: str = str(BACKEND_DIR / "var" / "uploads")
    # Ephemeral staging for processed/generated images (imaging sprint) — the
    # durable store is Xano; this only holds previews until save/purge.
    IMAGING_DIR: str = str(BACKEND_DIR / "var" / "imaging")

    # External service clients (all optional: empty key = integration disabled).
    ANTHROPIC_API_KEY: str = ""
    AI_DEFAULT_MODEL: str = "claude-sonnet-5"
    PHOTOROOM_API_KEY: str = ""
    FASHN_API_KEY: str = ""
    FIRECRAWL_API_KEY: str = ""
    BREVO_API_KEY: str = ""
    BREVO_SENDER_EMAIL: str = ""
    BREVO_SENDER_NAME: str = "CatalogAI"

    @property
    def xano_configured(self) -> bool:
        """Whether the Xano read path has the base URL and login it needs."""
        return bool(
            self.XANO_BASE_URL and self.XANO_LOGIN_EMAIL and self.XANO_LOGIN_PASSWORD
        )

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
            query=f"sslmode={self.POSTGRES_SSLMODE}" if self.POSTGRES_SSLMODE else None,
        )


settings = Settings()  # type: ignore[call-arg]
