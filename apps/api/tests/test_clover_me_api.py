"""`/me/clover` 잔액 조회·차감 확인 경로와 탈퇴 시 잔액 소멸.

🔴 시간을 얼리지 않는다 — 이 저장소에 `freezegun`·`time-machine`이 0건이라 KST 경계 검증은
`clover_spend_confirmed_on` 컬럼에 리터럴 날짜를 넣어 확인한다(`core/clover.py`의
`kst_today(now)`가 `now`를 인자로 받는 것과 같은 이유).
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover.router import _expiring_soon
from api.core.clover import grant, kst_today
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot
from factories import _login_as, _make_user


async def _logged_in(
    db_client: httpx.AsyncClient, db_session: AsyncSession, **overrides: object
) -> User:
    user = _make_user(**overrides)
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


async def _ledger_kinds(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """`id`가 uuid4라 정렬은 삽입 순서가 아니다 — 순서가 아니라 **내용**으로 비교한다."""
    rows = (await db.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))).all()
    return sorted(row.kind for row in rows)


async def _balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db.scalar(select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return balance


# ── 잔액 조회 ────────────────────────────────────────────────────────────────
async def test_balance_reports_flags_for_a_fresh_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in(db_client, db_session, clover_balance=30)

    resp = await db_client.get("/me/clover")

    assert resp.status_code == 200
    assert resp.json() == {
        "balance": 30,
        "spendConfirmedToday": False,
        "paidBalance": 0,
        "expiringSoon": None,
    }


async def test_balance_flag_flips_once_today_is_recorded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """오늘(KST) 확인을 남기면 `spendConfirmedToday`가 참이 된다 — 날짜 비교를 빼고 상수를 돌려주면 빨개진다."""
    today = kst_today(datetime.now(UTC))
    await _logged_in(db_client, db_session, clover_balance=30, clover_spend_confirmed_on=today)

    resp = await db_client.get("/me/clover")

    assert resp.json()["spendConfirmedToday"] is True


async def test_balance_read_does_not_grant(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 잔액 조회는 지급하지 않는다 — GET에 부작용을 두지 않는다. 조회만으로 지급되면 빨개진다."""
    user = await _logged_in(db_client, db_session)

    await db_client.get("/me/clover")

    assert await _balance(db_session, user.id) == 0
    assert await _ledger_kinds(db_session, user.id) == []


# ── expiringSoon ─────────────────────────────────────────────────────
async def test_expiring_soon_is_null_when_no_lot_has_an_expiry(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in(db_client, db_session, clover_balance=30)
    db_session.add(
        CloverLot(user_id=user.id, granted_amount=30, remaining=30, expires_at=None, kind="legacy_balance")
    )
    await db_session.commit()

    resp = await db_client.get("/me/clover")

    assert resp.json()["expiringSoon"] is None


async def test_expiring_soon_reports_the_soonest_bucket_and_ignores_the_later_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """가장 임박한 묶음만 보고한다 — 더 늦게 만료되는 로트는 무시한다.

    빨개지는 조건: 임박 순 정렬 없이 아무 로트나 고르면(또는 전부 합산하면) `amount`가
    30(soon)이 아니라 30+70=100이 되거나 `expiresAt`이 later가 될 수 있다.
    """
    now = datetime.now(UTC)
    user = await _logged_in(db_client, db_session)
    soon_expiry = now + timedelta(days=1)
    later_expiry = now + timedelta(days=5)
    db_session.add_all(
        [
            CloverLot(
                user_id=user.id, granted_amount=30, remaining=30, expires_at=soon_expiry, kind="attendance_grant"
            ),
            CloverLot(
                user_id=user.id, granted_amount=70, remaining=70, expires_at=later_expiry, kind="mission_grant"
            ),
        ]
    )
    await db_session.commit()

    resp = await db_client.get("/me/clover")

    assert resp.json()["expiringSoon"] == {
        "amount": 30,
        "expiresAt": soon_expiry.isoformat().replace("+00:00", "Z"),
    }


async def test_expiring_soon_sums_lots_sharing_the_same_expiry(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    user = await _logged_in(db_client, db_session)
    expiry = now + timedelta(days=2)
    db_session.add_all(
        [
            CloverLot(
                user_id=user.id, granted_amount=10, remaining=10, expires_at=expiry, kind="attendance_grant"
            ),
            CloverLot(
                user_id=user.id, granted_amount=20, remaining=20, expires_at=expiry, kind="mission_grant"
            ),
        ]
    )
    await db_session.commit()

    resp = await db_client.get("/me/clover")

    assert resp.json()["expiringSoon"]["amount"] == 30


async def test_expiring_soon_excludes_lots_that_already_expired(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """배치가 아직 못 지운 이미 만료된 로트(`expires_at <= now`)는 제외한다.

    빨개지는 조건: `expires_at > now` 필터를 빼면 이미 지난 로트가 골라져 음수 D-day가 뜬다.
    """
    now = datetime.now(UTC)
    user = await _logged_in(db_client, db_session)
    db_session.add(
        CloverLot(
            user_id=user.id,
            granted_amount=30,
            remaining=30,
            expires_at=now - timedelta(minutes=1),
            kind="attendance_grant",
        )
    )
    await db_session.commit()

    resp = await db_client.get("/me/clover")

    assert resp.json()["expiringSoon"] is None


async def test_expiring_soon_is_null_when_only_lots_are_more_than_three_days_out(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """임박 임계값은 3일이다.

    빨개지는 조건: 3일 상한 필터가 없으면 7일 남은 로트도 `expiringSoon`을 채워 "곧
    사라진다"는 거짓 신호를 준다.
    """
    now = datetime.now(UTC)
    user = await _logged_in(db_client, db_session)
    db_session.add(
        CloverLot(
            user_id=user.id,
            granted_amount=100,
            remaining=100,
            expires_at=now + timedelta(days=7),
            kind="attendance_grant",
        )
    )
    await db_session.commit()

    resp = await db_client.get("/me/clover")

    assert resp.json()["expiringSoon"] is None


async def test_expiring_soon_threshold_includes_a_lot_expiring_in_exactly_three_days(
    db_session: AsyncSession,
) -> None:
    """경계(정확히 3일 남음)는 **포함**으로 정했다("3일 이내"라는 규칙은
    등호 포함 여부까지는 정하지 않았다. "이내"의 통상 의미(초과가 아님)를 따라 포함 쪽을
    골랐다). `_expiring_soon`에 리터럴 `now`를 직접 주입해 HTTP 왕복의 시각 오차 없이
    경계를 정확히 맞춘다.
    """
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    db_session.add(
        CloverLot(
            user_id=user.id,
            granted_amount=30,
            remaining=30,
            expires_at=now + timedelta(days=3),
            kind="attendance_grant",
        )
    )
    await db_session.commit()

    result = await _expiring_soon(db_session, user_id=user.id, now=now)

    assert result is not None
    assert result.amount == 30


async def test_expiring_soon_threshold_excludes_a_lot_expiring_just_past_three_days(
    db_session: AsyncSession,
) -> None:
    """위 테스트의 반대쪽 경계 — 3일을 조금이라도 넘기면 제외된다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    db_session.add(
        CloverLot(
            user_id=user.id,
            granted_amount=30,
            remaining=30,
            expires_at=now + timedelta(days=3, seconds=1),
            kind="attendance_grant",
        )
    )
    await db_session.commit()

    result = await _expiring_soon(db_session, user_id=user.id, now=now)

    assert result is None


async def test_expiring_soon_excludes_a_lot_that_is_already_exhausted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`remaining = 0`인 소진 로트는 만료 전이어도 대상에서 빠진다.

    빨개지는 조건: `CloverLot.remaining > 0` 필터를 빼면 소진 로트가 더 이른 만료라
    "가장 임박한 묶음"으로 잘못 골라져 `amount`가 어긋난다.
    """
    now = datetime.now(UTC)
    user = await _logged_in(db_client, db_session)
    exhausted_expiry = now + timedelta(days=1)
    remaining_expiry = now + timedelta(days=2)
    db_session.add_all(
        [
            CloverLot(
                user_id=user.id,
                granted_amount=50,
                remaining=0,
                expires_at=exhausted_expiry,
                kind="attendance_grant",
            ),
            CloverLot(
                user_id=user.id,
                granted_amount=20,
                remaining=20,
                expires_at=remaining_expiry,
                kind="mission_grant",
            ),
        ]
    )
    await db_session.commit()

    resp = await db_client.get("/me/clover")

    assert resp.json()["expiringSoon"] == {
        "amount": 20,
        "expiresAt": remaining_expiry.isoformat().replace("+00:00", "Z"),
    }


# ── 소진 확인 ────────────────────────────────────────────────────────────────
async def test_spend_confirmation_records_today_and_repeats_safely(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in(db_client, db_session, clover_balance=30)

    first = await db_client.post("/me/clover/spend-confirmation")
    second = await db_client.post("/me/clover/spend-confirmation")

    assert first.status_code == 204
    assert second.status_code == 204
    stored = await db_session.scalar(
        select(User.clover_spend_confirmed_on).where(User.id == user.id)
    )
    assert stored == kst_today(datetime.now(UTC))
    # 확인은 잔액 변동이 아니다 — 원장에 자리가 없다.
    assert await _ledger_kinds(db_session, user.id) == []


# ── 인증·동의 ────────────────────────────────────────────────────────────────
async def test_clover_routes_require_a_session(db_client: httpx.AsyncClient) -> None:
    assert (await db_client.get("/me/clover")).status_code == 401
    assert (await db_client.post("/me/clover/spend-confirmation")).status_code == 401


async def test_daily_attendance_route_is_gone(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """일일 무료 지급 라우트는 없앴다 — 열어 둔 옛 화면의 버튼은 404를 받고 돈은 움직이지 않는다."""
    user = await _logged_in(db_client, db_session)

    resp = await db_client.post("/me/clover/attendance")

    assert resp.status_code == 404
    assert await _ledger_kinds(db_session, user.id) == []


# ── 탈퇴 시 잔액 소멸 ──────────────────────────────────────────────────
async def test_withdraw_burns_the_balance_and_keeps_the_ledger(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잔액은 0으로 소멸시키고 원장은 남긴다.

    빨개지는 조건: 소멸을 빼면 잔액이 100으로 남는다(탈퇴는 soft delete라 행이 그대로다).
    원장을 지우면 `attendance_grant`가 사라진다.
    """
    user = await _logged_in(db_client, db_session)
    await grant(db_session, user_id=user.id, amount=100, kind="attendance_grant")
    await db_session.commit()

    resp = await db_client.delete("/me")

    assert resp.status_code == 204
    assert await _balance(db_session, user.id) == 0
    # 기존 행이 남고 소멸 행이 더해진다 — 원장은 불변이다.
    assert await _ledger_kinds(db_session, user.id) == ["attendance_grant", "withdrawal_burn"]
    burn = await db_session.scalar(
        select(CloverLedger).where(
            CloverLedger.user_id == user.id, CloverLedger.kind == "withdrawal_burn"
        )
    )
    assert burn is not None
    assert burn.amount == -100
    assert burn.balance_after == 0

    # `grant()`가 만든 로트도 함께 0이 됐다.
    # 유령 로트 금지: 잔액만 0이 되고 로트가 남으면 안 된다.
    lot = await db_session.scalar(select(CloverLot).where(CloverLot.user_id == user.id))
    assert lot is not None
    assert lot.remaining == 0


async def test_withdraw_burns_whatever_the_row_actually_holds(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 소멸은 **남은 걸 없애는 것**이지 "얼마를 쓴다"가 아니다.

    `user`는 탈퇴 라우트 초입에서 로드되고 그 뒤 채팅방·메시지·asset 삭제가 이어진다. 그 창에서
    다른 탭의 차감이 커밋되면 메모리의 잔액은 낡는다 — 여기서는 DB만 40으로 낮추고 ORM
    인스턴스를 100으로 남겨 그 상태를 만든다.

    빨개지는 조건: 소멸을 `spend(amount=user.clover_balance, guard=True)`로 하면
    `WHERE clover_balance >= 100`이 DB의 40에 걸려 **아무 행도 안 돌아오고**, 반환값을 버리므로
    잔액 40이 남은 채 204가 나간다. 무조건 0으로 만들고 이전 값을 `RETURNING`으로 받으면
    낡은 값을 쓸 자리가 애초에 없다.
    """
    user = await _logged_in(db_client, db_session)
    await grant(db_session, user_id=user.id, amount=100, kind="attendance_grant")
    await db_session.commit()

    await db_session.execute(
        update(User).where(User.id == user.id).values(clover_balance=40),
        execution_options={"synchronize_session": False},
    )
    await db_session.commit()
    assert user.clover_balance == 100  # 메모리는 낡았다 — 이게 이 테스트의 전제다

    resp = await db_client.delete("/me")

    assert resp.status_code == 204
    assert await _balance(db_session, user.id) == 0
    burn = await db_session.scalar(
        select(CloverLedger).where(
            CloverLedger.user_id == user.id, CloverLedger.kind == "withdrawal_burn"
        )
    )
    assert burn is not None
    # 낡은 100이 아니라 **실제로 있던 40**이 소멸된다.
    assert burn.amount == -40
    assert burn.balance_after == 0

    # 로트는 잔액(40)이 아니라 **그 유저의 로트 전부**가 0이 된다(전량 무효화,
    # `revoke`의 부분 무효화와 다르다). 로트가 여전히 100을 들고 있던(원래의 불일치) 상태라도
    # 소멸이 유령 로트를 남기지 않는다.
    lot = await db_session.scalar(select(CloverLot).where(CloverLot.user_id == user.id))
    assert lot is not None
    assert lot.remaining == 0


async def test_withdraw_with_zero_balance_writes_no_ledger_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잔액 0이면 의미 없는 원장 행을 만들지 않는다.

    빨개지는 조건: `if user.clover_balance > 0:` 가드를 빼면 `withdrawal_burn` 0원 행이 생긴다.
    """
    user = await _logged_in(db_client, db_session)

    resp = await db_client.delete("/me")

    assert resp.status_code == 204
    assert await _ledger_kinds(db_session, user.id) == []


async def test_withdraw_with_zero_balance_still_zeroes_out_leftover_lots(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잔액은 이미 0인데 로트만 남은 비정상 상태(Σ 불변식이 이미 깨진 경우)도
    탈퇴가 정리한다.

    빨개지는 조건: `burn_all`이 잔액 기준(`clover_balance > 0`)으로 일찍 빠져나가며 로트
    UPDATE를 건너뛰면, 탈퇴 후에도 "만료 예정"으로 남은 유령 로트가 그대로 남는다.
    """
    user = await _logged_in(db_client, db_session)
    db_session.add(
        CloverLot(
            user_id=user.id, granted_amount=50, remaining=50, expires_at=None, kind="legacy_balance"
        )
    )
    await db_session.commit()
    assert await _balance(db_session, user.id) == 0  # 잔액은 이미 0 — 로트만 남은 상태

    resp = await db_client.delete("/me")

    assert resp.status_code == 204
    assert await _ledger_kinds(db_session, user.id) == []

    lot = await db_session.scalar(select(CloverLot).where(CloverLot.user_id == user.id))
    assert lot is not None
    assert lot.remaining == 0
