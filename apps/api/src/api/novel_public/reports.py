"""노벨 신고 — 소설 전체·공개 화 하나·화 댓글 하나를 회원이 신고한다.

작품 댓글·채팅 응답 신고와 같은 모양이다. 접수 때 신고 시점의 공개본(소설 제목·소개, 화 신고면 화 제목과 본문 앞부분)이나
댓글 본문을 증거로 복사해 두고, 90일이 지나면 어드민 조회에서 숨기고 파기 작업이 비운다. 소설·화·댓글이 지워져도 신고와
증거는 보유 기간 동안 남는다(신고 표의 대상 칸이 `SET NULL`).

신고할 수 있는 것은 지금 그 사람이 볼 수 있는 것뿐이다 — 노벨·화 신고는 지금 독자가 읽을 수 있는 노벨(남이 게시한 것), 댓글
신고는 그 사람이 볼 수 있는 화의 보이는 남의 댓글이다. 같은 대상을 다시 신고하면 처음 신고를 그대로 돌려준다. 노벨·화·댓글
신고가 한 한도(회원당 분당 10)를 같이 쓴다. 재동의 게이트는 걸지 않는다 — 신고는 새 약관에 동의하기 전에도 열려 있어야 하는
안전 경로다. 정지된 회원은 403 이다(신고자 행을 잠근 뒤 DB 의 정지 표식으로 다시 확인한다).

**잠금** — 신고자 행 → 대상 행(키 공유) 순서다. 대상은 하나만 잡는다: 화 신고는 화 행(화가 남아 있는 동안 소설도 지워지지
않는다), 소설 신고는 소설 행, 댓글 신고는 댓글 행. 소설 삭제는 화 행을 `FOR UPDATE` 로 잡은 뒤 소설 행을 지우므로, 소설과 화를
둘 다 잡으면 그 순서와 엇갈려 교착할 수 있다."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import lock_active_user
from api.core.rate_limit import check_rate_limit
from api.db.models.moderation import ReportStatus
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelComment,
    NovelCommentReport,
    NovelPublication,
    NovelReport,
)
from api.db.session import get_db_session
from api.novel_public.access import require_novel_public_readable, select_readable_publications
from api.novel_public.comments import require_chapter_reader
from api.novel_public.schemas import (
    PublicNovelCommentReportRequest,
    PublicNovelReportRequest,
    PublicNovelReportResponse,
)
from api.session.dependencies import get_current_user_id

# 화 신고 증거로 남길 본문 앞부분의 글자 수. 화 본문은 수천 자라 통째로 두지 않는다 — 신고 화면은 문제 구절이 앞부분에 없을
# 때를 위해 지금 공개본도 함께 보여 준다. 호출 때 모듈 전역으로 읽는다(테스트가 바꿔 끼울 수 있게).
NOVEL_REPORT_EVIDENCE_BODY_CHARS = 2000
NOVEL_REPORT_EVIDENCE_DAYS = 90

reports_router = APIRouter(prefix="/webnovels", tags=["webnovels"])


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


async def _check_report_rate(user_id: uuid.UUID) -> None:
    # DB 조회보다 먼저 센다 — 없는 대상을 두드리는 요청도 같은 한도를 쓴다.
    retry_after = await check_rate_limit("novel-report", str(user_id), 10, window_seconds=60)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "NOVEL_REPORT_RATE_LIMITED",
                "message": "잠시 후 다시 신고해 주세요.",
                "retryAfterSeconds": retry_after,
                "windowSeconds": 60,
            },
            headers={"Retry-After": str(retry_after)},
        )


@reports_router.post("/{novel_id}/reports", dependencies=[Depends(require_novel_public_readable)])
async def report_webnovel(
    novel_id: uuid.UUID,
    body: PublicNovelReportRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PublicNovelReportResponse:
    """노벨(`chapterId` 없음)이나 그 공개 화 하나를 신고한다. 지금 읽을 수 없는 노벨은 404 `NOVEL_NOT_FOUND`, 그 노벨의 공개
    화가 아니면 404 `NOVEL_CHAPTER_NOT_FOUND`, 자기가 게시한 노벨은 403 `NOVEL_REPORT_OWN`, 한도를 넘으면 429
    `NOVEL_REPORT_RATE_LIMITED`. 화 신고는 그 화를 소장하지 않았어도 된다(목차의 화 제목도 공개 화면 글이다)."""
    await _check_report_rate(user_id)
    await lock_active_user(db, user_id)
    if body.chapter_id is not None:
        target = await db.scalar(
            select(NovelChapter.id)
            .where(NovelChapter.id == body.chapter_id, NovelChapter.novel_id == novel_id)
            .with_for_update(key_share=True, read=True)
        )
        if target is None:
            raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    else:
        await db.execute(select(Novel.id).where(Novel.id == novel_id).with_for_update(key_share=True, read=True))
    row = (
        await db.execute(select_readable_publications(NovelPublication, Novel).where(NovelPublication.novel_id == novel_id))
    ).one_or_none()
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND")
    publication, novel = row
    if novel.user_id == user_id:
        raise _error(status.HTTP_403_FORBIDDEN, "NOVEL_REPORT_OWN")
    chapter: tuple[NovelChapterPublication, str] | None = None
    if body.chapter_id is not None:
        found = (
            await db.execute(
                select(NovelChapterPublication, NovelChapterRevision.body)
                .join(NovelChapterRevision, NovelChapterRevision.id == NovelChapterPublication.revision_id)
                .where(
                    NovelChapterPublication.chapter_id == body.chapter_id,
                    NovelChapterPublication.novel_id == novel_id,
                )
            )
        ).one_or_none()
        if found is None:
            raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
        chapter = (found[0], found[1])

    existing = await db.scalar(
        select(NovelReport).where(
            NovelReport.reporter_user_id == user_id,
            NovelReport.novel_id == novel_id,
            NovelReport.chapter_id.is_not_distinct_from(body.chapter_id),
        )
    )
    if existing is not None:
        return PublicNovelReportResponse(report_id=existing.id, status=existing.status)
    created = datetime.now(UTC)
    report = NovelReport(
        reporter_user_id=user_id,
        publisher_user_id=novel.user_id,
        novel_id=novel_id,
        chapter_id=body.chapter_id,
        chapter_ordinal=chapter[0].ordinal if chapter is not None else None,
        reason_category=body.reason_category,
        status=ReportStatus.PENDING,
        created_at=created,
        evidence_title=publication.title if publication.title is not None else novel.content_title,
        evidence_synopsis=publication.synopsis,
        evidence_chapter_title=chapter[0].title if chapter is not None else None,
        evidence_body=chapter[1][:NOVEL_REPORT_EVIDENCE_BODY_CHARS] if chapter is not None else None,
        evidence_expires_at=created + timedelta(days=NOVEL_REPORT_EVIDENCE_DAYS),
    )
    db.add(report)
    await db.commit()
    return PublicNovelReportResponse(report_id=report.id, status=report.status)


@reports_router.post(
    "/{novel_id}/comments/{comment_id}/reports", dependencies=[Depends(require_novel_public_readable)]
)
async def report_webnovel_comment(
    novel_id: uuid.UUID,
    comment_id: uuid.UUID,
    body: PublicNovelCommentReportRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PublicNovelReportResponse:
    """남의 화 댓글을 신고한다. 없거나 지웠거나 운영자가 숨긴 댓글·내 댓글은 404 `NOVEL_COMMENT_NOT_FOUND`, 그 화를 볼 수
    없으면 404/403(`require_chapter_reader`), 한도를 넘으면 429 `NOVEL_REPORT_RATE_LIMITED`."""
    await _check_report_rate(user_id)
    await lock_active_user(db, user_id)
    comment = await db.scalar(
        select(NovelComment)
        .where(NovelComment.id == comment_id, NovelComment.novel_id == novel_id)
        .with_for_update(key_share=True, read=True)
        .execution_options(populate_existing=True)
    )
    if (
        comment is None
        or comment.deleted_at is not None
        or comment.moderator_hidden
        or comment.author_user_id == user_id
    ):
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_COMMENT_NOT_FOUND")
    await require_chapter_reader(db, novel_id=novel_id, chapter_id=comment.chapter_id, user_id=user_id)

    existing = await db.scalar(
        select(NovelCommentReport).where(
            NovelCommentReport.reporter_user_id == user_id, NovelCommentReport.comment_id == comment_id
        )
    )
    if existing is not None:
        return PublicNovelReportResponse(report_id=existing.id, status=existing.status)
    created = datetime.now(UTC)
    report = NovelCommentReport(
        reporter_user_id=user_id,
        comment_id=comment_id,
        novel_id=novel_id,
        comment_author_user_id=comment.author_user_id,
        reason_category=body.reason_category,
        status=ReportStatus.PENDING,
        created_at=created,
        evidence_body=comment.body,
        evidence_expires_at=created + timedelta(days=NOVEL_REPORT_EVIDENCE_DAYS),
    )
    db.add(report)
    await db.commit()
    return PublicNovelReportResponse(report_id=report.id, status=report.status)
