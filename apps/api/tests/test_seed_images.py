"""`scripts/seed_content/images.py` 의 절차적 목업과 Asset upsert (US-003)."""

import io
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.s3 import download_object
from api.db.models.auth import User
from api.db.models.media import Asset, AssetKind, AssetStatus
from seed_content import images
from seed_content.ids import SEED_AUTHOR_USER_ID

# prd-genre-seed-content.md §7 의 30개 slug — 목업은 이 조합에서 카드가 서로 구분돼야 한다.
GENRE_SLUGS: dict[str, list[str]] = {
    "로맨스": ["romance-3rdloop", "romance-lockedwith", "romance-threeoffering"],
    "판타지": ["fantasy-burnlife", "fantasy-guildkitchen", "fantasy-inkcity"],
    "미스터리·스릴러": ["mystery-elevator", "mystery-onair12", "mystery-teahouse"],
    "SF": ["sf-backup", "sf-longnight", "sf-norespawn"],
    "일상": ["daily-rooftop", "daily-lostandfound", "daily-lastorder"],
    "학원": ["school-relay", "school-notebook", "school-honorcode"],
    "공포": ["horror-sevenrules", "horror-callerid", "horror-yeondeung"],
    "개그·코미디": ["comedy-fakefather", "comedy-demonintern", "comedy-condolence"],
    "무협·액션": ["wuxia-oneform", "wuxia-snowinn", "wuxia-lastguard"],
    "힐링": ["healing-4am", "healing-walkinglog", "healing-seedvillage"],
}
VALUE_CEILING_CHANNEL = 92  # HSV value 0.36 -> 최대 채널


def _colors(png: bytes) -> list[tuple[int, int, int]]:
    """등장하는 색 목록 — 세로 그라데이션이라 명도 단계마다 한 색씩 나온다."""
    with Image.open(io.BytesIO(png)) as image:
        counts = image.convert("RGB").getcolors(maxcolors=1_000_000)
    assert counts is not None
    return [color for _count, color in counts]


def _brightest(png: bytes) -> tuple[int, int, int]:
    """색 관계는 가장 밝은 단계에서 본다 — 어두운 쪽은 반올림으로 채널이 붙는다."""
    return max(_colors(png), key=max)


def _top_channel(png: bytes) -> int:
    """가장 밝은 채널 값 — 목업의 명도 대표값 (그라데이션 상단)."""
    return max(_brightest(png))


async def _seed_author(db_session: AsyncSession) -> None:
    """`assets.owner_user_id` FK 를 만족시킬 작가 계정 (테스트 종료 시 롤백된다)."""
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


def test_mock_thumbnail_is_480x720_and_not_blank() -> None:
    with Image.open(io.BytesIO(images.mock_thumbnail("romance-3rdloop", "로맨스"))) as image:
        assert image.size == (480, 720)
        assert len(image.convert("RGB").getcolors(maxcolors=1_000_000) or []) > 1


def test_mock_thumbnail_is_deterministic() -> None:
    assert images.mock_thumbnail("sf-backup", "SF") == images.mock_thumbnail("sf-backup", "SF")


def test_mock_thumbnail_hue_differs_by_genre() -> None:
    """같은 slug 라도 장르가 다르면 색 계열이 다르다 (채널 대소 관계로 확인)."""
    romance = _brightest(images.mock_thumbnail("slot", "로맨스"))
    sf = _brightest(images.mock_thumbnail("slot", "SF"))
    healing = _brightest(images.mock_thumbnail("slot", "힐링"))

    assert romance[0] == max(romance)  # 로즈 계열 — 빨강이 가장 세다
    assert sf[2] == max(sf)  # 시안 계열 — 파랑이 가장 세다
    assert healing[1] == max(healing)  # 민트 계열 — 초록이 가장 세다


def test_mock_thumbnails_are_distinguishable_within_each_genre() -> None:
    """§7 의 30개 slug 로 실제 카드가 겹치지 않는지 본다.

    명도는 slug 해시라 슬롯끼리 우연히 붙을 수 있어서(사전 조정 불가) 띠 위치·기울기를 함께
    본다 — 한 축이 붙으면 다른 축이 벌어져야 한다. slug 를 추가·변경하면 여기서 잡힌다.
    """
    for genre, slugs in GENRE_SLUGS.items():
        cards = [
            (
                slug,
                _top_channel(images.mock_thumbnail(slug, genre)),
                images.band_center(slug),
                images.band_slant_sign(slug),
            )
            for slug in slugs
        ]
        for index, (slug, brightness, band, slant) in enumerate(cards):
            for other_slug, other_brightness, other_band, other_slant in cards[index + 1 :]:
                assert brightness != other_brightness, f"{genre}: {slug} vs {other_slug} 명도 동일"
                difference = (
                    abs(brightness - other_brightness) / VALUE_CEILING_CHANNEL
                    + abs(band - other_band)
                    + (0.25 if slant != other_slant else 0.0)
                )
                assert difference >= 0.10, f"{genre}: {slug} vs {other_slug} 구분 약함"


def test_mock_thumbnail_stays_in_the_dark_palette() -> None:
    """DESIGN.md: 다크에서 순백 금지. 목업 천장은 HSV value 0.36 = 채널 92."""
    for genre, slugs in GENRE_SLUGS.items():
        for slug in slugs:
            assert _top_channel(images.mock_thumbnail(slug, genre)) <= VALUE_CEILING_CHANNEL


def test_unknown_genre_falls_back_to_near_grayscale() -> None:
    pixel = _brightest(images.mock_thumbnail("romance-3rdloop-scene1", None))
    assert max(pixel) - min(pixel) <= 3


def test_read_image_prefers_the_file_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path)
    (tmp_path / "romance-3rdloop.png").write_bytes(b"real-png-bytes")

    assert images.read_image("romance-3rdloop", "로맨스") == b"real-png-bytes"


def test_read_image_falls_back_to_mock_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path)

    assert images.read_image("romance-3rdloop", "로맨스") == images.mock_thumbnail(
        "romance-3rdloop", "로맨스"
    )
    assert "romance-3rdloop.png" in capsys.readouterr().out


async def test_ensure_asset_uploads_and_upserts_the_same_row_twice(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path)
    await _seed_author(db_session)

    first = await images.ensure_asset(db_session, "sf-backup", AssetKind.THUMBNAIL, "SF")
    await db_session.flush()
    second = await images.ensure_asset(db_session, "sf-backup", AssetKind.THUMBNAIL, "SF")
    await db_session.flush()

    assert first == second
    asset = await db_session.get(Asset, first)
    assert asset is not None
    assert asset.owner_user_id == SEED_AUTHOR_USER_ID
    assert asset.kind == AssetKind.THUMBNAIL
    assert asset.status == AssetStatus.READY
    assert str(first) in asset.storage_key
    assert await db_session.scalar(select(func.count()).select_from(Asset)) == 1
    assert download_object(asset.storage_key) == images.mock_thumbnail("sf-backup", "SF")


async def test_ensure_asset_derives_distinct_ids_per_kind(
    db_session: AsyncSession, s3_bucket: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path)
    await _seed_author(db_session)

    original = await images.ensure_asset(db_session, "scene1", AssetKind.ORIGINAL)
    blurred = await images.ensure_asset(db_session, "scene1", AssetKind.BLURRED, data=b"blurred")
    await db_session.flush()

    assert original != blurred
    blurred_asset = await db_session.get(Asset, blurred)
    assert blurred_asset is not None
    assert download_object(blurred_asset.storage_key) == b"blurred"


async def test_ensure_asset_survives_a_dead_object_store(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """moto 가 꺼져 있어도 경고 한 줄만 남기고 행은 들어간다."""
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path)

    def _explode(key: str, body: bytes, content_type: str) -> None:
        raise ConnectionError("moto is down")

    monkeypatch.setattr(images, "upload_object", _explode)
    await _seed_author(db_session)

    asset_id = await images.ensure_asset(db_session, "daily-rooftop", AssetKind.THUMBNAIL, "일상")
    await db_session.flush()

    assert isinstance(asset_id, uuid.UUID)
    assert await db_session.get(Asset, asset_id) is not None
    assert "업로드 건너뜀" in capsys.readouterr().out
