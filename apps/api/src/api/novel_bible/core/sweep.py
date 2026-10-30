"""정본 기억 만료 정리 — 처리하던 프로세스가 사라져(교체에서 정지 유예를 넘겨 잘린 워커 따위) 실행 중 작업이나 연결·검사 중
확정으로 남은 행을 되돌리거나 끝낸다.

워커는 작업 하나·준비된 확정 처리 하나를 `BIBLE_TASK_TIMEOUT_SECONDS` 안에 끝내거나 끊는다. 그래서 그보다 60초 더 멈춘 행은
처리하던 프로세스가 없는 것이고, 이 정리는 살아 있는 처리를 빼앗지 않는다. 상태 전이는 모두 조건부 UPDATE 라 교체 겹침에 워커
둘이 함께 정리해도 한 번만 바뀐다. 작업 행을 먼저, 확정 행을 나중에 바꾼다(작업 받기와 같은 순서). 정본 기억은 과금이 없어
환불이 없다."""

from datetime import timedelta

from sqlalchemy import exists, func, update

from api.db.models.novel_bible import NovelBibleCommit, NovelBibleJob
from api.novel_bible.core.jobs import MAX_ATTEMPTS, RETRY_DELAY, SessionFactory

# 작업 하나·준비된 확정 처리 하나의 시간 상한(초). 소설 작업 상한(기본 360초)보다 작아, 워커 정지 유예 안에 끝난다.
BIBLE_TASK_TIMEOUT_SECONDS = 300
_EXPIRY_MARGIN = timedelta(seconds=60)
# 멈춘 연결·검사를 추출 끝 상태로 되돌리는 횟수 상한. 판정 같은 유료 단계가 시간을 넘길 때마다 되돌려 처음부터 다시 부르는 일이
# 끝없이 되풀이되지 않게, 이만큼 되돌린 확정은 실패(멈춤)로 끝낸다.
MAX_RESTARTS = 3


async def expire_stale_work(factory: SessionFactory) -> int:
    """멈춘 행을 정리하고 바꾼 행 수를 돌려준다.

    - 실행 중으로 멈춘 작업: 시도가 남았으면 대기(만료 사유, 다른 재시도와 같은 대기 시각), 다 썼으면 실패(만료).
    - 연결·검사에 멈춘 확정: 추출 끝 상태로 되돌린다 — 작업이 모두 끝나 있으므로 다음 바퀴에 준비된 확정으로 다시 집혀 연결부터
      한다. 이미 `MAX_RESTARTS` 번 되돌렸으면 실패(멈춤).
    - 밀려난(`stale`) 확정에 남은 대기 작업: 실패(취소). 고르기 조건에서 이미 빠져 돌지 않지만, 확정 입구가 작업 → 확정 잠금
      순서를 거스르지 않으려고 그 자리에서 끝내지 않은 것을 여기서 끝낸다."""
    cutoff = func.now() - timedelta(seconds=BIBLE_TASK_TIMEOUT_SECONDS) - _EXPIRY_MARGIN
    stuck_job = (NovelBibleJob.status == "running", NovelBibleJob.claimed_at < cutoff)
    stuck_commit = (NovelBibleCommit.status.in_(("linking", "checking")), NovelBibleCommit.stage_started_at < cutoff)
    stale_commit = exists().where(NovelBibleCommit.id == NovelBibleJob.commit_id, NovelBibleCommit.status == "stale")
    statements = (
        update(NovelBibleJob)
        .where(*stuck_job, NovelBibleJob.attempts < MAX_ATTEMPTS)
        .values(status="queued", failure_code="expired", available_at=func.now() + NovelBibleJob.attempts * RETRY_DELAY)
        .returning(NovelBibleJob.id),
        update(NovelBibleJob)
        .where(*stuck_job, NovelBibleJob.attempts >= MAX_ATTEMPTS)
        .values(status="failed", failure_code="expired", finished_at=func.now())
        .returning(NovelBibleJob.id),
        update(NovelBibleJob)
        .where(NovelBibleJob.status == "queued", stale_commit)
        .values(status="failed", failure_code="cancelled", finished_at=func.now())
        .returning(NovelBibleJob.id),
        update(NovelBibleCommit)
        .where(*stuck_commit, NovelBibleCommit.restarts < MAX_RESTARTS)
        .values(status="extracting", restarts=NovelBibleCommit.restarts + 1)
        .returning(NovelBibleCommit.id),
        update(NovelBibleCommit)
        .where(*stuck_commit, NovelBibleCommit.restarts >= MAX_RESTARTS)
        .values(status="failed", failure_code="stalled", finished_at=func.now())
        .returning(NovelBibleCommit.id),
    )
    changed = 0
    async with factory() as session:
        # 문장마다 커밋한다 — 행 잠금을 한 트랜잭션에 쌓아 작업 받기·커밋 트랜잭션과 오래 겹치지 않게.
        for statement in statements:
            changed += len((await session.scalars(statement)).all())
            await session.commit()
    return changed
