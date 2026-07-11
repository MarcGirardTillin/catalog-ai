"""Authentication request/response schemas."""

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """Credentials submitted to the login endpoint."""

    email: EmailStr
    password: str


class UserPublic(BaseModel):
    """Public-facing representation of a user."""

    id: int
    email: EmailStr
    full_name: str | None = None
    is_active: bool
    # Platform operator: unlocks the admin console (pricing, per-client
    # monitoring). Regular client users are always False.
    is_admin: bool = False
