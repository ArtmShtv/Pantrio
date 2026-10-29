from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

# Pydantic writes Decimal to JSON as a string ("12.50"). The spec wants numbers.
Num = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class Page[T](BaseModel):
    items: list[T]
    total: int
