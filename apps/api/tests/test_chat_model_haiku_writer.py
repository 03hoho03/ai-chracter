"""채팅 글쓰기 모델 Haiku(`haiku_writer`) — 공개 목록에 넣으면 채팅·빌더 미리보기에서 고를 수 있고, 턴마다 그 모델 값을 낸다.

판정 전용 `haiku` 와 다른 id 다. 기본 모델이 아니라 상위 모델 갈래를 타서 레이트리밋 면제 계정도 매 턴 그 값을 내고, Redis 장애면
열지 않는다(Gemini 보다 싸도 그렇다).
공개 목록에서 빼면 지정·미리보기 시작이 403 이고, 이미 Haiku 가 저장된 방은 Gemini 로, Gemini 값으로 돈다. 모델 목록과 공개
가격은 레지스트리 순서(기본 모델, 그 뒤 채팅 턴 가격이 낮은 것부터)로 싣고, 항목마다 기본 모델인지를 싣는다.

설정은 테스트마다 `monkeypatch` 로 정한다 — 로컬 `.env` 의 값에 따라 결과가 달라지지 않게 한다. 실제로 어느 구현·모델 id 로
보내는지는 `test_chat_call_model_routes.py` 가 공급자 SDK 자리에서 본다.
"""

import uuid
import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.db.models import User
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom, ChatTurn
from api.db.models.clover import CloverLedger
from api.llm.client import LLMClientError
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user_with_clover_lot,
    _override_llm_client,
    _parse_sse_events,
    _preview_character_payload,
)

_HAIKU = clover.CLOVER_MODEL_PRICES["haiku_writer"].chat_turn
_GEMINI = clover.CLOVER_MODEL_PRICES["gemini"].chat_turn
_START = 1000


def _configure(monkeypatch: pytest.MonkeyPatch, *, switch: bool = True, visible: list[str] | None = None) -> None:
    monkeypatch.setattr(settings, "chat_premium_models_enabled", switch)
    monkeypatch.setattr(settings, "chat_models_visible", ["opus", "haiku_writer"] if visible is None else visible)


async def _user(db_client: httpx.AsyncClient, db_session: AsyncSession, *, exempt: bool = False) -> User:
    """일반 계정(명단·허용 행 없음). `exempt` 면 레이트리밋 면제 계정이다."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=_START, rate_limit_exempt=exempt)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


async def _room(db_client: httpx.AsyncClient, db_session: AsyncSession, user: User) -> uuid.UUID:
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["id"])


async def _store_model(db_session: AsyncSession, room_id: uuid.UUID, model: str | None) -> None:
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(chat_model=model))
    await db_session.commit()


async def _ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = (await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))).all()
    return sorted((row.kind, row.amount) for row in rows)


async def _send(
    db_client: httpx.AsyncClient, path: str, fake: _FakeLLMClient, body: dict[str, str] | None
) -> httpx.Response:
    _override_llm_client(fake)
    try:
        return await db_client.post(path, json=body)
    finally:
        _clear_llm_override()


def _generated_with(fake: _FakeLLMClient, call_site: str = "chat_generate") -> list[str]:
    return [u.model for u in fake.usages if u.call_site == call_site]


async def _start_preview(db_client: httpx.AsyncClient, model: str) -> httpx.Response:
    return await db_client.post("/preview-sessions", json=_preview_character_payload(), params={"model": model})


# ---- 목록과 공개 가격 ----


@pytest.mark.parametrize(
    ("switch", "visible", "expected"),
    [
        pytest.param(True, ["opus", "sonnet", "haiku_writer"], ["gemini", "haiku_writer", "sonnet", "opus"], id="all"),
        pytest.param(True, ["haiku_writer"], ["gemini", "haiku_writer"], id="haiku-only"),
        pytest.param(True, ["opus"], ["gemini", "opus"], id="default-list-hides-haiku"),
        pytest.param(True, [], ["gemini"], id="blank-list"),
        pytest.param(False, ["opus", "haiku_writer"], ["gemini"], id="switch-off"),
    ],
)
async def test_the_model_list_is_in_price_order_and_marks_exactly_the_default_model(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    switch: bool,
    visible: list[str],
    expected: list[str],
) -> None:
    """화면은 이 순서 그대로 보인다 — 기본 모델이 맨 앞이고, 상위 모델은 턴 가격이 낮은 것부터다(공개 목록의 순서와 무관하다).
    기본 모델 표시는 어느 조합에서도 정확히 하나, 첫 항목이다. 공개 가격의 모델 행도 같은 목록·같은 표시다."""
    _configure(monkeypatch, switch=switch, visible=visible)
    await _user(db_client, db_session)

    listed = (await db_client.get("/chat-models")).json()
    priced = (await db_client.get("/clover/pricing")).json()["models"]

    assert [m["id"] for m in listed] == expected
    assert [m["id"] for m in listed if m["isDefault"]] == ["gemini"]
    assert listed[0]["isDefault"] is True
    assert [(m["id"], m["isDefault"]) for m in priced] == [(m["id"], m["isDefault"]) for m in listed]


async def test_a_visible_haiku_is_listed_with_its_name_price_and_beta_mark(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    await _user(db_client, db_session)

    [haiku] = [m for m in (await db_client.get("/chat-models")).json() if m["id"] == "haiku_writer"]

    assert haiku == {"id": "haiku_writer", "name": "Claude Haiku 5.5", "isDefault": False, "beta": True, "turnCost": 12}


# ---- 공개된 Haiku 방의 턴 ----


async def test_a_haiku_room_charges_its_price_on_every_turn_kind_and_records_the_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """새 턴·재생성·수정이 모두 Haiku 값(12)을 내고, 생성은 Haiku 로 가고, 턴 기록에 Haiku 와 그 값이 남는다."""
    _configure(monkeypatch)
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)
    assert (await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "haiku_writer"})).status_code == 200
    fake = _FakeLLMClient(tokens=["응", "답"])

    sent = await _send(db_client, f"/chat-rooms/{room_id}/messages", fake, {"content": "안녕"})
    regenerated = await _send(db_client, f"/chat-rooms/{room_id}/regenerate", fake, None)
    message_id = await db_session.scalar(
        select(ChatMessage.id).where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.USER)
    )
    _override_llm_client(fake)
    try:
        edited = await db_client.patch(f"/chat-rooms/{room_id}/messages/{message_id}", json={"content": "고침"})
    finally:
        _clear_llm_override()

    for resp in (sent, regenerated, edited):
        assert resp.status_code == 200, resp.text
        assert _parse_sse_events(resp.text)[-1]["type"] == "done"
    assert _HAIKU == 12
    assert await _ledger(db_session, user.id) == [("chat_spend", -_HAIKU)] * 3
    assert _generated_with(fake) == ["haiku_writer"] * 3
    db_session.expire_all()
    turns = (
        await db_session.execute(
            select(ChatTurn.chat_model, ChatTurn.clover_amount).where(ChatTurn.chat_room_id == room_id)
        )
    ).all()
    assert [tuple(turn) for turn in turns] == [("haiku_writer", _HAIKU)] * 3


async def test_a_failed_haiku_generation_refunds_the_haiku_price(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)
    await _store_model(db_session, room_id, "haiku_writer")
    fake = _FakeLLMClient(error=LLMClientError("anthropic down"))

    resp = await _send(db_client, f"/chat-rooms/{room_id}/messages", fake, {"content": "안녕"})

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]
    assert await _ledger(db_session, user.id) == [("chat_refund", _HAIKU), ("chat_spend", -_HAIKU)]
    await db_session.refresh(user)
    assert user.clover_balance == _START
    assert _generated_with(fake) == ["haiku_writer"]


# ---- 면제 계정과 Redis 장애 ----


async def test_a_haiku_turn_is_charged_even_for_a_rate_limit_exempt_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """레이트리밋 면제는 기본 모델 턴의 차감만 건너뛴다 — Gemini 보다 싼 Haiku 도 면제 계정에서 12 를 낸다. 같은 방을 Gemini 로
    돌린 다음 턴은 내지 않는다."""
    _configure(monkeypatch)
    user = await _user(db_client, db_session, exempt=True)
    room_id = await _room(db_client, db_session, user)
    await _store_model(db_session, room_id, "haiku_writer")
    fake = _FakeLLMClient(tokens=["응"])

    first = await _send(db_client, f"/chat-rooms/{room_id}/messages", fake, {"content": "안녕"})
    await _store_model(db_session, room_id, None)
    second = await _send(db_client, f"/chat-rooms/{room_id}/messages", fake, {"content": "다시"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert await _ledger(db_session, user.id) == [("chat_spend", -_HAIKU)]
    assert _generated_with(fake) == ["haiku_writer", "gemini"]


async def test_a_haiku_turn_is_refused_when_redis_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기본 모델이 아닌 턴은 분당 상한을 못 센 채 열지 않는다 — Gemini 턴은 Redis 장애에도 내고 열지만 Haiku 는 싸도 상위 모델 규칙이다."""
    _configure(monkeypatch)
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)
    await _store_model(db_session, room_id, "haiku_writer")

    async def _down(*args: object, **kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", _down)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)
    fake = _FakeLLMClient(tokens=["응"])

    resp = await _send(db_client, f"/chat-rooms/{room_id}/messages", fake, {"content": "안녕"})

    assert resp.status_code == 503
    assert resp.json()["detail"] == {"code": "CHAT_MODEL_UNAVAILABLE"}
    assert await _ledger(db_session, user.id) == []
    assert fake.usages == []


# ---- 빌더 미리보기 ----


async def test_a_haiku_preview_starts_and_charges_the_haiku_price(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    user = await _user(db_client, db_session)
    started = await _start_preview(db_client, "haiku_writer")
    assert started.status_code == 201, started.text
    fake = _FakeLLMClient(tokens=["응", "답"])

    resp = await _send(
        db_client, f"/preview-sessions/{started.json()['previewSessionId']}/messages", fake, {"content": "안녕"}
    )

    assert resp.status_code == 200, resp.text
    assert _parse_sse_events(resp.text)[-1]["type"] == "done"
    assert await _ledger(db_session, user.id) == [("chat_spend", -_HAIKU)]
    assert _generated_with(fake, "preview_generate") == ["haiku_writer"]


# ---- 숨김(기본 공개 목록) ----


async def test_a_hidden_haiku_is_refused_everywhere_and_a_stored_haiku_room_runs_on_gemini(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """공개 목록이 기본값(Opus 하나)이면 Haiku 는 목록·공개 가격에 없고 지정·미리보기 시작이 403 이다. 숨기기 전에 Haiku 를 고른
    방은 막히지 않고 Gemini 로, Gemini 값으로 돈다 — 숨기는 것이 롤백이라 그때 턴이 막히면 롤백이 장애가 된다."""
    _configure(monkeypatch, visible=["opus"])
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)

    listed = [m["id"] for m in (await db_client.get("/chat-models")).json()]
    priced = [m["id"] for m in (await db_client.get("/clover/pricing")).json()["models"]]
    chosen = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "haiku_writer"})
    preview = await _start_preview(db_client, "haiku_writer")
    await _store_model(db_session, room_id, "haiku_writer")
    fake = _FakeLLMClient(tokens=["응"])
    room = (await db_client.get(f"/chat-rooms/{room_id}")).json()
    resp = await _send(db_client, f"/chat-rooms/{room_id}/messages", fake, {"content": "안녕"})

    assert "haiku_writer" not in listed and "haiku_writer" not in priced
    assert (chosen.status_code, chosen.json()["detail"]) == (403, {"code": "CHAT_MODEL_NOT_ALLOWED"})
    assert (preview.status_code, preview.json()["detail"]) == (403, {"code": "CHAT_MODEL_NOT_ALLOWED"})
    assert (room["chatModel"], room["effectiveChatModel"], room["turnCost"]) == ("haiku_writer", "gemini", _GEMINI)
    assert resp.status_code == 200
    assert await _ledger(db_session, user.id) == [("chat_spend", -_GEMINI)]
    assert _generated_with(fake) == ["gemini"]


async def test_the_judgment_only_haiku_is_still_not_a_chat_room_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """글쓰기 id 를 더해도 판정 전용 `haiku` 는 방 모델 요청 타입 밖이라 422 다."""
    _configure(monkeypatch)
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)

    resp = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "haiku"})

    assert resp.status_code == 422
