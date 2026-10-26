"""비공개 시드 묶음(`seed_content/private/`)을 고르고 넣는 경로.

묶음은 운영에 남은 작품을 읽기 전용으로 내보낸 것이라 gitignore 이고, 여기서는 합성 묶음을 `tmp_path` 에 만들어
`loader.PRIVATE_DIR` 자리에 끼운다. 묶음 모양:

    private/stories/{slug}.json      StoryDraftPayload + 최상위 `seedPublished`(생략하면 발행)
    private/characters/{slug}.json   CharacterDraftPayload + 같은 키
    private/images/{파일}            원본 바이트만(변형은 시드가 로컬에서 만든다)
    private/manifest.json            작품 slug 별로 대표 이미지와 칸 그림이 어느 파일인지, 원래 형식·크롭·프레임 수

하위 항목 id 는 운영 entity id 를 JSON 에 그대로 적는다 — 칸 태그(`{{img::<칸 id>}}`)와 측정 도구의 기본 id 가
이어지려면 로컬에서도 같아야 한다. JSON 의 자산 id 는 운영 자산이라 로컬에 없고, 시드가 매니페스트의 파일로 만든
로컬 자산 id 로 바꿔 넣는다.
"""

import io
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import seed_dev
from factories import _make_user
from api.assets.image_processing import generate_blurred_image
from api.core.s3 import (
    build_animated_display_key,
    build_animated_thumbnail_key,
    build_thumbnail_key,
    download_object,
)
from api.db.models.chat import ChatRoom
from api.db.models.content import Content, ContentVersion, ContentVisibility
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import MediaBookCell, MediaBookPerson, MediaBookScene, StartingSetup, StoryVersionDetail
from seed_content import images, loader
from seed_content.ids import SEED_AUTHOR_USER_ID, seed_uuid
from seed_content.upsert import (
    character_content_id,
    story_content_id,
    story_draft_version_id,
    story_version_id,
)

# 마이그레이션(91a008760f4a)이 시드한 장르 '로맨스'.
GENRE_ROMANCE = uuid.UUID("b8a1e6b0-1c1a-4b8a-9b0a-000000000001")
# 합성 "운영" id — 운영 데이터가 아니라 이 테스트가 지어낸 값이다.
_TEST_NAMESPACE = uuid.UUID("7e570000-0000-4000-8000-0000000000aa")


def _ops_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_TEST_NAMESPACE, name)


FILMCLUB_SLUG = "tutorial-filmclub"
FILMCLUB_YUNA_SLUG = "tutorial-filmclub-yuna"
MEDIA_BOOK_SLUG = "private-mediabook"
DRAFT_CHARACTER_SLUG = "private-draft"
CELL_IDS = (_ops_id("cell-1"), _ops_id("cell-2"))
CELL_SOURCE_ASSET_IDS = (_ops_id("cell-asset-1"), _ops_id("cell-asset-2"))
PERSON_ID = _ops_id("person-1")
SCENE_IDS = (_ops_id("scene-1"), _ops_id("scene-2"))
THUMBNAIL_SIZE = (400, 300)
THUMBNAIL_CROP = {"x": 0, "y": 0, "width": 100, "height": 50}


def _png(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _story_json(name: str, *, visibility: str = "public", media_book: dict[str, Any] | None = None) -> dict[str, Any]:
    """발행 검증을 통과하는 가장 작은 스토리. 운영에서 내보낸 것처럼 하위 항목 id 와 자산 id 를 적어 둔다."""
    raw: dict[str, Any] = {
        "name": name,
        "oneLiner": f"{name} 한 줄 소개",
        "thumbnailAssetId": str(_ops_id(f"{name}-thumbnail")),
        "promptTemplate": "basic",
        "settingText": "세계관 설명",
        "customPrompt": None,
        "startingSetups": [
            {
                "id": str(_ops_id(f"{name}-setup")),
                "name": "첫 장면",
                "prologue": f"{{{{img::{CELL_IDS[0]}}}}} 동아리방 문이 열린다."
                if media_book
                else "동아리방 문이 열린다.",
                "openingMessage": None,
                "playguide": None,
                "suggestedReplies": [],
                "statDefs": [],
                "endings": [],
            }
        ],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "상세 설명",
        "genreId": str(GENRE_ROMANCE),
        "target": "female",
        "hashtags": ["합성"],
        "visibility": visibility,
    }
    if media_book is not None:
        raw["mediaBook"] = media_book
    return raw


def _media_book_json() -> dict[str, Any]:
    return {
        "people": [{"id": str(PERSON_ID), "name": "민유나"}],
        "scenes": [{"id": str(SCENE_IDS[0]), "name": "동아리방"}, {"id": str(SCENE_IDS[1]), "name": "옥상"}],
        "cells": [
            {
                "id": str(cell_id),
                "personId": str(PERSON_ID),
                "sceneId": str(scene_id),
                "imageAssetId": str(source_asset_id),
                "situationDescription": "합성 칸 설명",
                "unlockHint": "",
            }
            for cell_id, scene_id, source_asset_id in zip(CELL_IDS, SCENE_IDS, CELL_SOURCE_ASSET_IDS, strict=True)
        ],
    }


def _character_json(name: str, *, intro: str = "(고개를 든다) 왔어?") -> dict[str, Any]:
    return {
        "name": name,
        "oneLiner": f"{name} 한 줄 소개",
        "thumbnailAssetId": None,
        "intro": intro,
        "exampleDialogues": [],
        "characterPrompt": f"너는 '{name}'이다.",
        "playguide": None,
        "situationalImages": [],
        "description": "상세 설명",
        "genreId": str(GENRE_ROMANCE),
        "target": "female",
        "hashtags": ["합성"],
        "visibility": "private",
    }


def _image_entry(file: str, *, kind: str = "thumbnail", crop: dict[str, int] | None = None) -> dict[str, Any]:
    """매니페스트 항목 하나 — 원본 파일 이름, 운영 자산의 종류·원래 형식·프레임 수·크롭."""
    return {"file": file, "kind": kind, "contentType": "image/png", "frameCount": 1, "crop": crop}


def _write_json(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def _write_image(private_dir: Path, file: str, data: bytes) -> bytes:
    path = private_dir / "images" / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


@pytest.fixture
def private_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """비어 있는 비공개 묶음 자리. 튜토리얼 이미지 폴더도 비워 목업 경로로 고정한다(CI 와 같은 조건)."""
    directory = tmp_path / "private"
    monkeypatch.setattr(loader, "PRIVATE_DIR", directory)
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "tutorial-images")
    return directory


def _write_bundle(private_dir: Path) -> dict[str, bytes]:
    """조감독 slug 를 이어받는 비공개 스토리, 미디어 북이 있는 스토리, 미발행 캐릭터 하나씩. 파일 이름 → 바이트."""
    files = {
        "filmclub-thumb.png": _png(THUMBNAIL_SIZE, (60, 30, 40)),
        "mediabook-thumb.png": _png(THUMBNAIL_SIZE, (30, 40, 60)),
        "cell-1.png": _png((64, 96), (50, 20, 20)),
        "cell-2.png": _png((64, 96), (20, 50, 20)),
    }
    for file, data in files.items():
        _write_image(private_dir, file, data)
    _write_json(private_dir / "stories" / f"{FILMCLUB_SLUG}.json", _story_json("비공개 조감독", visibility="private"))
    _write_json(
        private_dir / "stories" / f"{MEDIA_BOOK_SLUG}.json", _story_json("칸 있는 작품", media_book=_media_book_json())
    )
    _write_json(
        private_dir / "characters" / f"{DRAFT_CHARACTER_SLUG}.json",
        {**_character_json("쓰다 만 캐릭터", intro=""), "genreId": None, "seedPublished": False},
    )
    _write_json(
        private_dir / "manifest.json",
        {
            "stories": {
                FILMCLUB_SLUG: {"thumbnail": _image_entry("filmclub-thumb.png", crop=THUMBNAIL_CROP)},
                MEDIA_BOOK_SLUG: {
                    "thumbnail": _image_entry("mediabook-thumb.png"),
                    "mediaBookCells": {
                        str(CELL_IDS[0]): _image_entry("cell-1.png", kind="original"),
                        str(CELL_IDS[1]): _image_entry("cell-2.png", kind="original"),
                    },
                },
            },
            "characters": {},
        },
    )
    return files


async def _seed_author(db_session: AsyncSession) -> None:
    """`contents.creator_user_id` / `assets.owner_user_id` FK 를 만족시킬 작가 계정."""
    db_session.add(_make_user(id=SEED_AUTHOR_USER_ID))
    await db_session.flush()


async def _count(db_session: AsyncSession, model: Any, *where: Any) -> int:
    result = await db_session.scalar(select(func.count()).select_from(model).where(*where))
    assert result is not None
    return result


async def _cells(db_session: AsyncSession, version_id: uuid.UUID) -> list[MediaBookCell]:
    return list(
        (
            await db_session.scalars(
                select(MediaBookCell)
                .where(MediaBookCell.content_version_id == version_id)
                .order_by(MediaBookCell.scene_entity_id)
            )
        ).all()
    )


def _local_cell_asset_id(cell_id: uuid.UUID) -> uuid.UUID:
    """시드가 미디어 북 작품의 칸 그림으로 만드는 로컬 원본 자산 id(작품 slug·칸 id 파생)."""
    return seed_uuid("asset", f"{MEDIA_BOOK_SLUG}-cell-{cell_id}", AssetKind.ORIGINAL.value)


def _image_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return image.size


# ---- 묶음 고르기(로더) ----


def _tutorial_slugs() -> tuple[list[str], list[str]]:
    return (
        [story.slug for story in loader.load_all_stories()],
        [character.slug for character in loader.load_all_characters()],
    )


def test_load_seed_lists_only_the_private_bundle_when_it_holds_a_work(private_dir: Path) -> None:
    _write_json(private_dir / "stories" / "private-one.json", _story_json("하나"))
    _write_json(private_dir / "characters" / "private-two.json", _character_json("둘"))

    stories = loader.load_seed_stories(private_dir)
    characters = loader.load_seed_characters(private_dir)

    assert [story.slug for story in stories] == ["private-one"]
    assert [character.slug for character in characters] == ["private-two"]
    # 운영 entity id 를 적어 두면 위치 파생 id 로 덮지 않는다.
    assert stories[0].payload.starting_setups[0].id == _ops_id("하나-setup")


def test_load_seed_lists_no_tutorial_story_when_the_bundle_holds_only_characters(private_dir: Path) -> None:
    """묶음을 쓸지는 스토리·캐릭터를 합쳐 정한다 — 캐릭터만 내보냈다고 튜토리얼 스토리가 섞여 들어오면 안 된다."""
    _write_json(private_dir / "characters" / "private-two.json", _character_json("둘"))

    assert loader.load_seed_stories(private_dir) == []
    assert [character.slug for character in loader.load_seed_characters(private_dir)] == ["private-two"]


@pytest.mark.parametrize("layout", ["missing", "no-work-json"])
def test_load_seed_falls_back_to_the_tutorial_without_a_private_work(private_dir: Path, layout: str) -> None:
    """묶음이 없는 기기(CI·다른 개발 기기)와, 이미지·매니페스트만 있고 작품 JSON 이 없는 묶음은 튜토리얼을 넣는다."""
    if layout == "no-work-json":
        _write_image(private_dir, "orphan.png", _png((8, 8), (10, 10, 10)))
        _write_json(private_dir / "manifest.json", {"stories": {}, "characters": {}})
        (private_dir / "stories").mkdir()

    tutorial_stories, tutorial_characters = _tutorial_slugs()
    assert [story.slug for story in loader.load_seed_stories(private_dir)] == tutorial_stories
    assert [character.slug for character in loader.load_seed_characters(private_dir)] == tutorial_characters


def test_load_seed_reads_the_seed_published_flag(private_dir: Path) -> None:
    _write_json(private_dir / "stories" / "published-story.json", _story_json("발행작"))
    _write_json(
        private_dir / "characters" / "draft-character.json", {**_character_json("초안"), "seedPublished": False}
    )

    [story] = loader.load_seed_stories(private_dir)
    [character] = loader.load_seed_characters(private_dir)

    assert (story.slug, story.published) == ("published-story", True)
    assert (character.slug, character.published) == ("draft-character", False)


def test_load_seed_reads_tutorial_works_as_published(private_dir: Path) -> None:
    """키가 없는 튜토리얼 JSON 은 지금처럼 발행한다."""
    assert all(story.published for story in loader.load_seed_stories(private_dir))
    assert all(character.published for character in loader.load_seed_characters(private_dir))


# ---- 묶음 넣기(seed_dev) ----


async def test_seed_content_files_seeds_only_the_private_bundle(
    db_session: AsyncSession, s3_bucket: None, private_dir: Path
) -> None:
    """묶음이 있으면 튜토리얼은 넣지 않는다. 조감독은 같은 slug 라 같은 id 에 비공개 내용이 들어간다 — 측정·기억 평가
    도구가 그 id 를 기본값으로 쓴다."""
    _write_bundle(private_dir)
    await _seed_author(db_session)

    await seed_dev.seed_content_files(db_session)

    detail = await db_session.get(StoryVersionDetail, story_version_id(FILMCLUB_SLUG))
    assert detail is not None
    assert detail.name == "비공개 조감독"
    filmclub = await db_session.get(Content, story_content_id(FILMCLUB_SLUG))
    assert filmclub is not None
    assert filmclub.visibility == ContentVisibility.PRIVATE
    assert filmclub.current_published_version_id == story_version_id(FILMCLUB_SLUG)
    setup = await db_session.scalar(
        select(StartingSetup).where(StartingSetup.content_version_id == story_version_id(FILMCLUB_SLUG))
    )
    assert setup is not None and setup.entity_id == _ops_id("비공개 조감독-setup")

    assert await db_session.get(Content, character_content_id(FILMCLUB_YUNA_SLUG)) is None, "튜토리얼 캐릭터가 섞였다"

    draft = await db_session.get(Content, character_content_id(DRAFT_CHARACTER_SLUG))
    assert draft is not None
    assert draft.current_published_version_id is None
    assert await _count(db_session, ContentVersion, ContentVersion.content_id == draft.id) == 1


async def test_seed_content_files_builds_thumbnail_variants_from_the_manifest_crop(
    db_session: AsyncSession, s3_bucket: None, private_dir: Path
) -> None:
    """원본은 자르지 않은 채 올리고 크롭은 변형에만 건다(운영 대표 이미지와 같은 규칙). 크롭이 없는 짝은 원본 크기
    그대로다(긴 변이 썸네일 한도보다 작아 줄지 않는다)."""
    files = _write_bundle(private_dir)
    await _seed_author(db_session)

    await seed_dev.seed_content_files(db_session)

    sizes: dict[str, tuple[Any, tuple[int | None, int | None], tuple[int, int]]] = {}
    for slug, file in ((FILMCLUB_SLUG, "filmclub-thumb.png"), (MEDIA_BOOK_SLUG, "mediabook-thumb.png")):
        detail = await db_session.get(StoryVersionDetail, story_version_id(slug))
        assert detail is not None and detail.thumbnail_asset_id is not None, f"{slug}: 대표 이미지가 없다"
        assert detail.thumbnail_asset_id != _ops_id(f"{detail.name}-thumbnail"), f"{slug}: 운영 자산 id 가 남았다"
        asset = await db_session.get(Asset, detail.thumbnail_asset_id)
        assert asset is not None
        assert download_object(asset.storage_key) == files[file], f"{slug}: 원본이 매니페스트 파일이 아니다"
        sizes[slug] = (
            asset.crop,
            (asset.width, asset.height),
            _image_size(download_object(build_thumbnail_key(asset.storage_key))),
        )

    assert sizes[FILMCLUB_SLUG] == (THUMBNAIL_CROP, (100, 50), (100, 50))
    assert sizes[MEDIA_BOOK_SLUG] == (None, THUMBNAIL_SIZE, THUMBNAIL_SIZE)


async def test_seed_content_files_seeds_the_media_book_on_local_assets_with_blurs(
    db_session: AsyncSession, s3_bucket: None, private_dir: Path
) -> None:
    """칸 entity id 는 JSON 그대로여야 프롤로그의 칸 태그가 이어진다. 칸 그림은 작가 소유의 로컬 원본 자산이고,
    보관함이 아직 못 본 칸을 그리는 블러본이 붙는다. 다시 돌려도 자산·칸이 늘지 않는다. 미디어 북 없는 작품은 칸 0."""
    files = _write_bundle(private_dir)
    await _seed_author(db_session)

    await seed_dev.seed_content_files(db_session)

    for version_id in (story_version_id(MEDIA_BOOK_SLUG), story_draft_version_id(MEDIA_BOOK_SLUG)):
        cells = await _cells(db_session, version_id)
        assert sorted(cell.entity_id for cell in cells) == sorted(CELL_IDS)
        for cell in cells:
            file = "cell-1.png" if cell.entity_id == CELL_IDS[0] else "cell-2.png"
            assert cell.image_asset_id == _local_cell_asset_id(cell.entity_id), "칸이 로컬 자산을 가리키지 않는다"
            original = await db_session.get(Asset, cell.image_asset_id)
            assert original is not None
            assert (original.owner_user_id, original.status, original.kind) == (
                SEED_AUTHOR_USER_ID,
                AssetStatus.READY,
                AssetKind.ORIGINAL,
            )
            assert download_object(original.storage_key) == files[file]
            assert cell.blurred_asset_id is not None, "블러본이 없다"
            blurred = await db_session.get(Asset, cell.blurred_asset_id)
            assert blurred is not None
            assert (blurred.status, blurred.kind) == (AssetStatus.READY, AssetKind.BLURRED)
            assert download_object(blurred.storage_key) == generate_blurred_image(files[file]), (
                "블러본이 칸 원본의 블러가 아니다"
            )
    setup = await db_session.scalar(
        select(StartingSetup).where(StartingSetup.content_version_id == story_version_id(MEDIA_BOOK_SLUG))
    )
    assert setup is not None and f"{{{{img::{CELL_IDS[0]}}}}}" in setup.prologue

    assert await _cells(db_session, story_version_id(FILMCLUB_SLUG)) == []

    counts = [await _count(db_session, Asset), await _count(db_session, MediaBookCell)]
    await seed_dev.seed_content_files(db_session)
    assert [await _count(db_session, Asset), await _count(db_session, MediaBookCell)] == counts


async def test_seed_content_files_points_cells_at_local_assets_even_when_the_source_ids_exist_locally(
    db_session: AsyncSession, s3_bucket: None, private_dir: Path
) -> None:
    """JSON 의 자산 id 가 로컬에도 작가 소유의 쓸 수 있는 자산으로 있으면 자동저장의 자산 검사를 통과한다 — 그래도 칸은
    매니페스트 파일로 만든 로컬 자산을 가리켜야 한다. 이 조건이 없으면 바꿔 넣기를 빼먹어도 자산 검사가 먼저 422 로
    막아 칸 단언까지 가지 않는다."""
    _write_bundle(private_dir)
    await _seed_author(db_session)
    for source_asset_id in CELL_SOURCE_ASSET_IDS:
        db_session.add(
            Asset(
                id=source_asset_id,
                owner_user_id=SEED_AUTHOR_USER_ID,
                storage_key=f"assets/test/{source_asset_id}.png",
                kind=AssetKind.ORIGINAL,
                status=AssetStatus.READY,
            )
        )
    await db_session.flush()

    await seed_dev.seed_content_files(db_session)

    for version_id in (story_version_id(MEDIA_BOOK_SLUG), story_draft_version_id(MEDIA_BOOK_SLUG)):
        cells = await _cells(db_session, version_id)
        assert sorted(cell.entity_id for cell in cells) == sorted(CELL_IDS)
        assert {cell.entity_id: cell.image_asset_id for cell in cells} == {
            cell_id: _local_cell_asset_id(cell_id) for cell_id in CELL_IDS
        }


async def _media_book_counts(db_session: AsyncSession, version_id: uuid.UUID) -> tuple[int, int, int]:
    return (
        await _count(db_session, MediaBookPerson, MediaBookPerson.content_version_id == version_id),
        await _count(db_session, MediaBookScene, MediaBookScene.content_version_id == version_id),
        await _count(db_session, MediaBookCell, MediaBookCell.content_version_id == version_id),
    )


async def test_reseeding_a_slug_without_a_media_book_clears_the_previous_media_book(
    db_session: AsyncSession, s3_bucket: None, private_dir: Path
) -> None:
    """같은 로컬 DB 를 묶음 없는 작업트리가 다시 시드하면 같은 slug 가 미디어 북 없는 JSON 으로 덮인다. 자동저장은
    미디어 북 키가 없으면 칸을 건드리지 않으므로, 시드가 비우지 않으면 앞 묶음의 인물·장면·칸이 새 본문에 붙어 남는다.
    처음부터 미디어 북이 없던 작품은 그대로 0 이다."""
    _write_bundle(private_dir)
    await _seed_author(db_session)
    await seed_dev.seed_content_files(db_session)
    assert await _media_book_counts(db_session, story_version_id(MEDIA_BOOK_SLUG)) == (1, 2, 2)

    _write_json(private_dir / "stories" / f"{MEDIA_BOOK_SLUG}.json", _story_json("칸 있는 작품"))
    await seed_dev.seed_content_files(db_session)

    for slug in (MEDIA_BOOK_SLUG, FILMCLUB_SLUG):
        for version_id in (story_version_id(slug), story_draft_version_id(slug)):
            assert await _media_book_counts(db_session, version_id) == (0, 0, 0), f"{slug}: 미디어 북이 남았다"


async def _add_room(db_session: AsyncSession, slug: str) -> None:
    db_session.add(
        ChatRoom(
            user_id=SEED_AUTHOR_USER_ID,
            content_id=story_content_id(slug),
            content_version_id=story_version_id(slug),
            name="합성 대화방 이름",
        )
    )
    await db_session.flush()


def _room_warnings(output: str) -> list[str]:
    return [line for line in output.splitlines() if "대화방" in line]


async def test_seed_warns_when_the_starting_setups_of_a_work_with_rooms_change(
    db_session: AsyncSession, s3_bucket: None, private_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """튜토리얼과 묶음을 바꿔 넣으면 같은 콘텐츠 id 의 시작설정 entity id 가 바뀌고, 그 작품의 로컬 대화방은 사라진
    시작설정·엔딩·스탯을 가리킨다(FK 가 없어 DB 가 막지 않는다). 시드는 작품 slug 와 방 수만 한 줄로 알린다."""
    _write_bundle(private_dir)
    await _seed_author(db_session)
    await seed_dev.seed_content_files(db_session)
    await _add_room(db_session, FILMCLUB_SLUG)
    capsys.readouterr()

    _write_json(private_dir / "stories" / f"{FILMCLUB_SLUG}.json", _story_json("바뀐 조감독", visibility="private"))
    await seed_dev.seed_content_files(db_session)

    [warning] = _room_warnings(capsys.readouterr().out)
    assert FILMCLUB_SLUG in warning and "대화방 1개" in warning
    assert "바뀐 조감독" not in warning and "합성 대화방 이름" not in warning


async def test_seed_stays_quiet_when_the_starting_setups_of_a_work_with_rooms_stay(
    db_session: AsyncSession, s3_bucket: None, private_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_bundle(private_dir)
    await _seed_author(db_session)
    await seed_dev.seed_content_files(db_session)
    await _add_room(db_session, FILMCLUB_SLUG)
    capsys.readouterr()

    await seed_dev.seed_content_files(db_session)

    assert _room_warnings(capsys.readouterr().out) == []


async def test_seed_content_files_crops_the_animated_variants_of_a_moving_thumbnail(
    db_session: AsyncSession, s3_bucket: None, private_dir: Path
) -> None:
    """움직이는 대표 이미지는 화면이 자르지 못해 서버가 매니페스트의 크롭을 모든 프레임에 건다 — 움직이는 변형도 크롭
    크기여야 한다(원본 40×30, 크롭 20×10)."""
    frames = [Image.new("RGB", (40, 30), color) for color in ((40, 20, 20), (20, 20, 40))]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    _write_image(private_dir, "moving.gif", buffer.getvalue())
    _write_json(private_dir / "stories" / "private-moving.json", _story_json("움직이는 작품"))
    _write_json(
        private_dir / "manifest.json",
        {
            "stories": {
                "private-moving": {
                    "thumbnail": _image_entry("moving.gif", crop={"x": 10, "y": 5, "width": 20, "height": 10})
                }
            },
            "characters": {},
        },
    )
    await _seed_author(db_session)

    await seed_dev.seed_content_files(db_session)

    detail = await db_session.get(StoryVersionDetail, story_version_id("private-moving"))
    assert detail is not None and detail.thumbnail_asset_id is not None
    asset = await db_session.get(Asset, detail.thumbnail_asset_id)
    assert asset is not None and asset.animated_variants_ready is True
    assert _image_size(download_object(build_animated_thumbnail_key(asset.storage_key))) == (20, 10)
    assert _image_size(download_object(build_animated_display_key(asset.storage_key))) == (20, 10)
