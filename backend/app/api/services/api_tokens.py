"""Jetons d'API personnels : création, liste, révocation, authentification.

Format : `cat_<8 car.>_<secret>` — le préfixe (`cat_<8 car.>`) identifie le
jeton dans la liste, le secret (32 octets urlsafe) n'est jamais stocké : seul
le SHA-256 du jeton complet l'est. Un jeton agit avec les droits de son
utilisateur, vérifiés à chaque appel (compte actif, modules, crédits).
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.models import ApiToken, User

TOKEN_PREFIX = "cat_"
DEFAULT_TTL_DAYS = 90
MAX_TTL_DAYS = 365
MAX_ACTIVE_TOKENS = 10
# `last_used_at` n'est réécrit qu'au-delà de ce délai (pas une écriture par appel).
_TOUCH_INTERVAL = timedelta(minutes=5)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite (tests) relit les dates sans fuseau : on les suppose en UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def is_active(token: ApiToken, now: datetime | None = None) -> bool:
    now = now or _now()
    expires_at = _aware(token.expires_at)
    return token.revoked_at is None and (expires_at is None or expires_at > now)


def list_api_tokens(db: Session, user: User) -> list[ApiToken]:
    return list(
        db.scalars(
            select(ApiToken)
            .where(ApiToken.user_id == user.id)
            .order_by(ApiToken.id.desc())
        ).all()
    )


def create_api_token(
    db: Session, user: User, *, name: str, ttl_days: int = DEFAULT_TTL_DAYS
) -> tuple[ApiToken, str]:
    """Crée un jeton ; renvoie la ligne et le jeton EN CLAIR (affiché une fois)."""
    active = [token for token in list_api_tokens(db, user) if is_active(token)]
    if len(active) >= MAX_ACTIVE_TOKENS:
        raise AppException(
            status_code=409,
            code="too_many_tokens",
            message=f"{MAX_ACTIVE_TOKENS} jetons actifs au plus : révoquez-en un.",
        )
    prefix = TOKEN_PREFIX + secrets.token_hex(4)
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    token = ApiToken(
        user_id=user.id,
        name=name.strip(),
        prefix=prefix,
        token_hash=hash_token(raw),
        expires_at=_now() + timedelta(days=min(ttl_days, MAX_TTL_DAYS)),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token, raw


def revoke_api_token(db: Session, user: User, token_id: int) -> ApiToken:
    token = db.get(ApiToken, token_id)
    if token is None or token.user_id != user.id:
        raise AppException(
            status_code=404, code="not_found", message="Jeton introuvable"
        )
    if token.revoked_at is None:
        token.revoked_at = _now()
        db.commit()
        db.refresh(token)
    return token


def authenticate_api_token(db: Session, raw: str) -> tuple[ApiToken, User] | None:
    """Jeton actif + utilisateur actif, sinon None (jamais d'exception)."""
    if not raw.startswith(TOKEN_PREFIX):
        return None
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    now = _now()
    if token is None or not is_active(token, now):
        return None
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        return None
    last_used = _aware(token.last_used_at)
    if last_used is None or now - last_used > _TOUCH_INTERVAL:
        token.last_used_at = now
        db.commit()
    return token, user
