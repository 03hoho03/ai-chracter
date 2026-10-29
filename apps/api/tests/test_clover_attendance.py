"""누적 28칸 출석판 — `GET /me/attendance`·`POST /me/attendance/claim`, 상태 계산, 공개 안내, 표 제약.

이 파일이 검증하는 성질:

1. 스위치가 꺼져 있으면 두 라우트는 로그인·정지와 무관하게 404 이고 돈이 움직이지 않는다.
2. 하루(KST)에 한 칸, 연속이 아니어도 다음 칸(누적), 28칸 다음 날 새 판. 7·14·21·28칸은 큰 금액이다.
3. 진행 중 판은 그 판 1칸의 보상표 버전을 끝까지 쓴다 — 보상표가 바뀌어도 그 판의 금액은 그대로이고, 새 판부터 새 표다.
4. 수령 자격은 본인인증(`identity_verified_at`) 하나다. 미인증 회원 게이트 스위치·면제와 무관하다 — 탈퇴 재수령 차단이 CI 해시에
   걸려 있어 CI 없는 회원이 받으면 막을 길이 없다.
5. 같은 사람이 오늘 탈퇴 전 계정에서 받았으면 새 계정은 오늘 받지 못한다(어제 기록은 막지 않는다).
6. 인증을 통과한 뒤 탈퇴가 커밋되면 수령은 잠근 뒤 회원 행을 다시 읽어 401 로 멈춘다.

시각은 `attendance.utcnow` 를 바꿔 주입한다 — 이 저장소에는 시계를 얼리는 도구가 없다. 출석 행의 `claimed_at` 은 DB 시각이라
주입한 시계와 다르므로 판정에 쓰지 않는다. 같은 회원의 동시 수령과 탈퇴 경합은 독립 커넥션이 있어야 재현돼
`test_clover_concurrency.py` 에 있다.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover import attendance
from api.clover.attendance import AttendanceState, LastClaim
from api.core import clover
from api.core.clover import earned_lot_expiry
from api.core.config import settings
from api.core.rate_limit import KST
from api.db.models.auth import User, WithdrawnIdentity
from api.db.models.clover import AttendanceClaim, CloverLedger, CloverLot
from api.main import app
from factories import _login_as, _make_attendance_claim, _make_user, _make_user_with_clover_lot

# KST 2026-10-29 12:00 — 날짜 경계에서 먼 평범한 오늘.
_NOW = datetime(2026, 10, 29, 3, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 29)
_YESTERDAY = date(2026, 10, 28)
_V1 = attendance.ATTENDANCE_REWARDS[1]


@pytest.fixture(autouse=True)
def _board_on_and_identity_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """출석판은 켜고 미인증 회원 게이트는 끈 채로 시작한다. 게이트를 켜는 경우를 위해 본인인증 설정도 채운다(게이트는 그 설정이
    있어야 켜진다). 시계는 `_NOW` 다."""
    monkeypatch.setattr(settings, "attendance_board_enabled", True)
    monkeypatch.setattr(settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "identity_gate_enabled", False)
    _set_clock(monkeypatch, _NOW)


def _set_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    monkeypatch.setattr(attendance, "utcnow", lambda: now)


def _verified(ci_hmac: str | None = None) -> dict[str, object]:
    return {"identity_ci_hmac": ci_hmac or f"ci-{uuid.uuid4().hex}", "identity_verified_at": _NOW}


async def _member(db: AsyncSession, client: httpx.AsyncClient, **overrides: object) -> User:
    """잔액 0 으로 로그인한 회원. 인증 여부는 `overrides` 로 정한다."""
    user = await _make_user_with_clover_lot(db, clover_balance=0, **overrides)
    await db.commit()
    await _login_as(client, user.id)
    return user


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = (await db.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))).all()
    return sorted((row.kind, row.amount) for row in rows)


async def _claims(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[int, int, int, date, int]]:
    """(판, 칸, 보상표 버전, 받은 날, 금액) — 판·칸 순서."""
    rows = (
        await db.scalars(
            select(AttendanceClaim)
            .where(AttendanceClaim.user_id == user_id)
            .order_by(AttendanceClaim.board_no, AttendanceClaim.seq)
        )
    ).all()
    return [(r.board_no, r.seq, r.reward_version, r.claimed_on, r.amount) for r in rows]


async def _balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db.scalar(select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return balance


def _statuses(board: dict[str, Any]) -> list[str]:
    return [cell["status"] for cell in board["cells"]]


# ── 스위치 ────────────────────────────────────────────────────────────────
async def test_board_routes_are_404_while_the_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """꺼진 동안 화면이 라우트를 찾지 못한 것과 같다. 깨지는 시나리오: 스위치 검사가 빠지면 인증 회원에게 800 이 지급된다."""
    monkeypatch.setattr(settings, "attendance_board_enabled", False)
    user = await _member(db_session, db_client, **_verified())

    assert (await db_client.get("/me/attendance")).status_code == 404
    assert (await db_client.post("/me/attendance/claim")).status_code == 404
    assert await _ledger(db_session, user.id) == []


async def test_switch_off_answers_404_even_without_a_session(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치 검사가 인증보다 먼저다 — 꺼진 동안은 비로그인에게도 401 이 아니라 404 라 기능이 있다는 것이 드러나지 않는다."""
    monkeypatch.setattr(settings, "attendance_board_enabled", False)

    assert (await db_client.get("/me/attendance")).status_code == 404
    assert (await db_client.post("/me/attendance/claim")).status_code == 404


async def test_switch_on_requires_a_session(db_client: httpx.AsyncClient) -> None:
    assert (await db_client.get("/me/attendance")).status_code == 401
    assert (await db_client.post("/me/attendance/claim")).status_code == 401


# ── 수령 ──────────────────────────────────────────────────────────────────
async def test_first_claim_grants_the_first_cell(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """첫 수령은 1판 1칸 800 이다. 원장 한 행(`attendance_grant`, 회원·KST 날짜 멱등키), 지급일 KST 자정 + 8일에 만료되는 로트,
    그 원장 행을 가리키는 출석 행이 함께 생긴다. 깨지는 시나리오: 만료를 넘기지 않으면 무료 클로버가 무기한으로 남는다."""
    user = await _member(db_session, db_client, **_verified())

    resp = await db_client.post("/me/attendance/claim")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["granted"], body["balance"]) == (True, 800)
    assert body["board"]["boardNo"] == 1
    assert _statuses(body["board"]) == ["claimed"] + ["upcoming"] * 27
    assert body["board"]["canClaimToday"] is False
    assert await _balance(db_session, user.id) == 800
    ledger = (await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user.id))).one()
    assert (ledger.kind, ledger.amount) == ("attendance_grant", 800)
    assert ledger.idempotency_key == f"attendance28:{user.id}:2026-10-29"
    lot = (await db_session.scalars(select(CloverLot).where(CloverLot.user_id == user.id))).one()
    assert lot.expires_at == earned_lot_expiry(_NOW)
    claim = (await db_session.scalars(select(AttendanceClaim).where(AttendanceClaim.user_id == user.id))).one()
    assert (claim.board_no, claim.seq, claim.reward_version, claim.claimed_on, claim.amount) == (1, 1, 1, _TODAY, 800)
    assert claim.ledger_id == ledger.id


async def test_second_claim_on_the_same_day_grants_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 날 두 번째는 에러가 아니라 `granted=false` 이고 잔액·원장이 그대로다. 판은 그 순간의 상태를 싣는다."""
    user = await _member(db_session, db_client, **_verified())
    assert (await db_client.post("/me/attendance/claim")).json()["granted"] is True

    resp = await db_client.post("/me/attendance/claim")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["granted"], body["balance"]) == (False, 800)
    assert _statuses(body["board"]) == ["claimed"] + ["upcoming"] * 27
    assert await _ledger(db_session, user.id) == [("attendance_grant", 800)]
    assert len(await _claims(db_session, user.id)) == 1


async def test_ledger_key_already_taken_rolls_back_to_no_grant(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """출석 행은 없는데 오늘 멱등키의 원장 행만 있으면(잠금이 빠지는 회귀에서 다른 수령이 원장까지만 쓴 상태) 지급이 원장 유니크에
    걸린다. 그때 SAVEPOINT 만 되감고 `granted=false` 로 답하며, 응답 잔액은 되감긴 뒤의 DB 잔액이다. 깨지는 시나리오: 잔액을
    DB 에서 다시 읽지 않고 메모리의 회원 객체로 답하면 지급하다 만 잔액을 내보내거나, 되감긴 객체를 읽다 500 이 난다."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=300, **_verified())
    # 앱의 SAVEPOINT 되감기가 같은 세션의 이 회원 객체를 만료시키므로, 요청 뒤에는 미리 잡아 둔 id 만 쓴다.
    user_id = user.id
    db_session.add(
        CloverLedger(
            user_id=user_id,
            amount=800,
            balance_after=1100,
            kind="attendance_grant",
            idempotency_key=f"attendance28:{user_id}:2026-10-29",
        )
    )
    await db_session.commit()
    await _login_as(db_client, user_id)

    resp = await db_client.post("/me/attendance/claim")

    assert resp.status_code == 200
    body = resp.json()
    assert body["granted"] is False
    assert body["balance"] == await _balance(db_session, user_id) == 300
    assert await _claims(db_session, user_id) == []
    assert await _ledger(db_session, user_id) == [("attendance_grant", 800)]


async def test_claims_across_kst_midnight_land_on_two_days(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KST 23:59:59 와 1초 뒤 00:00:00 은 다른 날이다. 깨지는 시나리오: 날짜를 UTC 로 자르면 두 시각이 같은 UTC 날짜(10-29)라
    두 번째가 "이미 받음"이 된다."""
    user = await _member(db_session, db_client, **_verified())

    _set_clock(monkeypatch, datetime(2026, 10, 29, 14, 59, 59, tzinfo=UTC))
    first = await db_client.post("/me/attendance/claim")
    _set_clock(monkeypatch, datetime(2026, 10, 29, 15, 0, 0, tzinfo=UTC))
    second = await db_client.post("/me/attendance/claim")

    assert first.json()["granted"] is True
    assert second.json()["granted"] is True
    assert [(seq, claimed_on) for _, seq, _, claimed_on, _ in await _claims(db_session, user.id)] == [
        (1, date(2026, 10, 29)),
        (2, date(2026, 10, 30)),
    ]


async def test_skipped_days_still_advance_to_the_next_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """누적이다 — 마지막 수령이 9일 전이어도 판이 처음으로 돌아가지 않고 다음 칸을 받는다."""
    user = await _member(db_session, db_client, **_verified())
    await _make_attendance_claim(db_session, user.id, board_no=1, seq=3, claimed_on=date(2026, 10, 20))

    resp = await db_client.post("/me/attendance/claim")

    assert resp.json()["granted"] is True
    assert (await _claims(db_session, user.id))[-1] == (1, 4, 1, _TODAY, 800)


@pytest.mark.parametrize(
    ("seq", "amount"),
    [
        pytest.param(7, 1_600, id="seq-7"),
        pytest.param(14, 2_400, id="seq-14"),
        pytest.param(21, 3_200, id="seq-21"),
        pytest.param(28, 4_800, id="seq-28"),
    ],
)
async def test_special_cells_pay_the_larger_amounts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, seq: int, amount: int
) -> None:
    user = await _member(db_session, db_client, **_verified())
    await _make_attendance_claim(db_session, user.id, board_no=1, seq=seq - 1, claimed_on=_YESTERDAY)
    before = await _balance(db_session, user.id)

    resp = await db_client.post("/me/attendance/claim")

    assert resp.json()["granted"] is True
    assert resp.json()["balance"] == before + amount
    assert (await _claims(db_session, user.id))[-1] == (1, seq, 1, _TODAY, amount)


async def test_board_on_the_day_the_last_cell_is_claimed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """28칸째를 받은 날은 판이 끝난 모양이다 — 28칸 모두 받음, 오늘 완주, 오늘 받을 칸 없음, 다음 특별일 없음. 깨지는 시나리오:
    받은 날 바로 새 판을 보여 주면 화면이 오늘 한 번 더 받을 수 있는 것처럼 그린다."""
    user = await _member(db_session, db_client, **_verified())
    await _make_attendance_claim(db_session, user.id, board_no=1, seq=27, claimed_on=_YESTERDAY)
    assert (await db_client.post("/me/attendance/claim")).json()["granted"] is True

    board = (await db_client.get("/me/attendance")).json()

    assert board["boardNo"] == 1
    assert _statuses(board) == ["claimed"] * 28
    assert board["completedToday"] is True
    assert board["canClaimToday"] is False
    assert board["nextSpecial"] is None


async def test_the_day_after_completion_opens_the_next_board(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _member(db_session, db_client, **_verified())
    await _make_attendance_claim(db_session, user.id, board_no=1, seq=28, claimed_on=_YESTERDAY)

    board = (await db_client.get("/me/attendance")).json()
    resp = await db_client.post("/me/attendance/claim")

    assert board["boardNo"] == 2
    assert _statuses(board) == ["today"] + ["upcoming"] * 27
    assert board["completedToday"] is False
    assert resp.json()["granted"] is True
    assert (await _claims(db_session, user.id))[-1] == (2, 1, 1, _TODAY, 800)


async def test_a_board_in_progress_keeps_its_reward_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """보상표에 버전 2 가 생기고 현재 버전이 2 가 돼도 진행 중 판은 버전 1 금액으로 이어진다. 그 판을 끝낸 다음 날 새 판부터 버전
    2 다. 깨지는 시나리오: 새 행에 언제나 현재 버전을 넣으면 판 중간에 금액이 바뀌고, 조회가 보여 준 금액과 지급이 갈린다."""
    v2 = tuple(amount + 100 for amount in _V1)
    monkeypatch.setattr(attendance, "ATTENDANCE_REWARDS", {1: _V1, 2: v2})
    monkeypatch.setattr(attendance, "CURRENT_REWARD_VERSION", 2)
    in_progress = await _member(db_session, db_client, **_verified())
    await _make_attendance_claim(db_session, in_progress.id, board_no=1, seq=5, claimed_on=_YESTERDAY)

    board = (await db_client.get("/me/attendance")).json()
    resp = await db_client.post("/me/attendance/claim")

    assert board["rewardVersion"] == 1
    assert [cell["amount"] for cell in board["cells"]] == list(_V1)
    assert resp.json()["granted"] is True
    assert (await _claims(db_session, in_progress.id))[-1] == (1, 6, 1, _TODAY, _V1[5])

    finished = await _member(db_session, db_client, **_verified())
    await _make_attendance_claim(db_session, finished.id, board_no=1, seq=28, claimed_on=_YESTERDAY)

    assert (await db_client.post("/me/attendance/claim")).json()["granted"] is True
    assert (await _claims(db_session, finished.id))[-1] == (2, 1, 2, _TODAY, v2[0])


# ── 자격 ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("gate", [pytest.param(False, id="gate-off"), pytest.param(True, id="gate-on")])
async def test_unverified_member_is_refused_whether_or_not_the_gate_is_on(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, gate: bool
) -> None:
    """깨지는 시나리오: 미인증 회원 게이트 판정을 쓰면 게이트가 꺼진 동안 CI 없는 회원이 받아, 탈퇴하고 다시 가입해 같은 날 또
    받을 수 있다."""
    monkeypatch.setattr(settings, "identity_gate_enabled", gate)
    user = await _member(db_session, db_client)

    resp = await db_client.post("/me/attendance/claim")

    assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})
    assert await _ledger(db_session, user.id) == []


async def test_exemption_does_not_open_the_claim_to_an_unverified_member(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """레이트리밋 면제는 미인증 회원 게이트를 건너뛰게 하지만 출석 자격은 열지 않는다 — 면제 회원도 CI 가 없으면 재수령을 막을
    길이 없다."""
    monkeypatch.setattr(settings, "identity_gate_enabled", True)
    user = await _member(db_session, db_client, rate_limit_exempt=True)

    resp = await db_client.post("/me/attendance/claim")

    assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})
    assert await _ledger(db_session, user.id) == []


@pytest.mark.parametrize(
    ("gate", "exempt"),
    [pytest.param(False, False, id="verified-gate-off"), pytest.param(True, True, id="verified-exempt-gate-on")],
)
async def test_verified_member_claims_regardless_of_gate_and_exemption(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, gate: bool, exempt: bool
) -> None:
    monkeypatch.setattr(settings, "identity_gate_enabled", gate)
    await _member(db_session, db_client, rate_limit_exempt=exempt, **_verified())

    resp = await db_client.post("/me/attendance/claim")

    assert resp.json()["granted"] is True


# ── 탈퇴한 같은 사람 ────────────────────────────────────────────────────────
async def test_same_person_who_claimed_today_before_withdrawing_cannot_claim_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """오늘 탈퇴 전 계정에서 받은 사람의 새 계정은 오늘 받지 못한다. 판은 행이 없어 1판이고 오늘 받을 칸이 없다. 깨지는 시나리오:
    탈퇴 보관 행을 보지 않으면 탈퇴 → 재가입으로 하루에 여러 번 받는다."""
    ci_hmac = f"ci-{uuid.uuid4().hex}"
    db_session.add(WithdrawnIdentity(ci_hmac=ci_hmac, withdrawn_at=_NOW, attendance_claimed_on=_TODAY))
    user = await _member(db_session, db_client, **_verified(ci_hmac))

    resp = await db_client.post("/me/attendance/claim")
    board = (await db_client.get("/me/attendance")).json()

    assert resp.json()["granted"] is False
    assert await _ledger(db_session, user.id) == []
    assert board["boardNo"] == 1
    assert board["canClaimToday"] is False
    assert "today" not in _statuses(board)


async def test_withdrawal_record_from_yesterday_does_not_block_today(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """막는 것은 탈퇴한 그날 하루다 — 날짜 대신 기록의 존재만 보면 같은 사람이 영영 못 받는다."""
    ci_hmac = f"ci-{uuid.uuid4().hex}"
    db_session.add(
        WithdrawnIdentity(ci_hmac=ci_hmac, withdrawn_at=_NOW - timedelta(days=1), attendance_claimed_on=_YESTERDAY)
    )
    await _member(db_session, db_client, **_verified(ci_hmac))

    resp = await db_client.post("/me/attendance/claim")

    assert resp.json()["granted"] is True


async def test_withdrawal_committed_after_authentication_refuses_the_claim(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """인증 의존성을 통과한 뒤 다른 곳에서 탈퇴가 커밋된 경우. 정지 스위치 의존성(인증 다음에 풀린다)을 갈아 끼워 그 자리에서
    회원 행의 `deleted_at` 을 DB 에만 찍는다 — 세션이 들고 있는 회원 객체는 탈퇴 전 값 그대로라, 잠근 뒤 행을 다시 읽지 않으면
    낡은 값을 보고 지급한다. 깨지는 시나리오: 수령이 잠그지 않거나 잠근 뒤 다시 읽지 않으면 탈퇴한 계정에 800 이 나간다."""
    user = await _member(db_session, db_client, **_verified())
    assert user.deleted_at is None

    async def _withdraw_after_auth() -> None:
        await db_session.execute(
            update(User).where(User.id == user.id).values(deleted_at=_NOW),
            execution_options={"synchronize_session": False},
        )

    app.dependency_overrides[clover.raise_if_clover_paused] = _withdraw_after_auth
    try:
        resp = await db_client.post("/me/attendance/claim")
    finally:
        del app.dependency_overrides[clover.raise_if_clover_paused]

    assert resp.status_code == 401
    assert await _ledger(db_session, user.id) == []


# ── 재동의 ────────────────────────────────────────────────────────────────
async def test_pending_reconsent_blocks_the_board(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """다른 `/me` 클로버 라우트와 같이 재동의 전에는 막는다."""
    user = _make_user(terms_version=None, **_verified())
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    for resp in (await db_client.get("/me/attendance"), await db_client.post("/me/attendance/claim")):
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "LEGAL_RECONSENT_REQUIRED"
    assert await _ledger(db_session, user.id) == []


# ── 응답 모양 ──────────────────────────────────────────────────────────────
async def test_fresh_board_response_shape(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """처음 보는 회원의 판 — camelCase 키, 1칸만 오늘, 다음 특별일은 7칸(오늘 1칸을 받으면 6일 뒤)."""
    await _member(db_session, db_client, **_verified())

    resp = await db_client.get("/me/attendance")

    assert resp.status_code == 200
    assert resp.json() == {
        "boardNo": 1,
        "rewardVersion": 1,
        "cells": [{"seq": 1, "amount": 800, "status": "today"}]
        + [{"seq": seq, "amount": _V1[seq - 1], "status": "upcoming"} for seq in range(2, 29)],
        "canClaimToday": True,
        "completedToday": False,
        "nextSpecial": {"seq": 7, "amount": 1_600, "daysUntil": 6},
    }


async def test_next_special_counts_days_from_the_board_in_progress(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """어제 9칸까지 받았으면 오늘 10칸이고 다음 특별일은 14칸으로 4일 뒤다. 오늘 받은 뒤에는 내일이 11칸이라 여전히 4일 뒤다 —
    오늘 받을 칸이 있는지에 따라 세는 기준 칸이 다르다. 깨지는 시나리오: 기준을 한쪽으로만 세면 둘 중 하나가 하루 어긋난다."""
    user = await _member(db_session, db_client, **_verified())
    await _make_attendance_claim(db_session, user.id, board_no=1, seq=9, claimed_on=_YESTERDAY)

    before = (await db_client.get("/me/attendance")).json()
    after = (await db_client.post("/me/attendance/claim")).json()["board"]

    assert before["nextSpecial"] == {"seq": 14, "amount": 2_400, "daysUntil": 4}
    assert _statuses(before) == ["claimed"] * 9 + ["today"] + ["upcoming"] * 18
    assert after["nextSpecial"] == {"seq": 14, "amount": 2_400, "daysUntil": 4}
    assert _statuses(after) == ["claimed"] * 10 + ["upcoming"] * 18


# ── 상태 계산(DB 없음) ──────────────────────────────────────────────────────
def _last(seq: int, claimed_on: date, *, board_no: int = 1, reward_version: int = 7) -> LastClaim:
    """보상표 버전을 표에 없는 7 로 두어, 이어지는 판이 마지막 행의 버전을 물려받는지 새 판이 현재 버전(1)을 받는지가 값으로
    갈리게 한다."""
    return LastClaim(board_no=board_no, seq=seq, reward_version=reward_version, claimed_on=claimed_on)


@pytest.mark.parametrize(
    ("last", "today_claimed", "withdrawn_today", "expected"),
    [
        pytest.param(None, False, False, AttendanceState(1, 1, 0, 1, False), id="no-rows"),
        pytest.param(None, False, True, AttendanceState(1, 1, 0, None, False), id="no-rows-withdrawn-today"),
        pytest.param(_last(5, _TODAY), True, False, AttendanceState(1, 7, 5, None, False), id="claimed-today"),
        pytest.param(_last(28, _TODAY), True, False, AttendanceState(1, 7, 28, None, True), id="completed-today"),
        pytest.param(_last(5, _YESTERDAY), False, False, AttendanceState(1, 7, 5, 6, False), id="continue"),
        pytest.param(
            _last(5, date(2026, 9, 1)), False, False, AttendanceState(1, 7, 5, 6, False), id="continue-after-gap"
        ),
        pytest.param(
            _last(28, _YESTERDAY, board_no=3), False, False, AttendanceState(4, 1, 0, 1, False), id="next-board"
        ),
    ],
)
def test_compute_state(
    last: LastClaim | None, today_claimed: bool, withdrawn_today: bool, expected: AttendanceState
) -> None:
    assert attendance.compute_state(last, _TODAY, today_claimed=today_claimed, withdrawn_today=withdrawn_today) == expected


# ── 공개 안내 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("switch", [pytest.param(False, id="off"), pytest.param(True, id="on")])
async def test_public_pricing_carries_the_attendance_policy(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, switch: bool
) -> None:
    """로그인하지 않은 방문자도 출석 안내를 읽는다 — 켜짐 여부는 스위치를, 보상표는 현재 버전 표를 따르고 최소 유효 일수는 7이다."""
    monkeypatch.setattr(settings, "attendance_board_enabled", switch)

    resp = await db_client.get("/clover/pricing")

    policy = resp.json()["attendance"]
    assert policy["enabled"] is switch
    assert policy["rewards"] == list(_V1)
    assert (len(policy["rewards"]), sum(policy["rewards"])) == (28, 31_200)
    assert policy["minValidDays"] == 7


async def test_public_reward_table_follows_the_current_version(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """깨지는 시나리오: 라우트가 버전 1 표를 그대로 들고 있으면 보상표를 바꾼 뒤에도 옛 금액을 안내한다."""
    v2 = tuple(amount + 100 for amount in _V1)
    monkeypatch.setattr(attendance, "ATTENDANCE_REWARDS", {1: _V1, 2: v2})
    monkeypatch.setattr(attendance, "CURRENT_REWARD_VERSION", 2)

    resp = await db_client.get("/clover/pricing")

    assert resp.json()["attendance"]["rewards"] == list(v2)


def test_min_valid_days_holds_for_a_claim_at_the_last_second_of_the_day() -> None:
    """안내하는 최소 유효 일수는 가장 늦게(KST 23:59:59) 받은 클로버에도 참이어야 한다. 깨지는 시나리오: 만료 규칙을 지급일
    자정 + 7일로 줄이면 그 시각에 받은 클로버는 6일 남짓만 남아 안내가 거짓이 된다."""
    last_second = datetime(2026, 10, 29, 23, 59, 59, tzinfo=KST)

    assert earned_lot_expiry(last_second) - last_second >= timedelta(days=attendance.ATTENDANCE_MIN_VALID_DAYS)


# ── 표 제약 ──────────────────────────────────────────────────────────────
# CHECK 둘은 `alembic check` 가 비교하지 않아 이 테스트가 유일한 검증이다(유니크 둘은 `alembic check` 가 비교한다).
async def _ledger_row(db: AsyncSession) -> CloverLedger:
    user = _make_user()
    db.add(user)
    await db.flush()
    row = CloverLedger(user_id=user.id, amount=800, balance_after=800, kind="attendance_grant")
    db.add(row)
    await db.flush()
    return row


async def _insert_claim(db: AsyncSession, ledger: CloverLedger, **overrides: object) -> None:
    """정상 행을 기본값으로, `overrides` 로 칸을 틀어 넣는다."""
    values: dict[str, object] = {
        "user_id": ledger.user_id,
        "board_no": 1,
        "reward_version": 1,
        "seq": 1,
        "claimed_on": _TODAY,
        "amount": 800,
        "ledger_id": ledger.id,
    }
    values.update(overrides)
    db.add(AttendanceClaim(**values))
    await db.flush()


@pytest.mark.parametrize("seq", [pytest.param(0, id="seq-0"), pytest.param(29, id="seq-29")])
async def test_seq_outside_the_board_is_rejected(db_session: AsyncSession, seq: int) -> None:
    with pytest.raises(IntegrityError, match="ck_attendance_claims_seq_range"):
        await _insert_claim(db_session, await _ledger_row(db_session), seq=seq)


@pytest.mark.parametrize("seq", [pytest.param(1, id="seq-1"), pytest.param(28, id="seq-28")])
async def test_seq_at_the_board_edges_is_accepted(db_session: AsyncSession, seq: int) -> None:
    await _insert_claim(db_session, await _ledger_row(db_session), seq=seq)


async def test_zero_amount_is_rejected(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_attendance_claims_amount_positive"):
        await _insert_claim(db_session, await _ledger_row(db_session), amount=0)


async def test_smallest_positive_amount_is_accepted(db_session: AsyncSession) -> None:
    await _insert_claim(db_session, await _ledger_row(db_session), amount=1)
