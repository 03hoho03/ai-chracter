"""`scripts/backfill_thumbnails.py` — READY 자산에 빠진 변형(`_thumb.webp`·`_display.webp`)을 채운다."""

import io
import uuid
from datetime import UTC, datetime

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

import backfill_thumbnails as backfill
from api.core.config import settings
from api.core.s3 import (
    build_display_key,
    build_thumbnail_key,
    build_variant_keys,
    download_object,
    get_object_size,
    s3_client,
    upload_object,
)
from api.db.models.media import Asset, AssetKind, AssetStatus
from factories import _make_user


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


def _exists(key: str) -> bool:
    return get_object_size(key) is not None


async def _asset(
    db_session: AsyncSession,
    *,
    status: AssetStatus = AssetStatus.READY,
    original: tuple[int, int] | None = (2048, 1536),
    variants: tuple[str, ...] = (),
) -> Asset:
    """`original` 은 저장소에 올릴 원본 크기(None 이면 올리지 않는다), `variants` 는 미리 올려 둘 변형 키 유도 이름
    (`"thumb"`·`"display"`)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/test/{uuid.uuid4()}.png",
        kind=AssetKind.GENERATED,
        status=status,
    )
    db_session.add(asset)
    await db_session.flush()
    if original is not None:
        upload_object(asset.storage_key, _png(*original), "image/png")
    builders = {"thumb": build_thumbnail_key, "display": build_display_key}
    for name in variants:
        upload_object(builders[name](asset.storage_key), b"existing-variant", "image/webp")
    return asset


async def test_backfill_adds_missing_variants_to_ready_assets_only(
    db_session: AsyncSession, s3_bucket: None
) -> None:
    bare = await _asset(db_session)
    pending = await _asset(db_session, status=AssetStatus.PENDING)

    assert await backfill.run(db_session, dry_run=False) == 0

    with Image.open(io.BytesIO(download_object(build_display_key(bare.storage_key)))) as display:
        assert (display.format, display.size) == ("WEBP", (1024, 768))
    with Image.open(io.BytesIO(download_object(build_thumbnail_key(bare.storage_key)))) as thumbnail:
        assert (thumbnail.format, thumbnail.size) == ("WEBP", (512, 384))
    assert not any(_exists(key) for key in build_variant_keys(pending.storage_key))


async def test_backfill_keeps_an_existing_variant_and_adds_only_the_missing_one(
    db_session: AsyncSession, s3_bucket: None
) -> None:
    """썸네일만 있는 자산(표시용 변형이 생기기 전에 READY 가 된 운영 재고 전부)은 표시용만 더한다."""
    thumbnail_only = await _asset(db_session, variants=("thumb",))

    assert await backfill.run(db_session, dry_run=False) == 0

    assert download_object(build_thumbnail_key(thumbnail_only.storage_key)) == b"existing-variant"
    assert _exists(build_display_key(thumbnail_only.storage_key))


async def test_backfill_skips_assets_that_already_have_every_variant(
    db_session: AsyncSession, s3_bucket: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """변형이 다 있으면 원본을 내려받지 않는다 — 원본이 없어도 실패로 세지 않는 것으로 확인한다."""
    complete = await _asset(db_session, original=None, variants=("thumb", "display"))

    assert await backfill.run(db_session, dry_run=False) == 0

    assert download_object(build_display_key(complete.storage_key)) == b"existing-variant"
    assert "생성 대상 0건, 원본 없음 0건, 이미 있음 1건" in capsys.readouterr().out


async def test_backfill_dry_run_counts_targets_and_writes_nothing(
    db_session: AsyncSession, s3_bucket: None, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = await _asset(db_session)
    await _asset(db_session, variants=("thumb",))
    await _asset(db_session, variants=("thumb", "display"))

    assert await backfill.run(db_session, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "READY 자산 3건 — 생성 대상 2건, 원본 없음 0건, 이미 있음 1건" in out
    assert "_display.webp 2건" in out
    assert "_thumb.webp 1건" in out
    assert not any(_exists(key) for key in build_variant_keys(bare.storage_key))


async def test_backfill_collects_failures_and_keeps_going(
    db_session: AsyncSession, s3_bucket: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """변형을 못 만드는 자산(원본이 그림이 아님)은 건너뛰고 나머지를 채운다. 다시 돌려 볼 실패가 있으면 종료 코드
    1 이다 — 원본이 없는 자산이 함께 있어도 1 이 앞선다. 실패할 자산이 먼저 처리되도록 만든 시각을 앞당긴다 —
    같은 트랜잭션의 행은 만든 시각이 같아 순서가 정해지지 않는다."""
    broken = await _asset(db_session, original=None)
    upload_object(broken.storage_key, b"not-an-image", "image/png")
    broken.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    await _asset(db_session, original=None)
    found = await _asset(db_session)
    await db_session.flush()

    assert await backfill.run(db_session, dry_run=False) == 1

    assert all(_exists(key) for key in build_variant_keys(found.storage_key))
    assert broken.storage_key in capsys.readouterr().out


async def test_backfill_reports_assets_without_an_original_separately_with_their_own_exit_code(
    db_session: AsyncSession, s3_bucket: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """원본이 영구히 없는 자산은 다시 돌려도 고쳐지지 않는다 — 일시 오류(종료 코드 1)와 섞이면 운영자가 끝없이 재실행하게
    된다. 따로 세어 목록으로 보이고, 남은 것이 그것뿐이면 종료 코드 2 다. dry-run 도 같은 목록을 보인다."""
    lost = await _asset(db_session, original=None)
    found = await _asset(db_session)

    assert await backfill.run(db_session, dry_run=True) == 0
    dry_out = capsys.readouterr().out
    assert "생성 대상 1건, 원본 없음 1건, 이미 있음 0건" in dry_out
    assert lost.storage_key in dry_out

    assert await backfill.run(db_session, dry_run=False) == backfill.EXIT_ONLY_MISSING_ORIGINALS == 2

    assert all(_exists(key) for key in build_variant_keys(found.storage_key))
    assert not any(_exists(key) for key in build_variant_keys(lost.storage_key))
    assert lost.storage_key in capsys.readouterr().out


async def test_backfill_ends_its_database_transaction_before_touching_storage(
    db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """저장소 작업은 운영에서 길다 — 그동안 트랜잭션을 열어 두면 `assets` 잠금이 남아, 겹친 배포의 마이그레이션과
    그 뒤의 `assets` 조회가 함께 막힌다."""
    await _asset(db_session)
    in_transaction_during_storage: list[bool] = []

    def recording_size(key: str) -> int | None:
        in_transaction_during_storage.append(db_session.in_transaction())
        return get_object_size(key)

    def recording_download(key: str) -> bytes:
        in_transaction_during_storage.append(db_session.in_transaction())
        return download_object(key)

    monkeypatch.setattr(backfill, "get_object_size", recording_size)
    monkeypatch.setattr(backfill, "download_object", recording_download)

    assert await backfill.run(db_session, dry_run=False) == 0

    assert in_transaction_during_storage
    assert not any(in_transaction_during_storage)


async def test_backfill_uploads_variants_as_webp(db_session: AsyncSession, s3_bucket: None) -> None:
    """원본의 타입(`image/png`)으로 올리면 브라우저·링크 미리보기가 WebP 바이트를 PNG 로 받는다."""
    bare = await _asset(db_session)

    assert await backfill.run(db_session, dry_run=False) == 0

    for key in build_variant_keys(bare.storage_key):
        assert s3_client.head_object(Bucket=settings.s3_bucket_name, Key=key)["ContentType"] == "image/webp"
