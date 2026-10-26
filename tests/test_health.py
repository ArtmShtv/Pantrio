from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_db(client: AsyncClient) -> None:
    """Needs Postgres running (docker compose up -d)."""
    response = await client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
