"""소설 라우트. 모든 라우트(읽기 포함)가 라우터 수준에서 소설화 접근 게이트를 거친다.

의존성은 이 순서로 돈다: 로그인(`get_current_user_id`) → 라우터 수준 소설화 게이트 → 쓰기 라우트만 재동의 게이트
(데코레이터) → 소유권(소설 또는 방) → 본문. 라우터 수준 의존성이 데코레이터 의존성보다 먼저 풀리므로, 허용이 없는
사용자는 재동의가 필요해도 기능 게이트의 403 을 받는다.

자기 데이터를 지우는 라우트(소설 삭제·마지막 장 삭제)는 재동의 게이트를 걸지 않는다 — 새 문안에 동의하지 않은
사용자도 자기가 만든 것을 지울 수 있어야 한다. 읽기와 작업 폴링도 막지 않는다.

**잠금 순서는 사용자 → 작업 → 장 → 소설이다.** 작업 생성·환불·탈퇴가 사용자 행을 먼저 잡고(`billing.py`), 성공
저장은 작업 행 → 장 → 소설 순서다. 그래서 여기서도 소설 행을 먼저 잠그지 않고, 장을 잠근 뒤 작업 행을 고치지 않는다
(거꾸로 잡으면 겹치는 경로와 서로를 기다려 한쪽이 교착 오류로 끊긴다)."""

import base64
import json
import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import PromptRenderError, load_active_prompt_set
from api.chat.router import _ensure_content_playable, _get_owned_room
from api.content.media_tags import strip_media_tags
from api.core.config import settings
from api.core.rate_limit import check_rate_limit
from api.core.rate_limit_gate import _too_many_requests
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.content import Content, ContentType
from api.db.models.novel import Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.db.models.persona import UserPersona
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from api.llm.dependencies import get_llm_client
from api.novelize.access import require_novelize_access
from api.novelize.billing import (
    ACTIVE_JOB_STATUSES,
    _lock_user,
    create_charged_job,
    job_price,
    refund_active_jobs,
)
from api.novelize.deletion import delete_novels
from api.novelize.inputs import current_revision
from api.novelize.prompts import NovelizeBoundaryResult, build_novelize_boundary_prompt
from api.novelize.runner import enqueue_job, expire_stale_jobs
from api.novelize.schemas import (
    AI_EDIT_INSTRUCTION_MAX_LENGTH,
    CHAPTER_BODY_MAX_LENGTH,
    SETTING_NOTES_MAX_LENGTH,
    NovelActiveJob,
    NovelAiEditPreview,
    NovelAiEditRequest,
    NovelChapterCandidate,
    NovelChapterCreateRequest,
    NovelChapterProposalResponse,
    NovelChapterRegenerateRequest,
    NovelChapterResponse,
    NovelChapterSuggestion,
    NovelChapterSummary,
    NovelDetailResponse,
    NovelJobResponse,
    NovelLimits,
    NovelListItem,
    NovelListResponse,
    NovelPendingAiEdit,
    NovelPrices,
    NovelProtagonistNameRequest,
    NovelRevisionCreateRequest,
    NovelRevisionListResponse,
    NovelRevisionResponse,
    NovelRevisionRestoreRequest,
    NovelRevisionSummary,
    NovelSettingNotesRequest,
)
from api.novelize.source import (
    format_turn_lines,
    group_turns,
    load_candidates,
    load_segment,
    message_key,
    next_chapter_start,
    novel_prompt_names,
    segment_hash,
)
from api.novelize.text import split_paragraphs
from api.persona.schemas import PERSONA_NAME_MAX_LENGTH
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/novels", tags=["novels"], dependencies=[Depends(require_novelize_access)])
# 방에서 소설로 들어가는 두 라우트. prefix 가 달라 두 번째 라우터로 두고, `main.py` 는 별칭으로 import 한다.
room_router = APIRouter(prefix="/chat-rooms", tags=["novels"], dependencies=[Depends(require_novelize_access)])

# 내 소설 목록 한 페이지. 테스트가 바꿔 끼울 수 있게 부를 때 모듈 전역으로 읽는다.
NOVEL_PAGE_SIZE = 20


def _novel_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


# ── 소유권 ──────────────────────────────────────────────────────────────────
async def _get_owned_novel(db: AsyncSession, novel_id: uuid.UUID, user_id: uuid.UUID) -> Novel:
    """없으면 404, 남의 것이면 403(방 소유권 검사와 같은 모양). 행을 잠그지 않는다 — 소설 행을 먼저 잠그면 성공
    저장(작업 행 → 소설 행)과 교착한다."""
    novel = await db.get(Novel, novel_id, populate_existing=True)
    if novel is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND")
    if novel.user_id != user_id:
        raise _novel_error(status.HTTP_403_FORBIDDEN, "NOVEL_FORBIDDEN")
    return novel


async def _owned_novel_dependency(
    novel_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> Novel:
    return await _get_owned_novel(db, novel_id, user_id)


async def _owned_room_dependency(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoom:
    return await _get_owned_room(db, room_id, user_id)


# ── 응답 조립 ───────────────────────────────────────────────────────────────
def _prices() -> NovelPrices:
    return NovelPrices(
        chapter_generate=job_price("chapter_generate"),
        chapter_regenerate=job_price("chapter_regenerate"),
        ai_edit=job_price("ai_edit"),
    )


_LIMITS = NovelLimits(
    setting_notes_max_length=SETTING_NOTES_MAX_LENGTH,
    chapter_body_max_length=CHAPTER_BODY_MAX_LENGTH,
    ai_edit_instruction_max_length=AI_EDIT_INSTRUCTION_MAX_LENGTH,
    protagonist_name_max_length=PERSONA_NAME_MAX_LENGTH,
)


async def _chapter_summaries(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelChapterSummary]:
    """장마다 현재 개정(번호 최대) 하나를 붙인 목차. 개정은 장마다 `revision_no` 내림차순 첫 행이다."""
    latest = (
        select(NovelChapterRevision)
        .distinct(NovelChapterRevision.chapter_id)
        .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
        .where(NovelChapter.novel_id == novel_id)
        .order_by(NovelChapterRevision.chapter_id, NovelChapterRevision.revision_no.desc())
    )
    revisions = {revision.chapter_id: revision for revision in (await db.scalars(latest)).all()}
    chapters = (
        await db.scalars(select(NovelChapter).where(NovelChapter.novel_id == novel_id).order_by(NovelChapter.ordinal))
    ).all()
    summaries: list[NovelChapterSummary] = []
    for chapter in chapters:
        revision = revisions.get(chapter.id)
        if revision is None:
            # 장 행과 첫 개정은 한 트랜잭션에서 함께 들어가므로 개정 없는 장은 없다.
            continue
        summaries.append(
            NovelChapterSummary(
                id=chapter.id,
                ordinal=chapter.ordinal,
                assistant_message_count=chapter.assistant_message_count,
                current_revision_id=revision.id,
                current_revision_no=revision.revision_no,
                current_revision_source=revision.source,
                updated_at=revision.created_at,
                created_at=chapter.created_at,
            )
        )
    return summaries


async def _active_job(db: AsyncSession, novel_id: uuid.UUID) -> NovelActiveJob | None:
    job = await db.scalar(
        select(NovelJob)
        .where(NovelJob.novel_id == novel_id, NovelJob.status.in_(ACTIVE_JOB_STATUSES))
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if job is None:
        return None
    return NovelActiveJob(id=job.id, kind=job.kind, status=job.status, chapter_id=job.chapter_id)


async def _pending_ai_edits(
    db: AsyncSession, novel_id: uuid.UUID, chapters: list[NovelChapterSummary]
) -> list[NovelPendingAiEdit]:
    """성공했고 적용·버리기 전이며 기준 개정이 그 장의 현재 개정인 AI 수정. 현재 개정은 목차가 이미 읽은 값을 쓴다."""
    current_revision_ids = [chapter.current_revision_id for chapter in chapters]
    if not current_revision_ids:
        return []
    jobs = await db.scalars(
        select(NovelJob)
        .where(
            NovelJob.novel_id == novel_id,
            NovelJob.kind == "ai_edit",
            NovelJob.status == "succeeded",
            NovelJob.result_revision_id.is_(None),
            NovelJob.dismissed_at.is_(None),
            NovelJob.base_revision_id.in_(current_revision_ids),
        )
        .order_by(NovelJob.created_at.desc(), NovelJob.id.desc())
        .execution_options(populate_existing=True)
    )
    pending: list[NovelPendingAiEdit] = []
    for job in jobs.all():
        # 성공한 AI 수정은 만들 때 장·범위·지시를, 성공 저장 때 결과 본문을 반드시 채운다.
        assert (
            job.chapter_id is not None
            and job.paragraph_start is not None
            and job.paragraph_end is not None
            and job.instruction is not None
            and job.result_text is not None
        )
        pending.append(
            NovelPendingAiEdit(
                id=job.id,
                chapter_id=job.chapter_id,
                paragraph_start=job.paragraph_start,
                paragraph_end=job.paragraph_end,
                instruction=job.instruction,
                result_text=job.result_text,
                created_at=job.created_at,
            )
        )
    return pending


async def _detail(db: AsyncSession, novel_id: uuid.UUID) -> NovelDetailResponse:
    novel = await db.get_one(Novel, novel_id, populate_existing=True)
    chapters = await _chapter_summaries(db, novel.id)
    return NovelDetailResponse(
        id=novel.id,
        chat_room_id=novel.chat_room_id,
        content_id=novel.content_id,
        content_type=novel.content_type,
        content_title=novel.content_title,
        character_name=novel.character_name,
        protagonist_name=novel.protagonist_name,
        setting_notes=novel.setting_notes,
        chapters=chapters,
        active_job=await _active_job(db, novel.id),
        pending_ai_edits=await _pending_ai_edits(db, novel.id, chapters),
        prices=_prices(),
        limits=_LIMITS,
        created_at=novel.created_at,
        updated_at=novel.updated_at,
    )


async def _expire_and_detail(db: AsyncSession, novel_id: uuid.UUID) -> NovelDetailResponse:
    """지연 정리 — 서버 재기동으로 사라진 작업이 진행 중으로 남아 있으면 실패·환불로 끝낸 뒤 상세를 답한다. 그래야
    화면이 죽은 작업을 폴링하지 않고, 다음 작업 요청이 그 작업 때문에 409 를 받지 않는다."""
    await expire_stale_jobs(db, novel_id=novel_id)
    await db.commit()
    return await _detail(db, novel_id)


def _job_response(job: NovelJob) -> NovelJobResponse:
    ai_edit = (
        NovelAiEditPreview(
            base_revision_id=job.base_revision_id,
            paragraph_start=job.paragraph_start,
            paragraph_end=job.paragraph_end,
            instruction=job.instruction,
            result_text=job.result_text,
        )
        if job.kind == "ai_edit"
        else None
    )
    return NovelJobResponse(
        id=job.id,
        kind=job.kind,
        status=job.status,
        charged_amount=job.charged_amount,
        refunded=job.refunded_at is not None,
        failure_reason=job.failure_code,
        chapter_id=job.chapter_id,
        revision_id=job.result_revision_id,
        ai_edit=ai_edit,
        created_at=job.created_at,
    )


# ── 방의 소설 ───────────────────────────────────────────────────────────────
async def _room_novel_id(db: AsyncSession, room_id: uuid.UUID) -> uuid.UUID | None:
    novel_id: uuid.UUID | None = await db.scalar(select(Novel.id).where(Novel.chat_room_id == room_id))
    return novel_id


@room_router.get("/{room_id}/novel")
async def get_room_novel(
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """방에서 만든 소설. 아직 없으면 404 `NOVEL_NOT_FOUND`."""
    novel_id = await _room_novel_id(db, room.id)
    if novel_id is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND")
    return await _expire_and_detail(db, novel_id)


@room_router.post("/{room_id}/novel", dependencies=[Depends(require_legal_consent)])
async def create_room_novel(
    response: Response,
    room: ChatRoom = Depends(_owned_room_dependency),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """방의 소설을 만들거나, 이미 있으면 그대로 돌려준다(201 / 200). 무과금이다.

    원작 제목·캐릭터 이름·레인은 방이 고정한 버전에서 사본으로 떠 둔다 — 방이 지워지거나 작품이 바뀌어도 소설은
    그대로 읽혀야 한다. 주인공 이름은 방에 건 대화 프로필 이름, 없으면 그 버전의 작품 기본 이름이고, 둘 다 없으면
    비워 두었다가 첫 장을 만들기 전에 받는다. 이용 제한 작품이어도 만들 수 있다(모델을 부르지 않는다)."""
    existing = await _room_novel_id(db, room.id)
    if existing is not None:
        return await _expire_and_detail(db, existing)

    content = await db.get_one(Content, room.content_id)
    persona = await db.get(UserPersona, room.persona_id) if room.persona_id is not None else None
    character_name: str | None
    if content.type == ContentType.STORY:
        story = await db.get_one(StoryVersionDetail, room.content_version_id)
        title, character_name, default_user_name = story.name, None, story.default_user_name
    else:
        character = await db.get_one(CharacterVersionDetail, room.content_version_id)
        title, character_name, default_user_name = character.name, character.name, character.default_user_name
    protagonist = (persona.name if persona is not None else "") or default_user_name.strip()

    # 같은 방에 두 요청이 겹치면 방 유니크 인덱스에서 하나만 들어가고 다른 쪽은 아무것도 하지 않는다.
    inserted = await db.scalar(
        insert(Novel)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            chat_room_id=room.id,
            content_id=content.id,
            content_type=content.type.value,
            content_title=title,
            character_name=character_name,
            protagonist_name=protagonist or None,
        )
        .on_conflict_do_nothing(index_elements=[Novel.chat_room_id])
        .returning(Novel.id)
    )
    await db.commit()
    if inserted is None:
        novel_id = await _room_novel_id(db, room.id)
        assert novel_id is not None  # 충돌한 상대가 커밋한 행이다
        return await _detail(db, novel_id)
    response.status_code = status.HTTP_201_CREATED
    return await _detail(db, inserted)


# ── 목록·상세 ───────────────────────────────────────────────────────────────
def _encode_cursor(updated_at: datetime, novel_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([updated_at.isoformat(), str(novel_id)]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        updated_at, novel_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(updated_at), uuid.UUID(novel_id)
    except (ValueError, TypeError) as exc:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_CURSOR_INVALID") from exc


@router.get("")
async def list_novels(
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelListResponse:
    """내 소설을 최근 수정 순으로. 원래 방이 지워진 소설도 나온다(`chatRoomId` null)."""
    chapter_count = (
        select(func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == Novel.id).scalar_subquery()
    )
    query = (
        select(Novel, chapter_count)
        .where(Novel.user_id == user_id)
        .order_by(Novel.updated_at.desc(), Novel.id.desc())
    )
    if cursor is not None:
        # 오른쪽은 평범한 튜플이다 — `tuple_` 끼리 비교하면 mypy 가 결과를 bool 로 본다.
        query = query.where(tuple_(Novel.updated_at, Novel.id) < _decode_cursor(cursor))
    page_size = NOVEL_PAGE_SIZE
    rows = (await db.execute(query.limit(page_size + 1))).all()
    page = rows[:page_size]
    next_cursor = _encode_cursor(page[-1][0].updated_at, page[-1][0].id) if len(rows) > page_size else None
    return NovelListResponse(
        items=[
            NovelListItem(
                id=novel.id,
                chat_room_id=novel.chat_room_id,
                content_type=novel.content_type,
                content_title=novel.content_title,
                character_name=novel.character_name,
                chapter_count=count,
                created_at=novel.created_at,
                updated_at=novel.updated_at,
            )
            for novel, count in page
        ],
        next_cursor=next_cursor,
    )


@router.get("/{novel_id}")
async def get_novel(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """소설 머리·설정 노트·목차(장마다 현재 개정)·진행 중 작업·지금 단가. 답하기 전에 죽은 작업을 정리한다."""
    return await _expire_and_detail(db, novel.id)


@router.delete("/{novel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_novel(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """소설과 그 아래 행을 지운다. 진행 중 작업은 같은 트랜잭션에서 먼저 환불한다 — 지우고 나면 실행 경로가 실패해도
    환불할 행이 없다. 원래 방은 그대로다.

    사용자 행을 먼저 잠근다. 같은 사용자의 작업 생성이 이 사이에 끼어들면 지울 소설에 새 작업 행이 붙어 소설 DELETE
    가 FK 위반이 되는데, 작업 생성도 사용자 행을 먼저 잡으므로 둘이 줄을 선다. 소설 행은 잠그지 않는다(모듈 머리)."""
    await _lock_user(db, novel.user_id)
    # 행이 곧 지워져 남지 않으므로 사유 칸은 어느 값이든 같다 — 우리 쪽 사정으로 끝낸 작업이라 `internal` 이다.
    await refund_active_jobs(db, novel_id=novel.id, failure_code="internal")
    await delete_novels(db, [novel.id])
    await db.commit()


# ── 설정 노트·주인공 이름 ───────────────────────────────────────────────────
@router.put("/{novel_id}/notes", dependencies=[Depends(require_legal_consent)])
async def update_novel_notes(
    payload: NovelSettingNotesRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """설정 노트를 바꾼다. 다음 장 생성과 AI 수정부터 실린다(이미 만든 장은 그대로)."""
    await db.execute(
        update(Novel).where(Novel.id == novel.id).values(setting_notes=payload.setting_notes, updated_at=func.now())
    )
    await db.commit()
    return await _detail(db, novel.id)


@router.put("/{novel_id}/protagonist-name", dependencies=[Depends(require_legal_consent)])
async def update_novel_protagonist_name(
    payload: NovelProtagonistNameRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """주인공 이름을 바꾼다. 다음 장 생성부터 쓰이고 이미 만든 장 본문은 그대로다."""
    await db.execute(
        update(Novel)
        .where(Novel.id == novel.id)
        .values(protagonist_name=payload.protagonist_name, updated_at=func.now())
    )
    await db.commit()
    return await _detail(db, novel.id)


# ── 작업 폴링 ───────────────────────────────────────────────────────────────
def _job_not_found() -> HTTPException:
    return _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_JOB_NOT_FOUND")


@router.get("/{novel_id}/jobs/{job_id}")
async def get_novel_job(
    novel_id: uuid.UUID,
    job_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelJobResponse:
    """작업 폴링. 없는 작업·남의 소설·다른 소설의 작업은 모두 404 다(남의 것이 있다는 사실도 드러내지 않는다).

    답하기 전에 이 소설의 죽은 작업을 정리한다 — 서버가 재기동되어 작업이 사라졌으면 폴링이 실패·환불을 보게 된다."""
    owner = await db.scalar(select(Novel.user_id).where(Novel.id == novel_id))
    if owner != user_id:
        raise _job_not_found()
    await expire_stale_jobs(db, novel_id=novel_id)
    await db.commit()

    job = await db.scalar(
        select(NovelJob)
        .where(NovelJob.id == job_id, NovelJob.novel_id == novel_id)
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise _job_not_found()
    return _job_response(job)


# ── 장: 공통 검사 ───────────────────────────────────────────────────────────
async def _get_chapter(db: AsyncSession, novel: Novel, chapter_id: uuid.UUID) -> NovelChapter:
    chapter = await db.scalar(
        select(NovelChapter)
        .where(NovelChapter.id == chapter_id, NovelChapter.novel_id == novel.id)
        .execution_options(populate_existing=True)
    )
    if chapter is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    return chapter


async def _ensure_content_allows_model(db: AsyncSession, novel: Novel) -> None:
    """모델을 부르는 라우트(경계 제안·장 생성·재생성·AI 수정)만 막는다. 작품은 소설 행에 사본으로 둔 원작 id 로
    읽어 방이 지워져도 판정한다. 원작 행이 아예 없으면 이용 제한과 같이 막는다(풀어 줄 근거가 없다)."""
    content = await db.get(Content, novel.content_id, populate_existing=True)
    if content is None:
        raise _novel_error(status.HTTP_403_FORBIDDEN, "CONTENT_RESTRICTED")
    _ensure_content_playable(content)


def _source_room_id(novel: Novel) -> uuid.UUID:
    """새 장의 원문이 있는 방. 방이 지워진 소설은 읽고 고칠 수는 있어도 새 장·재생성을 할 원문이 없다."""
    if novel.chat_room_id is None:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_ROOM_GONE")
    return novel.chat_room_id


def _require_protagonist_name(novel: Novel) -> None:
    """장 본문은 사용자 쪽 인물을 이름으로 부른다 — 이름이 없으면 차감하기 전에 받는다."""
    if not (novel.protagonist_name or "").strip():
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_PROTAGONIST_NAME_REQUIRED")


async def _next_segment(db: AsyncSession, novel: Novel, room_id: uuid.UUID) -> list[ChatMessage]:
    """다음 장이 될 수 있는 원문 — 시작 메시지부터 응답을 장 턴 상한만큼 셀 때까지. 시작은 서버가 정한다(마지막 장
    끝 키보다 뒤의 첫 메시지). 장으로 만들 응답이 하나도 없으면 409 `NOVEL_NOTHING_NEW`."""
    last_chapter = await db.scalar(
        select(NovelChapter).where(NovelChapter.novel_id == novel.id).order_by(NovelChapter.ordinal.desc()).limit(1)
    )
    start = await next_chapter_start(db, room_id, last_chapter)
    candidates = (
        await load_candidates(db, room_id, message_key(start), settings.novelize_chapter_max_turns)
        if start is not None
        else []
    )
    if not candidates:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_NOTHING_NEW")
    return candidates


async def _start_job(
    db: AsyncSession, job: NovelJob, expected_cost: int, session_factory: "SessionFactory", llm_client: LLMClient
) -> NovelJobResponse:
    """차감하며 작업을 넣고(커밋) 백그라운드로 띄운다. 거절 판정은 모두 이 앞에서 끝낸다 — 거절된 요청은 원장에
    아무것도 남기지 않는다. 응답은 띄우기 전에 만든다: 띄운 작업이 같은 커넥션을 쓰는 테스트에서 겹치지 않게."""
    job = await create_charged_job(db, job=job, expected_cost=expected_cost, now=datetime.now(UTC))
    response = _job_response(await db.get_one(NovelJob, job.id, populate_existing=True))
    await enqueue_job(session_factory, llm_client, job.id)
    return response


async def _expire_before_new_job(db: AsyncSession, novel: Novel) -> None:
    """새 작업 차감 직전의 지연 정리. 커밋까지 해 둔다 — 작업 생성이 거절하며 롤백해도 정리(환불)는 남고, 서버
    재기동으로 죽은 작업이 진행 중으로 남아 새 작업을 계속 409 로 막지 않는다."""
    await expire_stale_jobs(db, novel_id=novel.id)
    await db.commit()


SessionFactory = async_sessionmaker[AsyncSession]


# ── 장 경계 제안 ────────────────────────────────────────────────────────────
_PROPOSAL_SCOPE = "novelize-proposal"
_HOUR_SECONDS = 3600
# 후보 턴 발췌 길이(글자)와 제안 이유 상한. 이유는 문안이 60자 이내로 쓰라고 하지만 넘쳐 와도 버리지 않고 자른다.
_EXCERPT_CHARS = 80
_REASON_MAX_CHARS = 100
_WHITESPACE = re.compile(r"\s+")


def _excerpt(message: ChatMessage, novel: Novel) -> str:
    names = novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name)
    text = _WHITESPACE.sub(" ", names.expand(strip_media_tags(message.content))).strip()
    return text[:_EXCERPT_CHARS]


async def _check_proposal_limit(user_id: uuid.UUID) -> None:
    """무과금 호출의 남용 상한(시간당 고정 창). 면제 계정도 센다 — 과금이 없어 이 상한이 유일한 제동이다. Redis 가
    실패하면 채팅·이미지 상한과 같이 통과시킨다."""
    try:
        retry_after = await check_rate_limit(
            _PROPOSAL_SCOPE, str(user_id), settings.novelize_proposal_hourly_limit, window_seconds=_HOUR_SECONDS
        )
    except RedisError:
        logger.warning("소설 장 경계 제안 상한 검사 실패 — 통과시킨다", exc_info=True)
        return
    if retry_after > 0:
        raise _too_many_requests(user_id, "novelize", retry_after)


@router.post("/{novel_id}/chapter-proposal", dependencies=[Depends(require_legal_consent)])
async def propose_novel_chapter(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelChapterProposalResponse:
    """다음 장의 후보 턴 목록과 모델이 고른 끝 턴(무과금, 동기).

    후보는 서버가 정한 시작부터 응답을 장 턴 상한만큼 센 턴들이고, 화면은 이 목록에서 끝을 고른다 — 화면의 방
    메시지 캐시는 최근 일부뿐이라 장 시작이 그보다 앞일 수 있다. 모델 제안이 실패해도 200 에 `suggestion: null`
    이다: 경계는 사용자가 고르는 것이라 제안 실패가 장 생성을 막을 이유가 없다. 모델을 부르기 전에 커밋해 커넥션을
    돌려준다(모델 호출 동안 쥐지 않는다)."""
    await _ensure_content_allows_model(db, novel)
    room_id = _source_room_id(novel)
    candidates = await _next_segment(db, novel, room_id)
    turns = group_turns(candidates)
    prompt_set, sections = await load_active_prompt_set(db, lane=novel.content_type)
    await _check_proposal_limit(novel.user_id)
    await db.commit()

    suggestion: NovelChapterSuggestion | None = None
    is_story = novel.content_type == "story"
    names = novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name)
    try:
        prompt = build_novelize_boundary_prompt(
            prompt_set=prompt_set,
            sections=sections,
            is_story_chat=is_story,
            max_turns=len(turns),
            user_name=(novel.protagonist_name or "").strip(),
            turn_lines=format_turn_lines(
                turns,
                names=names,
                user_label=prompt_set.user_label,
                assistant_label=prompt_set.story_assistant_label if is_story else prompt_set.character_assistant_label,
            ),
        )
        result = await llm_client.generate_structured_with_instruction(
            prompt.prompt,
            NovelizeBoundaryResult,
            system_instruction=prompt.system_instruction,
            usage=LLMCallContext(call_site="novelize_boundary", user_id=novel.user_id, room_id=room_id),
        )
    except (LLMClientError, PromptRenderError) as exc:
        logger.warning("소설 장 경계 제안이 실패해 후보만 돌려준다: %s", type(exc).__name__)
    else:
        # 범위 밖 번호는 실패로 버리지 않고 범위 끝으로 바꾼다 — 사용자가 어차피 확인·조정하는 제안이다.
        end_turn = result.end_turn if 1 <= result.end_turn <= len(turns) else len(turns)
        suggestion = NovelChapterSuggestion(
            end_message_id=turns[end_turn - 1].assistant.id, reason=result.reason.strip()[:_REASON_MAX_CHARS]
        )

    return NovelChapterProposalResponse(
        start_message_id=candidates[0].id,
        candidates=[
            NovelChapterCandidate(
                message_id=turn.assistant.id,
                ordinal=n,
                created_at=turn.assistant.created_at,
                excerpt=_excerpt(turn.assistant, novel),
            )
            for n, turn in enumerate(turns, start=1)
        ],
        suggestion=suggestion,
        cost=job_price("chapter_generate"),
    )


# ── 장 생성·재생성 ──────────────────────────────────────────────────────────
@router.post(
    "/{novel_id}/chapters", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_legal_consent)]
)
async def create_novel_chapter(
    payload: NovelChapterCreateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """다음 장을 만드는 작업(과금, 202). 시작은 서버가 정하고, 끝(`endMessageId`)은 경계 제안의 후보 턴 중 하나여야
    한다 — 다음 장 시작부터 장 턴 상한 안의 AI 응답이 아니면 422 `NOVEL_CHAPTER_END_INVALID`.

    순서: 작품 상태(403)·방(409)·주인공 이름(422) → 죽은 작업 정리·커밋 → 구간 검사(409·422) → 차감·작업 생성(단가
    409·진행 중 409·하루 상한 429·잔액 429) → 띄우기. 차감 앞의 거절은 원장에 아무것도 남기지 않는다."""
    await _ensure_content_allows_model(db, novel)
    room_id = _source_room_id(novel)
    _require_protagonist_name(novel)
    await _expire_before_new_job(db, novel)

    candidates = await _next_segment(db, novel, room_id)
    end = next(
        (m for m in candidates if m.id == payload.end_message_id and m.role == ChatMessageRole.ASSISTANT), None
    )
    if end is None:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_CHAPTER_END_INVALID")
    start = candidates[0]
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="chapter_generate",
        start_message_id=start.id,
        start_message_created_at=start.created_at,
        end_message_id=end.id,
        end_message_created_at=end.created_at,
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


@router.post(
    "/{novel_id}/chapters/{chapter_id}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def regenerate_novel_chapter(
    chapter_id: uuid.UUID,
    payload: NovelChapterRegenerateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """장 하나를 같은 원문 구간으로 다시 만드는 작업(과금, 202). 마지막 장이 아니어도 된다. 결과는 그 장의 새
    개정으로 쌓이고, 그 사이의 직접 수정·되돌리기는 이력에 남는다.

    원문이 장을 만든 때와 다르면(메시지 편집·응답 재생성·삭제) 차감 전에 409 `NOVEL_SOURCE_CHANGED` — 같은 입력으로
    다시 만든다는 약속을 지킬 수 없다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    await _ensure_content_allows_model(db, novel)
    room_id = _source_room_id(novel)
    _require_protagonist_name(novel)
    await _expire_before_new_job(db, novel)

    segment = await load_segment(
        db,
        room_id,
        (chapter.start_message_created_at, chapter.start_message_id),
        (chapter.end_message_created_at, chapter.end_message_id),
    )
    if (
        not segment
        or segment[0].id != chapter.start_message_id
        or segment[-1].id != chapter.end_message_id
        or segment_hash(segment) != chapter.source_hash
    ):
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_CHANGED")
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="chapter_regenerate",
        chapter_id=chapter.id,
        start_message_id=chapter.start_message_id,
        start_message_created_at=chapter.start_message_created_at,
        end_message_id=chapter.end_message_id,
        end_message_created_at=chapter.end_message_created_at,
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


# ── 마지막 장 삭제 ──────────────────────────────────────────────────────────
@router.delete("/{novel_id}/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_last_novel_chapter(
    chapter_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """마지막 장만 지운다(무과금). 지우면 다음 장 시작이 그 장 시작으로 돌아간다 — 경계를 잘못 골랐을 때 고치는 길이다.
    마지막이 아니면 409 `NOVEL_CHAPTER_NOT_LAST`, 소설에 진행 중 작업이 있으면 409 `NOVEL_JOB_IN_PROGRESS`(끝난 뒤
    다시).

    그 장을 가리키던 작업 행은 지우지 않고 장·개정 참조만 비운다 — 같은 장의 하루 재시도 상한이 작업 행 수로 세므로,
    지우면 장을 지웠다 다시 만드는 것으로 상한이 풀린다. 차감 기록의 작업 쪽 짝도 남는다.

    잠금: 사용자 행(작업 생성과 줄 세우기 — 진행 중 확인과 삭제 사이에 새 작업이 끼지 않게) → 작업 행 → 장 행.
    장을 잠근 뒤 개정을 지운다 — 직접 수정·되돌리기가 장을 잠근 채 넣는 개정을 기다렸다가 함께 지우려는 것이다."""
    await _lock_user(db, novel.user_id)
    chapter = await _get_chapter(db, novel, chapter_id)
    active = await db.scalar(
        select(NovelJob.id).where(NovelJob.novel_id == novel.id, NovelJob.status.in_(ACTIVE_JOB_STATUSES)).limit(1)
    )
    if active is not None:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_IN_PROGRESS")
    last_ordinal = await db.scalar(select(func.max(NovelChapter.ordinal)).where(NovelChapter.novel_id == novel.id))
    if chapter.ordinal != last_ordinal:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_CHAPTER_NOT_LAST")

    # 작업의 개정 참조는 모두 같은 장의 개정이다(작업의 `chapter_id` 가 그 장) — 장으로 골라 셋을 함께 비운다.
    await db.execute(
        update(NovelJob)
        .where(NovelJob.chapter_id == chapter.id)
        .values(chapter_id=None, base_revision_id=None, result_revision_id=None)
    )
    await db.execute(select(NovelChapter.id).where(NovelChapter.id == chapter.id).with_for_update())
    await db.execute(delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id == chapter.id))
    await db.execute(delete(NovelChapter).where(NovelChapter.id == chapter.id))
    await db.execute(update(Novel).where(Novel.id == novel.id).values(updated_at=func.now()))
    await db.commit()


# ── 장 읽기·개정 이력 ───────────────────────────────────────────────────────
def _revision_summary(revision: NovelChapterRevision) -> NovelRevisionSummary:
    return NovelRevisionSummary(
        id=revision.id,
        revision_no=revision.revision_no,
        source=revision.source,
        reverted_from_revision_id=revision.reverted_from_revision_id,
        created_at=revision.created_at,
    )


def _revision_response(revision: NovelChapterRevision) -> NovelRevisionResponse:
    return NovelRevisionResponse(
        **_revision_summary(revision).model_dump(), body=revision.body, paragraphs=split_paragraphs(revision.body)
    )


async def _chapter_response(db: AsyncSession, chapter: NovelChapter) -> NovelChapterResponse:
    revision = await current_revision(db, chapter.id)
    assert revision is not None  # 장 행과 첫 개정은 한 트랜잭션에서 함께 들어간다
    return NovelChapterResponse(
        id=chapter.id,
        novel_id=chapter.novel_id,
        ordinal=chapter.ordinal,
        assistant_message_count=chapter.assistant_message_count,
        revision=_revision_response(revision),
    )


async def _get_revision(db: AsyncSession, chapter: NovelChapter, revision_id: uuid.UUID) -> NovelChapterRevision:
    revision = await db.scalar(
        select(NovelChapterRevision).where(
            NovelChapterRevision.id == revision_id, NovelChapterRevision.chapter_id == chapter.id
        )
    )
    if revision is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_REVISION_NOT_FOUND")
    return revision


@router.get("/{novel_id}/chapters/{chapter_id}")
async def get_novel_chapter(
    chapter_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """장의 현재 개정 본문과 그 문단 배열. 문단 범위(AI 수정)는 이 배열의 인덱스다 — 화면이 본문을 다시 나누면 빈 줄
    해석 차이로 범위가 어긋난다."""
    return await _chapter_response(db, await _get_chapter(db, novel, chapter_id))


@router.get("/{novel_id}/chapters/{chapter_id}/revisions")
async def list_novel_chapter_revisions(
    chapter_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelRevisionListResponse:
    """장의 개정 이력(최신 먼저). 본문은 싣지 않는다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    revisions = await db.scalars(
        select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter.id)
        .order_by(NovelChapterRevision.revision_no.desc())
    )
    return NovelRevisionListResponse(items=[_revision_summary(revision) for revision in revisions.all()])


@router.get("/{novel_id}/chapters/{chapter_id}/revisions/{revision_id}")
async def get_novel_chapter_revision(
    chapter_id: uuid.UUID,
    revision_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelRevisionResponse:
    chapter = await _get_chapter(db, novel, chapter_id)
    return _revision_response(await _get_revision(db, chapter, revision_id))


# ── 직접 수정·되돌리기·적용 ─────────────────────────────────────────────────
async def _lock_current_revision_for_edit(
    db: AsyncSession, chapter_id: uuid.UUID, base_revision_id: uuid.UUID
) -> NovelChapterRevision:
    """개정을 쌓는 세 경로(직접 수정·되돌리기·AI 수정 적용)의 공통 앞부분. 장 행을 먼저 잠그고(`FOR NO KEY UPDATE`)
    그 뒤에 현재 개정을 읽는다 — 잠그기 전에 읽으면 그사이 커밋된 새 개정을 못 보고 옛 개정 위에 덮어쓴다. 현재
    개정이 요청의 기준 개정이 아니면 409 `NOVEL_REVISION_CONFLICT`(다른 탭이 먼저 고쳤다). 장이 그사이 지워졌으면
    404. 재생성 결과 저장도 같은 잠금으로 줄을 서서 같은 번호를 두 번 쓰지 않는다."""
    locked = await db.scalar(select(NovelChapter.id).where(NovelChapter.id == chapter_id).with_for_update(key_share=True))
    if locked is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    current = await current_revision(db, chapter_id)
    if current is None or current.id != base_revision_id:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_REVISION_CONFLICT")
    return current


async def _stack_revision(
    db: AsyncSession, novel: Novel, current: NovelChapterRevision, revision: NovelChapterRevision
) -> NovelChapterRevision:
    """잠근 현재 개정 다음 번호로 `revision` 을 넣고 소설 수정 시각을 민다(커밋은 호출자)."""
    revision.chapter_id = current.chapter_id
    revision.revision_no = current.revision_no + 1
    db.add(revision)
    await db.flush()
    await db.execute(update(Novel).where(Novel.id == novel.id).values(updated_at=func.now()))
    return revision


@router.post(
    "/{novel_id}/chapters/{chapter_id}/revisions",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def create_novel_chapter_revision(
    chapter_id: uuid.UUID,
    payload: NovelRevisionCreateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """직접 수정 — 장 전체 본문을 새 개정으로 쌓는다(무과금). 화면이 고른 문단을 본문 안에서 바꿔 보내므로 서버는
    문단 범위를 모른다. 본문은 문단을 빈 줄 하나로 다시 이어 저장한다(문단 배열과 같은 나누기). 이용 제한 작품이나
    방이 지워진 소설도 고칠 수 있다(모델을 부르지 않는다)."""
    chapter = await _get_chapter(db, novel, chapter_id)
    current = await _lock_current_revision_for_edit(db, chapter.id, payload.base_revision_id)
    await _stack_revision(
        db,
        novel,
        current,
        NovelChapterRevision(body="\n\n".join(split_paragraphs(payload.body)), source="manual_edit"),
    )
    await db.commit()
    return await _chapter_response(db, chapter)


@router.post(
    "/{novel_id}/chapters/{chapter_id}/revisions/{revision_id}/restore",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def restore_novel_chapter_revision(
    chapter_id: uuid.UUID,
    revision_id: uuid.UUID,
    payload: NovelRevisionRestoreRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """옛 개정으로 되돌린다 — 옛 본문을 복제한 새 개정을 쌓는다(이력은 지우지 않는다)."""
    chapter = await _get_chapter(db, novel, chapter_id)
    source = await _get_revision(db, chapter, revision_id)
    current = await _lock_current_revision_for_edit(db, chapter.id, payload.base_revision_id)
    await _stack_revision(
        db,
        novel,
        current,
        NovelChapterRevision(body=source.body, source="revert", reverted_from_revision_id=source.id),
    )
    await db.commit()
    return await _chapter_response(db, chapter)


@router.post(
    "/{novel_id}/chapters/{chapter_id}/ai-edits",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def create_novel_ai_edit(
    chapter_id: uuid.UUID,
    payload: NovelAiEditRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """고른 문단 범위(0부터, 양 끝 포함 — 장 조회의 `paragraphs` 인덱스)를 지시대로 고치는 작업(과금, 202). 결과는
    개정이 아니라 작업의 미리보기 본문(`aiEdit.resultText`)이고, 적용해야 새 개정이 된다. 버려도 환불은 없다.

    방이 지워진 소설도 고칠 수 있다(원문 대화가 필요 없다). 기준 개정이 현재 개정이 아니면 409, 범위가 문단 밖이면
    422 — 둘 다 차감 전이다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    await _ensure_content_allows_model(db, novel)
    await _expire_before_new_job(db, novel)
    current = await current_revision(db, chapter.id)
    if current is None or current.id != payload.base_revision_id:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_REVISION_CONFLICT")
    if not payload.paragraph_start <= payload.paragraph_end < len(split_paragraphs(current.body)):
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_PARAGRAPH_RANGE_INVALID")
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="ai_edit",
        chapter_id=chapter.id,
        base_revision_id=current.id,
        paragraph_start=payload.paragraph_start,
        paragraph_end=payload.paragraph_end,
        instruction=payload.instruction,
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


@router.post(
    "/{novel_id}/jobs/{job_id}/apply", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def apply_novel_ai_edit(
    job_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """끝난 AI 수정의 미리보기를 새 개정으로 쌓는다(무과금). 수정을 맡긴 뒤 장이 바뀌었으면(기준 개정이 현재가
    아니면) 409 `NOVEL_REVISION_CONFLICT`. 적용할 수 없는 작업(AI 수정이 아님·아직 안 끝남·실패·이미 적용·버림·장이
    지워짐)은 409 `NOVEL_JOB_NOT_APPLICABLE`. 적용한 개정은 작업의 결과 개정(`revisionId`)이 된다.

    잠금은 작업 행 → 장 행이다(소설·마지막 장 삭제와 같은 순서). 같은 작업을 두 번 적용하려는 요청은 작업 행에서
    줄을 서고, 뒤 요청은 결과 개정이 채워진 것을 본다."""
    job = await db.scalar(
        select(NovelJob)
        .where(NovelJob.id == job_id, NovelJob.novel_id == novel.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_JOB_NOT_FOUND")
    if (
        job.kind != "ai_edit"
        or job.status != "succeeded"
        or job.result_text is None
        or job.result_revision_id is not None
        or job.dismissed_at is not None
        or job.chapter_id is None
        or job.base_revision_id is None
    ):
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_NOT_APPLICABLE")
    current = await _lock_current_revision_for_edit(db, job.chapter_id, job.base_revision_id)
    revision = await _stack_revision(
        db, novel, current, NovelChapterRevision(body=job.result_text, source="ai_edit")
    )
    await db.execute(update(NovelJob).where(NovelJob.id == job.id).values(result_revision_id=revision.id))
    await db.commit()
    return await _chapter_response(db, await _get_chapter(db, novel, current.chapter_id))


@router.post(
    "/{novel_id}/jobs/{job_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_legal_consent)],
)
async def dismiss_novel_ai_edit(
    job_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """끝난 AI 수정의 미리보기를 적용하지 않고 버린다(환불 없음). 버린 수정은 상세의 미적용 목록에서 빠지고 적용도
    409 가 된다. 버릴 수 없는 작업(AI 수정이 아님·아직 안 끝남·실패·이미 적용·이미 버림)은 409
    `NOVEL_JOB_NOT_APPLICABLE`.

    적용과 같은 작업 행을 잠근다 — 같은 수정의 적용과 버리기가 겹치면 뒤 요청이 앞 요청의 결과를 보고 409 다."""
    job = await db.scalar(
        select(NovelJob)
        .where(NovelJob.id == job_id, NovelJob.novel_id == novel.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_JOB_NOT_FOUND")
    if (
        job.kind != "ai_edit"
        or job.status != "succeeded"
        or job.result_revision_id is not None
        or job.dismissed_at is not None
    ):
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_NOT_APPLICABLE")
    await db.execute(update(NovelJob).where(NovelJob.id == job.id).values(dismissed_at=func.now()))
    await db.commit()
