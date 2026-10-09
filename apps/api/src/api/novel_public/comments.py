"""노벨 화 댓글 — 목록·쓰기·지우기.

댓글은 화마다 최신순으로 쌓이는 글뿐이다(답글·멘션·좋아요 없음). **보기와 쓰기 권한이 곧 그 화의 열람 권한이다** — 지금
독자가 읽을 수 있는 노벨(`select_readable_publications`)의 공개 화이고, 무료 화이거나 소장했거나 게시자 본인이어야 한다.
소장하지 않은 유료 화의 댓글은 본문의 줄거리를 흘릴 수 있어 보기도 막는다. 노벨 스위치가 꺼져 있으면 404
`NOVEL_PUBLIC_DISABLED` 다.

**지우기**는 작성자 본인과 그 노벨의 게시자만 한다. 행은 남기고 본문을 비운다(신고 행이 댓글을 계속 가리키게) — 지운 댓글과
운영자가 숨긴 댓글은 목록·수에서 빠진다. 자기 글을 거두는 일이라 노벨의 지금 상태와 스위치를 따지지 않는다.

**잠금** — 쓰기는 작성자 행 → 화 행(키 공유) 순서로 잡는다. 소설·묶음 삭제는 사용자 행 → 화 행(`FOR UPDATE`) → 댓글 DELETE
순서라, 이쪽이 화를 먼저 쥐면 삭제가 기다렸다가 새 댓글까지 지우고, 삭제가 먼저면 화가 없음을 보고 404 다(독자 읽은 자리
저장과 같은 이유)."""

import uuid
from datetime import UTC, datetime

import regex
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import lock_active_user
from api.core.rate_limit import check_rate_limit
from api.db.models.auth import User
from api.db.models.novel import Novel, NovelChapter, NovelChapterPublication, NovelComment, NovelPublication
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.novel_public.access import require_novel_public_readable, select_readable_publications
from api.novel_public.no_store import NoStoreRoute
from api.novel_public.reading import _chapter_access, _decode_cursor, _encode_cursor, _owned_chapter_ids
from api.novel_public.schemas import (
    PublicNovelCommentCreateRequest,
    PublicNovelCommentItem,
    PublicNovelCommentListResponse,
)
from api.session.dependencies import get_current_user_id

NOVEL_COMMENT_PAGE_SIZE = 20
# 화면에 보이는 글자(자소 묶음) 기준 — 작품 댓글과 같은 상한이다.
NOVEL_COMMENT_MAX_CHARS = 1000

comments_router = APIRouter(prefix="/webnovels", tags=["webnovels"], route_class=NoStoreRoute)


def _error(status_code: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, **extra})


async def require_chapter_reader(
    db: AsyncSession, *, novel_id: uuid.UUID, chapter_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID:
    """이 사람이 지금 이 노벨 화를 볼 수 있으면 게시자 id 를 돌려준다. 지금 읽을 수 있는 공개 화가 아니면 404
    `NOVEL_CHAPTER_NOT_FOUND`(이유를 가르지 않는다), 소장하지 않은 유료 화면 403 `NOVEL_CHAPTER_LOCKED` 다 — 화 읽기·읽은
    자리 저장과 같은 판정이다."""
    row = (
        await db.execute(
            select_readable_publications(Novel.user_id, NovelChapterPublication.ordinal)
            .join(NovelChapterPublication, NovelChapterPublication.novel_id == NovelPublication.novel_id)
            .where(NovelPublication.novel_id == novel_id, NovelChapterPublication.chapter_id == chapter_id)
        )
    ).one_or_none()
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    publisher_id: uuid.UUID = row[0]
    ordinal: int = row[1]
    owned = await _owned_chapter_ids(db, user_id, novel_id)
    if _chapter_access(ordinal, chapter_id, is_publisher=publisher_id == user_id, owned=owned) == "locked":
        raise _error(status.HTTP_403_FORBIDDEN, "NOVEL_CHAPTER_LOCKED")
    return publisher_id


def _item(
    comment: NovelComment, nickname: str | None, *, viewer_id: uuid.UUID, publisher_id: uuid.UUID
) -> PublicNovelCommentItem:
    assert comment.body is not None  # 지운 댓글은 목록에 오지 않는다(본문이 비는 것은 지울 때뿐 — CHECK).
    is_mine = comment.author_user_id == viewer_id
    return PublicNovelCommentItem(
        id=comment.id,
        author_nickname=nickname,
        is_publisher=comment.author_user_id == publisher_id,
        is_mine=is_mine,
        can_delete=is_mine or viewer_id == publisher_id,
        can_report=not is_mine,
        body=comment.body,
        created_at=comment.created_at,
    )


@comments_router.get(
    "/{novel_id}/chapters/{chapter_id}/comments", dependencies=[Depends(require_novel_public_readable)]
)
async def list_webnovel_comments(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PublicNovelCommentListResponse:
    """화 댓글 최신순 20개씩. 다음 페이지는 `nextCursor` 를 그대로 `cursor` 로 넘긴다."""
    publisher_id = await require_chapter_reader(db, novel_id=novel_id, chapter_id=chapter_id, user_id=user_id)
    visible = (
        NovelComment.chapter_id == chapter_id,
        NovelComment.deleted_at.is_(None),
        NovelComment.moderator_hidden.is_(False),
    )
    query = (
        select(NovelComment, User.nickname)
        .join(User, User.id == NovelComment.author_user_id)
        .where(*visible)
        .order_by(NovelComment.created_at.desc(), NovelComment.id.desc())
    )
    if cursor is not None:
        created_at, last_id = _decode_cursor(cursor, 2)
        try:
            key = (datetime.fromisoformat(created_at), uuid.UUID(last_id))
        except ValueError:
            raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_CURSOR") from None
        query = query.where(tuple_(NovelComment.created_at, NovelComment.id) < key)
    rows = (await db.execute(query.limit(NOVEL_COMMENT_PAGE_SIZE + 1))).tuples().all()
    page = rows[:NOVEL_COMMENT_PAGE_SIZE]
    total = await db.scalar(select(func.count()).select_from(NovelComment).where(*visible))
    next_cursor: str | None = None
    if len(rows) > NOVEL_COMMENT_PAGE_SIZE and page:
        last = page[-1][0]
        next_cursor = _encode_cursor([last.created_at.isoformat(), str(last.id)])
    return PublicNovelCommentListResponse(
        items=[_item(comment, nickname, viewer_id=user_id, publisher_id=publisher_id) for comment, nickname in page],
        next_cursor=next_cursor,
        total_count=total or 0,
    )


@comments_router.post(
    "/{novel_id}/chapters/{chapter_id}/comments",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_novel_public_readable), Depends(require_legal_consent)],
)
async def create_webnovel_comment(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    payload: PublicNovelCommentCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PublicNovelCommentItem:
    """화 댓글 쓰기. 빈 글은 422 `NOVEL_COMMENT_EMPTY`, 1,000자 초과는 422 `NOVEL_COMMENT_TOO_LONG`, 분당 5개를 넘으면 429
    `NOVEL_COMMENT_RATE_LIMITED`, 볼 수 없는 화는 404/403(`require_chapter_reader`). 정지된 회원은 403 이다(작성자 행을 잠근
    뒤 DB 의 정지 표식으로 다시 확인한다)."""
    # DB 조회보다 먼저 센다 — 볼 수 없는 화를 두드리는 요청도 같은 한도를 쓴다.
    retry_after = await check_rate_limit("novel-comment-create", str(user_id), 5, window_seconds=60)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "NOVEL_COMMENT_RATE_LIMITED",
                "message": "잠시 후 다시 작성해 주세요.",
                "retryAfterSeconds": retry_after,
                "windowSeconds": 60,
            },
            headers={"Retry-After": str(retry_after)},
        )
    if not payload.body.strip():
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_COMMENT_EMPTY")
    for index, _ in enumerate(regex.finditer(r"\X", payload.body), start=1):
        if index > NOVEL_COMMENT_MAX_CHARS:
            raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_COMMENT_TOO_LONG")

    author = await lock_active_user(db, user_id)
    await db.execute(
        select(NovelChapter.id)
        .where(NovelChapter.id == chapter_id, NovelChapter.novel_id == novel_id)
        .with_for_update(key_share=True, read=True)
    )
    publisher_id = await require_chapter_reader(db, novel_id=novel_id, chapter_id=chapter_id, user_id=user_id)
    comment = NovelComment(novel_id=novel_id, chapter_id=chapter_id, author_user_id=user_id, body=payload.body)
    db.add(comment)
    await db.flush()
    await db.commit()
    return _item(comment, author.nickname, viewer_id=user_id, publisher_id=publisher_id)


@comments_router.delete("/{novel_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webnovel_comment(
    novel_id: uuid.UUID,
    comment_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """작성자 본인이나 그 노벨의 게시자가 댓글을 지운다. 없거나 이미 지운 댓글은 404 `NOVEL_COMMENT_NOT_FOUND`, 둘 다
    아니면 403 `NOVEL_COMMENT_DELETE_FORBIDDEN` 이다. 본문을 비우고 지운 사람·시각을 적는다(모듈 docstring)."""
    comment = await db.scalar(
        select(NovelComment)
        .where(NovelComment.id == comment_id, NovelComment.novel_id == novel_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if comment is None or comment.deleted_at is not None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_COMMENT_NOT_FOUND")
    publisher_id = await db.scalar(select(Novel.user_id).where(Novel.id == novel_id))
    if comment.author_user_id == user_id:
        comment.deleted_by = "author"
    elif publisher_id == user_id:
        comment.deleted_by = "publisher"
    else:
        raise _error(status.HTTP_403_FORBIDDEN, "NOVEL_COMMENT_DELETE_FORBIDDEN")
    comment.body = None
    comment.deleted_at = datetime.now(UTC)
    await db.commit()
