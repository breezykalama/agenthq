from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def get_pagination(
    limit: Annotated[int, Query(ge=1)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=min(limit, MAX_LIMIT), offset=offset)


PaginationParams = Annotated[Pagination, Depends(get_pagination)]
