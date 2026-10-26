"""방을 고치는 라우트와 방 삭제의 경합.

이름 바꾸기·대화 초기화·최신 버전 고정·버전 업그레이드 확인·대화 프로필 바꾸기·모델 바꾸기는 모두 주인을 확인한 뒤 방을
고치고 커밋한다. 두 틈이 있다.

- 주인 확인과 쓰기 사이에 다른 요청이 방을 지우고 커밋하면, 쓰기는 0행을 고치거나(ORM 이 그 불일치로 실패) 지워진 방을
  가리키는 오프닝 메시지를 넣다가 FK 위반을 내 500 이 된다. 방이 없으니 404 여야 한다 — 쓰기 전에 방 행을 잠그면 삭제
  커밋을 기다렸다가 방이 없음을 본다.
- 쓰기가 커밋한 바로 다음 방이 지워지면, 커밋 뒤에 방을 다시 읽어 응답을 만드는 라우트는 빈 결과로 500 이 난다. 저장은
  이미 됐으므로 저장한 값으로 200 이어야 한다 — 응답을 커밋 전에 만든다.

경합은 한 커넥션 위에서는 드러나지 않으므로(같은 트랜잭션끼리는 락을 다투지 않는다) 커밋되는 독립 커넥션을 쓰고, 순서는
시간이 아니라 락 대기 상태와 커밋 자리로 강제한다.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.chat.room_deletion import delete_chat_rooms
from api.db.models import (
    Asset,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentVersion,
    User,
    UserPersona,
)
from api.db.session import get_db_session, get_session_factory
from api.main import app
from factories import (
    _committed_engine,
    _get_genre,
    _login_as,
    _make_asset,
    _make_published_character,
    _make_user,
    _wait_until_a_lock_is_awaited,
)

# 여기서 쓴 행은 커밋되므로 픽스처가 이 표지로 골라 지운다.
_MARKER_DOMAIN = "room-deletion-race.test"
_PERSONA_NAME = "고른 프로필"


@pytest_asyncio.fixture
async def committed_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """커밋되는 독립 커넥션용 엔진. 끝나면 이 파일의 표지가 붙은 사용자와 그 행을 지운다."""
    committed = _committed_engine(db_engine)
    yield committed
    factory = async_sessionmaker(committed, expire_on_commit=False)
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(sa.select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            room_ids = (await cleanup.scalars(sa.select(ChatRoom.id).where(ChatRoom.user_id.in_(user_ids)))).all()
            # 초기화가 실패한 경우를 빼면 방은 테스트가 지웠다. 남은 방이 프로필을 FK 로 잡으므로 프로필보다 먼저 지운다.
            await delete_chat_rooms(cleanup, room_ids)
            await cleanup.execute(sa.delete(UserPersona).where(UserPersona.user_id.in_(user_ids)))
            content_ids = (
                await cleanup.scalars(sa.select(Content.id).where(Content.creator_user_id.in_(user_ids)))
            ).all()
            version_ids = (
                await cleanup.scalars(sa.select(ContentVersion.id).where(ContentVersion.content_id.in_(content_ids)))
            ).all()
            await cleanup.execute(
                sa.delete(CharacterVersionDetail).where(CharacterVersionDetail.content_version_id.in_(version_ids))
            )
            await cleanup.execute(
                sa.update(Content).where(Content.id.in_(content_ids)).values(current_published_version_id=None)
            )
            await cleanup.execute(sa.delete(ContentVersion).where(ContentVersion.id.in_(version_ids)))
            await cleanup.execute(sa.delete(Content).where(Content.id.in_(content_ids)))
            await cleanup.execute(sa.delete(Asset).where(Asset.owner_user_id.in_(user_ids)))
            await cleanup.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()
    await committed.dispose()


@dataclass(frozen=True)
class _SeededRoom:
    room_id: uuid.UUID
    user_id: uuid.UUID
    persona_id: uuid.UUID


async def _seed_room(engine: AsyncEngine) -> _SeededRoom:
    """여섯 라우트가 모두 실제로 방 행을 고치게 차려 둔 캐릭터 방을 커밋한다. 값이 그대로면 ORM 이 UPDATE 를 내지 않아
    경합이 생기지 않으므로 각 라우트가 바꿀 칸을 미리 다른 값으로 둔다 — 한 턴을 지나(초기화가 되돌릴 것), 옛 발행 버전에
    고정돼(최신 버전 고정이 옮길 것), 자동 업그레이드 표시가 켜져(확인이 끌 것), 상위 모델을 골라 둔(기본 모델로 되돌릴 것)
    방이다. 대화 프로필은 고르지 않은 채로 두고 고를 프로필 하나를 만든다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    base = datetime.now(UTC) - timedelta(days=1)
    async with factory() as session:
        user = _make_user(email=f"owner-{uuid.uuid4()}@{_MARKER_DOMAIN}")
        session.add(user)
        await session.flush()
        genre = await _get_genre(session)
        content = await _make_published_character(session, creator_user_id=user.id, genre_id=genre.id)
        first_version_id = content.current_published_version_id
        assert first_version_id is not None

        newer = ContentVersion(
            content_id=content.id, version_number=2, published_at=datetime.now(UTC), detail_description="설명"
        )
        session.add(newer)
        await session.flush()
        thumbnail = await _make_asset(session, owner_user_id=user.id)
        session.add(
            CharacterVersionDetail(
                content_version_id=newer.id,
                name="캐릭터",
                one_liner="한줄소개",
                thumbnail_asset_id=thumbnail.id,
                intro="새 인트로",
                example_dialogues=[],
                character_prompt="프롬프트",
            )
        )
        content.current_published_version_id = newer.id

        persona = UserPersona(user_id=user.id, name=_PERSONA_NAME)
        session.add(persona)
        room = ChatRoom(
            user_id=user.id,
            content_id=content.id,
            content_version_id=first_version_id,
            turn_count=1,
            version_auto_upgraded=True,
            chat_model="opus",
        )
        session.add(room)
        await session.flush()
        session.add_all(
            [
                ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content="인트로", created_at=base),
                ChatMessage(
                    chat_room_id=room.id,
                    role=ChatMessageRole.USER,
                    content="[U01]",
                    created_at=base + timedelta(seconds=1),
                ),
                ChatMessage(
                    chat_room_id=room.id,
                    role=ChatMessageRole.ASSISTANT,
                    content="[A01]",
                    created_at=base + timedelta(seconds=2),
                ),
            ]
        )
        await session.commit()
    return _SeededRoom(room_id=room.id, user_id=user.id, persona_id=persona.id)


async def _room_exists(engine: AsyncEngine, room_id: uuid.UUID) -> bool:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return await session.scalar(sa.select(ChatRoom.id).where(ChatRoom.id == room_id)) is not None


# 라우트마다 (메서드, 방 경로 뒤 꼬리, 요청 본문, 저장한 값이 응답에 실렸는지 보는 검사).
_Body = Callable[[_SeededRoom], dict[str, object] | None]
_Check = Callable[[dict[str, Any], _SeededRoom], None]


def _renamed(body: dict[str, Any], _: _SeededRoom) -> None:
    assert body["name"] == "새 이름"


def _reset(body: dict[str, Any], _: _SeededRoom) -> None:
    assert body["turnCount"] == 0
    assert [message["content"] for message in body["messages"]] == ["인트로"]


def _pinned(body: dict[str, Any], _: _SeededRoom) -> None:
    assert body["latestVersionAvailable"] is False


def _acknowledged(body: dict[str, Any], _: _SeededRoom) -> None:
    assert body["versionAutoUpgraded"] is False


def _persona_chosen(body: dict[str, Any], seeded: _SeededRoom) -> None:
    assert (body["personaId"], body["personaName"]) == (str(seeded.persona_id), _PERSONA_NAME)


def _model_reset(body: dict[str, Any], _: _SeededRoom) -> None:
    assert (body["chatModel"], body["effectiveChatModel"]) == (None, "gemini")


_ROOM_WRITES = [
    pytest.param("PATCH", "", lambda _: {"name": "새 이름"}, _renamed, id="rename"),
    pytest.param("POST", "/reset", lambda _: None, _reset, id="reset"),
    pytest.param("POST", "/pin-latest-version", lambda _: None, _pinned, id="pin latest version"),
    pytest.param("POST", "/acknowledge-version-upgrade", lambda _: None, _acknowledged, id="acknowledge upgrade"),
    pytest.param(
        "PUT", "/persona", lambda seeded: {"personaId": str(seeded.persona_id)}, _persona_chosen, id="persona"
    ),
    pytest.param("PUT", "/model", lambda _: {"model": "gemini"}, _model_reset, id="model"),
]


@pytest.mark.parametrize(("method", "suffix", "body", "check"), _ROOM_WRITES)
async def test_a_room_write_that_overlaps_a_room_deletion_is_not_found(
    committed_engine: AsyncEngine,
    db_client: httpx.AsyncClient,
    method: str,
    suffix: str,
    body: _Body,
    check: _Check,
) -> None:
    """다른 세션이 방 삭제를 커밋 직전까지 진행해 둔 채 요청이 들어온다. 삭제가 커밋 전이라 주인 확인은 방을 보고
    지나가고, 요청은 쓰기에서 삭제의 락을 기다린다. 그것을 확인한 뒤 삭제를 커밋시킨다 — 이제 방이 없으므로 404 여야
    한다. 쓰기 전에 방 행을 잠그지 않으면 0행 UPDATE 나 지워진 방에 넣는 오프닝 메시지가 500 을 낸다."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    seeded = await _seed_room(committed_engine)

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    deletion = factory()
    saved = {key: app.dependency_overrides[key] for key in (get_db_session, get_session_factory)}
    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    write: asyncio.Task[httpx.Response] | None = None
    try:
        await _login_as(db_client, seeded.user_id)
        await delete_chat_rooms(deletion, [seeded.room_id])
        write = asyncio.create_task(
            db_client.request(method, f"/chat-rooms/{seeded.room_id}{suffix}", json=body(seeded))
        )
        await _wait_until_a_lock_is_awaited(committed_engine)
        await deletion.commit()
        resp = await asyncio.wait_for(write, 10)
    finally:
        await deletion.close()
        if write is not None and not write.done():
            write.cancel()
        app.dependency_overrides.update(saved)

    assert resp.status_code == 404
    assert not await _room_exists(committed_engine, seeded.room_id)


@pytest.mark.parametrize(("method", "suffix", "body", "check"), _ROOM_WRITES)
async def test_a_room_write_answers_with_what_it_saved_even_if_the_room_is_deleted_right_after(
    committed_engine: AsyncEngine,
    db_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    suffix: str,
    body: _Body,
    check: _Check,
) -> None:
    """쓰기는 성공해 커밋했다. 그 바로 다음 다른 세션이 방을 지우고 커밋해도 응답은 저장한 값이어야 한다 — 커밋 뒤에
    방을 다시 읽어 응답을 만들면 빈 결과로 500 이 나고, 화면은 저장이 실패한 줄 안다. 실제로는 쓰기가 잡은 락을 기다리던
    삭제가 그 커밋과 함께 풀려 이 틈에 들어온다. 시간 대신 요청 세션의 커밋을 감싸 그 순서를 매번 같게 만든다."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    seeded = await _seed_room(committed_engine)

    async def _delete_the_room() -> None:
        async with factory() as session:
            await delete_chat_rooms(session, [seeded.room_id])
            await session.commit()

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            commit = session.commit

            async def _commit_then_delete_the_room() -> None:
                await commit()
                await _delete_the_room()

            monkeypatch.setattr(session, "commit", _commit_then_delete_the_room)
            yield session

    await _login_as(db_client, seeded.user_id)
    saved = {key: app.dependency_overrides[key] for key in (get_db_session, get_session_factory)}
    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        resp = await db_client.request(method, f"/chat-rooms/{seeded.room_id}{suffix}", json=body(seeded))
    finally:
        app.dependency_overrides.update(saved)

    assert resp.status_code == 200
    check(resp.json(), seeded)
    assert not await _room_exists(committed_engine, seeded.room_id)
