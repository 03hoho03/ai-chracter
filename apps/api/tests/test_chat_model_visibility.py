"""채팅 상위 모델의 공개 목록 — 총 스위치(`chat_premium_models_enabled`) 아래에서 모델마다 채팅에 보일지를 고른다.

공개 목록(`chat_models_visible`)에 있는 상위 모델만 모델 목록·공개 가격에 실리고, 방 모델 지정·빌더 미리보기 시작이 받아 주고,
저장된 방의 턴이 그 모델로 돈다. 목록에서 뺀 모델은 지정·미리보기 시작이 스위치 꺼짐과 같은 403 이고, 이미 그 모델이 저장된
방은 막히지 않고 Gemini 로, Gemini 가격으로 돈다 — 숨기는 것이 롤백이라 그때 턴이 막히면 롤백이 장애가 된다. 총 스위치를 끄면
목록과 무관하게 상위 모델은 모두 숨는다.

설정은 테스트마다 `monkeypatch` 로 정한다 — 로컬 `.env` 의 값에 따라 결과가 달라지지 않게 한다.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
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

_SONNET = clover.CLOVER_MODEL_PRICES["sonnet"].chat_turn
_GEMINI = clover.CLOVER_MODEL_PRICES["gemini"].chat_turn
_START = 1000


def _configure(monkeypatch: pytest.MonkeyPatch, *, switch: bool, visible: list[str]) -> None:
    monkeypatch.setattr(settings, "chat_premium_models_enabled", switch)
    monkeypatch.setattr(settings, "chat_models_visible", visible)


async def _user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    """오늘 확인을 마친 일반 계정(명단·허용 행 없음) — Gemini 턴이 하루 1회 확인 429 가 아니라 차감으로 드러나게 한다."""
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=_START, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
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


async def _stored(db_session: AsyncSession, room_id: uuid.UUID) -> str | None:
    return await db_session.scalar(select(ChatRoom.chat_model).where(ChatRoom.id == room_id))


async def _ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = (await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))).all()
    return sorted((row.kind, row.amount) for row in rows)


async def _listed(db_client: httpx.AsyncClient) -> tuple[list[str], list[str]]:
    """(모델 목록의 id, 공개 가격의 모델 id) — 둘은 같은 판정이라 함께 본다."""
    chat_models = [m["id"] for m in (await db_client.get("/chat-models")).json()]
    priced = [m["id"] for m in (await db_client.get("/clover/pricing")).json()["models"]]
    return chat_models, priced


async def _start_preview(db_client: httpx.AsyncClient, model: str) -> httpx.Response:
    return await db_client.post("/preview-sessions", json=_preview_character_payload(), params={"model": model})


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


# ---- 목록과 공개 가격 ----


@pytest.mark.parametrize(
    ("switch", "visible", "expected"),
    [
        pytest.param(True, ["opus"], ["gemini", "opus"], id="default-list-hides-sonnet"),
        pytest.param(True, ["opus", "sonnet"], ["gemini", "sonnet", "opus"], id="both-in-registry-order"),
        pytest.param(True, ["sonnet", "opus"], ["gemini", "sonnet", "opus"], id="list-order-does-not-matter"),
        pytest.param(True, ["sonnet"], ["gemini", "sonnet"], id="sonnet-only"),
        pytest.param(True, [], ["gemini"], id="blank-list-is-gemini-only"),
        pytest.param(False, ["opus", "sonnet"], ["gemini"], id="switch-off-hides-every-premium-model"),
    ],
)
async def test_the_model_list_and_the_public_pricing_show_the_visible_models(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    switch: bool,
    visible: list[str],
    expected: list[str],
) -> None:
    """화면 목록과 가격표는 같은 판정이다 — 목록에 없는 모델의 가격이 보이거나, 고를 수 있는 모델의 가격이 빠지면 안 된다.
    순서는 공개 목록이 아니라 레지스트리 순서다."""
    _configure(monkeypatch, switch=switch, visible=visible)
    await _user(db_client, db_session)

    assert await _listed(db_client) == (expected, expected)


async def test_a_visible_sonnet_is_listed_with_its_price_and_beta_mark(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, switch=True, visible=["opus", "sonnet"])
    await _user(db_client, db_session)

    [sonnet] = [m for m in (await db_client.get("/chat-models")).json() if m["id"] == "sonnet"]

    assert sonnet == {"id": "sonnet", "name": "Claude Sonnet 5.5", "isDefault": False, "beta": True, "turnCost": _SONNET}


# ---- 방 모델 지정 ----


async def test_a_hidden_sonnet_leaves_opus_selectable(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """숨김은 모델마다다 — Sonnet 이 거절되는 같은 순간 목록에 있는 Opus 는 고를 수 있다."""
    _configure(monkeypatch, switch=True, visible=["opus"])
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)

    assert (await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "sonnet"})).status_code == 403
    assert (await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "opus"})).status_code == 200
    assert await _stored(db_session, room_id) == "opus"


async def test_a_listed_sonnet_is_refused_while_the_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, switch=False, visible=["opus", "sonnet"])
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)

    for model in ("sonnet", "opus"):
        resp = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": model})
        assert resp.status_code == 403, model
    assert await _stored(db_session, room_id) is None


# ---- 빌더 미리보기 ----


@pytest.mark.parametrize(
    ("switch", "visible"),
    [
        pytest.param(True, ["opus"], id="hidden"),
        pytest.param(False, ["opus", "sonnet"], id="switch-off"),
    ],
)
async def test_a_preview_cannot_start_on_a_sonnet_that_is_not_visible(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    switch: bool,
    visible: list[str],
) -> None:
    _configure(monkeypatch, switch=switch, visible=visible)
    await _user(db_client, db_session)

    resp = await _start_preview(db_client, "sonnet")

    assert resp.status_code == 403
    assert resp.json()["detail"] == {"code": "CHAT_MODEL_NOT_ALLOWED"}


async def test_a_visible_sonnet_preview_charges_the_sonnet_price_and_generates_with_sonnet(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, switch=True, visible=["opus", "sonnet"])
    user = await _user(db_client, db_session)
    started = await _start_preview(db_client, "sonnet")
    assert started.status_code == 201, started.text
    fake = _FakeLLMClient(tokens=["응", "답"])

    resp = await _send(
        db_client, f"/preview-sessions/{started.json()['previewSessionId']}/messages", fake, {"content": "안녕"}
    )

    assert resp.status_code == 200, resp.text
    assert _parse_sse_events(resp.text)[-1]["type"] == "done"
    assert await _ledger(db_session, user.id) == [("chat_spend", -_SONNET)]
    assert _generated_with(fake, "preview_generate") == ["sonnet"]


# ---- 저장된 Sonnet 방의 턴 ----


async def test_a_room_that_stored_a_hidden_sonnet_runs_on_gemini_at_the_gemini_price(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """숨긴 뒤에도 Sonnet 이 저장된 방은 막히지 않는다 — 방 응답도 턴도 Gemini 다. Gemini 턴도 첫 턴부터 깎이므로 차감액이 Gemini 값으로 드러난다."""
    _configure(monkeypatch, switch=True, visible=["opus"])
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)
    await _store_model(db_session, room_id, "sonnet")
    fake = _FakeLLMClient(tokens=["응"])

    room = (await db_client.get(f"/chat-rooms/{room_id}")).json()
    resp = await _send(db_client, f"/chat-rooms/{room_id}/messages", fake, {"content": "안녕"})

    assert (room["chatModel"], room["effectiveChatModel"], room["turnCost"]) == ("sonnet", "gemini", _GEMINI)
    assert resp.status_code == 200
    assert await _ledger(db_session, user.id) == [("chat_spend", -_GEMINI)]
    assert _generated_with(fake) == ["gemini"]


async def test_a_visible_sonnet_room_charges_the_sonnet_price_on_every_turn_kind(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """새 턴·재생성·수정이 모두 Sonnet 값을 내고, 턴 기록에 Sonnet 과 그 값이 남는다."""
    _configure(monkeypatch, switch=True, visible=["opus", "sonnet"])
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)
    assert (await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "sonnet"})).status_code == 200
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
    assert await _ledger(db_session, user.id) == [("chat_spend", -_SONNET)] * 3
    assert _generated_with(fake) == ["sonnet"] * 3
    db_session.expire_all()
    turns = (
        await db_session.execute(
            select(ChatTurn.chat_model, ChatTurn.clover_amount).where(ChatTurn.chat_room_id == room_id)
        )
    ).all()
    assert [tuple(turn) for turn in turns] == [("sonnet", _SONNET)] * 3


async def test_a_failed_sonnet_generation_refunds_the_sonnet_price_without_falling_back_to_another_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """환불은 영수증의 차감액이다 — Gemini 값만 되돌리면 차액이 사라진다. 실패한 생성을 다른 모델로 다시 부르지 않는다."""
    _configure(monkeypatch, switch=True, visible=["opus", "sonnet"])
    user = await _user(db_client, db_session)
    room_id = await _room(db_client, db_session, user)
    await _store_model(db_session, room_id, "sonnet")
    fake = _FakeLLMClient(error=LLMClientError("anthropic down"))

    resp = await _send(db_client, f"/chat-rooms/{room_id}/messages", fake, {"content": "안녕"})

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]
    assert await _ledger(db_session, user.id) == [("chat_refund", _SONNET), ("chat_spend", -_SONNET)]
    await db_session.refresh(user)
    assert user.clover_balance == _START
    assert _generated_with(fake) == ["sonnet"]
