"""소설 화 삽화 라우트 — 붙이기·옮기기·바꾸기·떼기와 원작 그림 후보. 소설 삽화 스위치가 꺼져 있으면 모두 404 다.

배치 변경은 본문이 같은 새 개정(출처 `illustration`)을 쌓는다 — 직접 수정·되돌리기와 같은 낙관 잠금(기준 개정이 지금 개정이
아니면 409 `NOVEL_REVISION_CONFLICT`)과 같은 장 행 잠금을 쓴다. 무과금이고, 그림 파일은 지우지 않는다(앞 개정이 여전히 쓴다).
본문이 같으므로 AI 수정 미리보기는 낡지 않는다(비우기를 부르지 않는다).

모든 응답에 `Cache-Control: no-store` 를 붙인다 — 스위치가 꺼진 동안의 404 를 브라우저가 붙잡아 두지 않게(`no_store.py`)."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.s3 import build_display_key, generate_presigned_get_url
from api.db.models.novel import Novel, NovelChapterRevision, NovelIllustrationPlacement, NovelIllustrationSource
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.novel_public.no_store import NoStoreRoute
from api.novelize.access import require_novelize_access
from api.novelize.blocks import build_revision, copied_ids
from api.novelize.illustrations import PlacementSpec, original_candidates, placements_of, specs_of, usable_asset
from api.novelize.router import (
    _chapter_response,
    _get_chapter,
    _lock_current_revision_for_edit,
    _novel_error,
    _owned_novel_dependency,
    _stack_revision,
)
from api.novelize.schemas import (
    NovelChapterResponse,
    NovelIllustrationAttachRequest,
    NovelIllustrationDetachRequest,
    NovelIllustrationMoveRequest,
    NovelIllustrationReplaceRequest,
    NovelOriginalIllustrationCandidate,
    NovelOriginalIllustrationCandidates,
)


async def _require_illustrations_enabled() -> None:
    if not settings.novel_illustrations_enabled:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_ILLUSTRATIONS_DISABLED")


illustration_router = APIRouter(
    prefix="/novels",
    tags=["novels"],
    route_class=NoStoreRoute,
    dependencies=[Depends(_require_illustrations_enabled), Depends(require_novelize_access)],
)


def _placed_at(
    specs: list[PlacementSpec],
    spec: PlacementSpec,
    anchor_block_id: uuid.UUID,
    placement: NovelIllustrationPlacement,
    order: int | None,
) -> list[PlacementSpec]:
    """`spec` 를 그 자리(앵커·앞뒤)의 `order` 번째(비었거나 넘치면 맨 끝)에 끼운 새 목록."""
    moved = PlacementSpec(anchor_block_id, placement, spec.asset_id, spec.source)
    slot = [index for index, item in enumerate(specs) if (item.anchor_block_id, item.placement) == (anchor_block_id, placement)]
    if order is not None and order < len(slot):
        at = slot[order]
    elif slot:
        at = slot[-1] + 1
    else:
        at = len(specs)
    return [*specs[:at], moved, *specs[at:]]


def _require_anchor(current: NovelChapterRevision, anchor_block_id: uuid.UUID) -> None:
    if anchor_block_id not in current.block_ids:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_ILLUSTRATION_ANCHOR_INVALID")


async def _require_usable(
    db: AsyncSession, novel: Novel, asset_id: uuid.UUID, source: NovelIllustrationSource
) -> None:
    if not await usable_asset(db, novel, asset_id, source):
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_ILLUSTRATION_ASSET_INVALID")


async def _stack_placements(
    db: AsyncSession, novel: Novel, current: NovelChapterRevision, placements: list[PlacementSpec]
) -> None:
    await _stack_revision(
        db,
        novel,
        current,
        build_revision(body=current.body, source="illustration", block_ids=copied_ids(current)),
        placements=placements,
    )
    await db.commit()


@illustration_router.post(
    "/{novel_id}/chapters/{chapter_id}/illustrations",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def attach_novel_illustration(
    chapter_id: uuid.UUID,
    payload: NovelIllustrationAttachRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """그림 한 장을 지금 개정의 문단 앞·뒤에 붙인다. 문단이 지금 개정에 없으면 422 `NOVEL_ILLUSTRATION_ANCHOR_INVALID`, 그 출처로
    쓸 수 없는 그림(남의 것·준비 안 됨·삽화 용도가 아닌 업로드·본 적 없는 원작 그림 등 — 가르지 않는다)이면 422
    `NOVEL_ILLUSTRATION_ASSET_INVALID`."""
    chapter = await _get_chapter(db, novel, chapter_id)
    current = await _lock_current_revision_for_edit(db, chapter.id, payload.base_revision_id)
    _require_anchor(current, payload.anchor_block_id)
    await _require_usable(db, novel, payload.asset_id, payload.source)
    specs = specs_of(await placements_of(db, current))
    added = PlacementSpec(None, None, payload.asset_id, payload.source)
    await _stack_placements(
        db, novel, current, _placed_at(specs, added, payload.anchor_block_id, payload.placement, payload.order)
    )
    return await _chapter_response(db, chapter)


async def _picked(
    db: AsyncSession, current: NovelChapterRevision, illustration_id: uuid.UUID
) -> tuple[list[PlacementSpec], int]:
    """지금 개정의 배치 목록과 그중 `illustration_id` 의 자리. 지금 개정의 배치가 아니면 404 `NOVEL_ILLUSTRATION_NOT_FOUND`."""
    rows = await placements_of(db, current)
    for index, row in enumerate(rows):
        if row.id == illustration_id:
            return specs_of(rows), index
    raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_ILLUSTRATION_NOT_FOUND")


@illustration_router.post(
    "/{novel_id}/chapters/{chapter_id}/illustrations/{illustration_id}/move",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def move_novel_illustration(
    chapter_id: uuid.UUID,
    illustration_id: uuid.UUID,
    payload: NovelIllustrationMoveRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """배치 하나를 다른 자리로 옮긴다(위치 확인 필요인 그림을 다시 놓을 때도 같다). 그림은 그대로다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    current = await _lock_current_revision_for_edit(db, chapter.id, payload.base_revision_id)
    specs, index = await _picked(db, current, illustration_id)
    _require_anchor(current, payload.anchor_block_id)
    rest = [*specs[:index], *specs[index + 1 :]]
    await _stack_placements(
        db, novel, current, _placed_at(rest, specs[index], payload.anchor_block_id, payload.placement, payload.order)
    )
    return await _chapter_response(db, chapter)


@illustration_router.post(
    "/{novel_id}/chapters/{chapter_id}/illustrations/{illustration_id}/replace",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def replace_novel_illustration(
    chapter_id: uuid.UUID,
    illustration_id: uuid.UUID,
    payload: NovelIllustrationReplaceRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """배치 하나의 그림만 바꾼다(자리·순서 그대로). 그림 판정은 붙이기와 같다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    current = await _lock_current_revision_for_edit(db, chapter.id, payload.base_revision_id)
    specs, index = await _picked(db, current, illustration_id)
    await _require_usable(db, novel, payload.asset_id, payload.source)
    old = specs[index]
    specs[index] = PlacementSpec(old.anchor_block_id, old.placement, payload.asset_id, payload.source)
    await _stack_placements(db, novel, current, specs)
    return await _chapter_response(db, chapter)


@illustration_router.post(
    "/{novel_id}/chapters/{chapter_id}/illustrations/{illustration_id}/detach",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def detach_novel_illustration(
    chapter_id: uuid.UUID,
    illustration_id: uuid.UUID,
    payload: NovelIllustrationDetachRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """배치 하나를 뗀다. 그림 파일은 지우지 않는다 — 앞 개정이 여전히 쓰고, 되돌리기로 돌아올 수 있다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    current = await _lock_current_revision_for_edit(db, chapter.id, payload.base_revision_id)
    specs, index = await _picked(db, current, illustration_id)
    await _stack_placements(db, novel, current, [*specs[:index], *specs[index + 1 :]])
    return await _chapter_response(db, chapter)


@illustration_router.get("/{novel_id}/illustration-candidates")
async def list_novel_illustration_candidates(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelOriginalIllustrationCandidates:
    """원작 그림 후보 — 대표 이미지와, 작가가 그 작품에서 본 상황 이미지·미디어 북 칸(원작자 본인이면 지금 발행본의 그림 전부).
    못 본 그림은 블러본으로도 싣지 않는다. 원작을 그 작가에게 열 수 없으면 빈 목록이다."""
    candidates = await original_candidates(db, novel)
    return NovelOriginalIllustrationCandidates(
        items=[
            NovelOriginalIllustrationCandidate(
                asset_id=candidate.asset.id,
                kind=candidate.kind,
                url=generate_presigned_get_url(build_display_key(candidate.asset.storage_key)),
                width=candidate.asset.width,
                height=candidate.asset.height,
            )
            for candidate in candidates
        ]
    )
