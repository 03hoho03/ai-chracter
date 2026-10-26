"""여러 문단 수정 라우트 — 같은 장면 안의 떨어진 문단 여럿을 골라 한 번에 AI 수정을 맡기고(과금, 202), 받은 수정안(패치)을 단위마다
적용·버리고, 묶음 재검사를 묻는다(무료).

결과는 개정이 아니라 블록마다의 수정안이고, 상세의 `pendingBlockEdits` 로 본다. 옛 연속 범위 수정(`/ai-edits`)은 스위치와 무관하게
그대로 남는다(캐시된 옛 화면과 스위치가 꺼진 동안의 경로).

**스위치**: 새 요청과 재검사(모델을 부르는 둘)만 여러 문단 수정 스위치 뒤에 있고(꺼지면 404), 적용·버리기는 스위치와 무관하다 — 켰다
끈 뒤에도 이미 받은 수정안을 쓰거나 버릴 수 있어야 한다(버리지 못하면 사용자 글에서 나온 문단이 행에 남는다). 그래서 라우터가 둘이다.
모든 응답에 `Cache-Control: no-store` 를 붙인다 — 스위치가 꺼진 동안의 404 를 브라우저가 붙잡아 두지 않게.

**잠금**: 적용은 옛 적용과 같이 작업 행 → 장 행 순서다(소설·마지막 묶음 삭제와 같은 순서). 같은 작업의 두 단위를 동시에 적용하면
작업 행에서 줄을 서고, 다른 작업이 같은 블록을 고치면 장 행에서 줄을 선 뒤 뒤 요청이 바뀐 블록을 보고 409 다(덮어쓰지 않는다).
재검사는 모델을 부르는 동안 아무 잠금도 쥐지 않고, 판정을 쓸 때 작업 행을 잡아 그사이 바뀐 것이 없는지 다시 본다."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.rate_limit import check_rate_limit
from api.core.rate_limit_gate import _too_many_requests
from api.db.models.novel import Novel, NovelJob
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from api.llm.dependencies import get_llm_client
from api.novel_public.no_store import NoStoreRoute
from api.novelize.access import require_novelize_access
from api.novelize.block_edit_inputs import build_recheck_prompt, input_estimate
from api.novelize.block_edits import (
    BlockEdit,
    BlockEditPatch,
    BlocksNotInOneSceneError,
    RecheckNotNeededError,
    UnitNotApplicableError,
    UnitNotFoundError,
    applied_body,
    context_positions,
    dismissed_all,
    has_pending,
    one_scene,
    recheck_plan,
    request_targets,
    unit_patches,
    unit_stale_ids,
    with_applied,
    with_dismissed,
    with_split,
)
from api.novelize.blocks import BlockIdsInvalidError, build_revision
from api.novelize.inputs import current_revision, resolve_novel_call_route
from api.novelize.job_variants import variant_of
from api.novelize.prompts import NovelizeRecheckResult
from api.novelize.router import (
    SessionFactory,
    _chapter_response,
    _ensure_content_allows_model,
    _erase_stale_previews,
    _expire_before_new_job,
    _get_chapter,
    _lock_current_revision,
    _novel_error,
    _owned_novel_dependency,
    _stack_revision,
    _start_job,
)
from api.novelize.scenes import revision_scenes
from api.novelize.schemas import (
    BLOCK_EDIT_MAX_BLOCKS,
    CHAPTER_BODY_MAX_LENGTH,
    NovelBlockEditRequest,
    NovelBundleRecheckResponse,
    NovelChapterResponse,
    NovelJobResponse,
    NovelPatchDismissRequest,
    NovelPatchUnitRequest,
)
from api.novelize.text import split_paragraphs

logger = logging.getLogger(__name__)

_RECHECK_SCOPE = "novel-recheck"
_HOUR_SECONDS = 3600
# 재검사 판정 이유는 문안이 짧게 쓰라고 하지만 넘쳐 와도 버리지 않고 자른다.
_RECHECK_REASON_MAX_CHARS = 100


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


# ── 적용·버리기(스위치 무관) ────────────────────────────────────────────────
block_patch_router = APIRouter(
    prefix="/novels", tags=["novels"], route_class=NoStoreRoute, dependencies=[Depends(require_novelize_access)]
)


def _not_applicable() -> HTTPException:
    return _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_NOT_APPLICABLE")


async def _patch_job(db: AsyncSession, novel: Novel, job_id: uuid.UUID, *, lock: bool) -> tuple[NovelJob, BlockEdit]:
    """그 소설의 끝난 패치 작업과 그 칸. 없으면 404 `NOVEL_JOB_NOT_FOUND`, 패치 작업이 아니거나·성공하지 않았거나·전부 버렸거나·화가
    지워졌으면 409 `NOVEL_JOB_NOT_APPLICABLE`. `lock` 이면 작업 행을 `FOR NO KEY UPDATE` 로 잡는다."""
    query = select(NovelJob).where(NovelJob.id == job_id, NovelJob.novel_id == novel.id)
    if lock:
        query = query.with_for_update(key_share=True)
    job = await db.scalar(query.execution_options(populate_existing=True))
    if job is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_JOB_NOT_FOUND")
    if (
        variant_of(job) != "block_edit"
        or job.status != "succeeded"
        or job.dismissed_at is not None
        or job.chapter_id is None
    ):
        raise _not_applicable()
    return job, BlockEdit.model_validate(job.block_edit)


def _unit(edit: BlockEdit, *, patch_id: str | None, bundle_id: str | None) -> list[BlockEditPatch]:
    try:
        return unit_patches(edit, patch_id=patch_id, bundle_id=bundle_id)
    except UnitNotFoundError:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_PATCH_NOT_FOUND") from None
    except UnitNotApplicableError:
        raise _not_applicable() from None


def _settled_values(edit: BlockEdit) -> dict[str, object]:
    """작업 행에 쓸 칸 — 대기 수정안이 하나도 남지 않으면 지시문도 비운다(처리방침의 즉시 삭제)."""
    values: dict[str, object] = {"block_edit": edit.to_json()}
    if not has_pending(edit):
        values["instruction"] = None
    return values


@block_patch_router.post(
    "/{novel_id}/jobs/{job_id}/patches/apply",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def apply_novel_block_edit(
    job_id: uuid.UUID,
    payload: NovelPatchUnitRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """여러 문단 수정의 적용 단위(묶음에 들지 않은 수정안 하나 `patchId`, 또는 묶음 하나 `bundleId`)를 새 개정 하나로 쌓는다(무과금).
    지금 화를 앞에서부터 걸으며 단위의 블록만 수정안 문단으로 바꾸고 그 밖의 문단·블록 id 는 그대로 둔다(블록 id 는 그 블록 자리의
    문단 하나가 잇는다 — 삽화 배치가 따라간다). 적용한 수정안은 문단을 비우고 적용 개정 id 를 남기며, 작업의 결과 개정은 마지막으로
    적용한 개정이 된다. 대기 수정안이 더 없으면 지시문도 비운다. 새 개정 때문에 쓸 수 없게 된 다른 수정안(다른 작업이 같은 블록을
    고친 것 등)은 커밋 뒤 비우기가 낡음으로 바꾼다.

    거절(아무것도 쓰지 않는다): 작업 없음 404 `NOVEL_JOB_NOT_FOUND`, 패치 작업이 아님·전부 버림·화가 지워짐·묶음에 든 수정안을
    혼자·이미 끝난 수정안 409 `NOVEL_JOB_NOT_APPLICABLE`, 모르는 수정안·묶음 404 `NOVEL_PATCH_NOT_FOUND`, 단위 원소 중 하나라도
    그 블록이 바뀌었거나 없음 409 `NOVEL_PATCH_STALE` + `stalePatchIds`(묶음은 통째로 거절), 적용한 화가 직접 수정 본문 상한을 넘음
    409 `NOVEL_CHAPTER_TOO_LONG` + `maxChars`."""
    job, edit = await _patch_job(db, novel, job_id, lock=True)
    patches = _unit(edit, patch_id=payload.patch_id, bundle_id=payload.bundle_id)
    assert job.chapter_id is not None  # `_patch_job` 이 걸렀다
    current = await _lock_current_revision(db, job.chapter_id)
    if current is None:
        raise _not_applicable()
    paragraphs = split_paragraphs(current.body)
    try:
        stale = unit_stale_ids(patches, current.block_ids, paragraphs)
    except UnitNotApplicableError:
        raise _not_applicable() from None
    if stale:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "NOVEL_PATCH_STALE", "stalePatchIds": stale}
        )
    new_paragraphs, block_ids = applied_body(patches, current.block_ids, paragraphs)
    body = "\n\n".join(new_paragraphs)
    # 넘긴 화는 그 뒤 직접 수정이 늘 상한에 걸려 거절된다. 옛 연속 범위 적용에는 없는 가드라 그쪽은 그대로 둔다.
    if len(body) > CHAPTER_BODY_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NOVEL_CHAPTER_TOO_LONG", "maxChars": CHAPTER_BODY_MAX_LENGTH},
        )
    revision = await _stack_revision(
        db, novel, current, build_revision(body=body, source="ai_edit", block_ids=block_ids)
    )
    applied = with_applied(edit, [patch.id for patch in patches], revision.id)
    await db.execute(
        update(NovelJob)
        .where(NovelJob.id == job.id)
        .values(result_revision_id=revision.id, **_settled_values(applied))
    )
    await db.commit()
    await _erase_stale_previews(db, current.chapter_id)
    return await _chapter_response(db, await _get_chapter(db, novel, current.chapter_id))


@block_patch_router.post(
    "/{novel_id}/jobs/{job_id}/patches/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_legal_consent)],
)
async def dismiss_novel_block_edit(
    job_id: uuid.UUID,
    payload: NovelPatchDismissRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """여러 문단 수정의 수정안을 적용하지 않고 버린다(환불 없음). 적용 단위 하나(`patchId`·`bundleId`)면 그 수정안들을 — 대기든 낡음이든
    — 버림으로 바꾸고 문단과 그 블록의 기준 해시를 지운다(짧은 문단은 해시에서 글을 되찾을 수 있다). 대기 수정안이 더 없으면 지시문도
    비운다. `all` 이면 남은 수정안 전부를 버리고 버린 시각을 찍으며 모든 문단·묶음 이유·기준 해시와 지시문을 지운다(일부를 적용한
    작업에도 된다). 상태·블록 id 는 건수 기록으로 남는다.

    거절은 적용과 같다(404 `NOVEL_JOB_NOT_FOUND`·`NOVEL_PATCH_NOT_FOUND`, 409 `NOVEL_JOB_NOT_APPLICABLE` — 이미 적용·버린 수정안,
    묶음에 든 수정안을 혼자, 버릴 것이 없는 `all`). 적용과 같은 작업 행을 잠가 같은 단위의 적용과 버리기가 겹치면 뒤 요청이 409 다."""
    job, edit = await _patch_job(db, novel, job_id, lock=True)
    if payload.all:
        if not any(patch.state in ("pending", "stale") for patch in edit.patches):
            raise _not_applicable()
        await db.execute(
            update(NovelJob)
            .where(NovelJob.id == job.id)
            .values(dismissed_at=func.now(), instruction=None, block_edit=dismissed_all(edit).to_json())
        )
    else:
        patches = _unit(edit, patch_id=payload.patch_id, bundle_id=payload.bundle_id)
        try:
            dismissed = with_dismissed(edit, [patch.id for patch in patches])
        except UnitNotApplicableError:
            raise _not_applicable() from None
        await db.execute(update(NovelJob).where(NovelJob.id == job.id).values(**_settled_values(dismissed)))
    await db.commit()


# ── 묶음 재검사(스위치 뒤) ──────────────────────────────────────────────────
async def _check_recheck_limit(user_id: uuid.UUID) -> None:
    """무과금 호출의 남용 상한(시간당 고정 창). 면제 계정도 센다 — 과금이 없어 이 상한이 유일한 제동이다. Redis 가 실패하면 경계
    제안과 같이 통과시킨다."""
    try:
        retry_after = await check_rate_limit(
            _RECHECK_SCOPE, str(user_id), settings.novelize_recheck_hourly_limit, window_seconds=_HOUR_SECONDS
        )
    except RedisError:
        logger.warning("소설 묶음 재검사 상한 검사 실패 — 통과시킨다", exc_info=True)
        return
    if retry_after > 0:
        raise _too_many_requests(user_id, "novelize", retry_after)


@block_edit_router.post(
    "/{novel_id}/jobs/{job_id}/bundles/{bundle_id}/recheck", dependencies=[Depends(require_legal_consent)]
)
async def recheck_novel_block_edit_bundle(
    job_id: uuid.UUID,
    bundle_id: str,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelBundleRecheckResponse:
    """사용자가 묶음 원소의 블록을 직접 고친 뒤, 남은 수정안을 따로 적용해도 이야기가 어긋나지 않는지 모델에 묻는다(무과금, 동기,
    시간당 상한). 따로 적용해도 된다는 판정이면 고친 원소를 묶음에서 빼 낡음으로 두고(버리기만 된다), 남은 원소가 하나면 독립
    수정안으로, 둘 이상이면 그들끼리 묶음으로 남긴다. 아니라는 판정(판단이 서지 않음 포함)이면 묶음은 그대로라 버리기만 된다.

    거절: 작업 없음·모르는 묶음 404(`NOVEL_JOB_NOT_FOUND`·`NOVEL_PATCH_NOT_FOUND`), 고친 원소가 없음 409 `NOVEL_RECHECK_NOT_NEEDED`(묶음째
    적용하면 된다), 남은 원소가 없거나 고친 블록이 모두 지워짐·패치 작업이 아님 409 `NOVEL_JOB_NOT_APPLICABLE` — 여기까지는 모델을
    부르지 않고 상한도 깎지 않는다. 그다음 상한 초과 429, 모델 호출 실패 503 `NOVEL_RECHECK_UNAVAILABLE`(묶음 그대로). 모델을 부르는
    동안 그 화에 새 개정이 쌓였으면 409 `NOVEL_REVISION_CONFLICT`, 그 묶음이 바뀌었으면 409 `NOVEL_JOB_NOT_APPLICABLE` — 판정은
    옛 상태에 대한 것이라 쓰지 않는다. 모델을 부르기 전에 커밋해 커넥션을 돌려준다."""
    job, edit = await _patch_job(db, novel, job_id, lock=False)
    assert job.chapter_id is not None  # `_patch_job` 이 걸렀다
    chapter_id = job.chapter_id
    current = await current_revision(db, chapter_id)
    if current is None:
        raise _not_applicable()
    try:
        plan = recheck_plan(edit, bundle_id, current.block_ids, split_paragraphs(current.body))
    except UnitNotFoundError:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_PATCH_NOT_FOUND") from None
    except RecheckNotNeededError:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_RECHECK_NOT_NEEDED") from None
    except UnitNotApplicableError:
        raise _not_applicable() from None
    route = await resolve_novel_call_route(db, "novel_recheck")
    prompt = await build_recheck_prompt(db, novel, current, edit, plan, chain_model=route.chain_model)
    await _check_recheck_limit(novel.user_id)
    basis_revision_id = current.id
    usage = LLMCallContext(
        call_site="novelize_revise_recheck",
        user_id=novel.user_id,
        room_id=novel.chat_room_id,
        call_model=route.call_model,
    )
    await db.commit()

    try:
        verdict = await llm_client.generate_structured_with_instruction(
            prompt.prompt, NovelizeRecheckResult, system_instruction=prompt.system_instruction, usage=usage
        )
    except LLMClientError as exc:
        logger.warning("소설 묶음 재검사 호출이 실패했다: %s", type(exc).__name__)
        raise _novel_error(status.HTTP_503_SERVICE_UNAVAILABLE, "NOVEL_RECHECK_UNAVAILABLE") from exc

    locked, latest_edit = await _patch_job(db, novel, job_id, lock=True)
    if latest_edit != edit:
        raise _not_applicable()
    # 장 행도 잡는다(작업 행 → 장 행, 적용과 같은 순서) — 읽기만 하면 확인과 커밋 사이에 직접 수정이 커밋돼 옛 글에 대한 판정이 남는다.
    latest = await _lock_current_revision(db, chapter_id)
    if latest is None or latest.id != basis_revision_id:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_REVISION_CONFLICT")
    if verdict.separable:
        await db.execute(
            update(NovelJob).where(NovelJob.id == locked.id).values(block_edit=with_split(edit, bundle_id, plan).to_json())
        )
    await db.commit()
    return NovelBundleRecheckResponse(
        separable=verdict.separable, reason=verdict.reason.strip()[:_RECHECK_REASON_MAX_CHARS]
    )
