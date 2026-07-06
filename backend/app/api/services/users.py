"""User persistence and authentication helpers."""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models import User


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def create_user(
    db: Session, *, email: str, password: str, full_name: str | None = None
) -> User:
    """Create and persist a new user with a hashed password."""
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_or_create_federated_user(
    db: Session, *, email: str, full_name: str | None = None
) -> User:
    """Find a user by email, or create one for an externally-authenticated login.

    Used when a user signs in via Xano credentials: there is no local password,
    so a random unusable one is stored (they can only authenticate upstream).
    """
    user = get_user_by_email(db, email)
    if user is not None:
        return user
    return create_user(
        db, email=email, password=secrets.token_urlsafe(32), full_name=full_name
    )


def authenticate_user(db: Session, *, email: str, password: str) -> User | None:
    """Return the user when credentials are valid and the account is active."""
    user = get_user_by_email(db, email)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
