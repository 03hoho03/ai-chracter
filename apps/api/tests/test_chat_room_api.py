import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

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
    Genre,
    LogicalOp,
    ModerationStatus,
    Shortcut,
    StartingSetup,
    StatDef,
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
    """techspec-content-versioning.md §4 — GET은 순수 조회라 스스로 플래그를 끄면 안 된다."""
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
