"""AI 응답 신고 — 회원 접수와 어드민 목록·상세·처리.

댓글 신고(`comments/reports.py`)와 같은 모양이다: 접수 시 대화 사본을 증거로 복사해 두고, 90일이
지나거나 파기되면 어드민 조회에서 숨긴다. 차이는 신고 대상이 사람이 쓴 글이 아니라 AI 응답이라
처리가 해결·기각뿐이라는 점과, 신고자가 곧 대화 당사자라 탈퇴하면 사본을 즉시 비운다는 점이다
(탈퇴 처리는 `auth/router.py`의 `withdraw`).
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.chat.router import _get_owned_room
from api.chat.schemas import (
    AdminChatMessageReportActionRequest,
    AdminChatMessageReportDetailResponse,
    AdminChatMessageReportListItem,
    AdminChatMessageReportListResponse,
    ChatMessageReportCreateRequest,
    ChatMessageReportEvidenceResponse,
    ChatMessageReportResponse,
)
from api.comments.access import lock_active_user
from api.core.rate_limit import check_rate_limit
from api.db.models.chat import ChatMessage, ChatMessageReport, ChatMessageRole
from api.db.models.moderation import ReportStatus
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id

router = APIRouter(tags=["chat-moderation"])

_ADMIN_PAGE_SIZE = 20


@router.post("/chat-rooms/{room_id}/messages/{message_id}/report")
async def report_chat_message(
    room_id: uuid.UUID,
    message_id: uuid.UUID,
    body: ChatMessageReportCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatMessageReportResponse:
    """같은 회원이 같은 메시지를 다시 신고하면 처음 행을 그대로 돌려준다(사유·메모·증거·만료를
    갱신하지 않는다). 재동의 게이트를 걸지 않는다 — 신고는 새 약관에 동의하기 전에도 열려 있어야
    하는 안전 경로다."""
    # DB 조회보다 먼저 센다 — 남의 방·없는 방을 두드리는 요청도 같은 한도를 쓴다.
    retry_after = await check_rate_limit("chat-message-report", str(user_id), 10, window_seconds=60)
    if retry_after:
        raise HTTPException(
            429,
            detail={
                "code": "CHAT_REPORT_RATE_LIMITED",
                "message": "잠시 후 다시 신고해 주세요.",
                "retryAfterSeconds": retry_after,
                "windowSeconds": 60,
            },
            headers={"Retry-After": str(retry_after)},
        )
    # 신고자 행을 잠가 같은 회원의 동시 신고(더블클릭)를 직렬화한다. 유니크 키가 (메시지, 신고자)라
    # 중복 요청은 항상 같은 회원이고, 뒤 요청은 앞 요청의 커밋을 본 뒤 아래 중복 조회를 한다 —
    # 잠그지 않으면 둘 다 "없음"을 보고 INSERT 해 유니크 위반 500이 난다.
    await lock_active_user(db, user_id)
    room = await _get_owned_room(db, room_id, user_id)
    # 대상 메시지 행을 잠가 재생성·수정·삭제의 DELETE와 직렬화한다. 그 DELETE가 아직 커밋 전이면
    # 여기서 기다렸다가 행이 사라진 것을 보고 아래 404로 간다 — 잠그지 않으면 지워지기 전 행을 읽고
    # 신고를 INSERT 하다 FK 위반 500이 난다.
    message = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.id == message_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if message is None or message.chat_room_id != room.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    # 사용자 메시지 수정이 AI 메시지를 400으로 거절하는 것과 같은 모양이다.
    if message.role != ChatMessageRole.ASSISTANT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only AI messages can be reported")

    report = await db.scalar(
        select(ChatMessageReport).where(
            ChatMessageReport.reporter_user_id == user_id, ChatMessageReport.chat_message_id == message.id
        )
    )
    if report is None:
        # "직전"은 메시지 목록 정렬과 같은 (created_at, id) 순서로 정한다. created_at은 문장 실행
        # 시각(`clock_timestamp()`)이라 보통 메시지마다 다르지만 유일성은 보장되지 않으므로, 같은
        # 값이어도 화면 순서와 같은 한 메시지가 골라지게 id로 동점을 끊는다.
        user_message = await db.scalar(
            select(ChatMessage.content)
            .where(
                ChatMessage.chat_room_id == room.id,
                ChatMessage.role == ChatMessageRole.USER,
                tuple_(ChatMessage.created_at, ChatMessage.id) < (message.created_at, message.id),
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        created = datetime.now(UTC)
        report = ChatMessageReport(
            reporter_user_id=user_id,
            chat_room_id=room.id,
            chat_message_id=message.id,
            reason=body.reason,
            note=body.note,
            status=ReportStatus.PENDING,
            created_at=created,
            evidence_response=message.content,
            evidence_user_message=user_message,
            evidence_expires_at=created + timedelta(days=90),
        )
        db.add(report)
        await db.commit()
    return ChatMessageReportResponse(report_id=report.id, status=report.status)


def _evidence(report: ChatMessageReport) -> ChatMessageReportEvidenceResponse:
    available = report.evidence_purged_at is None and datetime.now(UTC) < report.evidence_expires_at
    return ChatMessageReportEvidenceResponse(
        expires_at=report.evidence_expires_at,
        available=available,
        response=report.evidence_response if available else None,
        user_message=report.evidence_user_message if available else None,
    )


def _detail(report: ChatMessageReport) -> AdminChatMessageReportDetailResponse:
    return AdminChatMessageReportDetailResponse(
        id=report.id,
        reporter_user_id=report.reporter_user_id,
        chat_room_id=report.chat_room_id,
        chat_message_id=report.chat_message_id,
        reason=report.reason,
        note=report.note,
        status=report.status,
        created_at=report.created_at,
        resolved_by_admin_id=report.resolved_by_admin_id,
        resolved_at=report.resolved_at,
        evidence=_evidence(report),
    )


async def _get_report(db: AsyncSession, report_id: uuid.UUID) -> ChatMessageReport:
    report = await db.get(ChatMessageReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat message report not found")
    return report


@router.get("/admin/chat-message-reports")
async def list_chat_message_reports(
    page: int = Query(1, ge=1),
    status_filter: ReportStatus | None = Query(None, alias="status"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminChatMessageReportListResponse:
    filters = [ChatMessageReport.status == status_filter] if status_filter is not None else []
    total = (await db.scalar(select(func.count()).select_from(ChatMessageReport).where(*filters))) or 0
    reports = (
        await db.scalars(
            select(ChatMessageReport)
            .where(*filters)
            .order_by(ChatMessageReport.created_at.desc(), ChatMessageReport.id.desc())
            .offset((page - 1) * _ADMIN_PAGE_SIZE)
            .limit(_ADMIN_PAGE_SIZE)
        )
    ).all()
    items = [
        AdminChatMessageReportListItem(
            id=report.id,
            reporter_user_id=report.reporter_user_id,
            chat_room_id=report.chat_room_id,
            chat_message_id=report.chat_message_id,
            reason=report.reason,
            status=report.status,
            created_at=report.created_at,
            evidence_expires_at=report.evidence_expires_at,
            evidence_available=_evidence(report).available,
        )
        for report in reports
    ]
    return AdminChatMessageReportListResponse(
        items=items, page=page, total_count=total, total_pages=-(-total // _ADMIN_PAGE_SIZE) if total else 0
    )


@router.get("/admin/chat-message-reports/{report_id}")
async def get_chat_message_report(
    report_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminChatMessageReportDetailResponse:
    return _detail(await _get_report(db, report_id))


@router.post("/admin/chat-message-reports/{report_id}/actions")
async def act_on_chat_message_report(
    report_id: uuid.UUID,
    body: AdminChatMessageReportActionRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminChatMessageReportDetailResponse:
    """이미 처리된 신고도 다시 처리할 수 있다(댓글 신고와 같다) — 상태·처리자·시각을 덮어쓰고
    감사 로그를 한 줄 더 남긴다."""
    reason = body.admin_comment.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="운영 조치 사유를 입력해주세요.")
    report = await _get_report(db, report_id)
    report.status = ReportStatus.REJECTED if body.action == "reject" else ReportStatus.RESOLVED
    report.resolved_at = datetime.now(UTC)
    report.resolved_by_admin_id = admin_id
    # 방이 지워져 `chat_room_id`가 비어도 누가 낸 신고였는지는 `target_user_id`(신고자 = 방
    # 소유자)로 남는다 — 어드민 채팅 열람 로그와 같은 짝이다.
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="chat-report-reject" if body.action == "reject" else "chat-report-resolve",
        target_user_id=report.reporter_user_id,
        target_chat_room_id=report.chat_room_id,
        reason_category=report.reason,
        reason_text=reason,
    )
    await db.commit()
    return _detail(report)
