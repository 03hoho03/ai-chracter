"""어드민 노벨 — 공개 노벨 목록·상세·화 공개본, 이용제한·해제, 노벨·노벨 댓글 신고 처리, 댓글 숨김·삭제.

**이용제한**은 공개 상태 행의 `moderation_status` 하나다. 독자 쪽 판정(`select_readable_publications`)이 이 칸을 보므로
이용제한하면 목록·작품 정보·화·구매·댓글·홈에서 함께 사라지고, 소장한 사람에게는 열람 종료(`restricted`)로 보인다. 해제하면
구매 행이 그대로라 소장한 화를 다시 읽는다 — 운영자가 잘못 내린 조치는 해제로 되돌린다. 게시자에게 따로 알림을 보내지
않는다(게시자의 공개 설정 화면이 이용제한 상태를 보여 준다).

**감사 로그** — 조치마다 한 줄. 대상 회원은 노벨 조치면 게시자, 댓글 조치면 작성자라 그 회원 상세의 조치 이력에 보인다.
신고로 한 조치는 신고 사유 분류를 함께 남긴다.

**잠금** — 노벨 조치는 공개 상태 행 → 신고 행, 댓글 조치는 댓글 행 → 신고 행 순서로 잡는다. 소설·묶음 삭제가 공개 상태
행 → (댓글 DELETE) → (신고 행의 `SET NULL`) 순서로 잡기 때문이다. 신고 행을 먼저 쥐면 그 삭제와 엇갈려 교착한다. 반려는 신고
행만 잡는다.

작품 신고 처리(`moderation/router.py`)와 나란히 둔 별도 라우트다 — 작품 신고 표·조치 표는 작품 FK 를 전제하므로 노벨을
섞지 않는다. 노벨 스위치와 무관하게 돈다(켜기 전에도 운영자가 볼 수 있게)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.db.models.auth import User
from api.db.models.content import Content
from api.db.models.moderation import AdminActionType, ReportStatus
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelComment,
    NovelCommentReport,
    NovelPublication,
    NovelPublicationModerationStatus,
    NovelPurchase,
    NovelReport,
    NovelScreening,
)
from api.db.session import get_db_session
from api.novel_public.access import select_readable_publications
from api.novel_public.admin_schemas import (
    AdminNovelChapterItem,
    AdminNovelChapterResponse,
    AdminNovelCommentAction,
    AdminNovelCommentActionRequest,
    AdminNovelCommentItem,
    AdminNovelCommentListResponse,
    AdminNovelCommentReportActionRequest,
    AdminNovelCommentReportDetailResponse,
    AdminNovelCommentReportEvidence,
    AdminNovelCommentReportListItem,
    AdminNovelCommentReportListResponse,
    AdminNovelDetailResponse,
    AdminNovelListItem,
    AdminNovelListResponse,
    AdminNovelModerationRequest,
    AdminNovelModerationResponse,
    AdminNovelReportActionRequest,
    AdminNovelReportDetailResponse,
    AdminNovelReportEvidence,
    AdminNovelReportListItem,
    AdminNovelReportListResponse,
    AdminNovelScreeningItem,
)
from api.novelize.text import split_paragraphs

ADMIN_NOVEL_PAGE_SIZE = 20

router = APIRouter(tags=["admin"])

_COMMENT_ACTION_LOG: dict[AdminNovelCommentAction, AdminActionType] = {
    "hide": "novel-comment-hide",
    "restore": "novel-comment-restore",
    "delete": "novel-comment-delete",
}


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


def _require_reason(admin_comment: str) -> str:
    reason = admin_comment.strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="운영 조치 사유를 입력해주세요.")
    return reason


def _total_pages(total: int) -> int:
    return -(-total // ADMIN_NOVEL_PAGE_SIZE) if total else 0


def _evidence_available(purged_at: datetime | None, expires_at: datetime) -> bool:
    """보유 기간이 지나면 파기 작업이 돌기 전에도 숨긴다(작품 댓글·채팅 응답 신고와 같다)."""
    return purged_at is None and datetime.now(UTC) < expires_at


# ── 노벨 목록·상세 ──────────────────────────────────────────────────────────
async def _list_items(db: AsyncSession, rows: list[tuple[NovelPublication, Novel, str | None]]) -> list[AdminNovelListItem]:
    novel_ids = [novel.id for _, novel, _ in rows]
    if not novel_ids:
        return []
    readable = set(
        (
            await db.scalars(
                select_readable_publications(NovelPublication.novel_id).where(NovelPublication.novel_id.in_(novel_ids))
            )
        ).all()
    )
    chapter_counts = dict(
        (
            await db.execute(
                select(NovelChapterPublication.novel_id, func.count())
                .where(NovelChapterPublication.novel_id.in_(novel_ids))
                .group_by(NovelChapterPublication.novel_id)
            )
        )
        .tuples()
        .all()
    )
    purchase_counts = dict(
        (
            await db.execute(
                select(NovelPurchase.novel_id, func.count())
                .where(NovelPurchase.novel_id.in_(novel_ids), NovelPurchase.refunded_at.is_(None))
                .group_by(NovelPurchase.novel_id)
            )
        )
        .tuples()
        .all()
    )
    report_counts = dict(
        (
            await db.execute(
                select(NovelReport.novel_id, func.count())
                .where(NovelReport.novel_id.in_(novel_ids), NovelReport.status == ReportStatus.PENDING)
                .group_by(NovelReport.novel_id)
            )
        )
        .tuples()
        .all()
    )
    return [
        AdminNovelListItem(
            id=novel.id,
            title=publication.title if publication.title is not None else novel.content_title,
            source_title=novel.content_title,
            publisher_user_id=novel.user_id,
            publisher_nickname=nickname,
            visibility=publication.visibility,
            moderation_status=publication.moderation_status,
            readable=novel.id in readable,
            chapter_count=chapter_counts.get(novel.id, 0),
            like_count=publication.like_count,
            view_count=publication.view_count,
            purchase_count=purchase_counts.get(novel.id, 0),
            pending_report_count=report_counts.get(novel.id, 0),
            published_at=publication.published_at,
        )
        for publication, novel, nickname in rows
    ]


def _report_item(report: NovelReport) -> AdminNovelReportListItem:
    available = _evidence_available(report.evidence_purged_at, report.evidence_expires_at)
    return AdminNovelReportListItem(
        id=report.id,
        novel_id=report.novel_id,
        chapter_id=report.chapter_id,
        chapter_ordinal=report.chapter_ordinal,
        publisher_user_id=report.publisher_user_id,
        reporter_user_id=report.reporter_user_id,
        reason_category=report.reason_category,
        status=report.status,
        created_at=report.created_at,
        evidence_title=report.evidence_title if available else None,
        evidence_expires_at=report.evidence_expires_at,
        evidence_available=available,
    )


@router.get("/admin/novels")
async def list_admin_novels(
    page: int = Query(1, ge=1),
    moderation_status: NovelPublicationModerationStatus | None = Query(None, alias="moderationStatus"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelListResponse:
    """공개한 적 있는 노벨 전부, 마지막 공개 시각 최신순 20개씩(쪽 번호). 이용제한 상태로 거를 수 있다."""
    filters = [NovelPublication.moderation_status == moderation_status] if moderation_status is not None else []
    total = (await db.scalar(select(func.count()).select_from(NovelPublication).where(*filters))) or 0
    rows = (
        await db.execute(
            select(NovelPublication, Novel, User.nickname)
            .join(Novel, Novel.id == NovelPublication.novel_id)
            .join(User, User.id == Novel.user_id)
            .where(*filters)
            .order_by(NovelPublication.published_at.desc(), NovelPublication.novel_id.desc())
            .offset((page - 1) * ADMIN_NOVEL_PAGE_SIZE)
            .limit(ADMIN_NOVEL_PAGE_SIZE)
        )
    ).tuples().all()
    return AdminNovelListResponse(
        items=await _list_items(db, list(rows)), page=page, total_pages=_total_pages(total), total_count=total
    )


async def _detail(db: AsyncSession, novel_id: uuid.UUID) -> AdminNovelDetailResponse:
    row = (
        await db.execute(
            select(NovelPublication, Novel, User)
            .join(Novel, Novel.id == NovelPublication.novel_id)
            .join(User, User.id == Novel.user_id)
            .where(NovelPublication.novel_id == novel_id)
        )
    ).tuples().one_or_none()
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND")
    publication, novel, publisher = row
    [item] = await _list_items(db, [(publication, novel, publisher.nickname)])
    chapters = (
        await db.scalars(
            select(NovelChapterPublication)
            .where(NovelChapterPublication.novel_id == novel_id)
            .order_by(NovelChapterPublication.ordinal)
        )
    ).all()
    screenings = (
        await db.scalars(
            select(NovelScreening)
            .where(NovelScreening.novel_id == novel_id)
            .order_by(NovelScreening.created_at.desc(), NovelScreening.id.desc())
            .limit(20)
        )
    ).all()
    reports = (
        await db.scalars(
            select(NovelReport)
            .where(NovelReport.novel_id == novel_id)
            .order_by(NovelReport.created_at.desc(), NovelReport.id.desc())
            .limit(20)
        )
    ).all()
    buyers, amount = (
        await db.execute(
            select(func.count(func.distinct(NovelPurchase.buyer_user_id)), func.coalesce(func.sum(NovelPurchase.price), 0))
            .where(NovelPurchase.novel_id == novel_id, NovelPurchase.refunded_at.is_(None))
        )
    ).one()
    source = await db.get(Content, novel.content_id)
    return AdminNovelDetailResponse(
        **item.model_dump(),
        synopsis=publication.synopsis,
        content_id=novel.content_id,
        source_moderation_status=source.moderation_status if source is not None else None,
        publisher_suspended=publisher.suspended_at is not None,
        first_published_at=publication.first_published_at,
        chapters=[
            AdminNovelChapterItem(id=c.chapter_id, ordinal=c.ordinal, title=c.title, edition=c.edition) for c in chapters
        ],
        screenings=[
            AdminNovelScreeningItem(
                chapter_ordinal=s.chapter_ordinal,
                outcome=s.outcome,
                flagged_parts=list(s.flagged_parts),
                reason=s.reason,
                model=s.model,
                created_at=s.created_at,
            )
            for s in screenings
        ],
        reports=[_report_item(report) for report in reports],
        purchase_buyer_count=int(buyers),
        purchase_amount=int(amount),
    )


@router.get("/admin/novels/{novel_id}")
async def get_admin_novel(
    novel_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelDetailResponse:
    """공개한 적 있는 노벨 하나(공개본 글·화 목록·심사 기록·최근 신고·구매). 공개 상태 행이 없으면 404 `NOVEL_NOT_FOUND`."""
    return await _detail(db, novel_id)


@router.get("/admin/novels/{novel_id}/chapters/{chapter_id}")
async def get_admin_novel_chapter(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelChapterResponse:
    """화 공개본 하나 — 독자에게 나가는 그대로. 그 노벨의 공개 화가 아니면 404 `NOVEL_CHAPTER_NOT_FOUND`."""
    row = (
        await db.execute(
            select(NovelChapterPublication, NovelChapterRevision.body)
            .join(NovelChapterRevision, NovelChapterRevision.id == NovelChapterPublication.revision_id)
            .where(NovelChapterPublication.novel_id == novel_id, NovelChapterPublication.chapter_id == chapter_id)
        )
    ).tuples().one_or_none()
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    chapter, body = row
    return AdminNovelChapterResponse(
        id=chapter.chapter_id,
        ordinal=chapter.ordinal,
        title=chapter.title,
        author_note=chapter.author_note,
        edition=chapter.edition,
        paragraphs=split_paragraphs(body),
    )


# ── 이용제한·해제 ────────────────────────────────────────────────────────────
async def _lock_publication(db: AsyncSession, novel_id: uuid.UUID) -> NovelPublication | None:
    publication: NovelPublication | None = await db.scalar(
        select(NovelPublication)
        .where(NovelPublication.novel_id == novel_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return publication


async def _set_moderation(
    db: AsyncSession,
    publication: NovelPublication,
    *,
    admin_id: uuid.UUID,
    restrict: bool,
    reason_category: str | None,
    reason: str,
) -> None:
    """이용제한 칸을 바꾸고 감사 로그를 남긴다(커밋은 호출부). 대상 회원은 게시자다."""
    publication.moderation_status = "restricted" if restrict else "normal"
    publisher_id = await db.scalar(select(Novel.user_id).where(Novel.id == publication.novel_id))
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="novel-restrict" if restrict else "novel-lift",
        target_user_id=publisher_id,
        target_novel_id=publication.novel_id,
        reason_category=reason_category,
        reason_text=reason,
    )


@router.post("/admin/novels/{novel_id}/moderation")
async def moderate_admin_novel(
    novel_id: uuid.UUID,
    body: AdminNovelModerationRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelModerationResponse:
    """노벨을 이용제한(`restrict`)하거나 해제(`lift`)한다. 사유가 공백뿐이면 422, 공개 상태 행이 없으면 404
    `NOVEL_NOT_FOUND`, 이미 그 상태면 409 `NOVEL_ALREADY_RESTRICTED`·`NOVEL_NOT_RESTRICTED`(감사 로그가 빈 조치로 쌓이지
    않게)."""
    reason = _require_reason(body.admin_comment)
    publication = await _lock_publication(db, novel_id)
    if publication is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND")
    restrict = body.action == "restrict"
    if restrict and publication.moderation_status == "restricted":
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_ALREADY_RESTRICTED")
    if not restrict and publication.moderation_status == "normal":
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_NOT_RESTRICTED")
    await _set_moderation(
        db,
        publication,
        admin_id=admin_id,
        restrict=restrict,
        reason_category=body.reason_category.value if body.reason_category is not None else None,
        reason=reason,
    )
    await db.commit()
    return AdminNovelModerationResponse(novel_id=novel_id, moderation_status=publication.moderation_status)


# ── 노벨 신고 ───────────────────────────────────────────────────────────────
async def _report_detail(db: AsyncSession, report: NovelReport) -> AdminNovelReportDetailResponse:
    available = _evidence_available(report.evidence_purged_at, report.evidence_expires_at)
    publication = await db.get(NovelPublication, report.novel_id) if report.novel_id is not None else None
    return AdminNovelReportDetailResponse(
        **_report_item(report).model_dump(),
        resolved_by_admin_id=report.resolved_by_admin_id,
        resolved_at=report.resolved_at,
        novel_moderation_status=publication.moderation_status if publication is not None else None,
        evidence=AdminNovelReportEvidence(
            expires_at=report.evidence_expires_at,
            available=available,
            title=report.evidence_title if available else None,
            synopsis=report.evidence_synopsis if available else None,
            chapter_title=report.evidence_chapter_title if available else None,
            body=report.evidence_body if available else None,
        ),
    )


async def _get_novel_report(db: AsyncSession, report_id: uuid.UUID, *, lock: bool = False) -> NovelReport:
    statement = select(NovelReport).where(NovelReport.id == report_id).execution_options(populate_existing=True)
    report = await db.scalar(statement.with_for_update() if lock else statement)
    if report is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_REPORT_NOT_FOUND")
    return report


@router.get("/admin/novel-reports")
async def list_admin_novel_reports(
    page: int = Query(1, ge=1),
    status_filter: ReportStatus | None = Query(None, alias="status"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelReportListResponse:
    """노벨 신고 최신순 20개씩(쪽 번호). 상태로 거를 수 있다."""
    filters = [NovelReport.status == status_filter] if status_filter is not None else []
    total = (await db.scalar(select(func.count()).select_from(NovelReport).where(*filters))) or 0
    reports = (
        await db.scalars(
            select(NovelReport)
            .where(*filters)
            .order_by(NovelReport.created_at.desc(), NovelReport.id.desc())
            .offset((page - 1) * ADMIN_NOVEL_PAGE_SIZE)
            .limit(ADMIN_NOVEL_PAGE_SIZE)
        )
    ).all()
    return AdminNovelReportListResponse(
        items=[_report_item(report) for report in reports],
        page=page,
        total_pages=_total_pages(total),
        total_count=total,
    )


@router.get("/admin/novel-reports/{report_id}")
async def get_admin_novel_report(
    report_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelReportDetailResponse:
    return await _report_detail(db, await _get_novel_report(db, report_id))


@router.post("/admin/novel-reports/{report_id}/actions")
async def act_on_admin_novel_report(
    report_id: uuid.UUID,
    body: AdminNovelReportActionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelReportDetailResponse:
    """신고를 처리한다 — `restrict` 는 그 노벨을 이용제한하고 신고를 처리완료로(이미 이용제한이어도 처리된다), `reject` 는
    노벨을 건드리지 않고 반려로 둔다. 이미 처리된 신고도 다시 처리할 수 있다(상태·처리자·시각을 덮어쓴다). 노벨이 지워져
    이용제한할 대상이 없으면 409 `NOVEL_GONE`(반려는 된다)."""
    reason = _require_reason(body.admin_comment)
    report = await _get_novel_report(db, report_id)
    if body.action == "restrict":
        publication = await _lock_publication(db, report.novel_id) if report.novel_id is not None else None
        if publication is None:
            raise _error(status.HTTP_409_CONFLICT, "NOVEL_GONE")
        report = await _get_novel_report(db, report_id, lock=True)
        await _set_moderation(
            db,
            publication,
            admin_id=admin_id,
            restrict=True,
            reason_category=report.reason_category.value,
            reason=reason,
        )
        report.status = ReportStatus.RESOLVED
    else:
        report = await _get_novel_report(db, report_id, lock=True)
        await record_admin_action(
            db,
            admin_id=admin_id,
            action_type="novel-report-reject",
            target_user_id=report.publisher_user_id,
            target_novel_id=report.novel_id,
            reason_category=report.reason_category.value,
            reason_text=reason,
        )
        report.status = ReportStatus.REJECTED
    report.resolved_by_admin_id = admin_id
    report.resolved_at = datetime.now(UTC)
    await db.commit()
    return await _report_detail(db, report)


# ── 댓글 ────────────────────────────────────────────────────────────────────
async def _comment_items(db: AsyncSession, comments: list[NovelComment]) -> list[AdminNovelCommentItem]:
    if not comments:
        return []
    ordinals = dict(
        (
            await db.execute(
                select(NovelChapter.id, NovelChapter.ordinal).where(NovelChapter.id.in_({c.chapter_id for c in comments}))
            )
        )
        .tuples()
        .all()
    )
    nicknames = dict(
        (
            await db.execute(
                select(User.id, User.nickname).where(User.id.in_({c.author_user_id for c in comments}))
            )
        )
        .tuples()
        .all()
    )
    return [
        AdminNovelCommentItem(
            id=comment.id,
            novel_id=comment.novel_id,
            chapter_id=comment.chapter_id,
            chapter_ordinal=ordinals[comment.chapter_id],
            author_user_id=comment.author_user_id,
            author_nickname=nicknames.get(comment.author_user_id),
            body=comment.body,
            moderator_hidden=comment.moderator_hidden,
            deleted_by=comment.deleted_by,
            deleted_at=comment.deleted_at,
            created_at=comment.created_at,
        )
        for comment in comments
    ]


@router.get("/admin/novels/{novel_id}/comments")
async def list_admin_novel_comments(
    novel_id: uuid.UUID,
    page: int = Query(1, ge=1),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelCommentListResponse:
    """노벨 하나의 댓글 전부(지운 것·숨긴 것 포함) 최신순 20개씩(쪽 번호)."""
    total = (
        await db.scalar(select(func.count()).select_from(NovelComment).where(NovelComment.novel_id == novel_id))
    ) or 0
    comments = (
        await db.scalars(
            select(NovelComment)
            .where(NovelComment.novel_id == novel_id)
            .order_by(NovelComment.created_at.desc(), NovelComment.id.desc())
            .offset((page - 1) * ADMIN_NOVEL_PAGE_SIZE)
            .limit(ADMIN_NOVEL_PAGE_SIZE)
        )
    ).all()
    return AdminNovelCommentListResponse(
        items=await _comment_items(db, list(comments)), page=page, total_pages=_total_pages(total), total_count=total
    )


async def _lock_comment(db: AsyncSession, comment_id: uuid.UUID) -> NovelComment | None:
    comment: NovelComment | None = await db.scalar(
        select(NovelComment)
        .where(NovelComment.id == comment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return comment


async def _moderate_comment(
    db: AsyncSession,
    comment: NovelComment,
    *,
    admin_id: uuid.UUID,
    action: AdminNovelCommentAction,
    reason_category: str | None,
    reason: str,
) -> None:
    """숨김·숨김 해제·삭제 하나와 감사 로그(커밋은 호출부). 지운 댓글에는 아무것도 할 수 없어 409 `NOVEL_COMMENT_DELETED`."""
    if comment.deleted_at is not None:
        raise _error(status.HTTP_409_CONFLICT, "NOVEL_COMMENT_DELETED")
    if action == "delete":
        comment.body = None
        comment.deleted_at = datetime.now(UTC)
        comment.deleted_by = "moderator"
    else:
        comment.moderator_hidden = action == "hide"
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type=_COMMENT_ACTION_LOG[action],
        target_user_id=comment.author_user_id,
        target_novel_id=comment.novel_id,
        reason_category=reason_category,
        reason_text=reason,
    )


@router.post("/admin/novel-comments/{comment_id}/actions", status_code=status.HTTP_204_NO_CONTENT)
async def act_on_admin_novel_comment(
    comment_id: uuid.UUID,
    body: AdminNovelCommentActionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """댓글을 숨기거나(`hide`, 독자 목록에서 빠지고 본문은 남는다) 되돌리거나(`restore`) 지운다(`delete`, 본문을 비우고 되돌릴
    수 없다). 사유가 공백뿐이면 422, 없는 댓글은 404 `NOVEL_COMMENT_NOT_FOUND`, 지운 댓글은 409."""
    reason = _require_reason(body.admin_comment)
    comment = await _lock_comment(db, comment_id)
    if comment is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_COMMENT_NOT_FOUND")
    await _moderate_comment(db, comment, admin_id=admin_id, action=body.action, reason_category=None, reason=reason)
    await db.commit()


# ── 댓글 신고 ───────────────────────────────────────────────────────────────
def _comment_report_item(report: NovelCommentReport) -> AdminNovelCommentReportListItem:
    return AdminNovelCommentReportListItem(
        id=report.id,
        comment_id=report.comment_id,
        novel_id=report.novel_id,
        comment_author_user_id=report.comment_author_user_id,
        reporter_user_id=report.reporter_user_id,
        reason_category=report.reason_category,
        status=report.status,
        created_at=report.created_at,
        evidence_expires_at=report.evidence_expires_at,
        evidence_available=_evidence_available(report.evidence_purged_at, report.evidence_expires_at),
    )


async def _comment_report_detail(db: AsyncSession, report: NovelCommentReport) -> AdminNovelCommentReportDetailResponse:
    item = _comment_report_item(report)
    comment = await db.get(NovelComment, report.comment_id) if report.comment_id is not None else None
    comment_item = (await _comment_items(db, [comment]))[0] if comment is not None else None
    return AdminNovelCommentReportDetailResponse(
        **item.model_dump(),
        resolved_by_admin_id=report.resolved_by_admin_id,
        resolved_at=report.resolved_at,
        comment=comment_item,
        evidence=AdminNovelCommentReportEvidence(
            expires_at=report.evidence_expires_at,
            available=item.evidence_available,
            body=report.evidence_body if item.evidence_available else None,
        ),
    )


async def _get_comment_report(db: AsyncSession, report_id: uuid.UUID, *, lock: bool = False) -> NovelCommentReport:
    statement = (
        select(NovelCommentReport)
        .where(NovelCommentReport.id == report_id)
        .execution_options(populate_existing=True)
    )
    report = await db.scalar(statement.with_for_update() if lock else statement)
    if report is None:
        raise _error(status.HTTP_404_NOT_FOUND, "NOVEL_COMMENT_REPORT_NOT_FOUND")
    return report


@router.get("/admin/novel-comment-reports")
async def list_admin_novel_comment_reports(
    page: int = Query(1, ge=1),
    status_filter: ReportStatus | None = Query(None, alias="status"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelCommentReportListResponse:
    """노벨 댓글 신고 최신순 20개씩(쪽 번호). 상태로 거를 수 있다."""
    filters = [NovelCommentReport.status == status_filter] if status_filter is not None else []
    total = (await db.scalar(select(func.count()).select_from(NovelCommentReport).where(*filters))) or 0
    reports = (
        await db.scalars(
            select(NovelCommentReport)
            .where(*filters)
            .order_by(NovelCommentReport.created_at.desc(), NovelCommentReport.id.desc())
            .offset((page - 1) * ADMIN_NOVEL_PAGE_SIZE)
            .limit(ADMIN_NOVEL_PAGE_SIZE)
        )
    ).all()
    return AdminNovelCommentReportListResponse(
        items=[_comment_report_item(report) for report in reports],
        page=page,
        total_pages=_total_pages(total),
        total_count=total,
    )


@router.get("/admin/novel-comment-reports/{report_id}")
async def get_admin_novel_comment_report(
    report_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelCommentReportDetailResponse:
    return await _comment_report_detail(db, await _get_comment_report(db, report_id))


@router.post("/admin/novel-comment-reports/{report_id}/actions")
async def act_on_admin_novel_comment_report(
    report_id: uuid.UUID,
    body: AdminNovelCommentReportActionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNovelCommentReportDetailResponse:
    """댓글 신고를 처리한다 — `hide`·`delete` 는 그 댓글을 숨기거나 지우고 처리완료로, `reject` 는 댓글을 건드리지 않고
    반려로 둔다. 이미 처리된 신고도 다시 처리할 수 있다. 댓글이 지워져(작성자 탈퇴·소설 삭제) 조치할 대상이 없으면 409
    `NOVEL_COMMENT_GONE`, 지운 댓글이면 409 `NOVEL_COMMENT_DELETED`(반려는 된다)."""
    reason = _require_reason(body.admin_comment)
    report = await _get_comment_report(db, report_id)
    if body.action == "reject":
        report = await _get_comment_report(db, report_id, lock=True)
        await record_admin_action(
            db,
            admin_id=admin_id,
            action_type="novel-comment-report-reject",
            target_user_id=report.comment_author_user_id,
            target_novel_id=report.novel_id,
            reason_category=report.reason_category.value,
            reason_text=reason,
        )
        report.status = ReportStatus.REJECTED
    else:
        comment = await _lock_comment(db, report.comment_id) if report.comment_id is not None else None
        if comment is None:
            raise _error(status.HTTP_409_CONFLICT, "NOVEL_COMMENT_GONE")
        report = await _get_comment_report(db, report_id, lock=True)
        await _moderate_comment(
            db,
            comment,
            admin_id=admin_id,
            action=body.action,
            reason_category=report.reason_category.value,
            reason=reason,
        )
        report.status = ReportStatus.RESOLVED
    report.resolved_by_admin_id = admin_id
    report.resolved_at = datetime.now(UTC)
    await db.commit()
    return await _comment_report_detail(db, report)
