"""limit-goal-prompt.md RL-1·RL-3·RL-4·RL-8·RL-11~RL-15·RL-21, S2+S3: 유저별 채팅
레이트리밋 게이트(`api.core.rate_limit_gate`)가 채팅 4경로에 실제로 물려 있는지 검증한다.

경로 테이블은 `test_consent_gate_endpoints.py`의 `_BLOCKED_REQUESTS`와 같은 모양이고, 같은
이유로 **경로 파라미터가 실존할 필요가 없다** — 게이트가 `_owned_room_dependency`(404) 앞의
`Depends`라 소유권 조회 전에 먼저 막는다. 바꿔 말해 이 파일의 429 테스트들은 "게이트가
소유권 검사보다 앞에 있다"까지 함께 증명한다.

⚠️ 429를 만드는 방법은 `monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)`이다 —
요청을 10번 보내서 만들지 않는다. 채팅 경로는 한 번만 통과해도 LLM을 태우므로(그리고 통과
요청마다 `get_llm_client`가 해석되므로) 상한을 진짜로 소진시키는 방식은 이 스위트에서
실행 비용이 그대로 늘어난다. 상한 자체의 산술(`count > limit`)은 `test_core_rate_limit.py`가
기구 단에서 검증한다.

`code`로 갈라 단언하는 이유: 이 4경로는 403(재동의)·503·다른 429를 낼 수 있는 경로라
상태코드만 보면 "막히긴 했는데 이유가 다른" 오탐이 생긴다.
"""

import logging
import uuid
from typing import cast

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import rate_limit_gate
from api.core.redis import redis_client
from api.db.models import User
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published,
    _make_published_character,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
)

# ---- 4경로 테이블 (RL-1). body는 그 경로의 최소 유효 요청 ----

_CHAT_ROUTES: list[tuple[str, str, dict[str, object] | None]] = [
    ("POST", "/chat-rooms/{room_id}/messages", {"content": "안녕"}),
    ("POST", "/chat-rooms/{room_id}/regenerate", None),
    ("PATCH", "/chat-rooms/{room_id}/messages/{message_id}", {"content": "안녕"}),
    ("POST", "/preview-sessions/{id}/messages", {"content": "안녕"}),
]

_ROUTE_IDS = [f"{method} {path}" for method, path, _body in _CHAT_ROUTES]

_DUMMY_IDS = {
    "room_id": str(uuid.uuid4()),
    "message_id": str(uuid.uuid4()),
    "id": uuid.uuid4().hex,
}


# ---- 이 스위트 전용 셋업 (나머지 헬퍼는 factories.py) ----


async def _consented_user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    """`_make_user`의 기본값이 이미 "동의한 사용자"라 재동의 403과 섞이지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


async def _logged_in_user_with_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> str:
    """로그인한 사용자와 그 사용자가 소유한 캐릭터 채팅방까지 만들고 방 id를 돌려준다.
    `POST /chat-rooms`는 RL-1의 4경로가 아니라 게이트가 붙지 않으므로 상한을 소모하지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    assert resp.status_code == 201
    room_id = resp.json()["id"]
    assert isinstance(room_id, str)
    return room_id


# ---- 1. 분당 버스트 초과 → 429 USER_LIMIT / window=minute (RL-11·RL-15) ----


@pytest.mark.parametrize(("method", "path_template", "body"), _CHAT_ROUTES, ids=_ROUTE_IDS)
async def test_chat_routes_return_429_with_user_limit_body_when_burst_exceeded(
    method: str,
    path_template: str,
    body: dict[str, object] | None,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _consented_user(db_client, db_session)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    resp = await db_client.request(method, path_template.format(**_DUMMY_IDS), json=body)

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "USER_LIMIT"
    assert detail["window"] == "minute"
    retry_after = detail["retryAfterSeconds"]
    assert isinstance(retry_after, int)
    # 상한은 분당 창 길이(60초)다 — 게이트 상수를 그대로 인용하면 항진명제가 된다.
    assert 1 <= retry_after <= 60


# ---- 2. 일일 상한 초과 → window=day, KST 자정까지 (RL-4·RL-15) ----


@pytest.mark.parametrize(("method", "path_template", "body"), _CHAT_ROUTES, ids=_ROUTE_IDS)
async def test_chat_routes_return_429_with_day_window_when_daily_exceeded(
    method: str,
    path_template: str,
    body: dict[str, object] | None,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """버스트는 기본값 그대로 두고 일일만 0으로 낮춘다 — 그래야 "버스트 → 일일" 순서(RL-3)에서
    뒤쪽 검사가 실제로 실행된다는 것까지 함께 증명된다."""
    await _consented_user(db_client, db_session)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await db_client.request(method, path_template.format(**_DUMMY_IDS), json=body)

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "USER_LIMIT"
    assert detail["window"] == "day"
    retry_after = detail["retryAfterSeconds"]
    assert isinstance(retry_after, int)
    assert 1 <= retry_after <= 86400


# ---- 2-1. 둘 다 넘겼을 때 이기는 쪽 = 버스트 (RL-3의 순서 결정) ----


async def test_burst_check_runs_before_daily_check(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """위 두 테스트는 한쪽만 0으로 낮추므로 **순서에 대해서는 항진명제다** — 두 검사를 맞바꿔도
    낮추지 않은 쪽은 기본 상한(10/30)에 안 걸려 그냥 통과하고, 같은 `window`가 나온다. 순서를
    구분하는 유일한 상태는 둘 다 넘긴 사용자이고, 그때 나와야 하는 값은 몇 시간짜리 `day`가
    아니라 몇 초짜리 `minute`이다(게이트 docstring의 UX 결정)."""
    await _consented_user(db_client, db_session)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await db_client.post(f"/chat-rooms/{uuid.uuid4()}/messages", json={"content": "안녕"})

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "USER_LIMIT"
    assert detail["window"] == "minute"
    # 분당 창 길이를 넘지 않는다 — `day`가 이겼다면 자정까지 남은 초(최대 86400)가 나온다.
    assert detail["retryAfterSeconds"] <= 60


# ---- 3. Depends 순서: 재동의 403이 429보다 먼저 (RL-1) ----


async def test_reconsent_403_wins_over_429(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user(terms_version=None)
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await db_session.commit()
    await _login_as(db_client, user.id)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    resp = await db_client.post(f"/chat-rooms/{uuid.uuid4()}/messages", json={"content": "안녕"})

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "LEGAL_RECONSENT_REQUIRED"


# ---- 4. 새 scope도 `rate_limit:` 프리픽스 (RL-6) ----


async def test_new_scopes_use_the_rate_limit_prefix_so_the_autouse_flush_covers_them(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`conftest.py`의 autouse `_flush_rate_limit_keys`가 `rate_limit:*`만 지운다 — 새 scope가
    그 프리픽스 밖이면 카운터가 테스트 사이에 남아 뒤 테스트가 실행 순서에 따라 429를 받는다."""
    await _consented_user(db_client, db_session)

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{uuid.uuid4()}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
    # 게이트는 통과했고(429가 아니다) 그 뒤 소유권 검사에서 막혔다.
    assert resp.status_code == 404

    # `core/redis.py`의 클라이언트는 `decode_responses=True`라 런타임 값이 `str`인데 redis
    # 타입 스텁은 항상 `bytes`로 본다(디코딩 여부를 타입으로 표현하지 않는다) — 스텁의 한계라
    # 여기서 한 번 좁힌다.
    keys = cast(list[str], await redis_client.keys("rate_limit:*"))
    assert keys
    assert any(key.startswith("rate_limit:chat_burst:") for key in keys)
    assert any(key.startswith("rate_limit:chat_day:") for key in keys)
    assert all(key.startswith(("rate_limit:chat_burst:", "rate_limit:chat_day:")) for key in keys)


# ---- 5. Redis 장애 시 fail-open + 창당 1회 보고 (RL-8·RL-21) ----


async def test_gate_fails_open_and_reports_redis_dependency_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id = await _logged_in_user_with_room(db_client, db_session)

    calls: list[str] = []

    async def _raise_redis_error(*args: object, **kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    def _spy(exc: BaseException | None = None, *, dependency: str) -> None:
        calls.append(dependency)

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", _raise_redis_error)
    monkeypatch.setattr(rate_limit_gate, "capture_dependency_failure", _spy)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)

    fake = _FakeLLMClient(tokens=["안", "녕"])
    _override_llm_client(fake)
    try:
        first = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
        second = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "또 반가워"})
    finally:
        _clear_llm_override()

    # fail-open: 429가 아니라 정상 스트림이다.
    assert first.status_code == 200
    assert [e["type"] for e in _parse_sse_events(first.text)] == ["token", "token", "done"]
    assert second.status_code == 200
    # RL-21: 창(60초) 안의 두 번째 장애는 보고하지 않는다.
    assert calls == ["redis"]

    monkeypatch.setattr(rate_limit_gate, "REDIS_FAILURE_REPORT_WINDOW_SECONDS", 0)
    _override_llm_client(fake)
    try:
        third = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "세 번째"})
    finally:
        _clear_llm_override()

    assert third.status_code == 200
    assert calls == ["redis", "redis"]


# ---- 6. 초과 로그 (RL-12) ----


async def test_exceeded_request_logs_warning_with_fixed_token(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = await _consented_user(db_client, db_session)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    with caplog.at_level(logging.WARNING):
        resp = await db_client.post(
            f"/chat-rooms/{uuid.uuid4()}/messages", json={"content": "비밀 프롬프트 문장"}
        )

    assert resp.status_code == 429
    records = [record for record in caplog.records if "user_limit_exceeded" in record.getMessage()]
    assert len(records) == 1
    line = records[0].getMessage()
    assert "window=minute" in line
    assert "retry_after=" in line
    assert str(user.id) in line
    # RL-12: user_id·window·retry_after까지. 이메일도 프롬프트 본문도 실리지 않는다.
    assert user.email is not None
    assert user.email not in line
    assert "비밀 프롬프트 문장" not in line


# ---- 7. 429는 제너레이터 전에 끊는다 (RL-13) ----


async def test_successful_request_does_not_touch_the_llm_when_limited(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실존하는 자기 방에 보내므로 게이트가 없었다면 200 스트림이 됐을 요청이다 — 그래서
    `received_prompt is None`이 "게이트가 SSE 제너레이터 앞에서 끊었다"를 실제로 증명한다."""
    room_id = await _logged_in_user_with_room(db_client, db_session)

    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    fake = _FakeLLMClient(tokens=["안", "녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "반가워"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "USER_LIMIT"
    assert fake.received_prompt is None


# ---- 8. 예외 플래그 컬럼 (RL-9) ----


async def test_user_rate_limit_exempt_is_none_before_flush_and_false_after_reload(
    db_session: AsyncSession,
) -> None:
    """`users.rate_limit_exempt`(RL-9)는 이번 단계에서 컬럼만이다 — 게이트가 읽는 건 S5,
    어드민이 뒤집는 건 S7이다. 그래서 여기서 검증할 건 "기본값이 켜져 있지 않다"와
    "true 가 DB 를 왕복한다" 둘뿐이다.

    ⚠️ 첫 단언이 `is None`인 건 오타가 아니다. `mapped_column(default=False)`는 **flush
    시점** 기본값이고 `Base`는 `MappedAsDataclass`가 아니라 생성자를 건드리지 않는다(실측:
    `default=False`가 있든 `server_default`만 있든 flush 전엔 똑같이 `None`이다). 그래서
    S5 의 게이트는 flush 되지 않은 `User` 인스턴스가 아니라 **DB 에서 읽은 행**에만 이
    플래그를 물어야 한다 — 그 자리에서 falsy 는 "예외가 아니다"가 아니라 "아직 모른다"다.
    """
    user = _make_user()
    assert user.rate_limit_exempt is None

    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.rate_limit_exempt is False

    user.rate_limit_exempt = True
    await db_session.flush()
    await db_session.refresh(user)
    assert user.rate_limit_exempt is True
