from fastapi.testclient import TestClient


def test_session_round_trip_create_read_delete(api_client: TestClient) -> None:
    api_client.cookies.clear()

    create_resp = api_client.post("/dev/session-echo", json={"data": {"user_id": "abc"}})
    assert create_resp.status_code == 201
    assert api_client.cookies.get("session_id") is not None

    read_resp = api_client.get("/dev/session-echo")
    assert read_resp.status_code == 200
    assert read_resp.json() == {"user_id": "abc"}

    delete_resp = api_client.delete("/dev/session-echo")
    assert delete_resp.status_code == 204

    read_after_delete_resp = api_client.get("/dev/session-echo")
    assert read_after_delete_resp.status_code in (401, 404)


def test_session_read_without_cookie_is_unauthorized(api_client: TestClient) -> None:
    api_client.cookies.clear()

    read_resp = api_client.get("/dev/session-echo")
    assert read_resp.status_code == 401


def test_session_data_is_isolated_per_session(api_client: TestClient) -> None:
    api_client.cookies.clear()

    resp_a = api_client.post("/dev/session-echo", json={"data": {"who": "a"}})
    session_id_a = resp_a.cookies["session_id"]
    resp_b = api_client.post("/dev/session-echo", json={"data": {"who": "b"}})
    session_id_b = resp_b.cookies["session_id"]

    assert session_id_a != session_id_b

    api_client.cookies.set("session_id", session_id_a)
    read_a = api_client.get("/dev/session-echo")
    api_client.cookies.set("session_id", session_id_b)
    read_b = api_client.get("/dev/session-echo")

    assert read_a.json() == {"who": "a"}
    assert read_b.json() == {"who": "b"}
