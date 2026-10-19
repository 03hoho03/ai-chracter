"""노벨 독자 라우트 — 목록, 작품 정보, 화 읽기, 읽은 자리, 좋아요, 홈 노벨.

전부 로그인 회원만 부른다. 소설화 접근 게이트는 걸지 않는다 — 노벨을 읽는 것은 소설화 기능 허용과 무관하다. 노벨 스위치가
꺼져 있거나 미리보기 명단 밖이면 404 `NOVEL_PUBLIC_DISABLED` 다(`require_novel_public_readable`). 화 읽기와 작품 정보만은
같은 판정(`novel_public_open_to`)을 직접 부른다 — 소장한 사람에게는 "잠시 쉬는 중"을 알려야 해서다.

**무엇을 읽을 수 있는가**는 `select_readable_publications` 한 곳이 정한다(공개 중 ∧ 운영 이용제한 없음 ∧ 게시자 탈퇴·정지
아님 ∧ 원작 이용제한·삭제 아님 ∧ 공개 화 하나 이상). 화면에 나가는 글은 공개 시점에 얼려 심사를 거친 사본뿐이다 — 화 제목·
작가의 말은 화 공개본 사본, 본문은 그 공개본이 가리키는 개정, 소설 제목·소개는 공개 상태 행 사본이고, 표지는 원작
썸네일이다(원작자가 탈퇴했으면 싣지 않는다 — 탈퇴한 회원의 작품 그림을 계속 내보이지 않는다).

**소장자 열람** — 정책 스위치(`novel_public_policy_v2_enabled`)가 켜져 있으면, 목록에서 빠진 노벨이어도 아직 환급되지 않은
구매를 가진 사람은 작품 정보·산 화·무료 화를 계속 읽고 읽은 자리를 저장한다(`select_owner_readable_publications` — 게시자의
거둠·정지, 원작자 정지로 인한 원작 일괄 제한, 판매된 소설 삭제). 그때 응답의 `salesStopped` 가 참이고, 사지 않은 유료 화는
살 수 없다(구매는 목록 조건을 본다). 산 사람은 산 때의 판을 골라 다시 읽는다(화 읽기의 쿼리 `edition`). 소장 목록
(`GET /webnovels/owned`)은 그런 노벨로 돌아가는 길이다 — 작품 정보가 여는 노벨 가운데 미환급 구매가 있는 것을 싣는다.

**열람 종료** — 읽을 수 없게 된 소설·화를 소장한 사람이 열면 410 `NOVEL_READING_ENDED` 와 이유(`reason`)를 준다. 소장하지
않은 사람에게는 이유 없이 404 다 — 게시자의 철회·운영 조치 사실을 제3자에게 알릴 까닭이 없다. 이유는 구매 행(소설·화가
지워져도 남는 사본, 환급 사유)과 지금 공개 상태로 가른다(`_ended_or_not_found`).

**조회 수**는 화 본문을 실제로 내준 때만, 소설 단위로 회원마다 하루 한 번 센다(Redis `SET NX`, 응답 뒤 백그라운드에서 상대
UPDATE — 작품 상세 조회와 같은 꼴)."""

import base64
import binascii
import json
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import Row, Select, delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from api.core import clover
from api.core.config import settings
from api.core.s3 import build_thumbnail_key, generate_presigned_get_url
from api.content.access import publicly_listed_conditions
from api.db.models.auth import User
from api.db.models.content import Content, ModerationStatus
from api.db.models.media import Asset
from api.db.models.novel import (
    HomeNovelCuration,
    Novel,
    NovelChapter,
    NovelChapterEdition,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelLike,
    NovelPublication,
    NovelPurchase,
    NovelPurchaseRefundReason,
    NovelReaderPosition,
)
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.novel_public.access import (
    novel_public_open_to,
    require_novel_public_readable,
    select_owner_readable_publications,
    select_readable_publications,
)
from api.novel_public.no_store import NoStoreRoute
from api.novel_public.purchases import chapter_price
from api.novel_public.schemas import (
    PublicNovelChapterAccess,
    PublicNovelChapterItem,
    PublicNovelChapterLink,
    PublicNovelChapterResponse,
    PublicNovelDetailResponse,
    PublicNovelEndedReason,
    PublicNovelHomeItem,
    PublicNovelHomeResponse,
    PublicNovelLastRead,
    PublicNovelListItem,
    PublicNovelListResponse,
    PublicNovelListSort,
    PublicNovelOwnedItem,
    PublicNovelOwnedListResponse,
    PublicNovelPurchasedEdition,
    PublicNovelReadingPosition,
    PublicNovelReadingPositionRequest,
    PublicNovelSource,
)
from api.novel_public.view_count import try_mark_novel_viewed
from api.novelize.router import _work_thumbnail_asset_ids
from api.novelize.text import split_paragraphs
from api.session.dependencies import get_current_user_id

PUBLIC_NOVEL_LIST_PAGE_SIZE = 20

reading_router = APIRouter(prefix="/webnovels", tags=["webnovels"], route_class=NoStoreRoute)

_source_creator = aliased(User)


def _error(status_code: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, **extra})


# ── 커서 ────────────────────────────────────────────────────────────────────
# `content/router.py` 의 `_encode_cursor`·`_decode_cursor` 와 같은 인코딩(base64 JSON 문자열 목록). 모듈마다 복제하는 것이
# 이 저장소의 관례다(`clover/router.py` 의 같은 복제).
def _encode_cursor(parts: list[str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(parts).encode()).decode()


def _decode_cursor(cursor: str, length: int) -> list[str]:
    """깨진 커서는 422 `INVALID_CURSOR` 다(손으로 고친 주소가 500 이 되지 않게)."""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        decoded = None
    if not isinstance(decoded, list) or len(decoded) != length or not all(isinstance(p, str) for p in decoded):
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_CURSOR")
    return decoded


# ── 공통 ────────────────────────────────────────────────────────────────────
def _title(publication: NovelPublication, novel: Novel) -> str:
    """공개본 제목. 비어 있으면 원작 제목이다(소유자 화면과 같은 규칙 — 둘 다 심사·발행을 거친 글이다)."""
    return publication.title if publication.title is not None else novel.content_title


async def _sources(db: AsyncSession, novels: Sequence[Novel]) -> dict[uuid.UUID, PublicNovelSource]:
    """소설마다 원작 표기. 표지는 원작의 지금 게시본 썸네일이고, 원작자 이름은 원작자의 지금 닉네임이다 — 원작자가
    탈퇴했으면 둘 다 싣지 않는다. 비공식 표시는 원작자가 게시자가 아닌가다. 한 페이지를 쿼리 넷(목록 조건·원작자·썸네일
    자산·자산 키)으로 읽는다. 서명은 네트워크 없이 로컬에서 한다(소유자 소설 목록의 표지와 같다)."""
    content_ids = {novel.content_id for novel in novels}
    if not content_ids:
        return {}
    listed = set(
        (await db.scalars(select(Content.id).where(Content.id.in_(content_ids), *publicly_listed_conditions()))).all()
    )
    # 원작 id → (원작자 id, 원작자 탈퇴 여부, 닉네임). 원작 행이 없으면 항목이 없다.
    creators: dict[uuid.UUID, tuple[uuid.UUID, bool, str | None]] = {
        content_id: (creator_id, deleted_at is not None, nickname)
        for content_id, creator_id, nickname, deleted_at in (
            await db.execute(
                select(Content.id, Content.creator_user_id, _source_creator.nickname, _source_creator.deleted_at)
                .join(_source_creator, _source_creator.id == Content.creator_user_id)
                .where(Content.id.in_(content_ids))
            )
        ).tuples()
    }
    creator_gone = {content_id for content_id, (_, gone, _) in creators.items() if gone}
    thumbnails = await _work_thumbnail_asset_ids(db, content_ids - creator_gone)
    storage_keys = (
        dict(
            (
                await db.execute(select(Asset.id, Asset.storage_key).where(Asset.id.in_(set(thumbnails.values()))))
            )
            .tuples()
            .all()
        )
        if thumbnails
        else {}
    )
    sources: dict[uuid.UUID, PublicNovelSource] = {}
    for novel in novels:
        asset_id = thumbnails.get(novel.content_id)
        key = storage_keys.get(asset_id) if asset_id is not None else None
        creator = creators.get(novel.content_id)
        sources[novel.id] = PublicNovelSource(
            content_id=novel.content_id,
            content_type=novel.content_type,
            title=novel.content_title,
            character_name=novel.character_name,
            cover_url=generate_presigned_get_url(build_thumbnail_key(key)) if key is not None else None,
            linkable=novel.content_id in listed,
            creator_nickname=creator[2] if creator is not None and not creator[1] else None,
            unofficial=creator is None or creator[0] != novel.user_id,
        )
    return sources


def _chapter_access(
    ordinal: int, stored_price: int, chapter_id: uuid.UUID, *, is_publisher: bool, owned: set[uuid.UUID]
) -> PublicNovelChapterAccess:
    """독자에게의 화 상태. 무료가 소장보다 먼저다 — 산 뒤 무료가 된 화는 "무료"로 보인다(산 때의 판 고르기는 구매 행으로
    따로 정한다)."""
    if is_publisher:
        return "publisher"
    if chapter_price(ordinal, stored_price) == 0:
        return "free"
    if chapter_id in owned:
        return "owned"
    return "locked"


def _price(ordinal: int, stored_price: int) -> int | None:
    """무료 화가 아니면 그 화의 가격."""
    price = chapter_price(ordinal, stored_price)
    return None if price == 0 else price


async def _owned_chapter_ids(db: AsyncSession, user_id: uuid.UUID, novel_id: uuid.UUID) -> set[uuid.UUID]:
    """이 사람이 이 소설에서 소장한 화(환급된 구매는 빼고 — 환급된 구매는 소장이 아니다)."""
    rows = await db.scalars(
        select(NovelPurchase.chapter_id).where(
            NovelPurchase.buyer_user_id == user_id,
            NovelPurchase.novel_id == novel_id,
            NovelPurchase.refunded_at.is_(None),
        )
    )
    return set(rows.all())


async def _keeps_reading(db: AsyncSession, user_id: uuid.UUID, novel_id: uuid.UUID) -> bool:
    """목록 조건으로 읽을 수 없는 노벨을 이 사람에게 소장자 조건으로 다시 볼 것인가 — 정책 스위치가 켜졌고 이 소설에 아직
    환급되지 않은 구매가 있다(모듈 docstring 의 소장자 열람)."""
    if not settings.novel_public_policy_v2_enabled:
        return False
    found = await db.scalar(
        select(NovelPurchase.id)
        .where(
            NovelPurchase.buyer_user_id == user_id,
            NovelPurchase.novel_id == novel_id,
            NovelPurchase.refunded_at.is_(None),
        )
        .limit(1)
    )
    return found is not None


def _position(row: NovelReaderPosition) -> PublicNovelReadingPosition:
    return PublicNovelReadingPosition(
        paragraph_index=row.paragraph_index,
        paragraph_count=row.paragraph_count,
        edition=row.edition,
        finished=row.finished_at is not None,
    )


# 환급 사유 → 열람 종료 이유. 410 의 이유 값을 늘리지 않고 기존 값에 대응시킨다 — 옛 화면의 이유별 안내가 그대로 맞는다.
# 사유가 비어 있는 환급은 이 칸이 생기기 전이나 옛 코드의 것이라 그때 유일했던 삭제 환급이다.
_ENDED_BY_REFUND: dict[NovelPurchaseRefundReason, PublicNovelEndedReason] = {
    "deleted": "deleted",
    "publisher_withdrawn": "publisher_withdrawn",
    "novel_restricted": "restricted",
    "source_restricted": "source_unavailable",
    "source_deleted": "source_unavailable",
}


async def _ended_or_not_found(
    db: AsyncSession, *, user_id: uuid.UUID, novel_id: uuid.UUID, chapter_id: uuid.UUID | None
) -> HTTPException:
    """읽을 수 없는 소설·화를 연 사람에게 줄 응답. 이 소설을 하나라도 소장한(했던) 사람에게만 410 `NOVEL_READING_ENDED` 와
    이유를, 아니면 404(`NOVEL_NOT_FOUND`, 화면 `NOVEL_CHAPTER_NOT_FOUND`)다. 이유는 앞의 것이 먼저다.

    1. 그 화의 구매가 모두 환급됐다(작품 정보면 소설이 없고 환급된 구매가 있다) — 가장 나중 환급의 사유로 가른다
       (`_ENDED_BY_REFUND`). 환급은 노벨을 다시 켜거나 다시 열어도 돌아오지 않으므로 스위치보다 먼저다.
    2. `service_off` — 노벨 스위치가 꺼져 있다(켜면 그대로 다시 열린다).
    3. 소설이 없다 — 게시자가 탈퇴했으면 `publisher_withdrawn`, 아니면 `deleted`(이미지를 옛 판으로 되돌린 동안의 삭제는
       환급하지 않아 이 길로 온다 — `refundedAmount` 0).
    4. `restricted`(운영 이용제한이나 게시자 정지) → `withdrawn`(게시자가 거둠) → `source_unavailable`(원작 이용제한·삭제).
    5. 소설은 읽을 수 있는데 그 화가 없다 — 환급된 구매가 있으면 그 사유(마지막 묶음을 지워 공개 화가 모두 사라지면
       `deleted`), 아니면 404.

    `refundedAmount` 는 돌려준 클로버다(화 읽기는 그 화 몫, 작품 정보는 소설 전체 몫). 환급이 있으면 이유와 무관하게 싣고,
    `deleted` 면 0 이어도 싣는다."""
    not_found = _error(
        status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND" if chapter_id is None else "NOVEL_CHAPTER_NOT_FOUND"
    )
    purchases = (
        await db.scalars(
            select(NovelPurchase).where(NovelPurchase.buyer_user_id == user_id, NovelPurchase.novel_id == novel_id)
        )
    ).all()
    if not purchases:
        return not_found
    scope = [p for p in purchases if chapter_id is None or p.chapter_id == chapter_id]
    refunded = [p for p in scope if p.refunded_at is not None]

    def ended(reason: PublicNovelEndedReason) -> HTTPException:
        extra: dict[str, object] = {}
        if refunded or reason == "deleted":
            extra["refundedAmount"] = sum(p.refunded_amount or 0 for p in refunded)
        return _error(status.HTTP_410_GONE, "NOVEL_READING_ENDED", reason=reason, **extra)

    def ended_by_refund() -> HTTPException:
        latest = max(refunded, key=lambda p: p.refunded_at or datetime.min.replace(tzinfo=UTC))
        return ended(_ENDED_BY_REFUND[latest.refund_reason or "deleted"])

    novel = await db.get(Novel, novel_id)
    # 다시 연 화를 다시 샀으면 환급되지 않은 구매가 있어 환급 사유가 아니라 지금 상태로 가른다.
    if chapter_id is not None and refunded and len(refunded) == len(scope):
        return ended_by_refund()
    if chapter_id is None and novel is None and refunded:
        return ended_by_refund()
    if not novel_public_open_to(user_id):
        return ended("service_off")
    if novel is None:
        publisher = await db.get(User, purchases[0].publisher_user_id)
        return ended("publisher_withdrawn" if publisher is not None and publisher.deleted_at is not None else "deleted")
    publication = await db.get(NovelPublication, novel_id)
    publisher = await db.get(User, novel.user_id)
    source = await db.get(Content, novel.content_id)
    if publication is None:
        return not_found
    if publication.moderation_status == "restricted" or (publisher is not None and publisher.suspended_at is not None):
        return ended("restricted")
    if publication.visibility == "withdrawn":
        return ended("withdrawn")
    if source is None or source.moderation_status != ModerationStatus.NORMAL:
        return ended("source_unavailable")
    return ended_by_refund() if refunded else not_found


async def _count_view(
    session_factory: async_sessionmaker[AsyncSession], novel_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """응답 뒤 백그라운드: 하루 한 번 거르기를 통과하면 조회 수를 DB 가 원자적으로 하나 올린다. 자기 세션을 연다 — 작품 상세
    조회의 `_count_view` 와 같은 이유(요청 세션의 읽기 트랜잭션에 쓰기를 얹지 않는다). 소설이 그사이 지워졌으면 0행이다."""
    if not await try_mark_novel_viewed(novel_id, user_id):
        return
    async with session_factory() as session:
        await session.execute(
            update(NovelPublication)
            .where(NovelPublication.novel_id == novel_id)
            .values(view_count=NovelPublication.view_count + 1)
        )
        await session.commit()


# ── 홈 노벨 ─────────────────────────────────────────────────────────────────
# `/{novel_id}` 보다 먼저 둔다 — 뒤에 두면 그 경로의 uuid 칸이 먼저 잡아 422 가 된다.
@reading_router.get("/home-curation", dependencies=[Depends(require_novel_public_readable)])
async def get_home_novels(
    _user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PublicNovelHomeResponse:
    """홈 노벨 섹션 — 운영자가 고른 노벨 가운데 지금 읽을 수 있는 것을 자리 순으로. 고른 노벨이 거둬지거나 이용제한되면
    지정은 남은 채 여기서 빠지고, 다시 읽을 수 있게 되면 돌아온다."""
    rows = (
        await db.execute(
            select_readable_publications(NovelPublication, Novel)
            .join(HomeNovelCuration, HomeNovelCuration.novel_id == NovelPublication.novel_id)
            .order_by(HomeNovelCuration.position)
        )
    ).all()
    sources = await _sources(db, [novel for _, novel in rows])
    return PublicNovelHomeResponse(
        items=[
            PublicNovelHomeItem(id=novel.id, title=_title(publication, novel), source=sources[novel.id])
            for publication, novel in rows
        ]
    )


# ── 목록 ────────────────────────────────────────────────────────────────────
def _chapter_count() -> Any:
    """공개 화 수 — 목록 쿼리의 열로 쓰는 상관 하위 쿼리."""
    return (
        select(func.count())
        .where(NovelChapterPublication.novel_id == NovelPublication.novel_id)
        .correlate(NovelPublication)
        .scalar_subquery()
    )


def _decode_latest_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    published_at, last_id = _decode_cursor(cursor, 2)
    try:
        return datetime.fromisoformat(published_at), uuid.UUID(last_id)
    except ValueError:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_CURSOR") from None


@reading_router.get("", dependencies=[Depends(require_novel_public_readable)])
async def list_webnovels(
    sort: PublicNovelListSort = "latest",
    cursor: str | None = None,
    _user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PublicNovelListResponse:
    """노벨 목록, 한 번에 20편. `latest` 는 공개 화면 글이 마지막으로 바뀐 시각 순, `popular` 는 좋아요 수 순(같으면 최신순).
    다음 페이지는 `nextCursor` 를 그대로 `cursor` 로 넘긴다."""
    query = select_readable_publications(NovelPublication, Novel, User.nickname, _chapter_count())
    if sort == "popular":
        query = query.order_by(
            NovelPublication.like_count.desc(), NovelPublication.published_at.desc(), NovelPublication.novel_id.desc()
        )
        if cursor is not None:
            like_count, published_at, last_id = _decode_cursor(cursor, 3)
            try:
                key = (int(like_count), datetime.fromisoformat(published_at), uuid.UUID(last_id))
            except ValueError:
                raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_CURSOR") from None
            query = query.where(
                tuple_(NovelPublication.like_count, NovelPublication.published_at, NovelPublication.novel_id) < key
            )
    else:
        query = query.order_by(NovelPublication.published_at.desc(), NovelPublication.novel_id.desc())
        if cursor is not None:
            query = query.where(
                tuple_(NovelPublication.published_at, NovelPublication.novel_id) < _decode_latest_cursor(cursor)
            )

    rows = (await db.execute(query.limit(PUBLIC_NOVEL_LIST_PAGE_SIZE + 1))).all()
    page = rows[:PUBLIC_NOVEL_LIST_PAGE_SIZE]
    sources = await _sources(db, [novel for _, novel, _, _ in page])
    items = [
        PublicNovelListItem(
            id=novel.id,
            title=_title(publication, novel),
            synopsis=publication.synopsis,
            source=sources[novel.id],
            publisher_nickname=nickname,
            chapter_count=count,
            like_count=publication.like_count,
            view_count=publication.view_count,
            published_at=publication.published_at,
        )
        for publication, novel, nickname, count in page
    ]
    next_cursor: str | None = None
    if len(rows) > PUBLIC_NOVEL_LIST_PAGE_SIZE and page:
        last: NovelPublication = page[-1][0]
        parts = [last.published_at.isoformat(), str(last.novel_id)]
        next_cursor = _encode_cursor([str(last.like_count), *parts] if sort == "popular" else parts)
    return PublicNovelListResponse(items=items, next_cursor=next_cursor)


# ── 소장 목록 ───────────────────────────────────────────────────────────────
# `/{novel_id}` 보다 먼저 둔다(홈 노벨과 같은 이유).
@reading_router.get("/owned", dependencies=[Depends(require_novel_public_readable)])
async def list_owned_webnovels(
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PublicNovelOwnedListResponse:
    """내가 소장한 노벨 — 아직 환급되지 않은 구매가 하나라도 있고 지금 작품 정보가 열리는 노벨을, 노벨 목록의 최신순과 같은
    순서·커서로 20편씩. 판단은 작품 정보와 같다: 목록 조건으로 읽히면 판매 중이고, 정책 스위치가 켜졌을 때 소장자 조건으로만
    읽히면 `salesStopped` 가 참이다(모듈 docstring 의 소장자 열람). 스위치가 꺼져 있으면 소장자 열람이 없어 판매 중인 노벨만
    싣는다 — 누르면 410 인 노벨을 "소장"으로 보이지 않는다. 환급으로 닫힌 노벨은 미환급 구매가 없어 빠진다."""
    policy_v2 = settings.novel_public_policy_v2_enabled
    select_publications = select_owner_readable_publications if policy_v2 else select_readable_publications
    owns = (
        select(NovelPurchase.id)
        .where(
            NovelPurchase.novel_id == NovelPublication.novel_id,
            NovelPurchase.buyer_user_id == user_id,
            NovelPurchase.refunded_at.is_(None),
        )
        .exists()
    )
    query = (
        select_publications(NovelPublication, Novel, User.nickname, _chapter_count())
        .where(owns)
        .order_by(NovelPublication.published_at.desc(), NovelPublication.novel_id.desc())
    )
    if cursor is not None:
        query = query.where(
            tuple_(NovelPublication.published_at, NovelPublication.novel_id) < _decode_latest_cursor(cursor)
        )
    rows = (await db.execute(query.limit(PUBLIC_NOVEL_LIST_PAGE_SIZE + 1))).all()
    page = rows[:PUBLIC_NOVEL_LIST_PAGE_SIZE]
    page_ids = [novel.id for _, novel, _, _ in page]
    on_sale = (
        set(
            (
                await db.scalars(
                    select_readable_publications(NovelPublication.novel_id).where(
                        NovelPublication.novel_id.in_(page_ids)
                    )
                )
            ).all()
        )
        if policy_v2 and page_ids
        else set(page_ids)
    )
    sources = await _sources(db, [novel for _, novel, _, _ in page])
    items = [
        PublicNovelOwnedItem(
            id=novel.id,
            title=_title(publication, novel),
            synopsis=publication.synopsis,
            source=sources[novel.id],
            publisher_nickname=nickname,
            chapter_count=count,
            like_count=publication.like_count,
            view_count=publication.view_count,
            published_at=publication.published_at,
            sales_stopped=novel.id not in on_sale,
        )
        for publication, novel, nickname, count in page
    ]
    next_cursor: str | None = None
    if len(rows) > PUBLIC_NOVEL_LIST_PAGE_SIZE and page:
        last: NovelPublication = page[-1][0]
        next_cursor = _encode_cursor([last.published_at.isoformat(), str(last.novel_id)])
    return PublicNovelOwnedListResponse(items=items, next_cursor=next_cursor)


# ── 작품 정보 ───────────────────────────────────────────────────────────────
@reading_router.get("/{novel_id}")
async def get_webnovel(
    novel_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PublicNovelDetailResponse:
    """노벨 작품 정보와 목차. 읽을 수 없으면 소장했던 사람에게 410 `NOVEL_READING_ENDED`, 아니면 404 `NOVEL_NOT_FOUND`
    (모듈 docstring). 목차의 화마다 독자에게의 상태(`access`)와 가격, 그 화를 읽던 자리를 싣는다. 목록에서 빠진 노벨을
    소장자가 열면 `salesStopped` 가 참이다(모듈 docstring 의 소장자 열람)."""
    open_to_viewer = novel_public_open_to(user_id)

    async def find(select_publications: Callable[..., Select[Any]]) -> Row[Any] | None:
        return (
            await db.execute(
                select_publications(NovelPublication, Novel, User.nickname).where(
                    NovelPublication.novel_id == novel_id
                )
            )
        ).one_or_none()

    row = await find(select_readable_publications)
    sales_stopped = False
    if row is None and open_to_viewer and await _keeps_reading(db, user_id, novel_id):
        row = await find(select_owner_readable_publications)
        sales_stopped = row is not None
    if row is None or not open_to_viewer:
        raise await _ended_or_not_found(db, user_id=user_id, novel_id=novel_id, chapter_id=None)
    publication, novel, nickname = row
    is_publisher = novel.user_id == user_id
    owned = await _owned_chapter_ids(db, user_id, novel_id)
    chapter_rows = (
        await db.execute(
            select(
                NovelChapterPublication.chapter_id,
                NovelChapterPublication.ordinal,
                NovelChapterPublication.title,
                NovelChapterPublication.price,
            )
            .where(NovelChapterPublication.novel_id == novel_id)
            .order_by(NovelChapterPublication.ordinal)
        )
    ).all()
    positions = {
        position.chapter_id: position
        for position in (
            await db.scalars(
                select(NovelReaderPosition).where(
                    NovelReaderPosition.user_id == user_id, NovelReaderPosition.novel_id == novel_id
                )
            )
        ).all()
    }
    chapters = [
        PublicNovelChapterItem(
            id=chapter_id,
            ordinal=ordinal,
            title=title,
            access=_chapter_access(ordinal, price, chapter_id, is_publisher=is_publisher, owned=owned),
            price=_price(ordinal, price),
            reading_position=_position(positions[chapter_id]) if chapter_id in positions else None,
        )
        for chapter_id, ordinal, title, price in chapter_rows
    ]
    ordinals = {chapter_id: ordinal for chapter_id, ordinal, _, _ in chapter_rows}
    last_read: PublicNovelLastRead | None = None
    recent = max(
        (p for p in positions.values() if p.chapter_id in ordinals), key=lambda p: p.updated_at, default=None
    )
    if recent is not None:
        last_read = PublicNovelLastRead(
            chapter_id=recent.chapter_id,
            ordinal=ordinals[recent.chapter_id],
            paragraph_index=recent.paragraph_index,
            paragraph_count=recent.paragraph_count,
            edition=recent.edition,
            updated_at=recent.updated_at,
        )
    liked = await db.scalar(
        select(NovelLike.novel_id).where(NovelLike.user_id == user_id, NovelLike.novel_id == novel_id)
    )
    return PublicNovelDetailResponse(
        id=novel.id,
        title=_title(publication, novel),
        synopsis=publication.synopsis,
        source=(await _sources(db, [novel]))[novel.id],
        publisher_user_id=novel.user_id,
        publisher_nickname=nickname,
        is_publisher=is_publisher,
        chapters=chapters,
        free_chapter_count=clover.NOVEL_FREE_CHAPTER_COUNT,
        chapter_price=clover.NOVEL_READ_COST,
        like_count=publication.like_count,
        liked=liked is not None,
        view_count=publication.view_count,
        last_read=last_read,
        first_published_at=publication.first_published_at,
        published_at=publication.published_at,
        sales_stopped=sales_stopped,
    )


# ── 화 읽기 ─────────────────────────────────────────────────────────────────
async def _purchased_edition(
    db: AsyncSession, *, user_id: uuid.UUID, chapter_id: uuid.UUID
) -> NovelChapterEdition | None:
    """이 사람이 그 화를 산 때의 판 행 — 아직 환급되지 않은 구매의 판 번호로 고른다. 그 판 행이 없으면(판 이력이 생기기 전의
    판을 샀다) 그 화의 가장 오래된 판 행으로 대신하고, 판 행이 하나도 없으면 None."""
    bought = await db.scalar(
        select(NovelPurchase.edition).where(
            NovelPurchase.buyer_user_id == user_id,
            NovelPurchase.chapter_id == chapter_id,
            NovelPurchase.refunded_at.is_(None),
        )
    )
    if bought is None:
        return None
    exact = await db.get(NovelChapterEdition, (chapter_id, bought))
    if exact is not None:
        return exact
    oldest: NovelChapterEdition | None = await db.scalar(
        select(NovelChapterEdition)
        .where(NovelChapterEdition.chapter_id == chapter_id)
        .order_by(NovelChapterEdition.edition)
        .limit(1)
    )
    return oldest


@reading_router.get("/{novel_id}/chapters/{chapter_id}")
async def get_webnovel_chapter(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    edition: int | None = Query(None, ge=1, le=2_147_483_647),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> PublicNovelChapterResponse:
    """노벨 화 하나. 무료 화·소장한 화·게시자 본인이면 공개본 본문을 문단 배열로 싣고, 게시자 본인이 아니면 조회 수를 센다
    (자기 글을 다시 열어 본 것은 독자의 조회가 아니다). 아니면 본문 없이
    `access: locked` 와 가격만 싣는다(소장 화면용). 읽을 수 없으면 소장했던 사람에게 410 `NOVEL_READING_ENDED`, 아니면 404
    `NOVEL_CHAPTER_NOT_FOUND`(모듈 docstring).

    `edition` 은 고를 판이다(정책 스위치가 켜졌을 때). 지금 판이거나, 그 화를 산 사람의 산 때의 판(`purchasedEdition`)만
    고를 수 있고 그 밖의 값은 404 `NOVEL_CHAPTER_NOT_FOUND` 다 — 사지 않은 사람·무료 화·게시자 본인은 지금 판만 읽는다.
    스위치가 꺼져 있으면 이 값을 보지 않고 지금 판을 준다."""
    open_to_viewer = novel_public_open_to(user_id)

    async def find(select_publications: Callable[..., Select[Any]]) -> Row[Any] | None:
        return (
            await db.execute(
                select_publications(NovelPublication, Novel, NovelChapterPublication, NovelChapterRevision.body)
                .join(NovelChapterPublication, NovelChapterPublication.novel_id == NovelPublication.novel_id)
                .join(NovelChapterRevision, NovelChapterRevision.id == NovelChapterPublication.revision_id)
                .where(NovelPublication.novel_id == novel_id, NovelChapterPublication.chapter_id == chapter_id)
            )
        ).one_or_none()

    row = await find(select_readable_publications)
    sales_stopped = False
    if row is None and open_to_viewer and await _keeps_reading(db, user_id, novel_id):
        row = await find(select_owner_readable_publications)
        sales_stopped = row is not None
    if row is None or not open_to_viewer:
        raise await _ended_or_not_found(db, user_id=user_id, novel_id=novel_id, chapter_id=chapter_id)
    publication, novel, chapter, body = row
    is_publisher = novel.user_id == user_id
    owned = await _owned_chapter_ids(db, user_id, novel_id)
    access = _chapter_access(chapter.ordinal, chapter.price, chapter_id, is_publisher=is_publisher, owned=owned)

    policy_v2 = settings.novel_public_policy_v2_enabled
    # 산 때의 판은 소장 표시가 아니라 미환급 구매로 고른다 — 산 뒤 무료가 된 화는 "무료"로 보이지만 산 사람은 산 글을 계속
    # 고른다. 게시자 본인은 지금 판만 읽는다.
    bought = (
        await _purchased_edition(db, user_id=user_id, chapter_id=chapter_id)
        if policy_v2 and not is_publisher and chapter_id in owned
        else None
    )
    if bought is not None and bought.edition == chapter.edition:
        bought = None  # 산 때의 판이 지금 판이면 고를 것이 없다
    served_edition, title, author_note = chapter.edition, chapter.title, chapter.author_note
    if policy_v2 and edition is not None and edition != chapter.edition:
        if bought is None or edition != bought.edition:
            raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
        old_revision = await db.get_one(NovelChapterRevision, bought.revision_id)
        served_edition, title, author_note, body = bought.edition, bought.title, bought.author_note, old_revision.body

    neighbours = {
        ordinal: (neighbour_id, price)
        for neighbour_id, ordinal, price in (
            await db.execute(
                select(
                    NovelChapterPublication.chapter_id, NovelChapterPublication.ordinal, NovelChapterPublication.price
                ).where(
                    NovelChapterPublication.novel_id == novel_id,
                    NovelChapterPublication.ordinal.in_((chapter.ordinal - 1, chapter.ordinal + 1)),
                )
            )
        ).tuples()
    }

    def link(ordinal: int) -> PublicNovelChapterLink | None:
        neighbour = neighbours.get(ordinal)
        if neighbour is None:
            return None
        neighbour_id, price = neighbour
        return PublicNovelChapterLink(
            id=neighbour_id,
            ordinal=ordinal,
            access=_chapter_access(ordinal, price, neighbour_id, is_publisher=is_publisher, owned=owned),
        )

    position = await db.get(NovelReaderPosition, (user_id, chapter_id))
    readable = access != "locked"
    if readable and not is_publisher:
        background_tasks.add_task(_count_view, session_factory, novel_id, user_id)
    return PublicNovelChapterResponse(
        novel_id=novel_id,
        novel_title=_title(publication, novel),
        id=chapter_id,
        ordinal=chapter.ordinal,
        title=title,
        access=access,
        price=_price(chapter.ordinal, chapter.price),
        edition=served_edition,
        paragraphs=split_paragraphs(body) if readable else None,
        author_note=author_note if readable else None,
        previous_chapter=link(chapter.ordinal - 1),
        next_chapter=link(chapter.ordinal + 1),
        reading_position=_position(position) if position is not None else None,
        purchased_edition=(
            PublicNovelPurchasedEdition(edition=bought.edition, published_at=bought.published_at)
            if bought is not None
            else None
        ),
        sales_stopped=sales_stopped,
    )


# ── 읽은 자리 ───────────────────────────────────────────────────────────────
@reading_router.put(
    "/{novel_id}/chapters/{chapter_id}/reading-position",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_novel_public_readable), Depends(require_legal_consent)],
)
async def save_webnovel_reading_position(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    payload: PublicNovelReadingPositionRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """노벨 화를 읽던 자리를 저장한다(소유자 읽은 자리와 같은 계약 — 문단 번호, 같은 값을 다시 보내도 같고, 다 읽은 화는
    다 읽은 화로 남는다). 문단 번호가 문단 수 밖이면 422 `NOVEL_PARAGRAPH_RANGE_INVALID`, 지금 읽을 수 없는 화(없음·숨김)는
    404 `NOVEL_CHAPTER_NOT_FOUND`, 소장하지 않은 유료 화는 403 `NOVEL_CHAPTER_LOCKED` 다. 소장자는 목록에서 빠진 노벨에서도
    저장한다(모듈 docstring 의 소장자 열람).

    화 행을 키 공유 잠금으로 확인한 뒤 저장한다 — 소유자 읽은 자리와 같은 이유다. 묶음·소설 삭제는 화를 `FOR UPDATE` 로
    잠근 뒤 읽은 자리를 지우므로, 이쪽이 먼저 잡으면 삭제가 이 저장을 기다렸다가 함께 지우고, 삭제가 먼저면 이 확인이
    기다렸다가 화가 없음을 보고 404 다."""
    if payload.paragraph_index >= payload.paragraph_count:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_PARAGRAPH_RANGE_INVALID")
    locked = await db.scalar(
        select(NovelChapter.id)
        .where(NovelChapter.id == chapter_id, NovelChapter.novel_id == novel_id)
        .with_for_update(key_share=True, read=True)
    )

    async def find(select_publications: Callable[..., Select[Any]]) -> Row[Any] | None:
        return (
            await db.execute(
                select_publications(Novel.user_id, NovelChapterPublication.ordinal, NovelChapterPublication.price)
                .join(NovelChapterPublication, NovelChapterPublication.novel_id == NovelPublication.novel_id)
                .where(NovelPublication.novel_id == novel_id, NovelChapterPublication.chapter_id == chapter_id)
            )
        ).one_or_none()

    row = await find(select_readable_publications) if locked is not None else None
    if row is None and locked is not None and await _keeps_reading(db, user_id, novel_id):
        row = await find(select_owner_readable_publications)
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    publisher_id, ordinal, price = row
    owned = await _owned_chapter_ids(db, user_id, novel_id)
    if _chapter_access(ordinal, price, chapter_id, is_publisher=publisher_id == user_id, owned=owned) == "locked":
        raise _error(status.HTTP_403_FORBIDDEN, "NOVEL_CHAPTER_LOCKED")
    stmt = insert(NovelReaderPosition).values(
        user_id=user_id,
        chapter_id=chapter_id,
        novel_id=novel_id,
        paragraph_index=payload.paragraph_index,
        paragraph_count=payload.paragraph_count,
        edition=payload.edition,
        finished_at=func.now() if payload.finished else None,
        updated_at=func.now(),
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[NovelReaderPosition.user_id, NovelReaderPosition.chapter_id],
            set_={
                "paragraph_index": stmt.excluded.paragraph_index,
                "paragraph_count": stmt.excluded.paragraph_count,
                "edition": stmt.excluded.edition,
                # 한 번 찍힌 다 읽은 시각은 되돌리지 않는다.
                "finished_at": func.coalesce(NovelReaderPosition.finished_at, stmt.excluded.finished_at),
                "updated_at": func.now(),
            },
        )
    )
    await db.commit()


# ── 좋아요 ──────────────────────────────────────────────────────────────────
@reading_router.post(
    "/{novel_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_novel_public_readable)],
)
async def like_webnovel(
    novel_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """좋아요. 이미 했으면 아무것도 바뀌지 않는다(화면이 낙관적으로 그리고 응답 본문을 읽지 않아 204). 지금 읽을 수 없는
    노벨은 404 `NOVEL_NOT_FOUND`.

    행을 넣은 요청만 수를 올린다 — 같은 사람의 좋아요 둘이 겹치면 뒤의 INSERT 가 앞의 것의 커밋을 기다렸다가 충돌로 아무것도
    넣지 않으므로 수가 한 번만 오른다. 수는 상대 UPDATE 라 다른 사람의 좋아요와 겹쳐도 빠지지 않는다."""
    readable = await db.scalar(
        select_readable_publications(NovelPublication.novel_id).where(NovelPublication.novel_id == novel_id)
    )
    if readable is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND")
    inserted = await db.scalar(
        insert(NovelLike)
        .values(user_id=user_id, novel_id=novel_id)
        .on_conflict_do_nothing(index_elements=[NovelLike.user_id, NovelLike.novel_id])
        .returning(NovelLike.novel_id)
    )
    if inserted is not None:
        await db.execute(
            update(NovelPublication)
            .where(NovelPublication.novel_id == novel_id)
            .values(like_count=NovelPublication.like_count + 1)
        )
    await db.commit()


@reading_router.delete(
    "/{novel_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_novel_public_readable)],
)
async def unlike_webnovel(
    novel_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """좋아요 취소. 안 했으면 아무것도 바뀌지 않는다. 노벨 스위치가 꺼져 있으면 다른 독자 라우트처럼 404
    `NOVEL_PUBLIC_DISABLED` 다(꺼진 동안 화면이 노벨 탭을 숨긴다). 스위치가 켜져 있으면 지금 읽을 수 없는 노벨이어도 취소는
    된다 — 내 표시를 거두는 일이라 노벨의 상태와 무관하다. 행을 지운 요청만 수를 내린다(좋아요와 같은 이유)."""
    removed = await db.scalar(
        delete(NovelLike)
        .where(NovelLike.user_id == user_id, NovelLike.novel_id == novel_id)
        .returning(NovelLike.novel_id)
    )
    if removed is not None:
        await db.execute(
            update(NovelPublication)
            .where(NovelPublication.novel_id == novel_id)
            .values(like_count=NovelPublication.like_count - 1)
        )
    await db.commit()
