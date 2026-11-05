"""일일 운영 요약의 감시 조건(`api.ops_digest.watch`).

조건마다 문턱 바로 위·아래를 손으로 넣은 수치로 치고, DB 수치는 실사용자 거르기(면제·탈퇴)와 하루·기준 시각 경계를 본다. 누적
수치는 표 전체를 세므로 행을 넣기 전후의 차이로 단언한다. 사건 수치는 다른 테스트의 "지금"과 겹치지 않는 지난 날(2026-10-21
KST)을 쓴다.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatRoom, User
from api.db.models.chat import ChatMessageReport, DiscardedResponse
from api.db.models.content import Content, ContentType, ContentVersion, ContentVisibility, ModerationStatus
from api.db.models.moderation import Report, ReportReasonCategory, ReportStatus
from api.db.models.novel import NovelJob, NovelScreening
from api.db.models.payment import PaymentCancellation
from api.db.models.story import StartingSetup, StatDef
from api.ops_digest import watch
from api.ops_digest.report import day_window
from api.ops_digest.watch import WatchMetrics, load_watch_metrics, watch_lines
from factories import (
    _console_cancel,
    _grant_feature,
    _make_bare_chat_room,
    _make_novel_tree,
    _make_payment,
    _make_player,
    _make_public_novel,
    _make_user,
    kst,
)

_START, _END = day_window(kst(10, 21).date())


@pytest.mark.parametrize(
    ("met", "unmet", "phrase"),
    [
        pytest.param({"real_signups_since_baseline": 1}, {}, "실사용자 가입이 시작됐어요", id="signups"),
        pytest.param({"real_listed_works": 1}, {}, "공개 목록에 있어요", id="first-work"),
        pytest.param({"real_listed_works": 20}, {"real_listed_works": 19}, "홈 개인화", id="twenty-works"),
        pytest.param({"real_long_rooms": 5}, {"real_long_rooms": 4}, "30턴 이상", id="long-rooms"),
        pytest.param(
            {"real_undo_window": 30, "real_regenerate_window": 150},
            {"real_undo_window": 30, "real_regenerate_window": 151},
            "답변 갈래",
            id="undo-ratio",
        ),
        pytest.param(
            {"real_undo_window": 30},
            {"real_undo_window": 29},
            "재생성 0회",
            id="undo-without-regenerate",
        ),
        pytest.param({"real_peak_room_undo": 50}, {"real_peak_room_undo": 49}, "되돌리기 상한", id="room-undo"),
        pytest.param({"real_novelize_grants": 1}, {}, "소설화 허용 1명", id="novelize-grant"),
        pytest.param({"real_novel_premium_grants": 1}, {}, "상위 모델 허용 1명", id="premium-grant"),
        pytest.param({"novel_jobs_peak": 3}, {"novel_jobs_peak": 2}, "동시 최대 3건", id="jobs-peak"),
        pytest.param({"novel_jobs_waited": 1}, {}, "기다린 작업 1건", id="jobs-waited"),
        pytest.param({"novel_jobs_long": 1}, {}, "돈 작업 1건", id="jobs-long"),
        pytest.param({"chain_jobs_expired": 1}, {}, "연쇄 생성", id="chain-expired"),
        pytest.param({"real_readable_novels": 10}, {"real_readable_novels": 9}, "읽을 수 있는 노벨", id="novels"),
        pytest.param({"real_generated_chapters": 20}, {"real_generated_chapters": 19}, "생성 화가 20개", id="chapters"),
        pytest.param({"real_screening_rejections": 1}, {}, "자동 심사 거절", id="screening"),
        pytest.param({"minor_safety_reports": 1}, {}, "미성년 안전", id="minor-safety"),
        pytest.param({"hidden_stat_works": 1}, {}, "숨김 스탯", id="hidden-stats"),
        pytest.param({"real_double_refunded_payments": 1}, {}, "두 번 이상", id="double-refund"),
        pytest.param({"real_cancelled_payments_with_clovers": 1}, {}, "클로버가 남은", id="cancelled-clovers"),
    ],
)
def test_each_condition_is_met_at_its_threshold_and_not_below(
    met: dict[str, int], unmet: dict[str, int], phrase: str
) -> None:
    assert any(phrase in line for line in watch_lines(WatchMetrics(**met)))
    assert not any(phrase in line for line in watch_lines(WatchMetrics(**unmet)))


def test_nothing_is_met_on_a_quiet_day() -> None:
    assert watch_lines(WatchMetrics()) == []


def test_met_lines_carry_the_current_numbers() -> None:
    (line,) = watch_lines(WatchMetrics(real_long_rooms=7))

    assert line.startswith("30턴 이상인 실사용자 방이 7개예요(기준 5)")


# ── DB 수치 ────────────────────────────────────────────────────────────────────
async def _member(db: AsyncSession, *, exempt: bool = False, **overrides: object) -> User:
    user = _make_user(rate_limit_exempt=exempt, **overrides)
    db.add(user)
    await db.flush()
    return user


async def _room_of(db: AsyncSession, user: User, **values: object) -> ChatRoom:
    room = await _make_bare_chat_room(db)
    room.user_id = user.id
    for name, value in values.items():
        setattr(room, name, value)
    await db.flush()
    return room


async def _metrics(db: AsyncSession) -> WatchMetrics:
    return await load_watch_metrics(db, _START, _END)


async def _published_content(db: AsyncSession, creator: User) -> Content:
    content = Content(
        creator_user_id=creator.id,
        type=ContentType.STORY,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    version = ContentVersion(content_id=content.id, detail_description="설명")
    db.add(version)
    await db.flush()
    content.current_published_version_id = version.id
    await db.flush()
    return content


async def test_every_query_runs_and_a_quiet_day_has_no_events(db_session: AsyncSession) -> None:
    metrics = await load_watch_metrics(db_session, *day_window(kst(1, 1, year=2020).date()))

    assert (metrics.real_peak_room_undo, metrics.novel_jobs_peak, metrics.minor_safety_reports) == (0, 0, 0)


async def test_real_signups_count_living_non_exempt_members_from_the_baseline(db_session: AsyncSession) -> None:
    baseline = watch.REAL_SIGNUP_BASELINE
    before = await _metrics(db_session)
    await _member(db_session, created_at=baseline)
    await _member(db_session, created_at=baseline - timedelta(seconds=1))
    await _member(db_session, exempt=True, created_at=baseline + timedelta(days=1))
    await _member(db_session, created_at=baseline + timedelta(days=1), deleted_at=baseline + timedelta(days=2))

    after = await _metrics(db_session)

    assert after.real_signups_since_baseline - before.real_signups_since_baseline == 1


async def test_listed_works_and_long_rooms_leave_out_exempt_owners(db_session: AsyncSession) -> None:
    before = await _metrics(db_session)
    real, staff = await _member(db_session), await _member(db_session, exempt=True)
    await _published_content(db_session, real)
    await _published_content(db_session, staff)
    await _room_of(db_session, real, turn_count=30)
    await _room_of(db_session, real, turn_count=29)
    await _room_of(db_session, staff, turn_count=30)

    after = await _metrics(db_session)

    assert after.real_listed_works - before.real_listed_works == 1
    assert after.real_long_rooms - before.real_long_rooms == 1


async def test_undo_counts_the_28_day_window_and_the_busiest_room_of_the_day(db_session: AsyncSession) -> None:
    real, staff = await _member(db_session), await _member(db_session, exempt=True)
    busy, quiet = await _room_of(db_session, real), await _room_of(db_session, real)
    staff_room = await _room_of(db_session, staff)

    def discard(room: ChatRoom, kind: str, at: datetime) -> DiscardedResponse:
        return DiscardedResponse(
            user_id=room.user_id, chat_room_id=room.id, kind=kind, discarded_count=1, created_at=at
        )

    db_session.add_all(
        [
            *(discard(busy, "undo", kst(10, 21, hour)) for hour in (0, 12, 23)),
            discard(quiet, "undo", kst(10, 21, 9)),
            *(discard(staff_room, "undo", kst(10, 21, 9)) for _ in range(5)),
            discard(quiet, "undo", kst(9, 24)),
            discard(quiet, "undo", kst(9, 23, 23, 59, 59)),
            discard(quiet, "undo", kst(10, 22)),
            discard(quiet, "regenerate", kst(10, 21, 9)),
            discard(quiet, "regenerate", kst(10, 21, 10)),
        ]
    )
    await db_session.flush()

    metrics = await _metrics(db_session)

    assert (metrics.real_undo_window, metrics.real_regenerate_window) == (5, 2)
    assert metrics.real_peak_room_undo == 3


async def test_novel_grants_count_non_exempt_members_per_feature(db_session: AsyncSession) -> None:
    before = await _metrics(db_session)
    real, staff = await _member(db_session), await _member(db_session, exempt=True)
    await _grant_feature(db_session, real.id, "novelize")
    await _grant_feature(db_session, real.id, "novelize_premium_models")
    await _grant_feature(db_session, staff.id, "novelize")

    after = await _metrics(db_session)

    assert after.real_novelize_grants - before.real_novelize_grants == 1
    assert after.real_novel_premium_grants - before.real_novel_premium_grants == 1


async def test_novel_job_peak_wait_and_run_time_of_the_day(db_session: AsyncSession) -> None:
    writer = await _member(db_session)
    novel_id = (await _make_novel_tree(db_session, writer.id)).novel.id

    def job(started: datetime | None, finished: datetime | None, **values: object) -> NovelJob:
        return NovelJob(
            novel_id=novel_id,
            user_id=writer.id,
            kind="chapter_generate",
            status="failed" if "failure_code" in values else "succeeded",
            charged_amount=1,
            started_at=started,
            finished_at=finished,
            **values,
        )

    db_session.add_all(
        [
            # 10:02 에 셋이 함께 돈다(10:00~10:03, 10:01~10:02:30, 10:02~10:04).
            job(kst(10, 21, 10), kst(10, 21, 10, 3)),
            job(kst(10, 21, 10, 1), kst(10, 21, 10, 2, 30)),
            job(kst(10, 21, 10, 2), kst(10, 21, 10, 4)),
            # 대기: 61초는 넘김, 60초는 아님, 시작 못 하고 만료는 넘김.
            job(kst(10, 21, 11, 1, 1), kst(10, 21, 11, 1, 11), created_at=kst(10, 21, 11)),
            job(kst(10, 21, 11, 1), kst(10, 21, 11, 1, 10), created_at=kst(10, 21, 11)),
            job(None, kst(10, 21, 11, 2), created_at=kst(10, 21, 11), failure_code="expired"),
            # 실행 시간: 300초는 넘김, 299초는 아님.
            job(kst(10, 21, 12), kst(10, 21, 12, 5)),
            job(kst(10, 21, 13), kst(10, 21, 13, 4, 59)),
        ]
    )
    await db_session.flush()

    metrics = await _metrics(db_session)

    assert (metrics.novel_jobs_peak, metrics.novel_jobs_waited, metrics.novel_jobs_long) == (3, 2, 1)


async def test_novel_conditions_leave_out_exempt_publishers_and_writers(db_session: AsyncSession) -> None:
    before = await _metrics(db_session)
    real, staff = await _member(db_session), await _member(db_session, exempt=True)
    await _make_public_novel(db_session, real.id, batches=(1,))
    await _make_public_novel(db_session, staff.id, batches=(1,))
    real_tree = await _make_novel_tree(db_session, real.id)
    await _make_novel_tree(db_session, staff.id)
    db_session.add_all(
        NovelScreening(
            novel_id=real_tree.novel.id,
            user_id=user.id,
            outcome="rejected",
            flagged_parts=["synopsis"],
            model="test",
            created_at=at,
        )
        for user, at in ((real, kst(10, 21, 9)), (staff, kst(10, 21, 9)), (real, kst(10, 22)))
    )
    await db_session.flush()

    after = await _metrics(db_session)

    assert after.real_readable_novels - before.real_readable_novels == 1
    # 공개 소설의 화 하나와 소설 한 권의 생성 개정 하나. 되돌리기 개정은 세지 않는다.
    assert after.real_generated_chapters - before.real_generated_chapters == 2
    assert after.real_screening_rejections == 1


async def test_minor_safety_reports_count_real_reporters_of_the_day_across_tables(db_session: AsyncSession) -> None:
    real, staff = await _member(db_session), await _member(db_session, exempt=True)
    content = await _published_content(db_session, real)

    def work_report(reporter: User, reason: ReportReasonCategory, at: datetime) -> Report:
        return Report(
            reporter_user_id=reporter.id,
            content_id=content.id,
            reason_category=reason,
            status=ReportStatus.PENDING,
            created_at=at,
        )

    db_session.add_all(
        [
            work_report(real, ReportReasonCategory.MINOR_SAFETY, kst(10, 21, 23, 59, 59)),
            work_report(staff, ReportReasonCategory.MINOR_SAFETY, kst(10, 21, 9)),
            work_report(real, ReportReasonCategory.SPAM, kst(10, 21, 9)),
            work_report(real, ReportReasonCategory.MINOR_SAFETY, kst(10, 22)),
            ChatMessageReport(
                reporter_user_id=real.id, reason="minor_safety", status=ReportStatus.PENDING, created_at=kst(10, 21)
            ),
        ]
    )
    await db_session.flush()

    metrics = await _metrics(db_session)

    assert metrics.minor_safety_reports == 2


async def test_hidden_stat_works_count_the_published_version_only(db_session: AsyncSession) -> None:
    before = await _metrics(db_session)
    creator = await _member(db_session)
    for hidden in (True, False):
        content = await _published_content(db_session, creator)
        assert content.current_published_version_id is not None
        setup = StartingSetup(
            entity_id=uuid.uuid4(),
            content_version_id=content.current_published_version_id,
            name="시작",
            prologue="프롤로그",
            order=0,
        )
        db_session.add(setup)
        await db_session.flush()
        db_session.add(
            StatDef(
                entity_id=uuid.uuid4(),
                starting_setup_id=setup.id,
                name="호감",
                icon="heart",
                color="red",
                min_value=0,
                max_value=100,
                initial_value=0,
                description="설명",
                order=0,
                hidden_from_player=hidden,
            )
        )
    await db_session.flush()

    after = await _metrics(db_session)

    assert after.hidden_stat_works - before.hidden_stat_works == 1


async def test_payment_conditions_leave_out_exempt_and_withdrawn_payers(db_session: AsyncSession) -> None:
    before = await _metrics(db_session)
    real, staff = await _member(db_session), await _member(db_session, exempt=True)
    for payer, statuses in (
        (real, ("succeeded", "succeeded")),
        (real, ("succeeded", "failed")),
        (staff, ("succeeded", "succeeded")),
    ):
        payment = await _make_payment(db_session, user_id=payer.id, status="partially_cancelled")
        db_session.add_all(
            PaymentCancellation(payment_id=payment.id, source="console", status=status, amount_krw=100)
            for status in statuses
        )
    # 전액 취소 뒤 클로버가 남은 결제: 실사용자 1건만 센다. 회수를 마친 결제·내부·탈퇴 회원은 빠진다.
    kept = await _make_player(db_session, amount_krw=9_900, paid=3_300)
    revoked = await _make_player(db_session, amount_krw=9_900, paid=3_300)
    await _console_cancel(db_session, revoked.payment, 9_900, kst(10, 21))
    tester = await _make_player(db_session, amount_krw=9_900, paid=3_300)
    tester.user.rate_limit_exempt = True
    gone = await _make_player(db_session, amount_krw=9_900, paid=3_300)
    gone.user.deleted_at = kst(10, 21)
    for player in (kept, revoked, tester, gone):
        player.payment.status = "cancelled"
    await db_session.flush()

    after = await _metrics(db_session)

    assert after.real_double_refunded_payments - before.real_double_refunded_payments == 1
    assert after.real_cancelled_payments_with_clovers - before.real_cancelled_payments_with_clovers == 1
