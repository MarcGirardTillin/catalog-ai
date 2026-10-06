"""OAuth 2.1 du serveur MCP (connecteur claude.ai) : clients, autorisations,
jetons.

Persisté en base — le backend tourne sur plusieurs workers, un stockage en
mémoire perdrait une autorisation d'un processus à l'autre. Les codes et les
jetons ne sont stockés que hachés (SHA-256).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OAuthClient(Base):
    """Client enregistré dynamiquement (RFC 7591, ex. claude.ai)."""

    __tablename__ = "oauth_client"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # OAuthClientInformationFull sérialisé (redirect_uris, nom, méthode…).
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OAuthAuthorization(Base):
    """Demande d'autorisation : en attente de consentement, puis code émis."""

    __tablename__ = "oauth_authorization"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identifiant opaque de la demande, passé à la page de consentement.
    request_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_client.client_id"), index=True
    )
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_explicit: Mapped[bool] = mapped_column(default=True)
    scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    state: Mapped[str | None] = mapped_column(Text, default=None)
    code_challenge: Mapped[str] = mapped_column(String(128))
    resource: Mapped[str | None] = mapped_column(Text, default=None)
    # Renseignés au consentement.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    code_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, default=None
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OAuthToken(Base):
    """Jeton d'accès ou de rafraîchissement émis à un client pour un
    utilisateur. `family` relie un jeton d'accès à son jeton de
    rafraîchissement (révocation conjointe, rotation)."""

    __tablename__ = "oauth_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # "access" | "refresh"
    family: Mapped[str] = mapped_column(String(64), index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_client.client_id"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    resource: Mapped[str | None] = mapped_column(Text, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
