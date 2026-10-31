"""누적 28칸 출석판 — 보상표, 오늘 상태 계산, 수령.

하루(KST)에 한 칸씩 받는다. 연속이 아니어도 다음 칸으로 이어지고(누적), 28칸을 다 받은 다음 날 새 판의 1칸이 열린다. 진도는
저장하지 않고 `attendance_claims` 의 마지막 행에서 계산한다. 지급은 `core/clover.py` 의 `grant` 에 맡기고 원장 멱등키는
`attendance_idempotency_key` 하나에서 만든다.

수령 자격은 본인인증을 마친 회원(`identity_verified_at` 이 있다)이다. 미인증 회원 게이트(`core/identity_gate.py` 의
`is_identity_gated`)는 쓰지 않는다 — 그 판정은 스위치가 꺼지거나 면제 회원이면 거짓인데, 출석의 탈퇴 재수령 차단이 CI 해시에
걸려 있어 CI 없는 회원이 받으면 같은 사람이 탈퇴하고 다시 가입해 같은 날 또 받는 것을 막을 길이 없다.

조회는 시각을 `now` 인자로, 수령은 시계 함수를 `clock` 인자로 받는다(수령은 잠근 뒤에 시각을 읽어야 해서다 — `claim`
docstring). 이 저장소에는 시계를 얼리는 도구가 없어 라우트는 `utcnow` 를 모듈 속성으로 찾아 넘기고, 테스트는 그 속성을 바꾸거나
시계 함수를 직접 넘겨 KST 자정 경계를 만든다.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.comments.access import lock_active_user
from api.core.clover import earned_lot_expiry, grant, kst_today
from api.core.identity_gate import identity_verification_required
from api.db.models.auth import User, WithdrawnIdentity
from api.db.models.clover import AttendanceClaim, CloverLedger

BOARD_SIZE = 28

# 보상표 버전 → 1~28칸 금액. 🔴 덧붙이기만 한다 — 진행 중 판은 그 판 1칸의 버전을 끝까지 쓰므로 옛 버전을 지우면 그 판의 조회와
# 수령이 깨진다. 표를 바꿀 때는 새 버전을 더하고 `CURRENT_REWARD_VERSION` 을 올린다.
ATTENDANCE_REWARDS: dict[int, tuple[int, ...]] = {
    1: (800,) * 6 + (1600,) + (800,) * 6 + (2400,) + (800,) * 6 + (3200,) + (800,) * 6 + (4800,),
}
CURRENT_REWARD_VERSION = 1

# 금액이 큰 칸. 화면의 "다음 특별일" 안내가 쓴다.
SPECIAL_SEQS: tuple[int, ...] = (7, 14, 21, 28)

# 공개 안내가 말하는 유효기간 일수. 실제 만료는 지급일 KST 자정 + 8일(`core/clover.py` 의 `earned_lot_expiry`)이라 가장 늦게
# (KST 23:59:59) 받아도 7일은 남는다 — 그래서 "최소 보장 일수"로 7을 말한다. 만료 규칙이 줄면 이 값이 거짓이 된다.
ATTENDANCE_MIN_VALID_DAYS = 7


def _check_rewards() -> None:
    """보상표가 틀리면 기동하지 않는다 — 잘못된 금액으로 지급하거나 진행 중 판의 조회가 `KeyError` 로 500 이 되는 것보다 뜨지 않는
    편이 낫다."""
    if CURRENT_REWARD_VERSION not in ATTENDANCE_REWARDS:
        raise RuntimeError("현재 보상표 버전이 표에 없다")
    for version, amounts in ATTENDANCE_REWARDS.items():
        if len(amounts) != BOARD_SIZE or any(amount <= 0 for amount in amounts):
            raise RuntimeError(f"보상표 {version} 이 {BOARD_SIZE}칸 양수 금액이 아니다")
    if sum(ATTENDANCE_REWARDS[1]) != 31_200:
        raise RuntimeError("보상표 1 의 합이 31,200 이 아니다")


_check_rewards()


def utcnow() -> datetime:
    """라우트가 쓰는 시계. 테스트가 이 속성을 바꿔 시각을 주입한다."""
    return datetime.now(UTC)


def attendance_idempotency_key(user_id: uuid.UUID, today: date) -> str:
    """원장 멱등키. 회원·KST 날짜로 정해져 같은 날 두 번째 지급이 원장 유니크에 걸린다. 없어진 일일 출석의 키는
    `attendance:` 로 시작해 접두가 달라 겹치지 않는다."""
    return f"attendance28:{user_id}:{today.isoformat()}"


@dataclass(frozen=True)
class LastClaim:
    """상태 계산에 쓰는 마지막 수령 행의 칸들."""

    board_no: int
    seq: int
    reward_version: int
    claimed_on: date


@dataclass(frozen=True)
class AttendanceState:
    """오늘 기준 출석판.

    `claimed_count` 는 이 판에서 받은 칸 수, `claimable_seq` 는 오늘 받을 칸(없으면 None), `completed_today` 는 오늘 28칸째를
    받아 판을 끝냈는가다. `reward_version` 은 이 판의 금액을 정하는 보상표 버전이다. `last_claimed_on` 은 이 계정의 마지막
    수령 행(판·칸 역순 첫 행)의 KST 날짜이고 행이 없으면 None 이다 — 판 계산과 무관해 `compute_state` 는 채우지 않고 행을 읽은
    쪽(`load_state`·`claim`)이 붙인다."""

    board_no: int
    reward_version: int
    claimed_count: int
    claimable_seq: int | None
    completed_today: bool
    last_claimed_on: date | None = None


@dataclass(frozen=True)
class AttendanceClaimResult:
    granted: bool
    balance: int
    state: AttendanceState


def compute_state(
    last: LastClaim | None, today: date, *, today_claimed: bool, withdrawn_today: bool
) -> AttendanceState:
    """마지막 수령 행과 오늘 여부로 오늘의 판을 계산한다(DB 없음).

    판이 이어지는 동안은 마지막 행의 보상표 버전을 그대로 쓰고, 새 판(행이 없거나 28칸째를 오늘이 아닌 날 받았다)만 현재
    버전을 받는다. 같은 사람이 오늘 탈퇴 전 계정에서 받았으면(`withdrawn_today`) 판 모양은 그대로 두고 오늘 받을 칸만 없앤다."""
    if last is None or (last.seq == BOARD_SIZE and not today_claimed):
        board_no = 1 if last is None else last.board_no + 1
        claimable = None if withdrawn_today else 1
        return AttendanceState(board_no, CURRENT_REWARD_VERSION, 0, claimable, False)
    if today_claimed:
        return AttendanceState(last.board_no, last.reward_version, last.seq, None, last.seq == BOARD_SIZE)
    claimable = None if withdrawn_today else last.seq + 1
    return AttendanceState(last.board_no, last.reward_version, last.seq, claimable, False)


async def claimed_today_before_withdrawal(db: AsyncSession, *, ci_hmac: str | None, today: date) -> bool:
    """같은 사람(CI 해시)이 오늘 탈퇴한 계정에서 출석을 받았는가. CI 가 없는 회원은 보관 행을 가질 수 없어 거짓이다."""
    if ci_hmac is None:
        return False
    found = await db.scalar(
        select(exists().where(WithdrawnIdentity.ci_hmac == ci_hmac, WithdrawnIdentity.attendance_claimed_on == today))
    )
    return bool(found)


async def load_state(db: AsyncSession, *, user_id: uuid.UUID, ci_hmac: str | None, now: datetime) -> AttendanceState:
    """마지막 수령 행·오늘 수령 여부·탈퇴 보관 행을 읽어 오늘의 판을 계산한다."""
    today = kst_today(now)
    row = (
        await db.execute(
            select(
                AttendanceClaim.board_no,
                AttendanceClaim.seq,
                AttendanceClaim.reward_version,
                AttendanceClaim.claimed_on,
            )
            .where(AttendanceClaim.user_id == user_id)
            .order_by(AttendanceClaim.board_no.desc(), AttendanceClaim.seq.desc())
            .limit(1)
        )
    ).first()
    last = (
        None
        if row is None
        else LastClaim(board_no=row.board_no, seq=row.seq, reward_version=row.reward_version, claimed_on=row.claimed_on)
    )
    today_claimed = bool(
        await db.scalar(select(exists().where(AttendanceClaim.user_id == user_id, AttendanceClaim.claimed_on == today)))
    )
    withdrawn_today = await claimed_today_before_withdrawal(db, ci_hmac=ci_hmac, today=today)
    state = compute_state(last, today, today_claimed=today_claimed, withdrawn_today=withdrawn_today)
    # 탈퇴 보관 기록의 수령일은 싣지 않는다 — 다른 계정의 활동 날짜가 이 계정 응답으로 드러난다.
    return replace(state, last_claimed_on=None if last is None else last.claimed_on)


async def claim(db: AsyncSession, *, user_id: uuid.UUID, clock: Callable[[], datetime]) -> AttendanceClaimResult:
    """오늘 칸을 받는다. 커밋은 호출자가 한다. 시각은 시각 값이 아니라 시계 함수(`clock`)로 받아 잠근 뒤에 부른다.

    회원 행을 먼저 잠근다(`lock_active_user`, 탈퇴도 같은 잠금을 쓴다). 그래야 같은 회원의 수령끼리, 수령과 탈퇴가 줄을 서고,
    뒤에 오는 쪽이 앞쪽이 커밋한 결과(새 출석 행, 탈퇴 표시)를 보고 판단한다. 그래서 상태와 시각을 둘 다 잠근 뒤에 읽는다.
    상태를 잠그기 전에 읽으면 자정을 사이에 둔 두 수령이 같은 칸을 계산해 뒤쪽이 받을 수 있던 칸을 잃는다. 시각을 잠그기 전에
    잡으면, 잠금을 기다린 요청이 그 사이 늦게 와 먼저 잠근 요청보다 이른 시각을 들고 들어온다 — 그러면 판·칸 순서와 날짜 순서가
    뒤집혀(뒤 칸이 앞 날짜를 갖는다) 마지막 행이 최신 날짜가 아니게 되고, 28칸째를 받은 날의 완주 표시가 사라진다.

    오늘 받을 칸이 없으면 에러가 아니라 `granted=False` 다. 원장 멱등키와 표의 두 유니크는 잠금이 빠지는 회귀가 생겨도 돈이
    두 번 나가지 않게 하는 마지막 그물이라, 위반이 나면 SAVEPOINT 만 되감고 같은 `granted=False` 로 답한다."""
    user = await lock_active_user(db, user_id)
    now = clock()
    # 판정은 잠근 행으로 한다 — 잠그기 전에 읽은 값은 낡았을 수 있다.
    if user.identity_verified_at is None:
        raise identity_verification_required()
    # SAVEPOINT 되감기는 잠근 회원 객체를 만료시키고, 비동기 세션에서는 만료된 속성의 지연 로드가 실패한다.
    # 그래서 복구 경로가 쓸 값은 여기서 지역 변수로 잡아 두고 그 뒤로는 `user` 속성을 읽지 않는다.
    ci_hmac = user.identity_ci_hmac

    state = await load_state(db, user_id=user_id, ci_hmac=ci_hmac, now=now)
    if state.claimable_seq is None:
        return AttendanceClaimResult(granted=False, balance=user.clover_balance, state=state)

    today = kst_today(now)
    seq = state.claimable_seq
    amount = ATTENDANCE_REWARDS[state.reward_version][seq - 1]
    key = attendance_idempotency_key(user_id, today)
    try:
        async with db.begin_nested():
            balance = await grant(
                db,
                user_id=user_id,
                amount=amount,
                kind="attendance_grant",
                idempotency_key=key,
                # 무료 지급에는 만료가 붙는다(지급일 KST 자정 + 8일).
                expires_at=earned_lot_expiry(now),
            )
            ledger_id = await db.scalar(select(CloverLedger.id).where(CloverLedger.idempotency_key == key))
            assert ledger_id is not None  # 방금 같은 트랜잭션에서 넣은 행이다.
            db.add(
                AttendanceClaim(
                    user_id=user_id,
                    board_no=state.board_no,
                    reward_version=state.reward_version,
                    seq=seq,
                    claimed_on=today,
                    amount=amount,
                    ledger_id=ledger_id,
                )
            )
            await db.flush()
    except IntegrityError:
        # SAVEPOINT 가 되감겨 지급이 없다. 잔액과 판은 지금 DB 에서 다시 읽는다.
        refreshed_balance = await db.scalar(select(User.clover_balance).where(User.id == user_id))
        assert refreshed_balance is not None  # 잠근 회원 행이다.
        current = await load_state(db, user_id=user_id, ci_hmac=ci_hmac, now=now)
        return AttendanceClaimResult(granted=False, balance=refreshed_balance, state=current)

    claimed = LastClaim(board_no=state.board_no, seq=seq, reward_version=state.reward_version, claimed_on=today)
    after = replace(compute_state(claimed, today, today_claimed=True, withdrawn_today=False), last_claimed_on=today)
    return AttendanceClaimResult(granted=True, balance=balance, state=after)
