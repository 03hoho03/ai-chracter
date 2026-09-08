import uuid
from datetime import timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.core.security import hash_password
from api.db.models import AdminActionLog, AdminUser
from factories import _make_user


def _make_admin(**overrides: object) -> AdminUser:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password_hash": hash_password("adminpassword123"),
    }
    defaults.update(overrides)
    return AdminUser(**defaults)


async def test_record_admin_action_does_not_commit(db_session: AsyncSession) -> None:
    """TS-7 — `db.add()`만 하고 커밋하지 않는다. 호출자가 롤백하면 행이 사라져야
    호출자의 트랜잭션에 로그가 얹혀 있다는 계약이 실제로 지켜지는 것이다."""
    admin = _make_admin()
    db_session.add(admin)
    await db_session.flush()

    await record_admin_action(db_session, admin_id=admin.id, action_type="legal-publish")
    await db_session.flush()  # INSERT를 실제로 내보내되 아직 commit하지 않는다.
    await db_session.rollback()

    count = (
        await db_session.execute(sa.select(sa.func.count()).select_from(AdminActionLog))
    ).scalar_one()
    assert count == 0


async def test_record_admin_action_partial_target_succeeds(db_session: AsyncSession) -> None:
    """경고/정지처럼 대상이 유저뿐인 조치는 target_user_id만 채우고 나머지 두 FK는
    null로 남아야 한다."""
    admin = _make_admin()
    user = _make_user()
    db_session.add_all([admin, user])
    await db_session.flush()

    await record_admin_action(
        db_session,
        admin_id=admin.id,
        action_type="user-warn",
        target_user_id=user.id,
        reason_category="hate",
        reason_text="혐오 표현 신고 누적",
    )
    await db_session.commit()

    log = (await db_session.execute(sa.select(AdminActionLog))).scalars().one()
    assert log.admin_id == admin.id
    assert log.action_type == "user-warn"
    assert log.target_user_id == user.id
    assert log.target_content_id is None
    assert log.target_chat_room_id is None
    assert log.reason_category == "hate"
    assert log.reason_text == "혐오 표현 신고 누적"


async def test_record_admin_action_all_targets_null_succeeds(db_session: AsyncSession) -> None:
    """세 타깃 FK가 전부 null인 행도 허용돼야 한다(예: 약관 게시처럼 유저/콘텐츠/채팅방
    어느 것도 대상이 아닌 조치). `reason_category` 생략 시 기본값 빈 문자열도 함께 확인한다."""
    admin = _make_admin()
    db_session.add(admin)
    await db_session.flush()

    await record_admin_action(db_session, admin_id=admin.id, action_type="legal-publish")
    await db_session.commit()

    log = (await db_session.execute(sa.select(AdminActionLog))).scalars().one()
    assert log.target_user_id is None
    assert log.target_content_id is None
    assert log.target_chat_room_id is None
    assert log.reason_category is None
    assert log.reason_text == ""
