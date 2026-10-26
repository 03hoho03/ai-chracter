"""`ops/quote_refunds.py` — 환불할 수 있는 모든 결제의 환불 견적(원화)을 CSV 로 뽑는 읽기 전용 스크립트.

단위 전환 전후에 한 번씩 뽑아 두 파일이 같은지(sha256)로 "전환이 환불 금액을 바꾸지 않았다"를 확인한다. 그래서 이 파일이
고정하는 성질은 셋이다.

1. 같은 DB·같은 접수일이면 출력이 바이트까지 같다 — 결제 id 순서, 결제마다 회사 귀책 거짓·참 두 줄, 원화·비율 칸만. 수량 칸은
   전환으로 정당하게 바뀌므로 싣지 않는다. 대상은 환불할 수 있는 상태(결제 완료·부분 취소)뿐이고, 고정 접수일보다 뒤에 결제된
   건은 오류 칸에 이유를 적고 계속한다.
2. 아무것도 쓰지 않는다 — 추출 중 INSERT·UPDATE·DELETE 가 0 이고, 운영에서 여는 트랜잭션은 읽기 전용이라 쓰기를 시도하면
   DB 가 거절한다.
3. CSV 는 화면에 나가지 않는다 — 표준 출력이 터미널이면 멈추고, 요약(행 수·sha256)만 표준 오류로 낸다.
"""

import hashlib
import io
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import ops.quote_refunds as quote_refunds
from api.core import clover
from api.db.models.payment import Payment
from api.db.session import engine
from factories import _make_payment, _make_user

_RECEIVED_ON = date(2026, 10, 20)


@contextmanager
def _writes() -> Iterator[list[str]]:
    seen: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        if statement.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            seen.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)


async def _order(db: AsyncSession, *, paid_on: date | None, status: str, paid_left: int, **overrides: object) -> Payment:
    user = _make_user()
    db.add(user)
    await db.flush()
    paid_at = datetime(paid_on.year, paid_on.month, paid_on.day, 3, tzinfo=UTC) if paid_on else None
    order = await _make_payment(db, user_id=user.id, status=status, paid_at=paid_at, **overrides)
    if paid_left:
        await clover.grant(db, user_id=user.id, amount=paid_left, kind="purchase_paid", payment_id=order.id)
    return order


async def _seed(db: AsyncSession) -> dict[str, Payment]:
    orders = {
        # 접수일이 결제 다음 날부터 7일 밖이라 귀책 거짓이면 90%, 참이면 전액(취소 가능 잔액 9,900 이 상한).
        "late": await _order(db, paid_on=date(2026, 10, 10), status="paid", paid_left=3_300),
        # 3,000원이 이미 취소됐고 남은 유료 2,000 — 7일 안이라 두 줄 모두 전액, 상한은 6,900.
        "partial": await _order(
            db, paid_on=date(2026, 10, 15), status="partially_cancelled", paid_left=2_000, cancelled_amount_krw=3_000
        ),
        # 고정 접수일 뒤에 결제됐다 — 견적이 거절된 이유를 적고 계속한다.
        "after": await _order(db, paid_on=date(2026, 10, 25), status="paid", paid_left=3_300),
        # 환불할 수 있는 상태가 아니다 — 줄이 없다.
        "cancelled": await _order(db, paid_on=date(2026, 10, 10), status="cancelled", paid_left=0),
        "pending": await _order(db, paid_on=None, status="pending", paid_left=0),
    }
    await db.commit()
    return orders


async def _csv(db: AsyncSession) -> str:
    return quote_refunds.render_csv(await quote_refunds.quote_rows(db, received_on=_RECEIVED_ON))


async def test_quote_rows_cover_refundable_payments_in_id_order(db_session: AsyncSession) -> None:
    orders = await _seed(db_session)
    mine = {order.payment_id for order in orders.values()}

    lines = (await _csv(db_session)).splitlines()

    assert lines[0] == "payment_id,status,company_fault,ratio_percent,refund_krw,cancellable_krw,error"
    rows = [line for line in lines[1:] if line.split(",", 1)[0] in mine]
    expected = {
        orders["late"].id: [
            f"{orders['late'].payment_id},paid,false,90,8910,9900,",
            f"{orders['late'].payment_id},paid,true,100,9900,9900,",
        ],
        orders["partial"].id: [
            f"{orders['partial'].payment_id},partially_cancelled,false,100,6000,6900,",
            f"{orders['partial'].payment_id},partially_cancelled,true,100,6000,6900,",
        ],
        orders["after"].id: [
            f"{orders['after'].payment_id},paid,false,,,,REFUND_RECEIVED_ON_INVALID",
            f"{orders['after'].payment_id},paid,true,,,,REFUND_RECEIVED_ON_INVALID",
        ],
    }
    assert rows == [line for order_id in sorted(expected) for line in expected[order_id]]


async def test_same_input_gives_the_same_bytes_and_writes_nothing(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 정렬이 없거나 시각·난수가 출력에 섞여, 전환 전후 diff 가 단위와 무관하게 빨개진다. 추출이 무엇이든 쓰면
    운영 DB 에서 돈 데이터를 건드린다."""
    await _seed(db_session)

    with _writes() as writes:
        first = await _csv(db_session)
        second = await _csv(db_session)

    assert hashlib.sha256(first.encode()).hexdigest() == hashlib.sha256(second.encode()).hexdigest()
    assert writes == []


async def test_extraction_transaction_refuses_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영에서 여는 트랜잭션은 첫 문장부터 읽기 전용이다 — 견적 코드가 바뀌어 무언가를 쓰려 해도 DB 가 거절한다."""

    async def write_instead(db: AsyncSession, *, received_on: date) -> list[quote_refunds.QuoteRow]:
        await db.execute(sa.text("CREATE TEMP TABLE quote_refunds_probe (id int)"))
        return []

    monkeypatch.setattr(quote_refunds, "quote_rows", write_instead)

    with pytest.raises(DBAPIError, match="read-only transaction"):
        await quote_refunds.extract(received_on=_RECEIVED_ON)


def test_summary_carries_only_the_count_and_hash() -> None:
    text = "payment_id,status\nclv1,paid\nclv2,paid\n"

    assert quote_refunds.summary(text) == f"rows=2 sha256={hashlib.sha256(text.encode()).hexdigest()}"


def test_refuses_to_print_the_csv_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdout", _Terminal())

    with pytest.raises(SystemExit, match="파일로 리다이렉트"):
        quote_refunds.main(["--received-on", "2026-10-20"])


def test_received_on_is_required() -> None:
    """기본값이 없다 — 두 번 뽑을 때 같은 날짜를 늘 적게 한다(실행한 날로 정하면 전후 비율이 갈릴 수 있다)."""
    with pytest.raises(SystemExit):
        quote_refunds.main([])


async def test_quote_today_is_the_fixed_received_on(db_session: AsyncSession) -> None:
    """견적의 "오늘"은 실행한 날이 아니라 고정 접수일이다. 깨지는 시나리오: 실행일을 오늘로 쓰면 실행일보다 늦은 접수일이 전부
    거절돼(접수일이 오늘 뒤) 미리 정한 날짜로 뽑을 수 없고, 두 추출의 실행일이 다르면 결과가 갈린다."""
    order = await _order(db_session, paid_on=date(2026, 10, 10), status="paid", paid_left=3_300)
    await db_session.commit()

    rows = await quote_refunds.quote_rows(db_session, received_on=date(2099, 1, 1))

    assert [(r.ratio_percent, r.error) for r in rows if r.payment_id == order.payment_id] == [(90, None), (100, None)]
