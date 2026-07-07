import uuid
from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    AssetKind,
    CharacterVersionDetail,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
    SituationalImage,
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


def _make_asset(owner: User, **overrides: object) -> Asset:
    defaults: dict[str, object] = {
        "owner_user_id": owner.id,
        "storage_key": f"uploads/{uuid.uuid4()}.png",
        "kind": AssetKind.ORIGINAL,
    }
    defaults.update(overrides)
    return Asset(**defaults)


async def _make_character_draft(db_session: AsyncSession) -> tuple[User, Asset, ContentVersion]:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    thumbnail = _make_asset(user)
    db_session.add(thumbnail)
    await db_session.flush()

    genre_result = await db_session.execute(sa.select(Genre).limit(1))
    genre = genre_result.scalar_one()

    content = Content(
        type=ContentType.CHARACTER,
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

    return user, thumbnail, draft


async def test_character_version_detail_attaches_to_draft(db_session: AsyncSession) -> None:
    _user, thumbnail, draft = await _make_character_draft(db_session)

    detail = CharacterVersionDetail(
        content_version_id=draft.id,
        name="아리아",
        one_liner="한 줄 소개",
        thumbnail_asset_id=thumbnail.id,
        intro="소개글",
        example_dialogues=[{"userLine": "안녕", "characterLine": "반가워"}],
        character_prompt="너는 아리아다.",
    )
    db_session.add(detail)
    await db_session.flush()

    assert detail.playguide is None
    assert detail.example_dialogues == [{"userLine": "안녕", "characterLine": "반가워"}]


async def test_character_version_detail_rejects_unknown_version(db_session: AsyncSession) -> None:
    _user, thumbnail, _draft = await _make_character_draft(db_session)

    detail = CharacterVersionDetail(
        content_version_id=uuid.uuid4(),
        name="아리아",
        one_liner="한 줄 소개",
        thumbnail_asset_id=thumbnail.id,
        intro="소개글",
        example_dialogues=[],
        character_prompt="너는 아리아다.",
    )
    db_session.add(detail)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_situational_image_keeps_entity_id_stable_across_versions(
    db_session: AsyncSession,
) -> None:
    user, thumbnail, draft = await _make_character_draft(db_session)
    blurred = _make_asset(user, kind=AssetKind.BLURRED)
    db_session.add(blurred)
    await db_session.flush()

    entity_id = uuid.uuid4()
    image = SituationalImage(
        entity_id=entity_id,
        content_version_id=draft.id,
        image_asset_id=thumbnail.id,
        blurred_asset_id=blurred.id,
        trigger_condition="사용자가 슬퍼할 때",
        order=1,
    )
    db_session.add(image)
    await db_session.flush()

    assert image.id is not None
    assert image.id != entity_id
    assert image.entity_id == entity_id


async def test_situational_image_rejects_unknown_version(db_session: AsyncSession) -> None:
    user, thumbnail, _draft = await _make_character_draft(db_session)
    blurred = _make_asset(user, kind=AssetKind.BLURRED)
    db_session.add(blurred)
    await db_session.flush()

    image = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=uuid.uuid4(),
        image_asset_id=thumbnail.id,
        blurred_asset_id=blurred.id,
        trigger_condition="사용자가 슬퍼할 때",
        order=1,
    )
    db_session.add(image)

    with pytest.raises(IntegrityError):
        await db_session.flush()
