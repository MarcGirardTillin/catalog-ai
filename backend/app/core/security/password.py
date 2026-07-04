"""Password hashing helpers (bcrypt)."""

import bcrypt

# bcrypt only considers the first 72 bytes of the password.
_MAX_BYTES = 72


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a bcrypt hash for the given plaintext password."""
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Return whether the plaintext password matches the stored hash."""
    try:
        return bcrypt.checkpw(_encode(password), hashed_password.encode("utf-8"))
    except ValueError:
        return False
