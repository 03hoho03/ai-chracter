import uuid

import httpx


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def test_generated_images_requires_login(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()

    resp = await api_client.get("/me/generated-images")
    assert resp.status_code == 401


async def test_generated_images_returns_empty_stub_list(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())

    resp = await api_client.get("/me/generated-images")
    assert resp.status_code == 200
    assert resp.json() == []
