"""`scripts/seed_dev.py` 가 `seed_content/data/` 전체를 발행 상태로 밀어 넣는 배선.

개별 업서트 동작은 `test_seed_upsert.py` / `test_seed_character_upsert.py` 가 인위적인
payload 로 이미 검사한다. 여기서는 **커밋된 데이터 파일 전부**가 실제 시드 경로(썸네일 자산
주입 -> upsert -> 발행)를 그대로 통과하는지, 그리고 재실행이 행을 늘리지 않는지를 본다.
"""

import json
import uuid
from datetime import date, datetime, timezone, UTC
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
from seed_content.loader import STORY_DIRS, load_all_characters, load_all_stories
from seed_content.upsert import (
    character_content_id,
    character_version_id,
    story_content_id,
    story_draft_version_id,
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
            terms_agreed_at=datetime.now(UTC),
            privacy_agreed_at=datetime.now(UTC),
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

    stories = load_all_stories()
    characters = load_all_characters()
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
        character_detail = await db_session.get(
            CharacterVersionDetail, character_version_id(character.slug)
        )
        assert character_detail is not None and character_detail.name == character.payload.name
        await _assert_published(
            db_session,
            character_content_id(character.slug),
            character_version_id(character.slug),
            ContentType.CHARACTER,
            character_detail.thumbnail_asset_id,
            character.slug,
        )


async def test_seed_content_files_writes_story_development_examples_from_the_json(
    db_session: AsyncSession, s3_bucket: None
) -> None:
    """채팅은 스토리 버전의 쌍 목록 `development_examples` 만 읽는다. 시드가 이 칸을 빈 목록으로
    덮으면 전개 예시가 조용히 사라진 채 채팅이 계속 돌아가므로(에러 없음), 발행본과 초안 둘 다
    파일에 적힌 쌍 목록 그대로 들어갔는지 원본 JSON 과 직접 대조한다. 로더를 거친 payload 와
    비교하면 키가 빠진 파일도 스키마 기본값 빈 목록끼리 같아져 통과해 버린다."""
    await _seed_author(db_session)

    await seed_dev.seed_content_files(db_session)

    for path in [path for directory in STORY_DIRS for path in sorted(directory.glob("*.json"))]:
        expected = json.loads(path.read_text(encoding="utf-8")).get("developmentExamples")
        assert expected, f"{path.stem}: 시드 JSON 에 전개 예시 쌍 목록이 없다"
        for version_id in (story_version_id(path.stem), story_draft_version_id(path.stem)):
            detail = await db_session.get(StoryVersionDetail, version_id)
            assert detail is not None
            assert detail.development_examples == expected, (
                f"{path.stem}: DB 의 전개 예시가 시드 JSON 과 다르다"
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
