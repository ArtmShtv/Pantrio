import secrets
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.catalog import Ingredient
from app.db.models.enums import MealType, Unit
from app.db.models.meal import Meal, RecipeItem
from app.db.models.pantry import Leftover
from app.db.models.plan import PlanSlot
from app.services.shopping import Pack, build_line, choose_pack, needs_from_slots, packs_needed


def pack(id=1, size="900", price="119.90", own=True) -> Pack:
    return Pack(id, f"pack {id}", "Magnit", D(size), D(price), own)


@pytest.mark.parametrize(
    ("to_buy", "size", "expected"),
    [("900", "900", 1), ("900.01", "900", 2), ("1", "900", 1), ("1800", "900", 2)],
)
def test_packs_needed_rounds_up(to_buy, size, expected):
    assert packs_needed(D(to_buy), D(size)) == expected


def test_line_cost_and_surplus():
    line = build_line(1, D("1000"), D("0"), [pack(size="900", price="119.90")], use_pantry=True)
    assert (line.to_buy_g, line.packs, line.cost, line.surplus_g) == (
        D("1000"),
        2,
        D("239.80"),
        D("800"),
    )


def test_pantry_reduces_what_to_buy():
    line = build_line(1, D("900"), D("200"), [pack()], use_pantry=True)
    assert (line.in_pantry_g, line.to_buy_g, line.packs, line.surplus_g) == (
        D("200"),
        D("700"),
        1,
        D("200"),
    )


def test_pantry_covering_everything_drops_the_line():
    assert build_line(1, D("900"), D("900"), [pack()], use_pantry=True) is None
    assert build_line(1, D("900"), D("5000"), [pack()], use_pantry=True) is None


def test_use_pantry_false_ignores_it():
    line = build_line(1, D("900"), D("900"), [pack()], use_pantry=False)
    assert line.to_buy_g == D("900") and line.in_pantry_g == D("900")


def test_no_product_gives_line_without_cost():
    line = build_line(1, D("100"), D("0"), [], use_pantry=True)
    assert line.pack is None and line.cost is None and line.packs is None
    assert line.to_buy_g == D("100")


def test_choose_cheapest_for_the_amount_not_per_gram():
    small = pack(1, size="400", price="79.90")  # 199.75/kg
    big = pack(2, size="5000", price="499.00")  # 99.80/kg, but 499 for 100 g of need
    assert choose_pack(D("100"), [small, big]) == small
    assert choose_pack(D("3000"), [small, big]) == big  # 8 x 79.90 = 639.20 > 499


def test_tie_on_cost_prefers_less_surplus():
    a = pack(1, size="1000", price="100")
    c = pack(3, size="900", price="100")
    assert choose_pack(D("850"), [a, c]) == c  # both 100, c leaves 50 g not 150 g


def test_own_products_beat_global_even_if_dearer():
    own = pack(1, price="200", own=True)
    glob = pack(2, price="100", own=False)
    assert choose_pack(D("100"), [own, glob]) == own
    assert choose_pack(D("100"), [glob]) == glob


def _ingredient(id, **kw) -> Ingredient:
    return Ingredient(id=id, name=f"i{id}", calories=0, protein=0, fat=0, carbs=0, **kw)


def test_needs_from_slots_scales_converts_and_skips_cooked():
    rice = _ingredient(1)
    milk = _ingredient(2, grams_per_ml=D("1.03"))
    meal = Meal(id=1, name="m", servings=2)
    meal.items = [
        RecipeItem(ingredient=rice, quantity=D("150"), unit=Unit.G),
        RecipeItem(ingredient=milk, quantity=D("200"), unit=Unit.ML),
    ]
    slots = [
        PlanSlot(day=0, meal_type=MealType.LUNCH, meal=meal, servings=D("1")),
        PlanSlot(day=1, meal_type=MealType.LUNCH, meal=meal, servings=D("2")),
        PlanSlot(
            day=2, meal_type=MealType.LUNCH, meal=meal, servings=D("4"), cooked_at=datetime.now(UTC)
        ),
    ]
    assert needs_from_slots(slots) == {1: D("225.00"), 2: D("309.00")}  # 1.5 x (150, 206)


def test_needs_rounding_avoids_an_extra_pack():
    rice = _ingredient(1)
    meal = Meal(id=1, name="m", servings=3)
    meal.items = [RecipeItem(ingredient=rice, quantity=D("100"), unit=Unit.G)]
    # 1.5 + 2 + 2 + 2 = 7.5 of 3 servings = exactly 250 g, but each slot's
    # share is a repeating decimal: unrounded, the sum is 250.0000000000000000000000001.
    slots = [
        PlanSlot(day=d, meal_type=MealType.LUNCH, meal=meal, servings=D(s))
        for d, s in enumerate(("1.5", "2", "2", "2"))
    ]
    need = needs_from_slots(slots)[1]
    assert need == D("250.00")
    assert packs_needed(need, D("250")) == 1


async def _post(client, url, headers, body, params=None) -> dict:
    r = await client.post(url, json=body, headers=headers, params=params)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def week(client: AsyncClient, make_user, db_session: AsyncSession):
    """Rice + milk porridge (2 servings), a plan with it on Mon and Tue (1 serving each)."""
    headers = await make_user()
    tag = secrets.token_hex(3)
    ing = {}
    for key, extra in (("rice", {}), ("milk", {"grams_per_ml": 1.03}), ("salt", {})):
        body = {"name": f"{key} {tag}", "calories": 100, "protein": 1, "fat": 1, "carbs": 1} | extra
        ing[key] = (await _post(client, "/ingredients", headers, body))["id"]
    meal = await _post(
        client,
        "/meals",
        headers,
        {
            "name": f"Porridge {tag}",
            "servings": 2,
            "items": [
                {"ingredient_id": ing["rice"], "quantity": 300, "unit": "g"},
                {"ingredient_id": ing["milk"], "quantity": 1000, "unit": "ml"},
                {"ingredient_id": ing["salt"], "quantity": 2, "unit": "g"},
            ],
        },
    )
    plan = await _post(client, "/plans", headers, {"start_date": "2026-10-26"})
    slots = [
        await _post(
            client,
            f"/plans/{plan['id']}/slots",
            headers,
            {"day": d, "meal_type": "lunch", "meal_id": meal["id"], "servings": 1},
        )
        for d in (0, 1)
    ]
    for body in (
        {
            "ingredient_id": ing["rice"],
            "name": "Rice 900 g",
            "pack_size": 900,
            "pack_unit": "g",
            "price": 119.9,
        },
        {
            "ingredient_id": ing["milk"],
            "name": "Milk 930 ml",
            "pack_size": 930,
            "pack_unit": "ml",
            "price": 89.9,
        },
    ):
        await _post(client, "/products", headers, body | {"shop_name": "Magnit"})
    return headers, plan, slots, ing, tag


async def test_shopping_list(client, week):
    headers, plan, _, ing, tag = week
    r = await client.get(f"/plans/{plan['id']}/shopping-list", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    # Two half-recipes = one full recipe: 300 g rice, 1000 ml = 1030 g milk, 2 g salt.
    milk, rice, salt = body["lines"]  # sorted by name
    assert rice["ingredient"]["id"] == ing["rice"]
    assert (rice["need_g"], rice["to_buy_g"], rice["packs"], rice["cost"], rice["surplus_g"]) == (
        300.0,
        300.0,
        1,
        119.9,
        600.0,
    )
    assert (milk["need_g"], milk["packs"], milk["cost"], milk["surplus_g"]) == (
        1030.0,
        2,
        179.8,
        885.8,
    )
    assert milk["product"]["name"] == "Milk 930 ml" and milk["product"]["pack_size_g"] == 957.9
    assert salt["product"] is None and salt["cost"] is None
    assert body["missing_prices"] == [{"id": ing["salt"], "name": f"salt {tag}"}]
    assert body["total_cost"] == 299.7
    assert body["use_pantry"] is True


async def test_pantry_and_cooked_slots(client, week, db_session: AsyncSession):
    headers, plan, slots, ing, _ = week
    user_id = (await client.get("/users/me", headers=headers)).json()["id"]
    db_session.add_all(
        [
            Leftover(user_id=user_id, ingredient_id=ing["rice"], quantity_g=D("100")),
            Leftover(user_id=user_id, ingredient_id=ing["salt"], quantity_g=D("500")),
        ]
    )
    # Monday's slot is already cooked: only Tuesday (half a recipe) is left.
    await db_session.execute(
        update(PlanSlot).where(PlanSlot.id == slots[0]["id"]).values(cooked_at=datetime.now(UTC))
    )
    await db_session.flush()
    db_session.expire_all()

    body = (await client.get(f"/plans/{plan['id']}/shopping-list", headers=headers)).json()
    lines = {ln["ingredient"]["id"]: ln for ln in body["lines"]}
    assert ing["salt"] not in lines  # 1 g needed, 500 g at home
    assert body["missing_prices"] == []
    rice = lines[ing["rice"]]
    assert (rice["need_g"], rice["in_pantry_g"], rice["to_buy_g"]) == (150.0, 100.0, 50.0)

    body = (
        await client.get(
            f"/plans/{plan['id']}/shopping-list", params={"use_pantry": "false"}, headers=headers
        )
    ).json()
    assert {ln["ingredient"]["id"] for ln in body["lines"]} == set(ing.values())


async def test_empty_plan_and_privacy(client, make_user, week):
    headers, plan, *_ = week
    bob = await make_user()
    assert (await client.get(f"/plans/{plan['id']}/shopping-list", headers=bob)).status_code == 404

    empty = await _post(client, "/plans", headers, {"start_date": "2026-11-02"})
    body = (await client.get(f"/plans/{empty['id']}/shopping-list", headers=headers)).json()
    assert body == {
        "plan_id": empty["id"],
        "use_pantry": True,
        "lines": [],
        "total_cost": 0.0,
        "missing_prices": [],
    }
