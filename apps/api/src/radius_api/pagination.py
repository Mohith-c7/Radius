"""Shared limit/offset pagination for list endpoints (C-11).

Every list endpoint takes ``limit`` (default 100, hard maximum 500) and ``offset``
and reports ``meta.pagination = {limit, offset, total, returned}``. The response
``data`` stays a plain list, so existing clients keep working (they now receive
the newest ``limit`` items instead of everything).
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_OFFSET = 1_000_000


@dataclass(frozen=True, slots=True)
class Page:
    """Requested page window."""

    limit: int
    offset: int

    def slice[T](self, items: list[T]) -> list[T]:
        return items[self.offset : self.offset + self.limit]

    def meta(self, *, total: int, returned: int) -> dict[str, object]:
        return {
            "pagination": {
                "limit": self.limit,
                "offset": self.offset,
                "total": total,
                "returned": returned,
            }
        }


def get_page(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Page size (max 500).")] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET, description="Items to skip.")] = 0,
) -> Page:
    return Page(limit=limit, offset=offset)


PageParams = Annotated[Page, Depends(get_page)]
