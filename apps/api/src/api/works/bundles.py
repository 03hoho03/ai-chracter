"""작품 묶음 — 작가가 자기 캐릭터·스토리·소설을 사적으로 정리하는 묶음(`/me/work-bundles`).

묶음은 스튜디오 안에서 본인에게만 보인다. 남의 묶음·남의 작품·없는 것은 모두 404 다 — 사적 정리라 무엇이 있는지 드러내지
않는다. 묶음별 항목 목록은 따로 두지 않고 통합 작품 목록(`GET /me/works?bundleId=`)이 같은 정렬·커서로 낸다.

넣기·빼기·이름 바꾸기는 묶음의 `updated_at` 만 민다. 작품 행(`contents`·`novels`)은 읽기만 한다 — 그 행에는 소설화 허락·권리
고정 칸과 작가의 편집 시각이 있어, 정리 동작이 그것을 바꾸면 안 된다.

잠금: 쓰기는 모두 회원 행(`lock_active_user`) → 묶음 행(`FOR UPDATE`) 순이다. 묶음 수 한도는 회원 행으로, 항목 수 한도와 같은
작품 동시 넣기는 묶음 행으로 줄을 세운 뒤 센다. 탈퇴 파기도 회원 행을 먼저 잡고 소설을 지운 뒤(소속 행 CASCADE) 묶음을 지우므로,
회원 행을 먼저 잡지 않으면 묶음 행을 쥔 넣기·빼기가 탈퇴가 지우는 소설·소속 행을 기다리고 탈퇴는 그 묶음 행을 기다려 교착이
된다. 회원 행에서 줄을 서면 탈퇴 뒤의 쓰기는 401 이다."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from api.comments.access import lock_active_user
from api.db.models.content import Content, ContentType
from api.db.models.novel import Novel
from api.db.models.work_bundle import WorkBundle, WorkBundleItem
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.novelize.access import has_novelize_access
from api.session.dependencies import get_current_user_id
from api.works.router import listed_content, listed_novel
from api.works.schemas import (
    WorkBundleCreatedResponse,
    WorkBundleKind,
    WorkBundleListResponse,
    WorkBundleNameRequest,
    WorkBundleSummary,
)

router = APIRouter(prefix="/me/work-bundles", tags=["works"])

# 넘으면 409 `WORK_BUNDLE_LIMIT`. 묶음 목록은 페이지 없이 한 번에 내므로 묶음 수가 그 응답 크기의 상한이다.
MAX_BUNDLES_PER_USER = 50
MAX_ITEMS_PER_BUNDLE = 500


def _bundle_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "WORK_BUNDLE_NOT_FOUND"})


def _limit_reached() -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "WORK_BUNDLE_LIMIT"})


async def _lock_own_bundle(db: AsyncSession, bundle_id: uuid.UUID, user_id: uuid.UUID) -> WorkBundle:
    bundle = await db.scalar(
        select(WorkBundle)
        .where(WorkBundle.id == bundle_id, WorkBundle.owner_user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if bundle is None:
        raise _bundle_not_found()
    return bundle


async def _require_own_work(db: AsyncSession, user_id: uuid.UUID, kind: WorkBundleKind, work_id: uuid.UUID) -> None:
    """넣을 수 있는 작품인지 — 통합 작품 목록에 나오는 것과 같은 조건이다(내 것, 운영 삭제·숨김 아님, 소설은 소설화 허용이
    있는 계정만). 캐릭터 id 를 `story` 로 넣는 것처럼 종류가 다르면 없는 것과 같다.

    확인한 행을 `FOR KEY SHARE` 로 이 트랜잭션 끝까지 잡는다. 초안 삭제·소설 삭제는 회원 행을 잡지 않고 작품 행을 지우므로, 잡지
    않으면 확인과 소속 INSERT 사이에 그 삭제가 커밋돼 INSERT 가 FK 위반(500)이 된다. 잡으면 삭제가 이 넣기의 커밋을 기다리고
    (지우면 소속 행은 CASCADE 로 함께 사라진다), 삭제가 먼저 커밋됐으면 이 조회가 행을 못 찾아 404 다."""
    if kind == "novel":
        found = (
            await has_novelize_access(db, user_id)
            and (
                await db.scalar(
                    select(Novel.id)
                    .where(Novel.id == work_id, listed_novel(Novel, user_id))
                    .with_for_update(read=True, key_share=True)
                )
            )
            is not None
        )
    else:
        found = (
            await db.scalar(
                select(Content.id)
                .where(Content.id == work_id, Content.type == ContentType(kind), listed_content(user_id))
                .with_for_update(read=True, key_share=True)
            )
        ) is not None
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "WORK_NOT_FOUND"})


def _item_matches(kind: WorkBundleKind, work_id: uuid.UUID) -> ColumnElement[bool]:
    return WorkBundleItem.novel_id == work_id if kind == "novel" else WorkBundleItem.content_id == work_id


async def _item_counts(db: AsyncSession, user_id: uuid.UUID, bundle_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """묶음별 항목 수. `GET /me/works?bundleId=` 와 같은 조건(`listed_content`·`listed_novel`·소설화 허용)으로 센다."""
    counts: dict[uuid.UUID, int] = dict.fromkeys(bundle_ids, 0)
    content_rows = await db.execute(
        select(WorkBundleItem.bundle_id, func.count())
        .join(Content, Content.id == WorkBundleItem.content_id)
        .where(WorkBundleItem.bundle_id.in_(bundle_ids), listed_content(user_id))
        .group_by(WorkBundleItem.bundle_id)
    )
    for bundle_id, item_count in content_rows.all():
        counts[bundle_id] += item_count
    if await has_novelize_access(db, user_id):
        novel_rows = await db.execute(
            select(WorkBundleItem.bundle_id, func.count())
            .join(Novel, Novel.id == WorkBundleItem.novel_id)
            .where(WorkBundleItem.bundle_id.in_(bundle_ids), listed_novel(Novel, user_id))
            .group_by(WorkBundleItem.bundle_id)
        )
        for bundle_id, item_count in novel_rows.all():
            counts[bundle_id] += item_count
    return counts


@router.get("")
async def list_my_work_bundles(
    kind: WorkBundleKind | None = None,
    work_id: uuid.UUID | None = Query(None, alias="workId"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> WorkBundleListResponse:
    """내 묶음 전부를 최근에 바뀐 것부터(한도 안이라 페이지 없음). `kind`·`workId` 를 함께 주면 각 묶음에 그 작품이 들었는지를
    `containsWork` 로 싣는다(작품 메뉴의 체크 표시). 둘 중 하나만 주면 422."""
    if (kind is None) != (work_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "WORK_BUNDLE_QUERY_INCOMPLETE"}
        )
    bundles = (
        await db.scalars(
            select(WorkBundle)
            .where(WorkBundle.owner_user_id == user_id)
            .order_by(WorkBundle.updated_at.desc(), WorkBundle.id.desc())
        )
    ).all()
    bundle_ids = [bundle.id for bundle in bundles]
    counts = await _item_counts(db, user_id, bundle_ids) if bundle_ids else {}
    holding: set[uuid.UUID] | None = None
    if kind is not None and work_id is not None:
        holding = set(
            (
                await db.scalars(
                    select(WorkBundleItem.bundle_id).where(
                        WorkBundleItem.bundle_id.in_(bundle_ids), _item_matches(kind, work_id)
                    )
                )
            ).all()
        )
    return WorkBundleListResponse(
        items=[
            WorkBundleSummary(
                id=bundle.id,
                name=bundle.name,
                item_count=counts.get(bundle.id, 0),
                updated_at=bundle.updated_at,
                contains_work=None if holding is None else bundle.id in holding,
            )
            for bundle in bundles
        ]
    )


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)])
async def create_work_bundle(
    body: WorkBundleNameRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> WorkBundleCreatedResponse:
    await lock_active_user(db, user_id)
    owned = await db.scalar(select(func.count()).select_from(WorkBundle).where(WorkBundle.owner_user_id == user_id))
    if (owned or 0) >= MAX_BUNDLES_PER_USER:
        raise _limit_reached()
    bundle = WorkBundle(owner_user_id=user_id, name=body.name)
    db.add(bundle)
    await db.commit()
    return WorkBundleCreatedResponse(id=bundle.id)


@router.patch("/{bundle_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_legal_consent)])
async def rename_work_bundle(
    bundle_id: uuid.UUID,
    body: WorkBundleNameRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """같은 이름이면 아무것도 바꾸지 않는다(목록 순서도 그대로)."""
    await lock_active_user(db, user_id)
    bundle = await _lock_own_bundle(db, bundle_id, user_id)
    if bundle.name != body.name:
        bundle.name = body.name
        bundle.updated_at = datetime.now(UTC)
    await db.commit()


@router.delete("/{bundle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_bundle(
    bundle_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """묶음과 그 소속 행(DB CASCADE)만 지운다. 작품·소설·채팅은 그대로다. 자기 데이터 정리라 재동의 전에도 열려 있다."""
    await lock_active_user(db, user_id)
    bundle = await _lock_own_bundle(db, bundle_id, user_id)
    await db.delete(bundle)
    await db.commit()


@router.put(
    "/{bundle_id}/items/{kind}/{work_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_legal_consent)],
)
async def put_work_bundle_item(
    bundle_id: uuid.UUID,
    kind: WorkBundleKind,
    work_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """작품 하나를 묶음에 넣는다. 이미 들었으면 그대로 204 다(멱등 — 한도에도 걸리지 않고 묶음 순서도 그대로). 묶음이 내 것이
    아니면 404 `WORK_BUNDLE_NOT_FOUND`, 작품을 넣을 수 없으면 404 `WORK_NOT_FOUND`(`_require_own_work`)."""
    await lock_active_user(db, user_id)
    bundle = await _lock_own_bundle(db, bundle_id, user_id)
    await _require_own_work(db, user_id, kind, work_id)
    present = await db.scalar(
        select(WorkBundleItem.id).where(WorkBundleItem.bundle_id == bundle.id, _item_matches(kind, work_id))
    )
    if present is not None:
        return
    # 한도는 화면의 항목 수와 같은 것을 센다 — 운영 삭제된 작품·숨긴 소설처럼 소속 행만 남은 것은 자리를 차지하지 않는다.
    # 묶음 행을 잡은 뒤라 같은 묶음의 넣기가 이 사이에 끼지 않는다.
    held = (await _item_counts(db, user_id, [bundle.id]))[bundle.id]
    if held >= MAX_ITEMS_PER_BUNDLE:
        raise _limit_reached()
    db.add(
        WorkBundleItem(
            bundle_id=bundle.id,
            content_id=None if kind == "novel" else work_id,
            novel_id=work_id if kind == "novel" else None,
        )
    )
    bundle.updated_at = datetime.now(UTC)
    await db.commit()


@router.delete("/{bundle_id}/items/{kind}/{work_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_work_bundle_item(
    bundle_id: uuid.UUID,
    kind: WorkBundleKind,
    work_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """작품 하나를 묶음에서 뺀다. 들어 있지 않아도 204 다. 작품 소유는 다시 보지 않는다 — 내 묶음에서 행을 지울 뿐이라 남의
    작품에 닿지 않는다. 자기 데이터 정리라 재동의 전에도 열려 있다."""
    await lock_active_user(db, user_id)
    bundle = await _lock_own_bundle(db, bundle_id, user_id)
    removed = (
        await db.scalars(
            delete(WorkBundleItem)
            .where(WorkBundleItem.bundle_id == bundle.id, _item_matches(kind, work_id))
            .returning(WorkBundleItem.id)
        )
    ).all()
    if removed:
        bundle.updated_at = datetime.now(UTC)
    await db.commit()
