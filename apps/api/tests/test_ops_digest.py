"""일일 운영 요약 본문(`api.ops_digest.report`).

DB 를 거치는 것은 KST 하루 경계·실사용자/내부 나눔·탈퇴 회원·돈 집계·처리 대기·식별 정보 없음·읽기 전용이고, 메시지 나눔과
LLM 줄은 숫자를 손으로 넣은 요약으로 친다. 날짜는 다른 테스트의 "지금"과 겹치지 않는 지난 날(2026-10-21 KST)이라 그날 범위의
행은 이 테스트가 넣은 것뿐이다. LLM 원가는 단가표에 시험용 모델 한 줄(100만 토큰당 1달러)을 끼워 손으로 셀 수 있게 한다.
"""

from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.redis import redis_client
from api.db.models import ChatRoom, User
from api.db.models.clover import CloverLedger
from api.db.models.creator_payout import CreatorPayoutApplication
from api.db.models.moderation import Report, ReportReasonCategory, ReportStatus
from api.db.models.payment import PaymentCancellation
from api.llm import pricing
from api.llm.pricing import ModelPrice
from api.llm.usage_store import UsageRow, usage_key
from api.ops_digest import report
from api.ops_digest.watch import WatchMetrics
from factories import (
    _console_cancel,
    _make_bare_chat_room,
    _make_chat_turn,
    _make_draft_content,
    _make_payment,
    _make_player,
    _make_user,
    _refund,
    _use,
    kst,
)

_DAY = date(2026, 10, 21)
_PRICED = "test-priced-model"


@pytest.fixture(autouse=True)
def _test_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력·출력 100만 토큰당 1달러, 캐시 읽기 0.1달러."""
    monkeypatch.setitem(pricing.MODEL_PRICES, _PRICED, ModelPrice(1.0, 0.1, 1.0))


async def _member(db: AsyncSession, *, exempt: bool = False, **overrides: object) -> User:
    user = _make_user(rate_limit_exempt=exempt, **overrides)
    db.add(user)
    await db.flush()
    return user


async def _room_of(db: AsyncSession, user: User) -> ChatRoom:
    """`user` 가 주인인 방. 최소 방 팩토리의 방 주인을 바꿔 쓴다(작품 작가는 그대로 다른 회원)."""
    room = await _make_bare_chat_room(db)
    room.user_id = user.id
    await db.flush()
    return room


async def _turns(db: AsyncSession, room: ChatRoom, *stamps: datetime, kind: str = "send") -> None:
    db.add_all(_make_chat_turn(room.id, kind=kind, created_at=at) for at in stamps)
    await db.flush()


_EMPTY = report.Digest(
    day=_DAY,
    real=report.Group(),
    internal=report.Group(),
    pending=report.Pending(
        reports={"작품": 0, "작품 댓글": 0, "채팅 응답": 0, "노벨": 0, "노벨 댓글": 0},
        inquiries=0,
        appeals=0,
        novel_first_reviews=0,
        refunds_in_progress=0,
        manual_payments=0,
        payout_applications=0,
    ),
    llm=[],
    watch=WatchMetrics(),
)


def _digest(**overrides: Any) -> report.Digest:
    """숫자를 손으로 넣은 요약 — 메시지 모양만 볼 때."""
    return replace(_EMPTY, **overrides)


def _all_watch_met() -> WatchMetrics:
    return WatchMetrics(**dict.fromkeys(WatchMetrics.__dataclass_fields__, 10_000))


def _usage(call_site: str, model: str = _PRICED, **metrics: int) -> UsageRow:
    return UsageRow(day=_DAY, call_site=call_site, model=model, **metrics)


# ── KST 하루 ───────────────────────────────────────────────────────────────────
def test_default_day_is_the_kst_yesterday_across_utc_midnight() -> None:
    """KST 10-22 00:00 은 UTC 로 아직 10-21 이다 — UTC 날로 셈하면 하루 앞 날(10-20)을 요약한다."""
    assert report.default_day(datetime(2026, 10, 21, 15, 0, tzinfo=UTC)) == date(2026, 10, 21)
    assert report.default_day(datetime(2026, 10, 21, 14, 59, 59, tzinfo=UTC)) == date(2026, 10, 20)


async def test_activity_counts_the_kst_day_and_splits_real_from_internal(db_session: AsyncSession) -> None:
    """KST 00:00 과 23:59:59 는 그날, 전날 23:59:59 와 다음 날 00:00 은 아니다. 면제 계정은 내부로 간다. 다음 날 08:59:59 는
    UTC 로는 아직 그날이다 — 이 줄이 없으면 UTC 하루로 잘라도 하나 빠지고(KST 00:00) 하나 들어와(다음 날 00:00) 수가 같다."""
    inside = (kst(10, 21), kst(10, 21, 23, 59, 59))
    outside = (kst(10, 20, 23, 59, 59), kst(10, 22), kst(10, 22, 8, 59, 59))
    for at in inside + outside:
        await _member(db_session, created_at=at)
    await _member(db_session, exempt=True, created_at=kst(10, 21, 12))

    talker = await _member(db_session, created_at=kst(10, 1))
    room = await _room_of(db_session, talker)
    await _turns(db_session, room, *inside, *outside)
    await _turns(db_session, room, kst(10, 21, 9), kind="regenerate")
    staff = await _member(db_session, exempt=True, created_at=kst(10, 1))
    await _turns(db_session, await _room_of(db_session, staff), kst(10, 21, 10), kind="edit")

    real, internal = await report.load_groups(db_session, *report.day_window(_DAY))

    assert (real.signups, internal.signups) == (2, 1)
    assert real.turns == Counter({"send": 2, "regenerate": 1})
    assert internal.turns == Counter({"edit": 1})
    assert (real.active_members, internal.active_members) == (1, 1)


async def test_first_chat_skips_members_who_talked_or_paid_for_chat_before_the_day(db_session: AsyncSession) -> None:
    newcomer = await _member(db_session, created_at=kst(10, 1))
    await _turns(db_session, await _room_of(db_session, newcomer), kst(10, 21, 8))

    regular = await _member(db_session, created_at=kst(10, 1))
    regular_room = await _room_of(db_session, regular)
    await _turns(db_session, regular_room, kst(10, 20, 23, 59, 59), kst(10, 21, 8))

    # 옛 방을 지워 턴 기록은 없지만 그 대화의 차감 사용처는 남은 회원 — 다시 첫 대화로 세면 안 된다.
    returning = await _make_player(db_session, amount_krw=9_900, paid=3_300)
    content = await _make_draft_content(db_session, creator_user_id=newcomer.id)
    await _use(db_session, returning, content, 10, kst(10, 15))
    await _turns(db_session, await _room_of(db_session, returning.user), kst(10, 21, 8))

    real, _ = await report.load_groups(db_session, *report.day_window(_DAY))

    assert real.first_chats == 1
    assert real.active_members == 3


async def test_a_withdrawn_member_still_counts_as_a_signup_and_a_payment(db_session: AsyncSession) -> None:
    """탈퇴는 회원 행을 남기고 결제 행도 5년 남긴다 — 그날 가입·결제한 사실은 그대로 센다."""
    gone = await _member(db_session, created_at=kst(10, 21, 7), deleted_at=kst(10, 21, 20))
    await _make_payment(db_session, user_id=gone.id, status="paid", paid_at=kst(10, 21, 8), amount_krw=4_900)

    real, _ = await report.load_groups(db_session, *report.day_window(_DAY))

    assert real.signups == 1
    assert (real.payments, real.payments_krw) == (1, 4_900)


async def test_money_splits_real_from_internal_by_grade_and_by_success(db_session: AsyncSession) -> None:
    buyer = await _make_player(db_session, amount_krw=9_900, paid=3_300, bonus=300, free=100)
    buyer.payment.paid_at = kst(10, 21, 10)
    content = await _make_draft_content(db_session, creator_user_id=buyer.user.id)
    # 무료 100 → 보너스 300 → 유료 100 순서로 깎인다. 환급 150 은 그 역순(유료 100 → 보너스 50).
    spent = await _use(db_session, buyer, content, 500, kst(10, 21, 11))
    await db_session.execute(sa.update(CloverLedger).where(CloverLedger.id == spent).values(created_at=kst(10, 21, 11)))
    await _refund(db_session, buyer, spent, 150, kst(10, 21, 12))
    await _console_cancel(db_session, buyer.payment, 1_000, kst(10, 21, 23, 59, 59))
    # 실패한 취소도 완료 시각을 찍는다 — 환불로 세면 안 된다.
    db_session.add(
        PaymentCancellation(
            payment_id=buyer.payment.id, source="console", status="failed", amount_krw=500, completed_at=kst(10, 21, 13)
        )
    )
    # 다음 날 0시 결제는 그날이 아니다.
    await _make_payment(db_session, user_id=buyer.user.id, status="paid", paid_at=kst(10, 22), amount_krw=4_900)

    tester = await _make_player(db_session, amount_krw=4_900, paid=1_600)
    tester.user.rate_limit_exempt = True
    tester.payment.paid_at = kst(10, 21, 9)
    await db_session.flush()

    real, internal = await report.load_groups(db_session, *report.day_window(_DAY))

    assert (real.payments, real.payments_krw, real.refunds, real.refunds_krw) == (1, 9_900, 1, 1_000)
    assert real.spent == Counter({"free": 100, "bonus": 300, "paid": 100})
    assert real.refunded == Counter({"paid": 100, "bonus": 50})
    assert (internal.payments, internal.payments_krw, internal.refunds) == (1, 4_900, 0)


def test_a_day_without_payments_reports_zero_won() -> None:
    blocks = report.build_blocks(_digest())

    money = next(block for block in blocks if block[0].startswith("[돈]"))
    assert money[1] == (
        "실사용자: 결제 0건 0원 · 환불 0건 0원 · 클로버 차감 0(유료 0·보너스 0·무료 0) · 환급 0(유료 0·보너스 0·무료 0)"
    )


# ── LLM 원가 ───────────────────────────────────────────────────────────────────
async def _put_usage(day: date, call_site: str, model: str = _PRICED, **metrics: int) -> None:
    await redis_client.hset(
        usage_key(day), mapping={f"{call_site}|{model}|{metric}": value for metric, value in metrics.items()}
    )


async def test_llm_cost_comes_from_the_daily_usage_hash_alone(db_session: AsyncSession) -> None:
    """합계는 일 집계 줄만 더한다 — 같은 날 턴 기록의 호출 원가(3달러)를 더하면 같은 호출이 두 번 들어간다. 이미지 호출 줄은
    입력이 비어 와서 total 에서 복원한다(50만 토큰 = 0.5달러)."""
    await _put_usage(_DAY, "chat_generate", calls=2, prompt=1_000_000, total=1_000_000)
    await _put_usage(_DAY, "image_match_judge", calls=1, prompt=0, total=500_000)
    room = await _make_bare_chat_room(db_session)
    call = {"callSite": "chat_generate", "model": _PRICED, "promptTokens": 3_000_000, "outputTokens": 0}
    db_session.add(_make_chat_turn(room.id, created_at=kst(10, 21, 9), llm_calls=[call]))
    await db_session.flush()

    digest = await report.load_digest(db_session, _DAY)
    rendered = report.render(digest, dry_run=False)

    assert "합계 $1.5000 ≈ 2,100원 · 호출 3회" in rendered
    assert "`image_match_judge` · `test-priced-model`: $0.5000 (1회)" in rendered


async def test_no_usage_hash_reads_as_no_records(db_session: AsyncSession) -> None:
    digest = await report.load_digest(db_session, _DAY)

    assert digest.llm == []
    assert "[LLM 추정 원가] 호출 기록 없음" in report.render(digest, dry_run=False)


async def test_a_redis_failure_blanks_only_the_llm_section(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _down(*_args: object, **_kwargs: object) -> list[UsageRow]:
        raise ConnectionError("redis down")

    monkeypatch.setattr(report, "read_usage", _down)
    await _member(db_session, created_at=kst(10, 21, 12))

    digest = await report.load_digest(db_session, _DAY)
    rendered = report.render(digest, dry_run=False)

    assert digest.llm is None
    assert "[LLM 추정 원가] 읽지 못함" in rendered
    assert "실사용자: 가입 1 ·" in rendered


def test_unpriced_models_are_named_but_left_out_of_the_total() -> None:
    rows = [
        _usage("chat_generate", calls=1, prompt=1_000_000),
        _usage("chat_generate", model="unknown-model", calls=4, prompt=9_000_000),
    ]

    llm = next(block for block in report.build_blocks(_digest(llm=rows)) if block[0].startswith("[LLM"))

    assert llm[1].startswith("합계 $1.0000 ≈ 1,400원 · 호출 5회")
    assert llm[-1] == "단가 없는 호출 4회(`unknown-model`) — 합계에 없다"


def test_only_the_costliest_rows_are_listed_and_the_rest_are_summed() -> None:
    rows = [_usage(f"site_{n:02d}", calls=1, prompt=(n + 1) * 100_000) for n in range(12)]

    llm = next(block for block in report.build_blocks(_digest(llm=rows)) if block[0].startswith("[LLM"))

    assert llm[2] == "`site_11` · `test-priced-model`: $1.2000 (1회)"
    assert len(llm) == 2 + report.LLM_TOP_ROWS + 1
    # 가장 싼 두 줄(0.1·0.2달러)이 묶인다.
    assert llm[-1] == "그 밖 2줄: $0.3000 (2회)"


# ── 처리 대기 ───────────────────────────────────────────────────────────────────
async def test_pending_counts_only_rows_still_waiting(db_session: AsyncSession) -> None:
    before = await report.load_pending(db_session)
    reporter = await _member(db_session)
    content = await _make_draft_content(db_session, creator_user_id=reporter.id)
    for status in (ReportStatus.PENDING, ReportStatus.RESOLVED):
        db_session.add(
            Report(
                reporter_user_id=reporter.id,
                content_id=content.id,
                reason_category=ReportReasonCategory.SPAM,
                status=status,
            )
        )
    payment = await _make_payment(db_session, user_id=reporter.id, status="paid")
    db_session.add(PaymentCancellation(payment_id=payment.id, source="console", status="requested", amount_krw=100))
    await _make_payment(db_session, user_id=reporter.id, status="mismatch")
    await _make_payment(db_session, user_id=reporter.id, status="owner_withdrawn")
    db_session.add(
        CreatorPayoutApplication(
            user_id=reporter.id, status="pending", consented_at=kst(10, 21), privacy_version="2026-10-01"
        )
    )
    await db_session.flush()

    after = await report.load_pending(db_session)

    assert after.reports["작품"] - before.reports["작품"] == 1
    assert after.refunds_in_progress - before.refunds_in_progress == 1
    assert after.manual_payments - before.manual_payments == 2
    assert after.payout_applications - before.payout_applications == 1


def test_pending_says_it_is_the_value_at_run_time() -> None:
    pending = next(block for block in report.build_blocks(_digest()) if block[0].startswith("[처리 대기]"))

    assert "--date 로 지난 날을 다시 돌려도 지금 값" in pending[0]
    assert pending[1] == "신고: 작품 0 · 작품 댓글 0 · 채팅 응답 0 · 노벨 0 · 노벨 댓글 0"


# ── 식별 정보 ──────────────────────────────────────────────────────────────────
async def test_the_output_never_carries_member_or_order_identifiers(db_session: AsyncSession) -> None:
    real = await _member(
        db_session, created_at=kst(10, 21, 9), nickname="표식닉네임가", email="marker-real@example.com"
    )
    staff = await _member(
        db_session, exempt=True, created_at=kst(10, 21, 9), nickname="표식닉네임나", email="marker-staff@example.com"
    )
    payments = [
        await _make_payment(db_session, user_id=user.id, status="paid", paid_at=kst(10, 21, 10))
        for user in (real, staff)
    ]
    await _turns(db_session, await _room_of(db_session, real), kst(10, 21, 11))
    await _put_usage(_DAY, "chat_generate", calls=1, prompt=1_000)

    rendered = report.render(await report.load_digest(db_session, _DAY), dry_run=False)

    assert "결제 1건 9,900원" in rendered
    for secret in (
        str(real.id),
        str(staff.id),
        real.email,
        staff.email,
        real.nickname,
        staff.nickname,
        *(payment.payment_id for payment in payments),
        *(str(payment.id) for payment in payments),
    ):
        assert secret is not None
        assert secret not in rendered


# ── 메시지 나눔 ────────────────────────────────────────────────────────────────
_HEADER = f"{report.MESSAGE_HEADER} {_DAY} (KST)"


def _bodies(messages: list[str]) -> list[str]:
    """머리를 떼고 빈 줄을 뺀 본문 줄들, 순서대로."""
    return [line for message in messages for line in message.split("\n")[1:] if line]


def test_a_short_digest_is_one_message_under_the_plain_header() -> None:
    messages = report.split_messages(_HEADER, report.build_blocks(_digest()))

    assert len(messages) == 1
    assert messages[0].split("\n")[0] == _HEADER


def test_a_long_digest_is_split_between_blocks_without_losing_a_line() -> None:
    blocks = [[f"[항목 {b}]", *(f"{b}-{n} " + "가" * 80 for n in range(8))] for b in range(6)]

    messages = report.split_messages(_HEADER, blocks, limit=2_000)

    assert len(messages) > 1
    assert all(len(message) <= 2_000 for message in messages)
    assert [message.split("\n")[0] for message in messages] == [
        f"{_HEADER} ({n}/{len(messages)})" for n in range(1, len(messages) + 1)
    ]
    assert _bodies(messages) == [line for block in blocks for line in block]
    # 들어가는 항목은 쪼개지 않는다 — 각 항목의 머리와 끝 줄이 같은 통에 있다.
    for block in blocks:
        assert any(block[0] in message and block[-1] in message for message in messages)


def test_a_block_longer_than_one_message_is_split_between_lines() -> None:
    block = [f"줄 {n} " + "나" * 100 for n in range(40)]

    messages = report.split_messages(_HEADER, [["앞 항목"], block], limit=2_000)

    assert all(len(message) <= 2_000 for message in messages)
    assert _bodies(messages) == ["앞 항목", *block]


def test_the_real_digest_fits_when_every_section_is_full() -> None:
    """감시 조건이 모두 충족되고 LLM 줄이 꽉 찬 날도 통마다 상한 안이고, 줄을 잃지 않는다."""
    rows = [_usage(f"call_site_{n:02d}", calls=n + 1, prompt=(n + 1) * 10_000) for n in range(30)]
    blocks = report.build_blocks(_digest(llm=rows, watch=_all_watch_met()))

    messages = report.split_messages(_HEADER, blocks)

    assert len(messages) > 1
    assert all(len(message) <= report.MESSAGE_LIMIT for message in messages)
    assert _bodies(messages) == [line for block in blocks for line in block]


def test_dry_run_puts_a_prefix_before_every_header() -> None:
    rows = [_usage(f"call_site_{n:02d}", calls=1, prompt=10_000) for n in range(30)]

    rendered = report.render(_digest(llm=rows, watch=_all_watch_met()), dry_run=True)

    headers = [line for line in rendered.split("\n") if report.MESSAGE_HEADER in line]
    assert len(headers) > 1
    assert all(line.startswith(f"[dry-run] {report.MESSAGE_HEADER} {_DAY} (KST)") for line in headers)
    assert not any(line.startswith(report.MESSAGE_HEADER) for line in rendered.split("\n"))


# ── 실행 ───────────────────────────────────────────────────────────────────────
def test_main_prints_the_messages_and_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _load(day: date) -> report.Digest:
        return _digest(day=day)

    monkeypatch.setattr(report, "_load", _load)

    assert report.main(["--date", "2026-10-21"]) == 0
    assert capsys.readouterr().out.startswith(f"{report.MESSAGE_HEADER} 2026-10-21 (KST)\n")


def test_main_exits_1_when_the_database_read_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(day: date) -> report.Digest:
        raise RuntimeError("db down")

    monkeypatch.setattr(report, "_load", _fail)

    assert report.main(["--date", "2026-10-21"]) == 1


def test_main_exits_2_on_a_bad_date() -> None:
    with pytest.raises(SystemExit) as exit_:
        report.main(["--date", "어제"])

    assert exit_.value.code == 2


async def test_the_digest_reads_inside_a_read_only_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def _fake_load(session: AsyncSession, day: date, **_kwargs: object) -> report.Digest:
        seen.append((await session.execute(text("SHOW transaction_read_only"))).scalar_one())
        return _digest()

    monkeypatch.setattr(report, "load_digest", _fake_load)

    await report.read_digest(_DAY - timedelta(days=1))

    assert seen == ["on"]
