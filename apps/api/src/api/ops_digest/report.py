"""일일 운영 요약 — 읽기 전용, LLM 호출 없음, 자동 조치 없음.

    # 운영: 서빙 중인 api 컨테이너 안에서 (ops/daily-digest.sh 가 매일 KST 09:00 에 어제 하루를 부른다)
    python -m api.ops_digest [--date YYYY-MM-DD] [--dry-run]

KST 하루(기본 어제)의 운영 숫자를 Discord 메시지로 만든다.
- 사용자 활동: 가입(그 뒤 탈퇴한 회원도 센다 — 그날 가입한 사실은 남는다), 첫 대화(그날 턴이 있고, 그날 0시 전의 턴 기록도 채팅
  차감 사용처 기록도 없는 회원 — 사용처 기록은 방을 지워도 남아, 방 삭제로 옛 턴이 사라진 회원을 다시 첫 대화로 세지 않는다),
  활성 회원(그날 턴이 하나 이상), 턴 수(보내기·수정·재생성). 턴은 실행 시각에 남아 있는 기록만 센다 — 탈퇴·방 삭제·초기화가
  그 방의 턴을 지운다.
- 돈: 결제(결제 완료 시각 기준 건수·원), 환불(취소 성공 시각 기준 건수·원), 클로버 차감을 로트 등급(유료·보너스·무료)으로 나눈
  합과 환급 합. 원과 클로버는 더하지 않는다 — 보너스·부가세 때문에 클로버 수는 매출이 아니다. 환급을 빼 순소비로 내지 않는 것은
  환급 대부분이 실패 턴이라 그 수 자체가 장애 신호이기 때문이다.
- LLM 추정 원가: Redis 일 집계(`llm/usage_store.py`) 하나로 호출 위치·모델별 원가와 합계. 집계에 사용자 단위가 없어 실사용자와
  내부를 나눌 수 없다. 🔴 턴 기록(`chat_turns`)의 원가와 더하지 않는다 — 일 집계가 그 호출도 같은 자리에서 세므로 더하면 두 번
  들어간다. 같은 이유로 턴 기록 기준인 채팅 원가 비율도 싣지 않는다(원가 비율 크론이 매일 따로 보고한다). Redis 를 읽지 못하면 이
  항목만 "읽지 못함"으로 싣고 나머지는 보낸다.
- 처리 대기: 실행 시각의 누적이다(어드민 대기열과 같은 조건 — 요약을 보고 연 화면의 숫자와 같아야 한다). `--date` 로 지난 날을 다시
  돌려도 지금 값이다.
- 감시 조건: `watch.py`. 충족한 것만 끝에 한 줄씩.

실사용자와 내부는 레이트리밋 면제(`users.rate_limit_exempt`)로 가른다 — 면제 아닌 계정이 실사용자이고, 면제 여부는 실행 시각의
값이다. 회원 id·주문 id·이메일·닉네임·결제 키는 읽지도 싣지도 않는다 — 건수와 금액만 꺼낸다.

출력은 보낼 메시지들이다. 메시지마다 첫 줄이 `MESSAGE_HEADER` 로 시작하고, 한 통이 `MESSAGE_LIMIT` 를 넘으면 항목 경계(한 항목이
한 통보다 길면 줄 경계)에서 여러 통으로 나눈다 — 잘라 보내지 않는다. 호스트 알림 스크립트(`scripts/ops/daily_digest_notify.py`)가
머리 줄마다 한 통씩 보낸다. 이 모듈은 어떤 경우에도 보내지 않는다. `--dry-run` 은 머리 앞에 `DRY_RUN_PREFIX` 를 붙여 알림
스크립트가 머리를 찾지 못하게 한다(본문은 같다).

종료 코드: 0 정상(전부 0 인 날·Redis 를 읽지 못한 날 포함), 1 DB 오류 등 실패(예외 문장은 표준 오류로만 — 래퍼는 고정 문구로
알린다), 2 인자 오류.
"""

import argparse
import asyncio
import sys
import traceback
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from redis.asyncio import Redis
from sqlalchemy import ColumnElement, Select, and_, case, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from api.core.clover import kst_today
from api.core.rate_limit import KST
from api.db.models.auth import User
from api.db.models.chat import ChatMessageReport, ChatRoom, ChatTurn
from api.db.models.clover import CloverLedger, CloverLot, CloverSpendAllocation, CloverSpendRefund, CloverSpendUsage
from api.db.models.comments import CommentReport
from api.db.models.creator_payout import CreatorPayoutApplication
from api.db.models.inquiry import Inquiry, InquiryStatus
from api.db.models.moderation import Appeal, AppealStatus, Report, ReportStatus
from api.db.models.novel import NovelCommentReport, NovelPublication, NovelReport
from api.db.models.payment import Payment, PaymentCancellation
from api.db.session import async_session_factory, engine
from api.llm.pricing import KRW_PER_USD, PRICES_AS_OF
from api.llm.usage_store import UsageRow, read_usage, usage_cost_usd
from api.ops_digest.watch import WatchMetrics, load_watch_metrics, watch_lines

# 호스트 알림 스크립트(`scripts/ops/daily_digest_notify.py`)에 같은 값의 사본이 있다 — VM 의 시스템 python3 는 이 패키지를 import
# 하지 못한다. 둘이 같은지는 테스트가 본다.
MESSAGE_HEADER = "📊 일일 운영 요약"
DRY_RUN_PREFIX = "[dry-run] "
# Discord 메시지 본문 상한은 2000자다. Discord 가 그림 문자 등을 Python `len` 과 같은 단위로 세는지 확인하지 못해 여유를 둔다.
MESSAGE_LIMIT = 1900
# 여러 통일 때 머리 끝에 붙는 쪽 번호(` (3/4)`) 자리. 통 수를 알기 전에 나누므로 두 자리 쪽 번호까지 미리 비워 둔다.
_PAGE_RESERVE = len(" (99/99)")
# 호출 위치 × 모델 줄은 30줄을 넘을 수 있다 — 원가가 큰 줄만 싣고 나머지는 한 줄로 묶는다.
LLM_TOP_ROWS = 10
# 공용 Redis 클라이언트에 소켓 timeout 이 없어, 응답 없는 Redis 가 크론을 무한정 붙잡지 않게 읽기에 상한을 둔다.
REDIS_READ_TIMEOUT_SECONDS = 10

_TURN_KINDS = (("send", "보내기"), ("edit", "수정"), ("regenerate", "재생성"))
_GRADES = (("paid", "유료"), ("bonus", "보너스"), ("free", "무료"))
# 구매 로트 둘만 이름으로 집고 나머지 kind 는 전부 무료로 본다 — 차감 정렬(`core/clover.py`)과 같은 규칙이라 무료 kind 가 늘어도
# 빠뜨릴 자리가 없다.
_GRADE = case(
    (CloverLot.kind == "purchase_paid", "paid"),
    (CloverLot.kind == "purchase_bonus", "bonus"),
    else_="free",
)


@dataclass
class Group:
    """실사용자 또는 내부 한쪽의 그날 숫자."""

    signups: int = 0
    first_chats: int = 0
    active_members: int = 0
    turns: Counter[str] = field(default_factory=Counter)
    payments: int = 0
    payments_krw: int = 0
    refunds: int = 0
    refunds_krw: int = 0
    spent: Counter[str] = field(default_factory=Counter)
    refunded: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class Pending:
    """실행 시각의 처리 대기. `reports` 는 신고 표(종류)마다의 대기 수다."""

    reports: dict[str, int]
    inquiries: int
    appeals: int
    novel_first_reviews: int
    refunds_in_progress: int
    manual_payments: int
    payout_applications: int


@dataclass(frozen=True)
class Digest:
    day: date
    real: Group
    internal: Group
    pending: Pending
    # None 이면 Redis 를 읽지 못했다(빈 목록은 그날 기록이 없는 것).
    llm: list[UsageRow] | None
    watch: WatchMetrics


def default_day(now: datetime) -> date:
    """`now`(tz-aware)의 KST 어제."""
    return kst_today(now) - timedelta(days=1)


def day_window(day: date) -> tuple[datetime, datetime]:
    """KST 하루의 반열린 구간 `[start, end)`."""
    start = datetime.combine(day, time.min, tzinfo=KST)
    return start, start + timedelta(days=1)


async def _count(session: AsyncSession, statement: Select[tuple[int]]) -> int:
    return (await session.scalar(statement)) or 0


async def load_groups(session: AsyncSession, start: datetime, end: datetime) -> tuple[Group, Group]:
    """(실사용자, 내부). 질의마다 면제 칸으로 묶어 두 무리를 한 번에 센다."""

    def in_day(column: InstrumentedAttribute[datetime] | InstrumentedAttribute[datetime | None]) -> ColumnElement[bool]:
        return and_(column >= start, column < end)

    groups = {False: Group(), True: Group()}
    exempt = User.rate_limit_exempt

    for flag, signups in await session.execute(
        select(exempt, func.count()).select_from(User).where(in_day(User.created_at)).group_by(exempt)
    ):
        groups[flag].signups = signups

    for flag, kind, turns in await session.execute(
        select(exempt, ChatTurn.kind, func.count())
        .select_from(ChatTurn)
        .join(ChatRoom, ChatRoom.id == ChatTurn.chat_room_id)
        .join(User, User.id == ChatRoom.user_id)
        .where(in_day(ChatTurn.created_at))
        .group_by(exempt, ChatTurn.kind)
    ):
        groups[flag].turns[kind] = turns
    for flag, members in await session.execute(
        select(exempt, func.count(func.distinct(ChatRoom.user_id)))
        .select_from(ChatTurn)
        .join(ChatRoom, ChatRoom.id == ChatTurn.chat_room_id)
        .join(User, User.id == ChatRoom.user_id)
        .where(in_day(ChatTurn.created_at))
        .group_by(exempt)
    ):
        groups[flag].active_members = members

    earlier_room, earlier_turn = aliased(ChatRoom), aliased(ChatTurn)
    talked_before = exists().where(
        earlier_turn.chat_room_id == earlier_room.id,
        earlier_room.user_id == User.id,
        earlier_turn.created_at < start,
    )
    chat_spend_before = exists().where(
        CloverSpendUsage.spender_user_id == User.id,
        CloverSpendUsage.usage_kind == "chat",
        CloverSpendUsage.created_at < start,
    )
    talked_today = (
        select(ChatRoom.user_id).join(ChatTurn, ChatTurn.chat_room_id == ChatRoom.id).where(in_day(ChatTurn.created_at))
    )
    for flag, first_chats in await session.execute(
        select(exempt, func.count())
        .select_from(User)
        .where(User.id.in_(talked_today), ~talked_before, ~chat_spend_before)
        .group_by(exempt)
    ):
        groups[flag].first_chats = first_chats

    for flag, payments, krw in await session.execute(
        select(exempt, func.count(), func.coalesce(func.sum(Payment.amount_krw), 0))
        .select_from(Payment)
        .join(User, User.id == Payment.user_id)
        .where(in_day(Payment.paid_at))
        .group_by(exempt)
    ):
        groups[flag].payments, groups[flag].payments_krw = payments, krw

    # 실패한 취소도 완료 시각을 찍으므로 성공만 고른다.
    for flag, refunds, krw in await session.execute(
        select(exempt, func.count(), func.coalesce(func.sum(PaymentCancellation.amount_krw), 0))
        .select_from(PaymentCancellation)
        .join(Payment, Payment.id == PaymentCancellation.payment_id)
        .join(User, User.id == Payment.user_id)
        .where(PaymentCancellation.status == "succeeded", in_day(PaymentCancellation.completed_at))
        .group_by(exempt)
    ):
        groups[flag].refunds, groups[flag].refunds_krw = refunds, krw

    # 차감 배분 행은 차감에만 생기고(회수·소멸은 남기지 않는다) 시각이 없어, 시각은 그 차감의 원장 행에서 읽는다.
    for flag, grade, spent in await session.execute(
        select(exempt, _GRADE, func.sum(CloverSpendAllocation.amount))
        .select_from(CloverSpendAllocation)
        .join(CloverLedger, CloverLedger.id == CloverSpendAllocation.spend_ledger_id)
        .join(CloverLot, CloverLot.id == CloverSpendAllocation.lot_id)
        .join(User, User.id == CloverLedger.user_id)
        .where(in_day(CloverLedger.created_at))
        .group_by(exempt, _GRADE)
    ):
        groups[flag].spent[grade] = spent
    for flag, grade, refunded in await session.execute(
        select(exempt, _GRADE, func.sum(CloverSpendRefund.amount))
        .select_from(CloverSpendRefund)
        .join(CloverSpendAllocation, CloverSpendAllocation.id == CloverSpendRefund.allocation_id)
        .join(CloverLot, CloverLot.id == CloverSpendAllocation.lot_id)
        .join(User, User.id == CloverLot.user_id)
        .where(in_day(CloverSpendRefund.created_at))
        .group_by(exempt, _GRADE)
    ):
        groups[flag].refunded[grade] = refunded

    return groups[False], groups[True]


async def load_pending(session: AsyncSession) -> Pending:
    """어드민 대기열과 같은 조건으로 지금 대기 중인 행을 센다."""
    return Pending(
        reports={
            "작품": await _count(
                session, select(func.count()).select_from(Report).where(Report.status == ReportStatus.PENDING)
            ),
            "작품 댓글": await _count(
                session,
                select(func.count()).select_from(CommentReport).where(CommentReport.status == ReportStatus.PENDING),
            ),
            "채팅 응답": await _count(
                session,
                select(func.count())
                .select_from(ChatMessageReport)
                .where(ChatMessageReport.status == ReportStatus.PENDING),
            ),
            "노벨": await _count(
                session, select(func.count()).select_from(NovelReport).where(NovelReport.status == ReportStatus.PENDING)
            ),
            "노벨 댓글": await _count(
                session,
                select(func.count())
                .select_from(NovelCommentReport)
                .where(NovelCommentReport.status == ReportStatus.PENDING),
            ),
        },
        inquiries=await _count(
            session, select(func.count()).select_from(Inquiry).where(Inquiry.status == InquiryStatus.PENDING)
        ),
        appeals=await _count(
            session, select(func.count()).select_from(Appeal).where(Appeal.status == AppealStatus.PENDING)
        ),
        novel_first_reviews=await _count(
            session,
            select(func.count()).select_from(NovelPublication).where(NovelPublication.review_status == "pending"),
        ),
        refunds_in_progress=await _count(
            session,
            select(func.count()).select_from(PaymentCancellation).where(PaymentCancellation.status == "requested"),
        ),
        manual_payments=await _count(
            session,
            select(func.count()).select_from(Payment).where(Payment.status.in_(("mismatch", "owner_withdrawn"))),
        ),
        payout_applications=await _count(
            session,
            select(func.count())
            .select_from(CreatorPayoutApplication)
            .where(CreatorPayoutApplication.status == "pending"),
        ),
    )


async def read_llm_usage(day: date, *, client: Redis | None = None) -> list[UsageRow] | None:
    """그날 일 집계. Redis 를 읽지 못하면 None — 요약 전체를 실패로 만들지 않는다(원인은 표준 오류의 traceback)."""
    try:
        async with asyncio.timeout(REDIS_READ_TIMEOUT_SECONDS):
            return await read_usage(day, day, client=client)
    except Exception:
        traceback.print_exc()
        return None


async def load_digest(session: AsyncSession, day: date, *, redis: Redis | None = None) -> Digest:
    start, end = day_window(day)
    real, internal = await load_groups(session, start, end)
    return Digest(
        day=day,
        real=real,
        internal=internal,
        pending=await load_pending(session),
        llm=await read_llm_usage(day, client=redis),
        watch=await load_watch_metrics(session, start, end),
    )


def _breakdown(counts: Counter[str], labels: tuple[tuple[str, str], ...]) -> str:
    return "·".join(f"{label} {counts[key]:,}" for key, label in labels)


def _activity_block(digest: Digest) -> list[str]:
    def line(name: str, group: Group) -> str:
        return (
            f"{name}: 가입 {group.signups:,} · 첫 대화 {group.first_chats:,} · 활성 회원 {group.active_members:,}"
            f" · 턴 {group.turns.total():,}({_breakdown(group.turns, _TURN_KINDS)})"
        )

    return [
        "[사용자 활동]",
        line("실사용자", digest.real),
        line("내부", digest.internal),
        "턴은 실행 시각에 남은 기록만 센다(탈퇴·방 삭제·초기화가 지운 턴은 빠진다)",
    ]


def _money_block(digest: Digest) -> list[str]:
    def line(name: str, group: Group) -> str:
        return (
            f"{name}: 결제 {group.payments:,}건 {group.payments_krw:,}원 · 환불 {group.refunds:,}건 {group.refunds_krw:,}원"
            f" · 클로버 차감 {group.spent.total():,}({_breakdown(group.spent, _GRADES)})"
            f" · 환급 {group.refunded.total():,}({_breakdown(group.refunded, _GRADES)})"
        )

    return [
        "[돈] 결제·환불은 원(부가세 포함), 클로버는 개수 — 둘을 더하지 않는다",
        line("실사용자", digest.real),
        line("내부", digest.internal),
    ]


def _llm_block(rows: list[UsageRow] | None) -> list[str]:
    title = "[LLM 추정 원가]"
    if rows is None:
        return [f"{title} 읽지 못함 — Redis 오류(로그 확인). 다른 항목은 그대로다"]
    if not rows:
        return [f"{title} 호출 기록 없음 — 호출이 없었거나 기록이 실패했다(둘은 구별되지 않는다)"]
    costs = [(row, usage_cost_usd(row)) for row in rows]
    priced = sorted(
        ((row, cost) for row, cost in costs if cost is not None),
        key=lambda pair: (-pair[1], pair[0].call_site, pair[0].model),
    )
    unpriced = [row for row, cost in costs if cost is None]
    total_usd = sum(cost for _, cost in priced)
    lines = [
        f"{title} Redis 일 집계 — 실사용자·내부 합계(집계에 사용자 단위가 없다)",
        f"합계 ${total_usd:,.4f} ≈ {total_usd * KRW_PER_USD:,.0f}원 · 호출 {sum(row.calls for row in rows):,}회"
        f" (단가 확인일 {PRICES_AS_OF}, 1달러 {KRW_PER_USD:,}원)",
    ]
    lines += [
        f"`{row.call_site}` · `{row.model}`: ${cost:,.4f} ({row.calls:,}회)" for row, cost in priced[:LLM_TOP_ROWS]
    ]
    rest = priced[LLM_TOP_ROWS:]
    if rest:
        lines.append(
            f"그 밖 {len(rest)}줄: ${sum(cost for _, cost in rest):,.4f} ({sum(row.calls for row, _ in rest):,}회)"
        )
    notes = []
    if unpriced:
        models = ", ".join(sorted({f"`{row.model}`" for row in unpriced}))
        notes.append(f"단가 없는 호출 {sum(row.calls for row in unpriced):,}회({models}) — 합계에 없다")
    missing = sum(row.missing for row in rows)
    if missing:
        notes.append(f"사용량 메타데이터 없는 호출 {missing:,}회")
    if notes:
        lines.append(" · ".join(notes))
    return lines


def _pending_block(pending: Pending) -> list[str]:
    return [
        "[처리 대기] 실행 시각 기준 누적 — --date 로 지난 날을 다시 돌려도 지금 값이다",
        "신고: " + " · ".join(f"{name} {count:,}" for name, count in pending.reports.items()),
        f"문의 {pending.inquiries:,} · 이의제기 {pending.appeals:,} · 노벨 첫 공개 승인 {pending.novel_first_reviews:,}",
        f"진행 중 환불 {pending.refunds_in_progress:,} · 수동 처리 결제 {pending.manual_payments:,}"
        f" · 크리에이터 정산 신청 {pending.payout_applications:,}",
    ]


def _watch_block(metrics: WatchMetrics) -> list[str]:
    lines = watch_lines(metrics)
    if not lines:
        return ["[감시 조건] 충족 없음"]
    return ["[감시 조건] 충족한 것만 — 누적 조건은 실행 시각 기준", *(f"· {line}" for line in lines)]


def build_blocks(digest: Digest) -> list[list[str]]:
    """메시지 본문의 항목들(줄 묶음), 싣는 순서대로."""
    return [
        ["실사용자 = 레이트리밋 면제가 아닌 계정, 내부 = 면제 계정(면제 여부는 실행 시각 값)"],
        _activity_block(digest),
        _money_block(digest),
        _llm_block(digest.llm),
        _pending_block(digest.pending),
        _watch_block(digest.watch),
    ]


def split_messages(header: str, blocks: Sequence[Sequence[str]], *, limit: int = MESSAGE_LIMIT) -> list[str]:
    """머리와 항목들을 한 통 `limit` 자 이하의 메시지로 나눈다. 항목은 빈 줄로 띄우고, 남은 자리에 안 들어가는 항목은 다음 통으로
    넘기며, 항목 하나가 한 통보다 길면 줄 경계에서 나눈다. 줄은 자르지 않는다 — 이 모듈이 만드는 줄은 한 통보다 훨씬 짧다.
    여러 통이면 머리 끝에 ` (i/n)` 을 붙인다."""
    budget = limit - len(header) - len("\n") - _PAGE_RESERVE
    pages: list[str] = []
    current = ""
    for block in blocks:
        text_ = "\n".join(block)
        joined = f"{current}\n\n{text_}" if current else text_
        if len(joined) <= budget:
            current = joined
            continue
        if current:
            pages.append(current)
            current = ""
        if len(text_) <= budget:
            current = text_
            continue
        for line in block:
            joined = f"{current}\n{line}" if current else line
            if len(joined) <= budget or not current:
                current = joined
            else:
                pages.append(current)
                current = line
    if current:
        pages.append(current)
    if len(pages) == 1:
        return [f"{header}\n{pages[0]}"]
    return [f"{header} ({number}/{len(pages)})\n{page}" for number, page in enumerate(pages, start=1)]


def render(digest: Digest, *, dry_run: bool) -> str:
    """표준출력 전체. 메시지 사이는 빈 줄로 띄운다(알림 스크립트는 머리 줄로 나누고 앞뒤 빈 줄을 버린다)."""
    header = f"{DRY_RUN_PREFIX if dry_run else ''}{MESSAGE_HEADER} {digest.day} (KST)"
    return "\n\n".join(split_messages(header, build_blocks(digest)))


async def read_digest(day: date) -> Digest:
    async with async_session_factory() as session, session.begin():
        # 첫 문장이어야 이 트랜잭션에 걸린다 — 운영 DB 에서 도는 요약이라 실수로라도 쓰지 못하게.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return await load_digest(session, day)


async def _load(day: date) -> Digest:
    try:
        return await read_digest(day)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=date.fromisoformat, help="KST 날짜(기본: 어제)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    day: date = args.date or default_day(datetime.now(UTC))
    try:
        digest = asyncio.run(_load(day))
    except Exception:
        # 로그 파일(VM)에만 남는다. 알림은 래퍼가 고정 문구로 보낸다 — 예외 문장에는 SQL 인자가 섞일 수 있다.
        traceback.print_exc()
        return 1
    print(render(digest, dry_run=args.dry_run))
    return 0
