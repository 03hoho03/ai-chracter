import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.session import get_db_session
from api.novelize.access import require_novelize_access
from factories import _grant_novelize, _login_as, _make_user

# 소설 라우트는 아직 없다 — 게이트만 붙인 시험용 라우트로 의존성 자체를 본다.
_probe_app = FastAPI()


@_probe_app.get("/probe")
async def _probe(user_id: uuid.UUID = Depends(require_novelize_access)) -> dict[str, str]:
    return {"userId": str(user_id)}


@pytest_asyncio.fixture
async def probe_client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def _session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    _probe_app.dependency_overrides[get_db_session] = _session
    transport = httpx.ASGITransport(app=_probe_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    _probe_app.dependency_overrides.clear()


async def _logged_in_user(
    db_session: AsyncSession, client: httpx.AsyncClient, *, granted: bool
) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    if granted:
        await _grant_novelize(db_session, user.id)
    await db_session.commit()
    await _login_as(client, user.id)
    return user.id


def _set_gate(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, allowlist: list[uuid.UUID]) -> None:
    monkeypatch.setattr(settings, "novelize_enabled", enabled)
    monkeypatch.setattr(settings, "novelize_grant_allowlist", allowlist)


async def test_granted_and_allowlisted_user_passes_when_enabled(
    probe_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _logged_in_user(db_session, probe_client, granted=True)
    _set_gate(monkeypatch, enabled=True, allowlist=[user_id])

    resp = await probe_client.get("/probe")

    assert resp.status_code == 200
    assert resp.json() == {"userId": str(user_id)}


async def test_kill_switch_off_blocks_even_a_granted_allowlisted_user(
    probe_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _logged_in_user(db_session, probe_client, granted=True)
    _set_gate(monkeypatch, enabled=False, allowlist=[user_id])

    resp = await probe_client.get("/probe")

    assert resp.status_code == 403
    assert resp.json()["detail"] == {"code": "NOVELIZE_NOT_ALLOWED"}


async def test_allowlisted_user_without_a_grant_row_is_blocked(
    probe_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _logged_in_user(db_session, probe_client, granted=False)
    _set_gate(monkeypatch, enabled=True, allowlist=[user_id])

    resp = await probe_client.get("/probe")

    assert resp.status_code == 403
    assert resp.json()["detail"] == {"code": "NOVELIZE_NOT_ALLOWED"}


async def test_grant_row_stops_working_once_the_user_leaves_the_allowlist(
    probe_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """명단에서 지우는 것만으로 회수돼야 한다 — 허용 행은 그대로 남아 있다. 명단에는 다른 계정을 둬서
    "명단이 비면 막힌다"가 아니라 "이 계정이 명단에 없으면 막힌다"를 본다."""
    user_id = await _logged_in_user(db_session, probe_client, granted=True)
    _set_gate(monkeypatch, enabled=True, allowlist=[uuid.uuid4()])

    resp = await probe_client.get("/probe")

    assert resp.status_code == 403
    assert resp.json()["detail"] == {"code": "NOVELIZE_NOT_ALLOWED"}


async def test_gate_requires_a_session(probe_client: httpx.AsyncClient) -> None:
    resp = await probe_client.get("/probe")

    assert resp.status_code == 401
