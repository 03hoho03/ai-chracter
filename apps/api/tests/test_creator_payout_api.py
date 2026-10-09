"""크리에이터 정산 신청(회원)과 신청 처리(어드민): 게이트 순서, 승인의 소급 확정과 컷, 재승인, 승인 취소, 알림.

시각: 한 테스트는 한 트랜잭션이라 `now()` 가 고정이다. 승인의 컷은 그 `now()` − 5분이고, 차감 시각은 사용처 행의
`created_at` 을 직접 고쳐 컷 앞뒤에 놓는다. 결제는 모두 1클로버 = 3원이라 비율 500bps 에서 유료 22클로버 = 3원이다.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import config
from api.core.config import settings
from api.creator_payout.router import APPLICATION_RECEIVED_MESSAGE
from api.creator_payout.settlement import confirm_window
from api.db.models.auth import User
from api.db.models.content import Content, ContentVersion
from api.db.models.creator_payout import (
    CreatorPayoutApplication,
    CreatorPayoutConfirmation,
    CreatorPayoutConfirmationLine,
)
from api.db.models.moderation import AdminActionLog
from api.legal.dependencies import _latest_published_legal_version
from api.main import app
from api.payments.notify import get_payment_notifier
from factories import (
    _create_admin,
    _get_genre,
    _login_as,
    _login_as_admin,
    _make_draft_content,
    _make_player,
    _make_published_character,
    _make_user,
    _use,
)

APPROVAL_CUT_LAG = timedelta(minutes=5)


# ── 셋업 ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _creator_payout_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """정산은 스위치와 본인인증 설정이 모두 있어야 켜진다. 로컬 `.env` 의 값이 아니라 테스트가 정한다."""
    monkeypatch.setattr(settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "creator_payout_enabled", True)
    monkeypatch.setattr(settings, "creator_payout_retro_days", 90)
    monkeypatch.setattr(settings, "creator_payout_rate_bps", 500)


@pytest.fixture(autouse=True)
def notifications() -> Iterator[list[str]]:
    sent: list[str] = []

    async def record(message: str) -> None:
        sent.append(message)

    app.dependency_overrides[get_payment_notifier] = lambda: record
    yield sent
    app.dependency_overrides.pop(get_payment_notifier, None)


async def _publish(db: AsyncSession, content: Content) -> None:
    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db.add(version)
    await db.flush()
    content.current_published_version_id = version.id
    await db.flush()


def _verified(**overrides: object) -> User:
    """본인인증을 마친 성인(2000-01-01생)."""
    values: dict[str, object] = {
        "identity_ci_hmac": uuid.uuid4().hex,
        "identity_verified_at": datetime.now(UTC),
        "birth_date": date(2000, 1, 1),
    }
    values.update(overrides)
    return _make_user(**values)


async def _creator(db: AsyncSession) -> tuple[User, Content]:
    """신청 자격을 다 갖춘 작가와 그 발행 작품."""
    creator = _verified()
    db.add(creator)
    await db.flush()
    content = await _make_draft_content(db, creator_user_id=creator.id)
    await _publish(db, content)
    return creator, content


async def _apply(client: httpx.AsyncClient, user: User) -> None:
    await _login_as(client, user.id)
    resp = await client.post("/me/creator-payout/application", json={"agreed": True})
    assert resp.status_code == 201, resp.text


async def _application_id(db: AsyncSession, user: User, status: str) -> uuid.UUID:
    application_id = await db.scalar(
        select(CreatorPayoutApplication.id).where(
            CreatorPayoutApplication.user_id == user.id, CreatorPayoutApplication.status == status
        )
    )
    assert application_id is not None
    return application_id


async def _as_admin(client: httpx.AsyncClient, db: AsyncSession) -> uuid.UUID:
    admin = await _create_admin(db)
    await _login_as_admin(client, admin)
    admin_id = admin["id"]
    assert isinstance(admin_id, uuid.UUID)
    return admin_id


async def _transaction_now(db: AsyncSession) -> datetime:
    now = await db.scalar(select(func.now()))
    assert now is not None
    return now


async def _approve(client: httpx.AsyncClient, application_id: uuid.UUID) -> httpx.Response:
    return await client.post(f"/admin/creator-payout/applications/{application_id}/approve", json={})


# ── 신청: 게이트 순서 ──────────────────────────────────────────────────────────
async def test_apply_gates_refuse_in_order(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    notifications: list[str],
) -> None:
    """앞 게이트를 하나씩 풀어 가며 다음 게이트의 거절을 본다. 각 단계의 회원은 그 뒤 게이트에도 모두 걸린 상태다 — 순서가
    바뀌면 그 단계의 응답이 달라진다. 정지는 Redis 표시 없이 DB 에만 있어 세션 확인을 지나고 DB 의 회원 상태가 막는다."""
    today = datetime.now(UTC).date()
    user = _make_user(suspended_at=datetime.now(UTC), birth_date=date(today.year - 18, 1, 1))
    db_session.add(user)
    await db_session.flush()
    content = await _make_draft_content(db_session, creator_user_id=user.id)
    await _login_as(db_client, user.id)

    async def apply() -> tuple[int, object]:
        resp = await db_client.post("/me/creator-payout/application", json={"agreed": True})
        return resp.status_code, resp.json()["detail"] if resp.status_code != 201 else resp.json()

    monkeypatch.setattr(settings, "creator_payout_enabled", False)
    assert await apply() == (503, {"code": "CREATOR_PAYOUT_UNAVAILABLE"})
    monkeypatch.setattr(settings, "creator_payout_enabled", True)
    assert await apply() == (403, "Account suspended")
    user.suspended_at = None
    await db_session.flush()
    assert await apply() == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})
    user.identity_ci_hmac = uuid.uuid4().hex
    user.identity_verified_at = datetime.now(UTC)
    await db_session.flush()
    assert await apply() == (403, {"code": "CREATOR_PAYOUT_AGE_RESTRICTED"})
    user.birth_date = date(today.year - 19, today.month, min(today.day, 28))
    await db_session.flush()
    assert await apply() == (422, {"code": "CREATOR_PAYOUT_NO_PUBLISHED_WORK"})
    await _publish(db_session, content)
    assert await apply() == (201, {"status": "pending"})
    assert await apply() == (409, {"code": "CREATOR_PAYOUT_ALREADY_APPLIED"})

    application = await db_session.scalar(
        select(CreatorPayoutApplication).where(CreatorPayoutApplication.user_id == user.id)
    )
    assert application is not None
    assert (application.status, application.privacy_version) == (
        "pending",
        await _latest_published_legal_version(db_session, "privacy"),
    )
    assert notifications == [APPLICATION_RECEIVED_MESSAGE]


async def test_withdrawn_member_cannot_apply(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    creator, _ = await _creator(db_session)
    await _login_as(db_client, creator.id)
    creator.deleted_at = datetime.now(UTC)
    await db_session.flush()

    resp = await db_client.post("/me/creator-payout/application", json={"agreed": True})

    assert resp.status_code == 401


async def test_application_notice_carries_no_member_identifier(
    db_client: httpx.AsyncClient, db_session: AsyncSession, notifications: list[str]
) -> None:
    """알림은 외부 채널로 나간다 — 회원 id·닉네임·신청 id 를 조각도 싣지 않는다."""
    creator, _ = await _creator(db_session)
    creator.nickname = "정산신청자닉"
    await db_session.flush()

    await _apply(db_client, creator)

    application_id = await _application_id(db_session, creator, "pending")
    [message] = notifications
    for identifier in (str(creator.id), creator.id.hex, str(creator.id)[:8], "정산신청자닉", str(application_id)[:8]):
        assert identifier not in message


async def test_apply_requires_agreement(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    creator, _ = await _creator(db_session)
    await _login_as(db_client, creator.id)

    resp = await db_client.post("/me/creator-payout/application", json={"agreed": False})

    assert resp.status_code == 422


# ── 조회 ─────────────────────────────────────────────────────────────────
async def test_get_is_closed_while_switched_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator, _ = await _creator(db_session)
    await _login_as(db_client, creator.id)
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "")

    resp = await db_client.get("/me/creator-payout")

    assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "CREATOR_PAYOUT_UNAVAILABLE"})


async def test_get_shows_eligibility_without_refusing(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """인증·나이·발행 작품이 모자라도 거절하지 않고 신청과 같은 판정으로 보여 준다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.get("/me/creator-payout")

    assert resp.status_code == 200
    assert resp.json() == {
        "application": None,
        "eligibility": {"identityVerified": False, "adult": False, "hasPublishedWork": False, "suspended": False},
        "everApproved": False,
        "balanceKrw": 0,
        "rateBps": 500,
    }


async def test_get_carries_the_configured_rate(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """적립 비율은 서버 설정값 그대로 실린다 — 웹은 이 값으로 비율을 말하므로 설정을 바꾸면 문구도 따라 바뀐다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    monkeypatch.setattr(settings, "creator_payout_rate_bps", 750)

    resp = await db_client.get("/me/creator-payout")

    assert resp.status_code == 200
    assert resp.json()["rateBps"] == 750


# ── 승인과 소급 ────────────────────────────────────────────────────────────
async def test_first_approval_confirms_retro_window_ending_five_minutes_before(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """컷 C = 승인 트랜잭션 시작 − 5분. 소급은 [C − 90일, C) 를 한 번 확정하고, 승인 4분 전(컷 뒤)에 시작한 차감은 소급이
    아니라 월 확정 구간 [C, …) 에 든다 — 컷이 승인 시각이면 그 차감은 소급에 들어간다."""
    creator, content = await _creator(db_session)
    player = await _make_player(db_session, amount_krw=3_300, paid=1_100)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    admin_id = await _as_admin(db_client, db_session)
    now = await _transaction_now(db_session)
    cut = now - APPROVAL_CUT_LAG
    retro_start = cut - timedelta(days=90)
    await _use(db_session, player, content, 220, cut - timedelta(seconds=1))
    await _use(db_session, player, content, 22, retro_start)
    await _use(db_session, player, content, 44, retro_start - timedelta(seconds=1))
    await _use(db_session, player, content, 22, now - timedelta(minutes=4))

    resp = await _approve(db_client, application_id)

    # 소급 = (220 + 22) × 3/22 = 33원.
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"retroAmountKrw": 33}
    application = await db_session.get(CreatorPayoutApplication, application_id, populate_existing=True)
    assert application is not None
    assert (application.status, application.decided_by_admin_id, application.decided_at) == ("approved", admin_id, now)
    assert (application.accrual_start_at, application.monthly_from_at) == (retro_start, cut)
    [retro] = (
        await db_session.scalars(select(CreatorPayoutConfirmation).where(CreatorPayoutConfirmation.user_id == creator.id))
    ).all()
    assert (retro.kind, retro.window_start, retro.window_end, retro.gross_units) == ("retro", retro_start, cut, 242)
    monthly = await confirm_window(
        db_session,
        creator_id=creator.id,
        kind="monthly",
        period_month=date(2099, 1, 1),
        windows=[(cut, now + timedelta(days=1))],
        cancel_adjust_month=(now, now + timedelta(days=1)),
    )
    assert monthly is not None and monthly.gross_units == 22
    actions = (
        await db_session.scalars(select(AdminActionLog.action_type).where(AdminActionLog.target_user_id == creator.id))
    ).all()
    assert actions == ["user-creator-payout-approve"]


async def test_retro_window_follows_the_retro_days_setting(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """소급 창과 적립 시작이 같은 설정값에서 나온다 — 30일이면 31일 전 차감은 소급에 들지 않는다."""
    monkeypatch.setattr(settings, "creator_payout_retro_days", 30)
    creator, content = await _creator(db_session)
    player = await _make_player(db_session, amount_krw=3_300, paid=1_100)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    await _as_admin(db_client, db_session)
    cut = await _transaction_now(db_session) - APPROVAL_CUT_LAG
    await _use(db_session, player, content, 22, cut - timedelta(days=29))
    await _use(db_session, player, content, 44, cut - timedelta(days=31))

    resp = await _approve(db_client, application_id)

    assert resp.json() == {"retroAmountKrw": 3}
    application = await db_session.get(CreatorPayoutApplication, application_id, populate_existing=True)
    retro = await db_session.scalar(
        select(CreatorPayoutConfirmation).where(CreatorPayoutConfirmation.user_id == creator.id)
    )
    assert application is not None and retro is not None
    assert application.accrual_start_at == retro.window_start == cut - timedelta(days=30)


async def test_reapproval_after_revoke_starts_at_the_cut_without_retro(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """승인 취소 → 재신청 → 재승인이면 소급 행은 그대로 하나이고, 적립·월 확정 모두 새 컷부터다."""
    creator, _ = await _creator(db_session)
    await _apply(db_client, creator)
    await _as_admin(db_client, db_session)
    first = await _application_id(db_session, creator, "pending")
    assert (await _approve(db_client, first)).status_code == 200
    resp = await db_client.post(
        f"/admin/creator-payout/applications/{first}/revoke", json={"reasonText": "부정 적립 의심"}
    )
    assert resp.status_code == 204
    retro_before = await db_session.scalar(
        select(CreatorPayoutConfirmation).where(CreatorPayoutConfirmation.user_id == creator.id)
    )
    await _apply(db_client, creator)
    second = await _application_id(db_session, creator, "pending")
    await _as_admin(db_client, db_session)

    resp = await _approve(db_client, second)

    assert (resp.status_code, resp.json()) == (200, {"retroAmountKrw": None})
    cut = await _transaction_now(db_session) - APPROVAL_CUT_LAG
    reapproved = await db_session.get(CreatorPayoutApplication, second, populate_existing=True)
    assert reapproved is not None
    assert (reapproved.status, reapproved.accrual_start_at, reapproved.monthly_from_at) == ("approved", cut, cut)
    confirmations = (
        await db_session.scalars(select(CreatorPayoutConfirmation).where(CreatorPayoutConfirmation.user_id == creator.id))
    ).all()
    assert confirmations == [retro_before]


async def test_revoke_stops_accrual_and_keeps_confirmed_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """승인 취소는 그 시각 이후의 적립만 멈춘다 — 소급 행은 남고, 취소 전 차감은 세고 취소 뒤 차감은 세지 않는다. 취소 사유와
    취소 시각은 신청자의 정산 화면 응답에 실리고(승인 시각과 따로), 사유는 감사 로그에도 남는다. 승인된 적이 있다는
    사실(`everApproved`)은 다시 신청해 대기 중이어도 남는다(확정분 지급 영역을 보일지)."""
    creator, content = await _creator(db_session)
    player = await _make_player(db_session, amount_krw=3_300, paid=1_100)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    admin_id = await _as_admin(db_client, db_session)
    now = await _transaction_now(db_session)
    await _use(db_session, player, content, 22, now - timedelta(days=1))
    assert (await _approve(db_client, application_id)).json() == {"retroAmountKrw": 3}
    await _use(db_session, player, content, 44, now - timedelta(minutes=1))
    await _use(db_session, player, content, 88, now + timedelta(minutes=1))
    # 한 테스트 안의 `now()` 는 하나라 승인과 취소 시각이 같아지므로, 승인을 이틀 전으로 옮겨 응답의 두 시각을 가른다.
    approved_at = now - timedelta(days=2)
    await db_session.execute(
        update(CreatorPayoutApplication)
        .where(CreatorPayoutApplication.id == application_id)
        .values(decided_at=approved_at)
    )

    resp = await db_client.post(
        f"/admin/creator-payout/applications/{application_id}/revoke", json={"reasonText": "운영 정책 위반"}
    )

    assert resp.status_code == 204
    application = await db_session.get(CreatorPayoutApplication, application_id, populate_existing=True)
    assert application is not None
    assert (application.status, application.revoked_at, application.revoked_by_admin_id) == ("revoked", now, admin_id)
    [retro] = (
        await db_session.scalars(select(CreatorPayoutConfirmation).where(CreatorPayoutConfirmation.user_id == creator.id))
    ).all()
    assert (retro.kind, retro.amount_krw) == ("retro", 3)
    assert application.monthly_from_at is not None
    monthly = await confirm_window(
        db_session,
        creator_id=creator.id,
        kind="monthly",
        period_month=date(2099, 1, 1),
        windows=[(application.monthly_from_at, now + timedelta(days=1))],
        cancel_adjust_month=(now, now + timedelta(days=1)),
    )
    assert monthly is not None and monthly.gross_units == 44

    reasons = (
        await db_session.execute(
            select(AdminActionLog.action_type, AdminActionLog.reason_text).where(
                AdminActionLog.target_user_id == creator.id
            )
        )
    ).tuples().all()
    assert ("user-creator-payout-revoke", "운영 정책 위반") in reasons

    await _login_as(db_client, creator.id)
    revoked = (await db_client.get("/me/creator-payout")).json()["application"]
    assert (revoked["status"], revoked["decisionReason"]) == ("revoked", "운영 정책 위반")
    assert (datetime.fromisoformat(revoked["revokedAt"]), datetime.fromisoformat(revoked["decidedAt"])) == (
        now,
        approved_at,
    )
    await _apply(db_client, creator)
    body = (await db_client.get("/me/creator-payout")).json()
    assert (body["application"]["status"], body["everApproved"]) == ("pending", True)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        pytest.param({"suspended_at": datetime.now(UTC)}, "suspended", id="suspended"),
        pytest.param({"deleted_at": datetime.now(UTC)}, "withdrawn", id="withdrawn"),
        pytest.param({"identity_verified_at": None, "identity_ci_hmac": None}, "identity_required", id="unverified"),
    ],
)
async def test_approval_rechecks_eligibility(
    db_client: httpx.AsyncClient, db_session: AsyncSession, change: dict[str, object], reason: str
) -> None:
    """신청 뒤 자격이 바뀌었으면 승인하지 않는다. 신청과 같은 판정이라 이유도 같은 이름이다."""
    creator, _ = await _creator(db_session)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    await db_session.execute(update(User).where(User.id == creator.id).values(**change))
    await _as_admin(db_client, db_session)

    resp = await _approve(db_client, application_id)

    assert (resp.status_code, resp.json()["detail"]) == (
        409,
        {"code": "CREATOR_PAYOUT_NOT_ELIGIBLE", "reason": reason},
    )
    assert await db_session.scalar(select(CreatorPayoutConfirmation.id)) is None


async def test_approval_rechecks_published_work(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    creator, content = await _creator(db_session)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    content.current_published_version_id = None
    await db_session.flush()
    await _as_admin(db_client, db_session)

    resp = await _approve(db_client, application_id)

    assert resp.json()["detail"] == {"code": "CREATOR_PAYOUT_NOT_ELIGIBLE", "reason": "no_published_work"}


# ── 거절·상태 충돌 ──────────────────────────────────────────────────────────
async def test_reject_shows_reason_to_applicant_and_allows_reapplying(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator, _ = await _creator(db_session)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    await _as_admin(db_client, db_session)

    resp = await db_client.post(
        f"/admin/creator-payout/applications/{application_id}/reject", json={"reasonText": "발행 작품이 비어 있어요"}
    )

    assert resp.status_code == 204
    await _login_as(db_client, creator.id)
    application = (await db_client.get("/me/creator-payout")).json()["application"]
    assert (application["status"], application["decisionReason"]) == ("rejected", "발행 작품이 비어 있어요")
    assert application["decidedAt"] is not None
    actions = (
        await db_session.scalars(select(AdminActionLog.action_type).where(AdminActionLog.target_user_id == creator.id))
    ).all()
    assert actions == ["user-creator-payout-reject"]
    await _apply(db_client, creator)


@pytest.mark.parametrize("action", ["reject", "revoke"])
async def test_reject_and_revoke_require_a_reason(
    db_client: httpx.AsyncClient, db_session: AsyncSession, action: str
) -> None:
    creator, _ = await _creator(db_session)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    await _as_admin(db_client, db_session)

    resp = await db_client.post(
        f"/admin/creator-payout/applications/{application_id}/{action}", json={"reasonText": "  "}
    )

    assert resp.status_code == 422


async def test_decisions_refuse_the_wrong_state(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    creator, _ = await _creator(db_session)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    await _as_admin(db_client, db_session)
    base = f"/admin/creator-payout/applications/{application_id}"

    revoke_pending = await db_client.post(f"{base}/revoke", json={"reasonText": "사유"})
    assert (await _approve(db_client, application_id)).status_code == 200
    approve_again = await _approve(db_client, application_id)
    reject_approved = await db_client.post(f"{base}/reject", json={"reasonText": "사유"})

    assert revoke_pending.json()["detail"] == {"code": "CREATOR_PAYOUT_APPLICATION_NOT_APPROVED"}
    assert approve_again.json()["detail"] == {"code": "CREATOR_PAYOUT_APPLICATION_NOT_PENDING"}
    assert reject_approved.json()["detail"] == {"code": "CREATOR_PAYOUT_APPLICATION_NOT_PENDING"}
    assert {revoke_pending.status_code, approve_again.status_code, reject_approved.status_code} == {409}
    missing = await _approve(db_client, uuid.uuid4())
    assert (missing.status_code, missing.json()["detail"]) == (404, {"code": "CREATOR_PAYOUT_APPLICATION_NOT_FOUND"})


async def test_withdrawn_applicant_can_still_be_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴 회원의 대기 신청도 거절해 큐에서 뺄 수 있어야 한다(승인만 막는다)."""
    creator, _ = await _creator(db_session)
    await _apply(db_client, creator)
    application_id = await _application_id(db_session, creator, "pending")
    creator.deleted_at = datetime.now(UTC)
    await db_session.flush()
    await _as_admin(db_client, db_session)

    resp = await db_client.post(
        f"/admin/creator-payout/applications/{application_id}/reject", json={"reasonText": "탈퇴"}
    )

    assert resp.status_code == 204


async def test_admin_queue_stays_open_while_switched_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치를 끈 뒤에도 끄기 전에 들어온 신청을 거절하고, 승인을 취소할 수 있어야 한다."""
    pending_creator, _ = await _creator(db_session)
    approved_creator, _ = await _creator(db_session)
    await _apply(db_client, pending_creator)
    await _apply(db_client, approved_creator)
    await _as_admin(db_client, db_session)
    approved_id = await _application_id(db_session, approved_creator, "pending")
    assert (await _approve(db_client, approved_id)).status_code == 200
    pending_id = await _application_id(db_session, pending_creator, "pending")
    monkeypatch.setattr(settings, "creator_payout_enabled", False)

    listed = await db_client.get("/admin/creator-payout/applications")
    rejected = await db_client.post(
        f"/admin/creator-payout/applications/{pending_id}/reject", json={"reasonText": "정산 종료"}
    )
    revoked = await db_client.post(
        f"/admin/creator-payout/applications/{approved_id}/revoke", json={"reasonText": "정산 종료"}
    )

    assert (listed.status_code, listed.json()["totalCount"]) == (200, 1)
    assert (rejected.status_code, revoked.status_code) == (204, 204)


# ── 어드민 목록 ────────────────────────────────────────────────────────────
async def test_admin_queue_lists_pending_applications_with_current_eligibility(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator, _ = await _creator(db_session)
    creator.nickname = "작가"
    leaver, _ = await _creator(db_session)
    await _apply(db_client, creator)
    await _apply(db_client, leaver)
    await db_session.execute(
        update(CreatorPayoutApplication)
        .where(CreatorPayoutApplication.user_id == leaver.id)
        .values(applied_at=datetime.now(UTC) + timedelta(seconds=1))
    )
    leaver.deleted_at = datetime.now(UTC)
    await db_session.flush()

    assert (await db_client.get("/admin/creator-payout/applications")).status_code == 401
    await _as_admin(db_client, db_session)
    resp = await db_client.get("/admin/creator-payout/applications")
    approved = await db_client.get("/admin/creator-payout/applications", params={"status": "approved"})

    assert resp.status_code == 200
    body = resp.json()
    assert (body["totalCount"], body["page"], body["totalPages"]) == (2, 1, 1)
    first, second = body["items"]
    assert (first["userId"], first["nickname"], first["status"]) == (str(creator.id), "작가", "pending")
    assert first["eligibility"] == {
        "identityVerified": True,
        "adult": True,
        "publishedCount": 1,
        "suspended": False,
        "withdrawn": False,
    }
    assert (second["userId"], second["nickname"], second["eligibility"]["withdrawn"]) == (str(leaver.id), None, True)
    assert approved.json()["items"] == []


# ── 적립 잔액·확정 내역 ────────────────────────────────────────────────────────
def _confirmation(
    user: User,
    *,
    amount_krw: int,
    window_end: datetime,
    kind: Literal["retro", "monthly"] = "monthly",
) -> CreatorPayoutConfirmation:
    return CreatorPayoutConfirmation(
        user_id=user.id,
        kind=kind,
        period_month=None if kind == "retro" else window_end.date().replace(day=1),
        window_start=window_end - timedelta(days=1),
        window_end=window_end,
        gross_units=0,
        refunded_units=0,
        rate_bps=500,
        exact_krw=Decimal(amount_krw),
        amount_krw=amount_krw,
    )


async def test_balance_is_the_sum_of_confirmed_amounts(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """소급 5원 + 10월 10원 + 11월 −8원(확정 뒤 결제 취소 조정). 다른 사람의 확정은 섞이지 않는다."""
    creator, _ = await _creator(db_session)
    other, _ = await _creator(db_session)
    db_session.add_all(
        [
            _confirmation(creator, amount_krw=5, window_end=datetime(2026, 9, 20, tzinfo=UTC), kind="retro"),
            _confirmation(creator, amount_krw=10, window_end=datetime(2026, 10, 31, tzinfo=UTC)),
            _confirmation(creator, amount_krw=-8, window_end=datetime(2026, 11, 30, tzinfo=UTC)),
            _confirmation(other, amount_krw=100, window_end=datetime(2026, 10, 31, tzinfo=UTC)),
        ]
    )
    await db_session.flush()
    await _login_as(db_client, creator.id)

    resp = await db_client.get("/me/creator-payout")

    assert resp.json()["balanceKrw"] == 7


async def test_statements_merge_payment_lines_by_content(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """한 작품을 결제 둘로 쓴 줄은 작품 하나로 합치고 원 미만을 합친 뒤 버린다(1.9 + 2.2 = 4.1 → 4원, 줄마다 버리면 3원).
    조정만 있는 작품은 순사용 0, 조정·금액이 음수(−1.5 → −1원)다. 작품 이름은 마지막 발행본의 것이다."""
    creator, _ = await _creator(db_session)
    genre = await _get_genre(db_session)
    titled = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    untitled = await _make_draft_content(db_session, creator_user_id=creator.id)
    player_a = await _make_player(db_session, amount_krw=9_900, paid=3_300)
    player_b = await _make_player(db_session, amount_krw=9_900, paid=3_300)
    confirmation = _confirmation(creator, amount_krw=2, window_end=datetime(2026, 10, 31, 15, tzinfo=UTC))
    db_session.add(confirmation)
    await db_session.flush()
    db_session.add_all(
        [
            CreatorPayoutConfirmationLine(
                confirmation_id=confirmation.id,
                content_id=titled.id,
                payment_id=player_a.payment.id,
                net_units=14,
                cancel_adjust_krw=Decimal(0),
                exact_krw=Decimal("1.9"),
            ),
            CreatorPayoutConfirmationLine(
                confirmation_id=confirmation.id,
                content_id=titled.id,
                payment_id=player_b.payment.id,
                net_units=16,
                cancel_adjust_krw=Decimal(0),
                exact_krw=Decimal("2.2"),
            ),
            CreatorPayoutConfirmationLine(
                confirmation_id=confirmation.id,
                content_id=untitled.id,
                payment_id=player_a.payment.id,
                net_units=0,
                cancel_adjust_krw=Decimal("-1.5"),
                exact_krw=Decimal("-1.5"),
            ),
        ]
    )
    await db_session.flush()
    await _login_as(db_client, creator.id)

    resp = await db_client.get("/me/creator-payout/statements")

    assert resp.status_code == 200
    assert resp.json() == {
        "items": [
            {
                "kind": "monthly",
                "periodMonth": "2026-10-01",
                "windowStart": "2026-10-30T15:00:00Z",
                "windowEnd": "2026-10-31T15:00:00Z",
                "grossUnits": 0,
                "refundedUnits": 0,
                "amountKrw": 2,
                "lines": [
                    {
                        "contentId": str(titled.id),
                        "contentTitle": "캐릭터",
                        "netUnits": 30,
                        "cancelAdjustKrw": 0,
                        "amountKrw": 4,
                    },
                    {
                        "contentId": str(untitled.id),
                        "contentTitle": "",
                        "netUnits": 0,
                        "cancelAdjustKrw": -1,
                        "amountKrw": -1,
                    },
                ],
            }
        ],
        "nextCursor": None,
    }


async def test_statements_page_newest_first(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """21개 → 첫 쪽 20개(가장 늦은 끝부터)와 커서, 둘째 쪽에 가장 이른 하나. 깨진 커서는 422."""
    creator, _ = await _creator(db_session)
    db_session.add_all(
        [
            _confirmation(creator, amount_krw=index, window_end=datetime(2025, 1, 15, tzinfo=UTC) + timedelta(days=31 * index))
            for index in range(21)
        ]
    )
    await db_session.flush()
    await _login_as(db_client, creator.id)

    first = (await db_client.get("/me/creator-payout/statements")).json()
    second = (
        await db_client.get("/me/creator-payout/statements", params={"cursor": first["nextCursor"]})
    ).json()
    broken = await db_client.get("/me/creator-payout/statements", params={"cursor": "not-a-cursor"})

    assert [item["amountKrw"] for item in first["items"]] == list(range(20, 0, -1))
    assert ([item["amountKrw"] for item in second["items"]], second["nextCursor"]) == ([0], None)
    assert (broken.status_code, broken.json()["detail"]) == (422, {"code": "CREATOR_PAYOUT_CURSOR_INVALID"})


async def test_statements_are_closed_while_switched_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator, _ = await _creator(db_session)
    await _login_as(db_client, creator.id)
    monkeypatch.setattr(settings, "creator_payout_enabled", False)

    resp = await db_client.get("/me/creator-payout/statements")

    assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "CREATOR_PAYOUT_UNAVAILABLE"})


# ── 기능 목록·설정 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("enabled", [True, False])
async def test_me_lists_creator_payout_only_while_active(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    monkeypatch.setattr(settings, "creator_payout_enabled", enabled)

    resp = await db_client.get("/me")

    assert ("creator_payout" in resp.json()["enabledFeatures"]) is enabled


def test_creator_payout_switch_reads_an_empty_value_as_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATOR_PAYOUT_ENABLED", "")
    assert config.Settings().creator_payout_enabled is False
