"""Request/response schemas for the editorial instruction library."""

from datetime import datetime

from pydantic import BaseModel, Field


class InstructionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)
    # Tillin category names this instruction is the default for.
    categories: list[str] = Field(default_factory=list)


class InstructionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)
    categories: list[str] = Field(default_factory=list)


class InstructionPublic(BaseModel):
    id: int
    name: str
    content: str
    categories: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
