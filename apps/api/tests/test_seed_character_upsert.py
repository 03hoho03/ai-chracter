"""`scripts/seed_content/upsert.py` 의 캐릭터 시드 업서트 (US-005)."""

import json
import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.image_processing import generate_blurred_image
from api.core.s3 import download_object
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus
from seed_content import images
from seed_content.ids import SEED_AUTHOR_USER_ID, seed_uuid
from seed_content.loader import load_character
from seed_content.upsert import (
    SeedPublishError,
    character_content_id,
    character_version_id,
    upsert_character,
)

SLUG = "romance-3rdloop-dj"
# 마이그레이션(91a008760f4a)이 시드한 장르 '로맨스'.
GENRE_ROMANCE = uuid.UUID("b8a1e6b0-1c1a-4b8a-9b0a-000000000001")


def _character_json() -> dict[str, Any]:
    """id 를 하나도 적지 않은 시드 JSON — entity_id 는 loader 가 위치로 파생한다."""
    return {
        "name": "서준",
        "oneLiner": "새벽 2시, 부스 안의 목소리",
        "thumbnailAssetId": None,  # 호출부가 ensure_asset 결과로 채운다
        "intro": "(헤드폰을 벗으며) 오늘도 왔네. 사연 하나 읽어줄까?",
        "exampleDialogues": [
            {"userLine": "오늘 방송 좋았어요", "characterLine": "…듣고 있었구나. 고마워."}
        ],
        "characterPrompt": "너는 심야 라디오 DJ '서준'이다. 항상 한국어로 나직하게 말한다.",
        "playguide": None,
        "situationalImages": [
            {"triggerCondition": "사용자가 첫 사연을 보냈을 때"},
            {"triggerCondition": "사용자가 회귀자임을 스스로 밝혔을 때"},
        ],
        "description": "심야 라디오 DJ와의 대화.",
        "genreId": str(GENRE_ROMANCE),
        "target": "female",
        "hashtags": ["로맨스", "라디오"],
        "visibility": "public",
    }


def _write_character(tmp_path: Path, payload: dict[str, Any]) -> Path:
    directory = tmp_path / "characters"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SLUG}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


async def _seed_author(db_session: AsyncSession) -> None:
    """`contents.creator_user_id` / `assets.owner_user_id` FK 를 만족시킬 작가 계정."""
    db_session.add(
        User(
            id=SEED_AUTHOR_USER_ID,
            email="seed-creator@example.com",
            nickname="시드 작가",
            birth_date=date(1995, 1, 1),
            terms_agreed_at=datetime.now(timezone.utc),
            privacy_agreed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()


async def _thumbnail_asset(db_session: AsyncSession) -> uuid.UUID:
    asset = Asset(
        owner_user_id=SEED_AUTHOR_USER_ID,
        storage_key=f"assets/seed/{uuid.uuid4()}.png",
        kind=AssetKind.THUMBNAIL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    return asset.id


async def _load_seed_payload(
    db_session: AsyncSession, tmp_path: Path, mutate: Callable[[dict[str, Any]], None] | None = None
) -> Any:
    """JSON 파일 -> loader -> 썸네일 자산 주입까지, 실제 시드 경로 그대로 만든다."""
    raw = _character_json()
    if mutate is not None:
        mutate(raw)
    payload = load_character(_write_character(tmp_path, raw))
    if raw["thumbnailAssetId"] is None:
        payload = payload.model_copy(update={"thumbnail_asset_id": await _thumbnail_asset(db_session)})
    return payload


async def _count(db_session: AsyncSession, model: Any, *where: Any) -> int:
    result = await db_session.scalar(select(func.count()).select_from(model).where(*where))
    assert result is not None
    return result


async def _situational_images(
    db_session: AsyncSession, version_id: uuid.UUID
) -> list[SituationalImage]:
    return list(
        (
            await db_session.scalars(
                select(SituationalImage)
                .where(SituationalImage.content_version_id == version_id)
                .order_by(SituationalImage.order)
            )
        ).all()
    )


@pytest.fixture(autouse=True)
def _no_image_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """이미지 디렉터리는 gitignore 라 CI 에는 없다 — 목업 폴백 경로로 고정해 테스트한다."""
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "images")


async def test_upsert_character_publishes_with_derived_ids(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path
) -> None:
    await _seed_author(db_session)
    payload = await _load_seed_payload(db_session, tmp_path)

    content_id = await upsert_character(db_session, SLUG, payload)

    assert content_id == seed_uuid("character", SLUG)
    content = await db_session.get(Content, content_id)
    assert content is not None
    assert content.creator_user_id == SEED_AUTHOR_USER_ID
    assert content.current_published_version_id == character_version_id(SLUG)
    assert content.visibility == ContentVisibility.PUBLIC
    assert content.moderation_status == ModerationStatus.NORMAL
    assert content.genre_id == GENRE_ROMANCE
    assert content.target == ContentTarget.FEMALE
    assert content.hashtags == ["로맨스", "라디오"]

    version = await db_session.get(ContentVersion, character_version_id(SLUG))
    assert version is not None
    assert version.version_number == 1
    assert version.published_at is not None
    assert version.detail_description == "심야 라디오 DJ와의 대화."

    detail = await db_session.get(CharacterVersionDetail, version.id)
    assert detail is not None
    assert detail.name == "서준"
    assert detail.thumbnail_asset_id == payload.thumbnail_asset_id
    assert detail.character_prompt.startswith("너는 심야 라디오 DJ")
    assert [pair["userLine"] for pair in detail.example_dialogues] == ["오늘 방송 좋았어요"]


async def test_upsert_character_pairs_each_image_with_a_blurred_asset(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path
) -> None:
    await _seed_author(db_session)
    payload = await _load_seed_payload(db_session, tmp_path)

    await upsert_character(db_session, SLUG, payload)

    rows = await _situational_images(db_session, character_version_id(SLUG))
    assert [row.trigger_condition for row in rows] == [
        "사용자가 첫 사연을 보냈을 때",
        "사용자가 회귀자임을 스스로 밝혔을 때",
    ]
    # entity_id 는 JSON 안의 위치에서 파생된다 (loader 규약).
    assert [row.entity_id for row in rows] == [
        seed_uuid(f"character:{SLUG}:situationalImages[0]"),
        seed_uuid(f"character:{SLUG}:situationalImages[1]"),
    ]

    for order, row in enumerate(rows):
        assert row.image_asset_id is not None
        assert row.blurred_asset_id is not None
        original = await db_session.get(Asset, row.image_asset_id)
        blurred = await db_session.get(Asset, row.blurred_asset_id)
        assert original is not None and blurred is not None
        assert (original.kind, blurred.kind) == (AssetKind.ORIGINAL, AssetKind.BLURRED)
        assert (original.status, blurred.status) == (AssetStatus.READY, AssetStatus.READY)
        # 이미지 파일이 없으므로 원본은 목업이고, 블러는 그 목업을 흐린 것이다.
        mock = images.mock_thumbnail(images.situational_image_slug(SLUG, order))
        assert download_object(original.storage_key) == mock
        assert download_object(blurred.storage_key) == generate_blurred_image(mock)


async def test_upsert_character_twice_does_not_duplicate_rows(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path
) -> None:
    await _seed_author(db_session)
    payload = await _load_seed_payload(db_session, tmp_path)
    version_id = character_version_id(SLUG)

    await upsert_character(db_session, SLUG, payload)
    first_rows = [(row.id, row.image_asset_id) for row in await _situational_images(db_session, version_id)]
    first_asset_count = await _count(db_session, Asset)

    await upsert_character(db_session, SLUG, payload)

    assert await _count(db_session, Content, Content.id == character_content_id(SLUG)) == 1
    assert (
        await _count(db_session, ContentVersion, ContentVersion.content_id == character_content_id(SLUG))
        == 1
    )
    assert await _count(db_session, Asset) == first_asset_count
    # 자식의 물리 id 까지 그대로여야 재시드가 기존 참조를 끊지 않는다.
    assert [
        (row.id, row.image_asset_id) for row in await _situational_images(db_session, version_id)
    ] == first_rows


async def test_upsert_character_updates_content_in_place(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path
) -> None:
    await _seed_author(db_session)
    await upsert_character(db_session, SLUG, await _load_seed_payload(db_session, tmp_path))
    version_id = character_version_id(SLUG)
    first_published_at = (await db_session.get(ContentVersion, version_id)).published_at  # type: ignore[union-attr]

    def _edit(raw: dict[str, Any]) -> None:
        raw["intro"] = "(마이크를 끄며) 또 왔구나."
        raw["situationalImages"].pop()  # 사라진 항목은 정리된다

    await upsert_character(db_session, SLUG, await _load_seed_payload(db_session, tmp_path, _edit))

    detail = await db_session.get(CharacterVersionDetail, version_id)
    assert detail is not None
    assert detail.intro == "(마이크를 끄며) 또 왔구나."
    assert len(await _situational_images(db_session, version_id)) == 1
    # 발행 시각은 최초 시드 값을 유지한다.
    version = await db_session.get(ContentVersion, version_id)
    assert version is not None
    assert version.published_at == first_published_at


async def test_upsert_character_rejects_incomplete_payload_without_writing(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path
) -> None:
    await _seed_author(db_session)

    def _break(raw: dict[str, Any]) -> None:
        raw["genreId"] = None
        raw["intro"] = ""

    raw = _character_json()
    _break(raw)
    payload = load_character(_write_character(tmp_path, raw))  # thumbnailAssetId 도 None 인 채로

    with pytest.raises(SeedPublishError) as exc_info:
        await upsert_character(db_session, SLUG, payload)

    message = str(exc_info.value)
    assert SLUG in message
    for field in ("thumbnailAssetId", "intro", "genreId"):
        assert field in message
    # 검증 실패 시 아무 행도 쓰이지 않는다 — 자산도 만들지 않는다.
    assert await db_session.get(Content, character_content_id(SLUG)) is None
    assert await db_session.get(ContentVersion, character_version_id(SLUG)) is None
    assert await _count(db_session, Asset) == 0
