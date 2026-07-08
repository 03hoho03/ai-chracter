import uuid
from datetime import date, datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    AssetKind,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Ending,
    Genre,
    ModerationStatus,
    StartingSetup,
    StoryEndingUnlock,
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
            setting_text="세계관 설정",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _add_starting_setup(db_session: AsyncSession, content: Content, **overrides: object) -> StartingSetup:
    assert content.current_published_version_id is not None
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "content_version_id": content.current_published_version_id,
        "name": "첫 만남",
        "prologue": "옛날 옛적, 낯선 마을에 도착했다.",
        "order": 1,
    }
    defaults.update(overrides)
    setup = StartingSetup(**defaults)
    db_session.add(setup)
    await db_session.flush()
    return setup


async def _add_ending(db_session: AsyncSession, setup: StartingSetup, **overrides: object) -> Ending:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "starting_setup_id": setup.id,
        "name": "엔딩",
        "turn_count_gate": 1,
        "judgment_prompt": "주인공이 마을을 완전히 떠났는가?",
        "epilogue": "이야기는 여기서 끝난다.",
        "hint": "마을을 떠나 보세요.",
        "order": 1,
    }
    defaults.update(overrides)
    ending = Ending(**defaults)
    db_session.add(ending)
    await db_session.flush()
    return ending


async def test_ending_collection_marks_reached_ending_with_epilogue_and_hides_hint(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    reached = await _add_ending(db_session, setup, order=1)
    unreached = await _add_ending(db_session, setup, order=2, name="다른 엔딩", hint="힌트만 노출")
    db_session.add(
        StoryEndingUnlock(
            user_id=user.id, starting_setup_entity_id=setup.entity_id, ending_entity_id=reached.entity_id
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")

    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == [str(reached.entity_id), str(unreached.entity_id)]

    reached_item, unreached_item = body
    assert reached_item["reached"] is True
    assert reached_item["epilogue"] == "이야기는 여기서 끝난다."
    assert reached_item["hint"] is None

    assert unreached_item["reached"] is False
    assert unreached_item["epilogue"] is None
    assert unreached_item["hint"] == "힌트만 노출"


async def test_ending_collection_reuses_unlock_across_new_chat_rooms_for_same_starting_setup(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """엔딩 도달 기록은 특정 대화방이 아니라 (user, starting_setup_entity_id, ending_entity_id)
    단위로 누적되므로, 같은 시작설정으로 새 대화방을 만들어도 유지되어야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    ending = await _add_ending(db_session, setup)
    db_session.add(
        StoryEndingUnlock(
            user_id=user.id, starting_setup_entity_id=setup.entity_id, ending_entity_id=ending.entity_id
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 201

    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")
    assert resp.status_code == 200
    assert resp.json()[0]["reached"] is True


async def test_ending_collection_requires_login(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await db_session.commit()

    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")
    assert resp.status_code == 401


async def test_ending_collection_unknown_starting_setup_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/stories/starting-setups/{uuid.uuid4()}/ending-collection")
    assert resp.status_code == 404


async def test_ending_collection_returns_empty_list_when_no_endings_registered(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")
    assert resp.status_code == 200
    assert resp.json() == []
