"""여러 문단 수정 요청 라우트 — 같은 장면 안의 떨어진 문단 여럿을 골라 한 번에 AI 수정을 맡긴다(과금, 202). 여러 문단 수정 스위치가
꺼져 있으면 404 다.

결과는 개정이 아니라 블록마다의 수정안(패치)이고, 상세의 `pendingBlockEdits` 로 본다. 옛 연속 범위 수정(`/ai-edits`)은 스위치와 무관하게
그대로 남는다(캐시된 옛 화면과 스위치가 꺼진 동안의 경로). 모든 응답에 `Cache-Control: no-store` 를 붙인다 — 스위치가 꺼진 동안의
404 를 브라우저가 붙잡아 두지 않게."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.novel import Novel, NovelJob
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.novel_public.no_store import NoStoreRoute
from api.novelize.access import require_novelize_access
from api.novelize.block_edit_inputs import input_estimate
from api.novelize.block_edits import BlockEdit, BlocksNotInOneSceneError, context_positions, one_scene, request_targets
from api.novelize.blocks import BlockIdsInvalidError
from api.novelize.inputs import current_revision
from api.novelize.router import (
    SessionFactory,
    _ensure_content_allows_model,
    _expire_before_new_job,
    _get_chapter,
    _novel_error,
    _owned_novel_dependency,
    _start_job,
)
from api.novelize.scenes import revision_scenes
from api.novelize.schemas import BLOCK_EDIT_MAX_BLOCKS, NovelBlockEditRequest, NovelJobResponse
from api.novelize.text import split_paragraphs


async def _require_multi_block_edit_enabled() -> None:
    if not settings.novelize_multi_block_edit_enabled:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_MULTI_BLOCK_EDIT_DISABLED")


block_edit_router = APIRouter(
    prefix="/novels",
    tags=["novels"],
    route_class=NoStoreRoute,
    dependencies=[Depends(require_novelize_access), Depends(_require_multi_block_edit_enabled)],
)


@block_edit_router.post(
    "/{novel_id}/chapters/{chapter_id}/block-edits",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def create_novel_block_edit(
    chapter_id: uuid.UUID,
    payload: NovelBlockEditRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """고른 블록(기준 개정의 블록 id)을 지시대로 고치는 작업(과금, 202). 금액은 AI 수정 단가 한 번이다(블록 수와 무관). 작업은 AI
    수정이고 범위·결과 본문 칸 대신 패치 칸을 쓴다.

    차감 전 거절: 작품 이용 제한(403), 기준 개정이 지금 개정이 아님 409 `NOVEL_REVISION_CONFLICT`, 블록이 비었거나 겹치거나 기준
    개정에 없음 422 `NOVEL_BLOCK_IDS_INVALID`, 상한보다 많음 422 `NOVEL_TOO_MANY_BLOCKS` + `maxBlocks`, 두 장면 이상에 걸침 422
    `NOVEL_BLOCKS_NOT_IN_ONE_SCENE`(장면 경계가 없는 화는 화 전체가 한 장면), 입력 견적이 상한 초과 422 `NOVEL_EDIT_INPUT_TOO_LONG` +
    `estimatedInputChars`·`maxInputChars`(고른 문단이 든 장면이 길다), 그리고 차감 함수의 금액 409·진행 중 409·잔액 429. 방이 지워진
    소설도 고칠 수 있다(원문 대화가 필요 없다)."""
    chapter = await _get_chapter(db, novel, chapter_id)
    await _ensure_content_allows_model(db, novel)
    await _expire_before_new_job(db, novel)
    current = await current_revision(db, chapter.id)
    if current is None or current.id != payload.base_revision_id:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_REVISION_CONFLICT")
    paragraphs = split_paragraphs(current.body)
    try:
        targets = request_targets(payload.block_ids, current.block_ids, paragraphs)
    except BlockIdsInvalidError:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_BLOCK_IDS_INVALID") from None
    if len(targets) > BLOCK_EDIT_MAX_BLOCKS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "NOVEL_TOO_MANY_BLOCKS", "maxBlocks": BLOCK_EDIT_MAX_BLOCKS},
        )
    scenes = await revision_scenes(db, chapter.id, current.block_ids)
    try:
        scene_id = one_scene(scenes, [target.label - 1 for target in targets])
    except BlocksNotInOneSceneError:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_BLOCKS_NOT_IN_ONE_SCENE") from None
    estimated = await input_estimate(
        db, novel, paragraphs, context_positions(scenes, scene_id), payload.instruction
    )
    cap = settings.novelize_block_edit_max_input_chars
    if estimated > cap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "NOVEL_EDIT_INPUT_TOO_LONG", "estimatedInputChars": estimated, "maxInputChars": cap},
        )
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="ai_edit",
        chapter_id=chapter.id,
        base_revision_id=current.id,
        instruction=payload.instruction,
        block_edit=BlockEdit(targets=targets, scene_id=scene_id).to_json(),
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)
