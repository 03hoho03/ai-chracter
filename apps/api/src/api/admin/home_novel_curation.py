"""홈 노벨 — 운영자가 홈 첫 화면의 노벨 섹션에 거는 노벨의 현황·지정·해제.

작품 홈 지정(`admin/home_curation.py`)과 같은 원칙이다. 지정은 지금 독자가 읽을 수 있는 노벨만 받고, 지정 뒤 노벨이 거둬지거나
이용제한돼도 지정을 지우지 않는다 — 홈이 읽을 때 노벨 목록과 같은 판정(`select_readable_publications`)으로 거르므로 그동안은
안 보이고, 다시 읽을 수 있게 되면 돌아온다. 그래서 거두기·운영 조치·정지 경로는 이 표를 몰라도 된다. 작품 지정과 다른 점은
자리가 여럿(`HOME_NOVEL_CURATION_SLOTS`, 자리 번호가 곧 홈의 순서)이라는 것뿐이다.

노벨 스위치가 꺼져 있어도 지정은 된다 — 켜기 전에 홈을 채워 둘 수 있게."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminHomeCurationClearRequest,
    AdminHomeNovelCurationListResponse,
    AdminHomeNovelCurationNovel,
    AdminHomeNovelCurationSetRequest,
    AdminHomeNovelCurationSlot,
)
from api.core.s3 import build_thumbnail_key, generate_presigned_get_url
from api.db.models.auth import User
from api.db.models.media import Asset
from api.db.models.novel import HOME_NOVEL_CURATION_SLOTS, HomeNovelCuration, Novel, NovelPublication
from api.db.session import get_db_session
from api.novel_public.access import select_readable_publications
from api.novelize.router import _work_thumbnail_asset_ids

router = APIRouter(tags=["admin"])

_Position = Path(ge=1, le=HOME_NOVEL_CURATION_SLOTS)


async def _is_listed(db: AsyncSession, novel_id: uuid.UUID) -> bool:
    found = await db.scalar(
        select_readable_publications(NovelPublication.novel_id).where(NovelPublication.novel_id == novel_id)
    )
    return found is not None


async def _slot_novel(db: AsyncSession, publication: NovelPublication, novel: Novel) -> AdminHomeNovelCurationNovel:
    """운영자 화면은 원작자가 탈퇴했어도 원작 썸네일을 보인다 — 무엇을 걸었는지 알아보는 것이 목적이다."""
    cover_url: str | None = None
    asset_id = (await _work_thumbnail_asset_ids(db, {novel.content_id})).get(novel.content_id)
    asset = await db.get(Asset, asset_id) if asset_id is not None else None
    if asset is not None:
        cover_url = generate_presigned_get_url(build_thumbnail_key(asset.storage_key))
    publisher = await db.get(User, novel.user_id)
    return AdminHomeNovelCurationNovel(
        id=novel.id,
        title=publication.title if publication.title is not None else novel.content_title,
        source_title=novel.content_title,
        cover_url=cover_url,
        publisher_nickname=publisher.nickname if publisher is not None else None,
        visibility=publication.visibility,
        moderation_status=publication.moderation_status,
    )


@router.get("/admin/home-novel-curations")
async def list_home_novel_curations(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminHomeNovelCurationListResponse:
    """자리 1부터 끝까지 전부 — 빈 자리도 한 줄씩(화면이 자리마다 지정 버튼을 그린다)."""
    rows = {
        position: (publication, novel)
        for position, publication, novel in (
            await db.execute(
                select(HomeNovelCuration.position, NovelPublication, Novel)
                .join(NovelPublication, NovelPublication.novel_id == HomeNovelCuration.novel_id)
                .join(Novel, Novel.id == HomeNovelCuration.novel_id)
            )
        ).tuples()
    }
    items: list[AdminHomeNovelCurationSlot] = []
    for position in range(1, HOME_NOVEL_CURATION_SLOTS + 1):
        found = rows.get(position)
        if found is None:
            items.append(AdminHomeNovelCurationSlot(position=position, novel=None, is_listed=False))
            continue
        publication, novel = found
        items.append(
            AdminHomeNovelCurationSlot(
                position=position,
                novel=await _slot_novel(db, publication, novel),
                is_listed=await _is_listed(db, novel.id),
            )
        )
    return AdminHomeNovelCurationListResponse(items=items)


@router.put("/admin/home-novel-curations/{position}", status_code=status.HTTP_204_NO_CONTENT)
async def set_home_novel_curation(
    body: AdminHomeNovelCurationSetRequest,
    position: int = _Position,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """그 자리에 이 노벨을 건다. 자리에 다른 노벨이 있으면 바꾸고, 이 노벨이 다른 자리에 걸려 있으면 그 자리를 비우고
    옮긴다(한 노벨은 한 자리에만). 같은 노벨을 같은 자리에 다시 걸어도 막지 않고 감사 로그에 한 행 더 남긴다.

    404 `NOVEL_NOT_FOUND` 는 공개한 적이 없는 소설, 400 `NOT_PUBLICLY_LISTED` 는 지금 독자가 읽을 수 없는 노벨이다(걸었는데
    홈에 안 보이는 혼란을 거는 시점에 막는다). 409 `HOME_NOVEL_CURATION_CONFLICT` 는 판정 뒤 쓰기 전에 상황이 바뀐 경우다 —
    다른 운영자가 같은 노벨을 다른 자리에 동시에 걸었거나(한 노벨 한 자리 유니크) 그 사이 게시자가 소설을 지웠다. 목록을
    새로 읽고 다시 걸면 된다."""
    if await db.get(NovelPublication, body.novel_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "NOVEL_NOT_FOUND"})
    if not await _is_listed(db, body.novel_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "NOT_PUBLICLY_LISTED"})

    # 판정과 쓰기 사이를 잠그지 않는다 — 운영자 한두 명이 쓰는 화면이라 드문 겹침은 제약 위반을 409 로 돌려주는 것으로 족하다.
    # SAVEPOINT 로 감싸 실패한 이 쓰기만 되감는다.
    try:
        async with db.begin_nested():
            await db.execute(
                delete(HomeNovelCuration).where(
                    HomeNovelCuration.novel_id == body.novel_id, HomeNovelCuration.position != position
                )
            )
            await db.execute(
                insert(HomeNovelCuration)
                .values(position=position, novel_id=body.novel_id)
                .on_conflict_do_update(
                    index_elements=[HomeNovelCuration.position],
                    set_={"novel_id": body.novel_id, "updated_at": func.now()},
                )
            )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "HOME_NOVEL_CURATION_CONFLICT"}
        ) from None
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="home-novel-curation-set",
        target_novel_id=body.novel_id,
        reason_text=body.admin_comment or "",
    )
    await db.commit()


@router.delete("/admin/home-novel-curations/{position}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_home_novel_curation(
    position: int = _Position,
    body: AdminHomeCurationClearRequest | None = None,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """그 자리를 비운다. 비어 있어도 204 다. 감사 로그는 실제로 비웠을 때만 남긴다(작품 홈 지정 해제와 같다)."""
    removed_novel_id = await db.scalar(
        delete(HomeNovelCuration).where(HomeNovelCuration.position == position).returning(HomeNovelCuration.novel_id)
    )
    if removed_novel_id is not None:
        await record_admin_action(
            db,
            admin_id=admin_id,
            action_type="home-novel-curation-clear",
            target_novel_id=removed_novel_id,
            reason_text=(body.admin_comment if body is not None else None) or "",
        )
    await db.commit()
