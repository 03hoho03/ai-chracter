"""정본 기억의 바깥 입구 — 어드민 내부 API 와 측정 하네스가 부른다. 코어 함수에 실제 등록부(`registry.REGISTRY`)와 규칙 목록
(`rules.RULES`)을 넘기는 자리다. 스위치(`novel_bible_enabled`)가 꺼져 있으면 확정을 받지 않는다."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleFinding, NovelBibleJob, NovelBibleRevision
from api.novel_bible.core import pipeline
from api.novel_bible.core.confirm import Actor, ConfirmResult, confirm
from api.novel_bible.core.contracts import AdapterResolver
from api.novel_bible.core.jobs import SessionFactory
from api.novel_bible.core.queries import bible_at
from api.novel_bible.core.types import BibleSnapshot
from api.novel_bible.ids import CommitFailure, CommitStatus, FindingSeverity, JobFailure, JobStatus, SlotId
from api.novel_bible.registry import REGISTRY
from api.novel_bible.rules import RULES


class BibleDisabledError(Exception):
    """정본 기억 스위치가 꺼져 있다."""


async def confirm_chapter(
    db: AsyncSession,
    *,
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    revision_id: uuid.UUID,
    actor: Actor,
    slots: frozenset[SlotId] | None = None,
) -> ConfirmResult:
    """화 개정 하나를 확정으로 받는다. `slots` 는 측정에서 슬롯 일부만 돌릴 때(None = 등록부 전부). 커밋은 호출부가 한다."""
    if not settings.novel_bible_enabled:
        raise BibleDisabledError
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
