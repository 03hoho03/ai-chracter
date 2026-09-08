"""테스트 전역에서 본문이 글자까지 같았던 셋업 헬퍼. `goal-prompt.md §4 T-2`가 80개
파일에 복사돼 있던 것 중 완전 동일본(또는 docstring만 다른 것)만 여기로 옮겼다."""

import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import date, datetime, UTC

import httpx
import sqlalchemy as sa

from api.db.models import User
from api.db.session import engine


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(UTC),
        "privacy_agreed_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _login_as_admin(db_client: httpx.AsyncClient, payload: dict[str, object]) -> None:
    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204


@contextmanager
def _count_queries() -> Generator[Callable[[], int], None, None]:
    """`before_cursor_execute` 이벤트로 실행된 SQL 문 개수를 센다."""
    count = 0

    def _before_cursor_execute(*_args: object, **_kwargs: object) -> None:
        nonlocal count
        count += 1

    sa.event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield lambda: count
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
