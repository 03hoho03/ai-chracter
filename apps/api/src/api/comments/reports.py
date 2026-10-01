import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.comments.access import comment_error, lock_active_user, lock_comment_context, require_readable_content, require_unhide_allowed
from api.comments.read import serialize_admin_comments, serialize_comments
from api.comments.schemas import (
    AdminCommentContentContextResponse,
    AdminCommentModerationRequest,
    AdminCommentReportActionRequest,
    AdminCommentReportDetailResponse,
    AdminCommentReportListItem,
    AdminCommentReportListResponse,
    CommentReportCreateRequest,
    CommentReportEvidenceResponse,
    CommentReportResponse,
)
from api.core.rate_limit import check_rate_limit
from api.db.models.auth import User
from api.db.models.comments import (
    Comment,
    CommentMention,
    CommentModerationAction,
    CommentModerationActionType,
    CommentReport,
)
from api.db.models.content import Content
from api.db.models.moderation import AdminActionType, Notification, ReportStatus
from api.db.session import get_db_session
from api.moderation.router import _admin_report_content_detail
from api.session.dependencies import get_current_user_id

router = APIRouter(tags=["comment-moderation"])
ACTION_LOG_TYPES: dict[CommentModerationActionType, AdminActionType] = {
    "hide": "comment-hide",
    "restore": "comment-restore",
    "reject": "comment-report-reject",
}


@router.post("/comments/{comment_id}/reports")
async def report_comment(
    comment_id: uuid.UUID,
    body: CommentReportCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> CommentReportResponse:
    retry_after = await check_rate_limit("comment-report", str(user_id), 10, window_seconds=60)
    if retry_after:
        raise HTTPException(
            429,
            detail={
                "code": "COMMENT_RATE_LIMITED",
                "message": "잠시 후 다시 신고해 주세요.",
                "retryAfterSeconds": retry_after,
                "windowSeconds": 60,
            },
            headers={"Retry-After": str(retry_after)},
        )
    await lock_active_user(db, user_id)
    content, comment = await lock_comment_context(db, comment_id)
    require_readable_content(content, user_id)
    current = (await serialize_comments(db, content, [comment], user_id))[0]
    if not current.can_report:
        raise comment_error(404, "COMMENT_NOT_FOUND", "신고할 수 있는 댓글을 찾지 못했어요.")
    report = await db.scalar(
        select(CommentReport).where(CommentReport.reporter_user_id == user_id, CommentReport.comment_id == comment_id)
    )
    if report is None:
        created = datetime.now(UTC)
        mentions = list(
            (
                await db.scalars(
                    select(CommentMention.user_id)
                    .where(CommentMention.comment_id == comment_id)
                    .order_by(CommentMention.user_id)
                )
            ).all()
        )
        report = CommentReport(
            reporter_user_id=user_id,
            comment_id=comment_id,
            reason_category=body.reason_category,
            status=ReportStatus.PENDING,
            created_at=created,
            evidence_body=comment.body,
            evidence_sticker_id=comment.sticker_id,
            evidence_mention_user_ids=mentions,
            evidence_expires_at=created + timedelta(days=90),
        )
        db.add(report)
        await db.commit()
    return CommentReportResponse(report_id=report.id, status=report.status)


def _evidence(report: CommentReport) -> CommentReportEvidenceResponse:
    available = report.evidence_purged_at is None and datetime.now(UTC) < report.evidence_expires_at
    return CommentReportEvidenceResponse(
        expires_at=report.evidence_expires_at,
        available=available,
        body=report.evidence_body if available else None,
        sticker_id=report.evidence_sticker_id if available else None,
        mention_user_ids=report.evidence_mention_user_ids if available else [],
    )


async def _report_detail(db: AsyncSession, report: CommentReport) -> AdminCommentReportDetailResponse:
    comment = await db.get(Comment, report.comment_id)
    assert comment is not None
    content = await db.get(Content, comment.content_id)
    assert content is not None
    ids = {comment.id, comment.root_comment_id or comment.id}
    if comment.reply_to_comment_id is not None:
        ids.add(comment.reply_to_comment_id)
    comments = list((await db.scalars(select(Comment).where(Comment.id.in_(ids)))).all())
    serialized = {item.id: item for item in await serialize_admin_comments(db, content, comments)}
    context = await _admin_report_content_detail(db, content)
    return AdminCommentReportDetailResponse(
        id=report.id,
        reason_category=report.reason_category,
        reporter_user_id=report.reporter_user_id,
        status=report.status,
        created_at=report.created_at,
        resolved_by_admin_id=report.resolved_by_admin_id,
        resolved_at=report.resolved_at,
        content=AdminCommentContentContextResponse(
            id=content.id,
            type=content.type,
            name=context.name,
            thumbnail_url=context.thumbnail_url,
            detail_description=context.detail_description,
            visibility=content.visibility,
            moderation_status=content.moderation_status,
        ),
        comment=serialized[comment.id],
        root=serialized[comment.root_comment_id or comment.id],
        reply_to=serialized.get(comment.reply_to_comment_id) if comment.reply_to_comment_id else None,
        evidence=_evidence(report),
    )


async def _get_report(db: AsyncSession, report_id: uuid.UUID) -> CommentReport:
    report = await db.get(CommentReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Comment report not found")
    return report


@router.get("/admin/comment-reports")
async def list_comment_reports(
    page: int = Query(1, ge=1),
    status_filter: ReportStatus | None = Query(None, alias="status"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminCommentReportListResponse:
    filters = [CommentReport.status == status_filter] if status_filter is not None else []
    total = (await db.scalar(select(func.count()).select_from(CommentReport).where(*filters))) or 0
    reports = (
        await db.scalars(
            select(CommentReport)
            .where(*filters)
            .order_by(CommentReport.created_at.desc(), CommentReport.id.desc())
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    items = []
    for report in reports:
        comment = await db.get(Comment, report.comment_id)
        assert comment is not None
        content = await db.get(Content, comment.content_id)
        assert content is not None
        context = await _admin_report_content_detail(db, content)
        items.append(
            AdminCommentReportListItem(
                id=report.id,
                comment_id=comment.id,
                content_id=content.id,
                content_type=content.type,
                content_name=context.name,
                reason_category=report.reason_category,
                status=report.status,
                created_at=report.created_at,
                evidence_expires_at=report.evidence_expires_at,
                evidence_available=_evidence(report).available,
            )
        )
    return AdminCommentReportListResponse(
        items=items, page=page, total_count=total, total_pages=-(-total // 20) if total else 0
    )


@router.get("/admin/comment-reports/{report_id}")
async def get_comment_report(
    report_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminCommentReportDetailResponse:
    return await _report_detail(db, await _get_report(db, report_id))


async def _moderate(
    db: AsyncSession,
    content: Content,
    comment: Comment,
    *,
    admin_id: uuid.UUID,
    action: CommentModerationActionType,
    admin_comment: str,
    report: CommentReport | None = None,
) -> None:
    reason = admin_comment.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="운영 조치 사유를 입력해주세요.")
    if action == "restore":
        require_unhide_allowed(comment)
    if action in ("hide", "restore"):
        comment.moderator_hidden = action == "hide"
        if action == "hide" and content.pinned_comment_id == comment.id:
            content.pinned_comment_id = None
    reason_category = report.reason_category.value if report else None
    action_row = CommentModerationAction(
        comment_id=comment.id,
        report_id=report.id if report else None,
        admin_id=admin_id,
        action=action,
        reason_category=reason_category,
        admin_comment=reason,
    )
    db.add(action_row)
    await db.flush()
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type=ACTION_LOG_TYPES[action],
        target_user_id=comment.author_user_id,
        target_content_id=content.id,
        target_comment_id=comment.id,
        reason_category=reason_category,
        reason_text=reason,
    )
    author = await db.get(User, comment.author_user_id)
    if action != "reject" and author is not None and author.deleted_at is None:
        db.add(
            Notification(
                user_id=author.id,
                type="comment-moderated",
                content_id=content.id,
                comment_id=comment.id,
                comment_action_id=action_row.id,
                reason_category=reason_category,
                admin_comment=reason,
            )
        )
    if report is not None:
        report.status = ReportStatus.REJECTED if action == "reject" else ReportStatus.RESOLVED
        report.resolved_at = datetime.now(UTC)
        report.resolved_by_admin_id = admin_id


@router.post("/admin/comment-reports/{report_id}/actions")
async def act_on_comment_report(
    report_id: uuid.UUID,
    body: AdminCommentReportActionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminCommentReportDetailResponse:
    report = await _get_report(db, report_id)
    content, comment = await lock_comment_context(db, report.comment_id)
    # 작품 잠금을 기다리는 동안 다른 운영자의 신고 처리 상태가 바뀔 수 있다.
    await db.refresh(report)
    await _moderate(
        db, content, comment, admin_id=admin_id, action=body.action, admin_comment=body.admin_comment, report=report
    )
    await db.commit()
    return await _report_detail(db, report)


@router.put("/admin/comments/{comment_id}/moderator-hidden", status_code=status.HTTP_204_NO_CONTENT)
async def hide_comment_as_moderator(
    comment_id: uuid.UUID,
    body: AdminCommentModerationRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    content, comment = await lock_comment_context(db, comment_id)
    await _moderate(db, content, comment, admin_id=admin_id, action="hide", admin_comment=body.admin_comment)
    await db.commit()


@router.delete("/admin/comments/{comment_id}/moderator-hidden", status_code=status.HTTP_204_NO_CONTENT)
async def restore_comment_as_moderator(
    comment_id: uuid.UUID,
    body: AdminCommentModerationRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    content, comment = await lock_comment_context(db, comment_id)
    await _moderate(db, content, comment, admin_id=admin_id, action="restore", admin_comment=body.admin_comment)
    await db.commit()
