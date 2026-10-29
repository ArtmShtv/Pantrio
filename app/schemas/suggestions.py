from decimal import Decimal
from typing import Self

from pydantic import BaseModel

from app.schemas.common import Num
from app.schemas.plans import MealRef
from app.schemas.products import IngredientRef
from app.services.calc import ONE_DECIMAL, round_to
from app.services.suggestions import Suggestion

SCORE_STEP = Decimal("0.001")


class CoveredLine(BaseModel):
    ingredient: IngredientRef
    have_g: Num
    need_g: Num


class MissingLine(BaseModel):
    ingredient: IngredientRef
    missing_g: Num


class MealSuggestion(BaseModel):
    meal: MealRef
    score: Num
    covered: list[CoveredLine]
    missing: list[MissingLine]

    @classmethod
    def from_service(cls, s: Suggestion) -> Self:
        def ref(ln) -> IngredientRef:
            return IngredientRef(id=ln.ingredient.id, name=ln.ingredient.name)

        lines = sorted(s.lines, key=lambda ln: (ln.ingredient.name.lower(), ln.ingredient.id))
        return cls(
            meal=MealRef(id=s.meal.id, name=s.meal.name),
            score=round_to(s.score, SCORE_STEP),
            covered=[
                CoveredLine(
                    ingredient=ref(ln),
                    have_g=round_to(ln.have_g, ONE_DECIMAL),
                    need_g=round_to(ln.need_g, ONE_DECIMAL),
                )
                for ln in lines
                if ln.have_g > 0
            ],
            missing=[
                MissingLine(
                    ingredient=ref(ln), missing_g=round_to(ln.need_g - ln.have_g, ONE_DECIMAL)
                )
                for ln in lines
                if ln.have_g < ln.need_g
            ],
        )
