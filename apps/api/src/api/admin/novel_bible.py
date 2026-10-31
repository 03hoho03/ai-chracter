"""정본 기억 확정의 어드민 내부 입구 — 화 개정 하나를 확정으로 받고, 그 확정의 상태·개수를 돌려준다.

어드민 화면이 쓰지 않는 내부 입구라 openapi 에 싣지 않는다. 스위치(`novel_bible_enabled`)가 꺼져 있으면 라우트가 없는 것과
같은 404 다. 켜져 있어도 확정이 만들 작업에 배정된 어댑터의 문안 체인에 그 슬롯 채널이 없으면 503 이다 — 처리될 수 없는 확정을
쌓지 않는다. 응답에 정본 기억 내용(사실 값·인용)을 싣지 않는다 — 사용자 소설에서 파생된 내용을 어드민이 열람하는 일은 조치
기록이 필요한 다른 일이다. 누가 확정했는지는 확정 행의 `actor_*` 가 남긴다."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.dependencies import get_current_admin_id
from api.core.config import settings
from api.core.schema import CamelModel
from api.db.session import get_db_session
from api.novel_bible import entry
from api.novel_bible.core.confirm import Actor, ConfirmConflictError, ConfirmTargetNotFoundError
from api.novel_bible.ids import CommitFailure, CommitStatus, JobFailure, JobStatus, SlotId

router = APIRouter(tags=["admin"])


class BibleConfirmRequest(CamelModel):
    novel_id: uuid.UUID
    chapter_id: uuid.UUID
    revision_id: uuid.UUID


class BibleConfirmResponse(CamelModel):
    commit_id: uuid.UUID
    status: CommitStatus
    created: bool  # 거짓 = 같은 개정이 이미 그 화의 현재 확정이라 아무것도 하지 않음


class BibleSlotJobStatus(CamelModel):
    slot: SlotId
    status: JobStatus
    attempts: int
    failure_code: JobFailure | None


class BibleCommitStatusResponse(CamelModel):
    commit_id: uuid.UUID
    status: CommitStatus
    failure_code: CommitFailure | None
    revision_no: int | None
    slots: list[BibleSlotJobStatus]
    blocking_count: int
    warning_count: int


def _require_enabled() -> None:
    """인증보다 먼저 본다 — 꺼져 있으면 세션이 있든 없든 라우트가 없는 것과 같다."""
    if not settings.novel_bible_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post("/admin/novel-bible/confirmations", status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
async def confirm_novel_chapter(
    body: BibleConfirmRequest,
    _enabled: None = Depends(_require_enabled),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> BibleConfirmResponse:
    try:
        result = await entry.confirm_chapter(
            db,
            novel_id=body.novel_id,
            chapter_id=body.chapter_id,
            revision_id=body.revision_id,
            actor=Actor(kind="admin", id=admin_id),
        )
    except ConfirmTargetNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except ConfirmConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from error
    except entry.BiblePromptMissingError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
    await db.commit()
    return BibleConfirmResponse(commit_id=result.commit_id, status=result.status, created=result.created)


@router.get("/admin/novel-bible/confirmations/{commit_id}", include_in_schema=False)
async def read_novel_bible_confirmation(
    commit_id: uuid.UUID,
    _enabled: None = Depends(_require_enabled),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> BibleCommitStatusResponse:
    view = await entry.read_commit(db, commit_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return BibleCommitStatusResponse(
        commit_id=view.commit_id,
        status=view.status,
        failure_code=view.failure_code,
        revision_no=view.revision_no,
        slots=[
            BibleSlotJobStatus(slot=job.slot, status=job.status, attempts=job.attempts, failure_code=job.failure_code)
            for job in view.jobs
        ],
        blocking_count=view.finding_counts.get("block", 0),
        warning_count=view.finding_counts.get("warning", 0),
    )
