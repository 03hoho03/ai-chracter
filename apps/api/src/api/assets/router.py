import logging
import uuid
from collections.abc import Sequence

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.assets.blur import blurred_asset_row, upload_blurred_copy
from api.assets.image_processing import (
    THUMBNAIL_CONTENT_TYPE,
    ImageTooLargeError,
    generate_variants,
    read_image_content_type,
    read_image_size,
    run_image_work,
)
from api.assets.schemas import (
    UPLOAD_SIZE_LIMIT_BYTES,
    AssetCompleteResponse,
    AssetPurpose,
    GeneratedImageItem,
    GeneratedImageUsage,
    GeneratedImageUsageField,
    PresignedUploadRequest,
    PresignedUploadResponse,
    RegisterSituationalImageRequest,
    SituationalImageResponse,
)
from api.core.rate_limit_gate import enforce_upload_rate_limit
from api.core.redis import redis_client
from api.core.redis_lock import release_lock, wait_for_lock
from api.core.s3 import (
    build_object_key,
    build_thumbnail_key,
    build_upload_key,
    build_variant_keys,
    delete_object,
    download_object,
    generate_presigned_get_url,
    generate_presigned_put_url,
    get_object_size,
    upload_object,
)
from api.core.sentry import capture_dependency_failure
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import Content, ContentType, ContentVersion
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import MediaBookCell, StoryVersionDetail
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])
me_router = APIRouter(prefix="/me", tags=["assets"])


@router.post(
    "/presigned-upload",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent), Depends(enforce_upload_rate_limit)],
)
async def create_presigned_upload(
    payload: PresignedUploadRequest,
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PresignedUploadResponse:
    asset_id = uuid.uuid4()
    storage_key = build_object_key(payload.purpose.value, asset_id, payload.content_type)
    # 서명은 임시 키에 한다 — 최종 키는 `complete_asset_upload` 가 검사한 바이트로만 채워진다.
    upload_url, expires_at = await run_in_threadpool(
        generate_presigned_put_url, build_upload_key(storage_key), payload.content_type
    )

    db.add(
        Asset(
            id=asset_id,
            owner_user_id=owner_user_id,
            storage_key=storage_key,
            kind=AssetKind.ORIGINAL,
            status=AssetStatus.PENDING,
        )
    )
    await db.commit()

    return PresignedUploadResponse(upload_url=upload_url, asset_id=asset_id, expires_at=expires_at)


def _upload_size_limit(storage_key: str) -> int | None:
    """Presigned-upload keys are `assets/{purpose}/{uuid}{ext}` (build_object_key);
    the Asset table has no purpose column, so the purpose is recovered from the key
    path. Keys outside the user-upload purposes (e.g. `assets/generated/...`) have
    no limit — the size check is a bypass safety net for presigned uploads only.
    """
    try:
        purpose = AssetPurpose(storage_key.split("/")[1])
    except ValueError:
        return None
    return UPLOAD_SIZE_LIMIT_BYTES[purpose]


# 같은 자산의 업로드 완료를 한 번에 하나만 들이는 락. TTL 은 완료 한 번이 걸릴 수 있는 가장 긴 시간보다 넉넉해야 한다
# — 저장소 왕복 넷(HEAD·GET·PUT 셋)에 클라이언트 타임아웃을 따로 두지 않았고 디코드는 프로세스 전역 한도를 기다릴 수
# 있다. 만료되면 둘이 겹칠 수 있다. 늦은 쪽은 최종 키에 올리기 직전에 상태를 다시 읽어 이미 끝난 자산의 저장소 객체를
# 덮지 않고, 행은 PENDING 일 때만 바꾼다. 그래도 둘이 동시에 올리는 중이면 저장소 객체는 늦게 올린 쪽 바이트가 된다.
_COMPLETE_LOCK_TTL_MS = 300_000
_COMPLETE_LOCK_POLL_SECONDS = 0.2


def _complete_lock_key(asset_id: uuid.UUID) -> str:
    return f"asset_complete:{asset_id}"


async def _discard_upload(db: AsyncSession, asset_id: uuid.UUID, upload_key: str) -> None:
    """검사에서 떨어진 업로드를 지운다. 저장소를 먼저 지워 실패하면 행이 남아 다시 시도할 수 있게 하고
    (`delete_generated_image` 와 같은 순서), 그다음 행을 지운다 — 검사를 못 넘은 업로드가 READY 로 남는 일은 없다.
    최종 키에는 아직 아무것도 쓰지 않았으므로 지울 것은 임시 객체뿐이다. 행은 아직 PENDING 일 때만 지운다 — 락이
    만료된 사이 다른 완료가 READY 로 만든 자산을 지우면 그 그림을 쓰는 화면이 사라진 행을 가리킨다."""
    await run_in_threadpool(delete_object, upload_key)
    await db.execute(delete(Asset).where(Asset.id == asset_id, Asset.status == AssetStatus.PENDING))
    await db.commit()


async def _response_for_current_state(db: AsyncSession, asset_id: uuid.UUID) -> AssetCompleteResponse:
    """다른 완료가 이 자산을 이미 처리했을 때 그 결과대로 답한다 — READY 면 같은 응답, 지워졌으면 404."""
    current = await db.scalar(select(Asset.status).where(Asset.id == asset_id))
    await db.commit()
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if current != AssetStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Upload is still being completed by another request"
        )
    return AssetCompleteResponse(asset_id=asset_id, status=current)


@router.post(
    "/{asset_id}/complete", dependencies=[Depends(require_legal_consent)]
)
async def complete_asset_upload(
    asset_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> AssetCompleteResponse:
    """브라우저가 임시 키에 올린 객체를 검사하고, 검사한 그 바이트를 최종 키(`storage_key`)에 다시 올린다.

    저장소 안에서 임시 객체를 복사하지 않는 이유: 검사와 복사 사이에 같은 서명 URL 로 임시 객체를 바꿔 올리면
    검사하지 않은 바이트가 최종 키로 간다. 이미 메모리에 있는 바이트를 올리면 최종 키 = 검사·축소본을 만든 바이트가
    보장된다. 이미 READY 인 자산은 저장소를 건드리지 않고 같은 응답을 돌려준다 — 같은 요청을 다시 보내는
    클라이언트를 깨지 않으면서, 완료 뒤 같은 URL 로 다시 올린 객체는 아무도 읽지 않는다.

    같은 자산의 완료가 겹치면 Redis 락으로 하나씩 처리한다 — 뒤의 요청은 앞의 요청이 끝날 때까지 기다렸다가 상태를
    다시 읽어 그대로 답한다. 둘이 각자 처리하면 그사이 바꿔 올린 바이트가 원본과 축소본에 섞일 수 있고, 발행 심사는
    칸을 축소본으로 본다. 저장소·디코드를 기다리는 동안에는 DB 트랜잭션을 쥐지 않는다(쥐면 커넥션 하나를 통째로
    잡는다). Redis 장애면 거절한다(503) — 채팅·발행 레이트리밋은 장애 때 통과시키지만 여기서 통과시키면 위 보호가
    사라지고, 세션도 Redis 라 그 상황엔 대개 인증부터 실패한다."""
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.owner_user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the asset owner")
    if asset.status == AssetStatus.READY:
        return AssetCompleteResponse(asset_id=asset.id, status=asset.status)
    storage_key = asset.storage_key
    # 읽기를 닫아 커넥션을 돌려준다(롤백은 세션의 객체를 만료시켜 쓰지 않는다).
    await db.commit()

    lock_key = _complete_lock_key(asset_id)
    try:
        token = await wait_for_lock(
            redis_client,
            lock_key,
            ttl_ms=_COMPLETE_LOCK_TTL_MS,
            max_wait_seconds=_COMPLETE_LOCK_TTL_MS / 1000,
            poll_interval_seconds=_COMPLETE_LOCK_POLL_SECONDS,
        )
    except RedisError as exc:
        logger.warning("upload completion lock unavailable: %s", type(exc).__name__)
        capture_dependency_failure(exc, dependency="redis")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Upload completion is currently unavailable"
        ) from exc
    if token is None:
        # 락의 TTL 만큼 기다렸는데도 못 잡았다 — 다른 요청이 계속 새로 잡고 있다. 지금 상태대로 답한다.
        return await _response_for_current_state(db, asset_id)
    try:
        return await _complete_locked_upload(db, asset_id, storage_key)
    finally:
        try:
            await release_lock(redis_client, lock_key, token)
        except RedisError:
            logger.warning("Failed to release upload completion lock %s; it expires on its own", lock_key)


async def _complete_locked_upload(db: AsyncSession, asset_id: uuid.UUID, storage_key: str) -> AssetCompleteResponse:
    """락을 쥔 채 하는 업로드 완료 본체. DB 는 처음의 상태 확인과 마지막의 조건부 쓰기에서만 짧게 쓴다."""
    # 락을 기다리는 사이 앞의 요청이 끝냈거나 지웠을 수 있다. 세션에 남은 옛 객체가 아니라 행을 다시 읽는다.
    current = await db.scalar(select(Asset.status).where(Asset.id == asset_id))
    await db.commit()
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if current == AssetStatus.READY:
        return AssetCompleteResponse(asset_id=asset_id, status=current)

    upload_key = build_upload_key(storage_key)
    reported_bytes = await run_in_threadpool(get_object_size, upload_key)
    if reported_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded object not found in storage yet",
        )

    # The FE resizes before upload, so oversize means the client bypassed it. The size
    # seen here only spares downloading an obviously oversized object; the object can
    # be replaced before the download, so the bytes actually downloaded are checked too.
    max_bytes = _upload_size_limit(storage_key)
    if max_bytes is not None and reported_bytes > max_bytes:
        await _discard_upload(db, asset_id, upload_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"maxBytes": max_bytes, "actualBytes": reported_bytes},
        )
    original_bytes = await run_in_threadpool(download_object, upload_key)
    if max_bytes is not None and len(original_bytes) > max_bytes:
        await _discard_upload(db, asset_id, upload_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"maxBytes": max_bytes, "actualBytes": len(original_bytes)},
        )

    # Invariant: a READY image asset always has every variant (`generate_variants`), so
    # responses can derive the keys without an existence check. A failed variant
    # therefore fails the whole asset — never READY with only the original.
    try:
        variants = await run_image_work(generate_variants, storage_key, original_bytes)
        width, height = await run_in_threadpool(read_image_size, original_bytes)
        detected_content_type = await run_in_threadpool(read_image_content_type, original_bytes)
    except ImageTooLargeError as exc:
        # `ValueError` 하위라 아래보다 먼저 잡아야 원인이 "풀 수 없는 그림"으로 가려지지 않는다. 바이트 상한과 같은
        # 모양으로 알린다. 정상 화면은 업로드 전에 줄여 올리므로 여기 닿는 것은 화면을 거치지 않은 요청이다.
        await _discard_upload(db, asset_id, upload_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"maxPixels": exc.max_pixels, "actualPixels": exc.actual_pixels},
        ) from exc
    except (OSError, ValueError) as exc:
        # Pillow can't decode the upload — deterministic failure, so clean up
        # like the oversize path instead of leaving an unretryable PENDING row.
        await _discard_upload(db, asset_id, upload_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded object is not a decodable image",
        ) from exc
    # 최종 키의 Content-Type 은 검사한 바이트의 실제 형식에서 정한다. 키의 확장자로는 되살릴 수 없다 — 시스템 MIME
    # 표가 없는 운영 이미지에서는 WebP 키에 확장자가 붙지 않아 `application/octet-stream` 이 되고, 원본을 새 탭에서
    # 열면 그림 대신 다운로드가 된다.
    content_type = detected_content_type or "application/octet-stream"
    # 내려받기·디코드 동안 락이 만료돼 다른 완료가 먼저 끝냈거나 지웠으면 최종 키를 덮지 않는다 — 행은 아래 조건부
    # 쓰기가 지키지만 저장소 객체는 이 확인만 지킨다(그 행의 크기·축소본과 다른 바이트가 원본 자리에 남는다).
    still_pending = await db.scalar(select(Asset.status).where(Asset.id == asset_id)) == AssetStatus.PENDING
    await db.commit()
    if not still_pending:
        return await _response_for_current_state(db, asset_id)
    await run_in_threadpool(upload_object, storage_key, original_bytes, content_type)
    for variant_key, variant_bytes in variants:
        await run_in_threadpool(upload_object, variant_key, variant_bytes, THUMBNAIL_CONTENT_TYPE)

    # 아직 PENDING 일 때만 READY 로 바꾼다. 락이 만료된 사이 다른 완료가 먼저 끝냈거나 지웠으면 그 결과를 덮지 않고
    # 그대로 답한다.
    marked = await db.scalar(
        update(Asset)
        .where(Asset.id == asset_id, Asset.status == AssetStatus.PENDING)
        .values(status=AssetStatus.READY, width=width, height=height)
        .returning(Asset.id)
    )
    await db.commit()
    if marked is None:
        return await _response_for_current_state(db, asset_id)

    # 임시 객체는 이제 아무도 읽지 않는다. 지우지 못해도 업로드는 끝난 것이라 실패로 돌리지 않는다 — 남은
    # 객체는 임시 접두사의 버킷 수명 규칙이 치운다.
    try:
        await run_in_threadpool(delete_object, upload_key)
    except (BotoCoreError, ClientError):
        logger.warning("Failed to delete temporary upload object %s", upload_key, exc_info=True)

    return AssetCompleteResponse(asset_id=asset_id, status=AssetStatus.READY)


@router.post(
    "/{asset_id}/register-situational-image", dependencies=[Depends(require_legal_consent)]
)
async def register_situational_image(
    asset_id: uuid.UUID,
    payload: RegisterSituationalImageRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> SituationalImageResponse:
    """Downloads the original asset, synchronously
    generates a Gaussian-blurred variant (no queue — a single-image blur is
    sub-second), and upserts the situational_images row keyed by entity_id.

    블러본을 만드는 동안(저장소 왕복 넷 + 디코드 한도 대기) DB 트랜잭션을 쥐지 않는다 — 확인을 커밋으로 닫고 블러본을
    올린 뒤, 짧은 트랜잭션에서 작품 행을 잠그고 그 버전이 아직 초안인지 다시 보고 쓴다. 발행 쓰기도 같은 작품 행을
    잠그므로 둘은 줄을 선다 — 그사이 발행됐으면 409 이고, 이 등록이 먼저면 발행이 그림이 바뀐 것을 보고 멈춘다.
    """
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.owner_user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the asset owner")
    if asset.status != AssetStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Asset upload is not complete yet"
        )

    content_version = await db.get(ContentVersion, payload.content_version_id)
    if content_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content version not found")
    content = await db.get(Content, content_version.content_id)
    if content is None or content.creator_user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the content creator")
    # 발행본은 독자가 대화하는 버전이고 발행 심사를 이미 통과한 상태다 — 여기서 이미지를 바로
    # 바꿔 넣으면 심사를 건너뛴다. 이미지는 초안에만 등록하고 발행으로 넘긴다.
    if content_version.published_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Content version is not a draft")
    # 상황별 이미지는 캐릭터만 읽는다. 스토리 버전에 붙은 행은 아무도 보지도 정리하지도 않는다.
    if content.type != ContentType.CHARACTER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Situational images are only for character content",
        )

    content_id, source_storage_key = content.id, asset.storage_key
    # 확인 조회를 닫아 커넥션을 돌려준다(롤백은 세션의 객체를 만료시켜 쓰지 않는다).
    await db.commit()

    blurred_upload = await upload_blurred_copy(source_storage_key)

    # 세션에 남은 옛 객체가 아니라 행을 다시 읽는다 — 블러본을 만드는 사이 다른 창이 이 초안을 발행했을 수 있다.
    content = await db.scalar(
        select(Content).where(Content.id == content_id).with_for_update().execution_options(populate_existing=True)
    )
    content_version = await db.scalar(
        select(ContentVersion)
        .where(ContentVersion.id == payload.content_version_id)
        .execution_options(populate_existing=True)
    )
    if content is None or content_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content version not found")
    if content_version.published_at is not None:
        # 올린 블러본은 가리키는 행 없이 남는다(아무 응답도 서명하지 않는다).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Content version is not a draft")
    blurred_asset_id = blurred_upload.asset_id
    db.add(blurred_asset_row(blurred_upload, owner_user_id=current_user_id))

    # 읽고 나서 쓰면 그 사이 자동저장 PATCH 가 같은 새 항목을 만들 수 있다 — 읽지 않고 한 문장으로
    # upsert 한다. 위에서 add 한 블러 자산이 이 행의 FK 대상이라 먼저 flush 한다.
    await db.flush()
    image_values = {
        "image_asset_id": asset_id,
        "blurred_asset_id": blurred_asset_id,
        "trigger_condition": payload.trigger_condition,
        "order": payload.order,
    }
    await db.execute(
        insert(SituationalImage)
        .values(entity_id=payload.entity_id, content_version_id=payload.content_version_id, **image_values)
        .on_conflict_do_update(constraint="ux_situational_images_version_entity", set_=image_values)
    )
    # 초안 이미지가 바뀌었으니 발행본과 달라졌다 — 초안 저장(PATCH)과 같이 작가 화면의 '발행 안 한 변경'을 세운다.
    content.has_unpublished_changes = True

    await db.commit()

    return SituationalImageResponse(
        entity_id=payload.entity_id,
        image_asset_id=asset_id,
        blurred_asset_id=blurred_asset_id,
        trigger_condition=payload.trigger_condition,
        order=payload.order,
    )


async def collect_asset_usages(
    db: AsyncSession, asset_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[GeneratedImageUsage]]:
    """어느 콘텐츠가 이 asset들을 참조 중인지 역조회한다.

    assets.id를 참조하는 6개 컬럼(character/story thumbnail_asset_id,
    situational_images.image/blurred_asset_id, media_book_cells.image/blurred_asset_id)을
    테이블별 일괄 select로 훑는다 —
    이미지마다 개별 조회하지 않는다(N+1 금지). 초안/발행 버전을 구분하지 않고 둘 다
    '사용 중'으로 보며, 같은 (content_id, field) 참조는 하나로 합친다(제목은 최신
    버전의 detail name이 남는다). 생성 이미지 삭제의 사전 판정도 이 함수를 재사용한다.

    이미지 생성 요청 행의 참조 이미지 칸은 보지 않는다 — 참조로 쓰였다는 이유로 삭제를 막으면
    한 번 참조한 이미지는 영영 못 지운다. 지우면 그 칸은 FK(`ON DELETE SET NULL`)가 비운다.
    """
    if not asset_ids:
        return {}

    merged: dict[uuid.UUID, dict[tuple[uuid.UUID, str], GeneratedImageUsage]] = {}

    def _add(
        asset_id: uuid.UUID,
        content_id: uuid.UUID,
        content_type: ContentType,
        content_title: str,
        field: GeneratedImageUsageField,
    ) -> None:
        merged.setdefault(asset_id, {})[(content_id, field)] = GeneratedImageUsage(
            content_id=content_id,
            content_type=content_type,
            content_title=content_title,
            field=field,
        )

    detail_models: tuple[type[CharacterVersionDetail] | type[StoryVersionDetail], ...] = (
        CharacterVersionDetail,
        StoryVersionDetail,
    )
    for detail_model in detail_models:
        thumbnail_rows = await db.execute(
            select(detail_model.thumbnail_asset_id, Content.id, Content.type, detail_model.name)
            .join(ContentVersion, ContentVersion.id == detail_model.content_version_id)
            .join(Content, Content.id == ContentVersion.content_id)
            .where(detail_model.thumbnail_asset_id.in_(asset_ids))
            .order_by(ContentVersion.created_at)
        )
        for thumbnail_asset_id, content_id, content_type, name in thumbnail_rows:
            _add(thumbnail_asset_id, content_id, content_type, name, "thumbnail")

    # 상황별 이미지는 캐릭터 전용이라 제목은 소속 버전의 character_version_details.name이다.
    requested_ids = set(asset_ids)
    situational_rows = await db.execute(
        select(
            SituationalImage.image_asset_id,
            SituationalImage.blurred_asset_id,
            Content.id,
            Content.type,
            CharacterVersionDetail.name,
        )
        .join(ContentVersion, ContentVersion.id == SituationalImage.content_version_id)
        .join(
            CharacterVersionDetail,
            CharacterVersionDetail.content_version_id == SituationalImage.content_version_id,
        )
        .join(Content, Content.id == ContentVersion.content_id)
        .where(
            or_(
                SituationalImage.image_asset_id.in_(asset_ids),
                SituationalImage.blurred_asset_id.in_(asset_ids),
            )
        )
        .order_by(ContentVersion.created_at)
    )
    for image_asset_id, blurred_asset_id, content_id, content_type, name in situational_rows:
        for referenced_id in (image_asset_id, blurred_asset_id):
            if referenced_id in requested_ids:
                _add(referenced_id, content_id, content_type, name, "situationalImage")

    # 미디어 북은 스토리 전용이라 제목은 소속 버전의 story_version_details.name이다.
    media_book_rows = await db.execute(
        select(
            MediaBookCell.image_asset_id,
            MediaBookCell.blurred_asset_id,
            Content.id,
            Content.type,
            StoryVersionDetail.name,
        )
        .join(ContentVersion, ContentVersion.id == MediaBookCell.content_version_id)
        .join(StoryVersionDetail, StoryVersionDetail.content_version_id == MediaBookCell.content_version_id)
        .join(Content, Content.id == ContentVersion.content_id)
        .where(
            or_(
                MediaBookCell.image_asset_id.in_(asset_ids),
                MediaBookCell.blurred_asset_id.in_(asset_ids),
            )
        )
        .order_by(ContentVersion.created_at)
    )
    for image_asset_id, blurred_asset_id, content_id, content_type, name in media_book_rows:
        for referenced_id in (image_asset_id, blurred_asset_id):
            if referenced_id in requested_ids:
                _add(referenced_id, content_id, content_type, name, "mediaBook")

    return {asset_id: list(entries.values()) for asset_id, entries in merged.items()}


@me_router.get("/generated-images")
async def list_generated_images(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[GeneratedImageItem]:
    """"생성한 이미지에서 선택" 갤러리 조회."""
    assets = list(
        await db.scalars(
            select(Asset)
            .where(
                Asset.owner_user_id == current_user_id,
                Asset.kind == AssetKind.GENERATED,
                Asset.status == AssetStatus.READY,
            )
            .order_by(Asset.created_at.desc())
        )
    )
    usages_by_asset = await collect_asset_usages(db, [asset.id for asset in assets])

    items: list[GeneratedImageItem] = []
    for asset in assets:
        image_url = await run_in_threadpool(generate_presigned_get_url, build_thumbnail_key(asset.storage_key))
        items.append(
            GeneratedImageItem(
                asset_id=asset.id,
                image_url=image_url,
                created_at=asset.created_at,
                usages=usages_by_asset.get(asset.id, []),
            )
        )
    return items


@me_router.delete("/generated-images/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generated_image(
    asset_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """생성 이미지 삭제.

    존재하지 않음/타인 소유/GENERATED 아님을 전부 404 하나로 답한다 — 남의 asset
    존재 여부를 노출하지 않기 위함. 사용 중이면 409에 사용처 목록을 담아
    발행·초안 참조가 깨지는 삭제를 구조적으로 막는다.
    """
    asset = await db.get(Asset, asset_id)
    if (
        asset is None
        or asset.owner_user_id != current_user_id
        or asset.kind != AssetKind.GENERATED
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    usages = (await collect_asset_usages(db, [asset_id])).get(asset_id, [])
    if usages:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "usages": [usage.model_dump(mode="json", by_alias=True) for usage in usages]
            },
        )

    storage_key = asset.storage_key
    # 저장소 삭제를 기다리는 동안 커넥션을 쥐지 않도록 조회를 닫는다(롤백은 세션의 객체를 만료시켜 쓰지 않는다).
    await db.commit()

    # S3를 먼저 지운다 — 실패하면 DB 행이 남아 재시도가 가능하다(고아 레코드 대신
    # 고아 파일을 피한다).
    await run_in_threadpool(delete_object, storage_key)
    # READY asset은 항상 변형(썸네일·표시용)을 갖는다 — 안 지우면 사용자가 만든 그림의 사본이 고아로 남는다.
    for variant_key in build_variant_keys(storage_key):
        await run_in_threadpool(delete_object, variant_key)

    # 저장소를 지우는 사이 다른 탭이 이 그림을 걸었을 수 있다 — 행을 지우기 전에 사용처를 다시 본다. 걸렸으면 행을 남겨
    # (외래 키 오류로 500 이 나는 대신) 사용처와 함께 409 로 답한다. 저장소 객체는 이미 지워졌다.
    usages = (await collect_asset_usages(db, [asset_id])).get(asset_id, [])
    if usages:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "usages": [usage.model_dump(mode="json", by_alias=True) for usage in usages]
            },
        )
    await db.delete(asset)
    await db.commit()
