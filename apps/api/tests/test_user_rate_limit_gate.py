"""유저별 채팅
레이트리밋 게이트(`api.core.rate_limit_gate`)가 채팅 4경로에 실제로 물려 있는지 검증한다.

경로 테이블은 `test_consent_gate_endpoints.py`의 `_BLOCKED_REQUESTS`와 같은 모양이다.

🔴 **경로 파라미터는 실존해야 한다 — 그리고 이 스위트는 더 이상 "게이트가 소유권 검사보다
앞에 있다"를 증명하지 않는다.** 예전에는 게이트가 `_owned_room_dependency`(404) 앞의
`Depends`라 더미 id로도 429를 받아낼 수 있었고, 그 사실 자체가 부수 증명이었다.
클로버 도입이 **게이트를 조회·검증 의존성 뒤로 옮겼다** — 차감이 일어난 뒤
404/400이 나면 클로버가 사라지기 때문이다. 그래서 이제 순서가 반대이고(404가 429보다 먼저),
이 스위트는 `_real_route_ids`로 실물을 만들어 게이트에 닿는다.

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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import rate_limit_gate
from api.core.redis import redis_client
from api.db.models import User
from api.db.models.chat import ChatMessage, ChatMessageRole
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

# ---- 4경로 테이블. body는 그 경로의 최소 유효 요청 ----

_CHAT_ROUTES: list[tuple[str, str, dict[str, object] | None]] = [
    ("POST", "/chat-rooms/{room_id}/messages", {"content": "안녕"}),
    ("POST", "/chat-rooms/{room_id}/regenerate", None),
    ("PATCH", "/chat-rooms/{room_id}/messages/{message_id}", {"content": "안녕"}),
    ("POST", "/preview-sessions/{id}/messages", {"content": "안녕"}),
]

_ROUTE_IDS = [f"{method} {path}" for method, path, _body in _CHAT_ROUTES]


# ---- 이 스위트 전용 셋업 (나머지 헬퍼는 factories.py) ----


async def _consented_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession, **overrides: object
) -> User:
    """`_make_user`의 기본값이 이미 "동의한 사용자"라 재동의 403과 섞이지 않는다.
    `**overrides`는 `_make_user`로 그대로 넘어간다(9번 절의 `rate_limit_exempt`)."""
    user = _make_user(**overrides)
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


_PREVIEW_PAYLOAD: dict[str, object] = {
    "name": "아리아",
    "oneLiner": "한 줄 소개",
    "thumbnailAssetId": None,
    "intro": "안녕하세요, 아리아예요",
    "exampleDialogues": [],
    "characterPrompt": "너는 아리아다.",
    "playguide": None,
    "situationalImages": [],
    "description": "상세 설명",
    "genreId": None,
    "target": None,
    "hashtags": [],
    "visibility": "private",
}


async def _clear_rate_limit_counters() -> None:
    """셋업이 남긴 카운터를 지운다.

    `conftest.py`의 autouse `_flush_rate_limit_keys`는 테스트 **시작 전**에만 돈다. 한 테스트
    안에서 셋업 전송을 한 뒤 상한을 패치하면 버킷이 0에서 시작하지 않아 산술이 어긋난다.
    """
    keys = await redis_client.keys("rate_limit:*")
    if keys:
        await redis_client.delete(*keys)


async def _real_room_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user: User
) -> str:
    """그 사용자가 소유한 캐릭터 채팅방을 실제로 만든다.

    🔴 클로버 도입이 게이트를 조회·검증 의존성 **뒤**로 옮기면서 이 스위트가
    쓰던 더미 id 지름길이 막혔다 — 없는 방은 게이트에 닿기도 전에 404다.

    `POST /chat-rooms`는 채팅 4경로가 아니라 게이트가 안 붙는다 — 이 셋업만으로는
    버킷이 소모되지 않는다.
    """
    genre = await _get_genre(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()

    created = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "character"}
    )
    assert created.status_code == 201
    return str(created.json()["id"])


async def _real_route_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user: User
) -> dict[str, str]:
    """4경로가 쓸 **실존** 경로 파라미터(방·메시지·미리보기 세션)를 만든다.

    셋업 전송 1회가 버킷을 소모하므로 마지막에 카운터를 지운다 — 호출부는 **이 함수 뒤에**
    상한을 패치해야 한다.
    """
    room_id = await _real_room_id(db_client, db_session, user)

    # 편집 대상 사용자 메시지와 재생성 대상 AI 응답을 성공 전송 한 번으로 함께 만든다.
    _override_llm_client(_FakeLLMClient(tokens=["첫", "응답"]))
    try:
        sent = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
    assert sent.status_code == 200

    rows = (
        await db_session.scalars(
            select(ChatMessage).where(
                ChatMessage.chat_room_id == uuid.UUID(room_id),
                ChatMessage.role == ChatMessageRole.USER,
            )
        )
    ).all()
    assert len(rows) == 1

    preview = await db_client.post("/preview-sessions", json=_PREVIEW_PAYLOAD)
    assert preview.status_code == 201

    await _clear_rate_limit_counters()
    return {
        "room_id": room_id,
        "message_id": str(rows[0].id),
        "id": str(preview.json()["previewSessionId"]),
    }


# ---- 1. 분당 버스트 초과 → 429 USER_LIMIT / window=minute ----


@pytest.mark.parametrize(("method", "path_template", "body"), _CHAT_ROUTES, ids=_ROUTE_IDS)
async def test_chat_routes_return_429_with_user_limit_body_when_burst_exceeded(
    method: str,
    path_template: str,
    body: dict[str, object] | None,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _consented_user(db_client, db_session)
    ids = await _real_route_ids(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    # apps/api/CLAUDE.md "테스트 인프라" — 게이트가 조회 뒤로 내려간 뒤는 `llm_client`가
    # 게이트보다 먼저 resolve된다. 429로 막혀 실제로 쓰이지 않아도 오버라이드가 없으면 진짜
    # 클라이언트를 만들다 API 키 부재로 500이 난다.
    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.request(method, path_template.format(**ids), json=body)
    finally:
        _clear_llm_override()

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "USER_LIMIT"
    assert detail["window"] == "minute"
    retry_after = detail["retryAfterSeconds"]
    assert isinstance(retry_after, int)
    # 상한은 분당 창 길이(60초)다 — 게이트 상수를 그대로 인용하면 항진명제가 된다.
    assert 1 <= retry_after <= 60


# ---- 1-1. 채팅 4경로가 버킷 하나를 공유한다 ----


async def test_four_chat_routes_share_one_bucket(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """위 parametrize는 경로마다 **새 유저 + 상한 0**이라 버킷이 하나인지에 대해서는
    항진명제다 — scope를 경로별로 갈라도(`_BURST_SCOPE + route`) 13개가 전부 그대로 초록이다.
    한 버킷을 구분하는 유일한 상태는 **한 사용자가 서로 다른 경로로 상한을 나눠 쓴 뒤**이고,
    그때 막혀야 하는 것은 아직 한 번도 안 쓴 나머지 두 경로다. 버킷이 갈리면 그 둘은 자기 몫의
    첫 요청이라 통과해 404로 떨어진다.

    단일 버킷을 고른 이유가 정확히 이 우회로다 — 전송으로 상한을 소진한 뒤 재생성·편집
    으로 계속 태울 수 있으면 상한이 상한이 아니다.
    """
    user = await _consented_user(db_client, db_session)
    ids = await _real_route_ids(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 2)

    _override_llm_client(_FakeLLMClient())
    try:
        sent = await db_client.post(
            f"/chat-rooms/{ids['room_id']}/messages", json={"content": "안녕"}
        )
        regenerated = await db_client.post(f"/chat-rooms/{ids['room_id']}/regenerate")
    finally:
        _clear_llm_override()
    # 게이트를 통과했다(429가 아니다). 게이트가 조회 뒤로 내려간 뒤로는 방이 실존하므로
    # 턴이 끝까지 돌아 200이다 — 서로 다른 두 경로가 같은 버킷의 2칸을 썼다는 뜻이다.
    assert sent.status_code == 200
    assert regenerated.status_code == 200

    # 429로 막힐 요청이지만 게이트보다 먼저 `llm_client`가 resolve된다 — 위 두 요청과
    # 같은 이유로 오버라이드가 필요하다.
    _override_llm_client(_FakeLLMClient())
    try:
        edited = await db_client.patch(
            f"/chat-rooms/{ids['room_id']}/messages/{ids['message_id']}",
            json={"content": "안녕"},
        )
        previewed = await db_client.post(
            f"/preview-sessions/{ids['id']}/messages", json={"content": "안녕"}
        )
    finally:
        _clear_llm_override()

    for resp in (edited, previewed):
        assert resp.status_code == 429
        detail = resp.json()["detail"]
        assert detail["code"] == "USER_LIMIT"
        assert detail["window"] == "minute"


# ---- 2. 일일 상한 초과 → 429, KST 자정까지 ----


@pytest.mark.parametrize(("method", "path_template", "body"), _CHAT_ROUTES, ids=_ROUTE_IDS)
async def test_chat_routes_return_429_with_day_window_when_daily_exceeded(
    method: str,
    path_template: str,
    body: dict[str, object] | None,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """버스트는 기본값 그대로 두고 일일만 0으로 낮춘다 — 그래야 "버스트 → 일일"
    순서(게이트 docstring)에서 뒤쪽 검사가 실제로 실행된다는 것까지 함께
    증명된다.

    🔴 **클로버 도입으로 바디가 바뀌었다**. 무료 일일분을 다 쓴
    뒤에는 클로버가 대신 내므로, **낼 클로버가 없을 때** 나가는 것이 이 429다 —
    `USER_LIMIT`/`window=day`가 아니라 `CLOVER_REQUIRED`/`window=clover`다.
    `_make_user`의 기본 잔액이 0이라 이 셋업이 곧 "낼 것이 없는 사용자"다.
    ⇒ **채팅에서 `window="day"`는 이제 도달할 수 없다** — 일일 초과는 전부 클로버 분기로
    넘어간다(잔액이 있으면 통과, 없으면 이 429).
    """
    user = await _consented_user(db_client, db_session)
    ids = await _real_route_ids(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.request(method, path_template.format(**ids), json=body)
    finally:
        _clear_llm_override()

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "CLOVER_REQUIRED"
    assert detail["window"] == "clover"
    retry_after = detail["retryAfterSeconds"]
    assert isinstance(retry_after, int)
    assert 1 <= retry_after <= 86400


# ---- 2-1. 둘 다 넘겼을 때 이기는 쪽 = 버스트 (게이트 docstring) ----


async def test_burst_check_runs_before_daily_check(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """위 두 테스트는 한쪽만 0으로 낮추므로 **순서에 대해서는 항진명제다** — 두 검사를 맞바꿔도
    낮추지 않은 쪽은 기본 상한(10/30)에 안 걸려 그냥 통과하고, 같은 `window`가 나온다. 순서를
    구분하는 유일한 상태는 둘 다 넘긴 사용자이고, 그때 나와야 하는 값은 몇 시간짜리 `day`가
    아니라 몇 초짜리 `minute`이다(게이트 docstring의 UX 결정)."""
    user = await _consented_user(db_client, db_session)
    room_id = await _real_room_id(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "USER_LIMIT"
    assert detail["window"] == "minute"
    # 분당 창 길이를 넘지 않는다 — `day`가 이겼다면 자정까지 남은 초(최대 86400)가 나온다.
    assert detail["retryAfterSeconds"] <= 60


# ---- 3. Depends 순서: 재동의 403이 429보다 먼저 ----


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


# ---- 4. 새 scope도 `rate_limit:` 프리픽스 ----


async def test_new_scopes_use_the_rate_limit_prefix_so_the_autouse_flush_covers_them(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`conftest.py`의 autouse `_flush_rate_limit_keys`가 `rate_limit:*`만 지운다 — 새 scope가
    그 프리픽스 밖이면 카운터가 테스트 사이에 남아 뒤 테스트가 실행 순서에 따라 429를 받는다."""
    user = await _consented_user(db_client, db_session)
    room_id = await _real_room_id(db_client, db_session, user)

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
    # 게이트를 통과해 턴이 끝까지 돌았다(429가 아니다) — 그 과정에서 두 scope의 키가 찍힌다.
    assert resp.status_code == 200

    # `core/redis.py`의 클라이언트는 `decode_responses=True`라 런타임 값이 `str`인데 redis
    # 타입 스텁은 항상 `bytes`로 본다(디코딩 여부를 타입으로 표현하지 않는다) — 스텁의 한계라
    # 여기서 한 번 좁힌다.
    keys = cast(list[str], await redis_client.keys("rate_limit:*"))
    assert keys
    assert any(key.startswith("rate_limit:chat_burst:") for key in keys)
    assert any(key.startswith("rate_limit:chat_day:") for key in keys)
    assert all(key.startswith(("rate_limit:chat_burst:", "rate_limit:chat_day:")) for key in keys)


# ---- 5. Redis 장애 시 fail-open + 창당 1회 보고 ----


async def test_gate_fails_open_and_reports_redis_dependency_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _consented_user(db_client, db_session)
    room_id = await _real_room_id(db_client, db_session, user)

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
    # 창(60초) 안의 두 번째 장애는 보고하지 않는다.
    assert calls == ["redis"]

    monkeypatch.setattr(rate_limit_gate, "REDIS_FAILURE_REPORT_WINDOW_SECONDS", 0)
    _override_llm_client(fake)
    try:
        third = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "세 번째"})
    finally:
        _clear_llm_override()

    assert third.status_code == 200
    assert calls == ["redis", "redis"]


# ---- 6. 초과 로그 ----


async def test_exceeded_request_logs_warning_with_fixed_token(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = await _consented_user(db_client, db_session)
    room_id = await _real_room_id(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    _override_llm_client(_FakeLLMClient())
    try:
        with caplog.at_level(logging.WARNING):
            resp = await db_client.post(
                f"/chat-rooms/{room_id}/messages", json={"content": "비밀 프롬프트 문장"}
            )
    finally:
        _clear_llm_override()

    assert resp.status_code == 429
    records = [record for record in caplog.records if "user_limit_exceeded" in record.getMessage()]
    assert len(records) == 1
    line = records[0].getMessage()
    # `code`가 있어야 이미지의 두 429(`USER_LIMIT`/`QUEUE_FULL`)를 로그에서 가른다.
    assert "code=USER_LIMIT" in line
    assert "window=minute" in line
    assert "retry_after=" in line
    assert str(user.id) in line
    # user_id·window·retry_after까지. 이메일도 프롬프트 본문도 실리지 않는다.
    assert user.email is not None
    assert user.email not in line
    assert "비밀 프롬프트 문장" not in line


# ---- 7. 429는 제너레이터 전에 끊는다 ----


async def test_successful_request_does_not_touch_the_llm_when_limited(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실존하는 자기 방에 보내므로 게이트가 없었다면 200 스트림이 됐을 요청이다 — 그래서
    `received_prompt is None`이 "게이트가 SSE 제너레이터 앞에서 끊었다"를 실제로 증명한다."""
    user = await _consented_user(db_client, db_session)
    room_id = await _real_room_id(db_client, db_session, user)

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


# ---- 8. 예외 플래그 컬럼 ----


async def test_user_rate_limit_exempt_is_none_before_flush_and_false_after_reload(
    db_session: AsyncSession,
) -> None:
    """`users.rate_limit_exempt` 컬럼 자체만 본다 — 게이트가 그 값으로 무엇을 하는지는
    아래 9번 절이고, 어드민이 뒤집는 건 어드민 토글 쪽이다. 그래서 여기서 검증할 건 "기본값이 켜져 있지
    않다"와 "true 가 DB 를 왕복한다" 둘뿐이다.

    ⚠️ 첫 단언이 `is None`인 건 오타가 아니다. `Base`는 `MappedAsDataclass`가 아니라
    생성자를 건드리지 않고 `server_default=false()`는 INSERT 가 실행돼야 값이 생기므로,
    flush 전 속성은 `None`이다(`default=False`를 붙여도 그건 flush 시점 기본값이라
    flush 전에는 똑같이 `None`이다 — A/B 로 실측하고 인자를 지웠다). 그래서
    면제를 판정하는 게이트는 flush 되지 않은 `User` 인스턴스가 아니라 **DB 에서 읽은 행**에만 이
    플래그를 물어야 한다 — 그 자리에서 falsy 는 "예외가 아니다"가 아니라 "아직 모른다"다.
    """
    user = _make_user()
    # ⚠️ `object`로 한 번 끊어서 단언한다. `Mapped[bool]` 속성을 그대로
    # `is None`으로 단언하면 mypy 가 그 뒤를 unreachable 로 좁혀 **아래 왕복 세 줄을 아예
    # 검사하지 않는다** — A/B 로 실측했다.
    before: object = user.rate_limit_exempt
    assert before is None

    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.rate_limit_exempt is False

    user.rate_limit_exempt = True
    await db_session.flush()
    await db_session.refresh(user)
    assert user.rate_limit_exempt is True


# ---- 9. 예외 판정: 일일만 면제하고 버스트는 유지한다 ----


async def test_exempt_user_bypasses_the_daily_limit_but_not_the_per_minute_burst(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """면제의 범위는 일일 상한(과 이미지 토큰버킷)이지 "상한 해제"가 아니다.
    분당 버스트는 예외 계정도 그대로 받는다 — 버스트는 쿼터가 아니라 폭주 방어라서 면제
    대상에게 열어 줄 이유가 없다."""
    user = await _consented_user(db_client, db_session, rate_limit_exempt=True)
    room_id = await _real_room_id(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_FakeLLMClient())
    try:
        passed = await db_client.post(
            f"/chat-rooms/{room_id}/messages", json={"content": "안녕"}
        )
    finally:
        _clear_llm_override()
    # 게이트를 통과해 턴이 끝까지 돌았다(429가 아니다) — 면제가 일일 상한을 비껴갔다는 뜻이다.
    assert passed.status_code == 200

    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    _override_llm_client(_FakeLLMClient())
    try:
        blocked = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert blocked.status_code == 429
    detail = blocked.json()["detail"]
    assert detail["code"] == "USER_LIMIT"
    assert detail["window"] == "minute"


async def test_non_exempt_user_hits_the_same_daily_limit_under_the_same_setup(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """위 테스트의 짝. 셋업이 글자까지 같고 `rate_limit_exempt`만 다르다 — 이 짝이 없으면 위의
    통과는 "면제가 먹혔다"가 아니라 "이 셋업에서는 원래 아무도 안 걸린다"일 수 있다(그 경우
    면제 판정을 통째로 지워도 두 테스트가 다 초록이다)."""
    user = await _consented_user(db_client, db_session, rate_limit_exempt=False)
    room_id = await _real_room_id(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_FakeLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 429
    # 잔액 0이라 클로버로도 못 낸다 — 면제 계정과의 대비는 그대로다.
    detail = resp.json()["detail"]
    assert detail["code"] == "CLOVER_REQUIRED"
    assert detail["window"] == "clover"


async def test_exemption_is_read_from_the_db_row_not_the_session_cookie(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """판정의 소스는 `users.rate_limit_exempt` 행 하나다 — Redis 미러도, 로그인 시점에
    세션에 굳는 사본도 없다. 그래서 로그인한 **뒤에** 행을 뒤집으면 같은 쿠키로 보낸 다음
    요청이 바로 일일 상한에 걸린다. 무효화할 캐시가 없다는 것이 이 단언의 내용이다."""
    user = await _consented_user(db_client, db_session, rate_limit_exempt=True)
    room_id = await _real_room_id(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    _override_llm_client(_FakeLLMClient())
    try:
        before = await db_client.post(
            f"/chat-rooms/{room_id}/messages", json={"content": "안녕"}
        )
    finally:
        _clear_llm_override()
    assert before.status_code == 200

    # ORM 대입이 아니라 raw UPDATE 다 — 대입은 이 세션의 인스턴스를 고쳐 버려서 "게이트가 DB 를
    # 읽었는가"를 구분할 수 없게 만든다.
    await db_session.execute(
        text("UPDATE users SET rate_limit_exempt = false WHERE id = :id"), {"id": user.id}
    )
    # 프로덕션은 요청마다 세션이 새로 열리지만 테스트는 `db_client`가 앱에 이 `db_session`
    # 하나를 물려준다(conftest) — identity map 이 그 차이를 덮으므로 여기서 한 번 만료시켜
    # "새 요청의 새 세션"을 재현한다.
    db_session.expire_all()

    _override_llm_client(_FakeLLMClient())
    try:
        after = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert after.status_code == 429
    # 면제가 풀린 뒤에는 일일 상한에 걸리고, 잔액이 0이라 클로버로도 못 낸다.
    detail = after.json()["detail"]
    assert detail["code"] == "CLOVER_REQUIRED"
    assert detail["window"] == "clover"
