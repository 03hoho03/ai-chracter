import uuid
from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    AssetKind,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
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


async def _make_story_draft(db_session: AsyncSession) -> ContentVersion:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    genre_result = await db_session.execute(sa.select(Genre).limit(1))
    genre = genre_result.scalar_one()

    content = Content(
        type=ContentType.STORY,
        creator_user_id=user.id,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    draft = ContentVersion(content_id=content.id, detail_description="초안 설명")
    db_session.add(draft)
    await db_session.flush()

    return draft


async def _make_starting_setup(db_session: AsyncSession, draft: ContentVersion, **overrides: object) -> StartingSetup:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "content_version_id": draft.id,
        "name": "시작 설정 1",
        "prologue": "이야기가 시작된다.",
        "order": 1,
    }
    defaults.update(overrides)
    setup = StartingSetup(**defaults)
    db_session.add(setup)
    await db_session.flush()
    return setup


async def test_story_version_detail_attaches_to_draft(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    draft = await _make_story_draft(db_session)

    thumbnail = Asset(owner_user_id=user.id, storage_key=f"uploads/{uuid.uuid4()}.png", kind=AssetKind.ORIGINAL)
    db_session.add(thumbnail)
    await db_session.flush()

    detail = StoryVersionDetail(
        content_version_id=draft.id,
        name="달빛 아래",
        one_liner="한 줄 소개",
        thumbnail_asset_id=thumbnail.id,
        prompt_template=StoryPromptTemplate.BASIC,
    )
    db_session.add(detail)
    await db_session.flush()

    assert detail.setting_text is None
    assert detail.prompt_template == StoryPromptTemplate.BASIC


async def test_story_version_detail_rejects_unknown_version(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    thumbnail = Asset(owner_user_id=user.id, storage_key=f"uploads/{uuid.uuid4()}.png", kind=AssetKind.ORIGINAL)
    db_session.add(thumbnail)
    await db_session.flush()

    detail = StoryVersionDetail(
        content_version_id=uuid.uuid4(),
        name="달빛 아래",
        one_liner="한 줄 소개",
        thumbnail_asset_id=thumbnail.id,
        prompt_template=StoryPromptTemplate.BASIC,
    )
    db_session.add(detail)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_starting_setup_keeps_entity_id_stable_and_orders_list(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)
    entity_id = uuid.uuid4()

    setup = await _make_starting_setup(db_session, draft, entity_id=entity_id, order=2)

    assert setup.id is not None
    assert setup.id != entity_id
    assert setup.entity_id == entity_id
    assert setup.order == 2


async def test_stat_def_is_independent_per_starting_setup(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)
    setup_a = await _make_starting_setup(db_session, draft, order=1)
    setup_b = await _make_starting_setup(db_session, draft, order=2)

    stat_a = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup_a.id,
        name="호감도",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        description="호감도 스탯",
        order=1,
    )
    stat_b = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup_b.id,
        name="호감도",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        description="호감도 스탯",
        order=1,
    )
    db_session.add_all([stat_a, stat_b])
    await db_session.flush()

    assert stat_a.starting_setup_id == setup_a.id
    assert stat_b.starting_setup_id == setup_b.id
    assert stat_a.id != stat_b.id


async def test_stat_def_rejects_unknown_starting_setup(db_session: AsyncSession) -> None:
    stat = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=uuid.uuid4(),
        name="호감도",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        description="호감도 스탯",
        order=1,
    )
    db_session.add(stat)

    with pytest.raises(IntegrityError):
        await db_session.flush()
