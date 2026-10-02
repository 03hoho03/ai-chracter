import logging
import uuid
from collections.abc import Sequence

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.assets.blur import create_blurred_asset
from api.assets.image_processing import (
    THUMBNAIL_CONTENT_TYPE,
    generate_thumbnail,
    read_image_content_type,
    read_image_size,
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
from api.core.s3 import (
    build_object_key,
    build_thumbnail_key,
    build_upload_key,
    delete_object,
    download_object,
    generate_presigned_get_url,
    generate_presigned_put_url,
    get_object_size,
    upload_object,
)
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
    "/presigned-upload", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
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


async def _discard_upload(db: AsyncSession, asset: Asset, upload_key: str) -> None:
    """검사에서 떨어진 업로드를 지운다. 저장소를 먼저 지워 실패하면 행이 남아 다시 시도할 수 있게 하고
    (`delete_generated_image` 와 같은 순서), 그다음 행을 지운다 — 검사를 못 넘은 업로드가 READY 로 남는 일은 없다.
    최종 키에는 아직 아무것도 쓰지 않았으므로 지울 것은 임시 객체뿐이다."""
    await run_in_threadpool(delete_object, upload_key)
    await db.delete(asset)
    await db.commit()


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
    클라이언트를 깨지 않으면서, 완료 뒤 같은 URL 로 다시 올린 객체는 아무도 읽지 않는다."""
    # 같은 자산의 complete 가 겹치면 하나씩 처리한다 — 뒤의 요청은 앞의 커밋 뒤 READY 를 보고 그대로 돌아간다.
    asset = await db.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.owner_user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the asset owner")
    if asset.status == AssetStatus.READY:
        return AssetCompleteResponse(asset_id=asset.id, status=asset.status)

    upload_key = build_upload_key(asset.storage_key)
    reported_bytes = await run_in_threadpool(get_object_size, upload_key)
    if reported_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded object not found in storage yet",
        )

    # The FE resizes before upload, so oversize means the client bypassed it. The size
    # seen here only spares downloading an obviously oversized object; the object can
    # be replaced before the download, so the bytes actually downloaded are checked too.
    max_bytes = _upload_size_limit(asset.storage_key)
    if max_bytes is not None and reported_bytes > max_bytes:
        await _discard_upload(db, asset, upload_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"maxBytes": max_bytes, "actualBytes": reported_bytes},
        )
    original_bytes = await run_in_threadpool(download_object, upload_key)
    if max_bytes is not None and len(original_bytes) > max_bytes:
        await _discard_upload(db, asset, upload_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"maxBytes": max_bytes, "actualBytes": len(original_bytes)},
        )

    # Invariant: a READY image asset always has a `{key}_thumb.webp` variant, so
    # list endpoints can derive the key without an existence check. A failed
    # variant therefore fails the whole asset — never READY with only the original.
    try:
        thumbnail_bytes = await run_in_threadpool(generate_thumbnail, original_bytes)
        width, height = await run_in_threadpool(read_image_size, original_bytes)
        detected_content_type = await run_in_threadpool(read_image_content_type, original_bytes)
    except (OSError, ValueError) as exc:
        # Pillow can't decode the upload — deterministic failure, so clean up
        # like the oversize path instead of leaving an unretryable PENDING row.
        await _discard_upload(db, asset, upload_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded object is not a decodable image",
        ) from exc
    # 최종 키의 Content-Type 은 검사한 바이트의 실제 형식에서 정한다. 키의 확장자로는 되살릴 수 없다 — 시스템 MIME
    # 표가 없는 운영 이미지에서는 WebP 키에 확장자가 붙지 않아 `application/octet-stream` 이 되고, 원본을 새 탭에서
    # 열면 그림 대신 다운로드가 된다.
    content_type = detected_content_type or "application/octet-stream"
    await run_in_threadpool(upload_object, asset.storage_key, original_bytes, content_type)
    await run_in_threadpool(
        upload_object,
        build_thumbnail_key(asset.storage_key),
        thumbnail_bytes,
        THUMBNAIL_CONTENT_TYPE,
    )

    asset.status = AssetStatus.READY
    asset.width, asset.height = width, height
    await db.commit()

    # 임시 객체는 이제 아무도 읽지 않는다. 지우지 못해도 업로드는 끝난 것이라 실패로 돌리지 않는다 — 남은
    # 객체는 임시 접두사의 버킷 수명 규칙이 치운다.
    try:
        await run_in_threadpool(delete_object, upload_key)
    except (BotoCoreError, ClientError):
        logger.warning("Failed to delete temporary upload object %s", upload_key, exc_info=True)

    return AssetCompleteResponse(asset_id=asset.id, status=asset.status)


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

    blurred_asset = await create_blurred_asset(db, source_storage_key=asset.storage_key, owner_user_id=current_user_id)
    blurred_asset_id = blurred_asset.id

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

    # S3를 먼저 지운다 — 실패하면 DB 행이 남아 재시도가 가능하다(고아 레코드 대신
    # 고아 파일을 피한다).
    await run_in_threadpool(delete_object, asset.storage_key)
    # READY asset은 항상 `_thumb.webp`
    # 변형을 갖는다(list_generated_images가 이걸 내보낸다) — 안 지우면 고아로 남는다.
    await run_in_threadpool(delete_object, build_thumbnail_key(asset.storage_key))
    await db.delete(asset)
    await db.commit()
