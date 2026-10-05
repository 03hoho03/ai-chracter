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
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.router import _get_owned_room
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatRoom
from api.db.models.content import Content, ContentType
from api.db.models.novel import Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.db.models.persona import UserPersona
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.novelize.access import require_novelize_access
from api.novelize.billing import ACTIVE_JOB_STATUSES, _lock_user, job_price, refund_active_jobs
from api.novelize.deletion import delete_novels
from api.novelize.runner import expire_stale_jobs
from api.novelize.schemas import (
    AI_EDIT_INSTRUCTION_MAX_LENGTH,
    CHAPTER_BODY_MAX_LENGTH,
    SETTING_NOTES_MAX_LENGTH,
    NovelActiveJob,
    NovelAiEditPreview,
    NovelChapterSummary,
    NovelDetailResponse,
    NovelJobResponse,
    NovelLimits,
    NovelListItem,
    NovelListResponse,
    NovelPrices,
    NovelProtagonistNameRequest,
    NovelSettingNotesRequest,
)
from api.persona.schemas import PERSONA_NAME_MAX_LENGTH
from api.session.dependencies import get_current_user_id

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


async def _detail(db: AsyncSession, novel_id: uuid.UUID) -> NovelDetailResponse:
    novel = await db.get_one(Novel, novel_id, populate_existing=True)
    return NovelDetailResponse(
        id=novel.id,
        chat_room_id=novel.chat_room_id,
        content_id=novel.content_id,
        content_type=novel.content_type,
        content_title=novel.content_title,
        character_name=novel.character_name,
        protagonist_name=novel.protagonist_name,
        setting_notes=novel.setting_notes,
        chapters=await _chapter_summaries(db, novel.id),
        active_job=await _active_job(db, novel.id),
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
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "NOVEL_CURSOR_INVALID") from exc


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
