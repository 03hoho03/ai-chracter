import uuid
from datetime import timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    AdminUser,
    Appeal,
    AppealStatus,
    AppealTargetKind,
    Content,
    ContentTarget,
    ContentType,
    ContentVisibility,
    Genre,
    ModerationAction,
    ModerationActionType,
    ModerationStatus,
    Notification,
    Report,
    ReportReasonCategory,
    ReportStatus,
    User,
)
from factories import _make_user


def _make_admin(**overrides: object) -> AdminUser:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password_hash": "hashed",
    }
    defaults.update(overrides)
    return AdminUser(**defaults)


async def _make_content(db_session: AsyncSession, user: User) -> Content:
    genre_result = await db_session.execute(sa.select(Genre).limit(1))
    genre = genre_result.scalar_one()

    content = Content(
        type=ContentType.CHARACTER,
        creator_user_id=user.id,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    return content


async def test_report_attaches_to_reporter_and_content(db_session: AsyncSession) -> None:
    reporter = _make_user()
    db_session.add(reporter)
    await db_session.flush()
    content = await _make_content(db_session, reporter)

    report = Report(
        reporter_user_id=reporter.id,
        content_id=content.id,
        reason_category=ReportReasonCategory.SPAM,
        status=ReportStatus.PENDING,
    )
    db_session.add(report)
    await db_session.flush()

    assert report.resolved_by_admin_id is None
    assert report.resolved_at is None


async def test_moderation_action_attaches_to_content_and_admin(db_session: AsyncSession) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    content = await _make_content(db_session, creator)
    admin = _make_admin()
    db_session.add(admin)
    await db_session.flush()

    action = ModerationAction(
        content_id=content.id, admin_id=admin.id, action=ModerationActionType.RESTRICT
    )
    db_session.add(action)
    await db_session.flush()

    assert action.action == ModerationActionType.RESTRICT


async def test_notification_attaches_to_moderation_action_and_defaults_unread(
    db_session: AsyncSession,
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    content = await _make_content(db_session, creator)
    admin = _make_admin()
    db_session.add(admin)
    await db_session.flush()
    action = ModerationAction(
        content_id=content.id, admin_id=admin.id, action=ModerationActionType.RESTRICT
    )
    db_session.add(action)
    await db_session.flush()

    notification = Notification(
        user_id=creator.id,
        content_id=content.id,
        action_id=action.id,
        reason_category="adult",
        admin_comment="부적절한 콘텐츠로 판단되어 이용제한 처리되었습니다.",
    )
    db_session.add(notification)
    await db_session.flush()

    assert notification.type == "moderation-action"
    assert notification.read is False


async def test_appeal_target_id_accepts_arbitrary_uuid_without_fk(db_session: AsyncSession) -> None:
    """target_id는 target_kind에 따라 발행거부 이력 또는 moderation_actions.id를 가리키는
    다형 참조라 DB FK가 없다 — 어떤 테이블에도 존재하지 않는 UUID도 그대로 저장된다."""

    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    appeal = Appeal(
        user_id=user.id,
        target_kind=AppealTargetKind.MODERATION_ACTION,
        target_id=uuid.uuid4(),
        reason_text="이의 있습니다.",
        status=AppealStatus.PENDING,
    )
    db_session.add(appeal)
    await db_session.flush()

    assert appeal.verdict is None
    assert appeal.resolved_at is None
