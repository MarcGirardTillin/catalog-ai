"""Schemas des visages mannequins (face swap FASHN)."""

from datetime import datetime

from pydantic import BaseModel


class FaceReferencePublic(BaseModel):
    id: int
    name: str
    created_at: datetime
