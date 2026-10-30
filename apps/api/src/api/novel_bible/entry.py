"""정본 기억의 바깥 입구 — 어드민 내부 API, 측정 하네스, 소설화 워커가 부른다. 코어 함수에 실제 등록부(`registry.REGISTRY`)와
규칙 목록(`rules.RULES`), 어댑터 해석기(`adapters/resolver.py` 의 `build_resolver`)를 넘기는 자리다. 스위치(`novel_bible_enabled`)가
꺼져 있으면 확정을 받지 않고, 워커는 처리기(`BibleWorker`)를 만들지 않는다."""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleFinding, NovelBibleJob, NovelBibleRevision
from api.novel_bible.adapters.resolver import build_resolver
from api.novel_bible.core import pipeline
from api.novel_bible.core.confirm import Actor, ConfirmResult, confirm
from api.novel_bible.core.contracts import AdapterResolver
from api.novel_bible.core.jobs import SessionFactory, run_next_job
from api.novel_bible.core.queries import bible_at
from api.novel_bible.core.render import verify_prompt_chains
from api.novel_bible.core.sweep import BIBLE_TASK_TIMEOUT_SECONDS, expire_stale_work
from api.novel_bible.core.types import BibleSnapshot
from api.novel_bible.ids import CommitFailure, CommitStatus, FindingSeverity, JobFailure, JobStatus, SlotId
from api.novel_bible.registry import REGISTRY
from api.novel_bible.rules import RULES

logger = logging.getLogger(__name__)


class BibleDisabledError(Exception):
    """정본 기억 스위치가 꺼져 있다."""


class BiblePromptMissingError(Exception):
    """확정이 만들 작업에 배정된 어댑터의 문안 체인에 그 슬롯 채널이 없다 — 받아도 작업이 문안 없음으로 실패할 뿐이다."""


async def confirm_chapter(
    db: AsyncSession,
    *,
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    revision_id: uuid.UUID,
    actor: Actor,
    slots: frozenset[SlotId] | None = None,
    resolver: AdapterResolver | None = None,
) -> ConfirmResult:
    """화 개정 하나를 확정으로 받는다. `slots` 는 측정에서 슬롯 일부만 돌릴 때(None = 등록부 전부), `resolver` 는 측정이 어댑터를
    바꿔 끼울 때(None = 코드 표와 env 덮어쓰기). 커밋은 호출부가 한다."""
    if not settings.novel_bible_enabled:
        raise BibleDisabledError
    missing = await verify_prompt_chains(db, REGISTRY, resolver or build_resolver(), slots=slots)
    if missing:
        raise BiblePromptMissingError(", ".join(missing))
    return await confirm(
        db, REGISTRY, novel_id=novel_id, chapter_id=chapter_id, revision_id=revision_id, actor=actor, slots=slots
    )


async def run_until_idle(
    session_factory: SessionFactory, resolver: AdapterResolver, *, novel_id: uuid.UUID | None = None,
    max_steps: int = 1_000,
) -> int:
    """워커가 하는 일(준비된 확정 처리 → 대기 작업 실행)을 이 프로세스 안에서 할 일이 없을 때까지 한다. 돌린 단계 수를
    돌려준다. 측정 하네스가 워커 없이 쓴다."""
    return await pipeline.run_until_idle(
        session_factory, REGISTRY, RULES, resolver, novel_id=novel_id, max_steps=max_steps
    )


class BibleWorker:
    """소설화 워커 프로세스 안의 정본 기억 처리기. 워커 루프가 스위치가 켜졌을 때만 `start` 로 만들고, 바퀴마다 `poll` 을, 소설
    작업 만료 정리와 같은 주기로 `sweep` 을 부른다. 동시 상한은 소설 작업과 따로 센다(`novel_bible_worker_max_concurrent`) — 내부
    기능이 사용자 소설 작업 자리를 먹지 않게.

    칸 하나는 할 일 하나다: 측정 하네스(`run_until_idle`)의 한 단계와 같이 준비된 확정 하나를 먼저 처리하고, 없으면 대기 작업
    하나를 돌린다. 고르기는 그 태스크 안에서 코어 함수가 한다 — 잠긴 행을 건너뛰고 고른 뒤 조건부 전이로 받으므로, 교체 겹침에
    워커 둘이 함께 골라도 한 행은 한쪽만 돈다. 한 칸은 `BIBLE_TASK_TIMEOUT_SECONDS` 안에 끝나거나 끊긴다. 끊기거나 취소된
    처리가 남긴 실행 중 작업·연결 중 확정은 만료 정리가 되돌린다."""

    def __init__(self, session_factory: SessionFactory, resolver: AdapterResolver) -> None:
        self._session_factory = session_factory
        self._resolver = resolver

    @classmethod
    async def start(cls, session_factory: SessionFactory) -> "BibleWorker | None":
        """등록부의 추출 슬롯마다 배정된 어댑터의 문안 체인에 슬롯 채널이 있는지 한 번 본다. 없거나 그 검사가 실패하면 정본
        기억만 끈 채(None) 오류를 남긴다 — 소설 작업을 정본 기억 문안 결함으로 멈추지 않는다. 다시 켜려면 워커를 재기동한다.

        어댑터에 모델 클라이언트를 넘기지 않는다 — 어댑터는 부를 때 앱의 클라이언트(`get_llm_client`, 프로세스에 하나)를 얻으므로
        워커가 쓰는 것과 같고, 이 모듈이 모델 호출 계층을 import 하지 않는다."""
        resolver = build_resolver()
        try:
            async with session_factory() as session:
                missing = await verify_prompt_chains(session, REGISTRY, resolver)
        except Exception as exc:
            logger.error("정본 기억 문안 검사에 실패해 이 워커는 정본 기억을 돌리지 않는다: %s", type(exc).__name__)
            capture_dependency_failure(exc, dependency="novelize")
            return None
        if missing:
            logger.error("정본 기억 문안에 슬롯 채널이 없어 이 워커는 정본 기억을 돌리지 않는다: %s", ", ".join(missing))
            capture_dependency_failure(BiblePromptMissingError(", ".join(missing)), dependency="novelize")
            return None
        return cls(session_factory, resolver)

    def poll(self, active: set[asyncio.Task[None]], free: int) -> None:
        """빈 칸마다 할 일 하나를 맡은 태스크를 띄운다. 할 일이 없으면 그 태스크는 고르기만 하고 끝난다."""
        for _ in range(free):
            active.add(asyncio.create_task(self._step()))

    async def _step(self) -> None:
        # 실패는 삼키고 남긴다 — 정본 기억 조회 실패가 워커의 살아 있음 판정(소설 고르기 성공에 묶임)을 흔들지 않는다.
        try:
            async with asyncio.timeout(BIBLE_TASK_TIMEOUT_SECONDS):
                if not await pipeline.process_ready_commit(self._session_factory, REGISTRY, RULES):
                    await run_next_job(self._session_factory, REGISTRY, self._resolver)
        except Exception as exc:
            logger.warning("정본 기억 처리 한 칸이 실패했다(다음 바퀴에 다시 고른다): %s", type(exc).__name__)
            capture_dependency_failure(exc, dependency="novelize")

    async def sweep(self) -> None:
        try:
            changed = await expire_stale_work(self._session_factory)
        except Exception as exc:
            logger.warning("정본 기억 만료 정리에 실패했다(다음 주기에 다시 한다): %s", type(exc).__name__)
            capture_dependency_failure(exc, dependency="novelize")
            return
        if changed:
            logger.warning("정본 기억 만료 정리로 멈춘 행 %d 개를 되돌리거나 끝냈다", changed)


async def read_snapshot(db: AsyncSession, novel_id: uuid.UUID, *, revision_no: int | None = None) -> BibleSnapshot:
    return await bible_at(db, novel_id, REGISTRY, revision_no=revision_no)


@dataclass(frozen=True)
class JobView:
    slot: SlotId
    status: JobStatus
    attempts: int
    failure_code: JobFailure | None


@dataclass(frozen=True)
class CommitView:
    """확정 하나의 상태·작업·검사 결과 개수. 정본 기억 내용(제안·사실 값·인용)은 담지 않는다."""

    commit_id: uuid.UUID
    status: CommitStatus
    failure_code: CommitFailure | None
    revision_no: int | None
    jobs: tuple[JobView, ...]
    finding_counts: dict[FindingSeverity, int]


async def read_commit(db: AsyncSession, commit_id: uuid.UUID) -> CommitView | None:
    commit = (
        await db.execute(
            select(NovelBibleCommit.status, NovelBibleCommit.failure_code).where(NovelBibleCommit.id == commit_id)
        )
    ).one_or_none()
    if commit is None:
        return None
    revision_no = await db.scalar(
        select(NovelBibleRevision.revision_no).where(NovelBibleRevision.commit_id == commit_id)
    )
    jobs = (
        await db.execute(
            select(NovelBibleJob.slot, NovelBibleJob.status, NovelBibleJob.attempts, NovelBibleJob.failure_code)
            .where(NovelBibleJob.commit_id == commit_id)
            .order_by(NovelBibleJob.slot)
        )
    ).all()
    counts = (
        await db.execute(
            select(NovelBibleFinding.severity, func.count())
            .where(NovelBibleFinding.commit_id == commit_id)
            .group_by(NovelBibleFinding.severity)
        )
    ).tuples()
    return CommitView(
        commit_id=commit_id,
        status=commit.status,
        failure_code=commit.failure_code,
        revision_no=revision_no,
        jobs=tuple(JobView(row.slot, row.status, row.attempts, row.failure_code) for row in jobs),
        finding_counts=dict(counts.all()),
    )
