import asyncio
import io
import threading
import uuid
from datetime import timezone
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

import boto3
import httpx
import pytest
from botocore.exceptions import ClientError
from PIL import Image
from redis.exceptions import RedisError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets import image_processing
from api.assets import router as assets_router
from api.assets.schemas import UPLOAD_SIZE_LIMIT_BYTES, AssetPurpose
from api.core import rate_limit_gate
from api.core.config import settings
from api.core.s3 import build_display_key, build_thumbnail_key, delete_object, download_object, upload_object
from api.db.models.media import Asset, AssetStatus
from factories import (
    _assert_blocked,
    _login_as,
    _make_user,
    _noting_open_transactions,
    _open_transaction_probe,
    _put_via_presigned_url,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def _png_bytes(width: int = 64, height: int = 64) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 40, 200)).save(output, format="PNG")
    return output.getvalue()


async def test_presigned_upload_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    assert resp.status_code == 401


def _s3() -> "S3Client":
    return boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)


def _signed_key(upload_url: str) -> str:
    """서명 URL 이 가리키는 객체 키. 테스트 저장소는 경로식 주소(`/{bucket}/{key}`)라 버킷 뒤가 키다."""
    path = unquote(urlsplit(upload_url).path)
    return path.split(f"/{settings.s3_bucket_name}/", 1)[1]


def _object_bytes(key: str) -> bytes | None:
    try:
        return _s3().get_object(Bucket=settings.s3_bucket_name, Key=key)["Body"].read()
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise


async def _presign(db_client: httpx.AsyncClient, purpose: str = "profile-image") -> tuple[str, str]:
    resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": purpose}
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["assetId"], body["uploadUrl"]


async def _logged_in_user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)


async def test_presigned_upload_signs_a_temporary_key_and_creates_pending_asset(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """브라우저가 받는 URL 은 최종 키가 아니라 임시 키를 가리킨다 — 최종 키에 서명하면 업로드 완료 뒤에도
    같은 URL 로 검사가 끝난 객체를 덮을 수 있다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["expiresAt"]

    asset = await db_session.get(Asset, uuid.UUID(body["assetId"]))
    assert asset is not None
    assert asset.owner_user_id == user.id
    assert asset.status == AssetStatus.PENDING
    assert asset.storage_key == f"assets/profile-image/{asset.id}.png"
    assert _signed_key(body["uploadUrl"]) == f"uploads/tmp/profile-image/{asset.id}.png"


async def test_complete_writes_the_checked_bytes_to_the_final_key_and_removes_the_temporary_object(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    uploaded = _png_bytes()
    _put_via_presigned_url(upload_url, uploaded)
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    assert _object_bytes(asset.storage_key) is None

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert complete_resp.status_code == 200
    assert complete_resp.json() == {"assetId": asset_id, "status": "ready"}
    await db_session.refresh(asset)
    assert asset.status == AssetStatus.READY
    final = _s3().get_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key)
    assert final["Body"].read() == uploaded
    assert final["ContentType"] == "image/png"
    thumbnail_bytes = _object_bytes(build_thumbnail_key(asset.storage_key))
    assert thumbnail_bytes is not None
    with Image.open(io.BytesIO(thumbnail_bytes)) as thumbnail:
        assert thumbnail.format == "WEBP"
    assert _object_bytes(_signed_key(upload_url)) is None


async def test_complete_stores_a_webp_display_variant_shrunk_to_a_1024_long_edge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """상세 화면이 원본 대신 받을 표시용 변형도 READY 가 되기 전에 올라가 있어야 한다 — 응답은 존재 확인 없이
    키를 유도한다."""
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client, purpose="content-thumbnail")
    _put_via_presigned_url(upload_url, _png_bytes(1536, 2048))

    assert (await db_client.post(f"/assets/{asset_id}/complete")).status_code == 200

    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    display_bytes = _object_bytes(build_display_key(asset.storage_key))
    assert display_bytes is not None
    with Image.open(io.BytesIO(display_bytes)) as display:
        assert (display.format, display.size) == ("WEBP", (768, 1024))
    # 변형은 원본의 타입(`image/png`)이 아니라 실제 바이트 형식으로 저장돼야 한다 — 2단계에서 상세 히어로·링크
    # 미리보기가 이 객체를 그대로 받는다.
    for variant_key in (build_thumbnail_key(asset.storage_key), build_display_key(asset.storage_key)):
        assert _s3().head_object(Bucket=settings.s3_bucket_name, Key=variant_key)["ContentType"] == "image/webp"


async def test_complete_stores_the_type_of_the_checked_image_even_when_the_key_has_no_extension(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    s3_bucket: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영 이미지에는 시스템 MIME 표가 없어 WebP 에 확장자를 못 붙이고 키에서 타입을 되살릴 수도 없다. 그래도 최종
    객체는 검사한 바이트의 실제 형식으로 저장돼야 한다 — 새 탭에서 원본을 열면 다운로드가 아니라 그림이 떠야 한다."""
    monkeypatch.setattr("mimetypes.guess_extension", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mimetypes.guess_type", lambda *_args, **_kwargs: (None, None))
    await _logged_in_user(db_client, db_session)
    resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/webp", "purpose": "situational-image"}
    )
    assert resp.status_code == 201
    asset_id, upload_url = resp.json()["assetId"], resp.json()["uploadUrl"]
    output = io.BytesIO()
    Image.new("RGB", (64, 64), color=(120, 40, 200)).save(output, format="WEBP")
    _put_via_presigned_url(upload_url, output.getvalue(), content_type="image/webp")

    assert (await db_client.post(f"/assets/{asset_id}/complete")).status_code == 200

    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    assert asset.storage_key == f"assets/situational-image/{asset_id}"
    final = _s3().head_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key)
    assert final["ContentType"] == "image/webp"


async def test_reusing_the_upload_url_after_complete_cannot_change_the_stored_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """완료 뒤 남은 서명 시간 동안 같은 URL 로 다른 그림을 올리고 complete 를 다시 불러도, 발행 심사가 본
    원본과 축소본은 그대로다. 두 번째 complete 는 저장소를 건드리지 않아 임시 객체도 그대로 남는다."""
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    first = _png_bytes(64, 64)
    _put_via_presigned_url(upload_url, first)
    assert (await db_client.post(f"/assets/{asset_id}/complete")).status_code == 200
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    thumbnail_key = build_thumbnail_key(asset.storage_key)
    thumbnail_before = _object_bytes(thumbnail_key)

    swapped = _png_bytes(300, 200)
    _put_via_presigned_url(upload_url, swapped)
    second_resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert second_resp.status_code == 200
    assert second_resp.json() == {"assetId": asset_id, "status": "ready"}
    assert _object_bytes(asset.storage_key) == first
    assert _object_bytes(thumbnail_key) == thumbnail_before
    assert _object_bytes(_signed_key(upload_url)) == swapped
    await db_session.refresh(asset)
    assert (asset.width, asset.height) == (64, 64)


async def test_complete_succeeds_even_if_the_temporary_object_cannot_be_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """임시 객체 삭제는 뒷정리다 — 최종 키·축소본·READY 는 이미 끝났으니 업로드를 실패로 돌리지 않는다."""
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, _png_bytes())

    def _failing_delete(_key: str) -> None:
        raise ClientError({"Error": {"Code": "InternalError", "Message": "boom"}}, "DeleteObject")

    monkeypatch.setattr("api.assets.router.delete_object", _failing_delete)

    resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert resp.status_code == 200
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    await db_session.refresh(asset)
    assert asset.status == AssetStatus.READY


async def test_complete_ignores_an_object_put_straight_to_the_final_key(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """배포 직전에 받은 옛 URL 은 최종 키로 올린다. 그 업로드는 받아 주지 않고 409 로 끝난다 — 사용자가 다시
    고르면 새 URL 로 올라간다."""
    await _logged_in_user(db_client, db_session)
    asset_id, _upload_url = await _presign(db_client)
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    _s3().put_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key, Body=_png_bytes())

    resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert resp.status_code == 409
    await db_session.refresh(asset)
    assert asset.status == AssetStatus.PENDING


async def test_complete_rejects_undecodable_image_and_cleans_up(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    storage_key = asset.storage_key
    _put_via_presigned_url(upload_url, b"not-an-image")

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 400
    assert complete_resp.json()["detail"] == "Uploaded object is not a decodable image"

    assert _object_bytes(_signed_key(upload_url)) is None
    assert _object_bytes(storage_key) is None
    assert await db_session.get(Asset, uuid.UUID(asset_id)) is None


async def test_complete_rejects_oversized_object_and_cleans_up(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    storage_key = asset.storage_key
    max_bytes = UPLOAD_SIZE_LIMIT_BYTES[AssetPurpose.PROFILE_IMAGE]
    _put_via_presigned_url(upload_url, b"x" * (max_bytes + 1))

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 400
    assert complete_resp.json()["detail"] == {"maxBytes": max_bytes, "actualBytes": max_bytes + 1}

    assert _object_bytes(_signed_key(upload_url)) is None
    assert _object_bytes(storage_key) is None
    assert await db_session.get(Asset, uuid.UUID(asset_id)) is None


async def test_complete_measures_the_downloaded_bytes_not_the_size_seen_beforehand(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """크기를 먼저 본 뒤 내려받기 전에 같은 URL 로 큰 객체를 다시 올릴 수 있다. 그 사이를 흉내 내려고 먼저 본
    크기를 1바이트로 바꿔 둔다 — 상한은 실제로 내려받은 바이트에 걸려야 한다."""
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    max_bytes = UPLOAD_SIZE_LIMIT_BYTES[AssetPurpose.PROFILE_IMAGE]
    _put_via_presigned_url(upload_url, b"x" * (max_bytes + 1))
    monkeypatch.setattr("api.assets.router.get_object_size", lambda _key: 1)

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert complete_resp.status_code == 400
    assert complete_resp.json()["detail"] == {"maxBytes": max_bytes, "actualBytes": max_bytes + 1}
    assert await db_session.get(Asset, uuid.UUID(asset_id)) is None


async def test_complete_before_upload_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    presign_resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    asset_id = presign_resp.json()["assetId"]

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 409


async def test_complete_rejects_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add(owner)
    db_session.add(other)
    await db_session.flush()

    await _login_as(db_client, owner.id)
    presign_resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )
    asset_id = presign_resp.json()["assetId"]

    await _login_as(db_client, other.id)
    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")
    assert complete_resp.status_code == 403


async def test_complete_unknown_asset_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/assets/{uuid.uuid4()}/complete")
    assert resp.status_code == 404


async def test_complete_upload_records_image_dimensions(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """화면은 저장된 너비·높이로 이미지 자리를 미리 잡는다. 가로·세로가 다른 원본이라 뒤바뀌어도 걸린다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    asset_id, upload_url = await _presign(db_client, "situational-image")
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    _put_via_presigned_url(upload_url, _png_bytes(300, 400))

    resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert resp.status_code == 200
    await db_session.refresh(asset)
    assert (asset.width, asset.height) == (300, 400)


def _bilevel_png_bytes(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("1", (width, height)).save(output, format="PNG")
    return output.getvalue()


async def test_complete_rejects_image_over_pixel_limit_and_cleans_up(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """바이트는 작고 픽셀은 많은 그림은 풀기 전에 거부하고, 바이트 상한처럼 원인을 알리며 업로드를 치운다."""
    monkeypatch.setattr(image_processing, "MAX_DECODE_PIXELS", 40 * 30 - 1)
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    asset = await db_session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    storage_key = asset.storage_key
    _put_via_presigned_url(upload_url, _bilevel_png_bytes(40, 30))

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert complete_resp.status_code == 400
    assert complete_resp.json()["detail"] == {"maxPixels": 40 * 30 - 1, "actualPixels": 40 * 30}
    assert _object_bytes(_signed_key(upload_url)) is None
    assert _object_bytes(storage_key) is None
    assert await db_session.get(Asset, uuid.UUID(asset_id)) is None


async def test_complete_rejects_pillow_decompression_bomb_and_cleans_up(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pillow 가 스스로 거부하는 폭탄(약 1.8억 픽셀 초과)도 500 과 PENDING 행 잔존이 아니라 정리 후 400 이다. 작은
    그림으로 흉내 내려고 Pillow 의 상한을 낮춘다."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, _bilevel_png_bytes(20, 20))

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert complete_resp.status_code == 400
    assert complete_resp.json()["detail"] == {"maxPixels": image_processing.MAX_DECODE_PIXELS, "actualPixels": None}
    assert _object_bytes(_signed_key(upload_url)) is None
    assert await db_session.get(Asset, uuid.UUID(asset_id)) is None


async def test_complete_runs_variant_generation_through_the_image_work_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """변형 생성(디코드)은 프로세스 전역 이미지 작업 한도를 거친다 — 동시 업로드 수만큼 디코드 메모리가 곱해지지 않게."""
    calls: list[str] = []
    real = image_processing.run_image_work

    async def spy(func: object, *args: object) -> object:
        calls.append(getattr(func, "__name__", ""))
        return await real(func, *args)  # type: ignore[arg-type]

    monkeypatch.setattr("api.assets.router.run_image_work", spy)
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, _png_bytes())

    complete_resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert complete_resp.status_code == 200
    assert calls == ["generate_variants"]


async def test_presigned_upload_returns_429_with_upload_window_after_hourly_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, s3_bucket: None
) -> None:
    """업로드 URL 발급은 사용자당 시간당 상한이 있다. 넘으면 다른 429 와 같은 모양에 `window` 로 기능을 가르고,
    PENDING 자산 행도 만들지 않는다."""
    monkeypatch.setattr(rate_limit_gate, "UPLOAD_LIMIT", 1)
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    await _presign(db_client)

    resp = await db_client.post(
        "/assets/presigned-upload", json={"contentType": "image/png", "purpose": "profile-image"}
    )

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert (detail["code"], detail["window"]) == ("USER_LIMIT", "upload")
    assert 0 < detail["retryAfterSeconds"] <= rate_limit_gate.HOURLY_WINDOW_SECONDS
    assets = await db_session.scalar(select(func.count()).select_from(Asset).where(Asset.owner_user_id == user.id))
    assert assets == 1


async def test_presigned_upload_limit_skips_exempt_users(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, s3_bucket: None
) -> None:
    """예외 계정(시드 작가 일괄 업로드)은 채팅·이미지와 같은 판정으로 업로드 상한도 건너뛴다."""
    monkeypatch.setattr(rate_limit_gate, "UPLOAD_LIMIT", 0)
    user = _make_user(rate_limit_exempt=True)
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    await _presign(db_client)


# ── 업로드 완료가 저장소·디코드를 기다리는 동안 DB 트랜잭션을 쥐지 않는다 ──────────────────────────────
#
# 업로드 완료는 저장소 HEAD·GET·PUT 셋과 이미지 디코드(프로세스 전역 한도를 기다릴 수 있다)를 거친다. 그동안 자산 행을
# `FOR UPDATE` 로 쥐고 있으면 커넥션 하나를 통째로 잡는다. 그래서 같은 자산의 완료가 겹치는 것은 Redis 락으로 막고,
# 상태는 "아직 PENDING 일 때만" 바꾸는 조건부 쓰기로 바꾼다.


async def test_complete_holds_no_transaction_while_talking_to_storage_or_decoding(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, _png_bytes())
    await db_session.commit()
    seen: list[tuple[str, int]] = []
    with _open_transaction_probe() as open_sessions:
        for name in ("get_object_size", "download_object", "generate_variants", "upload_object", "delete_object"):
            monkeypatch.setattr(
                assets_router, name, _noting_open_transactions(open_sessions, seen, name, getattr(assets_router, name))
            )
        resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert resp.status_code == 200, resp.text
    assert [name for name, _ in seen] == [
        "get_object_size",
        "download_object",
        "generate_variants",
        "upload_object",
        "upload_object",
        "upload_object",
        "delete_object",
    ]
    assert [(name, count) for name, count in seen if count != 0] == []


async def test_failed_complete_holds_no_transaction_while_deleting_the_upload(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, b"not-an-image")
    await db_session.commit()
    seen: list[tuple[str, int]] = []
    with _open_transaction_probe() as open_sessions:
        monkeypatch.setattr(
            assets_router, "delete_object", _noting_open_transactions(open_sessions, seen, "delete", delete_object)
        )
        resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert resp.status_code == 400, resp.text
    assert seen == [("delete", 0)]
    assert await db_session.get(Asset, uuid.UUID(asset_id)) is None


@pytest.mark.usefixtures("committing_request_session")
async def test_overlapping_completes_of_one_upload_process_it_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 같은 자산의 완료 둘이 겹치면 뒤의 요청은 앞의 요청이 끝날 때까지 기다렸다가
    (`_assert_blocked`) 저장소를 건드리지 않고 같은 READY 응답을 받아야 한다. 저장소에서 두 번 내려받거나 기다리지 않고
    끝나면 실패다 — 둘이 각자 내려받으면 그사이 같은 서명 URL 로 바꿔 올린 바이트가 원본·축소본에 섞일 수 있다."""
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, _png_bytes())
    downloads: list[str] = []
    entered, release = threading.Event(), threading.Event()

    def gated_download(key: str) -> bytes:
        downloads.append(key)
        if len(downloads) == 1:
            entered.set()
            release.wait(10)
        return download_object(key)

    monkeypatch.setattr(assets_router, "download_object", gated_download)
    first = asyncio.create_task(db_client.post(f"/assets/{asset_id}/complete"))
    assert await asyncio.to_thread(entered.wait, 10)
    second = asyncio.create_task(db_client.post(f"/assets/{asset_id}/complete"))
    try:
        await _assert_blocked(second, block_seconds=1.0)
    finally:
        release.set()
    first_resp, second_resp = await first, await second

    expected = {"assetId": asset_id, "status": "ready"}
    assert (first_resp.status_code, first_resp.json()) == (200, expected)
    assert (second_resp.status_code, second_resp.json()) == (200, expected)
    assert len(downloads) == 1


@pytest.mark.usefixtures("committing_request_session")
async def test_complete_keeps_the_result_of_a_completion_that_finished_meanwhile(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준: 락이 만료돼 다른 완료가 먼저 READY 로 바꿨다면(여기서는 저장소에 올리는 사이 행을 직접 READY 로
    바꿔 흉내 낸다) 늦은 쪽은 그 결과를 덮어쓰지 않고 READY 응답만 돌려준다 — 먼저 끝난 쪽이 적은 크기가 남아야 한다."""
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, _png_bytes(64, 64))

    async def finish_elsewhere() -> None:
        await db_session.execute(
            update(Asset).where(Asset.id == uuid.UUID(asset_id)).values(status=AssetStatus.READY, width=7, height=9)
        )
        await db_session.commit()

    loop = asyncio.get_running_loop()
    finished: list[bool] = []

    def upload_after_someone_else_finished(key: str, body: bytes, content_type: str) -> None:
        if not finished:
            asyncio.run_coroutine_threadsafe(finish_elsewhere(), loop).result(10)
            finished.append(True)
        upload_object(key, body, content_type)

    monkeypatch.setattr(assets_router, "upload_object", upload_after_someone_else_finished)
    resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert (resp.status_code, resp.json()) == (200, {"assetId": asset_id, "status": "ready"})
    row = (
        await db_session.execute(
            select(Asset.status, Asset.width, Asset.height).where(Asset.id == uuid.UUID(asset_id))
        )
    ).one()
    assert tuple(row) == (AssetStatus.READY, 7, 9)


@pytest.mark.usefixtures("committing_request_session")
async def test_failed_complete_does_not_delete_an_upload_that_finished_meanwhile(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준: 검사에 떨어진 늦은 요청이 그사이 다른 완료가 READY 로 만든 자산 행을 지우면 실패다(그 그림을 쓰는
    화면이 사라진 행을 가리킨다). 늦은 요청 자신은 자기가 받은 바이트에 대한 400 을 그대로 돌려준다."""
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, b"not-an-image")

    async def finish_elsewhere() -> None:
        await db_session.execute(
            update(Asset).where(Asset.id == uuid.UUID(asset_id)).values(status=AssetStatus.READY, width=7, height=9)
        )
        await db_session.commit()

    loop = asyncio.get_running_loop()

    def download_then_someone_else_finishes(key: str) -> bytes:
        body = download_object(key)
        asyncio.run_coroutine_threadsafe(finish_elsewhere(), loop).result(10)
        return body

    monkeypatch.setattr(assets_router, "download_object", download_then_someone_else_finishes)
    resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert resp.status_code == 400, resp.text
    status_now = await db_session.scalar(select(Asset.status).where(Asset.id == uuid.UUID(asset_id)))
    assert status_now == AssetStatus.READY


async def test_complete_is_refused_when_the_completion_lock_cannot_be_reached(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redis 장애 때는 완료를 거절한다(503) — 락 없이 진행하면 겹친 완료가 원본과 축소본을 서로 다른 바이트로 만들 수
    있고, 발행 심사는 축소본을 본다. 자산은 PENDING 그대로라 장애가 풀린 뒤 다시 완료할 수 있다."""
    await _logged_in_user(db_client, db_session)
    asset_id, upload_url = await _presign(db_client)
    _put_via_presigned_url(upload_url, _png_bytes())

    async def redis_down(*_args: object, **_kwargs: object) -> object:
        raise RedisError("down")

    monkeypatch.setattr(assets_router, "wait_for_lock", redis_down)
    resp = await db_client.post(f"/assets/{asset_id}/complete")

    assert resp.status_code == 503, resp.text
    status_now = await db_session.scalar(select(Asset.status).where(Asset.id == uuid.UUID(asset_id)))
    assert status_now == AssetStatus.PENDING
