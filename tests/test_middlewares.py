import pytest


@pytest.mark.parametrize("path", ["/docs", "/route-that-does-not-exist"])
async def test_security_headers_present(client, path):
    response = await client.get(path)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"