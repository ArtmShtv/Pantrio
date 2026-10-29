import secrets
from decimal import Decimal as D

import pytest
from httpx import AsyncClient

from app.db.models.catalog import Ingredient
from app.db.models.meal import Meal
from app.services.suggestions import LineIn, Strategy, rank, score

_ids = iter(range(1, 1000))


def line(need, have, price=None) -> LineIn:
    ing = Ingredient(id=next(_ids), name="x")
    return LineIn(ing, D(need), D(have), None if price is None else D(price))


# One fixed example; each strategy orders the three meals differently.
#
# Chicken: 500 g chicken (have all), 5 g salt, 2 g pepper (have neither).
#   share 1/3 = 0.333   grams 500/507 = 0.986   money 250/252.1 = 0.992
# Salad: 300 g cucumber + 300 g tomato (have both), 100 g cheese (missing).
#   share 2/3 = 0.667   grams 600/700 = 0.857   money 90/240 = 0.375
# Saffron rice: 500 g rice (missing), 1 g saffron (have it, very expensive).
#   share 1/2 = 0.5     grams 1/501 = 0.002     money 300/350 = 0.857
MEALS = {
    "Chicken": [line(500, 500, "0.5"), line(5, 0, "0.02"), line(2, 0, "1")],
    "Salad": [line(300, 300, "0.1"), line(300, 300, "0.2"), line(100, 0, "1.5")],
    "Saffron rice": [line(500, 0, "0.1"), line(1, 1, "300")],
}


def candidates():
    return [(Meal(id=i, name=name), lines) for i, (name, lines) in enumerate(MEALS.items())]


@pytest.mark.parametrize(
    ("strategy", "order"),
    [
        (Strategy.SHARE, ["Salad", "Saffron rice", "Chicken"]),
        (Strategy.GRAMS, ["Chicken", "Salad", "Saffron rice"]),
        (Strategy.MONEY, ["Chicken", "Saffron rice", "Salad"]),
    ],
)
def test_strategies_rank_the_same_meals_differently(strategy, order):
    assert [s.meal.name for s in rank(candidates(), strategy, 10)] == order


def test_scores():
    chicken = MEALS["Chicken"]
    assert score(chicken, Strategy.SHARE).quantize(D("0.001")) == D("0.333")
    assert score(chicken, Strategy.GRAMS).quantize(D("0.001")) == D("0.986")
    assert score(chicken, Strategy.MONEY).quantize(D("0.001")) == D("0.992")


def test_partial_coverage_counts_partly():
    assert score([line(200, 50)], Strategy.SHARE) == D("0.25")
    assert score([line(200, 50), line(100, 100)], Strategy.GRAMS) == D("0.5")


def test_money_ignores_unpriced_lines_and_is_zero_without_prices():
    assert score([line(100, 100, "1"), line(1000, 0)], Strategy.MONEY) == 1
    assert score([line(100, 100), line(50, 0)], Strategy.MONEY) == 0


def test_zero_scores_are_dropped_and_limit_applies():
    cands = candidates() + [(Meal(id=99, name="Nothing"), [line(100, 0, "1")])]
    result = rank(cands, Strategy.GRAMS, 10)
    assert "Nothing" not in [s.meal.name for s in result]
    assert len(rank(cands, Strategy.GRAMS, 2)) == 2


# --- API -------------------------------------------------------------------------------


async def _ing(client, headers, name, **extra) -> int:
    body = {"name": name, "calories": 100, "protein": 1, "fat": 1, "carbs": 1} | extra
    r = await client.post("/ingredients", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _meal(client, headers, name, items) -> int:
    body = {
        "name": name,
        "servings": 2,
        "items": [{"ingredient_id": i, "quantity": q, "unit": u} for i, q, u in items],
    }
    r = await client.post("/meals", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
async def kitchen(client: AsyncClient, make_user):
    headers = await make_user()
    t = secrets.token_hex(3)
    rice = await _ing(client, headers, f"rice {t}")
    milk = await _ing(client, headers, f"milk {t}", grams_per_ml=1.0)
    fish = await _ing(client, headers, f"fish {t}")
    porridge = await _meal(client, headers, f"Porridge {t}", [(rice, 200, "g"), (milk, 800, "ml")])
    rice_bowl = await _meal(client, headers, f"Rice bowl {t}", [(rice, 300, "g"), (fish, 300, "g")])
    fish_only = await _meal(client, headers, f"Fish {t}", [(fish, 500, "g")])
    await client.put(f"/pantry/{rice}", json={"quantity": 250}, headers=headers)
    await client.put(f"/pantry/{milk}", json={"quantity": 800}, headers=headers)
    return (
        headers,
        {"rice": rice, "milk": milk, "fish": fish},
        {
            "porridge": porridge,
            "rice_bowl": rice_bowl,
            "fish": fish_only,
        },
    )


async def test_suggestions(client, kitchen):
    headers, ing, meals = kitchen
    r = await client.get("/suggestions/meals", params={"strategy": "grams"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    # Porridge: 1000/1000 g covered. Rice bowl: 250/600. Fish: nothing -> left out.
    assert [s["meal"]["id"] for s in body] == [meals["porridge"], meals["rice_bowl"]]
    assert [s["score"] for s in body] == [1.0, 0.417]

    bowl = body[1]
    assert [(c["ingredient"]["id"], c["have_g"], c["need_g"]) for c in bowl["covered"]] == [
        (ing["rice"], 250.0, 300.0)
    ]
    missing = {m["ingredient"]["id"]: m["missing_g"] for m in bowl["missing"]}
    assert missing == {ing["fish"]: 300.0, ing["rice"]: 50.0}
    assert body[0]["missing"] == []


async def test_empty_pantry_and_privacy(client, kitchen, make_user):
    bob = await make_user()
    assert (await client.get("/suggestions/meals", headers=bob)).json() == []

    # Bob has rice of his own, but Alice's private meals are never suggested to him.
    bob_rice = await _ing(client, bob, "rice")
    await client.put(f"/pantry/{bob_rice}", json={"quantity": 1000}, headers=bob)
    assert (await client.get("/suggestions/meals", headers=bob)).json() == []


async def test_money_strategy_uses_prices(client, kitchen):
    headers, ing, meals = kitchen
    for key, price in (("rice", 100), ("fish", 1000)):  # 0.1 and 1.0 per gram; milk unpriced
        body = {
            "ingredient_id": ing[key],
            "name": key,
            "shop_name": "x",
            "pack_size": 1000,
            "pack_unit": "g",
            "price": price,
        }
        assert (await client.post("/products", json=body, headers=headers)).status_code == 201

    r = await client.get("/suggestions/meals", params={"strategy": "money"}, headers=headers)
    body = r.json()
    # Porridge: only rice is priced, and all 200 g are at home -> 1.0.
    # Rice bowl: 250 g rice at home = 25 of (30 rice + 300 fish) -> 0.076.
    assert [(s["meal"]["id"], s["score"]) for s in body] == [
        (meals["porridge"], 1.0),
        (meals["rice_bowl"], 0.076),
    ]


async def test_bad_params(client, kitchen):
    headers, *_ = kitchen
    for params in ({"strategy": "vibes"}, {"limit": 0}, {"limit": 51}):
        assert (
            await client.get("/suggestions/meals", params=params, headers=headers)
        ).status_code == 422
