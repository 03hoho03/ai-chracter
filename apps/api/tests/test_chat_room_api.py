import uuid
from datetime import datetime, timedelta, timezone, UTC
from decimal import Decimal

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.chat import router as chat_router
from api.core.s3 import build_thumbnail_key
from api.db.models import (
    AdminActionLog,
    Asset,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    ChatRoomStat,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Ending,
    EndingRule,
    EndingRuleGroup,
    EndingRuleOperator,
    LogicalOp,
    ModerationStatus,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
    UserPersona,
)
from factories import _create_admin, _get_genre, _login_as, _make_asset, _make_user


async def _make_published_character(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    intro: str = "인트로",
    playguide: str | None = None,
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, owner_user_id=creator_user_id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro=intro,
            example_dialogues=[],
            character_prompt="프롬프트",
            playguide=playguide,
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _publish_new_character_version(
    db_session: AsyncSession, content: Content, *, intro: str = "새 인트로"
) -> ContentVersion:
    version = ContentVersion(
        content_id=content.id, version_number=2, published_at=datetime.now(UTC), detail_description="설명 v2"
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, owner_user_id=content.creator_user_id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro=intro,
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return version


async def _make_published_story(db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.STORY,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, owner_user_id=creator_user_id)
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name="스토리",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            prompt_template=StoryPromptTemplate.BASIC,
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _add_starting_setup(
    db_session: AsyncSession,
    content: Content,
    *,
    opening_message: str | None = "다시 만났네요!",
    order: int = 1,
    playguide: str | None = None,
) -> StartingSetup:
    assert content.current_published_version_id is not None
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="첫 만남",
        prologue="옛날 옛적, 낯선 마을에 도착했다.",
        opening_message=opening_message,
        playguide=playguide,
        suggested_replies=["안녕하세요", "여긴 어디죠?"],
        order=order,
    )
    db_session.add(setup)
    await db_session.flush()
    return setup


async def _add_stat_def(db_session: AsyncSession, setup: StartingSetup, *, order: int = 1, **overrides: object) -> StatDef:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "starting_setup_id": setup.id,
        "name": "호감도",
        "icon": "heart",
        "color": "#ff0000",
        "min_value": 0,
        "max_value": 100,
        "initial_value": 50,
        "unit": None,
        "description": "호감도 스탯",
        "order": order,
    }
    defaults.update(overrides)
    stat_def = StatDef(**defaults)
    db_session.add(stat_def)
    await db_session.flush()
    return stat_def


async def _create_room_via_api(
    client: httpx.AsyncClient,
    content_id: uuid.UUID,
    *,
    content_type: str = "character",
    starting_setup_id: uuid.UUID | None = None,
) -> httpx.Response:
    payload: dict[str, object] = {"contentId": str(content_id), "contentType": content_type}
    if starting_setup_id is not None:
        payload["startingSetupId"] = str(starting_setup_id)
    return await client.post("/chat-rooms", json=payload)


async def test_create_chat_room_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await _create_room_via_api(db_client, uuid.uuid4())
    assert resp.status_code == 401


async def test_create_chat_room_unknown_content_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await _create_room_via_api(db_client, uuid.uuid4())
    assert resp.status_code == 404


async def test_create_chat_room_wrong_content_type_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await _create_room_via_api(db_client, story.id)
    assert resp.status_code == 400


async def test_create_chat_room_pins_version_and_includes_opening_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="안녕!")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await _create_room_via_api(db_client, content.id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["contentId"] == str(content.id)
    assert body["contentType"] == "character"
    assert body["turnCount"] == 0
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "assistant"
    assert body["messages"][0]["content"] == "안녕!"

    room = await db_session.get(ChatRoom, uuid.UUID(body["id"]))
    assert room is not None
    assert room.content_version_id == content.current_published_version_id


async def test_get_chat_room_reflects_latest_version_available(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    create_resp = await _create_room_via_api(db_client, content.id)
    room_id = create_resp.json()["id"]

    resp = await db_client.get(f"/chat-rooms/{room_id}")
    assert resp.status_code == 200
    assert resp.json()["latestVersionAvailable"] is False
    assert resp.json()["versionAutoUpgraded"] is False

    await _publish_new_character_version(db_session, content)
    await db_session.commit()

    resp = await db_client.get(f"/chat-rooms/{room_id}")
    assert resp.json()["latestVersionAvailable"] is True


async def test_get_chat_room_unknown_returns_404_and_other_user_returns_403(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=owner.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, owner.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    await _login_as(db_client, other.id)
    resp = await db_client.get(f"/chat-rooms/{room_id}")
    assert resp.status_code == 403

    resp = await db_client.get(f"/chat-rooms/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_list_chat_rooms_returns_auto_and_custom_names_with_last_message_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="첫 인사")
    await db_session.commit()

    await _login_as(db_client, user.id)
    first_room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    second_room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    # Both rooms are created inside this test's single outer transaction, so
    # Postgres' now() (used for the created_at server_default) ties between them —
    # force a real ordering instead of leaving sibling order to a random UUID
    # tiebreak (apps/api/CLAUDE.md's "same-transaction now() ties" gotcha).
    first_room = await db_session.get(ChatRoom, first_room_id)
    assert first_room is not None
    first_room.created_at = first_room.created_at - timedelta(minutes=1)
    await db_session.commit()

    rename_resp = await db_client.patch(f"/chat-rooms/{second_room_id}", json={"name": "나만의 대화방"})
    assert rename_resp.status_code == 200
    assert rename_resp.json()["name"] == "나만의 대화방"

    resp = await db_client.get("/chat-rooms", params={"contentId": str(content.id)})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    by_id = {item["id"]: item for item in items}
    assert by_id[str(first_room_id)]["name"] == "대화 1"
    assert by_id[str(first_room_id)]["lastMessagePreview"] == "첫 인사"
    assert by_id[str(second_room_id)]["name"] == "나만의 대화방"


async def test_list_chat_rooms_with_no_messages_returns_200_with_blank_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """오프닝 메시지까지 지워 메시지가 0개인 방이 있으면 `last_messages[room.id]`가
    KeyError -> 500이었다(delete_message가 오프닝 메시지도 가드 없이 지운다)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    create_resp = await _create_room_via_api(db_client, content.id)
    room_id = create_resp.json()["id"]
    message_id = create_resp.json()["messages"][0]["id"]

    del_resp = await db_client.delete(f"/chat-rooms/{room_id}/messages/{message_id}")
    assert del_resp.status_code == 204

    resp = await db_client.get("/chat-rooms", params={"contentId": str(content.id)})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["lastMessagePreview"] == ""


async def test_list_chat_rooms_response_bytes_pin_each_rooms_latest_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작품별 방 목록이 방마다 고르는 마지막 메시지와 응답 바이트 전체를 고정한다 — 방별 마지막 메시지를 고르는
    쿼리를 바꿔도 화면이 받는 목록은 한 글자도 달라지면 안 된다. 방 넷: 메시지 id 순서가 시각 순서와 거꾸로인 방,
    가장 늦은 시각에 메시지 둘이 겹친 방, 메시지가 없는 방, 마지막 메시지가 미디어 태그뿐이라 미리보기가 빈 방.
    id·시각을 모두 고정해 응답이 실행마다 같다. 시각만으로 정렬하면 겹친 두 행의 순서는 Postgres 정렬에 맡겨지는데,
    이 배치(넣는 순서 포함)에서는 그 정렬도 id 가 큰 쪽을 골랐다(실측) — 그래서 id 로 동률을 가르는 쿼리와 응답이
    같다. 정렬이 다른 쪽을 고르는 배치는 아래 동률 테스트가 따로 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    base = datetime(2026, 1, 1, tzinfo=UTC)

    def room(suffix: str, minutes: int, name: str | None = None) -> ChatRoom:
        return ChatRoom(
            id=uuid.UUID(f"00000000-0000-0000-0000-0000000000{suffix}"),
            user_id=user.id,
            content_id=content.id,
            content_version_id=content.current_published_version_id,
            name=name,
            created_at=base + timedelta(minutes=minutes),
        )

    def message(room_suffix: str, suffix: str, role: ChatMessageRole, text: str, seconds: int) -> ChatMessage:
        return ChatMessage(
            id=uuid.UUID(f"10000000-0000-0000-0000-0000000000{suffix}"),
            chat_room_id=uuid.UUID(f"00000000-0000-0000-0000-0000000000{room_suffix}"),
            role=role,
            content=text,
            created_at=base + timedelta(seconds=seconds),
        )

    db_session.add_all([room("a1", 0), room("a2", 1, name="이름 붙인 방"), room("a3", 2), room("a4", 3)])
    await db_session.flush()
    db_session.add_all(
        [
            # 시각이 늦을수록 id 가 작다 — id 순으로 고르면 첫 메시지가 나온다.
            message("a1", "19", ChatMessageRole.ASSISTANT, "첫 인사", 1),
            message("a1", "18", ChatMessageRole.USER, "두 번째", 2),
            message("a1", "17", ChatMessageRole.ASSISTANT, "{{img::민아/교실}}마지막이야 {{user}}, 나는 {{char}}", 3),
            message("a2", "21", ChatMessageRole.ASSISTANT, "앞선 메시지", 1),
            message("a2", "22", ChatMessageRole.ASSISTANT, "동률 중 id 가 작은 쪽", 5),
            message("a2", "2f", ChatMessageRole.USER, "동률 중 id 가 큰 쪽", 5),
            message("a4", "41", ChatMessageRole.USER, "{{img::7b0e3c1a-0000-0000-0000-000000000000}}", 4),
        ]
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/chat-rooms", params={"contentId": str(content.id)})

    assert resp.status_code == 200
    assert resp.content == (
        '[{"id":"00000000-0000-0000-0000-0000000000a1","name":"대화 1","lastMessagePreview":"마지막이야 당신, 나는 캐릭터","createdAt":"2026-01-01T00:00:00Z"}'
        ',{"id":"00000000-0000-0000-0000-0000000000a2","name":"이름 붙인 방","lastMessagePreview":"동률 중 id 가 큰 쪽","createdAt":"2026-01-01T00:01:00Z"}'
        ',{"id":"00000000-0000-0000-0000-0000000000a3","name":"대화 3","lastMessagePreview":"","createdAt":"2026-01-01T00:02:00Z"}'
        ',{"id":"00000000-0000-0000-0000-0000000000a4","name":"대화 4","lastMessagePreview":"","createdAt":"2026-01-01T00:03:00Z"}]'
    ).encode()


async def test_list_chat_rooms_breaks_a_latest_time_tie_by_the_larger_message_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """마지막 시각이 같은 메시지가 둘이면 id 가 큰 쪽을 미리보기로 쓴다 — 턴 히스토리 정렬 `(created_at, id)` 의
    마지막이자 헤더 "내 채팅목록" 이 고르는 메시지라, 두 목록이 같은 방에 다른 미리보기를 보이지 않는다. 작은 id 를
    먼저 넣는다 — 시각만으로 정렬하던 쿼리는 이 배치에서 작은 쪽을 골랐다(실측)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    chat_room = ChatRoom(
        user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id
    )
    db_session.add(chat_room)
    await db_session.flush()
    tied_at = datetime(2026, 1, 1, tzinfo=UTC)
    for message_id, text in (
        ("20000000-0000-0000-0000-000000000001", "id 가 작은 쪽"),
        ("20000000-0000-0000-0000-0000000000ff", "id 가 큰 쪽"),
    ):
        db_session.add(
            ChatMessage(
                id=uuid.UUID(message_id),
                chat_room_id=chat_room.id,
                role=ChatMessageRole.USER,
                content=text,
                created_at=tied_at,
            )
        )
        await db_session.flush()
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/chat-rooms", params={"contentId": str(content.id)})
    header_resp = await db_client.get("/me/chat-rooms")

    assert resp.status_code == 200
    assert [item["lastMessagePreview"] for item in resp.json()] == ["id 가 큰 쪽"]
    assert [item["lastMessagePreview"] for item in header_resp.json()] == ["id 가 큰 쪽"]


async def test_reset_chat_room_clears_messages_and_turn_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="처음뵙겠습니다")
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    room.turn_count = 5
    room.ending_reached = True
    db_session.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.USER, content="안녕"))
    db_session.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.ASSISTANT, content="반가워"))
    await db_session.commit()

    resp = await db_client.post(f"/chat-rooms/{room_id}/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["turnCount"] == 0
    assert body["endingReached"] is False
    assert len(body["messages"]) == 1
    assert body["messages"][0]["content"] == "처음뵙겠습니다"

    remaining = (
        await db_session.execute(sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id))
    ).scalars().all()
    assert len(remaining) == 1


async def test_delete_chat_room_removes_room_and_messages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    resp = await db_client.delete(f"/chat-rooms/{room_id}")
    assert resp.status_code == 204

    assert await db_session.get(ChatRoom, room_id) is None
    remaining = (
        await db_session.execute(sa.select(ChatMessage).where(ChatMessage.chat_room_id == room_id))
    ).scalars().all()
    assert remaining == []


async def _seed_chat_room_with_children(
    db_session: AsyncSession, *, user_id: uuid.UUID, content_version: ContentVersion
) -> uuid.UUID:
    """메시지 1개·스탯 1개·요약 스냅샷 1개를 가진 방을 심는다. 방 삭제가 자식을 빠짐없이, 그리고
    **그 방 것만** 지우는지 보려면 지워질 방과 남아야 할 방 양쪽에 자식이 있어야 한다."""
    room = ChatRoom(user_id=user_id, content_id=content_version.content_id, content_version_id=content_version.id)
    db_session.add(room)
    await db_session.flush()
    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="안녕")
    db_session.add(message)
    db_session.add(ChatRoomStat(chat_room_id=room.id, stat_entity_id=uuid.uuid4(), current_value=Decimal(1)))
    await db_session.flush()
    db_session.add(
        ChatRoomMemorySnapshot(
            chat_room_id=room.id,
            cursor_created_at=message.created_at,
            cursor_message_id=message.id,
            summary_text="요약",
            source="auto",
        )
    )
    await db_session.flush()
    return room.id


async def _chat_room_row_counts(db_session: AsyncSession, room_id: uuid.UUID) -> tuple[int, int, int, int]:
    """(방, 메시지, 스탯, 요약 스냅샷) 행 수. 컬럼 단위 count라 요청과 같은 세션의 identity map에
    남은 객체에 속지 않는다."""
    counts = []
    for model, column in (
        (ChatRoom, ChatRoom.id),
        (ChatMessage, ChatMessage.chat_room_id),
        (ChatRoomStat, ChatRoomStat.chat_room_id),
        (ChatRoomMemorySnapshot, ChatRoomMemorySnapshot.chat_room_id),
    ):
        counts.append(await db_session.scalar(sa.select(sa.func.count()).select_from(model).where(column == room_id)))
    return (counts[0] or 0, counts[1] or 0, counts[2] or 0, counts[3] or 0)


async def test_delete_chat_room_removes_only_that_rooms_children(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """방 삭제는 그 방의 메시지·스탯·요약 스냅샷·방 행을 모두 지우고, 같은 사용자의 다른 방은 건드리지 않는다.
    탈퇴도 같은 삭제 함수를 쓰므로 그 함수의 방 필터가 넓어지면 두 경로가 함께 여기서 드러난다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    version = await db_session.scalar(
        sa.select(ContentVersion).where(
            ContentVersion.content_id == content.id, ContentVersion.published_at.is_not(None)
        )
    )
    assert version is not None
    target = await _seed_chat_room_with_children(db_session, user_id=user.id, content_version=version)
    sibling = await _seed_chat_room_with_children(db_session, user_id=user.id, content_version=version)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.delete(f"/chat-rooms/{target}")

    assert resp.status_code == 204
    assert await _chat_room_row_counts(db_session, target) == (0, 0, 0, 0)
    assert await _chat_room_row_counts(db_session, sibling) == (1, 1, 1, 1)


async def test_delete_chat_room_viewed_by_admin_keeps_the_view_log_without_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """관리자가 한 번 열람한 방도 소유자가 지울 수 있어야 한다. 열람 로그는 감사 기록이라 남기고,
    사라진 방을 가리키던 칸만 비운다 — 로그가 방 삭제를 막으면 사용자는 500을 받는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    admin_id = uuid.UUID(str((await _create_admin(db_session))["id"]))
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    await record_admin_action(
        db_session,
        admin_id=admin_id,
        action_type="chat-view",
        target_user_id=user.id,
        target_chat_room_id=room_id,
        reason_text="신고 확인",
    )
    await db_session.commit()

    resp = await db_client.delete(f"/chat-rooms/{room_id}")

    assert resp.status_code == 204
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(ChatRoom).where(ChatRoom.id == room_id)) == 0
    logs = (
        await db_session.execute(
            sa.select(AdminActionLog.target_chat_room_id, AdminActionLog.target_user_id).where(
                AdminActionLog.admin_id == admin_id
            )
        )
    ).all()
    assert [tuple(row) for row in logs] == [(None, user.id)]


async def test_pin_latest_version_updates_pinned_version_and_preserves_messages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="처음뵙겠습니다")
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    db_session.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.USER, content="안녕"))
    await db_session.commit()

    new_version = await _publish_new_character_version(db_session, content)
    await db_session.commit()

    resp = await db_client.post(f"/chat-rooms/{room_id}/pin-latest-version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["latestVersionAvailable"] is False
    assert len(body["messages"]) == 2

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.content_version_id == new_version.id


async def test_acknowledge_version_upgrade_resets_flag(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    room.version_auto_upgraded = True
    await db_session.commit()

    resp = await db_client.post(f"/chat-rooms/{room_id}/acknowledge-version-upgrade")
    assert resp.status_code == 200
    assert resp.json()["versionAutoUpgraded"] is False

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.version_auto_upgraded is False


async def test_acknowledge_version_upgrade_get_does_not_reset_flag(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """GET은 순수 조회라 스스로 플래그를 끄면 안 된다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    room.version_auto_upgraded = True
    await db_session.commit()

    resp = await db_client.get(f"/chat-rooms/{room_id}")
    assert resp.status_code == 200
    assert resp.json()["versionAutoUpgraded"] is True

    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    assert room.version_auto_upgraded is True


async def test_rename_reset_delete_require_ownership(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=owner.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, owner.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    await _login_as(db_client, other.id)
    assert (await db_client.patch(f"/chat-rooms/{room_id}", json={"name": "훔친 이름"})).status_code == 403
    assert (await db_client.post(f"/chat-rooms/{room_id}/reset")).status_code == 403
    assert (await db_client.delete(f"/chat-rooms/{room_id}")).status_code == 403
    assert (await db_client.post(f"/chat-rooms/{room_id}/pin-latest-version")).status_code == 403
    assert (await db_client.post(f"/chat-rooms/{room_id}/acknowledge-version-upgrade")).status_code == 403


async def test_create_story_chat_room_requires_starting_setup_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    await _add_starting_setup(db_session, story)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await _create_room_via_api(db_client, story.id, content_type="story")
    assert resp.status_code == 400


async def test_create_story_chat_room_rejects_unknown_starting_setup(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    await _add_starting_setup(db_session, story)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=uuid.uuid4())
    assert resp.status_code == 400


async def test_create_story_chat_room_pins_starting_setup_and_seeds_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, story, opening_message="정신을 차려보니 낯선 방이었다.")
    stat = await _add_stat_def(db_session, setup, initial_value=42)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup.id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["contentType"] == "story"
    assert body["startingSetupId"] == str(setup.entity_id)
    assert len(body["messages"]) == 1
    assert body["messages"][0]["content"] == "정신을 차려보니 낯선 방이었다."
    assert body["stats"] == {str(stat.entity_id): 42.0}

    room_id = uuid.UUID(body["id"])
    stat_rows = (
        await db_session.execute(sa.select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room_id))
    ).scalars().all()
    assert len(stat_rows) == 1
    assert stat_rows[0].stat_entity_id == stat.entity_id
    assert stat_rows[0].current_value == 42


async def test_create_story_chat_room_falls_back_to_prologue_when_no_opening_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, story, opening_message=None)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup.id)
    assert resp.status_code == 201
    assert resp.json()["messages"][0]["content"] == setup.prologue


async def test_get_story_chat_room_embeds_content_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, story)
    stat = await _add_stat_def(db_session, setup)

    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="해피엔딩",
        turn_count_gate=10,
        judgment_prompt="호감도가 충분히 높은가?",
        order=1,
    )
    db_session.add(ending)
    await db_session.flush()

    top_rule = EndingRule(
        entity_id=uuid.uuid4(),
        ending_id=ending.id,
        stat_def_entity_id=stat.entity_id,
        operator=EndingRuleOperator.GTE,
        threshold=80,
        next_op=LogicalOp.AND,
        order=1,
    )
    group = EndingRuleGroup(entity_id=uuid.uuid4(), ending_id=ending.id, order=2)
    db_session.add_all([top_rule, group])
    await db_session.flush()

    nested_rule = EndingRule(
        entity_id=uuid.uuid4(),
        rule_group_id=group.id,
        stat_def_entity_id=stat.entity_id,
        operator=EndingRuleOperator.LT,
        threshold=20,
        order=1,
    )
    db_session.add(nested_rule)

    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=story.current_published_version_id,
        name="자기소개",
        description="자기소개를 유도",
        prompt="당신의 이름과 목적을 소개해주세요.",
    )
    db_session.add(shortcut)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (
        await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup.id)
    ).json()["id"]

    resp = await db_client.get(f"/chat-rooms/{room_id}")
    assert resp.status_code == 200
    snapshot = resp.json()["contentSnapshot"]

    assert snapshot["pinnedStartingSetupId"] == str(setup.id)

    assert snapshot["stats"] == [
        {
            "id": str(stat.entity_id),
            "name": stat.name,
            "icon": stat.icon,
            "color": stat.color,
            "minValue": stat.min_value,
            "maxValue": stat.max_value,
            "initialValue": stat.initial_value,
            "unit": stat.unit,
            "description": stat.description,
        }
    ]
    assert snapshot["shortcuts"] == [
        {"id": str(shortcut.entity_id), "name": "자기소개", "description": "자기소개를 유도", "prompt": shortcut.prompt}
    ]
    assert snapshot["suggestedReplies"] == ["안녕하세요", "여긴 어디죠?"]

    assert len(snapshot["endings"]) == 1
    ending_body = snapshot["endings"][0]
    assert ending_body["id"] == str(ending.entity_id)
    assert ending_body["statRules"] == [
        {
            "kind": "rule",
            "id": str(top_rule.entity_id),
            "statId": str(stat.entity_id),
            "operator": "gte",
            "threshold": 80.0,
            "nextOp": "and",
        },
        {
            "kind": "group",
            "id": str(group.entity_id),
            "nextOp": None,
            "rules": [
                {
                    "kind": "rule",
                    "id": str(nested_rule.entity_id),
                    "statId": str(stat.entity_id),
                    "operator": "lt",
                    "threshold": 20.0,
                    "nextOp": None,
                }
            ],
        },
    ]


async def test_reset_story_chat_room_resets_stats_to_initial_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, story)
    stat = await _add_stat_def(db_session, setup, initial_value=50)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID(
        (
            await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup.id)
        ).json()["id"]
    )

    room_stat = await db_session.get(ChatRoomStat, (room_id, stat.entity_id))
    assert room_stat is not None
    room_stat.current_value = Decimal(5)
    await db_session.commit()

    resp = await db_client.post(f"/chat-rooms/{room_id}/reset")
    assert resp.status_code == 200
    assert resp.json()["stats"] == {str(stat.entity_id): 50.0}


async def test_delete_story_chat_room_removes_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, story)
    await _add_stat_def(db_session, setup)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = uuid.UUID(
        (
            await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup.id)
        ).json()["id"]
    )

    resp = await db_client.delete(f"/chat-rooms/{room_id}")
    assert resp.status_code == 204

    remaining = (
        await db_session.execute(sa.select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room_id))
    ).scalars().all()
    assert remaining == []


async def test_get_play_guide_character_returns_pinned_version_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=genre.id, playguide="이렇게 대화해보세요."
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    resp = await db_client.get(f"/chat-rooms/{room_id}/play-guide")
    assert resp.status_code == 200
    assert resp.json() == {"playGuide": "이렇게 대화해보세요."}


async def test_get_play_guide_character_without_playguide_returns_null(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    resp = await db_client.get(f"/chat-rooms/{room_id}/play-guide")
    assert resp.status_code == 200
    assert resp.json() == {"playGuide": None}


async def test_get_play_guide_story_returns_pinned_starting_setup_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, story, playguide="스탯을 잘 관리하세요.")
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (
        await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup.id)
    ).json()["id"]

    resp = await db_client.get(f"/chat-rooms/{room_id}/play-guide")
    assert resp.status_code == 200
    assert resp.json() == {"playGuide": "스탯을 잘 관리하세요."}


async def test_change_starting_setup_creates_new_room_and_keeps_old_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    first_setup = await _add_starting_setup(db_session, story, opening_message="첫 시작", order=1)
    second_setup = await _add_starting_setup(db_session, story, opening_message="다른 시작", order=2)
    stat = await _add_stat_def(db_session, second_setup, initial_value=30)
    await db_session.commit()

    await _login_as(db_client, user.id)
    old_room_id = uuid.UUID(
        (
            await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=first_setup.id)
        ).json()["id"]
    )
    db_session.add(ChatMessage(chat_room_id=old_room_id, role=ChatMessageRole.USER, content="안녕"))
    await db_session.commit()

    resp = await db_client.post(
        f"/chat-rooms/{old_room_id}/change-starting-setup", json={"startingSetupId": str(second_setup.id)}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] != str(old_room_id)
    assert body["contentId"] == str(story.id)
    assert body["startingSetupId"] == str(second_setup.entity_id)
    assert len(body["messages"]) == 1
    assert body["messages"][0]["content"] == "다른 시작"
    assert body["stats"] == {str(stat.entity_id): 30.0}

    old_room = await db_session.get(ChatRoom, old_room_id)
    assert old_room is not None
    old_messages = (
        await db_session.execute(sa.select(ChatMessage).where(ChatMessage.chat_room_id == old_room_id))
    ).scalars().all()
    assert len(old_messages) == 2


async def test_change_starting_setup_starts_the_new_room_with_no_memory_and_keeps_the_old_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기억은 그 방의 이야기라 새 시작설정과 충돌한다 — 대화 프로필과 달리 새 방에 잇지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    first_setup = await _add_starting_setup(db_session, story, opening_message="첫 시작", order=1)
    second_setup = await _add_starting_setup(db_session, story, opening_message="다른 시작", order=2)
    await db_session.commit()
    await _login_as(db_client, user.id)
    old_room_id = uuid.UUID(
        (
            await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=first_setup.id)
        ).json()["id"]
    )
    opening_key = (
        await db_session.execute(
            sa.select(ChatMessage.created_at, ChatMessage.id).where(ChatMessage.chat_room_id == old_room_id)
        )
    ).one()
    await db_session.execute(
        sa.update(ChatRoom).where(ChatRoom.id == old_room_id).values(memory_note="주인공은 고양이를 무서워한다")
    )
    db_session.add(
        ChatRoomMemorySnapshot(
            chat_room_id=old_room_id,
            cursor_created_at=opening_key.created_at,
            cursor_message_id=opening_key.id,
            summary_text="지금까지의 요약",
            source="auto",
        )
    )
    await db_session.commit()

    resp = await db_client.post(
        f"/chat-rooms/{old_room_id}/change-starting-setup", json={"startingSetupId": str(second_setup.id)}
    )

    assert resp.status_code == 201
    new_room_id = uuid.UUID(resp.json()["id"])
    notes = dict(
        (
            await db_session.execute(
                sa.select(ChatRoom.id, ChatRoom.memory_note).where(ChatRoom.id.in_([old_room_id, new_room_id]))
            )
        ).tuples().all()
    )
    assert notes == {old_room_id: "주인공은 고양이를 무서워한다", new_room_id: ""}
    snapshot_rooms = (
        await db_session.execute(sa.select(ChatRoomMemorySnapshot.chat_room_id))
    ).scalars().all()
    assert snapshot_rooms == [old_room_id]


# ---- 대화 프로필 — 새 방의 `persona_id` (`_create_room`) ----


async def _persona_room_fixture(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[User, Content, StartingSetup, UserPersona, UserPersona]:
    """스토리 1개(시작설정 2개) + 프로필 2개(`default`가 유저의 기본, `other`는 기본 아님)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    await _add_starting_setup(db_session, story, order=1)
    second_setup = await _add_starting_setup(db_session, story, opening_message="다른 시작", order=2)
    default = UserPersona(user_id=user.id, name="기본")
    other = UserPersona(user_id=user.id, name="다른")
    db_session.add_all([default, other])
    await db_session.flush()
    user.default_persona_id = default.id
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user, story, second_setup, default, other


async def _room_persona_id(db_session: AsyncSession, room_id: str) -> uuid.UUID | None:
    return await db_session.scalar(sa.select(ChatRoom.persona_id).where(ChatRoom.id == uuid.UUID(room_id)))


async def _story_room_with_persona(
    db_client: httpx.AsyncClient, db_session: AsyncSession, story: Content, persona_id: uuid.UUID | None
) -> str:
    """방을 API로 만든 뒤 `persona_id`를 원하는 값으로 직접 맞춘다(방 선택 API는 `test_persona_api.py`)."""
    assert story.current_published_version_id is not None
    first_setup_id = await db_session.scalar(
        sa.select(StartingSetup.id).where(
            StartingSetup.content_version_id == story.current_published_version_id, StartingSetup.order == 1
        )
    )
    assert first_setup_id is not None
    room_id: str = (
        await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=first_setup_id)
    ).json()["id"]
    await db_session.execute(
        sa.update(ChatRoom).where(ChatRoom.id == uuid.UUID(room_id)).values(persona_id=persona_id)
    )
    await db_session.commit()
    return room_id


async def test_create_chat_room_starts_with_the_default_persona(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """새 방은 기본 프로필로 시작한다."""
    _, story, _, default, _ = await _persona_room_fixture(db_client, db_session)
    setup_id = await db_session.scalar(
        sa.select(StartingSetup.id).where(
            StartingSetup.content_version_id == story.current_published_version_id, StartingSetup.order == 1
        )
    )
    assert setup_id is not None

    resp = await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup_id)

    assert resp.status_code == 201
    assert resp.json()["personaId"] == str(default.id)
    assert await _room_persona_id(db_session, resp.json()["id"]) == default.id


async def _user_with_character(db_session: AsyncSession) -> tuple[User, Content]:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    return user, content


async def _add_persona(
    db_session: AsyncSession, user: User, name: str, created_at: datetime | None = None
) -> UserPersona:
    persona = UserPersona(user_id=user.id, name=name, **({"created_at": created_at} if created_at else {}))
    db_session.add(persona)
    await db_session.flush()
    return persona


async def _default_persona_id(db_session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    return await db_session.scalar(sa.select(User.default_persona_id).where(User.id == user_id))


async def test_create_chat_room_without_default_promotes_the_oldest_persona_and_uses_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기본이 비어 있는데 프로필이 있으면(예전 계정) 새 방을 만들 때 가장 먼저 만든 것을 기본으로 올리고 그걸로 시작한다.
    삽입 순서를 생성 시각 순서와 어긋나게 둬 "삽입 순"과 갈린다."""
    user, content = await _user_with_character(db_session)
    now = datetime.now(UTC)
    await _add_persona(db_session, user, "나중", now - timedelta(minutes=1))
    oldest = await _add_persona(db_session, user, "먼저", now - timedelta(minutes=3))
    await _add_persona(db_session, user, "중간", now - timedelta(minutes=2))
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await _create_room_via_api(db_client, content.id)

    assert resp.status_code == 201
    assert resp.json()["personaId"] == str(oldest.id)
    assert await _room_persona_id(db_session, resp.json()["id"]) == oldest.id
    assert await _default_persona_id(db_session, user.id) == oldest.id


async def test_create_chat_room_promotion_breaks_created_at_tie_by_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content = await _user_with_character(db_session)
    same_time = datetime.now(UTC) - timedelta(minutes=1)
    tied = [await _add_persona(db_session, user, f"동률{index}", same_time) for index in range(3)]
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await _create_room_via_api(db_client, content.id)

    assert resp.status_code == 201
    expected = min(persona.id for persona in tied)
    assert resp.json()["personaId"] == str(expected)
    assert await _default_persona_id(db_session, user.id) == expected


async def test_create_chat_room_with_persona_id_uses_it_and_still_promotes_a_default(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """시작 화면에서 고른 프로필로 방을 연다. 기본이 비어 있었으면 기본은 따로 가장 오래된 것으로 채운다 — 고른 것을
    기본으로 삼지 않는다."""
    user, content = await _user_with_character(db_session)
    now = datetime.now(UTC)
    oldest = await _add_persona(db_session, user, "먼저", now - timedelta(minutes=2))
    chosen = await _add_persona(db_session, user, "고른 것", now - timedelta(minutes=1))
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "character", "personaId": str(chosen.id)}
    )

    assert resp.status_code == 201
    assert resp.json()["personaId"] == str(chosen.id)
    assert await _room_persona_id(db_session, resp.json()["id"]) == chosen.id
    assert await _default_persona_id(db_session, user.id) == oldest.id


async def test_create_chat_room_with_persona_id_keeps_the_existing_default(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, story, _, default, other = await _persona_room_fixture(db_client, db_session)
    setup_id = await db_session.scalar(
        sa.select(StartingSetup.id).where(
            StartingSetup.content_version_id == story.current_published_version_id, StartingSetup.order == 1
        )
    )

    resp = await db_client.post(
        "/chat-rooms",
        json={
            "contentId": str(story.id),
            "contentType": "story",
            "startingSetupId": str(setup_id),
            "personaId": str(other.id),
        },
    )

    assert resp.status_code == 201
    assert resp.json()["personaId"] == str(other.id)
    assert await _default_persona_id(db_session, default.user_id) == default.id


async def test_create_chat_room_without_any_persona_has_no_persona(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필이 없는 사용자의 방은 "선택 없음"으로 연다 — 이름을 먼저 받는 건 화면 몫이고, 그걸 모르는 예전 화면도 방을
    열 수 있어야 한다."""
    user, content = await _user_with_character(db_session)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await _create_room_via_api(db_client, content.id)

    assert resp.status_code == 201
    assert resp.json()["personaId"] is None
    assert await _default_persona_id(db_session, user.id) is None


async def test_create_chat_room_with_others_or_unknown_persona_id_is_rejected_without_a_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 남의 프로필 id를 내 방에 실을 수 없다 — 방 선택(`PUT /chat-rooms/{id}/persona`)과 같은 응답이다."""
    user, content = await _user_with_character(db_session)
    own = await _add_persona(db_session, user, "내 것")
    user.default_persona_id = own.id
    stranger = _make_user()
    db_session.add(stranger)
    await db_session.flush()
    others = await _add_persona(db_session, stranger, "남의 것")
    await db_session.commit()
    await _login_as(db_client, user.id)
    body = {"contentId": str(content.id), "contentType": "character"}

    forbidden = await db_client.post("/chat-rooms", json={**body, "personaId": str(others.id)})
    missing = await db_client.post("/chat-rooms", json={**body, "personaId": str(uuid.uuid4())})

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Not the persona owner"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Persona not found"
    rooms = await db_session.scalar(sa.select(sa.func.count()).select_from(ChatRoom).where(ChatRoom.user_id == user.id))
    assert rooms == 0


async def test_change_starting_setup_inherits_the_original_rooms_non_default_persona(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기본이 아니라 원래 방의 선택을 잇는다 — 기본과 **다른** 프로필이라야 "기본을
    넣었다"와 구별된다."""
    _, story, second_setup, _, other = await _persona_room_fixture(db_client, db_session)
    room_id = await _story_room_with_persona(db_client, db_session, story, other.id)

    resp = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(second_setup.id)}
    )

    assert resp.status_code == 201
    assert resp.json()["personaId"] == str(other.id)
    assert await _room_persona_id(db_session, resp.json()["id"]) == other.id


async def test_change_starting_setup_inherits_no_persona_even_when_a_default_exists(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원래 방이 "선택 없음"이면 기본이 있어도 새 방도 "선택 없음"이다."""
    _, story, second_setup, _, _ = await _persona_room_fixture(db_client, db_session)
    room_id = await _story_room_with_persona(db_client, db_session, story, None)

    resp = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(second_setup.id)}
    )

    assert resp.status_code == 201
    assert resp.json()["personaId"] is None
    assert await _room_persona_id(db_session, resp.json()["id"]) is None


async def test_change_starting_setup_after_the_original_persona_was_deleted_has_no_persona(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원래 방의 프로필을 지우면 그 방은 NULL이 되고, 거기서
    시작설정을 바꾼 새 방도 NULL이다(지워진 id를 싣다 FK 위반 500이 나지 않는다)."""
    _, story, second_setup, _, other = await _persona_room_fixture(db_client, db_session)
    room_id = await _story_room_with_persona(db_client, db_session, story, other.id)
    assert (await db_client.delete(f"/me/personas/{other.id}")).status_code == 204

    resp = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(second_setup.id)}
    )

    assert resp.status_code == 201
    assert resp.json()["personaId"] is None


async def test_change_starting_setup_does_not_promote_a_default(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """시작설정 변경은 원래 방의 선택을 잇기만 한다 — 기본이 비어 있어도 여기서는 채우지 않고 새 방도 "선택 없음"이다."""
    user, story, second_setup, _, _ = await _persona_room_fixture(db_client, db_session)
    room_id = await _story_room_with_persona(db_client, db_session, story, None)
    await db_session.execute(sa.update(User).where(User.id == user.id).values(default_persona_id=None))
    await db_session.commit()

    resp = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(second_setup.id)}
    )

    assert resp.status_code == 201
    assert resp.json()["personaId"] is None
    assert await _default_persona_id(db_session, user.id) is None


async def test_change_starting_setup_rejects_character_chat_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    resp = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(uuid.uuid4())}
    )
    assert resp.status_code == 400


async def test_change_starting_setup_rejects_unknown_starting_setup(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, story)
    await db_session.commit()

    await _login_as(db_client, user.id)
    room_id = (
        await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup.id)
    ).json()["id"]

    resp = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(uuid.uuid4())}
    )
    assert resp.status_code == 400


async def test_change_starting_setup_requires_ownership(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=owner.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, story)
    await db_session.commit()

    await _login_as(db_client, owner.id)
    room_id = (
        await _create_room_via_api(db_client, story.id, content_type="story", starting_setup_id=setup.id)
    ).json()["id"]

    await _login_as(db_client, other.id)
    resp = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 403


async def test_get_play_guide_requires_ownership(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=owner.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, owner.id)
    room_id = (await _create_room_via_api(db_client, content.id)).json()["id"]

    await _login_as(db_client, other.id)
    resp = await db_client.get(f"/chat-rooms/{room_id}/play-guide")
    assert resp.status_code == 403

    resp = await db_client.get(f"/chat-rooms/{uuid.uuid4()}/play-guide")
    assert resp.status_code == 404


async def test_my_chat_rooms_excludes_other_users_and_orders_by_last_message_recency(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    content_a = await _make_published_character(db_session, creator_user_id=owner.id, genre_id=genre.id)
    content_b = await _make_published_character(db_session, creator_user_id=owner.id, genre_id=genre.id)
    other_content = await _make_published_character(db_session, creator_user_id=other.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, owner.id)
    room_a_id = uuid.UUID((await _create_room_via_api(db_client, content_a.id)).json()["id"])
    room_b_id = uuid.UUID((await _create_room_via_api(db_client, content_b.id)).json()["id"])

    await _login_as(db_client, other.id)
    await _create_room_via_api(db_client, other_content.id)

    room_a = await db_session.get(ChatRoom, room_a_id)
    assert room_a is not None
    t0 = room_a.created_at
    # room_a를 room_b보다 "나중에 생성된 것"처럼 만들되(생성순으로는 room_a가 위) 마지막
    # 메시지는 room_b가 더 최근이게 한다 — 정렬이 생성순이 아니라 마지막 메시지 기준임을
    # 실제로 가른다(양쪽에서 같은 순서가 나오는 데이터로는 아무것도 증명하지 못한다).
    room_a.created_at = t0 + timedelta(minutes=10)
    db_session.add(
        ChatMessage(
            chat_room_id=room_b_id,
            role=ChatMessageRole.USER,
            content="room B 최신 답장",
            created_at=t0 + timedelta(minutes=5),
        )
    )
    await db_session.commit()

    await _login_as(db_client, owner.id)
    resp = await db_client.get("/me/chat-rooms")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    ids = [item["id"] for item in items]
    assert ids == [str(room_b_id), str(room_a_id)]
    assert items[0]["lastMessagePreview"] == "room B 최신 답장"


async def test_my_chat_rooms_includes_empty_room_with_blank_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id, intro="안녕!")
    await db_session.commit()

    await _login_as(db_client, user.id)
    create_resp = await _create_room_via_api(db_client, content.id)
    room_id = create_resp.json()["id"]
    message_id = create_resp.json()["messages"][0]["id"]

    # 오프닝 메시지를 지워 메시지 0개인 방을 만든다 — delete_message는 오프닝 메시지도
    # 가드 없이 지운다.
    del_resp = await db_client.delete(f"/chat-rooms/{room_id}/messages/{message_id}")
    assert del_resp.status_code == 204

    resp = await db_client.get("/me/chat-rooms")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == room_id
    assert items[0]["lastMessagePreview"] == ""
    assert items[0]["lastMessageAt"] is None


async def test_my_chat_rooms_name_ordinal_matches_content_scoped_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    first_room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])
    second_room_id = uuid.UUID((await _create_room_via_api(db_client, content.id)).json()["id"])

    first_room = await db_session.get(ChatRoom, first_room_id)
    assert first_room is not None
    first_room.created_at = first_room.created_at - timedelta(minutes=1)
    await db_session.commit()

    scoped_resp = await db_client.get("/chat-rooms", params={"contentId": str(content.id)})
    my_resp = await db_client.get("/me/chat-rooms")
    assert scoped_resp.status_code == 200
    assert my_resp.status_code == 200

    scoped_by_id = {item["id"]: item for item in scoped_resp.json()}
    my_by_id = {item["id"]: item for item in my_resp.json()}
    assert scoped_by_id[str(first_room_id)]["name"] == my_by_id[str(first_room_id)]["name"] == "대화 1"
    assert scoped_by_id[str(second_room_id)]["name"] == my_by_id[str(second_room_id)]["name"] == "대화 2"


async def test_my_chat_rooms_mixed_content_types_thumbnail_and_moderation(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    character = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    deleted_character = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)

    # 썸네일 없는 스토리 콘텐츠 — _make_published_story는 항상 썸네일을 채우므로 직접 구성한다.
    story = Content(
        creator_user_id=user.id,
        type=ContentType.STORY,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(story)
    await db_session.flush()
    story_version = ContentVersion(
        content_id=story.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db_session.add(story_version)
    await db_session.flush()
    db_session.add(
        StoryVersionDetail(
            content_version_id=story_version.id,
            name="썸네일 없는 스토리",
            one_liner="한줄소개",
            thumbnail_asset_id=None,
            prompt_template=StoryPromptTemplate.BASIC,
        )
    )
    await db_session.flush()
    story.current_published_version_id = story_version.id
    await db_session.flush()
    setup = await _add_starting_setup(db_session, story)
    await db_session.commit()

    await _login_as(db_client, user.id)
    character_room_id = uuid.UUID((await _create_room_via_api(db_client, character.id)).json()["id"])
    story_room_id = uuid.UUID(
        (
            await _create_room_via_api(
                db_client, story.id, content_type="story", starting_setup_id=setup.id
            )
        ).json()["id"]
    )
    deleted_room_id = uuid.UUID(
        (await _create_room_via_api(db_client, deleted_character.id)).json()["id"]
    )

    # 발행 이후 이용제한/삭제로 바뀌어도 대화방 상세는 그대로 보이므로(채팅 라우터는
    # moderation_status를 보지 않는다) 목록에서도 감추지 않는다.
    story.moderation_status = ModerationStatus.RESTRICTED
    deleted_character.moderation_status = ModerationStatus.DELETED
    await db_session.commit()

    resp = await db_client.get("/me/chat-rooms")
    assert resp.status_code == 200
    items = {item["id"]: item for item in resp.json()}
    assert len(items) == 3

    character_item = items[str(character_room_id)]
    assert character_item["contentType"] == "character"
    assert character_item["contentName"] == "캐릭터"
    assert character_item["thumbnailUrl"] is not None
    assert "_thumb.webp" in character_item["thumbnailUrl"]

    story_item = items[str(story_room_id)]
    assert story_item["contentType"] == "story"
    assert story_item["contentName"] == "썸네일 없는 스토리"
    assert story_item["thumbnailUrl"] is None

    deleted_item = items[str(deleted_room_id)]
    assert deleted_item["contentType"] == "character"
    assert deleted_item["contentName"] == "캐릭터"
    assert deleted_item["thumbnailUrl"] is not None


async def _seed_my_rooms_with_a_skipped_room(
    db_session: AsyncSession,
) -> tuple[User, dict[str, uuid.UUID], str, str]:
    """"내 채팅목록" 의 자르기·순번·서명을 한 번에 가르는 방 배치를 직접 삽입한다(시각을 고정해야 활동순을 정할 수 있다).

    작품 C(썸네일) 에 방 c1·x·c2·c3(생성순), 작품 D(썸네일, C 와 다른 파일) 에 d1, 썸네일 없는 스토리 S 에 메시지 없는
    s1, 다른 사용자의 방 하나. x 는 버전 상세가 없는 C 의 두 번째 버전에 고정돼 목록에서 빠지지만 C 의 생성순 번호 하나를
    먹고(그래서 c2 가 "대화 3", c3 가 "대화 4"), 활동은 전체에서 가장 최근이라 빠지기 전에 자르면 맨 앞 칸을 차지한다.
    활동순은 x > c3 > d1 > c1 > c2 > s1 이다. 돌려주는 것은 (로그인할 사용자, 이름별 방 id, C 썸네일 키, D 썸네일 키).
    """
    user = _make_user()
    other = _make_user()
    db_session.add_all([user, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    content_c = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    content_d = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    other_content = await _make_published_character(db_session, creator_user_id=other.id, genre_id=genre.id)
    assert content_c.current_published_version_id is not None
    assert content_d.current_published_version_id is not None
    assert story.current_published_version_id is not None
    assert other_content.current_published_version_id is not None
    await db_session.execute(
        sa.update(StoryVersionDetail)
        .where(StoryVersionDetail.content_version_id == story.current_published_version_id)
        .values(thumbnail_asset_id=None)
    )
    detail_less_version = ContentVersion(
        content_id=content_c.id, version_number=2, published_at=datetime.now(UTC), detail_description="상세 없음"
    )
    db_session.add(detail_less_version)
    await db_session.flush()

    base = datetime(2026, 1, 1, tzinfo=UTC)
    # 이름 -> (사용자, 작품, 고정 버전, 생성 시각(분), 마지막 메시지 시각(분) 또는 None)
    layout: dict[str, tuple[User, Content, uuid.UUID, int, int | None]] = {
        "s1": (user, story, story.current_published_version_id, 0, None),
        "c1": (user, content_c, content_c.current_published_version_id, 1, 30),
        "x": (user, content_c, detail_less_version.id, 2, 60),
        "c2": (user, content_c, content_c.current_published_version_id, 3, 20),
        "c3": (user, content_c, content_c.current_published_version_id, 4, 50),
        "d1": (user, content_d, content_d.current_published_version_id, 5, 40),
        "other": (other, other_content, other_content.current_published_version_id, 6, 70),
    }
    room_ids: dict[str, uuid.UUID] = {}
    for label, (owner, content, version_id, created_minute, message_minute) in layout.items():
        room = ChatRoom(
            user_id=owner.id,
            content_id=content.id,
            content_version_id=version_id,
            created_at=base + timedelta(minutes=created_minute),
        )
        db_session.add(room)
        await db_session.flush()
        room_ids[label] = room.id
        if message_minute is not None:
            db_session.add(
                ChatMessage(
                    chat_room_id=room.id,
                    role=ChatMessageRole.USER,
                    content=f"{label} 마지막 말",
                    created_at=base + timedelta(minutes=message_minute),
                )
            )
    await db_session.flush()

    thumbnail_keys: list[str] = []
    for content in (content_c, content_d):
        storage_key = await db_session.scalar(
            sa.select(Asset.storage_key)
            .join(CharacterVersionDetail, CharacterVersionDetail.thumbnail_asset_id == Asset.id)
            .where(CharacterVersionDetail.content_version_id == content.current_published_version_id)
        )
        assert storage_key is not None
        thumbnail_keys.append(build_thumbnail_key(storage_key))
    await db_session.commit()
    return user, room_ids, thumbnail_keys[0], thumbnail_keys[1]


def _record_presigned_keys(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """라우터의 서명 함수를 키를 기록하고 `signed/<키>` 를 돌려주는 가짜로 바꾼다 — 응답 URL 이 결정적이 되고,
    어떤 방의 썸네일을 서명했는지 셀 수 있다(서명은 네트워크 없는 로컬 계산이라 moto 쪽에서는 보이지 않는다)."""
    signed_keys: list[str] = []

    def _fake_presign(key: str) -> str:
        signed_keys.append(key)
        return f"signed/{key}"

    monkeypatch.setattr(chat_router, "generate_presigned_get_url", _fake_presign)
    return signed_keys


async def test_my_chat_rooms_without_limit_drops_detail_less_rooms_but_counts_them_in_names(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`limit` 을 주지 않은 응답은 지금까지와 같아야 한다 — 옛 화면은 계속 생략해서 부른다. 순서·이름·썸네일·미리보기·
    시각을 전부 값으로 고정해, 서명 위치를 옮기는 리팩터가 이 중 하나라도 바꾸면 깨진다. 버전 상세가 없는 방은 목록에서
    빠지되 같은 작품의 "대화 N" 번호는 하나 먹는다(방 안에서 보이는 번호와 맞추려고)."""
    user, rooms, c_key, d_key = await _seed_my_rooms_with_a_skipped_room(db_session)
    _record_presigned_keys(monkeypatch)

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/chat-rooms")

    assert resp.status_code == 200
    base = datetime(2026, 1, 1, tzinfo=UTC)
    expected = [
        ("c3", "대화 4", "character", "캐릭터", f"signed/{c_key}", "c3 마지막 말", 50, 4),
        ("d1", "대화 1", "character", "캐릭터", f"signed/{d_key}", "d1 마지막 말", 40, 5),
        ("c1", "대화 1", "character", "캐릭터", f"signed/{c_key}", "c1 마지막 말", 30, 1),
        ("c2", "대화 3", "character", "캐릭터", f"signed/{c_key}", "c2 마지막 말", 20, 3),
        ("s1", "대화 1", "story", "스토리", None, "", None, 0),
    ]
    items = resp.json()
    assert [item["id"] for item in items] == [str(rooms[label]) for label, *_ in expected]
    for item, (label, name, content_type, content_name, thumbnail_url, preview, message_minute, created_minute) in zip(
        items, expected, strict=True
    ):
        room = await db_session.get(ChatRoom, rooms[label])
        assert room is not None
        assert item["name"] == name, label
        assert item["contentId"] == str(room.content_id), label
        assert item["contentType"] == content_type, label
        assert item["contentName"] == content_name, label
        assert item["thumbnailUrl"] == thumbnail_url, label
        assert item["lastMessagePreview"] == preview, label
        expected_message_at = None if message_minute is None else base + timedelta(minutes=message_minute)
        last_message_at = item["lastMessageAt"]
        assert (None if last_message_at is None else datetime.fromisoformat(last_message_at)) == expected_message_at, label
        assert datetime.fromisoformat(item["createdAt"]) == base + timedelta(minutes=created_minute), label


async def test_my_chat_rooms_limit_keeps_names_numbered_across_all_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """잘린 목록으로 "대화 N" 을 세면 최근 목록의 이름이 `/chats` 전체 목록·방 안 이름과 달라진다(c3 가 "대화 4" 가
    아니라 "대화 1" 로). 방 수보다 큰 `limit` 은 생략과 같은 전체를 준다."""
    user, rooms, _c_key, _d_key = await _seed_my_rooms_with_a_skipped_room(db_session)
    _record_presigned_keys(monkeypatch)

    await _login_as(db_client, user.id)
    full = (await db_client.get("/me/chat-rooms")).json()
    resp = await db_client.get("/me/chat-rooms", params={"limit": 1})
    large_resp = await db_client.get("/me/chat-rooms", params={"limit": 50})

    assert resp.status_code == 200
    assert [(item["id"], item["name"]) for item in resp.json()] == [(str(rooms["c3"]), "대화 4")]
    assert resp.json() == full[:1]
    assert large_resp.json() == full


async def test_my_chat_rooms_limit_fills_up_after_skipping_detail_less_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """목록에서 빠지는 방을 걸러내기 전에 자르면 그 방이 `limit` 칸 하나를 먹어 요청한 개수가 안 찬다(가장 최근 활동이
    빠지는 방 x 라 `limit=2` 가 c3 하나만 준다)."""
    user, rooms, _c_key, _d_key = await _seed_my_rooms_with_a_skipped_room(db_session)
    _record_presigned_keys(monkeypatch)

    await _login_as(db_client, user.id)
    full = (await db_client.get("/me/chat-rooms")).json()
    resp = await db_client.get("/me/chat-rooms", params={"limit": 2})

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [str(rooms["c3"]), str(rooms["d1"])]
    assert resp.json() == full[:2]


async def test_my_chat_rooms_limit_signs_only_returned_thumbnails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """자르기 전에 서명하면 `limit` 을 줘도 사용자의 방 전부를 서명한다 — 최근 목록은 여러 화면에서 불리므로 그 비용을
    없애는 것이 `limit` 의 목적이다. c1·c2·c3 는 같은 작품이라 키가 같아서, 잘려 나간 방 중 키가 다른 d1 로만 갈린다."""
    user, _rooms, c_key, d_key = await _seed_my_rooms_with_a_skipped_room(db_session)
    signed_keys = _record_presigned_keys(monkeypatch)

    await _login_as(db_client, user.id)
    await db_client.get("/me/chat-rooms")
    assert set(signed_keys) == {c_key, d_key}  # 가짜 서명이 실제로 호출 경로에 걸려 있다는 대조군

    signed_keys.clear()
    resp = await db_client.get("/me/chat-rooms", params={"limit": 1})

    assert resp.status_code == 200
    assert set(signed_keys) == {c_key}


async def test_my_chat_rooms_rejects_limit_below_one(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """하한이 없으면 파이썬 슬라이스가 `limit=0` 에 빈 목록, `limit=-1` 에 마지막 방만 빠진 목록을 200 으로 조용히
    돌려준다 — 틀린 화면이 오류 없이 그려지므로 요청 단계에서 422 로 막는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    db_session.add(
        ChatRoom(user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id)
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/chat-rooms", params={"limit": 0})

    assert resp.status_code == 422
    assert [error["loc"] for error in resp.json()["detail"]] == [["query", "limit"]]
