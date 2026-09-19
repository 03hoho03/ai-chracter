"""clover-techspec.md CT-18 · S11 — 독립 커넥션이 있어야만 검증되는 것들.

이 파일의 테스트는 **롤백되지 않는 진짜 커넥션**을 쓴다. 나머지 클로버 테스트가 쓰는
`db_session`/`db_client`는 한 커넥션 위의 한 트랜잭션이라(`conftest.py`의 `db_session`
docstring: *"sessions sharing a connection share its transaction"*) 두 가지를 재현하지 못한다:

- **롤백 독립성**(clover-goal-prompt.md CL-9) — 별도 세션의 쓰기가 호출자 트랜잭션에 합류해
  같이 롤백되므로 "요청이 롤백돼도 차감이 남는다"가 성립하는지 볼 수 없다.
- **경쟁** — 단일 커넥션에서는 두 코루틴이 같은 행을 두고 락을 다툴 수 없다. `asyncio.gather`로
  묶어도 실제로는 한 트랜잭션 안의 순차 실행이라, 통과하더라도 **동시성을 논증하지 못한다.**

🔴 그래서 이 파일의 경쟁 테스트는 **락이 실제로 걸리는 것을 먼저 단언**한다(`_assert_blocked`).
그게 없으면 "순차로 돌아도 통과하는" 항진명제가 된다 — 이 런에서 이미 세 번 겪은 형태다
(더미 리소스 · 셋업 플래그 주입 · 손으로 쓴 유니언).
"""

import asyncio
import re
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.core.clover import (
    ATTENDANCE_GRANT_AMOUNT,
    CHAT_TURN_COST,
    burn_all,
    grant,
    kst_today,
    spend,
    spend_in_new_transaction,
)
from api.db.models.auth import User
from api.db.models.clover import CloverLedger
from factories import _make_user

# teardown이 지울 대상을 고르는 표지다. 이 파일이 만든 유저만 지우므로 다른 테스트의 행을
# 건드리지 않는다 — 아래 픽스처 docstring의 "위험 1" 참조.
_MARKER_DOMAIN = "s11-independent.test"


@pytest_asyncio.fixture
async def independent_session_factory(
    db_engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """clover-techspec.md CT-18 — 롤백되지 않는 독립 커넥션을 주는 세션 팩토리.

    `conftest.py`의 `db_client`가 거는 `get_session_factory` 오버라이드를 **쓰지 않는다.**
    그건 `db_session`의 커넥션에 바인딩돼 같이 롤백되므로(`conftest.py:248-251`) 검증하려는
    성질이 사라진다. 여기서는 엔진에서 직접 만들어 세션마다 풀에서 **다른 커넥션**을 받는다.

    🔴 **여기서 쓴 행은 롤백되지 않는다 — teardown이 직접 지운다.**

    위험을 정직하게 적는다:

    1. **teardown이 `_MARKER_DOMAIN` 유저만 지운다.** techspec의 앞선 판본은
       `delete(CloverLedger)` 전역 + `update(User).values(clover_balance=0, ...)` 전역이었는데,
       그 전역 `UPDATE`는 **같은 테스트가 열어 둔 `db_session` 트랜잭션이 잡은 행 락에 막혀
       teardown이 멈출 수 있다**(픽스처는 역순으로 정리되므로 `db_session`이 아직 살아 있다).
       이 런에서 `alembic downgrade base`가 열린 트랜잭션에 막혀 스위트 전체가 행(hang)난
       사고를 이미 한 번 겪었다 — 같은 형태를 만들지 않으려고 범위를 좁혔다.
       ⇒ **대가**: 이 픽스처를 쓰는 테스트는 유저를 반드시 `_seed_user`로 만들어야 한다.
       `db_session`으로 만든 유저는 (가) 독립 커넥션에서 보이지도 않고 (나) teardown이
       치우지도 못한다.
    2. **유저를 지우는 것이 컬럼 3개를 되돌리는 것보다 완전하다.** `clover_balance` ·
       `clover_attendance_granted_on` · `clover_spend_confirmed_on` 중 하나라도 빠뜨리면
       커밋된 채 새는데, 행을 지우면 그 실수가 불가능하다. `clover_ledger`가 `users.id`를
       FK로 잡으므로 **원장을 먼저** 지운다(ON DELETE CASCADE가 없다).
    3. **teardown이 실패하면 다음 테스트가 오염된 상태를 본다.** finalizer는 테스트 실패
       시에도 돌지만 teardown 자체가 예외를 내면 막을 방법이 없다.
    4. 🔴 **`pytest-xdist`를 도입하면 이 픽스처가 먼저 깨진다** — 워커 둘이 같은 테스트 DB를
       공유하면 한쪽 teardown이 다른 쪽이 쓰는 중인 유저를 지운다. 표지가 워커별로 갈려야 한다.
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (
            await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))
        ).all()
        if user_ids:
            await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def _seed_user(
    factory: async_sessionmaker[AsyncSession], *, clover_balance: int
) -> uuid.UUID:
    """독립 커넥션으로 유저를 **커밋해서** 만든다.

    `db_session`으로 만들면 그 트랜잭션 안에 갇혀 이 파일의 다른 커넥션에서 보이지 않는다
    (clover-techspec.md CT-18 위험 2).
    """
    user = _make_user(
        email=f"s11-{uuid.uuid4()}@{_MARKER_DOMAIN}", clover_balance=clover_balance
    )
    async with factory() as session:
        session.add(user)
        await session.commit()
    return user.id


async def _read(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> tuple[int, list[CloverLedger]]:
    """**새 커넥션**으로 잔액과 원장을 읽는다 — 커밋된 것만 보인다는 뜻이다."""
    async with factory() as session:
        balance = await session.scalar(select(User.clover_balance).where(User.id == user_id))
        assert balance is not None
        rows = list(
            (
                await session.scalars(
                    select(CloverLedger).where(CloverLedger.user_id == user_id)
                )
            ).all()
        )
        return balance, rows


async def _assert_blocked(task: "asyncio.Task[object]", *, block_seconds: float = 0.5) -> None:
    """`task`가 DB 락에 막혀 있다는 것을 단언한다.

    🔴 **이 단언이 이 파일의 경쟁 테스트를 항진명제에서 구한다.** 최종 상태만 보면 두 연산이
    순차로 돌아도 같은 값이 나오므로, "정말 동시에 같은 행을 다퉜는가"는 여기서만 증명된다.
    `shield`로 감싸는 이유는 `wait_for`의 타임아웃이 task를 취소해 버리면 뒤에서 결과를 받을
    수 없기 때문이다.

    타이밍 의존이 한 방향뿐이라 안전하다 — 막힌 쪽은 상대가 커밋하기 전에는 **원리적으로**
    진행할 수 없으므로 타임아웃이 반드시 난다. 반대로 느슨하게 잡아 실패하는 경우는 없다.

    (인자 이름이 `timeout`이 아닌 것은 ruff `ASYNC109` 때문이다 — 그 규칙은 타임아웃을
    인자로 넘기지 말고 `asyncio.timeout`을 쓰라고 하는데, 여기서 재는 것은 "제한 시간"이
    아니라 **"이만큼 기다려도 안 끝난다"**는 성질이라 의미가 다르다.)
    """
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), block_seconds)


# ── S11-2a · `spend_in_new_transaction` 직접 테스트 ──────────────────────────
async def test_spend_in_new_transaction_commits_without_the_caller(
    independent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """차감이 **자기 트랜잭션에서 즉시 커밋**된다(clover-techspec.md CT-4).

    빨개지는 조건: `spend_in_new_transaction`이 `session.commit()`을 빼면 `_read`가 여는
    **새 커넥션**에서 잔액 100·원장 0행으로 보인다.
    """
    user_id = await _seed_user(independent_session_factory, clover_balance=100)

    charged = await spend_in_new_transaction(
        independent_session_factory, user_id=user_id, amount=CHAT_TURN_COST, kind="chat_spend"
    )

    assert charged == 90
    balance, rows = await _read(independent_session_factory, user_id)
    assert balance == 90
    assert [(row.kind, row.amount, row.balance_after) for row in rows] == [("chat_spend", -10, 90)]


async def test_spend_in_new_transaction_writes_nothing_when_short(
    independent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """잔액이 모자라면 `None`이고 **아무것도 커밋되지 않는다**.

    빨개지는 조건: `_apply`의 `guard=True`가 빠지면 잔액이 -5가 되고 원장에 1행이 남는다
    (CHECK 제약에 먼저 걸릴 수도 있다 — 어느 쪽이든 이 단언이 깨진다).
    """
    user_id = await _seed_user(independent_session_factory, clover_balance=5)

    charged = await spend_in_new_transaction(
        independent_session_factory, user_id=user_id, amount=CHAT_TURN_COST, kind="chat_spend"
    )

    assert charged is None
    balance, rows = await _read(independent_session_factory, user_id)
    assert balance == 5
    assert rows == []


# ── S11-3 · T-9 롤백 독립성 (clover-goal-prompt.md CL-9) ─────────────────────
async def test_charge_survives_the_callers_rollback(
    independent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """🔴 **CL-9의 존재 이유다** — 호출자 트랜잭션이 롤백돼도 차감이 남는다.

    채팅 4경로의 커밋 시점이 제각각이라 요청 세션에 얹으면 미리보기는 영원히 공짜가 된다.
    별도 트랜잭션이라야 그 차이가 사라진다.

    빨개지는 조건: `spend_in_new_transaction`이 자기 세션 대신 호출자 세션을 쓰면 아래
    `outer.rollback()`이 차감까지 되감아 잔액 100·원장 0행이 된다.

    ⚠️ 닉네임 단언이 **항진명제 방지**다. 그게 없으면 `outer`가 애초에 아무것도 안 썼거나
    롤백이 안 일어나도 테스트가 통과한다 — 롤백이 실제로 무언가를 되돌렸다는 증거가 필요하다.

    🔴 **닉네임을 *다른 유저* 행에 쓴다.** 차감 대상과 같은 행에 쓰면 `outer`가 그 행의 락을
    잡은 채 열려 있고, `spend_in_new_transaction`이 **다른 커넥션**에서 같은 행을 UPDATE하려다
    영원히 막힌다(실측: 이 테스트의 앞선 판본이 pytest를 10분 타임아웃까지 끌고 갔다).
    독립 커넥션이 진짜라는 증거이기도 하다 — 같은 커넥션이었다면 막히지 않았을 것이다.
    """
    user_id = await _seed_user(independent_session_factory, clover_balance=100)
    bystander_id = await _seed_user(independent_session_factory, clover_balance=0)

    outer = independent_session_factory()
    try:
        await outer.execute(
            update(User).where(User.id == bystander_id).values(nickname="롤백될 이름")
        )
        charged = await spend_in_new_transaction(
            independent_session_factory, user_id=user_id, amount=CHAT_TURN_COST, kind="chat_spend"
        )
        assert charged == 90
        await outer.rollback()
    finally:
        await outer.close()

    balance, rows = await _read(independent_session_factory, user_id)
    assert balance == 90
    assert len(rows) == 1

    async with independent_session_factory() as session:
        nickname = await session.scalar(select(User.nickname).where(User.id == bystander_id))
    assert nickname == "테스터"


# ── S11-2b · 진짜 동시 차감 ─────────────────────────────────────────────────
async def test_concurrent_spend_cannot_overdraw(
    independent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """🔴 두 커넥션이 같은 행을 두고 **실제로 락을 다툰다**. 잔액은 음수가 되지 않는다.

    `_apply`의 `WHERE clover_balance >= -delta`가 유일한 방어다 — Postgres가 B의 UPDATE를
    A의 커밋까지 막고, 풀린 뒤 **WHERE를 재평가**해 거짓이 되므로 0행이 돌아온다.

    빨개지는 조건:
    - 가드(`guard=True`)를 빼면 B가 통과해 잔액 -10 + 원장 2행이 된다
      (CHECK 제약에 먼저 걸리면 `IntegrityError`로 깨진다 — 어느 쪽이든 빨갛다).
    - 두 세션이 같은 커넥션을 쓰면 `_assert_blocked`가 **타임아웃하지 않아** 빨개진다.
    """
    user_id = await _seed_user(independent_session_factory, clover_balance=CHAT_TURN_COST)

    first = independent_session_factory()
    second = independent_session_factory()
    try:
        # A: 조건부 UPDATE가 통과하고 행 락을 잡는다. 아직 커밋하지 않는다.
        first_result = await spend(
            first, user_id=user_id, amount=CHAT_TURN_COST, kind="chat_spend"
        )
        assert first_result == 0

        # B: 같은 행에 같은 UPDATE를 낸다 → A가 커밋할 때까지 막힌다.
        task = asyncio.create_task(
            spend(second, user_id=user_id, amount=CHAT_TURN_COST, kind="chat_spend")
        )
        await _assert_blocked(task)

        await first.commit()

        # 락이 풀리고 B가 WHERE를 재평가한다 — 잔액이 0이라 조건이 거짓이다.
        second_result = await task
        assert second_result is None
        await second.commit()
    finally:
        await first.close()
        await second.close()

    balance, rows = await _read(independent_session_factory, user_id)
    assert balance == 0
    assert [(row.kind, row.amount) for row in rows] == [("chat_spend", -10)]


# ── S11-2c · 진짜 동시 출석 (S6 리뷰 H-1의 잔여) ────────────────────────────
async def test_concurrent_attendance_grants_only_once(
    independent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """🔴 같은 날 동시 출석 둘 중 **하나만** 지급된다. 막는 것은 원장 멱등키다.

    `clover/router.py`의 `is_same_kst_day` 검사는 **순차 재호출**만 막는다 — 둘째는 첫째가
    커밋하기 전에 표지를 읽어 못 보고 통과하고, `grant`는 `guard=False`라 조건 없는
    `WHERE users.id = :u`만 내므로 락이 풀린 뒤 재평가에서도 그대로 통과한다.
    ⇒ 격리를 맡는 것은 `ux_clover_ledger_idempotency_key`다(clover-goal-prompt.md CL-8).

    빨개지는 조건: `idempotency_key`를 `None`으로 넘기면 유니크 인덱스가 걸리지 않아 둘 다
    성공하고 **잔액 200 · 원장 2행**이 된다. 세션이 같은 커넥션이면 `_assert_blocked`가
    타임아웃하지 않아 빨개진다.
    """
    user_id = await _seed_user(independent_session_factory, clover_balance=0)
    today = kst_today(datetime.now(UTC))
    key = f"attendance:{user_id}:{today}"

    first = independent_session_factory()
    second = independent_session_factory()
    try:
        first_balance = await grant(
            first,
            user_id=user_id,
            amount=ATTENDANCE_GRANT_AMOUNT,
            kind="attendance_grant",
            idempotency_key=key,
        )
        assert first_balance == ATTENDANCE_GRANT_AMOUNT

        # B의 원장 INSERT가 같은 유니크 키에 막힌다 — A가 커밋할 때까지 대기한다.
        task = asyncio.create_task(
            grant(
                second,
                user_id=user_id,
                amount=ATTENDANCE_GRANT_AMOUNT,
                kind="attendance_grant",
                idempotency_key=key,
            )
        )
        await _assert_blocked(task)

        await first.commit()

        # 락이 풀리는 순간 유니크 위반이 확정된다 — 라우트는 이걸 `granted=false`로 번역한다.
        with pytest.raises(IntegrityError):
            await task
        await second.rollback()
    finally:
        await first.close()
        await second.close()

    balance, rows = await _read(independent_session_factory, user_id)
    assert balance == ATTENDANCE_GRANT_AMOUNT
    assert [(row.kind, row.amount) for row in rows] == [("attendance_grant", 100)]


# ── S11-2d · `burn_all`은 호출자가 읽어 둔 잔액에 기대지 않는다 ────────────────
async def test_burn_all_burns_the_balance_the_row_actually_holds(
    independent_session_factory: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    """🔴 `burn_all` 직전에 다른 트랜잭션이 차감하고 커밋해도 잔액은 정확히 0이 된다.

    탈퇴 라우트는 `user`를 초입에서 로드하고 그 뒤 채팅방·메시지·asset 삭제를 거치므로,
    소멸 시점의 실제 잔액이 그 로드값보다 적을 수 있다(다른 탭이 그 사이 채팅을 했다).
    여기서는 그 창을 **최대로 벌려** 재현한다 — 호출자가 100을 본 뒤 90으로 커밋된다.

    `burn_all`이 절대 대입(`SET clover_balance = 0`)이고 소멸액을 `RETURNING OLD`로 받으므로
    읽기와 쓰기가 **한 문장**이다. 그래서 ① 잔액이 정확히 0이고 ② 원장 금액이 **실제로
    소멸된 90**이다(호출자가 본 100이 아니다).

    🔴 이 테스트는 `burn_all`을 직접 부른다. 내부를 재현하면 구현이 바뀔 때 테스트만 초록으로
    남는다 — S11 첫 판본이 `_apply` 두 문장을 손으로 재현했다가 정확히 그 함정에 걸렸다.

    🔴 **그리고 결과만 봐서는 신호가 없다.** 읽기와 쓰기가 갈려 있어도 READ COMMITTED에서는
    각 문장이 새 스냅샷을 보므로, 두 문장 **사이에** 커밋이 끼지 않는 한 결과가 같다. 그래서
    `users`를 건드리는 문장 수를 함께 센다 — 창이 **있으면 2문장**(SELECT+UPDATE),
    **없으면 1문장**이다. 그 수가 이 테스트의 유일한 결정적 가드다.
    """
    user_id = await _seed_user(independent_session_factory, clover_balance=100)

    users_statements: list[str] = []

    def _record(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if re.search(r"\busers\b", statement):
            users_statements.append(statement.split(maxsplit=1)[0].upper())

    burner = independent_session_factory()
    spender = independent_session_factory()
    try:
        # ① 탈퇴 라우트가 `user`를 로드한 시점의 잔액.
        loaded = await burner.scalar(select(User.clover_balance).where(User.id == user_id))
        assert loaded == 100

        # ② 그 사이 다른 트랜잭션이 차감하고 **커밋한다** — 실제 잔액은 이제 90이다.
        spent = await spend(spender, user_id=user_id, amount=CHAT_TURN_COST, kind="chat_spend")
        assert spent == 90
        await spender.commit()

        # ③ 소멸. 낡은 `loaded`(100)가 아니라 행이 실제로 가진 90이 소멸돼야 한다.
        event.listen(db_engine.sync_engine, "before_cursor_execute", _record)
        try:
            burned = await burn_all(burner, user_id=user_id)
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", _record)
        assert burned == 90
        await burner.commit()
    finally:
        await burner.close()
        await spender.close()

    # 🔴 창이 없다는 것의 결정적 증거. 구 구현(SELECT 뒤 상대 증감)에서는 `["SELECT", "UPDATE"]`다.
    assert users_statements == ["UPDATE"]

    balance, rows = await _read(independent_session_factory, user_id)
    assert balance == 0
    assert sorted((row.kind, row.amount) for row in rows) == [
        ("chat_spend", -10),
        ("withdrawal_burn", -90),
    ]
