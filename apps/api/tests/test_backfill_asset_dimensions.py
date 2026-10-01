"""`scripts/backfill_asset_dimensions.py` — 너비·높이 컬럼이 생기기 전에 READY 가 된 자산에 크기를 채운다."""

import io
import uuid

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

import backfill_asset_dimensions as backfill
from api.core.s3 import upload_object
from api.db.models.media import Asset, AssetKind, AssetStatus
from factories import _make_user


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


async def _asset(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    kind: AssetKind = AssetKind.GENERATED,
    status: AssetStatus = AssetStatus.READY,
    size: tuple[int, int] | None = None,
    stored: tuple[int, int] | None = None,
) -> Asset:
    """`size` 는 저장소에 올리는 그림의 크기(None 이면 올리지 않는다), `stored` 는 행에 이미 적힌 크기."""
    asset = Asset(
        owner_user_id=owner_id,
        storage_key=f"assets/test/{uuid.uuid4()}.png",
        kind=kind,
        status=status,
        width=stored[0] if stored else None,
        height=stored[1] if stored else None,
    )
    db_session.add(asset)
    await db_session.flush()
    if size is not None:
        upload_object(asset.storage_key, _png(*size), "image/png")
    return asset


async def _owner(db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return user.id


async def _dims(db_session: AsyncSession, asset: Asset) -> tuple[int | None, int | None]:
    await db_session.refresh(asset)
    return asset.width, asset.height


async def test_backfill_fills_only_ready_assets_without_dimensions(
    db_session: AsyncSession, s3_bucket: None
) -> None:
    owner = await _owner(db_session)
    missing = await _asset(db_session, owner, size=(30, 20))
    blurred = await _asset(db_session, owner, kind=AssetKind.BLURRED, size=(40, 50))
    measured = await _asset(db_session, owner, size=(30, 20), stored=(1, 1))
    pending = await _asset(db_session, owner, status=AssetStatus.PENDING, size=(30, 20))

    assert await backfill.run(db_session, dry_run=False, force=False) == 0

    assert await _dims(db_session, missing) == (30, 20)
    assert await _dims(db_session, blurred) == (40, 50)
    assert await _dims(db_session, measured) == (1, 1)
    assert await _dims(db_session, pending) == (None, None)


async def test_backfill_dry_run_counts_targets_by_kind_and_writes_nothing(
    db_session: AsyncSession, s3_bucket: None, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = await _owner(db_session)
    generated = await _asset(db_session, owner, size=(30, 20))
    await _asset(db_session, owner, size=(30, 20))
    await _asset(db_session, owner, kind=AssetKind.THUMBNAIL, size=(30, 20))
    await _asset(db_session, owner, size=(30, 20), stored=(30, 20))

    assert await backfill.run(db_session, dry_run=True, force=False) == 0

    out = capsys.readouterr().out
    assert "generated 2" in out
    assert "thumbnail 1" in out
    assert "original" not in out
    assert await _dims(db_session, generated) == (None, None)


async def test_backfill_force_remeasures_assets_that_already_have_dimensions(
    db_session: AsyncSession, s3_bucket: None
) -> None:
    """시드 이미지 바이트만 갈아 끼우는 스크립트 뒤에는 저장된 크기가 낡는다 — 그때 다시 잰다."""
    owner = await _owner(db_session)
    stale = await _asset(db_session, owner, size=(30, 20), stored=(480, 720))

    assert await backfill.run(db_session, dry_run=False, force=True) == 0

    assert await _dims(db_session, stale) == (30, 20)


async def test_backfill_collects_failures_and_keeps_going(
    db_session: AsyncSession, s3_bucket: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """원본이 사라진 자산은 크기를 모르는 채로 두고(화면은 고정 비율 칸으로 그린다) 나머지는 채운다.
    실패가 있으면 종료 코드 1 로 알린다."""
    owner = await _owner(db_session)
    lost = await _asset(db_session, owner, size=None)
    found = await _asset(db_session, owner, size=(30, 20))

    assert await backfill.run(db_session, dry_run=False, force=False) == 1

    assert await _dims(db_session, lost) == (None, None)
    assert await _dims(db_session, found) == (30, 20)
    assert lost.storage_key in capsys.readouterr().out
