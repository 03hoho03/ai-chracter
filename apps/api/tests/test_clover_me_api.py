"""clover-techspec.md CT-9·CT-10 — `/me/clover` 3경로와 탈퇴 시 잔액 소멸(clover-goal-prompt.md CL-32).

🔴 시간을 얼리지 않는다 — 이 저장소에 `freezegun`·`time-machine`이 0건이라 KST 경계 검증은
`clover_attendance_granted_on` 컬럼에 리터럴 날짜를 넣어 확인한다(`core/clover.py`의
`kst_today(now)`가 `now`를 인자로 받는 것과 같은 이유).
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover.router import _expiring_soon
from api.core.clover import ATTENDANCE_GRANT_AMOUNT, earned_lot_expiry, grant, kst_today
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


# ── T-14. 출석 ──────────────────────────────────────────────────────────────
async def test_attendance_first_call_grants_and_increases_balance(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in(db_client, db_session)

    resp = await db_client.post("/me/clover/attendance")

    assert resp.status_code == 200
    assert resp.json() == {"granted": True, "balance": ATTENDANCE_GRANT_AMOUNT}
    assert await _balance(db_session, user.id) == ATTENDANCE_GRANT_AMOUNT
    assert await _ledger_kinds(db_session, user.id) == ["attendance_grant"]


async def test_attendance_grant_creates_a_lot_expiring_at_kst_midnight_plus_eight_days(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """clover-page-goal-prompt.md CE-11 — 출석 지급도 만료가 붙는다(CE-7과 같은 규칙: 지급일
    KST 자정 + 8일). 이 테스트가 빨개지는 조건: `claim_clover_attendance`가 `grant()`에
    `expires_at`을 안 넘기면(S2가 인자만 열어 둔 상태 그대로 남으면) 로트가 무기한
    (`expires_at IS NULL`)으로 생긴다."""
    user = await _logged_in(db_client, db_session)

    # 🔴 리터럴 주입 — 요청 전에 한 번만 `now`를 잡는다. 응답을 받은 뒤 다시
    # `datetime.now(UTC)`를 부르면(예전 버전) 그 사이 KST 자정을 걸쳐 실시간 평가가
    # 플레이크를 낸다(같은 파일의 `test_attendance_opens_again_on_the_next_kst_day` 등이
    # 이미 쓰는 "한 번만 잡은 값을 그대로 재사용" 패턴).
    now = datetime.now(UTC)
    resp = await db_client.post("/me/clover/attendance")
    assert resp.json()["granted"] is True

    lot = (
        await db_session.scalars(
            select(CloverLot).where(
                CloverLot.user_id == user.id, CloverLot.kind == "attendance_grant"
            )
        )
    ).one()
    assert lot.expires_at == earned_lot_expiry(now)


async def test_attendance_is_idempotent_within_the_same_kst_day(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 멱등을 서버가 보장한다(clover-techspec.md CT-10) — FE가 여러 번 불러도 안전해야 한다.

    이 테스트가 빨개지는 조건: `clover_attendance_granted_on` 검사를 빼면 두 번째 호출이
    `granted=true` + 잔액 200이 된다.
    """
    user = await _logged_in(db_client, db_session)

    first = await db_client.post("/me/clover/attendance")
    second = await db_client.post("/me/clover/attendance")

    assert first.json()["granted"] is True
    assert second.status_code == 200
    assert second.json() == {"granted": False, "balance": ATTENDANCE_GRANT_AMOUNT}
    assert await _balance(db_session, user.id) == ATTENDANCE_GRANT_AMOUNT
    # 원장 행도 하나뿐이다 — 잔액만 보면 "지급 후 회수"도 같은 값이라 구분되지 않는다.
    assert await _ledger_kinds(db_session, user.id) == ["attendance_grant"]


async def test_attendance_does_not_double_grant_when_the_marker_is_missed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 동시 요청이 이중 지급되지 않는다 — 멱등을 **DB가** 강제해야 한다.

    두 요청이 동시에 오면 두 번째는 첫 번째가 커밋하기 전에 `clover_attendance_granted_on`을
    읽으므로 **표지를 못 본다.** 그 상태를 여기서는 표지를 지워서 만든다 — 파이썬 쪽 검사를
    통과한 뒤에도 지급이 막히는가가 이 테스트의 질문이다.

    빨개지는 조건: 멱등이 `is_same_kst_day` 검사 하나에만 걸려 있으면(= 원장 멱등키가 없으면)
    두 번째 호출이 `granted=true` + 잔액 200 + 원장 2행이 된다. 진짜 동시 요청 재현은
    `independent_session_factory`가 필요해 S11 몫이고, 여기서는 **기구의 존재**를 고정한다.
    """
    user = await _logged_in(db_client, db_session)

    first = await db_client.post("/me/clover/attendance")
    assert first.json()["granted"] is True

    # 표지만 지운다(원장 행은 그대로) — 동시 요청 둘째가 보는 상태와 같다.
    # `synchronize_session=False`로 ORM 인스턴스를 건드리지 않고 DB만 바꾼 뒤 expire로 재조회를
    # 강제한다. 그냥 UPDATE하면 `synchronize_session="auto"`가 메모리까지 맞춰 버린다.
    await db_session.execute(
        update(User).where(User.id == user.id).values(clover_attendance_granted_on=None),
        execution_options={"synchronize_session": False},
    )
    await db_session.commit()
    db_session.expire_all()

    second = await db_client.post("/me/clover/attendance")

    assert second.status_code == 200
    assert second.json() == {"granted": False, "balance": ATTENDANCE_GRANT_AMOUNT}
    assert await _balance(db_session, user.id) == ATTENDANCE_GRANT_AMOUNT
    assert await _ledger_kinds(db_session, user.id) == ["attendance_grant"]


async def test_attendance_opens_again_on_the_next_kst_day(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """어제(KST) 받았으면 오늘 다시 받는다.

    시간을 얼리는 대신 컬럼에 어제 날짜를 넣는다 — 판정이 `is_same_kst_day(컬럼, now)` 하나라
    입력을 바꾸는 것으로 경계가 검증된다. 이 테스트가 빨개지는 조건: 판정을 "한 번이라도
    받았으면 끝"(`is not None`)으로 바꾸면 `granted=false`가 된다.
    """
    yesterday = kst_today(datetime.now(UTC)) - timedelta(days=1)
    user = await _logged_in(
        db_client, db_session, clover_balance=50, clover_attendance_granted_on=yesterday
    )

    resp = await db_client.post("/me/clover/attendance")

    assert resp.status_code == 200
    assert resp.json() == {"granted": True, "balance": 50 + ATTENDANCE_GRANT_AMOUNT}
    assert await _ledger_kinds(db_session, user.id) == ["attendance_grant"]


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
        "attendanceClaimable": True,
        "expiringSoon": None,
    }


async def test_balance_flags_flip_once_today_is_recorded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 플래그가 **각각의 컬럼**을 본다는 것까지 고정한다 — 한 컬럼으로 둘을 답하면 빨개진다."""
    today = kst_today(datetime.now(UTC))
    await _logged_in(
        db_client,
        db_session,
        clover_balance=30,
        clover_attendance_granted_on=today,
        clover_spend_confirmed_on=today,
    )

    resp = await db_client.get("/me/clover")

    assert resp.json() == {
        "balance": 30,
        "spendConfirmedToday": True,
        "attendanceClaimable": False,
        "expiringSoon": None,
    }


async def test_balance_does_not_grant_attendance(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 GET에 부작용을 두지 않는다(clover-techspec.md CT-10). 조회만으로 지급되면 빨개진다."""
    user = await _logged_in(db_client, db_session)

    await db_client.get("/me/clover")

    assert await _balance(db_session, user.id) == 0
    assert await _ledger_kinds(db_session, user.id) == []


# ── expiringSoon (CE-22) ─────────────────────────────────────────────────────
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
    """CE-22 — 배치가 아직 못 지운 이미 만료된 로트(`expires_at <= now`)는 제외한다.

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
    """clover-page-goal-prompt.md CE-22 — 임박 임계값은 3일이다(사전 점검 I-1).

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
    """경계(정확히 3일 남음)는 **포함**으로 정했다 — 이 런의 발명이다(CE-22는 "3일 이내"의
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
    """사전 점검 I-2 — `remaining = 0`인 소진 로트는 만료 전이어도 대상에서 빠진다.

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
    assert (await db_client.post("/me/clover/attendance")).status_code == 401
    assert (await db_client.post("/me/clover/spend-confirmation")).status_code == 401


# ── T-16. 탈퇴 시 잔액 소멸 ──────────────────────────────────────────────────
async def test_withdraw_burns_the_balance_and_keeps_the_ledger(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """clover-goal-prompt.md CL-32 — 잔액은 0으로 소멸시키고 원장은 남긴다.

    빨개지는 조건: 소멸을 빼면 잔액이 100으로 남는다(탈퇴는 soft delete라 행이 그대로다).
    원장을 지우면 `attendance_grant`가 사라진다.
    """
    user = await _logged_in(db_client, db_session)
    await grant(db_session, user_id=user.id, amount=100, kind="attendance_grant")
    await db_session.commit()

    resp = await db_client.delete("/me")

    assert resp.status_code == 204
    assert await _balance(db_session, user.id) == 0
    # 기존 행이 남고 소멸 행이 더해진다 — 원장은 불변이다(clover-goal-prompt.md CL-6).
    assert await _ledger_kinds(db_session, user.id) == ["attendance_grant", "withdrawal_burn"]
    burn = await db_session.scalar(
        select(CloverLedger).where(
            CloverLedger.user_id == user.id, CloverLedger.kind == "withdrawal_burn"
        )
    )
    assert burn is not None
    assert burn.amount == -100
    assert burn.balance_after == 0

    # clover-page-goal-prompt.md T-9(CE-29) — `grant()`가 만든 로트도 함께 0이 됐다.
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

    # T-9(CE-29) — 로트는 잔액(40)이 아니라 **그 유저의 로트 전부**가 0이 된다(전량 무효화,
    # `revoke`의 부분 무효화와 다르다). 로트가 여전히 100을 들고 있던(원래의 불일치) 상태라도
    # 소멸이 유령 로트를 남기지 않는다.
    lot = await db_session.scalar(select(CloverLot).where(CloverLot.user_id == user.id))
    assert lot is not None
    assert lot.remaining == 0


async def test_withdraw_with_zero_balance_writes_no_ledger_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잔액 0이면 의미 없는 원장 행을 만들지 않는다(§3-8).

    빨개지는 조건: `if user.clover_balance > 0:` 가드를 빼면 `withdrawal_burn` 0원 행이 생긴다.
    """
    user = await _logged_in(db_client, db_session)

    resp = await db_client.delete("/me")

    assert resp.status_code == 204
    assert await _ledger_kinds(db_session, user.id) == []


async def test_withdraw_with_zero_balance_still_zeroes_out_leftover_lots(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T-9(CE-29) — 잔액은 이미 0인데 로트만 남은 비정상 상태(Σ 불변식이 이미 깨진 경우)도
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
