import uuid
from datetime import date, datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    AssetKind,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
)


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(timezone.utc),
        "privacy_agreed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


async def _make_asset(db_session: AsyncSession, *, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(owner_user_id=owner_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL)
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_published_character(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID, intro: str = "인트로"
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
        content_id=content.id, version_number=1, published_at=datetime.now(timezone.utc), detail_description="설명"
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
        content_id=content.id, version_number=2, published_at=datetime.now(timezone.utc), detail_description="설명 v2"
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
        content_id=content.id, version_number=1, published_at=datetime.now(timezone.utc), detail_description="설명"
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


async def _create_room_via_api(
    client: httpx.AsyncClient, content_id: uuid.UUID, *, content_type: str = "character"
) -> httpx.Response:
    return await client.post("/chat-rooms", json={"contentId": str(content_id), "contentType": content_type})


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
