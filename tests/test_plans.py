import secrets
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.plan import PlanSlot

MONDAY = "2026-10-26"


async def make_meal(client: AsyncClient, headers, *, servings=2) -> dict:
    """Rice 150 g + milk 200 ml + 2 eggs: 812.3 kcal for the whole recipe."""

    async def ing(**fields) -> int:
        body = {"name": f"Ing {secrets.token_hex(3)}", **fields}
        r = await client.post("/ingredients", json=body, headers=headers)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    rice = await ing(calories=344, protein=6.7, fat=0.7, carbs=78.9)
    milk = await ing(calories=60, protein=3, fat=3.2, carbs=4.7, grams_per_ml=1.03)
    eggs = await ing(calories=157, protein=12.6, fat=10.6, carbs=1.1, grams_per_piece=55)
    body = {
        "name": f"Porridge {secrets.token_hex(3)}",
        "servings": servings,
        "items": [
            {"ingredient_id": rice, "quantity": 150, "unit": "g"},
            {"ingredient_id": milk, "quantity": 200, "unit": "ml"},
            {"ingredient_id": eggs, "quantity": 2, "unit": "piece"},
        ],
    }
    r = await client.post("/meals", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def make_plan(client: AsyncClient, headers, start=MONDAY) -> dict:
    r = await client.post("/plans", json={"start_date": start}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def add_slot(client, headers, plan_id, **body) -> dict:
    r = await client.post(f"/plans/{plan_id}/slots", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def setup(client, make_user):
    headers = await make_user()
    meal = await make_meal(client, headers)
    plan = await make_plan(client, headers)
    return headers, meal, plan


# --- plans ---------------------------------------------------------------------


async def test_new_plan_has_seven_empty_days(client, make_user):
    headers = await make_user()
    plan = await make_plan(client, headers)
    assert [d["date"] for d in plan["days"]][:2] == ["2026-10-26", "2026-10-27"]
    assert plan["days"][6]["date"] == "2026-11-01"
    assert all(d["slots"] == [] and d["total"]["kcal"] == 0 for d in plan["days"])
    assert plan["daily_average"]["kcal"] == 0


async def test_start_date_must_be_monday(client, make_user):
    headers = await make_user()
    r = await client.post("/plans", json={"start_date": "2026-10-29"}, headers=headers)
    assert r.status_code == 422
    assert "did you mean 2026-10-26?" in r.text


async def test_duplicate_week_is_409_with_id(client, make_user):
    alice, bob = await make_user(), await make_user()
    plan = await make_plan(client, alice)
    r = await client.post("/plans", json={"start_date": MONDAY}, headers=alice)
    assert r.status_code == 409 and str(plan["id"]) in r.json()["detail"]
    await make_plan(client, bob)  # another user, same week: fine


async def test_list_newest_first_with_filters_and_slot_count(client, setup):
    headers, meal, plan = setup
    newer = await make_plan(client, headers, "2026-11-02")
    await make_plan(client, headers, "2026-11-09")
    await add_slot(client, headers, plan["id"], day=0, meal_type="lunch", meal_id=meal["id"])
    await add_slot(client, headers, plan["id"], day=1, meal_type="lunch", meal_id=meal["id"])

    r = await client.get("/plans", params={"from": MONDAY, "to": "2026-11-02"}, headers=headers)
    page = r.json()
    assert page["total"] == 2
    assert [(p["id"], p["slot_count"]) for p in page["items"]] == [
        (newer["id"], 0),
        (plan["id"], 2),
    ]


async def test_plans_are_private(client, setup, make_user):
    headers, meal, plan = setup
    bob = await make_user()
    assert (await client.get(f"/plans/{plan['id']}", headers=bob)).status_code == 404
    assert (await client.delete(f"/plans/{plan['id']}", headers=bob)).status_code == 404
    r = await client.post(
        f"/plans/{plan['id']}/slots",
        json={"day": 0, "meal_type": "lunch", "meal_id": meal["id"]},
        headers=bob,
    )
    assert r.status_code == 404
    assert (await client.get("/plans", headers=bob)).json()["total"] == 0


async def test_delete_plan_removes_slots(client, setup):
    headers, meal, plan = setup
    await add_slot(client, headers, plan["id"], day=0, meal_type="lunch", meal_id=meal["id"])
    assert (await client.delete(f"/plans/{plan['id']}", headers=headers)).status_code == 204
    assert (await client.get(f"/plans/{plan['id']}", headers=headers)).status_code == 404
    # The meal is no longer used in a plan, so it can be deleted now.
    assert (await client.delete(f"/meals/{meal['id']}", headers=headers)).status_code == 204


# --- nutrition -------------------------------------------------------------------


async def test_slot_scales_meal_by_servings(client, setup):
    headers, meal, plan = setup  # meal: 2 servings, 812.3 kcal total
    one = await add_slot(
        client, headers, plan["id"], day=0, meal_type="lunch", meal_id=meal["id"], servings=1
    )
    half = await add_slot(
        client, headers, plan["id"], day=0, meal_type="dinner", meal_id=meal["id"], servings=0.5
    )
    default = await add_slot(
        client, headers, plan["id"], day=2, meal_type="lunch", meal_id=meal["id"]
    )

    assert one["kcal"] == 406.2  # 406.15
    assert half["kcal"] == 203.1  # 203.075
    assert default["servings"] == 2.0 and default["kcal"] == 812.3
    assert one["meal"] == {"id": meal["id"], "name": meal["name"]}


async def test_day_week_totals_and_average(client, setup):
    headers, meal, plan = setup
    for day, servings in ((0, 1), (0, 1), (3, 2)):
        await add_slot(
            client,
            headers,
            plan["id"],
            day=day,
            meal_type="lunch",
            meal_id=meal["id"],
            servings=servings,
        )

    detail = (await client.get(f"/plans/{plan['id']}", headers=headers)).json()
    days = detail["days"]
    assert days[0]["total"]["kcal"] == 812.3  # 406.15 * 2, summed before rounding
    assert days[3]["total"]["kcal"] == 812.3
    assert days[1]["total"]["kcal"] == 0
    assert detail["week_total"]["kcal"] == 1624.6
    assert detail["daily_average"]["kcal"] == 812.3  # over the 2 days with food, not 7
    assert detail["week_total"]["grams"] == 932.0


async def test_slots_sorted_by_meal_type_then_id(client, setup):
    headers, meal, plan = setup
    ids = {}
    for t in ("snack", "dinner", "breakfast", "lunch", "lunch"):
        s = await add_slot(client, headers, plan["id"], day=4, meal_type=t, meal_id=meal["id"])
        ids.setdefault(t, []).append(s["id"])

    day = (await client.get(f"/plans/{plan['id']}", headers=headers)).json()["days"][4]
    assert [s["id"] for s in day["slots"]] == (
        ids["breakfast"] + ids["lunch"] + ids["dinner"] + ids["snack"]
    )


# --- slot validation ----------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [{"day": 7}, {"day": -1}, {"meal_type": "brunch"}, {"servings": 0}, {"servings": 1.234}],
)
async def test_slot_body_validation(client, setup, change):
    headers, meal, plan = setup
    body = {"day": 0, "meal_type": "lunch", "meal_id": meal["id"]} | change
    r = await client.post(f"/plans/{plan['id']}/slots", json=body, headers=headers)
    assert r.status_code == 422, r.text


async def test_slot_with_someone_elses_meal_is_422(client, setup, make_user):
    headers, _, plan = setup
    bob = await make_user()
    bobs_meal = await make_meal(client, bob)
    r = await client.post(
        f"/plans/{plan['id']}/slots",
        json={"day": 0, "meal_type": "lunch", "meal_id": bobs_meal["id"]},
        headers=headers,
    )
    assert r.status_code == 422 and "Unknown meal" in r.json()["detail"]


# --- PATCH / DELETE slots ------------------------------------------------------------


async def test_patch_slot(client, setup):
    headers, meal, plan = setup
    other = await make_meal(client, headers, servings=1)
    slot = await add_slot(client, headers, plan["id"], day=0, meal_type="lunch", meal_id=meal["id"])

    r = await client.patch(
        f"/plans/{plan['id']}/slots/{slot['id']}",
        json={"day": 5, "meal_id": other["id"], "servings": 0.5},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["day"], body["meal"]["id"], body["servings"], body["kcal"]) == (
        5,
        other["id"],
        0.5,
        406.2,
    )


async def test_patch_rejects_null_and_unknown_meal(client, setup):
    headers, meal, plan = setup
    slot = await add_slot(client, headers, plan["id"], day=0, meal_type="lunch", meal_id=meal["id"])
    url = f"/plans/{plan['id']}/slots/{slot['id']}"
    assert (await client.patch(url, json={"servings": None}, headers=headers)).status_code == 422
    assert (
        await client.patch(url, json={"meal_id": 999_999_999}, headers=headers)
    ).status_code == 422


async def test_cooked_slot_cant_be_edited_but_can_be_deleted(
    client, setup, db_session: AsyncSession
):
    headers, meal, plan = setup
    slot = await add_slot(client, headers, plan["id"], day=0, meal_type="lunch", meal_id=meal["id"])
    # /cook arrives with the pantry (§7); set the flag directly for now.
    await db_session.execute(
        update(PlanSlot).where(PlanSlot.id == slot["id"]).values(cooked_at=datetime.now(UTC))
    )
    db_session.expire_all()

    url = f"/plans/{plan['id']}/slots/{slot['id']}"
    r = await client.patch(url, json={"servings": 1}, headers=headers)
    assert r.status_code == 409 and "un-cook" in r.json()["detail"]
    assert (await client.delete(url, headers=headers)).status_code == 204


async def test_slot_must_belong_to_the_plan_in_the_url(client, setup):
    headers, meal, plan = setup
    other_plan = await make_plan(client, headers, "2026-11-02")
    slot = await add_slot(client, headers, plan["id"], day=0, meal_type="lunch", meal_id=meal["id"])
    url = f"/plans/{other_plan['id']}/slots/{slot['id']}"
    assert (await client.patch(url, json={"day": 1}, headers=headers)).status_code == 404
    assert (await client.delete(url, headers=headers)).status_code == 404
