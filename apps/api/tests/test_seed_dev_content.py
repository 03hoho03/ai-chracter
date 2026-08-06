"""`scripts/seed_dev.py` 가 `seed_content/data/` 전체를 발행 상태로 밀어 넣는 배선 (US-010).

개별 업서트 동작은 `test_seed_upsert.py` / `test_seed_character_upsert.py` 가 인위적인
payload 로 이미 검사한다. 여기서는 **커밋된 데이터 파일 전부**가 실제 시드 경로(썸네일 자산
주입 -> upsert -> 발행)를 그대로 통과하는지, 그리고 재실행이 행을 늘리지 않는지를 본다.
"""

import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import seed_dev
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import Content, ContentType, ContentVersion, ContentVisibility
from api.db.models.media import Asset
from api.db.models.story import StoryVersionDetail
from seed_content import images
from seed_content.ids import SEED_AUTHOR_USER_ID
from seed_content.loader import load_characters, load_stories
from seed_content.upsert import (
    character_content_id,
    character_version_id,
    story_content_id,
    story_version_id,
)


@pytest.fixture(autouse=True)
def _no_image_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """이미지 디렉터리는 gitignore 라 CI 에는 없다 — 목업 폴백 경로로 고정해 테스트한다."""
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "images")


async def _seed_author(db_session: AsyncSession) -> None:
    """`contents.creator_user_id` / `assets.owner_user_id` FK 를 만족시킬 작가 계정."""
    db_session.add(
        User(
            id=SEED_AUTHOR_USER_ID,
            email=seed_dev.SEED_AUTHOR_EMAIL,
            nickname="시드 작가",
            birth_date=date(1995, 1, 1),
            terms_agreed_at=datetime.now(timezone.utc),
            privacy_agreed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()


async def _count(db_session: AsyncSession, model: Any) -> int:
    result = await db_session.scalar(select(func.count()).select_from(model))
    assert result is not None
    return result


async def _assert_published(
    db_session: AsyncSession,
    content_id: uuid.UUID,
    version_id: uuid.UUID,
    content_type: ContentType,
    thumbnail_asset_id: uuid.UUID | None,
    slug: str,
) -> None:
    content = await db_session.get(Content, content_id)
    assert content is not None, f"{slug}: 콘텐츠가 없다"
    assert content.type == content_type
    assert content.creator_user_id == SEED_AUTHOR_USER_ID
    assert content.visibility == ContentVisibility.PUBLIC
    assert content.current_published_version_id == version_id
    version = await db_session.get(ContentVersion, version_id)
    assert version is not None and version.published_at is not None
    assert thumbnail_asset_id is not None, f"{slug}: 썸네일 자산이 안 붙었다"
    assert await db_session.get(Asset, thumbnail_asset_id) is not None


async def test_seed_content_files_publishes_every_data_file(
    db_session: AsyncSession, s3_bucket: None
) -> None:
    await _seed_author(db_session)

    await seed_dev.seed_content_files(db_session)

    stories = load_stories()
    characters = load_characters()
    assert stories and characters, "시드할 데이터 파일이 없다"
    for story in stories:
        detail = await db_session.get(StoryVersionDetail, story_version_id(story.slug))
        assert detail is not None and detail.name == story.payload.name
        await _assert_published(
            db_session,
            story_content_id(story.slug),
            story_version_id(story.slug),
            ContentType.STORY,
            detail.thumbnail_asset_id,
            story.slug,
        )
    for character in characters:
        detail = await db_session.get(CharacterVersionDetail, character_version_id(character.slug))
        assert detail is not None and detail.name == character.payload.name
        await _assert_published(
            db_session,
            character_content_id(character.slug),
            character_version_id(character.slug),
            ContentType.CHARACTER,
            detail.thumbnail_asset_id,
            character.slug,
        )


async def test_seed_content_files_is_idempotent(db_session: AsyncSession, s3_bucket: None) -> None:
    await _seed_author(db_session)

    await seed_dev.seed_content_files(db_session)
    before = [
        await _count(db_session, model)
        for model in (Content, ContentVersion, SituationalImage, Asset)
    ]

    await seed_dev.seed_content_files(db_session)

    assert [
        await _count(db_session, model)
        for model in (Content, ContentVersion, SituationalImage, Asset)
    ] == before
