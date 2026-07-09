"""Request/response schemas for the Tillin locations (import destinations)."""

from pydantic import BaseModel


class LocationPublic(BaseModel):
    """A Tillin boutique location a CSV import can be transferred to."""

    id: int
    title: str
