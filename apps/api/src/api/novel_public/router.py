"""노벨 게시자 라우트 — 공개 상태 조회, 공개(처음 공개·다음 화·다시 공개), 공개 거두기.

조회와 공개는 소설화 접근 게이트와 노벨 스위치 게이트를 라우터 수준에서 거친다 — 공개할 수 있는 사람은 소설화를 쓸 수 있는
계정뿐이다. 공개 거두기는 두 게이트 밖의 두 번째 라우터에 있고 로그인·소유권만 본다. 자기 글을 내리는 일은 기능 허용과
무관하다(소설 삭제가 게이트 밖인 것과 같은 원칙) — 운영자가 소설화 허용을 거두거나 스위치를 꺼도 게시자는 공개를 거둘 수
있어야 한다.

**공개는 세 구간이다**(작품 발행과 같은 꼴). 심사 LLM 을 기다리는 동안(수 초) DB 트랜잭션을 열어 두면 커넥션 하나를 쥐어
다른 요청이 풀을 기다리기 때문이다.

1. 읽기: 따로 연 세션에서 공개 계획(무엇을 새로 공개하고 무엇을 다시 내며 무엇을 심사하는지)을 세우고 닫는다. 판정 실패
   (이어지지 않는 화, 원작 판정, 운영 조치)는 여기서 낸다.
2. 심사: 계획이 심사할 글을 실었으면 게시자 하루 거부 상한을 보고 심사를 부른다. 트랜잭션 없음.
3. 쓰기: 요청 세션에서 사용자 행을 잠그고 계획을 다시 세워 1 과 같은지 본다. 다르면(그사이 화를 고쳤거나 다른 요청이 먼저
   공개했다) 409 `NOVEL_PUBLISH_CONFLICT` 이고 아무것도 쓰지 않는다. 같으면 공개본을 쓴다(통과) 또는 거부 기록을 남긴다.

잠금은 사용자 행 하나다. 소설 삭제·마지막 묶음 삭제·탈퇴·스냅샷 복원이 사용자 행을 먼저 잡으므로(`novelize/router.py`
모듈 docstring 의 잠금 순서) 공개 쓰기는 그 경로들과 줄을 서고, 같은 소설의 공개 요청 둘도 여기서 줄을 선다. 화 직접 수정은
화 행만 잠그므로 쓰기 구간과 겹칠 수 있는데, 그러면 심사한 개정을 얼린다 — 공개본은 늘 심사를 거친 글이다.

**심사 실패는 공개하지 않는다**(fail-closed). 걸리면 400 `NOVEL_SCREENING_REJECTED`(어느 화의 어느 글인지 — 사유 문구는
화면이 가진다), 심사 호출이 실패하면 503 `NOVEL_SCREENING_UNAVAILABLE`(작품 발행 심사의 장애와 같은 코드 — 기다렸다 다시
시도하면 되는 일이라), 오늘 거부 상한이나 시간당 심사 호출 상한에 닿았으면 429.

공개 화면에 내보내는 표지는 원작 썸네일뿐이라 공개본에 표지 사본을 두지 않는다(소설 생성 표지는 심사를 거친 적이 없다)."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import PromptRenderError, PromptSetNotFoundError, load_active_prompt_set
from api.core.sentry import capture_dependency_failure
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelPublication,
    NovelScreening,
    NovelScreeningPart,
)
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.client import LLMClient, LLMClientError, LLMRateLimitError
from api.llm.dependencies import get_llm_client
from api.novel_public.access import RepublishBlock, judge_source, require_novel_public_enabled
from api.novel_public.schemas import (
    NovelPublicationScreening,
    NovelPublicationStatusResponse,
    NovelPublishRequest,
)
from api.novel_public.screening import (
    NOVEL_SCREEN_DAILY_REJECTION_LIMIT,
    NOVEL_SCREEN_LANE,
    NovelScreenItem,
    count_rejection,
    enforce_call_limit,
    enforce_rejection_limit,
    rejections_left,
    screen_novel_text,
)
from api.novelize.access import require_novelize_access
from api.novelize.billing import _lock_user
from api.novelize.router import _get_owned_novel
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/novels",
    tags=["novels"],
    dependencies=[Depends(require_novelize_access), Depends(require_novel_public_enabled)],
)
# 공개 거두기. 게이트를 라우터 수준에 걸었으므로 라우트 하나만 빼려면 라우터를 나눠야 한다.
owner_router = APIRouter(prefix="/novels", tags=["novels"])


def _error(status_code: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, **extra})


# ── 계획 ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _ChapterPlan:
    """공개하거나 다시 낼 화 하나와 그때 얼릴 값."""

    chapter_id: uuid.UUID
    ordinal: int
    revision_id: uuid.UUID
    title: str | None
    author_note: str
    body: str
    is_new: bool


@dataclass(frozen=True)
class _PublishPlan:
    """읽기 구간이 세운 계획. 쓰기 구간이 같은 함수로 다시 세워 이것과 같아야 쓴다 — 그사이 바뀐 것이 있으면 심사한 글과
    쓸 글이 어긋난다."""

    has_publication: bool
    reopen: bool
    # 다시 낼 소설 제목·소개. 공개본과 같으면 None.
    metadata: tuple[str | None, str] | None
    # 새로 공개하거나 다시 낼 화. 이미 공개한 화가 공개본과 같으면 None.
    chapter: _ChapterPlan | None
    items: tuple[NovelScreenItem, ...]

    @property
    def writes_nothing(self) -> bool:
        return self.has_publication and not self.reopen and self.metadata is None and self.chapter is None


def _items(plan_metadata: tuple[str | None, str] | None, chapter: _ChapterPlan | None) -> tuple[NovelScreenItem, ...]:
    """심사할 글. 빈 칸은 싣지 않는다 — 제목이 없으면(원작 제목으로 대신) 심사할 글이 아니다."""
    items: list[NovelScreenItem] = []
    if plan_metadata is not None:
        title, synopsis = plan_metadata
        if title is not None and title.strip():
            items.append(NovelScreenItem(part="novel_title", text=title))
        if synopsis.strip():
            items.append(NovelScreenItem(part="synopsis", text=synopsis))
    if chapter is not None:
        if chapter.title is not None and chapter.title.strip():
            items.append(NovelScreenItem(part="chapter_title", text=chapter.title))
        if chapter.author_note.strip():
            items.append(NovelScreenItem(part="author_note", text=chapter.author_note))
        if chapter.body.strip():
            items.append(NovelScreenItem(part="chapter_body", text=chapter.body))
    return tuple(items)


async def _current_revision(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision:
    revision = await db.scalar(
        select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    # 화는 개정과 함께 만들어지고 개정은 지워지지 않는다(화와 함께 지워질 뿐이다).
    assert revision is not None
    return revision


async def _published_count(db: AsyncSession, novel_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count()).select_from(NovelChapterPublication).where(NovelChapterPublication.novel_id == novel_id)
    )
    return count or 0


async def _plan(
    db: AsyncSession, novel: Novel, user_id: uuid.UUID, chapter_id: uuid.UUID | None
) -> _PublishPlan:
    publication = await db.get(NovelPublication, novel.id, populate_existing=True)
    if publication is not None and publication.moderation_status == "restricted":
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_PUBLICATION_RESTRICTED")
    gate = await judge_source(db, novel.content_id, user_id)
    if not gate.source_available:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_UNAVAILABLE")

    published = await _published_count(db, novel.id)
    chapter_plan: _ChapterPlan | None = None
    is_new = publication is None
    if chapter_id is None:
        if publication is None:
            raise _error(status.HTTP_409_CONFLICT, "NOVEL_PUBLISH_NOT_CONTIGUOUS", nextOrdinal=1)
    else:
        chapter = await db.scalar(
            select(NovelChapter)
            .where(NovelChapter.id == chapter_id, NovelChapter.novel_id == novel.id)
            .execution_options(populate_existing=True)
        )
        if chapter is None:
            raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
        if chapter.ordinal > published + 1:
            raise _error(status.HTTP_409_CONFLICT, "NOVEL_PUBLISH_NOT_CONTIGUOUS", nextOrdinal=published + 1)
        revision = await _current_revision(db, chapter.id)
        frozen = await db.get(NovelChapterPublication, chapter.id, populate_existing=True)
        chapter_is_new = frozen is None
        is_new = is_new or chapter_is_new
        if frozen is None or await _chapter_changed(db, frozen, chapter, revision):
            chapter_plan = _ChapterPlan(
                chapter_id=chapter.id,
                ordinal=chapter.ordinal,
                revision_id=revision.id,
                title=chapter.title,
                author_note=chapter.author_note,
                body=revision.body,
                is_new=chapter_is_new,
            )
    if is_new and gate.new_publish_block is not None:
        status_code = status.HTTP_403_FORBIDDEN if gate.new_publish_block == "source_permission" else 409
        raise _error(status_code, "NOVEL_SOURCE_NOT_PUBLISHABLE", reason=gate.new_publish_block)

    metadata: tuple[str | None, str] | None = None
    if publication is None or (publication.title, publication.synopsis) != (novel.title, novel.synopsis):
        metadata = (novel.title, novel.synopsis)
    return _PublishPlan(
        has_publication=publication is not None,
        reopen=publication is not None and publication.visibility == "withdrawn",
        metadata=metadata,
        chapter=chapter_plan,
        items=_items(metadata, chapter_plan),
    )


async def _chapter_changed(
    db: AsyncSession, frozen: NovelChapterPublication, chapter: NovelChapter, revision: NovelChapterRevision
) -> bool:
    """공개본과 지금 화가 다른가. 본문은 개정 id 가 아니라 글자로 비교한다 — 옛 판으로 되돌리기는 같은 본문의 새 개정을
    만드는데, 이미 심사를 통과한 글을 다시 심사할 이유가 없다."""
    if (frozen.title, frozen.author_note) != (chapter.title, chapter.author_note):
        return True
    if frozen.revision_id == revision.id:
        return False
    frozen_body = await db.scalar(select(NovelChapterRevision.body).where(NovelChapterRevision.id == frozen.revision_id))
    return frozen_body != revision.body


# ── 상태 ────────────────────────────────────────────────────────────────────
async def _changed_chapter_ordinals(db: AsyncSession, novel_id: uuid.UUID) -> list[int]:
    """공개본과 지금이 다른 공개 화의 번호(오름차순). `_chapter_changed` 와 같은 비교(제목·작가의 말, 본문은 글자)를 한
    쿼리로 한다 — 화마다 따로 읽으면 공개 화 수만큼 쿼리가 는다. 현재 개정은 화마다 `revision_no` 가 가장 큰 개정이다."""
    current = (
        select(NovelChapterRevision.chapter_id, NovelChapterRevision.body)
        .distinct(NovelChapterRevision.chapter_id)
        .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
        .where(NovelChapter.novel_id == novel_id)
        .order_by(NovelChapterRevision.chapter_id, NovelChapterRevision.revision_no.desc())
        .subquery()
    )
    frozen_revision = aliased(NovelChapterRevision)
    rows = await db.scalars(
        select(NovelChapterPublication.ordinal)
        .join(NovelChapter, NovelChapter.id == NovelChapterPublication.chapter_id)
        .join(frozen_revision, frozen_revision.id == NovelChapterPublication.revision_id)
        .join(current, current.c.chapter_id == NovelChapterPublication.chapter_id)
        .where(
            NovelChapterPublication.novel_id == novel_id,
            or_(
                NovelChapterPublication.title.is_distinct_from(NovelChapter.title),
                NovelChapterPublication.author_note != NovelChapter.author_note,
                frozen_revision.body != current.c.body,
            ),
        )
        .order_by(NovelChapterPublication.ordinal)
    )
    return list(rows.all())


async def _status(db: AsyncSession, novel: Novel, user_id: uuid.UUID) -> NovelPublicationStatusResponse:
    publication = await db.get(NovelPublication, novel.id, populate_existing=True)
    gate = await judge_source(db, novel.content_id, user_id)
    republish_block: RepublishBlock | None = None
    if publication is not None and publication.moderation_status == "restricted":
        republish_block = "restricted"
    elif not gate.source_available:
        republish_block = "source_unavailable"
    chapter_count = await db.scalar(
        select(func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == novel.id)
    )
    last = await db.scalar(
        select(NovelScreening)
        .where(NovelScreening.novel_id == novel.id)
        .order_by(NovelScreening.created_at.desc(), NovelScreening.id.desc())
        .limit(1)
    )
    return NovelPublicationStatusResponse(
        published=publication is not None,
        visibility=publication.visibility if publication is not None else None,
        moderation_status=publication.moderation_status if publication is not None else None,
        published_chapter_count=await _published_count(db, novel.id),
        chapter_count=chapter_count or 0,
        changed_chapter_ordinals=await _changed_chapter_ordinals(db, novel.id) if publication is not None else [],
        metadata_changed=publication is not None
        and (publication.title, publication.synopsis) != (novel.title, novel.synopsis),
        new_publish_block=gate.new_publish_block,
        republish_block=republish_block,
        last_screening=(
            NovelPublicationScreening(
                outcome=last.outcome,
                chapter_ordinal=last.chapter_ordinal,
                flagged_parts=list(last.flagged_parts),
                created_at=last.created_at,
            )
            if last is not None
            else None
        ),
        screening_rejections_left=await rejections_left(db, user_id, datetime.now(UTC)),
        screening_rejection_limit=NOVEL_SCREEN_DAILY_REJECTION_LIMIT,
        first_published_at=publication.first_published_at if publication is not None else None,
        published_at=publication.published_at if publication is not None else None,
    )


# ── 쓰기 ────────────────────────────────────────────────────────────────────
async def _apply(db: AsyncSession, novel: Novel, plan: _PublishPlan) -> None:
    now = func.now()
    if not plan.has_publication:
        assert plan.metadata is not None  # 처음 공개는 언제나 소설 제목·소개를 얼린다
        title, synopsis = plan.metadata
        db.add(NovelPublication(novel_id=novel.id, visibility="public", title=title, synopsis=synopsis))
        await db.flush()
    else:
        values: dict[str, object] = {}
        if plan.reopen:
            values["visibility"] = "public"
        if plan.metadata is not None:
            values["title"], values["synopsis"] = plan.metadata
        if plan.metadata is not None or plan.chapter is not None:
            values["published_at"] = now
        if values:
            await db.execute(update(NovelPublication).where(NovelPublication.novel_id == novel.id).values(**values))
    chapter = plan.chapter
    if chapter is None:
        return
    if chapter.is_new:
        db.add(
            NovelChapterPublication(
                chapter_id=chapter.chapter_id,
                novel_id=novel.id,
                ordinal=chapter.ordinal,
                revision_id=chapter.revision_id,
                title=chapter.title,
                author_note=chapter.author_note,
            )
        )
        await db.flush()
        return
    await db.execute(
        update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == chapter.chapter_id)
        .values(
            revision_id=chapter.revision_id,
            title=chapter.title,
            author_note=chapter.author_note,
            edition=NovelChapterPublication.edition + 1,
            published_at=now,
        )
    )


def _screening_row(
    novel: Novel,
    plan: _PublishPlan,
    user_id: uuid.UUID,
    *,
    passed: bool,
    flagged_parts: Sequence[NovelScreeningPart],
    reason: str | None,
    model: str,
) -> NovelScreening:
    chapter = plan.chapter
    return NovelScreening(
        novel_id=novel.id,
        chapter_id=chapter.chapter_id if chapter is not None else None,
        chapter_ordinal=chapter.ordinal if chapter is not None else None,
        user_id=user_id,
        outcome="passed" if passed else "rejected",
        flagged_parts=list(flagged_parts),
        reason=reason,
        model=model,
    )


async def _lock_and_replan(
    db: AsyncSession, novel_id: uuid.UUID, user_id: uuid.UUID, chapter_id: uuid.UUID | None, planned: _PublishPlan
) -> Novel:
    """쓰기 구간의 시작. 사용자 행을 잠근 뒤 계획을 다시 세워 읽기 구간의 것과 같은지 본다."""
    await _lock_user(db, user_id)
    novel = await _get_owned_novel(db, novel_id, user_id)
    if await _plan(db, novel, user_id, chapter_id) != planned:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_PUBLISH_CONFLICT")
    return novel


def _screening_unavailable(exc: Exception) -> HTTPException:
    logger.warning("novel_screen_unavailable: %s", exc)
    if isinstance(exc, LLMClientError):
        capture_dependency_failure(
            exc, dependency="gemini_rate_limit" if isinstance(exc, LLMRateLimitError) else "gemini"
        )
    else:
        capture_dependency_failure(exc, dependency="prompt_render")
    return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "NOVEL_SCREENING_UNAVAILABLE")


# ── 라우트 ──────────────────────────────────────────────────────────────────
@router.get("/{novel_id}/publication")
async def get_novel_publication(
    novel_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelPublicationStatusResponse:
    novel = await _get_owned_novel(db, novel_id, user_id)
    return await _status(db, novel, user_id)


@router.post("/{novel_id}/publication", dependencies=[Depends(require_legal_consent)])
async def publish_novel(
    novel_id: uuid.UUID,
    body: NovelPublishRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> NovelPublicationStatusResponse:
    """소설을 노벨에 공개하거나 다시 공개한다(요청 하나 = 화 하나 — `NovelPublishRequest`). 세 구간은 모듈 docstring.
    바뀐 것이 없으면 아무것도 쓰지 않고 지금 상태를 돌려준다."""
    # 인증·게이트 의존성이 요청 세션에 연 읽기 트랜잭션을 닫는다(롤백은 세션의 객체를 만료시켜 쓰지 않는다).
    await db.commit()
    now = datetime.now(UTC)
    async with session_factory() as read_db:
        novel = await _get_owned_novel(read_db, novel_id, user_id)
        plan = await _plan(read_db, novel, user_id, body.chapter_id)
        if plan.items:
            await enforce_rejection_limit(read_db, user_id, now)
            try:
                _prompt_set, sections = await load_active_prompt_set(read_db, lane=NOVEL_SCREEN_LANE)
            except PromptSetNotFoundError as exc:
                raise _screening_unavailable(exc) from exc
            await enforce_call_limit(read_db, user_id)
        await read_db.commit()

    verdict = None
    if plan.items:
        try:
            verdict = await screen_novel_text(llm_client, sections=sections, items=plan.items, user_id=user_id)
        except (LLMClientError, PromptRenderError) as exc:
            raise _screening_unavailable(exc) from exc

    novel = await _lock_and_replan(db, novel_id, user_id, body.chapter_id, plan)
    if verdict is not None and not verdict.passed:
        db.add(
            _screening_row(
                novel, plan, user_id, passed=False, flagged_parts=verdict.flagged_parts, reason=verdict.reason,
                model=verdict.model,
            )
        )
        await db.commit()
        await count_rejection(user_id, now)
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "NOVEL_SCREENING_REJECTED",
            chapterOrdinal=plan.chapter.ordinal if plan.chapter is not None else None,
            flaggedParts=list(verdict.flagged_parts),
        )
    if not plan.writes_nothing:
        await _apply(db, novel, plan)
        if verdict is not None:
            db.add(_screening_row(novel, plan, user_id, passed=True, flagged_parts=(), reason=None, model=verdict.model))
        await db.commit()
    return await _status(db, novel, user_id)


@owner_router.post("/{novel_id}/publication/withdraw", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_novel_publication(
    novel_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """공개를 거둔다. 공개 상태 행과 공개본은 지우지 않고 공개 범위만 바꾼다 — 다시 공개하면 공개본이 그대로 살아난다.
    이미 거둔 공개면 그대로 204 다. 재동의 게이트를 걸지 않는다(자기 글을 내리는 일이라)."""
    await _lock_user(db, user_id)
    await _get_owned_novel(db, novel_id, user_id)
    updated = await db.scalar(
        update(NovelPublication)
        .where(NovelPublication.novel_id == novel_id)
        .values(visibility="withdrawn")
        .returning(NovelPublication.novel_id)
    )
    if updated is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_PUBLICATION_NOT_FOUND")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
