"""Jetons d'API personnels (serveur MCP : Claude Code, Codex…).

Un jeton appartient à un utilisateur et agit EXACTEMENT avec ses droits
(modules du compte, scoping, crédits). Seul le hachage SHA-256 est stocké ;
le jeton en clair n'est affiché qu'une fois, à la création.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiToken(Base):
    __tablename__ = "api_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    # Début du jeton (`cat_xxxxxxxx`) : identifie le jeton dans la liste.
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
