"""운영 작품을 비공개 시드 묶음으로 내보내는 스크립트(`scripts/export_seed_bundle.py`).

핵심은 왕복이다 — 앱 경로로 만든 작품을 내보내고, 묶음을 풀어 다른 작가(시드 작가)로 시드한 뒤 시드된 초안 응답이
원본 응답과 같아야 한다. 자산 id·URL·작품 id 처럼 환경마다 달라지는 칸만 빼고 비교한다. 운영 데이터는 쓰지 않고 이
테스트가 지어낸 합성 작품만 쓴다.

내보내기는 트랜잭션을 읽기 전용으로 바꾸므로, 테스트는 그것을 세이브포인트 안에서 부르고 되돌린다 — 되돌리지 않으면
같은 테스트 트랜잭션의 뒤이은 시드 쓰기가 거부된다.
"""

import hashlib
import io
import json
import tarfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import export_seed_bundle
import seed_dev
from factories import _make_user
from api.assets.image_processing import read_frame_count, read_image_content_type, read_image_size
from api.content.router import (
    _character_draft_response,
    _story_draft_response,
    _update_character_draft,
    _update_story_draft,
)
from api.content.schemas import CharacterDraftPayload, StoryDraftPayload
from api.core.s3 import download_object, upload_object
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import Content, ContentType, ContentVersion, ContentVisibility, ModerationStatus
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import KeywordNote, MediaBookCell, StartingSetup, StoryVersionDetail
from seed_content import images, loader
from seed_content.ids import SEED_AUTHOR_USER_ID
from seed_content.upsert import (
    character_content_id,
    character_draft_version_id,
    story_content_id,
    story_draft_version_id,
)

# 마이그레이션(91a008760f4a)이 시드한 장르 '로맨스'.
GENRE_ROMANCE = uuid.UUID("b8a1e6b0-1c1a-4b8a-9b0a-000000000001")
# 합성 작품의 이름·본문마다 넣는 표식 — 표준 출력에 이 글자가 보이면 이름이나 본문이 새어 나간 것이다.
MARK = "합성표식"
STORY_SLUG = "private-export-story"
CHARACTER_SLUG = "private-export-character"
DRAFT_CHARACTER_SLUG = "private-export-draft"
GIF_CROP = {"x": 4, "y": 2, "width": 20, "height": 12}


def _png(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _gif() -> bytes:
    frames = [Image.new("RGB", (40, 30), color) for color in ((60, 20, 20), (20, 20, 60))]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buffer.getvalue()


async def _source_asset(
    db: AsyncSession, owner_id: uuid.UUID, data: bytes, *, crop: dict[str, int] | None = None
) -> Asset:
    """업로드가 끝난 작가 원본 자산 하나. 원본 바이트는 moto 에 올린다 — 내보내기가 내려받을 자리다."""
    content_type = read_image_content_type(data) or "image/png"
    width, height = (crop["width"], crop["height"]) if crop is not None else read_image_size(data)
    asset = Asset(
        owner_user_id=owner_id,
        storage_key=f"assets/test-export/{uuid.uuid4()}.{content_type.removeprefix('image/')}",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
        width=width,
        height=height,
        frame_count=read_frame_count(data),
        crop=crop,
    )
    db.add(asset)
    await db.flush()
    upload_object(asset.storage_key, data, content_type)
    return asset


async def _new_content(db: AsyncSession, author_id: uuid.UUID, content_type: ContentType) -> Content:
    content = Content(
        creator_user_id=author_id,
        type=content_type,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    return content


async def _story_version(db: AsyncSession, content: Content, payload: StoryDraftPayload) -> ContentVersion:
    """빌더 자동저장 경로(`_update_story_draft`)로 채운 버전 하나. 상세 행은 `POST /contents` 가 만드는 것처럼 먼저 둔다."""
    version = ContentVersion(content_id=content.id, detail_description=payload.description)
    db.add(version)
    await db.flush()
    db.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name=payload.name,
            one_liner=payload.one_liner,
            prompt_template=payload.prompt_template,
        )
    )
    await db.flush()
    await _update_story_draft(db, content, version, payload)
    await db.flush()
    return version


async def _character_version(
    db: AsyncSession, content: Content, payload: CharacterDraftPayload, image_asset_ids: list[uuid.UUID]
) -> ContentVersion:
    """`_story_version` 의 캐릭터 판. 상황별 이미지 그림은 등록 라우트가 하듯 행에 직접 건다."""
    version = ContentVersion(content_id=content.id, detail_description=payload.description)
    db.add(version)
    await db.flush()
    db.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name=payload.name,
            one_liner=payload.one_liner,
            intro=payload.intro,
            example_dialogues=[],
            character_prompt=payload.character_prompt,
        )
    )
    await db.flush()
    await _update_character_draft(db, content, version, payload)
    await db.flush()
    rows = (
        await db.scalars(
            select(SituationalImage)
            .where(SituationalImage.content_version_id == version.id)
            .order_by(SituationalImage.order)
        )
    ).all()
    for row, asset_id in zip(rows, image_asset_ids, strict=True):
        row.image_asset_id = asset_id
    await db.flush()
    return version


async def _publish(db: AsyncSession, content: Content, version: ContentVersion) -> None:
    version.version_number = 1
    version.published_at = datetime.now(UTC)
    content.current_published_version_id = version.id
    await db.flush()


def _story_payload(
    *,
    name: str,
    thumbnail_asset_id: uuid.UUID | None,
    cell_ids: tuple[uuid.UUID, uuid.UUID],
    cell_asset_ids: tuple[uuid.UUID, uuid.UUID],
) -> StoryDraftPayload:
    """빌더의 거의 모든 칸을 채운 비공개 스토리 — 시작설정 둘, 스탯·규칙, 규칙 그룹이 든 엔딩, 상황 노트, 시작설정을
    가리키는 키워드 노트, 단축어, 칸 둘짜리 미디어 북. 설명과 프롤로그는 칸 태그로 칸 id 를 가리킨다."""
    setup_ids = (uuid.uuid4(), uuid.uuid4())
    trust_id, timer_id = uuid.uuid4(), uuid.uuid4()
    person_id = uuid.uuid4()
    scene_ids = (uuid.uuid4(), uuid.uuid4())

    def rule(threshold: float, next_op: str | None = None) -> dict[str, Any]:
        return {
            "kind": "rule",
            "id": str(uuid.uuid4()),
            "statId": str(trust_id),
            "operator": "gte",
            "threshold": threshold,
            "nextOp": next_op,
        }

    raw: dict[str, Any] = {
        "name": name,
        "oneLiner": f"{MARK} 한 줄 소개",
        "thumbnailAssetId": str(thumbnail_asset_id) if thumbnail_asset_id else None,
        "promptTemplate": "basic",
        "settingText": f"{MARK} 서술자 지시문",
        "developmentExample": None,
        "customPrompt": None,
        "developmentExamples": [],
        "userGoal": f"{MARK} 목표",
        "rules": f"{MARK} 규칙",
        "sceneHeaderEnabled": True,
        "startingSetups": [
            {
                "id": str(setup_ids[0]),
                "name": f"{MARK} 첫 장면",
                "prologue": f"{{{{img::{cell_ids[1]}}}}} {MARK} 프롤로그",
                "openingMessage": f"{MARK} 첫 메시지",
                "playguide": f"{MARK} 안내",
                "suggestedReplies": ["안녕"],
                "initialScenePlace": "동아리방",
                "initialSceneTime": "방과 후",
                "statDefs": [
                    {
                        "id": str(trust_id),
                        "name": "신뢰",
                        "icon": "heart",
                        "color": "#c04060",
                        "minValue": 0,
                        "maxValue": 100,
                        "initialValue": 10,
                        "unit": "점",
                        "description": f"{MARK} 신뢰 설명",
                        "hiddenFromPlayer": True,
                        "playerDescription": "마음의 거리",
                        "signalHiddenChange": True,
                        "rules": [{"id": str(uuid.uuid4()), "condition": "칭찬하면", "delta": 5}],
                    }
                ],
                "endings": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": f"{MARK} 엔딩",
                        "turnCountGate": 12,
                        "judgmentPrompt": f"{MARK} 판정",
                        "epilogue": f"{MARK} 에필로그",
                        "hint": "더 가까워지면",
                        "statRules": [
                            rule(50, "and"),
                            {
                                "kind": "group",
                                "id": str(uuid.uuid4()),
                                "nextOp": None,
                                "rules": [rule(70, "or"), rule(90)],
                            },
                        ],
                        "priorityStatId": str(trust_id),
                    }
                ],
                "situationNotes": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "가까워짐",
                        "infoText": f"{MARK} 상황 노트",
                        "conditionRules": [rule(30)],
                    }
                ],
            },
            {
                "id": str(setup_ids[1]),
                "name": f"{MARK} 둘째 장면",
                "prologue": f"{MARK} 둘째 프롤로그",
                "openingMessage": None,
                "playguide": None,
                "suggestedReplies": [],
                "statDefs": [
                    {
                        "id": str(timer_id),
                        "name": "남은 시간",
                        "icon": "clock",
                        "color": "#808080",
                        "minValue": 0,
                        "maxValue": 30,
                        "initialValue": 30,
                        "unit": None,
                        "description": "턴마다 준다",
                        "perTurnDelta": -1,
                    }
                ],
                "endings": [],
                "situationNotes": [],
            },
        ],
        "keywordNotes": [
            {
                "id": str(uuid.uuid4()),
                "infoText": f"{MARK} 둘째 장면 노트",
                "triggerKeywords": ["동아리"],
                "startingSetupId": str(setup_ids[1]),
                "name": "동아리",
                "excludeKeywords": ["꿈"],
                "stickyTurns": 2,
                "alwaysOn": False,
            },
            {
                "id": str(uuid.uuid4()),
                "infoText": f"{MARK} 상시 노트",
                "triggerKeywords": [],
                "startingSetupId": None,
                "name": "상시",
                "excludeKeywords": [],
                "stickyTurns": 0,
                "alwaysOn": True,
            },
        ],
        "shortcuts": [{"id": str(uuid.uuid4()), "name": "인사", "description": "인사한다", "prompt": f"{MARK} 인사"}],
        "description": f"{{{{img::{cell_ids[0]}}}}} {MARK} 등록 설명",
        "genreId": str(GENRE_ROMANCE),
        "target": "female",
        "hashtags": ["합성", "왕복"],
        "visibility": "private",
        "novelPermission": "public",
        "mediaBook": {
            "people": [{"id": str(person_id), "name": "유나"}],
            "scenes": [{"id": str(scene_ids[0]), "name": "교실"}, {"id": str(scene_ids[1]), "name": "옥상"}],
            "cells": [
                {
                    "id": str(cell_id),
                    "personId": str(person_id),
                    "sceneId": str(scene_id),
                    "imageAssetId": str(asset_id),
                    "situationDescription": f"{MARK} 칸 설명",
                    "unlockHint": "옥상에서",
                    "excludeFromChat": index == 1,
                }
                for index, (cell_id, scene_id, asset_id) in enumerate(
                    zip(cell_ids, scene_ids, cell_asset_ids, strict=True)
                )
            ],
        },
    }
    return StoryDraftPayload.model_validate(raw)


def _character_payload(
    *, name: str, thumbnail_asset_id: uuid.UUID | None, situational_ids: list[uuid.UUID], published: bool = True
) -> CharacterDraftPayload:
    return CharacterDraftPayload.model_validate(
        {
            "name": name,
            "oneLiner": f"{MARK} 캐릭터 한 줄",
            "thumbnailAssetId": str(thumbnail_asset_id) if thumbnail_asset_id else None,
            "intro": f"{MARK} 인트로" if published else "",
            "exampleDialogues": [{"id": "d1", "userLine": "안녕", "characterLine": f"{MARK} 응"}],
            "characterPrompt": f"너는 {MARK} 이다.",
            "playguide": None,
            "situationalImages": [
                {"id": str(entity_id), "triggerCondition": f"{MARK} 조건 {index}"}
                for index, entity_id in enumerate(situational_ids)
            ],
            "description": f"{MARK} 캐릭터 설명",
            "genreId": str(GENRE_ROMANCE) if published else None,
            "target": "female" if published else None,
            "hashtags": ["합성"],
            "visibility": "private" if published else "public",
            "novelPermission": "forbidden",
        }
    )


@dataclass
class _Sources:
    author_id: uuid.UUID
    story_id: uuid.UUID
    character_id: uuid.UUID
    draft_character_id: uuid.UUID
    cell_ids: tuple[uuid.UUID, uuid.UUID]
    situational_ids: list[uuid.UUID]
    # 그림 자리 → 원본 바이트: "story-thumbnail", "cell-0", "cell-1", "character-thumbnail", "situational-0", ….
    image_bytes: dict[str, bytes]
    # 내보내기 전에 만들어 둔 원본 초안 응답(비교용 꼴). 스토리·캐릭터는 발행본, 미발행 캐릭터는 초안.
    expected: dict[str, dict[str, Any]]


async def _make_sources(db: AsyncSession) -> _Sources:
    """작가 한 명의 발행 스토리(발행 뒤 초안을 더 고쳤다), GIF 대표 이미지에 크롭이 걸린 발행 캐릭터, 초안만 있는 캐릭터."""
    author = _make_user()
    db.add(author)
    await db.flush()
    image_bytes = {
        "story-thumbnail": _png((48, 32), (40, 30, 50)),
        "cell-0": _png((64, 96), (50, 20, 20)),
        "cell-1": _png((64, 96), (20, 50, 20)),
        "character-thumbnail": _gif(),
        "situational-0": _png((30, 40), (20, 20, 50)),
        "situational-1": _png((30, 40), (50, 50, 20)),
    }
    assets = {
        role: await _source_asset(db, author.id, data, crop=GIF_CROP if role == "character-thumbnail" else None)
        for role, data in image_bytes.items()
    }

    cell_ids = (uuid.uuid4(), uuid.uuid4())
    cell_asset_ids = (assets["cell-0"].id, assets["cell-1"].id)
    story = await _new_content(db, author.id, ContentType.STORY)
    published_story_payload = _story_payload(
        name=f"{MARK} 왕복 스토리",
        thumbnail_asset_id=assets["story-thumbnail"].id,
        cell_ids=cell_ids,
        cell_asset_ids=cell_asset_ids,
    )
    story_published = await _story_version(db, story, published_story_payload)
    await _publish(db, story, story_published)
    # 발행 뒤 작가가 초안을 더 고쳤다 — 내보내기는 이 초안이 아니라 발행본을 담아야 한다.
    await _story_version(db, story, published_story_payload.model_copy(update={"name": f"{MARK} 고친 초안"}))

    situational_ids = [uuid.uuid4(), uuid.uuid4()]
    character = await _new_content(db, author.id, ContentType.CHARACTER)
    character_published = await _character_version(
        db,
        character,
        _character_payload(
            name=f"{MARK} 왕복 캐릭터",
            thumbnail_asset_id=assets["character-thumbnail"].id,
            situational_ids=situational_ids,
        ),
        [assets["situational-0"].id, assets["situational-1"].id],
    )
    await _publish(db, character, character_published)

    draft_character = await _new_content(db, author.id, ContentType.CHARACTER)
    draft_character_version = await _character_version(
        db,
        draft_character,
        _character_payload(name=f"{MARK} 쓰다 만 캐릭터", thumbnail_asset_id=None, situational_ids=[], published=False),
        [],
    )

    expected = {
        STORY_SLUG: _comparable(await _story_draft_response(db, story, story_published)),
        CHARACTER_SLUG: _comparable(await _character_draft_response(db, character, character_published)),
        DRAFT_CHARACTER_SLUG: _comparable(
            await _character_draft_response(db, draft_character, draft_character_version)
        ),
    }
    return _Sources(
        author_id=author.id,
        story_id=story.id,
        character_id=character.id,
        draft_character_id=draft_character.id,
        cell_ids=cell_ids,
        situational_ids=situational_ids,
        image_bytes=image_bytes,
        expected=expected,
    )


def _comparable(response: Any) -> dict[str, Any]:
    """초안 응답에서 환경마다 달라지는 칸(작품·버전 id, 자산 id, 서명 URL)을 뺀 꼴."""
    dumped: dict[str, Any] = response.model_dump(by_alias=True, mode="json")
    for key in ("id", "contentVersionId", "thumbnailAssetId", "thumbnailUrl"):
        dumped.pop(key, None)
    for cell in dumped.get("mediaBook", {}).get("cells", []):
        cell.pop("imageAssetId")
        cell.pop("imageUrl")
    for image in dumped.get("situationalImages", []):
        image.pop("imageAssetId")
        image.pop("imageUrl")
    return dumped


def _write_map(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _sources_map(tmp_path: Path, sources: _Sources) -> Path:
    return _write_map(
        tmp_path / "map.txt",
        [
            "# 합성 작품 맵",
            f"{sources.story_id} {STORY_SLUG}",
            "",
            f"{sources.character_id} {CHARACTER_SLUG}",
            f"{sources.draft_character_id} {DRAFT_CHARACTER_SLUG}",
        ],
    )


async def _run_export(db: AsyncSession, map_path: Path, out: Path) -> int:
    """내보내기를 세이브포인트 안에서 부르고 되돌린다 — 읽기 전용 표시도 함께 풀린다."""
    savepoint = await db.begin_nested()
    try:
        return await export_seed_bundle.run(db, map_path, out)
    finally:
        await savepoint.rollback()


def _extract(out: Path, destination: Path) -> Path:
    destination.mkdir()
    with tarfile.open(out, "r:gz") as archive:
        archive.extractall(destination, filter="data")
    return destination


async def _seed_from(db: AsyncSession, private_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """푼 묶음을 시드 작가로 시드한다. 튜토리얼 이미지 폴더는 비워 목업 경로로 고정한다(CI 와 같은 조건)."""
    monkeypatch.setattr(loader, "PRIVATE_DIR", private_dir)
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "tutorial-images")
    db.add(_make_user(id=SEED_AUTHOR_USER_ID))
    await db.flush()
    await seed_dev.seed_content_files(db)


async def _asset(db: AsyncSession, asset_id: uuid.UUID | None) -> Asset:
    assert asset_id is not None
    asset = await db.get(Asset, asset_id)
    assert asset is not None
    return asset


# ---- 왕복 ----


async def test_exported_bundle_seeds_works_equal_to_the_originals(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """내보낸 묶음을 다른 작가로 시드하면 초안 응답이 원본(발행본이 있으면 발행본)과 같다. 칸 entity id 가 이어져
    본문의 칸 태그가 같은 칸을 가리키고, 그림 원본 바이트·움직이는 대표 이미지의 크롭·프레임 수도 같다."""
    sources = await _make_sources(db_session)
    out = tmp_path / "seed-bundle.tar.gz"

    assert await _run_export(db_session, _sources_map(tmp_path, sources), out) == 0

    assert out.is_file(), "묶음 파일이 없다"
    private_dir = _extract(out, tmp_path / "private")
    assert (private_dir / "manifest.json").is_file(), "묶음에 최상위 폴더가 끼어 있다"
    assert len(list((private_dir / "images").iterdir())) == len(sources.image_bytes)
    manifest = json.loads((private_dir / "manifest.json").read_text(encoding="utf-8"))
    gif_entry = manifest["characters"][CHARACTER_SLUG]["thumbnail"]
    assert (gif_entry["kind"], gif_entry["contentType"], gif_entry["frameCount"], gif_entry["crop"]) == (
        AssetKind.ORIGINAL.value,
        "image/gif",
        2,
        GIF_CROP,
    )
    draft_raw = json.loads((private_dir / "characters" / f"{DRAFT_CHARACTER_SLUG}.json").read_text(encoding="utf-8"))
    assert draft_raw["seedPublished"] is False

    await _seed_from(db_session, private_dir, monkeypatch, tmp_path)

    story = await db_session.get(Content, story_content_id(STORY_SLUG))
    story_draft = await db_session.get(ContentVersion, story_draft_version_id(STORY_SLUG))
    assert story is not None and story_draft is not None
    assert story.creator_user_id == SEED_AUTHOR_USER_ID
    assert _comparable(await _story_draft_response(db_session, story, story_draft)) == sources.expected[STORY_SLUG]
    assert (story.visibility, story.current_published_version_id is not None) == (ContentVisibility.PRIVATE, True)
    setups = (
        await db_session.scalars(
            select(StartingSetup)
            .where(StartingSetup.content_version_id == story_draft.id)
            .order_by(StartingSetup.order)
        )
    ).all()
    assert f"{{{{img::{sources.cell_ids[1]}}}}}" in setups[0].prologue
    assert f"{{{{img::{sources.cell_ids[0]}}}}}" in story_draft.detail_description
    cells = (
        await db_session.scalars(select(MediaBookCell).where(MediaBookCell.content_version_id == story_draft.id))
    ).all()
    for cell in cells:
        index = sources.cell_ids.index(cell.entity_id)
        cell_asset = await _asset(db_session, cell.image_asset_id)
        assert download_object(cell_asset.storage_key) == sources.image_bytes[f"cell-{index}"]
    story_detail = await db_session.get(StoryVersionDetail, story_draft.id)
    assert story_detail is not None
    story_thumbnail = await _asset(db_session, story_detail.thumbnail_asset_id)
    assert download_object(story_thumbnail.storage_key) == sources.image_bytes["story-thumbnail"]

    character = await db_session.get(Content, character_content_id(CHARACTER_SLUG))
    character_draft = await db_session.get(ContentVersion, character_draft_version_id(CHARACTER_SLUG))
    assert character is not None and character_draft is not None
    assert (
        _comparable(await _character_draft_response(db_session, character, character_draft))
        == sources.expected[CHARACTER_SLUG]
    )
    assert (character.visibility, character.current_published_version_id is not None) == (
        ContentVisibility.PRIVATE,
        True,
    )
    character_detail = await db_session.get(CharacterVersionDetail, character_draft.id)
    assert character_detail is not None
    gif = await _asset(db_session, character_detail.thumbnail_asset_id)
    assert (gif.crop, gif.frame_count) == (GIF_CROP, 2)
    assert download_object(gif.storage_key) == sources.image_bytes["character-thumbnail"]
    situational_rows = (
        await db_session.scalars(
            select(SituationalImage)
            .where(SituationalImage.content_version_id == character_draft.id)
            .order_by(SituationalImage.order)
        )
    ).all()
    assert [row.entity_id for row in situational_rows] == sources.situational_ids
    for index, row in enumerate(situational_rows):
        situational_asset = await _asset(db_session, row.image_asset_id)
        assert download_object(situational_asset.storage_key) == sources.image_bytes[f"situational-{index}"]

    draft_character = await db_session.get(Content, character_content_id(DRAFT_CHARACTER_SLUG))
    draft_character_version = await db_session.get(ContentVersion, character_draft_version_id(DRAFT_CHARACTER_SLUG))
    assert draft_character is not None and draft_character_version is not None
    assert (
        _comparable(await _character_draft_response(db_session, draft_character, draft_character_version))
        == sources.expected[DRAFT_CHARACTER_SLUG]
    )
    assert (draft_character.visibility, draft_character.current_published_version_id) == (
        ContentVisibility.PUBLIC,
        None,
    )


# ---- 안전장치 ----


async def _draft_story(db: AsyncSession, author_id: uuid.UUID) -> uuid.UUID:
    """그림 없는 초안 스토리 하나 — 안전장치는 그림을 보기 전에 멈춰야 한다."""
    content = await _new_content(db, author_id, ContentType.STORY)
    cell_ids = (uuid.uuid4(), uuid.uuid4())
    payload = _story_payload(name=f"{MARK} 초안", thumbnail_asset_id=None, cell_ids=cell_ids, cell_asset_ids=cell_ids)
    await _story_version(db, content, payload.model_copy(update={"media_book": None}))
    return content.id


async def _author(db: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db.add(user)
    await db.flush()
    return user.id


async def test_export_refuses_a_map_id_missing_from_the_db(db_session: AsyncSession, tmp_path: Path) -> None:
    story_id = await _draft_story(db_session, await _author(db_session))
    map_path = _write_map(tmp_path / "map.txt", [f"{story_id} private-a", f"{uuid.uuid4()} private-b"])
    out = tmp_path / "seed-bundle.tar.gz"

    assert await _run_export(db_session, map_path, out) == export_seed_bundle.EXIT_REFUSED
    assert not out.exists()


async def test_export_refuses_works_of_two_authors(db_session: AsyncSession, tmp_path: Path) -> None:
    """묶음은 시드 작가 한 명의 작품이 된다 — 두 작가의 작품을 섞으면 남의 작품이 한 사람 것으로 합쳐진다."""
    first = await _draft_story(db_session, await _author(db_session))
    second = await _draft_story(db_session, await _author(db_session))
    map_path = _write_map(tmp_path / "map.txt", [f"{first} private-a", f"{second} private-b"])
    out = tmp_path / "seed-bundle.tar.gz"

    assert await _run_export(db_session, map_path, out) == export_seed_bundle.EXIT_REFUSED
    assert not out.exists()


async def test_export_refuses_a_slug_used_twice(db_session: AsyncSession, tmp_path: Path) -> None:
    """slug 가 곧 파일 이름이자 시드 id 라 겹치면 한 작품이 다른 작품을 조용히 덮는다."""
    author_id = await _author(db_session)
    first = await _draft_story(db_session, author_id)
    second = await _draft_story(db_session, author_id)
    map_path = _write_map(tmp_path / "map.txt", [f"{first} private-a", f"{second} private-a"])
    out = tmp_path / "seed-bundle.tar.gz"

    assert await _run_export(db_session, map_path, out) == export_seed_bundle.EXIT_REFUSED
    assert not out.exists()


@pytest.mark.parametrize("slug", ["a/b", "../x", "Private-A", "-private", ""])
async def test_export_refuses_a_slug_outside_the_file_name_form(
    db_session: AsyncSession, tmp_path: Path, slug: str
) -> None:
    """slug 는 묶음 안 파일 이름이 된다 — 슬래시나 `..` 가 들어가면 풀 때 정해진 폴더 밖이나 엉뚱한 폴더에 파일이
    생기고, 대문자는 대소문자를 가리지 않는 파일 시스템에서 다른 slug 와 부딪힌다."""
    story_id = await _draft_story(db_session, await _author(db_session))
    map_path = _write_map(tmp_path / "map.txt", [f"{story_id} {slug}"])
    out = tmp_path / "seed-bundle.tar.gz"

    assert await _run_export(db_session, map_path, out) == export_seed_bundle.EXIT_REFUSED
    assert not out.exists()


def test_read_map_accepts_a_lowercase_hyphenated_slug(tmp_path: Path) -> None:
    content_id = uuid.uuid4()
    map_path = _write_map(tmp_path / "map.txt", [f"{content_id} tutorial-filmclub"])

    assert export_seed_bundle.read_map(map_path) == [
        export_seed_bundle.MapEntry(content_id=content_id, slug="tutorial-filmclub")
    ]


async def test_export_refuses_the_same_work_under_two_slugs(db_session: AsyncSession, tmp_path: Path) -> None:
    """같은 작품을 두 slug 로 담으면 로컬에 같은 작품이 둘 생긴다 — 맵을 쓴 사람이 의도한 결과가 아니다."""
    story_id = await _draft_story(db_session, await _author(db_session))
    map_path = _write_map(tmp_path / "map.txt", [f"{story_id} private-a", f"{story_id} private-b"])
    out = tmp_path / "seed-bundle.tar.gz"

    assert await _run_export(db_session, map_path, out) == export_seed_bundle.EXIT_REFUSED
    assert not out.exists()


async def test_export_refuses_to_overwrite_an_existing_out_file(db_session: AsyncSession, tmp_path: Path) -> None:
    story_id = await _draft_story(db_session, await _author(db_session))
    map_path = _write_map(tmp_path / "map.txt", [f"{story_id} private-a"])
    out = tmp_path / "seed-bundle.tar.gz"
    out.write_bytes(b"earlier bundle")

    assert await _run_export(db_session, map_path, out) == export_seed_bundle.EXIT_REFUSED
    assert out.read_bytes() == b"earlier bundle"


# ---- 읽기 전용 ----


def _recording_read_only(
    original: Callable[..., Awaitable[Any]], seen: list[str | None]
) -> Callable[..., Awaitable[Any]]:
    async def wrapper(db: AsyncSession, content: Content, version: ContentVersion) -> Any:
        seen.append(await db.scalar(text("SHOW transaction_read_only")))
        return await original(db, content, version)

    return wrapper


async def _row_counts(db: AsyncSession) -> dict[str, int]:
    counts = {}
    for model in (
        Content,
        ContentVersion,
        StoryVersionDetail,
        CharacterVersionDetail,
        StartingSetup,
        KeywordNote,
        MediaBookCell,
        SituationalImage,
        Asset,
    ):
        count = await db.scalar(select(func.count()).select_from(model))
        assert count is not None
        counts[model.__tablename__] = count
    return counts


async def test_export_reads_every_work_inside_a_read_only_transaction(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """작품을 직렬화하는 순간마다 트랜잭션이 읽기 전용이다 — 실수로 쓰기가 섞여도 운영 DB 가 거부한다. 내보낸 뒤
    관련 표의 행 수도 그대로다."""
    sources = await _make_sources(db_session)
    seen: list[str | None] = []
    monkeypatch.setattr(export_seed_bundle, "_story_draft_response", _recording_read_only(_story_draft_response, seen))
    monkeypatch.setattr(
        export_seed_bundle, "_character_draft_response", _recording_read_only(_character_draft_response, seen)
    )
    before = await _row_counts(db_session)
    out = tmp_path / "seed-bundle.tar.gz"

    savepoint = await db_session.begin_nested()
    try:
        assert await export_seed_bundle.run(db_session, _sources_map(tmp_path, sources), out) == 0
        after = await _row_counts(db_session)
    finally:
        await savepoint.rollback()

    # 작품 셋이니 적어도 세 번 직렬화한다.
    assert len(seen) >= 3 and set(seen) == {"on"}, f"읽기 전용 트랜잭션 밖에서 직렬화했다: {seen}"
    assert after == before


# ---- 출력 ----


async def test_export_prints_only_counts_and_the_digest(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """운영 컨테이너 로그에 남는 글이라 작품 이름·본문은 찍지 않는다. 묶음을 옮긴 뒤 같은 파일인지 대조할 sha256 과
    바이트 수는 찍는다."""
    sources = await _make_sources(db_session)
    out = tmp_path / "seed-bundle.tar.gz"
    capsys.readouterr()

    assert await _run_export(db_session, _sources_map(tmp_path, sources), out) == 0

    captured = capsys.readouterr()
    printed = captured.out + captured.err
    assert out.is_file(), "묶음 파일이 없다"
    assert hashlib.sha256(out.read_bytes()).hexdigest() in printed
    assert str(out.stat().st_size) in printed
    assert MARK not in printed, "작품 이름이나 본문이 출력에 새었다"
