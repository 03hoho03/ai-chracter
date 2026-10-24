"""소설 전체 구성안 라우트 — 조회·만들기(과금)·고친 판 저장·승인. 구성 흐름 스위치가 꺼져 있으면 모두 404 다.

구성안은 리비전으로 쌓고 어느 판도 지우지 않는다. 모델이 만든 판과 사용자가 고친 판 모두 미승인으로 들어오고, 승인한 판은 고치지
않는다 — 고치면 그 위의 새 리비전이 된다(다음 단계가 승인한 판을 근거로 삼으므로). 저장·승인은 가장 최근 리비전을 기준으로만
받는다(다른 탭이 먼저 저장했으면 409). 리비전 번호는 사용자 행 잠금 아래에서 정한다 — 작업 실행의 저장도 같은 잠금을 먼저 잡는다.

만들기는 장 생성과 같은 꼴이다: 원작 상태·허락 재검사, 방, 주인공 이름, 모델 허용 → 죽은 작업 정리 → 승인한 구간 선택을 관문으로
읽어 검사(선택 없음·화와 겹침·원문 변경·입력 상한) → 선차감 + 작업(202) → 실행. 차감 앞의 거절은 원장에 아무것도 남기지 않는다.
실행이 실패하거나 모델이 거절하면 한 번 전액 환불하고, 쓸 수 있는 구성안을 사용자가 승인하지 않는 것은 환불하지 않는다(다시 만들기는
새 유료 요청이다).

모든 응답에 `Cache-Control: no-store` 를 붙인다(구간 선택 라우트와 같은 이유)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.novel import Novel, NovelJob, NovelOutline
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.novel_public.no_store import NoStoreRoute
from api.novelize.access import require_novelize_access
from api.novelize.billing import _lock_user, job_price
from api.novelize.inputs import SourceChangedError
from api.novelize.outline import (
    InputTooLargeError,
    OutlineInvalidError,
    SectionLockedError,
    SelectionMissingError,
    _include_rows,
    checked_episodes,
    load_outline_source,
    selection_still_holds,
    stored_episode_keys,
)
from api.novelize.router import (
    SessionFactory,
    _chapter_models,
    _ensure_content_allows_model,
    _expire_before_new_job,
    _novel_error,
    _owned_novel_dependency,
    _require_chapter_model,
    _require_protagonist_name,
    _source_room_id,
    _start_job,
)
from api.novelize.scene_outline import episode_progress
from api.novelize.schemas import (
    NovelJobResponse,
    NovelOutlineApproveRequest,
    NovelOutlineCreateRequest,
    NovelOutlineEpisodeView,
    NovelOutlineModel,
    NovelOutlineSaveRequest,
    NovelOutlineState,
    NovelOutlineView,
    NovelSourceRange,
)
from api.novelize.selection import selection_sections
from api.novelize.selection_router import _require_outline_flow_enabled, section_views

outline_router = APIRouter(
    prefix="/novels",
    tags=["novels"],
    route_class=NoStoreRoute,
    dependencies=[Depends(require_novelize_access), Depends(_require_outline_flow_enabled)],
)


async def _latest(db: AsyncSession, novel_id: uuid.UUID, *, approved: bool = False) -> NovelOutline | None:
    query = select(NovelOutline).where(NovelOutline.novel_id == novel_id)
    if approved:
        query = query.where(NovelOutline.approved_at.is_not(None))
    outline: NovelOutline | None = await db.scalar(
        query.order_by(NovelOutline.revision.desc()).limit(1).execution_options(populate_existing=True)
    )
    return outline


async def _view(db: AsyncSession, outline: NovelOutline, room_id: uuid.UUID | None) -> NovelOutlineView:
    keys = [uuid.UUID(str(episode["key"])) for episode in outline.episodes]
    progress = await episode_progress(db, outline.novel_id, keys)
    stale = not await selection_still_holds(db, outline.novel_id, outline.selection_id)
    return NovelOutlineView(
        revision=outline.revision,
        source=outline.source,
        model=outline.model,
        approved_at=outline.approved_at,
        created_at=outline.created_at,
        stale=stale,
        source_sections=(
            await section_views(db, room_id, _include_rows(await selection_sections(db, outline.selection_id)))
            if stale
            else None
        ),
        episodes=[
            NovelOutlineEpisodeView(
                key=key,
                title=episode["title"],
                summary=episode["summary"],
                goal=episode["goal"],
                basis=[
                    NovelSourceRange(
                        start_message_id=uuid.UUID(basis["start_message_id"]),
                        end_message_id=uuid.UUID(basis["end_message_id"]),
                    )
                    for basis in episode["basis"]
                ],
                chapter_id=progress[key][0],
                scene_outline=progress[key][1],
            )
            for key, episode in zip(keys, outline.episodes, strict=True)
        ],
    )


async def _state(db: AsyncSession, novel: Novel) -> NovelOutlineState:
    latest = await _latest(db, novel.id)
    approved = await _latest(db, novel.id, approved=True)
    draft = latest if latest is not None and latest.approved_at is None else None
    chapter_models, _ = await _chapter_models(db, novel.user_id)
    return NovelOutlineState(
        approved=None if approved is None else await _view(db, approved, novel.chat_room_id),
        draft=None if draft is None else await _view(db, draft, novel.chat_room_id),
        max_episodes=settings.novelize_outline_max_episodes,
        models=[
            NovelOutlineModel(id=option.id, name=option.name, cost=job_price("outline_generate", option.id))
            for option in chapter_models
        ],
    )


async def _locked_latest(db: AsyncSession, novel: Novel, revision: int) -> NovelOutline:
    """사용자 행을 잠근 뒤 가장 최근 리비전을 읽는다. 그것이 `revision` 이 아니면(또는 구성안이 없으면) 409
    `NOVEL_OUTLINE_CONFLICT`."""
    await _lock_user(db, novel.user_id)
    latest = await _latest(db, novel.id)
    if latest is None or latest.revision != revision:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_OUTLINE_CONFLICT")
    return latest


@outline_router.get("/{novel_id}/outline")
async def get_novel_outline(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelOutlineState:
    """전체 구성안 화면의 상태 — 승인본·초안(낡음 표시 포함)과 화 수 상한, 고를 수 있는 모델과 구성안 가격."""
    return await _state(db, novel)


@outline_router.post(
    "/{novel_id}/outline", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_legal_consent)]
)
async def create_novel_outline(
    payload: NovelOutlineCreateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """지금 승인한 구간 선택으로 전체 구성안을 만드는 작업(과금, 202). 금액은 고른 모델의 구성안 고정가다.

    차감 전 거절: 작품 이용 제한·소설화 허락(403), 방 없음 409 `NOVEL_ROOM_GONE`, 주인공 이름 422, 모델 허용 403, 승인한 선택 없음
    409 `NOVEL_SOURCE_SELECTION_REQUIRED`, include 구간이 승인 뒤 화가 됨 422 `NOVEL_SOURCE_SECTION_LOCKED`, 고른 구간의 원문이 바뀜
    409 `NOVEL_SOURCE_SELECTION_SOURCE_CHANGED`(다시 골라 승인한다), 입력 견적이 상한 초과 422 `NOVEL_OUTLINE_INPUT_TOO_LARGE` +
    `estimatedInputTokens`·`maxInputTokens`(구간을 줄여 다시 승인한다), 그리고 차감 함수의 금액 409·진행 중 409·잔액 429."""
    await _ensure_content_allows_model(db, novel)
    _source_room_id(novel)
    _require_protagonist_name(novel)
    await _require_chapter_model(db, novel, payload.model)
    await _expire_before_new_job(db, novel)
    try:
        await load_outline_source(db, novel)
    except SelectionMissingError:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_REQUIRED") from None
    except SectionLockedError:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_SOURCE_SECTION_LOCKED") from None
    except InputTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "NOVEL_OUTLINE_INPUT_TOO_LARGE",
                "estimatedInputTokens": exc.estimated,
                "maxInputTokens": exc.cap,
            },
        ) from None
    except SourceChangedError:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED") from None
    job = NovelJob(novel_id=novel.id, user_id=novel.user_id, kind="outline_generate", model=payload.model)
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


@outline_router.put("/{novel_id}/outline/draft", dependencies=[Depends(require_legal_consent)])
async def save_novel_outline_draft(
    payload: NovelOutlineSaveRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelOutlineState:
    """고친 구성안을 기준 리비전 위의 새 미승인 리비전(출처 edit)으로 저장한다(무과금). 기준이 가장 최근 리비전이 아니면 409
    `NOVEL_OUTLINE_CONFLICT`, 기준 판이 낡았으면 409 `NOVEL_OUTLINE_STALE`, 화 목록이 규칙을 어기면 422 `NOVEL_OUTLINE_INVALID` +
    `reason`(`outline.checked_episodes`). 방이 지워졌으면 409 `NOVEL_ROOM_GONE`."""
    room_id = _source_room_id(novel)
    base = await _locked_latest(db, novel, payload.base_revision)
    if not await selection_still_holds(db, novel.id, base.selection_id):
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_OUTLINE_STALE")
    try:
        episodes = await checked_episodes(
            db, room_id, base.selection_id, stored_episode_keys(base.episodes), payload.episodes
        )
    except OutlineInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "NOVEL_OUTLINE_INVALID", "reason": exc.reason},
        ) from None
    db.add(
        NovelOutline(
            novel_id=novel.id,
            revision=base.revision + 1,
            source="edit",
            selection_id=base.selection_id,
            episodes=episodes,
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_OUTLINE_CONFLICT") from None
    await db.commit()
    return await _state(db, novel)


@outline_router.post("/{novel_id}/outline/approve", dependencies=[Depends(require_legal_consent)])
async def approve_novel_outline(
    payload: NovelOutlineApproveRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelOutlineState:
    """가장 최근 리비전을 승인한다(무과금). 이미 승인한 최신 리비전이면 그대로 돌려준다(두 번 누름). 최신이 아니면 409
    `NOVEL_OUTLINE_CONFLICT`, 낡은 판이면 409 `NOVEL_OUTLINE_STALE`."""
    latest = await _locked_latest(db, novel, payload.revision)
    if latest.approved_at is None:
        if not await selection_still_holds(db, novel.id, latest.selection_id):
            raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_OUTLINE_STALE")
        await db.execute(
            update(NovelOutline)
            .where(NovelOutline.id == latest.id, NovelOutline.approved_at.is_(None))
            .values(approved_at=func.now())
        )
        await db.commit()
    return await _state(db, novel)
