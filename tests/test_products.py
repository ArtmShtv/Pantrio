import secrets

import pytest
from httpx import AsyncClient


async def make_ingredient(client: AsyncClient, headers, *, scope="private", **overrides) -> dict:
    body = {
        "name": f"Milk {secrets.token_hex(3)}",
        "calories": 60,
        "protein": 3,
        "fat": 3.2,
        "carbs": 4.7,
        "grams_per_ml": 1.03,
        "grams_per_piece": None,
    } | overrides
    r = await client.post("/ingredients", json=body, headers=headers, params={"scope": scope})
    assert r.status_code == 201, r.text
    return r.json()


async def make_product(
    client: AsyncClient, headers, ingredient_id: int, *, scope="private", **overrides
) -> dict:
    body = {
        "ingredient_id": ingredient_id,
        "name": "Milk 3.2% 930 ml",
        "shop_name": "Pyaterochka",
        "pack_size": 930,
        "pack_unit": "ml",
        "price": 89.90,
    } | overrides
    r = await client.post("/products", json=body, headers=headers, params={"scope": scope})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize(
    ("pack_size", "pack_unit", "grams"),
    [(930, "ml", 957.9), (10, "piece", 550.0), (500, "g", 500.0)],
)
async def test_pack_converts_to_grams(client, make_user, pack_size, pack_unit, grams):
    alice = await make_user()
    ing = await make_ingredient(client, alice, grams_per_piece=55)
    p = await make_product(client, alice, ing["id"], pack_size=pack_size, pack_unit=pack_unit)
    assert p["pack_size_g"] == grams


async def test_pack_grams_are_rounded_to_hundredths(client, make_user):
    alice = await make_user()
    ing = await make_ingredient(client, alice, grams_per_ml=1.0333)
    p = await make_product(client, alice, ing["id"], pack_size=1000, pack_unit="ml")
    assert p["pack_size_g"] == 1033.3


async def test_unit_without_factor_is_422(client, make_user):
    alice = await make_user()
    ing = await make_ingredient(client, alice)  # no grams_per_piece
    r = await client.post(
        "/products",
        json={
            "ingredient_id": ing["id"],
            "name": "Milk",
            "shop_name": "X",
            "pack_size": 6,
            "pack_unit": "piece",
            "price": 100,
        },
        headers=alice,
    )
    assert r.status_code == 422
    assert "piece" in r.json()["detail"]


async def test_patch_pack_size_reconverts(client, make_user):
    alice = await make_user()
    ing = await make_ingredient(client, alice)
    p = await make_product(client, alice, ing["id"])
    r = await client.patch(
        f"/products/{p['id']}", json={"pack_size": 1, "pack_unit": "g"}, headers=alice
    )
    assert r.status_code == 200 and r.json()["pack_size_g"] == 1.0


async def test_patch_pack_size_without_unit_is_422(client, make_user):
    alice = await make_user()
    ing = await make_ingredient(client, alice)
    p = await make_product(client, alice, ing["id"])
    r = await client.patch(f"/products/{p['id']}", json={"pack_size": 1}, headers=alice)
    assert r.status_code == 422


@pytest.mark.parametrize(
    "patch", [{"price": None}, {"ingredient_id": 1}, {"price": -1}, {"price": 1.005}]
)
async def test_patch_validation(client, make_user, patch):
    alice = await make_user()
    ing = await make_ingredient(client, alice)
    p = await make_product(client, alice, ing["id"])
    r = await client.patch(f"/products/{p['id']}", json=patch, headers=alice)
    assert r.status_code == 422, r.text


async def test_patch_price_and_name(client, make_user):
    alice = await make_user()
    ing = await make_ingredient(client, alice)
    p = await make_product(client, alice, ing["id"])
    r = await client.patch(
        f"/products/{p['id']}", json={"price": 99.5, "name": " Milk 2.5% "}, headers=alice
    )
    assert r.json()["price"] == 99.5 and r.json()["name"] == "Milk 2.5%"
    assert r.json()["pack_size_g"] == 957.9


async def test_users_product_is_invisible_to_others(client, make_user, admin_and_global):
    admin, ing = admin_and_global
    alice, bob = await make_user(), await make_user()
    p = await make_product(client, alice, ing["id"])

    r = await client.get(f"/ingredients/{ing['id']}/products", headers=bob)
    assert r.status_code == 200 and r.json() == []
    for method, kwargs in (("patch", {"json": {"price": 1}}), ("delete", {})):
        r = await getattr(client, method)(f"/products/{p['id']}", headers=bob, **kwargs)
        assert r.status_code == 404


async def test_product_on_invisible_ingredient_is_404(client, make_user):
    alice, bob = await make_user(), await make_user()
    ing = await make_ingredient(client, alice)
    body = {
        "ingredient_id": ing["id"],
        "name": "X",
        "shop_name": "X",
        "pack_size": 1,
        "pack_unit": "g",
        "price": 1,
    }
    assert (await client.post("/products", json=body, headers=bob)).status_code == 404
    r = await client.get(f"/ingredients/{ing['id']}/products", headers=bob)
    assert r.status_code == 404


async def test_global_products(client, make_user, admin_and_global):
    admin, ing = admin_and_global
    alice = await make_user()

    body = {
        "ingredient_id": ing["id"],
        "name": "X",
        "shop_name": "X",
        "pack_size": 1,
        "pack_unit": "g",
        "price": 1,
    }
    r = await client.post("/products", json=body, headers=alice, params={"scope": "global"})
    assert r.status_code == 403

    p = await make_product(client, admin, ing["id"], scope="global")
    assert p["is_global"] is True
    r = await client.get(f"/ingredients/{ing['id']}/products", headers=alice)
    assert [x["id"] for x in r.json()] == [p["id"]]

    assert (
        await client.patch(f"/products/{p['id']}", json={"price": 1}, headers=alice)
    ).status_code == 403
    assert (await client.delete(f"/products/{p['id']}", headers=alice)).status_code == 403
    assert (await client.delete(f"/products/{p['id']}", headers=admin)).status_code == 204


async def test_global_product_needs_global_ingredient(client, make_user):
    admin = await make_user(admin=True)
    ing = await make_ingredient(client, admin)  # admin's private ingredient
    body = {
        "ingredient_id": ing["id"],
        "name": "X",
        "shop_name": "X",
        "pack_size": 1,
        "pack_unit": "g",
        "price": 1,
    }
    r = await client.post("/products", json=body, headers=admin, params={"scope": "global"})
    assert r.status_code == 422


async def test_delete_own_product(client, make_user):
    alice = await make_user()
    ing = await make_ingredient(client, alice)
    p = await make_product(client, alice, ing["id"])
    assert (await client.delete(f"/products/{p['id']}", headers=alice)).status_code == 204
    r = await client.get(f"/ingredients/{ing['id']}/products", headers=alice)
    assert r.json() == []


async def test_sorted_by_price_per_gram(client, make_user):
    alice = await make_user()
    ing = await make_ingredient(client, alice)
    # Per kg: big 92.47, mid 99.90, small 104.40 (930 ml = 957.9 g)
    await make_product(client, alice, ing["id"], name="small", pack_size=930, price=100)
    await make_product(
        client, alice, ing["id"], name="big", pack_size=1000, pack_unit="g", price=92.47
    )
    await make_product(
        client, alice, ing["id"], name="mid", pack_size=500, pack_unit="g", price=49.95
    )

    r = await client.get(f"/ingredients/{ing['id']}/products", headers=alice)
    items = r.json()
    assert [p["name"] for p in items] == ["big", "mid", "small"]
    assert [p["price_per_kg"] for p in items] == [92.47, 99.9, 104.4]


@pytest.fixture
async def admin_and_global(client, make_user):
    admin = await make_user(admin=True)
    return admin, await make_ingredient(client, admin, scope="global")
