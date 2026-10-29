import secrets
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import MealType
from app.db.models.meal import RecipeItem
from app.db.models.plan import PlanSlot, WeekPlan


async def ingredient(client: AsyncClient, headers, *, scope="private", **fields) -> int:
    body = {
        "name": f"Ing {secrets.token_hex(3)}",
        "calories": 100,
        "protein": 1,
        "fat": 1,
        "carbs": 1,
    }
    r = await client.post(
        "/ingredients", json=body | fields, headers=headers, params={"scope": scope}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
async def pantry(client, make_user):
    """A user with rice (g), milk (ml) and eggs (pieces)."""
    headers = await make_user()
    rice = await ingredient(
        client,
        headers,
        name=f"Rice {secrets.token_hex(3)}",
        calories=344,
        protein=6.7,
        fat=0.7,
        carbs=78.9,
    )
    milk = await ingredient(
        client, headers, calories=60, protein=3, fat=3.2, carbs=4.7, grams_per_ml=1.03
    )
    eggs = await ingredient(
        client, headers, calories=157, protein=12.6, fat=10.6, carbs=1.1, grams_per_piece=55
    )
    return headers, {"rice": rice, "milk": milk, "eggs": eggs}


def meal_body(ids: dict, name: str | None = None, **overrides) -> dict:
    body = {
        "name": name or f"Porridge {secrets.token_hex(3)}",
        "servings": 2,
        "items": [
            {"ingredient_id": ids["rice"], "quantity": 150, "unit": "g"},
            {"ingredient_id": ids["milk"], "quantity": 200, "unit": "ml"},
            {"ingredient_id": ids["eggs"], "quantity": 2, "unit": "piece"},
        ],
    }
    return body | overrides


async def create_meal(client, headers, body, *, scope="private") -> dict:
    r = await client.post("/meals", json=body, headers=headers, params={"scope": scope})
    assert r.status_code == 201, r.text
    return r.json()


# --- nutrition in responses ----------------------------------------------------


async def test_detail_computes_grams_and_nutrition(client, pantry):
    headers, ids = pantry
    meal = await create_meal(client, headers, meal_body(ids))

    rice, milk, eggs = meal["items"]
    assert (rice["grams"], rice["kcal"]) == (150.0, 516.0)
    assert (milk["grams"], milk["kcal"]) == (206.0, 123.6)  # 200 ml * 1.03
    assert (eggs["grams"], eggs["kcal"]) == (110.0, 172.7)  # 2 * 55 g
    assert eggs["quantity"] == 2.0 and eggs["unit"] == "piece"

    assert meal["total"] == {
        "grams": 466.0,
        "kcal": 812.3,
        "protein": 30.1,
        "fat": 19.3,
        "carbs": 129.2,
    }
    assert meal["per_serving"] == {
        "grams": 233.0,
        "kcal": 406.2,
        "protein": 15.0,
        "fat": 9.7,
        "carbs": 64.6,
    }

    r = await client.get(f"/meals/{meal['id']}", headers=headers)
    assert r.json() == meal


async def test_list_shows_kcal_per_serving(client, pantry):
    headers, ids = pantry
    tag = secrets.token_hex(3)
    await create_meal(client, headers, meal_body(ids, name=f"{tag} b"))
    await create_meal(client, headers, meal_body(ids, name=f"{tag} a", servings=1))

    r = await client.get("/meals", params={"q": tag}, headers=headers)
    page = r.json()
    assert page["total"] == 2
    assert [(m["name"], m["kcal_per_serving"]) for m in page["items"]] == [
        (f"{tag} a", 812.3),
        (f"{tag} b", 406.2),
    ]
    assert page["items"][0] == page["items"][0] | {"servings": 1, "is_global": False}


# --- validation ----------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"items": []},
        {"servings": 0},
        {"name": "  "},
        {"items": [{"ingredient_id": 1, "quantity": 0, "unit": "g"}]},
        {"items": [{"ingredient_id": 1, "quantity": 1, "unit": "kg"}]},
    ],
)
async def test_body_validation(client, pantry, change):
    headers, ids = pantry
    r = await client.post("/meals", json=meal_body(ids, **change), headers=headers)
    assert r.status_code == 422, r.text


async def test_same_ingredient_twice_is_422(client, pantry):
    headers, ids = pantry
    body = meal_body(ids)
    body["items"].append({"ingredient_id": ids["rice"], "quantity": 50, "unit": "g"})
    r = await client.post("/meals", json=body, headers=headers)
    assert r.status_code == 422
    assert "merge the lines" in r.text


async def test_unit_without_factor_is_422(client, pantry):
    headers, ids = pantry
    body = meal_body(ids)
    body["items"][0]["unit"] = "piece"  # rice has no grams_per_piece
    r = await client.post("/meals", json=body, headers=headers)
    assert r.status_code == 422
    assert "piece" in r.json()["detail"]


async def test_other_users_or_unknown_ingredient_is_422(client, pantry, make_user):
    headers, ids = pantry
    bob = await make_user()
    bobs = await ingredient(client, bob)
    body = meal_body(ids)
    body["items"].append({"ingredient_id": bobs, "quantity": 1, "unit": "g"})
    body["items"].append({"ingredient_id": 999_999_999, "quantity": 1, "unit": "g"})
    r = await client.post("/meals", json=body, headers=headers)
    assert r.status_code == 422
    assert str(bobs) in r.json()["detail"] and "999999999" in r.json()["detail"]


async def test_duplicate_name_is_409(client, pantry):
    headers, ids = pantry
    meal = await create_meal(client, headers, meal_body(ids))
    r = await client.post("/meals", json=meal_body(ids, name=meal["name"].upper()), headers=headers)
    assert r.status_code == 409


# --- global meals --------------------------------------------------------------


async def test_global_meals(client, make_user):
    admin, alice = await make_user(admin=True), await make_user()
    glob = await ingredient(client, admin, scope="global")
    private = await ingredient(client, admin)
    items = [{"ingredient_id": glob, "quantity": 100, "unit": "g"}]
    body = {"name": f"Global {secrets.token_hex(3)}", "servings": 1, "items": items}

    r = await client.post("/meals", json=body, headers=alice, params={"scope": "global"})
    assert r.status_code == 403

    with_private = body | {
        "items": items + [{"ingredient_id": private, "quantity": 1, "unit": "g"}]
    }
    r = await client.post("/meals", json=with_private, headers=admin, params={"scope": "global"})
    assert r.status_code == 422 and "global" in r.json()["detail"]

    meal = await create_meal(client, admin, body, scope="global")
    assert meal["is_global"] is True
    assert (await client.get(f"/meals/{meal['id']}", headers=alice)).status_code == 200
    assert (await client.put(f"/meals/{meal['id']}", json=body, headers=alice)).status_code == 403
    assert (await client.delete(f"/meals/{meal['id']}", headers=alice)).status_code == 403


# --- visibility ------------------------------------------------------------------


async def test_private_meal_is_invisible_to_others(client, pantry, make_user):
    headers, ids = pantry
    bob = await make_user()
    meal = await create_meal(client, headers, meal_body(ids))

    assert (await client.get(f"/meals/{meal['id']}", headers=bob)).status_code == 404
    r = await client.put(f"/meals/{meal['id']}", json=meal_body(ids), headers=bob)
    assert r.status_code == 404
    assert (await client.delete(f"/meals/{meal['id']}", headers=bob)).status_code == 404
    r = await client.get("/meals", params={"q": meal["name"]}, headers=bob)
    assert r.json()["total"] == 0


# --- PUT ---------------------------------------------------------------------------


async def test_put_replaces_everything_and_removes_dropped_items(
    client, pantry, db_session: AsyncSession
):
    headers, ids = pantry
    meal = await create_meal(client, headers, meal_body(ids))

    # Keep rice with a new quantity (same ingredient: the unique-constraint case),
    # drop milk and eggs.
    new = {
        "name": "Plain rice",
        "servings": 1,
        "items": [{"ingredient_id": ids["rice"], "quantity": 80, "unit": "g"}],
    }
    r = await client.put(f"/meals/{meal['id']}", json=new, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Plain rice" and body["servings"] == 1
    assert [(i["ingredient"]["id"], i["grams"]) for i in body["items"]] == [(ids["rice"], 80.0)]

    rows = await db_session.scalar(select(func.count()).where(RecipeItem.meal_id == meal["id"]))
    assert rows == 1


async def test_put_rename_to_taken_name_is_409(client, pantry):
    headers, ids = pantry
    a = await create_meal(client, headers, meal_body(ids))
    b = await create_meal(client, headers, meal_body(ids))
    r = await client.put(f"/meals/{b['id']}", json=meal_body(ids, name=a["name"]), headers=headers)
    assert r.status_code == 409
    # Keeping its own name is fine.
    r = await client.put(f"/meals/{b['id']}", json=meal_body(ids, name=b["name"]), headers=headers)
    assert r.status_code == 200


# --- DELETE --------------------------------------------------------------------------


async def test_delete(client, pantry):
    headers, ids = pantry
    meal = await create_meal(client, headers, meal_body(ids))
    assert (await client.delete(f"/meals/{meal['id']}", headers=headers)).status_code == 204
    assert (await client.get(f"/meals/{meal['id']}", headers=headers)).status_code == 404


async def test_delete_meal_used_in_plan_is_409(client, pantry, db_session: AsyncSession):
    headers, ids = pantry
    meal = await create_meal(client, headers, meal_body(ids))
    user_id = (await client.get("/users/me", headers=headers)).json()["id"]

    plan = WeekPlan(user_id=user_id, start_date=date(2026, 10, 26))  # a Monday
    plan.slots = [PlanSlot(day=0, meal_type=MealType.LUNCH, meal_id=meal["id"], servings=1)]
    db_session.add(plan)
    await db_session.flush()

    r = await client.delete(f"/meals/{meal['id']}", headers=headers)
    assert r.status_code == 409 and "plan" in r.json()["detail"]


async def test_deleting_meal_frees_its_ingredients(client, pantry):
    headers, ids = pantry
    meal = await create_meal(client, headers, meal_body(ids))
    assert (await client.delete(f"/ingredients/{ids['rice']}", headers=headers)).status_code == 409
    await client.delete(f"/meals/{meal['id']}", headers=headers)
    assert (await client.delete(f"/ingredients/{ids['rice']}", headers=headers)).status_code == 204
