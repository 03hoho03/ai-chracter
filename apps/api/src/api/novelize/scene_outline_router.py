"""화별 장면 구성안과 구성 흐름 원고 라우트 — 장면 구성안 조회·만들기(과금)·고친 판 저장·승인, 승인한 장면 구성안으로 원고 쓰기
(과금), 구성 흐름 화 다시 만들기(과금). 구성 흐름 스위치가 꺼져 있으면 모두 404 다.

장면 구성안은 화 키마다 리비전으로 쌓고 어느 판도 지우지 않는다. 모델이 만든 판과 사용자가 고친 판 모두 미승인으로 들어오고,
승인한 판은 고치지 않는다(고치면 새 리비전). 저장·승인은 그 화의 가장 최근 리비전을 기준으로만 받고(다른 탭이 먼저 저장했으면 409),
리비전 번호는 사용자 행 잠금 아래에서 정한다 — 작업 실행의 저장도 같은 잠금을 먼저 잡는다.

만들기·원고·다시 만들기는 장 생성과 같은 꼴이다: 원작 상태·허락 재검사, 방, 주인공 이름, 모델 허용 → 죽은 작업 정리 → 원문 검사
(`scene_outline.py` 의 쓸 수 있는가) → 선차감 + 작업(202) → 실행. 차감 앞의 거절은 원장에 아무것도 남기지 않는다. 실행이 실패하거나
모델이 거절하면 한 번 전액 환불하고, 사용자가 승인하지 않는 것은 환불하지 않는다(다시 만들기는 새 유료 요청이다).

구성 흐름 화의 다시 만들기는 작업 종류를 따로 두지 않고 `chapter_regenerate` 다 — 화를 갈아 끼우는 저장·낡은 수정 미리보기 지우기·
화 수 확인이 옛 다시 만들기와 같고, 입력만 그 화가 쓴 장면 구성안으로 관문을 거쳐 만든다(작업에 장면 구성안 리비전을 싣는다). 하루
재시도 상한은 원고와 함께 그 장면 구성안 리비전으로 센다.

모든 응답에 `Cache-Control: no-store` 를 붙인다(구간 선택 라우트와 같은 이유)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import Novel, NovelEpisodeOutline, NovelJob
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.novel_public.no_store import NoStoreRoute
from api.novelize.access import require_novelize_access
from api.novelize.billing import _lock_user, job_price
from api.novelize.inputs import SourceChangedError
from api.novelize.outline import InputTooLargeError, SectionLockedError, SelectionMissingError
from api.novelize.router import (
    SessionFactory,
    _chapter_models,
    _ensure_content_allows_model,
    _expire_before_new_job,
    _get_chapter,
    _novel_error,
    _owned_novel_dependency,
    _require_chapter_model,
    _require_protagonist_name,
    _source_room_id,
    _start_job,
)
from api.novelize.scene_outline import (
    EpisodeNotFoundError,
    EpisodeOutlineMissingError,
    EpisodeOutlineStaleError,
    EpisodeOutOfOrderError,
    EpisodeWrittenError,
    OutlineMissingError,
    OutlineStaleError,
    ScenesInvalidError,
    approved_episode,
    chapter_turn_cap_exceeded,
    checked_scenes,
    episode_basis_holds,
    episode_ranges_for_edit,
    latest_episode_outline,
    load_outline_chapter_source,
    load_scene_outline_source,
    load_scene_source,
    written_episodes,
)
from api.novelize.schemas import (
    NovelEpisodeOutlineApproveRequest,
    NovelEpisodeOutlineCreateRequest,
    NovelEpisodeOutlineSaveRequest,
    NovelEpisodeOutlineState,
    NovelEpisodeOutlineView,
    NovelJobResponse,
    NovelOutlineChapterRequest,
    NovelOutlineModel,
    NovelSceneView,
    NovelSourceRange,
)
from api.novelize.selection_router import _require_outline_flow_enabled
from api.novelize.source import segment_hash

scene_outline_router = APIRouter(
    prefix="/novels",
    tags=["novels"],
    route_class=NoStoreRoute,
    dependencies=[Depends(require_novelize_access), Depends(_require_outline_flow_enabled)],
)

# 원문 검사 실패 → 응답. 위에서부터 처음 맞는 종류다(아래 둘은 위 종류들의 부모라 맨 뒤).
_REFUSALS: tuple[tuple[type[SourceChangedError], int, str], ...] = (
    (OutlineMissingError, status.HTTP_409_CONFLICT, "NOVEL_OUTLINE_REQUIRED"),
    (EpisodeNotFoundError, status.HTTP_404_NOT_FOUND, "NOVEL_OUTLINE_EPISODE_NOT_FOUND"),
    (OutlineStaleError, status.HTTP_409_CONFLICT, "NOVEL_OUTLINE_STALE"),
    (EpisodeWrittenError, status.HTTP_409_CONFLICT, "NOVEL_OUTLINE_EPISODE_WRITTEN"),
    (EpisodeOutOfOrderError, status.HTTP_409_CONFLICT, "NOVEL_OUTLINE_EPISODE_OUT_OF_ORDER"),
    (EpisodeOutlineMissingError, status.HTTP_409_CONFLICT, "NOVEL_EPISODE_OUTLINE_REQUIRED"),
    (EpisodeOutlineStaleError, status.HTTP_409_CONFLICT, "NOVEL_EPISODE_OUTLINE_STALE"),
    (SelectionMissingError, status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_REQUIRED"),
    (SectionLockedError, status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_SOURCE_SECTION_LOCKED"),
    (SourceChangedError, status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED"),
)


def _refusal(exc: SourceChangedError) -> HTTPException:
    if isinstance(exc, InputTooLargeError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "NOVEL_OUTLINE_INPUT_TOO_LARGE",
                "estimatedInputTokens": exc.estimated,
                "maxInputTokens": exc.cap,
            },
        )
    _, status_code, code = next(refusal for refusal in _REFUSALS if isinstance(exc, refusal[0]))
    return _novel_error(status_code, code)


async def _view(db: AsyncSession, novel_id: uuid.UUID, row: NovelEpisodeOutline) -> NovelEpisodeOutlineView:
    return NovelEpisodeOutlineView(
        revision=row.revision,
        source=row.source,
        model=row.model,
        approved_at=row.approved_at,
        created_at=row.created_at,
        stale=not await episode_basis_holds(db, novel_id, row.outline_id, row.episode_key),
        scenes=[
            NovelSceneView(
                id=scene["id"],
                title=scene["title"],
                summary=scene["summary"],
                purpose=scene["purpose"],
                characters=scene["characters"],
                flashback=scene["flashback"],
                basis=[
                    NovelSourceRange(
                        start_message_id=uuid.UUID(basis["start_message_id"]),
                        end_message_id=uuid.UUID(basis["end_message_id"]),
                    )
                    for basis in scene["basis"]
                ],
            )
            for scene in row.scenes
        ],
    )


async def _state(db: AsyncSession, novel: Novel, key: uuid.UUID) -> NovelEpisodeOutlineState:
    latest = await latest_episode_outline(db, novel.id, key)
    approved = await latest_episode_outline(db, novel.id, key, approved=True)
    draft = latest if latest is not None and latest.approved_at is None else None
    options, _ = await _chapter_models(db, novel.user_id)
    return NovelEpisodeOutlineState(
        episode_key=key,
        approved=None if approved is None else await _view(db, novel.id, approved),
        draft=None if draft is None else await _view(db, novel.id, draft),
        models=[
            NovelOutlineModel(id=option.id, name=option.name, cost=job_price("episode_outline_generate", option.id))
            for option in options
        ],
        chapter_models=[
            NovelOutlineModel(id=option.id, name=option.name, cost=job_price("outline_chapter_generate", option.id))
            for option in options
        ],
        chapter_id=(await written_episodes(db, novel.id)).get(str(key)),
    )


async def _locked_latest(db: AsyncSession, novel: Novel, key: uuid.UUID, revision: int) -> NovelEpisodeOutline:
    """사용자 행을 잠근 뒤 그 화의 가장 최근 리비전을 읽는다. 그것이 `revision` 이 아니면(또는 없으면) 409
    `NOVEL_EPISODE_OUTLINE_CONFLICT`."""
    await _lock_user(db, novel.user_id)
    latest = await latest_episode_outline(db, novel.id, key)
    if latest is None or latest.revision != revision:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_EPISODE_OUTLINE_CONFLICT")
    return latest


async def _check_paid_request(
    db: AsyncSession, novel: Novel, request: NovelEpisodeOutlineCreateRequest | NovelOutlineChapterRequest
) -> None:
    """과금 요청 셋의 공통 앞 검사 — 원작 상태·허락(403), 방(409), 주인공 이름(422), 모델 허용(403), 그리고 죽은 작업 정리·커밋."""
    await _ensure_content_allows_model(db, novel)
    _source_room_id(novel)
    _require_protagonist_name(novel)
    await _require_chapter_model(db, novel, request.model)
    await _expire_before_new_job(db, novel)


@scene_outline_router.get("/{novel_id}/outline/episodes/{episode_key}/scenes")
async def get_episode_outline(
    episode_key: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelEpisodeOutlineState:
    """한 화의 장면 구성안 화면 상태 — 승인본·초안(낡음 표시 포함), 장면 구성안·원고 가격, 이미 쓴 화. 승인한 전체 구성안이 없으면 409
    `NOVEL_OUTLINE_REQUIRED`, 그 구성안에 없는 화 키면 404 `NOVEL_OUTLINE_EPISODE_NOT_FOUND`."""
    try:
        await approved_episode(db, novel.id, episode_key)
    except SourceChangedError as exc:
        raise _refusal(exc) from None
    return await _state(db, novel, episode_key)


@scene_outline_router.post(
    "/{novel_id}/outline/episodes/{episode_key}/scenes",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def create_episode_outline(
    episode_key: uuid.UUID,
    payload: NovelEpisodeOutlineCreateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """지금 승인한 전체 구성안의 그 화로 장면 구성안을 만드는 작업(과금, 202). 금액은 고른 모델의 장면 구성안 고정가다.

    차감 전 거절: 작품 이용 제한·소설화 허락(403), 방 없음 409 `NOVEL_ROOM_GONE`, 주인공 이름 422, 모델 허용 403, 승인 구성안 없음 409
    `NOVEL_OUTLINE_REQUIRED`, 화 키 없음 404 `NOVEL_OUTLINE_EPISODE_NOT_FOUND`, 구성안이 낡음 409 `NOVEL_OUTLINE_STALE`, 이미 원고가 된 화
    409 `NOVEL_OUTLINE_EPISODE_WRITTEN`, 화 근거가 승인 뒤 화가 됨 422 `NOVEL_SOURCE_SECTION_LOCKED`, 원문이 바뀜 409
    `NOVEL_SOURCE_SELECTION_SOURCE_CHANGED`, 입력 견적 상한 초과 422 `NOVEL_OUTLINE_INPUT_TOO_LARGE`, 그리고 차감 함수의 금액 409·진행
    중 409·잔액 429."""
    await _check_paid_request(db, novel, payload)
    try:
        source = await load_scene_outline_source(db, novel, episode_key, outline_id=None)
    except SourceChangedError as exc:
        raise _refusal(exc) from None
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="episode_outline_generate",
        model=payload.model,
        outline_id=source.outline.id,
        outline_episode_key=episode_key,
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


@scene_outline_router.put(
    "/{novel_id}/outline/episodes/{episode_key}/scenes/draft", dependencies=[Depends(require_legal_consent)]
)
async def save_episode_outline_draft(
    episode_key: uuid.UUID,
    payload: NovelEpisodeOutlineSaveRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelEpisodeOutlineState:
    """고친 장면 구성안을 기준 리비전 위의 새 미승인 리비전(출처 edit)으로 저장한다(무과금). 기준이 그 화의 가장 최근 리비전이 아니면 409
    `NOVEL_EPISODE_OUTLINE_CONFLICT`, 기준 판이 낡았으면 409 `NOVEL_EPISODE_OUTLINE_STALE`, 장면 목록이 규칙을 어기면 422
    `NOVEL_EPISODE_OUTLINE_INVALID` + `reason`(`scene_outline.checked_scenes`). 방이 지워졌으면 409 `NOVEL_ROOM_GONE`."""
    room_id = _source_room_id(novel)
    base = await _locked_latest(db, novel, episode_key, payload.base_revision)
    if not await episode_basis_holds(db, novel.id, base.outline_id, episode_key):
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_EPISODE_OUTLINE_STALE")
    try:
        outline, ranges = await episode_ranges_for_edit(db, novel, episode_key)
        scenes = await checked_scenes(db, room_id, ranges, {scene["id"] for scene in base.scenes}, payload.scenes)
    except SourceChangedError as exc:
        raise _refusal(exc) from None
    except ScenesInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "NOVEL_EPISODE_OUTLINE_INVALID", "reason": exc.reason},
        ) from None
    db.add(
        NovelEpisodeOutline(
            novel_id=novel.id,
            outline_id=outline.id,
            episode_key=episode_key,
            revision=base.revision + 1,
            source="edit",
            scenes=scenes,
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_EPISODE_OUTLINE_CONFLICT") from None
    await db.commit()
    return await _state(db, novel, episode_key)


@scene_outline_router.post(
    "/{novel_id}/outline/episodes/{episode_key}/scenes/approve", dependencies=[Depends(require_legal_consent)]
)
async def approve_episode_outline(
    episode_key: uuid.UUID,
    payload: NovelEpisodeOutlineApproveRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelEpisodeOutlineState:
    """그 화의 가장 최근 리비전을 승인한다(무과금). 이미 승인한 최신 리비전이면 그대로 돌려준다(두 번 누름). 최신이 아니면 409
    `NOVEL_EPISODE_OUTLINE_CONFLICT`, 낡은 판이면 409 `NOVEL_EPISODE_OUTLINE_STALE`."""
    latest = await _locked_latest(db, novel, episode_key, payload.revision)
    if latest.approved_at is None:
        if not await episode_basis_holds(db, novel.id, latest.outline_id, episode_key):
            raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_EPISODE_OUTLINE_STALE")
        await db.execute(
            update(NovelEpisodeOutline)
            .where(NovelEpisodeOutline.id == latest.id, NovelEpisodeOutline.approved_at.is_(None))
            .values(approved_at=func.now())
        )
        await db.commit()
    return await _state(db, novel, episode_key)


@scene_outline_router.post(
    "/{novel_id}/outline/episodes/{episode_key}/chapter",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def create_outline_chapter(
    episode_key: uuid.UUID,
    payload: NovelOutlineChapterRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """그 화의 승인한 장면 구성안으로 원고(화 하나)를 쓰는 작업(과금, 202). 금액은 고른 모델의 화 단가 하나다. 화는 다음 화 번호를 받는다.

    차감 전 거절은 장면 구성안 만들기와 같은 것에 더해: 구성안에서 앞 화가 아직 원고가 아님 409 `NOVEL_OUTLINE_EPISODE_OUT_OF_ORDER`,
    승인한 장면 구성안 없음 409 `NOVEL_EPISODE_OUTLINE_REQUIRED`, 장면 구성안이 낡음(그 화 근거가 바뀜) 409 `NOVEL_EPISODE_OUTLINE_STALE`,
    장면이 쓰는 턴 수가 고른 모델의 턴 상한 초과 409 `NOVEL_MODEL_INELIGIBLE` + `reason: too_many_turns`. 같은 화를 이미 쓴 화가 있으면
    차감 함수도 사용자 잠금 아래에서 409 `NOVEL_OUTLINE_EPISODE_WRITTEN` 으로 막는다."""
    await _check_paid_request(db, novel, payload)
    try:
        source = await load_outline_chapter_source(db, novel, episode_key, episode_outline_id=None)
    except SourceChangedError as exc:
        raise _refusal(exc) from None
    if chapter_turn_cap_exceeded(source.scenes, payload.model):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NOVEL_MODEL_INELIGIBLE", "reason": "too_many_turns"},
        )
    first, last = source.scenes.messages[0], source.scenes.messages[-1]
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="outline_chapter_generate",
        model=payload.model,
        episode_outline_id=source.episode_outline.id,
        outline_episode_key=episode_key,
        start_message_id=first.id,
        start_message_created_at=first.created_at,
        end_message_id=last.id,
        end_message_created_at=last.created_at,
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


@scene_outline_router.post(
    "/{novel_id}/outline/chapters/{chapter_id}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def regenerate_outline_chapter(
    chapter_id: uuid.UUID,
    payload: NovelOutlineChapterRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """구성 흐름 화 하나를 같은 장면 구성안으로 다시 쓰는 작업(과금, 202). 결과는 그 화의 새 개정으로 쌓인다(화 수·화 번호 그대로).
    금액은 고른 모델의 화 단가다.

    차감 전 거절: 옛 흐름 화 409 `NOVEL_CHAPTER_NOT_OUTLINE_FLOW`(옛 다시 만들기 라우트로 한다), 작품 상태·방·주인공 이름·모델 허용,
    화를 만든 때와 장면 원문이 다름 409 `NOVEL_SOURCE_CHANGED`, 그리고 차감 함수의 모델 적격성 409·금액 409·진행 중 409·하루 상한
    429·잔액 429. 없는 화는 404 `NOVEL_CHAPTER_NOT_FOUND`."""
    chapter = await _get_chapter(db, novel, chapter_id)
    if chapter.episode_outline_id is None:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_CHAPTER_NOT_OUTLINE_FLOW")
    await _check_paid_request(db, novel, payload)
    room_id = _source_room_id(novel)
    episode_outline = await db.get(NovelEpisodeOutline, chapter.episode_outline_id)
    try:
        if episode_outline is None:
            raise SourceChangedError(f"chapter={chapter.id} 장면 구성안이 지워졌다")
        scenes = await load_scene_source(db, room_id, episode_outline.scenes)
    except SourceChangedError:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_CHANGED") from None
    if segment_hash(scenes.messages) != chapter.source_hash:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_CHANGED")
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="chapter_regenerate",
        model=payload.model,
        batch_id=chapter.batch_id,
        chapter_id=chapter.id,
        episode_outline_id=episode_outline.id,
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)
