from typing import Any, Literal

from pydantic import BaseModel, Field, NonNegativeInt
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class PaginationParams(BaseModel):
    page: NonNegativeInt = Field(default=1, ge=1, description="Page number")
    page_size: NonNegativeInt = Field(
        default=20, ge=1, le=100, description="Number of items per page"
    )


class SortingParams(BaseModel):
    sort_by: str | None = Field(default=None, description="Column to sort by")
    sort_order: Literal["asc", "desc"] = Field(default="desc", description="Sort order")


class PaginatedResponse[T: BaseModel](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


def paginate_query[T: BaseModel](
    db: Session,
    query: Select[Any],
    pagination: PaginationParams,
    pydantic_model: type[T],
) -> PaginatedResponse[T]:
    total_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(total_query) or 0

    paged_query = query.offset((pagination.page - 1) * pagination.page_size).limit(
        pagination.page_size
    )
    result = db.execute(paged_query)
    items = result.scalars().all()

    pydantic_items: list[T] = [
        pydantic_model.model_validate(item, from_attributes=True) for item in items
    ]
    total_pages = (total + pagination.page_size - 1) // pagination.page_size

    return PaginatedResponse(
        items=pydantic_items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=total_pages,
    )
