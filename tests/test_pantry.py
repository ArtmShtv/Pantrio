import asyncio
import secrets
from decimal import Decimal as D

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.db.config import async_session_maker
from app.db.models.catalog import Ingredient
from app.db.models.pantry import Leftover
from app.db.models.user import User
from app.services.pantry import add_grams


async def ingredient(client: AsyncClient, headers, **fields) -> dict:
    body = {
        "name": f"Ing {secrets.token_hex(3)}",
        "calories": 100,
        "protein": 1,
        "fat": 1,
        "carbs": 1,
    }
    r = await client.post("/ingredients", json=body | fields, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def pantry(client, headers) -> dict[int, float]:
    r = await client.get("/pantry", headers=headers)
    assert r.status_code == 200
    return {row["ingredient"]["id"]: row["quantity_g"] for row in r.json()}


async def test_put_sets_not_adds(client, make_user):
    headers = await make_user()
    rice = await ingredient(client, headers)
    url = f"/pantry/{rice['id']}"

    r = await client.put(url, json={"quantity": 500}, headers=headers)
    assert r.status_code == 200
    assert r.json()["quantity_g"] == 500.0 and r.json()["ingredient"]["name"] == rice["name"]
    await client.put(url, json={"quantity": 300}, headers=headers)
    assert await pantry(client, headers) == {rice["id"]: 300.0}


async def test_put_converts_units(client, make_user):
    headers = await make_user()
    milk = await ingredient(client, headers, grams_per_ml=1.03)
    r = await client.put(
        f"/pantry/{milk['id']}", json={"quantity": 930, "unit": "ml"}, headers=headers
    )
    assert r.json()["quantity_g"] == 957.9
    r = await client.put(
        f"/pantry/{milk['id']}", json={"quantity": 2, "unit": "piece"}, headers=headers
    )
    assert r.status_code == 422


async def test_put_zero_deletes(client, make_user):
    headers = await make_user()
    rice = await ingredient(client, headers)
    await client.put(f"/pantry/{rice['id']}", json={"quantity": 500}, headers=headers)
    r = await client.put(f"/pantry/{rice['id']}", json={"quantity": 0}, headers=headers)
    assert r.status_code == 204
    assert await pantry(client, headers) == {}


async def test_put_needs_visible_ingredient(client, make_user):
    alice, bob = await make_user(), await make_user()
    rice = await ingredient(client, alice)
    r = await client.put(f"/pantry/{rice['id']}", json={"quantity": 1}, headers=bob)
    assert r.status_code == 404


async def test_delete_is_idempotent(client, make_user):
    headers = await make_user()
    rice = await ingredient(client, headers)
    await client.put(f"/pantry/{rice['id']}", json={"quantity": 1}, headers=headers)
    for _ in range(2):
        assert (await client.delete(f"/pantry/{rice['id']}", headers=headers)).status_code == 204
    assert await pantry(client, headers) == {}


async def test_pantry_is_private_and_sorted(client, make_user):
    alice, bob = await make_user(), await make_user()
    tag = secrets.token_hex(3)
    b = await ingredient(client, alice, name=f"b {tag}")
    a = await ingredient(client, alice, name=f"A {tag}")
    for i in (b, a):
        await client.put(f"/pantry/{i['id']}", json={"quantity": 1}, headers=alice)

    rows = (await client.get("/pantry", headers=alice)).json()
    assert [r["ingredient"]["id"] for r in rows] == [a["id"], b["id"]]
    assert await pantry(client, bob) == {}


async def test_purchase_adds_and_merges_duplicate_lines(client, make_user):
    headers = await make_user()
    rice = await ingredient(client, headers)
    milk = await ingredient(client, headers, grams_per_ml=1.03)
    await client.put(f"/pantry/{rice['id']}", json={"quantity": 100}, headers=headers)

    r = await client.post(
        "/pantry/purchases",
        json={
            "items": [
                {"ingredient_id": rice["id"], "quantity": 900},
                {"ingredient_id": rice["id"], "quantity": 900},  # two packs, two lines
                {"ingredient_id": milk["id"], "quantity": 930, "unit": "ml"},
            ]
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert {row["ingredient"]["id"]: row["quantity_g"] for row in r.json()} == {
        rice["id"]: 1900.0,
        milk["id"]: 957.9,
    }


async def test_purchase_validation(client, make_user):
    alice, bob = await make_user(), await make_user()
    bobs = await ingredient(client, bob)
    r = await client.post(
        "/pantry/purchases",
        json={"items": [{"ingredient_id": bobs["id"], "quantity": 1}]},
        headers=alice,
    )
    assert r.status_code == 422 and str(bobs["id"]) in r.json()["detail"]
    assert (
        await client.post("/pantry/purchases", json={"items": []}, headers=alice)
    ).status_code == 422


@pytest.fixture
async def cooking(client: AsyncClient, make_user):
    """Rice 300 g + milk 1000 ml (2 servings); a Monday slot of 1 serving."""
    headers = await make_user()
    rice = await ingredient(client, headers)
    milk = await ingredient(client, headers, grams_per_ml=1.03)
    meal = (
        await client.post(
            "/meals",
            json={
                "name": f"Porridge {secrets.token_hex(3)}",
                "servings": 2,
                "items": [
                    {"ingredient_id": rice["id"], "quantity": 300, "unit": "g"},
                    {"ingredient_id": milk["id"], "quantity": 1000, "unit": "ml"},
                ],
            },
            headers=headers,
        )
    ).json()
    plan = (await client.post("/plans", json={"start_date": "2026-10-26"}, headers=headers)).json()
    slot = (
        await client.post(
            f"/plans/{plan['id']}/slots",
            json={"day": 0, "meal_type": "lunch", "meal_id": meal["id"], "servings": 1},
            headers=headers,
        )
    ).json()
    await client.put(f"/pantry/{rice['id']}", json={"quantity": 1000}, headers=headers)
    await client.put(f"/pantry/{milk['id']}", json={"quantity": 100}, headers=headers)
    url = f"/plans/{plan['id']}/slots/{slot['id']}"
    return headers, url, plan, rice, milk


async def test_cook_subtracts_and_clamps_at_zero(client, cooking):
    headers, url, _, rice, milk = cooking
    r = await client.post(f"{url}/cook", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slot"]["cooked_at"] is not None
    changes = {c["ingredient"]["id"]: (c["before_g"], c["after_g"]) for c in body["pantry_changes"]}
    # Half the recipe: 150 g rice, 500 ml = 515 g milk; only 100 g milk at home.
    assert changes == {rice["id"]: (1000.0, 850.0), milk["id"]: (100.0, 0.0)}
    assert await pantry(client, headers) == {rice["id"]: 850.0}  # milk row deleted


async def test_cook_twice_is_409(client, cooking):
    headers, url, *_ = cooking
    assert (await client.post(f"{url}/cook", headers=headers)).status_code == 200
    r = await client.post(f"{url}/cook", headers=headers)
    assert r.status_code == 409
    assert (await pantry(client, headers))[cooking[3]["id"]] == 850.0  # subtracted once


async def test_uncook_adds_full_amount_back(client, cooking):
    headers, url, plan, rice, milk = cooking
    await client.post(f"{url}/cook", headers=headers)
    r = await client.delete(f"{url}/cook", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["slot"]["cooked_at"] is None
    # Rice is back to 1000. Milk gets the full 515 g, not the 100 g that was
    # really taken (the documented MVP inaccuracy).
    assert await pantry(client, headers) == {rice["id"]: 1000.0, milk["id"]: 515.0}

    assert (await client.delete(f"{url}/cook", headers=headers)).status_code == 409
    r = await client.patch(url, json={"servings": 2}, headers=headers)
    assert r.status_code == 200  # editable again


async def test_cooked_slot_leaves_the_shopping_list(client, cooking):
    headers, url, plan, rice, _ = cooking
    params = {"use_pantry": "false"}
    before = (
        await client.get(f"/plans/{plan['id']}/shopping-list", params=params, headers=headers)
    ).json()
    assert len(before["lines"]) == 2
    await client.post(f"{url}/cook", headers=headers)
    after = (
        await client.get(f"/plans/{plan['id']}/shopping-list", params=params, headers=headers)
    ).json()
    assert after["lines"] == []


async def test_cook_someone_elses_slot_is_404(client, cooking, make_user):
    _, url, *_ = cooking
    bob = await make_user()
    assert (await client.post(f"{url}/cook", headers=bob)).status_code == 404


@pytest.fixture
async def committed_user_and_ingredient():
    """Outside the rollback fixture: these rows are committed, then deleted."""
    tag = secrets.token_hex(4)
    async with async_session_maker() as s:
        user = User(email=f"race-{tag}@example.com", username=f"race-{tag}")
        s.add(user)
        await s.flush()
        ing = Ingredient(
            name=f"race {tag}", created_by_id=user.id, calories=0, protein=0, fat=0, carbs=0
        )
        s.add(ing)
        await s.commit()
        ids = (user.id, ing.id)
    try:
        yield ids
    finally:
        async with async_session_maker() as s:
            await s.execute(delete(User).where(User.id == ids[0]))  # cascades
            await s.commit()


@pytest.mark.parametrize("existing", [None, D("100")])
async def test_parallel_purchases_dont_lose_an_update(committed_user_and_ingredient, existing):
    user_id, ing_id = committed_user_and_ingredient
    if existing is not None:
        async with async_session_maker() as s:
            await add_grams(s, user_id, {ing_id: existing})
            await s.commit()

    async with async_session_maker() as a, async_session_maker() as b:
        await add_grams(a, user_id, {ing_id: D("900")})  # holds the row lock, not committed

        async def second() -> None:
            await add_grams(b, user_id, {ing_id: D("400")})  # must wait for A
            await b.commit()

        task = asyncio.create_task(second())
        await asyncio.sleep(0.3)
        assert not task.done(), "B should be blocked by A's uncommitted row"
        await a.commit()
        await asyncio.wait_for(task, timeout=5)

    async with async_session_maker() as s:
        grams = await s.scalar(
            select(Leftover.quantity_g).where(
                Leftover.user_id == user_id, Leftover.ingredient_id == ing_id
            )
        )
    assert grams == (existing or 0) + D("1300")
