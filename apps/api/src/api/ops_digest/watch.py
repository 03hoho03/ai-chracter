"""일일 운영 요약 끝에 붙는 감시 조건 — "실사용자가 생기면 할 일" 가운데 DB 로 판정할 수 있는 것.

조건마다 수치 하나 이상(`WatchMetrics`)과 문장 하나가 있고, 충족한 조건만 요약 끝에 한 줄씩 싣는다. 조건의 정의(문턱·문장)는
아래 `WATCH_CONDITIONS` 한 곳이다 — 할 일을 처리하면 그 조건을 여기서 지운다. 누적 조건은 충족한 뒤 매일 같은 줄이 다시 실리는데,
지울 때까지 남기는 상기가 의도다.

- 실사용자는 레이트리밋 면제가 아닌 회원이다(요약 본문과 같은 기준, 실행 시각의 면제 값). 가입·공개 작품·긴 방·취소 뒤 남은
  클로버는 탈퇴 회원도 뺀다 — 탈퇴한 계정은 지금 실사용자가 아니고, 남은 클로버는 탈퇴로 소멸한다. 기능 허용은 탈퇴가 지우고,
  읽을 수 있는 노벨은 그 조건 함수가 탈퇴 게시자를 거른다. 되돌리기·신고·심사·생성 개정·결제처럼 탈퇴해도 남는 기록은 면제 칸만
  본다 — 탈퇴 전에 실제로 일어난 일이다.
- 누적 조건은 실행 시각의 상태를, 사건 조건은 요약하는 KST 하루(되돌리기 비율은 그날까지 28일)를 센다.
- 공개 목록·읽을 수 있는 노벨 판정은 목록 화면이 쓰는 조건 함수를 그대로 쓴다 — 조건을 새로 쓰면 목록과 감시가 갈린다.
- 회원 id·작품 id 를 상수로 박지 않는다(저장소가 공개이고 요약은 식별 정보를 싣지 않는다). 설치 때 이미 참인 조건은 기준 시각을
  두는 꼴로 바꾼다 — 실사용자 가입이 처음부터 그 꼴이다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, Select, and_, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from api.content.access import publicly_listed_conditions
from api.core.rate_limit import KST
from api.db.models.auth import User
from api.db.models.chat import ChatMessageReport, ChatRoom, DiscardedResponse
from api.db.models.clover import CloverLot
from api.db.models.comments import CommentReport
from api.db.models.content import Content, ModerationStatus
from api.db.models.feature_grant import UserFeatureGrant
from api.db.models.moderation import Report, ReportReasonCategory
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterRevision,
    NovelCommentReport,
    NovelJob,
    NovelReport,
    NovelScreening,
)
from api.db.models.payment import Payment, PaymentCancellation
from api.db.models.story import StartingSetup, StatDef
from api.novel_public.access import select_readable_publications

# 실사용자 가입을 세기 시작하는 시각. 그 전에 만든 면제 아닌 계정(시험·결제 심사용)이 있어 "면제 아닌 회원이 있다"만으로는
# 설치하자마자 참이 된다. 크론을 켜는 날에 맞춘다.
REAL_SIGNUP_BASELINE = datetime(2026, 11, 6, tzinfo=KST)
# 공개 작품 수 두 문턱 — 첫 작품은 닉네임 사칭 대책의 마감이고(섞이기 전에 해야 한다), 스무 편은 홈 개인화·신인 섹션을 채울
# 모집단이다.
LISTED_WORKS_FIRST = 1
LISTED_WORKS_FOR_SECTIONS = 20
# 요약 접기가 처음 도는 턴 — 그 아래 방에서는 기억·요약 기능이 발동하지 않아 측정할 것이 없다.
LONG_ROOM_TURNS = 30
LONG_ROOMS_MIN = 5
UNDO_WINDOW_DAYS = 28
UNDO_MIN = 30
UNDO_PER_REGENERATE_MIN = 0.2
ROOM_UNDO_PER_DAY_MIN = 50
# 소설화 워커 동시 상한(4)을 다시 열 신호 — 동시 3건, 60초 넘는 대기, 장 실행 상한(360초)에 근접한 300초.
NOVEL_JOBS_PEAK_MIN = 3
NOVEL_JOB_WAIT = timedelta(seconds=60)
NOVEL_JOB_LONG_RUN = timedelta(seconds=300)
# 연쇄 생성은 다른 작업과 칸을 다투지 않아 동시·대기·실행 시간에서 뺀다.
CHAIN_JOB_KIND = "chain_generate"
READABLE_NOVELS_MIN = 10
# 소설 레인 지시문 보강을 운영에 게시한 시각. 그 뒤 생성 개정만 보강 효과의 표본이다.
NOVEL_DIRECTIVE_PUBLISHED_AT = datetime(2026, 10, 9, 7, 19, tzinfo=UTC)
GENERATED_CHAPTERS_MIN = 20


@dataclass(frozen=True)
class WatchMetrics:
    real_signups_since_baseline: int = 0
    real_listed_works: int = 0
    real_long_rooms: int = 0
    real_undo_window: int = 0
    real_regenerate_window: int = 0
    real_peak_room_undo: int = 0
    real_novelize_grants: int = 0
    real_novel_premium_grants: int = 0
    novel_jobs_peak: int = 0
    novel_jobs_waited: int = 0
    novel_jobs_long: int = 0
    chain_jobs_expired: int = 0
    real_readable_novels: int = 0
    real_generated_chapters: int = 0
    real_screening_rejections: int = 0
    minor_safety_reports: int = 0
    hidden_stat_works: int = 0
    real_double_refunded_payments: int = 0
    real_cancelled_payments_with_clovers: int = 0


@dataclass(frozen=True)
class WatchCondition:
    met: Callable[[WatchMetrics], bool]
    line: Callable[[WatchMetrics], str]


def _undo_ratio_met(m: WatchMetrics) -> bool:
    if m.real_undo_window < UNDO_MIN:
        return False
    # 재생성이 0 이면 비율이 무한대다 — 되돌리기만 쓰이는 것도 신호다.
    return m.real_regenerate_window == 0 or m.real_undo_window / m.real_regenerate_window >= UNDO_PER_REGENERATE_MIN


def _undo_ratio_text(m: WatchMetrics) -> str:
    if m.real_regenerate_window == 0:
        return "재생성 0회"
    return f"재생성 대비 {m.real_undo_window / m.real_regenerate_window:.0%}"


WATCH_CONDITIONS: tuple[WatchCondition, ...] = (
    WatchCondition(
        lambda m: m.real_signups_since_baseline >= 1,
        lambda m: (
            f"실사용자 가입이 시작됐어요({REAL_SIGNUP_BASELINE:%Y-%m-%d} 뒤 {m.real_signups_since_baseline}명)"
            " — 실사용자 전에 하기로 한 처리방침 법률 검토·법무 묶음 게시와 결제 심사용 계정의 수동 인증 표시 정리를 할 때예요"
        ),
    ),
    WatchCondition(
        lambda m: m.real_listed_works >= LISTED_WORKS_FIRST,
        lambda m: f"실사용자 작품이 공개 목록에 있어요({m.real_listed_works}편) — 브랜드 닉네임 사칭 대책을 볼 때예요",
    ),
    WatchCondition(
        lambda m: m.real_listed_works >= LISTED_WORKS_FOR_SECTIONS,
        lambda m: (
            f"실사용자 공개 작품이 {m.real_listed_works}편이에요(기준 {LISTED_WORKS_FOR_SECTIONS})"
            " — 홈 개인화·신인 섹션을 다시 볼 수 있어요"
        ),
    ),
    WatchCondition(
        lambda m: m.real_long_rooms >= LONG_ROOMS_MIN,
        lambda m: (
            f"{LONG_ROOM_TURNS}턴 이상인 실사용자 방이 {m.real_long_rooms}개예요(기준 {LONG_ROOMS_MIN})"
            " — 기억·요약·스탯 판정의 실사용 측정을 돌릴 때예요"
        ),
    ),
    WatchCondition(
        _undo_ratio_met,
        lambda m: (
            f"최근 {UNDO_WINDOW_DAYS}일 실사용자 되돌리기 {m.real_undo_window}회, {_undo_ratio_text(m)}예요"
            f"(기준 {UNDO_MIN}회·{UNDO_PER_REGENERATE_MIN:.0%}) — 답변 갈래 보존을 다시 볼 신호예요"
        ),
    ),
    WatchCondition(
        lambda m: m.real_peak_room_undo >= ROOM_UNDO_PER_DAY_MIN,
        lambda m: (
            f"그날 한 방에서 실사용자 되돌리기가 {m.real_peak_room_undo}회였어요(기준 {ROOM_UNDO_PER_DAY_MIN})"
            " — 되돌리기 상한을 볼 때예요"
        ),
    ),
    WatchCondition(
        lambda m: m.real_novelize_grants >= 1 or m.real_novel_premium_grants >= 1,
        lambda m: (
            f"운영자 밖 계정에 소설화 허용 {m.real_novelize_grants}명·소설 상위 모델 허용"
            f" {m.real_novel_premium_grants}명이 있어요 — 허용 전 선행 조건(소설 지우기 화면·주기 만료 환불 정리·원가 관측·"
            "법률 확인)을 확인했는지 보세요"
        ),
    ),
    WatchCondition(
        lambda m: m.novel_jobs_peak >= NOVEL_JOBS_PEAK_MIN or m.novel_jobs_waited >= 1 or m.novel_jobs_long >= 1,
        lambda m: (
            f"그날 소설화 작업: 동시 최대 {m.novel_jobs_peak}건(기준 {NOVEL_JOBS_PEAK_MIN})·"
            f"{NOVEL_JOB_WAIT.seconds}초 넘게 기다린 작업 {m.novel_jobs_waited}건·"
            f"{NOVEL_JOB_LONG_RUN.seconds}초 이상 돈 작업 {m.novel_jobs_long}건 — 워커 동시 상한을 다시 볼 때예요"
        ),
    ),
    WatchCondition(
        lambda m: m.chain_jobs_expired >= 1,
        lambda m: (
            f"그날 만료로 끝난 연쇄 생성이 {m.chain_jobs_expired}건이에요 — 연쇄 생성을 워커로 옮길 근거예요"
            "(그날 배포 교체 시각과 맞춰 보세요)"
        ),
    ),
    WatchCondition(
        lambda m: m.real_readable_novels >= READABLE_NOVELS_MIN,
        lambda m: (
            f"실사용자가 공개한 읽을 수 있는 노벨이 {m.real_readable_novels}편이에요(기준 {READABLE_NOVELS_MIN})"
            " — 홈 노벨 대체 정렬·어드민 노벨 검색을 볼 때예요"
        ),
    ),
    WatchCondition(
        lambda m: m.real_generated_chapters >= GENERATED_CHAPTERS_MIN,
        lambda m: (
            f"소설 지시문 보강 게시({NOVEL_DIRECTIVE_PUBLISHED_AT:%Y-%m-%d}) 뒤 실사용자 생성 화가"
            f" {m.real_generated_chapters}개예요(기준 {GENERATED_CHAPTERS_MIN}) — 보강 효과를 운영 통계로 다시 잴 때예요"
        ),
    ),
    WatchCondition(
        lambda m: m.real_screening_rejections >= 1,
        lambda m: (
            f"그날 실사용자 노벨 자동 심사 거절이 {m.real_screening_rejections}건이에요"
            " — 거절이 맞는지(오탐인지) 어드민 노벨 상세에서 확인하세요"
        ),
    ),
    WatchCondition(
        lambda m: m.minor_safety_reports >= 1,
        lambda m: (
            f"그날 미성년 안전 사유 신고가 {m.minor_safety_reports}건이에요"
            " — 신고 사본이 90일 뒤 사라지니 그 전에 원문을 모으세요"
        ),
    ),
    WatchCondition(
        lambda m: m.hidden_stat_works >= 1,
        lambda m: (
            f"숨김 스탯을 쓰는 작품이 발행돼 있어요({m.hidden_stat_works}편)"
            " — 플레이어 방 응답·스트림에서 숨김이 지켜지는지 확인하세요"
        ),
    ),
    WatchCondition(
        lambda m: m.real_double_refunded_payments >= 1,
        lambda m: (
            f"환불이 두 번 이상 성공한 실사용자 결제가 {m.real_double_refunded_payments}건이에요"
            " — 두 번째 환불 견적이 맞았는지 확인하세요"
        ),
    ),
    WatchCondition(
        lambda m: m.real_cancelled_payments_with_clovers >= 1,
        lambda m: (
            f"전액 취소 뒤 클로버가 남은 실사용자 결제가 {m.real_cancelled_payments_with_clovers}건이에요"
            " — 탈퇴 화면의 유료 잔액 경고 문구를 확인하세요"
        ),
    ),
)


def watch_lines(metrics: WatchMetrics) -> list[str]:
    """충족한 조건의 문장, 정의 순서대로."""
    return [condition.line(metrics) for condition in WATCH_CONDITIONS if condition.met(metrics)]


_REAL = User.rate_limit_exempt.is_(False)
_ALIVE = User.deleted_at.is_(None)


async def _count(session: AsyncSession, statement: Select[tuple[int]]) -> int:
    return (await session.scalar(statement)) or 0


async def load_watch_metrics(session: AsyncSession, start: datetime, end: datetime) -> WatchMetrics:
    """`start`~`end`(요약하는 KST 하루의 반열린 구간)와 지금 상태로 감시 수치를 읽는다. SELECT 만 한다."""

    def in_day(column: InstrumentedAttribute[datetime] | InstrumentedAttribute[datetime | None]) -> ColumnElement[bool]:
        return and_(column >= start, column < end)

    window_start = start - timedelta(days=UNDO_WINDOW_DAYS - 1)
    undo, regenerate = (
        await session.execute(
            select(
                func.count().filter(DiscardedResponse.kind == "undo"),
                func.count().filter(DiscardedResponse.kind == "regenerate"),
            )
            .select_from(DiscardedResponse)
            .join(User, User.id == DiscardedResponse.user_id)
            .where(_REAL, DiscardedResponse.created_at >= window_start, DiscardedResponse.created_at < end)
        )
    ).one()
    room_undo = (
        select(func.count().label("undo_count"))
        .select_from(DiscardedResponse)
        .join(User, User.id == DiscardedResponse.user_id)
        .where(
            _REAL,
            DiscardedResponse.kind == "undo",
            DiscardedResponse.chat_room_id.is_not(None),
            in_day(DiscardedResponse.created_at),
        )
        .group_by(DiscardedResponse.chat_room_id)
        .subquery()
    )
    novelize, novel_premium = (
        await session.execute(
            select(
                func.count().filter(UserFeatureGrant.feature == "novelize"),
                func.count().filter(UserFeatureGrant.feature == "novelize_premium_models"),
            )
            .select_from(UserFeatureGrant)
            .join(User, User.id == UserFeatureGrant.user_id)
            .where(_REAL)
        )
    ).one()

    # 그날 시작한 작업마다 그 순간 돌던 작업 수(자기 포함). 아직 안 끝난 작업은 지금까지 도는 것으로 본다.
    job, other = aliased(NovelJob), aliased(NovelJob)
    running_at_start = (
        select(func.count(other.id).label("running"))
        .select_from(job)
        .join(
            other,
            and_(
                other.kind != CHAIN_JOB_KIND,
                other.started_at <= job.started_at,
                func.coalesce(other.finished_at, func.now()) > job.started_at,
            ),
        )
        .where(job.kind != CHAIN_JOB_KIND, in_day(job.started_at))
        .group_by(job.id)
        .subquery()
    )
    not_chain = NovelJob.kind != CHAIN_JOB_KIND
    waited = or_(
        and_(NovelJob.started_at.is_not(None), NovelJob.started_at - NovelJob.created_at > NOVEL_JOB_WAIT),
        and_(NovelJob.started_at.is_(None), NovelJob.failure_code == "expired"),
    )
    long_run = and_(NovelJob.finished_at.is_not(None), NovelJob.finished_at - NovelJob.started_at >= NOVEL_JOB_LONG_RUN)

    generated_chapters = (
        select(func.count())
        .select_from(NovelChapterRevision)
        .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
        .join(Novel, Novel.id == NovelChapter.novel_id)
        .join(User, User.id == Novel.user_id)
        .where(
            _REAL,
            NovelChapterRevision.source.in_(("generate", "regenerate")),
            NovelChapterRevision.created_at >= NOVEL_DIRECTIVE_PUBLISHED_AT,
        )
    )

    minor_safety = 0
    for reporter, created_at, reason in (
        (Report.reporter_user_id, Report.created_at, Report.reason_category == ReportReasonCategory.MINOR_SAFETY),
        (
            CommentReport.reporter_user_id,
            CommentReport.created_at,
            CommentReport.reason_category == ReportReasonCategory.MINOR_SAFETY,
        ),
        (ChatMessageReport.reporter_user_id, ChatMessageReport.created_at, ChatMessageReport.reason == "minor_safety"),
        (
            NovelReport.reporter_user_id,
            NovelReport.created_at,
            NovelReport.reason_category == ReportReasonCategory.MINOR_SAFETY,
        ),
        (
            NovelCommentReport.reporter_user_id,
            NovelCommentReport.created_at,
            NovelCommentReport.reason_category == ReportReasonCategory.MINOR_SAFETY,
        ),
    ):
        minor_safety += await _count(
            session,
            select(func.count())
            .select_from(reporter.class_)
            .join(User, User.id == reporter)
            .where(_REAL, reason, in_day(created_at)),
        )

    refunded_twice = (
        select(PaymentCancellation.payment_id)
        .where(PaymentCancellation.status == "succeeded")
        .group_by(PaymentCancellation.payment_id)
        .having(func.count() >= 2)
        .subquery()
    )

    return WatchMetrics(
        real_signups_since_baseline=await _count(
            session,
            select(func.count()).select_from(User).where(_REAL, _ALIVE, User.created_at >= REAL_SIGNUP_BASELINE),
        ),
        real_listed_works=await _count(
            session,
            select(func.count())
            .select_from(Content)
            .join(User, User.id == Content.creator_user_id)
            .where(_REAL, _ALIVE, *publicly_listed_conditions()),
        ),
        real_long_rooms=await _count(
            session,
            select(func.count())
            .select_from(ChatRoom)
            .join(User, User.id == ChatRoom.user_id)
            .where(_REAL, _ALIVE, ChatRoom.turn_count >= LONG_ROOM_TURNS),
        ),
        real_undo_window=undo,
        real_regenerate_window=regenerate,
        real_peak_room_undo=await _count(session, select(func.max(room_undo.c.undo_count))),
        real_novelize_grants=novelize,
        real_novel_premium_grants=novel_premium,
        novel_jobs_peak=await _count(session, select(func.max(running_at_start.c.running))),
        novel_jobs_waited=await _count(
            session, select(func.count()).select_from(NovelJob).where(not_chain, in_day(NovelJob.created_at), waited)
        ),
        novel_jobs_long=await _count(
            session, select(func.count()).select_from(NovelJob).where(not_chain, in_day(NovelJob.started_at), long_run)
        ),
        chain_jobs_expired=await _count(
            session,
            select(func.count())
            .select_from(NovelJob)
            .where(
                NovelJob.kind == CHAIN_JOB_KIND,
                NovelJob.status == "failed",
                NovelJob.failure_code == "expired",
                in_day(NovelJob.finished_at),
            ),
        ),
        real_readable_novels=await _count(session, select_readable_publications(func.count()).where(_REAL)),
        real_generated_chapters=await _count(session, generated_chapters),
        real_screening_rejections=await _count(
            session,
            select(func.count())
            .select_from(NovelScreening)
            .join(User, User.id == NovelScreening.user_id)
            .where(_REAL, NovelScreening.outcome == "rejected", in_day(NovelScreening.created_at)),
        ),
        minor_safety_reports=minor_safety,
        hidden_stat_works=await _count(
            session,
            select(func.count(distinct(Content.id)))
            .select_from(Content)
            .join(StartingSetup, StartingSetup.content_version_id == Content.current_published_version_id)
            .join(StatDef, StatDef.starting_setup_id == StartingSetup.id)
            .where(StatDef.hidden_from_player.is_(True), Content.moderation_status == ModerationStatus.NORMAL),
        ),
        real_double_refunded_payments=await _count(
            session,
            select(func.count())
            .select_from(Payment)
            .join(refunded_twice, refunded_twice.c.payment_id == Payment.id)
            .join(User, User.id == Payment.user_id)
            .where(_REAL),
        ),
        real_cancelled_payments_with_clovers=await _count(
            session,
            select(func.count(distinct(Payment.id)))
            .select_from(Payment)
            .join(User, User.id == Payment.user_id)
            .join(CloverLot, CloverLot.payment_id == Payment.id)
            .where(_REAL, _ALIVE, Payment.status == "cancelled", CloverLot.remaining > 0),
        ),
    )
