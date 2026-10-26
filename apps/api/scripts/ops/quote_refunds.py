"""환불할 수 있는 모든 결제(결제 완료·부분 취소)의 환불 견적을 원화로 CSV 에 뽑는다. 읽기 전용 트랜잭션에서 SELECT 만 한다.

클로버 단위를 바꾸기 전과 뒤에 같은 접수일로 한 번씩 뽑아 두 파일의 sha256 이 같으면 전환이 환불 금액을 바꾸지 않은 것이다.
견적은 어드민 환불 화면과 같은 함수(`payments/refund.py` 의 `quote_refund`)이고, 결제마다 회사 귀책 거짓·참 두 줄이다. 원화·비율
칸만 싣는다 — 남은 유료·쓴 보너스 같은 수량 칸은 전환으로 정당하게 바뀌므로 넣으면 늘 다르게 나온다. 고정 접수일보다 뒤에
결제된 건은 오류 칸에 거절 이유를 적고 계속한다.

    # 운영 VM — 돌고 있는 api 컨테이너 안에서(DATABASE_URL 이 이미 들어 있다). CSV 는 호스트의 root 파일로만 받고 화면에는
    # 표준 오류의 요약(행 수·sha256)만 남는다.
    cd /opt/ddona/app && sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env \\
        exec -T api_$(sudo bash ops/active-color.sh) python scripts/ops/quote_refunds.py --received-on 2026-11-01 \\
        | sudo tee /root/clover-quote-before.csv >/dev/null

    # 로컬
    cd apps/api && uv run --env-file .env python scripts/ops/quote_refunds.py --received-on 2026-11-01 > /tmp/quote.csv

`--received-on`(KST 날짜)은 필수다 — 실행한 날로 정하면 두 번 뽑는 사이 날짜가 바뀌어 비율이 갈릴 수 있다. 견적의 "오늘"도 그
날로 고정한다. 표준 출력이 터미널이면 결제 목록을 화면에 내지 않으려고 멈춘다.

이 파일은 같은 폴더의 다른 운영 스크립트와 달리 VM 의 시스템 python3 가 아니라 api 이미지 안에서 돈다(`api` 패키지를 쓴다).
"""

import argparse
import asyncio
import csv
import hashlib
import io
import sys
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.payment import Payment
from api.db.session import async_session_factory
from api.payments import refund

HEADER = ("payment_id", "status", "company_fault", "ratio_percent", "refund_krw", "cancellable_krw", "error")


@dataclass(frozen=True)
class QuoteRow:
    payment_id: str
    status: str
    company_fault: bool
    ratio_percent: int | None
    refund_krw: int | None
    cancellable_krw: int | None
    error: str | None


async def quote_rows(db: AsyncSession, *, received_on: date) -> list[QuoteRow]:
    """결제 행 id 순서로 결제마다 회사 귀책 거짓·참 두 줄. 순서가 고정이라 같은 DB 에서 두 번 부르면 같은 목록이다."""
    orders = (
        await db.scalars(select(Payment).where(Payment.status.in_(refund.REFUNDABLE_STATUSES)).order_by(Payment.id))
    ).all()
    rows: list[QuoteRow] = []
    for order in orders:
        for company_fault in (False, True):
            try:
                quote = await refund.quote_refund(
                    db, order, received_on=received_on, company_fault=company_fault, today=received_on
                )
            except refund.RefundRefusedError as exc:
                rows.append(QuoteRow(order.payment_id, order.status, company_fault, None, None, None, exc.code))
                continue
            rows.append(
                QuoteRow(
                    order.payment_id,
                    order.status,
                    company_fault,
                    quote.ratio_percent,
                    quote.refund_krw,
                    quote.cancellable_krw,
                    None,
                )
            )
    return rows


def render_csv(rows: list[QuoteRow]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    for row in rows:
        writer.writerow(
            (
                row.payment_id,
                row.status,
                "true" if row.company_fault else "false",
                "" if row.ratio_percent is None else row.ratio_percent,
                "" if row.refund_krw is None else row.refund_krw,
                "" if row.cancellable_krw is None else row.cancellable_krw,
                row.error or "",
            )
        )
    return out.getvalue()


async def extract(*, received_on: date) -> str:
    async with async_session_factory() as session, session.begin():
        # 첫 문장이어야 이 트랜잭션에 걸린다 — 운영 DB 의 돈 데이터 위에서 도는 스크립트라 실수로라도 쓰지 못하게. 끝은 커밋이
        # 아니라 롤백이다(아무것도 쓰지 않았으므로 같은 일이다).
        await session.execute(text("SET TRANSACTION READ ONLY"))
        rows = await quote_rows(session, received_on=received_on)
        await session.rollback()
    return render_csv(rows)


def summary(csv_text: str) -> str:
    """화면에 남기는 것은 데이터 줄 수(머리줄 제외)와 출력 전체의 sha256 뿐이다."""
    count = max(0, len(csv_text.splitlines()) - 1)
    return f"rows={count} sha256={hashlib.sha256(csv_text.encode()).hexdigest()}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--received-on", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    if sys.stdout.isatty():
        raise SystemExit("CSV 를 화면에 내지 않는다 — 표준 출력을 파일로 리다이렉트해서 다시 실행한다")
    csv_text = asyncio.run(extract(received_on=args.received_on))
    sys.stdout.write(csv_text)
    print(summary(csv_text), file=sys.stderr)


if __name__ == "__main__":
    main()
