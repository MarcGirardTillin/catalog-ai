"""Minimal example route for the template."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(
    prefix="/example",
    tags=["example"],
)


class ExampleResponse(BaseModel):
    """Response payload returned by the example endpoint."""

    status: str
    message: str
    sample_id: int


@router.get("", response_model=ExampleResponse)
def read_example(
    sample_id: int = Query(default=1, ge=1),
) -> ExampleResponse:
    """Return a small payload without touching the database."""
    return ExampleResponse(
        status="ok",
        message="Example endpoint reached",
        sample_id=sample_id,
    )
