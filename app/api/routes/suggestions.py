from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser
from app.schemas.suggestions import MealSuggestion
from app.services import suggestions as service
from app.services.suggestions import Strategy

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


@router.get(
    "/meals",
    response_model=list[MealSuggestion],
    summary="Meals ranked by how much of them your pantry already covers",
    description=(
        "Scores one batch of each recipe. `share`: average coverage per ingredient. "
        "`grams`: covered grams / needed grams. `money`: share of the meal's cost "
        "already at home. Meals with score 0 are left out."
    ),
)
async def suggest_meals(
    user: CurrentUser,
    db: DB,
    strategy: Strategy = Strategy.GRAMS,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    result = await service.suggest(db, user, strategy=strategy, limit=limit)
    return [MealSuggestion.from_service(s) for s in result]
