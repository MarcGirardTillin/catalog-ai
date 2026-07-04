"""JWT access tokens for the session cookie."""

from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings


def create_access_token(subject: str | int) -> str:
    """Create a signed JWT carrying the user id as ``sub``."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.APP_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the ``sub`` claim if the token is valid, otherwise ``None``."""
    try:
        payload = jwt.decode(
            token, settings.APP_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.InvalidTokenError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
