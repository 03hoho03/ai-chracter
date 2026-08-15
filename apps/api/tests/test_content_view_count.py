import uuid
from http.cookies import SimpleCookie

import pytest
from fastapi import Request, Response
from redis.exceptions import RedisError

from api.content.view_count import resolve_viewer_key, try_mark_viewed
from api.core.config import settings
from api.core.redis import redis_client


def _request(guest_cookie: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if guest_cookie is not None:
        headers.append((b"cookie", f"{settings.guest_viewer_cookie_name}={guest_cookie}".encode()))
    return Request({"type": "http", "headers": headers})


def _set_cookie_morsel(response: Response) -> "SimpleCookie | None":
    header = response.headers.get("set-cookie")
    if header is None:
        return None
    cookie = SimpleCookie()
    cookie.load(header)
    return cookie


def test_logged_in_user_key_uses_user_prefix() -> None:
    user_id = uuid.uuid4()
    response = Response()

    key = resolve_viewer_key(_request(), response, user_id)

    assert key == f"user:{user_id}"
    assert response.headers.get("set-cookie") is None


def test_guest_without_cookie_gets_new_uuid_and_set_cookie() -> None:
    response = Response()

    key = resolve_viewer_key(_request(), response, None)

    prefix, _, raw_id = key.partition(":")
    assert prefix == "guest"
    issued_id = uuid.UUID(raw_id)

    cookie = _set_cookie_morsel(response)
    assert cookie is not None
    morsel = cookie[settings.guest_viewer_cookie_name]
    assert morsel.value == str(issued_id)
    assert morsel["max-age"] == str(settings.guest_viewer_cookie_max_age_seconds)
    assert morsel["httponly"]


def test_guest_with_cookie_reuses_it_without_rebaking() -> None:
    existing_id = str(uuid.uuid4())
    response = Response()

    key = resolve_viewer_key(_request(guest_cookie=existing_id), response, None)

    assert key == f"guest:{existing_id}"
    assert response.headers.get("set-cookie") is None


def test_corrupted_guest_cookie_is_reissued() -> None:
    response = Response()

    key = resolve_viewer_key(_request(guest_cookie="not-a-uuid"), response, None)

    prefix, _, raw_id = key.partition(":")
    assert prefix == "guest"
    issued_id = uuid.UUID(raw_id)

    cookie = _set_cookie_morsel(response)
    assert cookie is not None
    assert cookie[settings.guest_viewer_cookie_name].value == str(issued_id)


async def test_try_mark_viewed_dedups_same_content_and_viewer() -> None:
    content_id = uuid.uuid4()
    viewer_key = f"user:{uuid.uuid4()}"

    assert await try_mark_viewed(content_id, viewer_key) is True
    assert await try_mark_viewed(content_id, viewer_key) is False


async def test_try_mark_viewed_sets_dedup_ttl() -> None:
    content_id = uuid.uuid4()
    viewer_key = f"user:{uuid.uuid4()}"

    await try_mark_viewed(content_id, viewer_key)

    ttl = await redis_client.ttl(f"view:{content_id}:{viewer_key}")
    assert ttl == settings.content_view_dedup_ttl_seconds


async def test_try_mark_viewed_counts_different_contents_separately() -> None:
    viewer_key = f"user:{uuid.uuid4()}"

    assert await try_mark_viewed(uuid.uuid4(), viewer_key) is True
    assert await try_mark_viewed(uuid.uuid4(), viewer_key) is True


async def test_try_mark_viewed_counts_different_viewers_separately() -> None:
    content_id = uuid.uuid4()

    assert await try_mark_viewed(content_id, f"user:{uuid.uuid4()}") is True
    assert await try_mark_viewed(content_id, f"user:{uuid.uuid4()}") is True


async def test_user_and_guest_prefixes_never_collide_on_same_uuid() -> None:
    content_id = uuid.uuid4()
    shared_id = uuid.uuid4()

    assert await try_mark_viewed(content_id, f"user:{shared_id}") is True
    assert await try_mark_viewed(content_id, f"guest:{shared_id}") is True


async def test_try_mark_viewed_swallows_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise_redis_error(*args: object, **kwargs: object) -> None:
        raise RedisError("connection refused")

    monkeypatch.setattr(redis_client, "set", _raise_redis_error)

    assert await try_mark_viewed(uuid.uuid4(), f"user:{uuid.uuid4()}") is False
