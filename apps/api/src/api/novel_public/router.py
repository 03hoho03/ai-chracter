"""노벨 게시자 라우트 — 공개 상태 조회, 공개(처음 공개·다음 화·다시 공개), 화 무료로 전환, 공개 거두기.

조회와 공개는 소설화 접근 게이트와 노벨 스위치 게이트를 라우터 수준에서 거친다 — 공개할 수 있는 사람은 소설화를 쓸 수 있는
계정뿐이다. 공개 거두기는 두 게이트 밖의 두 번째 라우터에 있고 로그인·소유권만 본다. 자기 글을 내리는 일은 기능 허용과
무관하다(소설 삭제가 게이트 밖인 것과 같은 원칙) — 운영자가 소설화 허용을 거두거나 스위치를 꺼도 게시자는 공개를 거둘 수
있어야 한다.

**공개는 세 구간이다**(작품 발행과 같은 꼴). 심사 LLM 을 기다리는 동안(수 초) DB 트랜잭션을 열어 두면 커넥션 하나를 쥐어
다른 요청이 풀을 기다리기 때문이다.

1. 읽기: 따로 연 세션에서 공개 계획(무엇을 새로 공개하고 무엇을 다시 내며 무엇을 심사하는지)을 세우고 닫는다. 판정 실패
   (이어지지 않는 화, 원작 판정, 운영 조치)는 여기서 낸다.
2. 심사: 계획이 심사할 글을 실었으면 게시자 하루 거부 상한을 보고 심사를 부른다. 삽화 스위치가 켜져 있으면 얼릴 개정의
   문단에 붙은 그림도 내려받아 운영자 내림 → 통과 기억 순으로 보고 남은 그림을 한 번에 심사한다(`illustration_screening.py`).
   글과 그림을 둘 다 불러도 상한은 요청 하나를 한 번으로 센다. 트랜잭션 없음.
3. 쓰기: 요청 세션에서 사용자 행을 잠그고 계획을 다시 세워 1 과 같은지 본다. 다르면(그사이 화를 고쳤거나 다른 요청이 먼저
   공개했다) 409 `NOVEL_PUBLISH_CONFLICT` 이고 아무것도 쓰지 않는다. 같으면 공개본을 쓴다(통과) 또는 거부 기록을 남긴다.

잠금은 사용자 행 하나다. 소설 삭제·마지막 묶음 삭제·탈퇴·스냅샷 복원이 사용자 행을 먼저 잡으므로(`novelize/router.py`
모듈 docstring 의 잠금 순서) 공개 쓰기는 그 경로들과 줄을 서고, 같은 소설의 공개 요청 둘도 여기서 줄을 선다. 화 직접 수정은
화 행만 잠그므로 쓰기 구간과 겹칠 수 있는데, 그러면 심사한 개정을 얼린다 — 공개본은 늘 심사를 거친 글이다.

**심사 실패는 공개하지 않는다**(fail-closed). 걸리면 400 `NOVEL_SCREENING_REJECTED`(어느 화의 어느 글인지 — 사유 문구는
화면이 가진다), 심사 호출이 실패하면 503 `NOVEL_SCREENING_UNAVAILABLE`(작품 발행 심사의 장애와 같은 코드 — 기다렸다 다시
시도하면 되는 일이라), 오늘 거부 상한이나 시간당 심사 호출 상한에 닿았으면 429.

**첫 공개 운영자 승인** — 정책 스위치(`novel_public_policy_v2_enabled`)가 켜졌고 소설이 아직 연재권 잠금을 갖지 않았으면
(한 번도 독자에게 보인 적 없음, `novel_public/serial_lock.py`) 자동 글 심사를 통과한 첫 공개는 바로 열리지 않고 운영자
승인을 기다린다(공개 상태 행의 `review_status` 대기, 공개 범위 `withdrawn`). 대기 중에는 그 소설의 공개 요청을 모두 409
`NOVEL_PUBLICATION_IN_REVIEW` 로 막아 운영자가 본 글과 승인되는 글을 같게 한다. 대기·반려 행은 독자에게 보인 적 없는 공개라
그 위의 공개 요청은 처음 공개와 같이 지금 원작 판정을 거친다. 잠금은 스위치와 무관하게 결과가 독자에게 열리는 쓰기(또는
승인)에서 찍힌다.

**화별 가격** — 무료·유료는 화를 처음 공개할 때 정해 화 공개본에 남긴다(`NovelPublishRequest.free`). 유료 화의 가격은
남긴 값이 아니라 늘 지금 화당 가격이다(`purchases.chapter_price`). 앞 화(`NOVEL_FREE_CHAPTER_COUNT` 까지)는 늘 무료이고,
정책 스위치가 켜져 있으면 그 뒤 화마다 무료·유료를 고른다(꺼져 있으면 지금 약관대로 그 뒤는 유료). 다시 공개는 가격을 덮지
않으므로 무료로 공개한 화는 무료로 남는다. 유료 화를 무료로 바꾸는 것은 따로 있는 "무료로 전환"(`make_chapter_free`, 스위치가
켜졌을 때만)뿐이다 — 글이 바뀌지 않으므로 심사·판 올림·공개 시각 갱신이 없고, 거둔 공개를 다시 열지 않으며, 이미 산 사람에게
환불하지 않는다. 무료에서 유료로 가는 길은 없다.

**무료 번호 기억** — 6화부터를 무료로 공개하거나 무료로 전환하면 그 번호를 소설마다 남긴다(`NovelFreeOrdinal`). 마지막 묶음
삭제로 그 화를 지우고 같은 번호의 화를 다시 만들어도, 정책 스위치가 켜져 있으면 그 번호는 무료로만 공개한다 — 독자에게 한 번
무료로 준 번호를 지웠다 다시 만드는 것으로 유료로 돌릴 수 없게. 기록과 확인은 모두 게시자 사용자 행 잠금 안에서 한다
(공개 쓰기·무료로 전환·묶음 삭제가 같은 행에서 줄을 선다).

공개 화면에 내보내는 표지는 원작 썸네일뿐이라 공개본에 표지 사본을 두지 않는다(소설 생성 표지는 심사를 거친 적이 없다)."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import ColumnElement, SQLColumnExpression, Text, and_, delete, false, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import PromptRenderError, PromptSetNotFoundError, load_active_prompt_set
from api.core import clover
from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.media import Asset
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterEdition,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelFreeOrdinal,
    NovelPublication,
    NovelScreening,
    NovelScreeningPart,
)
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.legal.documents import current_legal_version
from api.llm.client import LLMClient, LLMClientError, LLMRateLimitError
from api.llm.dependencies import get_llm_client
from api.novel_public.access import RepublishBlock, judge_source, require_novel_public_enabled
from api.novel_public.illustration_screening import (
    NOVEL_ILLUSTRATION_SCREEN_LANE,
    TAKEN_DOWN_REASON,
    IllustrationVerdict,
    PlannedPicture,
    build_novel_illustration_screen_prompt,
    download_pictures,
    picture_label,
    prompt_version,
    remember_passes,
    remembered_shas,
    screen_novel_illustrations,
    screening_model,
    sha256_of,
    taken_down_shas,
)
from api.novel_public.purchases import chapter_price
from api.novel_public.schemas import (
    NovelPublicationScreening,
    NovelPublicationStatusResponse,
    NovelPublishedChapter,
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
from api.novel_public.serial_lock import lock_in_effect, lock_serial, needs_review
from api.novelize.access import require_novelize_access
from api.novelize.billing import _lock_user
from api.novelize.illustrations import NOVEL_ILLUSTRATION_LIMIT, placement_fingerprint, placements_of
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
    """공개하거나 다시 낼 화 하나와 그때 얼릴 값. `price` 는 새로 공개하는 화면 그때 저장할 값(0 = 무료, 유료면 지금 화당
    가격), 다시 내는 화면 지금 가격이다 — 다시 내기는 가격을 쓰지 않지만 재계획 비교에 들어가, 심사를 기다리는 사이 그 화가
    무료로 바뀌면 쓰지 않고 409 `NOVEL_PUBLISH_CONFLICT` 다(다시 누르면 된다).

    `change_summary` 는 이 판의 판 행에 남길 작가의 변경 요약이다. 정책 스위치가 켜졌고 이미 공개한 화를 다시 낼 때만
    있다(그때는 꼭 있다) — 새 화·스위치가 꺼진 동안에는 요청에 실려 와도 None 이다.

    `text_changed` 는 화의 글(제목·작가의 말·본문)이 공개본과 다른가(새 화면 참) — 거짓이면 그림만 바뀐 화라 글은 다시
    심사하지 않는다. `pictures` 는 얼릴 개정의 문단에 붙은 그림(심사할 것)이고, `screens_pictures` 는 삽화 스위치가 켜져
    이 공개가 그림을 심사하고 심사 시각을 찍는가다. 꺼져 있으면 그림을 보지 않고 시각을 비운 채 얼린다 — 읽기는 시각이 찬
    판에서만 그림을 싣으므로 미심사 그림이 독자에게 나가지 않는다. 그림은 개정 id 에 묶여 바뀌지 않으므로(배치 행은 고치지
    않는다) 재계획 비교의 개정 id 가 "심사한 그림 = 얼릴 그림"을 보장한다 — 그림 목록도 비교에 함께 들어간다."""

    chapter_id: uuid.UUID
    ordinal: int
    revision_id: uuid.UUID
    title: str | None
    author_note: str
    body: str
    is_new: bool
    price: int
    change_summary: str | None
    text_changed: bool
    pictures: tuple[PlannedPicture, ...]
    screens_pictures: bool


@dataclass(frozen=True)
class _PublishPlan:
    """읽기 구간이 세운 계획. 쓰기 구간이 같은 함수로 다시 세워 이것과 같아야 쓴다 — 그사이 바뀐 것이 있으면 심사한 글과
    쓸 글이 어긋난다."""

    has_publication: bool
    reopen: bool
    # 공개 상태 행이 운영자 승인 대기·반려라 독자에게 보인 적이 없다. 이 위의 공개는 처음 공개처럼 원작 판정을 거치고,
    # 승인 없이 열면 심사 칸을 비운다.
    unseen: bool
    # 이 요청의 결과가 독자에게 열리지 않고 운영자 승인을 기다린다.
    review: bool
    # 다시 낼 소설 제목·소개. 공개본과 같으면 None.
    metadata: tuple[str | None, str] | None
    # 새로 공개하거나 다시 낼 화. 이미 공개한 화가 공개본과 같으면 None.
    chapter: _ChapterPlan | None
    items: tuple[NovelScreenItem, ...]

    @property
    def writes_nothing(self) -> bool:
        return self.has_publication and not self.reopen and self.metadata is None and self.chapter is None


def _items(plan_metadata: tuple[str | None, str] | None, chapter: _ChapterPlan | None) -> tuple[NovelScreenItem, ...]:
    """심사할 글. 빈 칸은 싣지 않는다 — 제목이 없으면(원작 제목으로 대신) 심사할 글이 아니다. 그림만 바뀐 화(`text_changed`
    거짓)는 이미 심사를 통과해 얼린 글과 같으므로 화의 글을 싣지 않는다(변경 요약은 이번 판의 새 글이라 싣는다)."""
    items: list[NovelScreenItem] = []
    if plan_metadata is not None:
        title, synopsis = plan_metadata
        if title is not None and title.strip():
            items.append(NovelScreenItem(part="novel_title", text=title))
        if synopsis.strip():
            items.append(NovelScreenItem(part="synopsis", text=synopsis))
    if chapter is not None and chapter.text_changed:
        if chapter.title is not None and chapter.title.strip():
            items.append(NovelScreenItem(part="chapter_title", text=chapter.title))
        if chapter.author_note.strip():
            items.append(NovelScreenItem(part="author_note", text=chapter.author_note))
        if chapter.body.strip():
            items.append(NovelScreenItem(part="chapter_body", text=chapter.body))
    if chapter is not None:
        if chapter.change_summary is not None:
            items.append(NovelScreenItem(part="change_summary", text=chapter.change_summary))
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


def _price_for(
    ordinal: int, frozen: NovelChapterPublication | None, free: bool | None, *, remembered_free: bool
) -> int:
    """이 요청이 그 화에 둘 가격(`NovelPublishRequest.free` 의 규칙). 이미 공개한 화는 지금 가격을 돌려준다(쓰지 않는다).
    정책 스위치가 꺼져 있으면 요청의 선택을 보지 않는다. `remembered_free` 는 새 화의 번호가 무료로 나간 적 있는가(스위치가
    켜졌을 때만 참) — 앞 화처럼 무료로만 공개한다."""
    choice = free if settings.novel_public_policy_v2_enabled else None
    if frozen is not None:
        current = chapter_price(frozen.ordinal, frozen.price)
        if choice is False and current == 0:
            raise _error(status.HTTP_409_CONFLICT, "NOVEL_CHAPTER_PRICE_LOCKED")
        if choice is True and current > 0:
            raise _error(status.HTTP_409_CONFLICT, "NOVEL_CHAPTER_ALREADY_PRICED")
        return current
    if ordinal <= clover.NOVEL_FREE_CHAPTER_COUNT or remembered_free:
        if choice is False:
            raise _error(status.HTTP_409_CONFLICT, "NOVEL_CHAPTER_PRICE_LOCKED")
        return 0
    return 0 if choice is True else clover.NOVEL_READ_COST


async def _remembered_free(db: AsyncSession, novel_id: uuid.UUID, ordinal: int) -> bool:
    """새로 공개할 화의 번호가 무료로 나간 적 있는가. 정책 스위치가 꺼져 있으면 보지 않는다(지금 약관대로 6화부터 유료)."""
    if not settings.novel_public_policy_v2_enabled or ordinal <= clover.NOVEL_FREE_CHAPTER_COUNT:
        return False
    found = await db.scalar(
        select(NovelFreeOrdinal.ordinal).where(NovelFreeOrdinal.novel_id == novel_id, NovelFreeOrdinal.ordinal == ordinal)
    )
    return found is not None


async def _remember_free(db: AsyncSession, novel_id: uuid.UUID, ordinal: int) -> None:
    """이 번호가 무료로 나갔다고 남긴다(이미 있으면 그대로). 앞 화는 상수가 무료로 지키므로 남기지 않는다."""
    if ordinal <= clover.NOVEL_FREE_CHAPTER_COUNT:
        return
    await db.execute(
        insert(NovelFreeOrdinal).values(novel_id=novel_id, ordinal=ordinal).on_conflict_do_nothing()
    )


async def _plan(db: AsyncSession, novel: Novel, user_id: uuid.UUID, body: NovelPublishRequest) -> _PublishPlan:
    publication = await db.get(NovelPublication, novel.id, populate_existing=True)
    if publication is not None and publication.moderation_status == "restricted":
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_PUBLICATION_RESTRICTED")
    # 운영자가 판매를 멈춘 공개는 새 화도 고친 글도 받지 않는다 — 판매 중단은 "공개·신규 판매 중단"이다. 거두기·무료로 전환은
    # 이 계획을 거치지 않아 된다.
    if publication is not None and publication.sales_stopped_at is not None:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_PUBLICATION_SALES_STOPPED")
    if (
        publication is not None
        and publication.review_status == "pending"
        and settings.novel_public_policy_v2_enabled
    ):
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_PUBLICATION_IN_REVIEW")
    unseen = publication is not None and publication.review_status in ("pending", "rejected")
    gate = await judge_source(db, novel.content_id, user_id, permission_locked=lock_in_effect(novel))
    if not gate.source_available:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_UNAVAILABLE")

    published = await _published_count(db, novel.id)
    chapter_plan: _ChapterPlan | None = None
    # 보인 적 없는 공개 상태 행 위의 요청은 처음 공개와 같다 — 허락·목록 판정을 건너뛴 채 잠금을 얻는 길을 막는다.
    is_new = publication is None or unseen
    chapter_id = body.chapter_id
    if chapter_id is None:
        # 화 공개본이 하나도 없는 보인 적 없는 행(반려로 화 공개본이 지워짐)도 처음 공개처럼 1화부터 내야 한다.
        if publication is None or (unseen and published == 0):
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
        remembered_free = frozen is None and await _remembered_free(db, novel.id, chapter.ordinal)
        price = _price_for(chapter.ordinal, frozen, body.free, remembered_free=remembered_free)
        chapter_is_new = frozen is None
        is_new = is_new or chapter_is_new
        changed, text_changed = (True, True) if frozen is None else await _chapter_changes(db, chapter, revision)
        if changed:
            # 변경 요약은 새 판을 내는 다시 공개에만 쓴다. 스위치가 켜져 있으면 꼭 있어야 한다 — 심사를 부르기 전에 거절한다.
            change_summary = (
                body.change_summary if settings.novel_public_policy_v2_enabled and not chapter_is_new else None
            )
            if settings.novel_public_policy_v2_enabled and not chapter_is_new and change_summary is None:
                raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_CHANGE_SUMMARY_REQUIRED")
            chapter_plan = _ChapterPlan(
                chapter_id=chapter.id,
                ordinal=chapter.ordinal,
                revision_id=revision.id,
                title=chapter.title,
                author_note=chapter.author_note,
                body=revision.body,
                is_new=chapter_is_new,
                price=price,
                change_summary=change_summary,
                text_changed=text_changed,
                pictures=await _planned_pictures(db, revision) if settings.novel_illustrations_enabled else (),
                screens_pictures=settings.novel_illustrations_enabled,
            )
            if len(chapter_plan.pictures) > NOVEL_ILLUSTRATION_LIMIT:
                raise _error(status.HTTP_409_CONFLICT, "NOVEL_ILLUSTRATION_LIMIT_EXCEEDED")
    if is_new and gate.new_publish_block is not None:
        status_code = status.HTTP_403_FORBIDDEN if gate.new_publish_block == "source_permission" else 409
        raise _error(status_code, "NOVEL_SOURCE_NOT_PUBLISHABLE", reason=gate.new_publish_block)
    # 남의 원작 그림은 원작의 소설화 허락이 공개일 때만 노벨에 낸다 — 비공개 소장만 허락한 원작의 그림이다. 판정은 글의 새 공개와
    # 같은 원작 판정 하나라서 연재권 잠금이 효력이 있으면(그 소설에 한정된 허락이 이어진다) 원작 그림도 계속 낸다. 이미 공개한
    # 화를 다시 낼 때도 본다 — 글과 달리 그 그림은 이번 공개로 처음 노벨에 나간다.
    if (
        chapter_plan is not None
        and gate.new_publish_block == "source_permission"
        and any(picture.source == "original" for picture in chapter_plan.pictures)
    ):
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_ILLUSTRATION_ORIGINAL_NOT_PUBLISHABLE")

    metadata: tuple[str | None, str] | None = None
    if publication is None or (publication.title, publication.synopsis) != (novel.title, novel.synopsis):
        metadata = (novel.title, novel.synopsis)
    return _PublishPlan(
        has_publication=publication is not None,
        reopen=publication is not None and publication.visibility == "withdrawn",
        unseen=unseen,
        review=needs_review(novel) and (publication is None or unseen),
        metadata=metadata,
        chapter=chapter_plan,
        items=_items(metadata, chapter_plan),
    )


async def _planned_pictures(db: AsyncSession, revision: NovelChapterRevision) -> tuple[PlannedPicture, ...]:
    """개정의 문단에 붙은 그림을 읽는 순서로(심사 순서 = 프롬프트 목록 순서). 위치 확인 필요인 그림은 독자에게 안 나가 뺀다."""
    rows = [row for row in await placements_of(db, revision) if row.anchor_block_id is not None]
    if not rows:
        return ()
    keys = dict(
        (await db.execute(select(Asset.id, Asset.storage_key).where(Asset.id.in_({row.asset_id for row in rows}))))
        .tuples()
        .all()
    )
    position = {block_id: index for index, block_id in enumerate(revision.block_ids)}
    pictures: list[PlannedPicture] = []
    for row in rows:
        if row.anchor_block_id is None or row.placement is None:
            continue
        pictures.append(
            PlannedPicture(
                asset_id=row.asset_id,
                storage_key=keys[row.asset_id],
                source=row.source,
                paragraph=position[row.anchor_block_id],
                placement=row.placement,
            )
        )
    return tuple(pictures)


def _text_differs_from_publication(
    title: SQLColumnExpression[str | None] | str | None,
    author_note: SQLColumnExpression[str] | str,
    current_hash: SQLColumnExpression[str] | str,
) -> ColumnElement[bool]:
    """화 공개본의 글(제목·작가의 말·본문)이 지금 화와 다른가. 본문은 얼린 개정과 지금 개정의 본문 해시로 비교한다 — 옛 판으로
    되돌리기는 같은 본문의 새 개정을 만드는데, 이미 심사를 통과한 글을 다시 심사할 이유가 없다. 개정을 쓰는 경로는 본문을 문단을
    빈 줄 하나로 이은 모양으로 저장하므로 해시 비교는 글자 비교와 결과가 같다."""
    frozen_hash = (
        select(NovelChapterRevision.content_hash)
        .where(NovelChapterRevision.id == NovelChapterPublication.revision_id)
        .correlate(NovelChapterPublication)
        .scalar_subquery()
    )
    return or_(
        NovelChapterPublication.title.is_distinct_from(title),
        NovelChapterPublication.author_note != author_note,
        frozen_hash != current_hash,
    )


def _pictures_differ_from_publication(current_revision_id: SQLColumnExpression[uuid.UUID] | uuid.UUID) -> ColumnElement[bool]:
    """화 공개본의 삽화가 지금 화와 다른가 — 삽화 스위치가 켜졌을 때만 본다(꺼진 동안은 그림이 독자에게 안 나가고 공개도 그림을
    심사하지 않으니 그림만 바뀐 화를 다시 낼 일이 없다). 독자 화면의 그림 모양(`placement_fingerprint`)이 다르거나, 얼린 개정에
    문단에 붙은 그림이 있는데 심사 시각이 비었으면(꺼진 동안 얼린 공개본) 바뀐 화다 — 다시 공개하면 심사를 거쳐 그림이 열린다."""
    if not settings.novel_illustrations_enabled:
        return false()
    frozen = placement_fingerprint(NovelChapterPublication.revision_id)
    return or_(
        frozen.is_distinct_from(placement_fingerprint(current_revision_id)),
        and_(NovelChapterPublication.illustrations_screened_at.is_(None), frozen.is_not(None)),
    )


def _differs_from_publication(
    title: SQLColumnExpression[str | None] | str | None,
    author_note: SQLColumnExpression[str] | str,
    current_hash: SQLColumnExpression[str] | str,
    current_revision_id: SQLColumnExpression[uuid.UUID] | uuid.UUID,
) -> ColumnElement[bool]:
    """화 공개본(`NovelChapterPublication` 행)이 지금 화와 다른가 — 다시 공개의 계획(`_chapter_changes`)과 작가 상태의
    "바뀐 공개 화"(`_changed_chapter_ordinals`)가 함께 쓰는 하나의 기준이다. 둘이 따로 비교하면 상태는 바뀐 화로 알리는데
    다시 공개는 아무것도 안 쓰는(또는 그 반대) 화가 생긴다. 글(`_text_differs_from_publication`)이나 삽화
    (`_pictures_differ_from_publication`)가 다르면 다르다."""
    return or_(
        _text_differs_from_publication(title, author_note, current_hash),
        _pictures_differ_from_publication(current_revision_id),
    )


async def _chapter_changes(
    db: AsyncSession, chapter: NovelChapter, revision: NovelChapterRevision
) -> tuple[bool, bool]:
    """공개한 화 `chapter` 의 공개본이 지금 화(`revision` = 지금 개정)와 다른가(`_differs_from_publication`)와, 그중 글이
    다른가."""
    row = (
        await db.execute(
            select(
                _differs_from_publication(chapter.title, chapter.author_note, revision.content_hash, revision.id),
                _text_differs_from_publication(chapter.title, chapter.author_note, revision.content_hash),
            ).where(NovelChapterPublication.chapter_id == chapter.id)
        )
    ).one()
    return bool(row[0]), bool(row[1])


# ── 상태 ────────────────────────────────────────────────────────────────────
async def _changed_chapter_ordinals(db: AsyncSession, novel_id: uuid.UUID) -> list[int]:
    """공개본과 지금이 다른 공개 화의 번호(오름차순). `_chapter_changes` 와 같은 기준(`_differs_from_publication`)을 한
    쿼리로 쓴다 — 화마다 따로 읽으면 공개 화 수만큼 쿼리가 는다. 현재 개정은 화마다 `revision_no` 가 가장 큰 개정이다."""
    current = (
        select(NovelChapterRevision.chapter_id, NovelChapterRevision.id, NovelChapterRevision.content_hash)
        .distinct(NovelChapterRevision.chapter_id)
        .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
        .where(NovelChapter.novel_id == novel_id)
        .order_by(NovelChapterRevision.chapter_id, NovelChapterRevision.revision_no.desc())
        .subquery()
    )
    rows = await db.scalars(
        select(NovelChapterPublication.ordinal)
        .join(NovelChapter, NovelChapter.id == NovelChapterPublication.chapter_id)
        .join(current, current.c.chapter_id == NovelChapterPublication.chapter_id)
        .where(
            NovelChapterPublication.novel_id == novel_id,
            _differs_from_publication(
                NovelChapter.title, NovelChapter.author_note, current.c.content_hash, current.c.id
            ),
        )
        .order_by(NovelChapterPublication.ordinal)
    )
    return list(rows.all())


async def _published_chapters(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelPublishedChapter]:
    rows = await db.execute(
        select(NovelChapterPublication.chapter_id, NovelChapterPublication.ordinal, NovelChapterPublication.price)
        .where(NovelChapterPublication.novel_id == novel_id)
        .order_by(NovelChapterPublication.ordinal)
        .execution_options(populate_existing=True)
    )
    return [
        NovelPublishedChapter(chapter_id=chapter_id, ordinal=ordinal, price=chapter_price(ordinal, price))
        for chapter_id, ordinal, price in rows.tuples()
    ]


async def _free_locked_ordinals(db: AsyncSession, novel_id: uuid.UUID, published: int) -> list[int]:
    """아직 공개하지 않은 번호 중 무료로만 공개할 수 있는 번호(오름차순). 정책 스위치가 꺼져 있으면 지키지 않으므로 비운다."""
    if not settings.novel_public_policy_v2_enabled:
        return []
    rows = await db.scalars(
        select(NovelFreeOrdinal.ordinal)
        .where(NovelFreeOrdinal.novel_id == novel_id, NovelFreeOrdinal.ordinal > published)
        .order_by(NovelFreeOrdinal.ordinal)
    )
    return list(rows.all())


async def _status(db: AsyncSession, novel: Novel, user_id: uuid.UUID) -> NovelPublicationStatusResponse:
    publication = await db.get(NovelPublication, novel.id, populate_existing=True)
    gate = await judge_source(db, novel.content_id, user_id, permission_locked=lock_in_effect(novel))
    republish_block: RepublishBlock | None = None
    if publication is not None and publication.moderation_status == "restricted":
        republish_block = "restricted"
    elif publication is not None and publication.sales_stopped_at is not None:
        republish_block = "sales_stopped"
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
    published_count = await _published_count(db, novel.id)
    return NovelPublicationStatusResponse(
        published=publication is not None,
        visibility=publication.visibility if publication is not None else None,
        moderation_status=publication.moderation_status if publication is not None else None,
        published_chapter_count=published_count,
        published_chapters=await _published_chapters(db, novel.id),
        free_locked_ordinals=await _free_locked_ordinals(db, novel.id, published_count),
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
        review_status=publication.review_status if publication is not None else None,
        review_reason=(
            publication.review_reason
            if publication is not None and publication.review_status == "rejected"
            else None
        ),
        reviewed_at=publication.reviewed_at if publication is not None else None,
        review_required=needs_review(novel),
        sales_stopped=publication is not None and publication.sales_stopped_at is not None,
    )


# ── 쓰기 ────────────────────────────────────────────────────────────────────
async def _apply(db: AsyncSession, novel: Novel, plan: _PublishPlan, *, terms_version: str | None) -> None:
    """계획대로 공개본을 쓴다. 승인 대기로 가는 요청(`plan.review`)은 공개 범위를 `withdrawn` 으로 두고 대기를 표시하고,
    그 밖에는 결과가 독자에게 열리므로 연재권 잠금을 찍는다(이미 잠겼으면 그대로). 화를 공개하거나 다시 내면 그 판의 판 행을
    하나 쌓는다(`_record_edition`) — 다시 내기가 화 공개본을 덮어도 산 사람이 산 때의 판을 다시 읽을 수 있게. 새 화를
    6화부터 무료로 공개하면 그 번호를 남긴다(`_remember_free`).

    공개 범위와 심사 칸은 같은 UPDATE 문으로 바꾼다 — 대기·반려 행은 `withdrawn` 이어야 한다는 CHECK 가 문장마다 걸리므로
    나눠 쓰면 첫 문장이 거부된다."""
    now = func.now()
    if not plan.has_publication:
        assert plan.metadata is not None  # 처음 공개는 언제나 소설 제목·소개를 얼린다
        title, synopsis = plan.metadata
        db.add(
            NovelPublication(
                novel_id=novel.id,
                visibility="withdrawn" if plan.review else "public",
                review_status="pending" if plan.review else None,
                title=title,
                synopsis=synopsis,
            )
        )
        await db.flush()
    else:
        values: dict[str, object] = {}
        if plan.review:
            # 반려 뒤 다시 신청 — 공개 범위는 `withdrawn` 그대로 두고 새 대기로 돌린다.
            values.update(review_status="pending", review_reason=None, reviewed_at=None, published_at=now)
        elif plan.reopen:
            values["visibility"] = "public"
            if plan.unseen:
                # 스위치가 꺼진 뒤 남은 대기·반려 행을 승인 없이 연다(원작 판정은 계획에서 처음 공개처럼 거쳤다). 독자에게
                # 처음 열리는 때라 승인처럼 처음 공개 시각과 공개 시각을 지금으로 찍는다 — 신청 시각이 남으면 연재권 잠금
                # 시각과 어긋나고 최신순 목록에서도 신청한 날 자리에 놓인다.
                values.update(
                    review_status=None,
                    review_reason=None,
                    reviewed_at=None,
                    first_published_at=now,
                    published_at=now,
                )
        if plan.metadata is not None:
            values["title"], values["synopsis"] = plan.metadata
        if plan.metadata is not None or plan.chapter is not None:
            values["published_at"] = now
        if values:
            await db.execute(update(NovelPublication).where(NovelPublication.novel_id == novel.id).values(**values))
    if not plan.review:
        await lock_serial(db, novel.id, terms_version=terms_version)
    chapter = plan.chapter
    if chapter is None:
        return
    # 이 공개가 얼리는 개정의 그림을 심사했으면 지금, 아니면(스위치 꺼짐) 비운다 — 다시 내기가 앞 판의 시각을 남기면 심사하지
    # 않은 새 개정의 그림이 독자에게 나간다.
    screened_at = now if chapter.screens_pictures else None
    if chapter.is_new:
        db.add(
            NovelChapterPublication(
                chapter_id=chapter.chapter_id,
                novel_id=novel.id,
                ordinal=chapter.ordinal,
                revision_id=chapter.revision_id,
                title=chapter.title,
                author_note=chapter.author_note,
                price=chapter.price,
                illustrations_screened_at=screened_at,
            )
        )
        await db.flush()
        if chapter.price == 0:
            await _remember_free(db, novel.id, chapter.ordinal)
    else:
        await db.execute(
            update(NovelChapterPublication)
            .where(NovelChapterPublication.chapter_id == chapter.chapter_id)
            .values(
                revision_id=chapter.revision_id,
                title=chapter.title,
                author_note=chapter.author_note,
                edition=NovelChapterPublication.edition + 1,
                published_at=now,
                illustrations_screened_at=screened_at,
            )
        )
    await _record_edition(db, chapter.chapter_id, chapter.change_summary)


async def _record_edition(db: AsyncSession, chapter_id: uuid.UUID, change_summary: str | None) -> None:
    """방금 쓴 화 공개본의 지금 판을 판 행으로 남긴다(정책 스위치와 무관) — 화 공개본 행을 그대로 베껴 판 번호·개정·제목·
    작가의 말·공개 시각·삽화 심사 시각이 공개본과 어긋나지 않는다. 변경 요약은 화 공개본에 없어 요청 값을 그대로 싣는다.

    같은 (화, 판) 행이 이미 있으면 덮어쓴다. 그런 행은 독자에게 보인 적 없는 판뿐이다 — 판 행은 승인 대기 공개에서도
    쓰이는데, 배포가 겹치는 동안 판 행을 모르는 옛 이미지가 그 대기를 반려·취소하면 화 공개본만 지우고 판 행은 남긴다.
    그 소설을 다시 공개하면 화 공개본이 1판부터 다시 시작해 남은 행과 부딪친다. 보인 적 있는 판은 화 공개본이 지워지지
    않는 한 판 번호가 줄지 않고, 화를 지우면 판 행도 함께 지워지므로 덮어쓰는 행이 산 사람의 판일 수 없다."""
    current = select(
        NovelChapterPublication.chapter_id,
        NovelChapterPublication.edition,
        NovelChapterPublication.novel_id,
        NovelChapterPublication.revision_id,
        NovelChapterPublication.title,
        NovelChapterPublication.author_note,
        NovelChapterPublication.published_at,
        literal(change_summary, Text),
        NovelChapterPublication.illustrations_screened_at,
    ).where(NovelChapterPublication.chapter_id == chapter_id)
    statement = insert(NovelChapterEdition).from_select(
        [
            "chapter_id",
            "edition",
            "novel_id",
            "revision_id",
            "title",
            "author_note",
            "published_at",
            "change_summary",
            "illustrations_screened_at",
        ],
        current,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[NovelChapterEdition.chapter_id, NovelChapterEdition.edition],
            set_={
                "novel_id": statement.excluded.novel_id,
                "revision_id": statement.excluded.revision_id,
                "title": statement.excluded.title,
                "author_note": statement.excluded.author_note,
                "published_at": statement.excluded.published_at,
                "change_summary": statement.excluded.change_summary,
                "illustrations_screened_at": statement.excluded.illustrations_screened_at,
            },
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
    db: AsyncSession, novel_id: uuid.UUID, user_id: uuid.UUID, body: NovelPublishRequest, planned: _PublishPlan
) -> Novel:
    """쓰기 구간의 시작. 사용자 행을 잠근 뒤 계획을 다시 세워 읽기 구간의 것과 같은지 본다."""
    await _lock_user(db, user_id)
    novel = await _get_owned_novel(db, novel_id, user_id)
    if await _plan(db, novel, user_id, body) != planned:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_PUBLISH_CONFLICT")
    return novel


def _screening_unavailable(exc: Exception) -> HTTPException:
    logger.warning("novel_screen_unavailable: %s", exc)
    if isinstance(exc, LLMClientError):
        capture_dependency_failure(
            exc, dependency="gemini_rate_limit" if isinstance(exc, LLMRateLimitError) else "gemini"
        )
    elif isinstance(exc, (BotoCoreError, ClientError)):
        capture_dependency_failure(exc, dependency="s3")
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
        plan = await _plan(read_db, novel, user_id, body)
        pictures = plan.chapter.pictures if plan.chapter is not None else ()
        try:
            sections = (await load_active_prompt_set(read_db, lane=NOVEL_SCREEN_LANE))[1] if plan.items else []
            picture_prompt = (
                await load_active_prompt_set(read_db, lane=NOVEL_ILLUSTRATION_SCREEN_LANE) if pictures else None
            )
        except PromptSetNotFoundError as exc:
            raise _screening_unavailable(exc) from exc
        await read_db.commit()

    # 그림은 트랜잭션 밖에서 내려받는다(장마다 수백 KB, 저장소 왕복). 못 받으면 심사할 수 없으니 공개하지 않는다.
    try:
        picture_bytes = await download_pictures(pictures)
    except (BotoCoreError, ClientError) as exc:
        raise _screening_unavailable(exc) from exc
    shas = tuple(sha256_of(data) for data in picture_bytes)
    picture_model = screening_model()
    version = prompt_version(picture_prompt[0].id, novel.content_type) if picture_prompt is not None else ""
    # 심사에 실을 그림(첫 자리만 — 같은 바이트가 두 자리에 있으면 한 번). 운영자가 내린 바이트가 있으면 심사 없이 거부하므로
    # 통과 기억도 보지 않는다(내림이 기억보다 먼저다).
    to_screen: list[int] = []
    taken_down = False
    if plan.items or shas:
        async with session_factory() as read_db:
            taken_down = bool(await taken_down_shas(read_db, shas))
            if not taken_down:
                remembered = await remembered_shas(read_db, shas, model=picture_model, version=version)
                for index, sha in enumerate(shas):
                    if sha not in remembered and sha not in {shas[i] for i in to_screen}:
                        to_screen.append(index)
            # 상한은 공개 요청 하나를 한 번으로 센다 — 글과 그림 심사를 둘 다 불러도 게시자의 시간당 상한이 반으로 줄지 않게.
            if plan.items or to_screen:
                await enforce_rejection_limit(read_db, user_id, now)
                await enforce_call_limit(read_db, user_id)
            await read_db.commit()

    verdict = None
    if plan.items:
        try:
            verdict = await screen_novel_text(llm_client, sections=sections, items=plan.items, user_id=user_id)
        except (LLMClientError, PromptRenderError) as exc:
            raise _screening_unavailable(exc) from exc
    picture_verdict: IllustrationVerdict | None = None
    if to_screen:
        assert picture_prompt is not None  # 그림이 있으면 위에서 세트를 읽었다
        try:
            prompt = build_novel_illustration_screen_prompt(
                picture_prompt[1],
                scope=novel.content_type,
                labels=[picture_label(pictures[index].paragraph, pictures[index].placement) for index in to_screen],
            )
            picture_verdict = await screen_novel_illustrations(
                llm_client, prompt=prompt, images=[picture_bytes[index] for index in to_screen], user_id=user_id
            )
        except (LLMClientError, PromptRenderError) as exc:
            raise _screening_unavailable(exc) from exc

    novel = await _lock_and_replan(db, novel_id, user_id, body, plan)
    # 심사를 기다리는 사이 운영자가 그 바이트를 내렸을 수 있다 — 잠근 뒤 다시 본다.
    taken_down = taken_down or bool(await taken_down_shas(db, shas))
    text_rejected = verdict is not None and not verdict.passed
    pictures_rejected = taken_down or (picture_verdict is not None and not picture_verdict.passed)
    if text_rejected or pictures_rejected:
        flagged: list[NovelScreeningPart] = list(verdict.flagged_parts) if verdict is not None and text_rejected else []
        reasons = [verdict.reason] if verdict is not None and text_rejected else []
        if pictures_rejected:
            flagged.append("illustration")
            reasons.append(TAKEN_DOWN_REASON if taken_down else picture_verdict.reason if picture_verdict else None)
        db.add(
            _screening_row(
                novel,
                plan,
                user_id,
                passed=False,
                flagged_parts=flagged,
                reason=" / ".join(reason for reason in reasons if reason) or None,
                model=verdict.model if verdict is not None else picture_model,
            )
        )
        await db.commit()
        await count_rejection(user_id, now)
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "NOVEL_SCREENING_REJECTED",
            chapterOrdinal=plan.chapter.ordinal if plan.chapter is not None else None,
            flaggedParts=flagged,
        )
    if not plan.writes_nothing:
        terms_version = await current_legal_version(db, "terms", now=datetime.now(UTC))
        await _apply(db, novel, plan, terms_version=terms_version)
        if picture_verdict is not None:
            await remember_passes(
                db, [shas[index] for index in to_screen], model=picture_verdict.model, version=version
            )
        screened_by = verdict or picture_verdict
        if screened_by is not None:
            db.add(
                _screening_row(novel, plan, user_id, passed=True, flagged_parts=(), reason=None, model=screened_by.model)
            )
        await db.commit()
        # 잠금은 ORM 객체를 거치지 않는 UPDATE 로 찍혀 객체의 잠금 칸이 낡았다. 상태 응답의 승인 필요 여부가 그 칸을 본다.
        await db.refresh(novel)
    return await _status(db, novel, user_id)


async def make_chapter_free(
    db: AsyncSession, *, user_id: uuid.UUID, novel_id: uuid.UUID, chapter_id: uuid.UUID
) -> None:
    """게시자가 공개한 유료 화를 무료로 바꾼다. **커밋하지 않는다**(라우트가 한다). 그 화의 가격 칸과 바꾼 시각만 쓴다 —
    글이 바뀌지 않으므로 심사·판 올림·판 행·공개 상태(공개 범위·공개 시각)는 그대로다. 이미 무료인 화면 아무것도 쓰지
    않는다. 산 사람의 구매는 그대로 두고 환불하지 않는다. 바꾼 화의 번호는 무료로 나간 번호로 남겨, 그 화를 지우고 다시
    만들어도 무료로만 공개한다(모듈 docstring 의 무료 번호 기억).

    - 409 `NOVEL_PRICE_CHOICE_DISABLED`: 정책 스위치가 꺼져 있다(지금 약관은 화 번호로 가격을 정한다).
    - 404 `NOVEL_NOT_FOUND`·403 `NOVEL_FORBIDDEN`: 없는(숨긴) 소설·남의 소설.
    - 404 `NOVEL_CHAPTER_NOT_FOUND`: 그 소설의 공개한 화가 아니다.

    게시자 행을 먼저 잠근다 — 구매도 게시자 행을 잡으므로 둘은 줄을 서고, 뒤에 선 구매는 잠근 뒤 다시 읽은 가격(0)으로 살
    것이 없다고 거절하며, 앞선 구매는 낸 그대로 남는다."""
    if not settings.novel_public_policy_v2_enabled:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_PRICE_CHOICE_DISABLED")
    await _lock_user(db, user_id)
    await _get_owned_novel(db, novel_id, user_id)
    publication = await db.scalar(
        select(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == chapter_id, NovelChapterPublication.novel_id == novel_id)
        .execution_options(populate_existing=True)
    )
    if publication is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    if chapter_price(publication.ordinal, publication.price) == 0:
        return
    await db.execute(
        update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == chapter_id)
        .values(price=0, price_changed_at=func.now())
    )
    await _remember_free(db, novel_id, publication.ordinal)


@router.post("/{novel_id}/publication/chapters/{chapter_id}/free", dependencies=[Depends(require_legal_consent)])
async def make_novel_chapter_free(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelPublicationStatusResponse:
    """공개한 유료 화를 무료로 바꾸고 바뀐 공개 상태를 돌려준다(`make_chapter_free`)."""
    await make_chapter_free(db, user_id=user_id, novel_id=novel_id, chapter_id=chapter_id)
    await db.commit()
    novel = await _get_owned_novel(db, novel_id, user_id)
    return await _status(db, novel, user_id)


@owner_router.post("/{novel_id}/publication/withdraw", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_novel_publication(
    novel_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """공개를 거둔다. 공개 상태 행과 공개본은 지우지 않고 공개 범위만 바꾼다 — 다시 공개하면 공개본이 그대로 살아난다.
    이미 거둔 공개면 그대로 204 다. 재동의 게이트를 걸지 않는다(자기 글을 내리는 일이라).

    운영자 승인을 기다리는 공개를 거두는 것은 신청 취소다 — 독자에게 보인 적 없는 글이라 공개 상태 행과 화 공개본, 그 판
    행을 지운다.
    대기 조건을 건 DELETE 를 먼저 낸다. 그 문장이 승인과 같은 공개 상태 행 잠금에서 줄을 서므로, 승인이 먼저 커밋했으면
    다시 평가한 조건에 걸려 아무것도 지우지 않고 아래의 보통 거두기가 된다. 읽어서 대기면 지우는 식으로 하면 승인 커밋 뒤에도
    지워져 공개 상태 행 없이 잠금만 남은 소설이 생긴다. 정책 스위치와 무관하다."""
    await _lock_user(db, user_id)
    await _get_owned_novel(db, novel_id, user_id)
    cancelled = await db.scalar(
        delete(NovelPublication)
        .where(NovelPublication.novel_id == novel_id, NovelPublication.review_status == "pending")
        .returning(NovelPublication.novel_id)
    )
    if cancelled is not None:
        await db.execute(delete(NovelChapterPublication).where(NovelChapterPublication.novel_id == novel_id))
        await db.execute(delete(NovelChapterEdition).where(NovelChapterEdition.novel_id == novel_id))
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
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
