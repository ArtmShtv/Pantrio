from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

Num = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class Page[T](BaseModel):
    items: list[T]
    total: int
