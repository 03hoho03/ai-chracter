"""홈 큐레이션 — 운영자가 홈 첫 화면에 유형마다 한 편씩 거는 지정작의 현황·지정·해제.

지정은 지금 공개 목록에 실리는 작품만 받는다. 지정 뒤 작품이 이용제한·비공개가 돼도 지정을 지우지 않는다 — 홈이 읽을
때 같은 판정으로 거르므로 그동안은 안 보이고, 제한이 풀리면 다시 보인다. 그래서 조치 경로(작품 조치·신고 처리·정지)는
이 표를 몰라도 된다. 판정은 홈 목록과 같은 `select_publicly_listed`(조건 + 조인) 하나를 쓴다 — 사본이 갈리면 어드민의 "보임"
표시와 실제 홈이 어긋난다."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminHomeCurationClearRequest,
    AdminHomeCurationContent,
    AdminHomeCurationListResponse,
    AdminHomeCurationSetRequest,
    AdminHomeCurationSlot,
)
from api.content.access import select_publicly_listed
from api.core.s3 import build_thumbnail_key, generate_presigned_get_url
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentType, HomeCuration
from api.db.models.media import Asset
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session

router = APIRouter(tags=["admin"])

# 홈이 스토리를 기본 유형으로 열므로 현황도 스토리부터 보인다.
_SLOT_ORDER = (ContentType.STORY, ContentType.CHARACTER)


async def _is_publicly_listed(db: AsyncSession, content: Content) -> bool:
    listed_id = await db.scalar(select_publicly_listed(content.type, Content.id).where(Content.id == content.id))
    return listed_id is not None


async def _slot_content(db: AsyncSession, content: Content) -> AdminHomeCurationContent:
    name = ""
    thumbnail_url: str | None = None
    version_id = content.current_published_version_id
    if version_id is not None:
        detail: CharacterVersionDetail | StoryVersionDetail | None = (
            await db.get(CharacterVersionDetail, version_id)
            if content.type == ContentType.CHARACTER
            else await db.get(StoryVersionDetail, version_id)
        )
        if detail is not None:
            name = detail.name
            asset = await db.get(Asset, detail.thumbnail_asset_id) if detail.thumbnail_asset_id else None
            if asset is not None:
                thumbnail_url = await run_in_threadpool(
                    generate_presigned_get_url, build_thumbnail_key(asset.storage_key)
                )
    return AdminHomeCurationContent(
        id=content.id,
        name=name,
        thumbnail_url=thumbnail_url,
        visibility=content.visibility,
        moderation_status=content.moderation_status,
    )


@router.get("/admin/home-curations")
async def list_home_curations(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminHomeCurationListResponse:
    curated = {row.content_type: row.content_id for row in (await db.scalars(select(HomeCuration))).all()}
    items: list[AdminHomeCurationSlot] = []
    for content_type in _SLOT_ORDER:
        content_id = curated.get(content_type)
        content = await db.get(Content, content_id) if content_id is not None else None
        if content is None:
            items.append(AdminHomeCurationSlot(type=content_type, content=None, is_listed=False))
            continue
        items.append(
            AdminHomeCurationSlot(
                type=content_type,
                content=await _slot_content(db, content),
                is_listed=await _is_publicly_listed(db, content),
            )
        )
    return AdminHomeCurationListResponse(items=items)


@router.put("/admin/home-curations/{content_type}", status_code=status.HTTP_204_NO_CONTENT)
async def set_home_curation(
    content_type: ContentType,
    body: AdminHomeCurationSetRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """그 유형의 지정작을 이 작품으로 둔다. 이미 다른 작품이 지정돼 있으면 바꾼다(한 문장 upsert라 동시 지정은 나중
    것이 이긴다). 같은 작품을 다시 지정해도 막지 않고 감사 로그에 한 행 더 남긴다.

    400 은 둘이고 `code` 로 갈린다: 칸과 유형이 다른 작품(`CONTENT_TYPE_MISMATCH` — 유형 일치는 DB 가 아니라 여기서만
    지킨다), 지금 공개 목록에 실리지 않는 작품(`NOT_PUBLICLY_LISTED` — 지정했는데 홈에 안 보이는 혼란을 지정
    시점에 막는다)."""
    content = await db.get(Content, body.content_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    if content.type != content_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "CONTENT_TYPE_MISMATCH"})
    if not await _is_publicly_listed(db, content):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "NOT_PUBLICLY_LISTED"})

    await db.execute(
        insert(HomeCuration)
        .values(content_type=content_type, content_id=content.id)
        .on_conflict_do_update(
            index_elements=[HomeCuration.content_type],
            set_={"content_id": content.id, "updated_at": func.now()},
        )
    )
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="home-curation-set",
        target_content_id=content.id,
        reason_text=body.admin_comment or "",
    )
    await db.commit()


@router.delete("/admin/home-curations/{content_type}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_home_curation(
    content_type: ContentType,
    body: AdminHomeCurationClearRequest | None = None,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """그 유형의 지정을 지운다. 지정이 없어도 204 다 — 결과가 같으니 다시 눌러도 막지 않는다. 감사 로그는 실제로
    지웠을 때만 남긴다(대상 작품이 있어야 기록이 무엇을 내렸는지 말할 수 있다)."""
    removed_content_id = await db.scalar(
        delete(HomeCuration).where(HomeCuration.content_type == content_type).returning(HomeCuration.content_id)
    )
    if removed_content_id is not None:
        await record_admin_action(
            db,
            admin_id=admin_id,
            action_type="home-curation-clear",
            target_content_id=removed_content_id,
            reason_text=(body.admin_comment if body is not None else None) or "",
        )
    await db.commit()
