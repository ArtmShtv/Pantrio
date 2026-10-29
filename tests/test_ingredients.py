import secrets
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.catalog import ShopProduct
from app.db.models.enums import Unit
from app.db.models.meal import Meal, RecipeItem


def body(name: str | None = None, **overrides) -> dict:
    data = {
        "name": name or f"Rice {secrets.token_hex(3)}",
        "calories": 344,
        "protein": 6.7,
        "fat": 0.7,
        "carbs": 78.9,
    }
    return data | overrides


async def create(client: AsyncClient, headers, **kwargs) -> dict:
    params = kwargs.pop("params", None)
    r = await client.post("/ingredients", json=body(**kwargs), headers=headers, params=params)
    assert r.status_code == 201, r.text
    return r.json()


async def add_meal_using(db: AsyncSession, ingredient_id: int, user_id: int | None, unit=Unit.G):
    meal = Meal(name=f"Meal {secrets.token_hex(3)}", created_by_id=user_id, servings=2)
    meal.items = [RecipeItem(ingredient_id=ingredient_id, quantity=Decimal(2), unit=unit)]
    db.add(meal)
    await db.flush()
    return meal


async def me(client: AsyncClient, headers) -> int:
    return (await client.get("/users/me", headers=headers)).json()["id"]


# --- create / read -----------------------------------------------------------


async def test_create_returns_numbers_not_strings(client, make_user):
    alice = await make_user()
    ing = await create(client, alice, grams_per_piece=55)
    assert ing["calories"] == 344.0 and isinstance(ing["protein"], float)
    assert ing["grams_per_piece"] == 55.0 and ing["grams_per_ml"] is None
    assert ing["is_global"] is False


async def test_list_search_and_paging(client, make_user):
    alice = await make_user()
    tag = secrets.token_hex(3)
    for n in ("b", "a", "c"):
        await create(client, alice, name=f"{tag} {n}")

    r = await client.get("/ingredients", params={"q": tag, "limit": 2, "offset": 1}, headers=alice)
    page = r.json()
    assert page["total"] == 3
    assert [i["name"] for i in page["items"]] == [f"{tag} b", f"{tag} c"]


async def test_search_escapes_wildcards(client, make_user):
    alice = await make_user()
    tag = secrets.token_hex(3)
    await create(client, alice, name=f"{tag} milk")
    r = await client.get("/ingredients", params={"q": f"{tag}%"}, headers=alice)
    assert r.json()["total"] == 0


async def test_detail_lists_visible_products_cheapest_per_gram_first(client, make_user, db_session):
    alice, bob = await make_user(), await make_user()
    ing = await create(client, alice)
    alice_id, bob_id = await me(client, alice), await me(client, bob)
    db_session.add_all(
        [
            ShopProduct(
                ingredient_id=ing["id"],
                created_by_id=alice_id,
                name="Big",
                shop_name="Magnit",
                pack_size_g=900,
                price=Decimal("119.90"),
            ),
            ShopProduct(
                ingredient_id=ing["id"],
                created_by_id=alice_id,
                name="Small",
                shop_name="Magnit",
                pack_size_g=400,
                price=Decimal("79.90"),
            ),
            ShopProduct(
                ingredient_id=ing["id"],
                created_by_id=bob_id,
                name="Bob's",
                shop_name="X",
                pack_size_g=1000,
                price=Decimal("1"),
            ),
        ]
    )
    await db_session.flush()

    r = await client.get(f"/ingredients/{ing['id']}", headers=alice)
    products = r.json()["products"]
    assert [p["name"] for p in products] == ["Big", "Small"]  # Bob's is hidden
    assert products[0]["price_per_kg"] == 133.22


# --- visibility and permissions ----------------------------------------------


async def test_private_ingredient_is_invisible_to_others(client, make_user):
    alice, bob = await make_user(), await make_user()
    ing = await create(client, alice)

    assert (await client.get(f"/ingredients/{ing['id']}", headers=bob)).status_code == 404
    r = await client.patch(f"/ingredients/{ing['id']}", json={"fat": 1}, headers=bob)
    assert r.status_code == 404
    assert (await client.delete(f"/ingredients/{ing['id']}", headers=bob)).status_code == 404
    r = await client.get("/ingredients", params={"q": ing["name"]}, headers=bob)
    assert r.json()["total"] == 0


async def test_only_admin_creates_global(client, make_user):
    alice = await make_user()
    r = await client.post("/ingredients", json=body(), params={"scope": "global"}, headers=alice)
    assert r.status_code == 403


async def test_global_is_visible_to_all_but_editable_by_admin_only(client, make_user):
    admin, alice = await make_user(admin=True), await make_user()
    ing = await create(client, admin, params={"scope": "global"})
    assert ing["is_global"] is True

    r = await client.get(
        "/ingredients", params={"q": ing["name"], "scope": "global"}, headers=alice
    )
    assert r.json()["total"] == 1
    r = await client.get("/ingredients", params={"q": ing["name"], "scope": "mine"}, headers=alice)
    assert r.json()["total"] == 0

    r = await client.patch(f"/ingredients/{ing['id']}", json={"fat": 1}, headers=alice)
    assert r.status_code == 403
    assert (await client.delete(f"/ingredients/{ing['id']}", headers=alice)).status_code == 403
    r = await client.patch(f"/ingredients/{ing['id']}", json={"fat": 1}, headers=admin)
    assert r.status_code == 200


async def test_requires_auth(client):
    assert (await client.get("/ingredients")).status_code == 401


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"protein": 50, "fat": 30, "carbs": 30},  # macros > 100
        {"calories": -1},
        {"protein": 1.234},  # more decimals than the column holds
        {"grams_per_piece": 0},
        {"name": "   "},
        {"is_global": True},  # unknown field
    ],
)
async def test_create_validation(client, make_user, overrides):
    alice = await make_user()
    r = await client.post("/ingredients", json=body(**overrides), headers=alice)
    assert r.status_code == 422, r.text


async def test_patch_checks_macros_against_stored_values(client, make_user):
    alice = await make_user()
    ing = await create(client, alice)  # 6.7 + 0.7 + 78.9 = 86.3
    r = await client.patch(f"/ingredients/{ing['id']}", json={"fat": 20}, headers=alice)
    assert r.status_code == 422
    assert "can't exceed 100" in r.json()["detail"]


async def test_patch_rejects_null_for_required_fields(client, make_user):
    alice = await make_user()
    ing = await create(client, alice)
    r = await client.patch(f"/ingredients/{ing['id']}", json={"calories": None}, headers=alice)
    assert r.status_code == 422


async def test_patch_partial_update(client, make_user):
    alice = await make_user()
    ing = await create(client, alice)
    r = await client.patch(
        f"/ingredients/{ing['id']}",
        json={"name": "  Basmati  ", "grams_per_ml": 0.85},
        headers=alice,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Basmati" and r.json()["grams_per_ml"] == 0.85
    assert r.json()["calories"] == 344.0


# --- conflicts ---------------------------------------------------------------


async def test_duplicate_name_is_409_case_insensitive(client, make_user):
    alice, bob = await make_user(), await make_user()
    ing = await create(client, alice)
    r = await client.post("/ingredients", json=body(ing["name"].upper()), headers=alice)
    assert r.status_code == 409
    # Another user may use the same name: names are unique per owner.
    await create(client, bob, name=ing["name"])


async def test_rename_to_taken_name_is_409(client, make_user):
    alice = await make_user()
    a, b = await create(client, alice), await create(client, alice)
    r = await client.patch(f"/ingredients/{b['id']}", json={"name": a["name"]}, headers=alice)
    assert r.status_code == 409


async def test_delete_unused_then_gone(client, make_user):
    alice = await make_user()
    ing = await create(client, alice)
    assert (await client.delete(f"/ingredients/{ing['id']}", headers=alice)).status_code == 204
    assert (await client.get(f"/ingredients/{ing['id']}", headers=alice)).status_code == 404


async def test_delete_used_in_meal_is_409(client, make_user, db_session):
    alice = await make_user()
    ing = await create(client, alice)
    meal = await add_meal_using(db_session, ing["id"], await me(client, alice))

    r = await client.delete(f"/ingredients/{ing['id']}", headers=alice)
    assert r.status_code == 409
    assert meal.name in r.json()["detail"]


async def test_admin_cant_delete_global_used_by_someones_meal(client, make_user, db_session):
    admin, bob = await make_user(admin=True), await make_user()
    ing = await create(client, admin, params={"scope": "global"})
    bobs_meal = await add_meal_using(db_session, ing["id"], await me(client, bob))

    r = await client.delete(f"/ingredients/{ing['id']}", headers=admin)
    assert r.status_code == 409
    assert bobs_meal.name in r.json()["detail"]


async def test_removing_piece_factor_in_use_is_409(client, make_user, db_session):
    alice = await make_user()
    ing = await create(client, alice, grams_per_piece=55, grams_per_ml=1.03)
    await add_meal_using(db_session, ing["id"], await me(client, alice), unit=Unit.PIECE)

    r = await client.patch(
        f"/ingredients/{ing['id']}", json={"grams_per_piece": None}, headers=alice
    )
    assert r.status_code == 409
    # The ml factor isn't used, so removing it is fine.
    r = await client.patch(f"/ingredients/{ing['id']}", json={"grams_per_ml": None}, headers=alice)
    assert r.status_code == 200 and r.json()["grams_per_ml"] is None
