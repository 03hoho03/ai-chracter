"""방의 글쓰기 모델 — 지정 라우트, 방 응답의 유효 모델·턴 가격, 모델 목록, `/me` 허용 기능."""

import uuid

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.core.config import settings
from api.db.models.chat import ChatRoom
from api.llm.chat_models import CHAT_MODELS_BY_ID
from factories import (
    _enable_chat_premium,
    _get_genre,
    _grant_feature,
    _login_as,
    _make_published_character,
    _make_user,
)


async def _room_of_new_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, allowed: bool
) -> tuple[uuid.UUID, uuid.UUID]:
    """새 일반 계정(명단·허용 행 없음)의 방. `allowed` 는 채팅 상위 모델 스위치를 켤지다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    if allowed:
        _enable_chat_premium(monkeypatch)
    await _login_as(db_client, user.id)
    resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["id"]), user.id


async def _stored(db_session: AsyncSession, room_id: uuid.UUID) -> str | None:
    return await db_session.scalar(select(ChatRoom.chat_model).where(ChatRoom.id == room_id))


# ---- PUT /chat-rooms/{id}/model ----


async def test_any_account_selects_a_premium_model_while_the_switch_is_on(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """채팅 상위 모델은 스위치 하나로 로그인 회원 전원에게 열린다 — 명단에도 허용 행에도 없는 계정이 고를 수 있다."""
    room_id, _ = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=True)

    resp = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "opus"})

    assert resp.status_code == 200
    assert resp.json() == {
        "chatModel": "opus",
        "effectiveChatModel": "opus",
        "effectiveChatModelName": CHAT_MODELS_BY_ID["opus"].name,
        "turnCost": clover.CHAT_TURN_COST_OPUS,
    }
    assert await _stored(db_session, room_id) == "opus"


@pytest.mark.parametrize("model", [pytest.param("gemini", id="gemini"), pytest.param(None, id="null")])
async def test_anyone_can_go_back_to_gemini_even_with_the_switch_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, model: str | None
) -> None:
    """되돌리기는 허용과 무관하다 — 허용을 거둔 뒤 상위 모델이 저장된 방도 Gemini 로 돌려놓을 수 있어야 한다. 기본 모델은
    빈 값으로 저장한다(새 방과 같은 상태)."""
    room_id, _ = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=False)
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(chat_model="sonnet"))
    await db_session.commit()

    resp = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": model})

    assert resp.status_code == 200
    assert resp.json() == {
        "chatModel": None,
        "effectiveChatModel": "gemini",
        "effectiveChatModelName": "Gemini",
        "turnCost": clover.CHAT_TURN_COST,
    }
    assert await _stored(db_session, room_id) is None


async def test_premium_model_is_refused_with_the_switch_off_even_with_an_old_grant_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치를 끄면 거절이다. 어드민 허용 토글이 있던 시절의 허용 행이 남아 있어도 스위치를 이기지 못한다."""
    room_id, user_id = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=False)
    await _grant_feature(db_session, user_id, "chat_premium_models")
    await db_session.commit()

    resp = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "opus"})

    assert resp.status_code == 403
    assert resp.json()["detail"] == {"code": "CHAT_MODEL_NOT_ALLOWED"}
    assert await _stored(db_session, room_id) is None


async def test_unknown_model_is_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, _ = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=True)

    resp = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "haiku"})

    assert resp.status_code == 422
    assert await _stored(db_session, room_id) is None


async def test_a_registry_model_chat_does_not_offer_is_422_even_with_access(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonnet 은 소설 장 생성에만 남은 모델이다 — 허용이 있는 계정이 채팅방에 지정하려 해도 받지 않고 저장하지 않는다."""
    room_id, _ = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=True)

    resp = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "sonnet"})

    assert resp.status_code == 422
    assert await _stored(db_session, room_id) is None


async def test_cannot_set_the_model_of_someone_elses_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, _ = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=False)
    other = _make_user()
    db_session.add(other)
    await db_session.commit()
    _enable_chat_premium(monkeypatch)
    await _login_as(db_client, other.id)

    resp = await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "opus"})

    assert resp.status_code == 403
    assert await _stored(db_session, room_id) is None


# ---- 방 응답 ----


async def test_room_response_shows_the_stored_and_the_effective_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """방 응답은 실제로 쓰일 모델과 그 가격·이름을 보인다 — 스위치를 끄면 저장된 값은 남고 유효 모델·이름·가격은 Gemini 다."""
    room_id, _ = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=True)
    fresh = (await db_client.get(f"/chat-rooms/{room_id}")).json()
    assert (fresh["chatModel"], fresh["effectiveChatModel"], fresh["turnCost"]) == (
        None,
        "gemini",
        clover.CHAT_TURN_COST,
    )
    assert (await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "opus"})).status_code == 200

    chosen = (await db_client.get(f"/chat-rooms/{room_id}")).json()
    monkeypatch.setattr(settings, "chat_premium_models_enabled", False)
    revoked = (await db_client.get(f"/chat-rooms/{room_id}")).json()

    assert (chosen["chatModel"], chosen["effectiveChatModel"], chosen["turnCost"]) == (
        "opus",
        "opus",
        clover.CHAT_TURN_COST_OPUS,
    )
    assert (
        revoked["chatModel"],
        revoked["effectiveChatModel"],
        revoked["effectiveChatModelName"],
        revoked["turnCost"],
    ) == ("opus", "gemini", "Gemini", clover.CHAT_TURN_COST)


async def test_a_room_storing_sonnet_runs_on_gemini_even_with_access(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """채팅에서 내린 Sonnet 이 저장된 방(내리기 전에 고른 방)은 허용이 있어도 Gemini 와 Gemini 가격으로 보인다 — 화면이
    고를 수 없는 모델로 턴이 돌면 안 된다."""
    room_id, _ = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=True)
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(chat_model="sonnet"))
    await db_session.commit()

    body = (await db_client.get(f"/chat-rooms/{room_id}")).json()

    assert (body["chatModel"], body["effectiveChatModel"], body["effectiveChatModelName"], body["turnCost"]) == (
        "sonnet",
        "gemini",
        "Gemini",
        clover.CHAT_TURN_COST,
    )


async def test_the_effective_model_name_is_the_name_the_model_list_shows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화면은 방의 모델 이름을 목록과 따로 받는다 — 두 곳의 이름이 갈리면 고른 이름과 방에 뜨는 이름이 다르다."""
    room_id, _ = await _room_of_new_user(db_client, db_session, monkeypatch, allowed=True)
    names = {m["id"]: m["name"] for m in (await db_client.get("/chat-models")).json()}
    fresh = (await db_client.get(f"/chat-rooms/{room_id}")).json()

    put = (await db_client.put(f"/chat-rooms/{room_id}/model", json={"model": "opus"})).json()
    chosen = (await db_client.get(f"/chat-rooms/{room_id}")).json()

    assert fresh["effectiveChatModelName"] == names["gemini"]
    assert put["effectiveChatModelName"] == names["opus"]
    assert chosen["effectiveChatModelName"] == names["opus"]


# ---- GET /chat-models ----


async def test_model_list_for_an_account_without_access_is_gemini_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    monkeypatch.setattr(settings, "chat_premium_models_enabled", False)
    await _login_as(db_client, user.id)

    resp = await db_client.get("/chat-models")

    assert resp.status_code == 200
    assert resp.json() == [{"id": "gemini", "name": "Gemini", "beta": False, "turnCost": clover.CHAT_TURN_COST}]


async def test_model_list_with_the_switch_on_has_the_chat_models_with_price_and_beta_mark(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonnet 은 채팅에서 고를 수 없어 스위치가 켜져 있어도 목록에 없다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    _enable_chat_premium(monkeypatch)
    await _login_as(db_client, user.id)

    resp = await db_client.get("/chat-models")

    assert [(m["id"], m["turnCost"], m["beta"]) for m in resp.json()] == [
        ("gemini", clover.CHAT_TURN_COST, False),
        ("opus", clover.CHAT_TURN_COST_OPUS, True),
    ]


async def test_model_list_requires_a_session(db_client: httpx.AsyncClient) -> None:
    assert (await db_client.get("/chat-models")).status_code == 401


# ---- /me ----


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [pytest.param(True, ["chat_premium_models"], id="switch-on"), pytest.param(False, [], id="switch-off")],
)
async def test_me_lists_chat_premium_models_by_the_switch_alone(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    expected: list[str],
) -> None:
    """화면은 이 목록으로 모델 선택을 보이고 숨긴다. 명단에도 허용 행에도 없는 계정이 스위치를 그대로 따른다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    monkeypatch.setattr(settings, "chat_premium_models_enabled", enabled)
    await _login_as(db_client, user.id)

    resp = await db_client.get("/me")

    assert resp.json()["enabledFeatures"] == expected


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        pytest.param(["novelize", "novelize_premium_models"], ["novelize", "novelize_premium_models"], id="novel"),
        pytest.param(["novelize_premium_models"], [], id="novel-premium-without-novelize"),
        pytest.param(
            ["novelize", "chat_premium_models", "novelize_premium_models"],
            ["novelize", "novelize_premium_models"],
            id="all-with-an-old-chat-grant",
        ),
    ],
)
async def test_me_lists_the_novel_features_by_their_grant_rows(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    features: list[str],
    expected: list[str],
) -> None:
    """소설 쪽은 여전히 스위치·명단·허용 행을 모두 본다. 스위치·명단은 모두 열어 두고 허용 행만 바꾼다 — 소설 상위 모델은
    소설화 허용 없이는 목록에 없다. 채팅 스위치는 꺼 둬서, 옛 채팅 허용 행이 채팅 항목을 되살리지 않음을 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    for feature in features:
        await _grant_feature(db_session, user.id, feature)  # type: ignore[arg-type]
    await db_session.commit()
    for switch, allowlist in (
        ("novelize_enabled", "novelize_grant_allowlist"),
        ("novelize_premium_models_enabled", "novelize_premium_model_allowlist"),
    ):
        monkeypatch.setattr(settings, switch, True)
        monkeypatch.setattr(settings, allowlist, [user.id])
    monkeypatch.setattr(settings, "chat_premium_models_enabled", False)
    await _login_as(db_client, user.id)

    resp = await db_client.get("/me")

    assert resp.json()["enabledFeatures"] == expected
