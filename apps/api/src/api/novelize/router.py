"""소설 라우트. 모든 라우트(읽기 포함)가 라우터 수준에서 소설화 접근 게이트를 거친다."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.schema import CamelModel
from api.db.models.novel import Novel, NovelJob, NovelJobFailureCode, NovelJobKind, NovelJobStatus
from api.db.session import get_db_session
from api.novelize.access import require_novelize_access
from api.novelize.runner import expire_stale_jobs
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/novels", tags=["novels"], dependencies=[Depends(require_novelize_access)])


class NovelAiEditPreview(CamelModel):
    """문단 수정 작업의 입력과 결과 후보. `result_text` 는 범위 밖 문단까지 이은 장 전체 본문이고, 성공 전에는 null."""

    base_revision_id: uuid.UUID | None
    paragraph_start: int | None
    paragraph_end: int | None
    instruction: str | None
    result_text: str | None


class NovelJobResponse(CamelModel):
    id: uuid.UUID
    kind: NovelJobKind
    status: NovelJobStatus
    charged_amount: int
    refunded: bool
    failure_reason: NovelJobFailureCode | None
    chapter_id: uuid.UUID | None
    # 이 작업이 만든 개정. 문단 수정은 개정을 만들지 않으므로 늘 null 이다(적용할 때 새 개정이 된다).
    revision_id: uuid.UUID | None
    ai_edit: NovelAiEditPreview | None
    created_at: datetime


def _job_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "NOVEL_JOB_NOT_FOUND"})


@router.get("/{novel_id}/jobs/{job_id}")
async def get_novel_job(
    novel_id: uuid.UUID,
    job_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelJobResponse:
    """작업 폴링. 없는 작업·남의 소설·다른 소설의 작업은 모두 404 다(남의 것이 있다는 사실도 드러내지 않는다).

    답하기 전에 이 소설의 죽은 작업을 정리한다 — 서버가 재기동되어 작업이 사라졌으면 폴링이 실패·환불을 보게 된다."""
    owner = await db.scalar(select(Novel.user_id).where(Novel.id == novel_id))
    if owner != user_id:
        raise _job_not_found()
    await expire_stale_jobs(db, novel_id=novel_id)
    await db.commit()

    job = await db.scalar(select(NovelJob).where(NovelJob.id == job_id, NovelJob.novel_id == novel_id))
    if job is None:
        raise _job_not_found()
    ai_edit = (
        NovelAiEditPreview(
            base_revision_id=job.base_revision_id,
            paragraph_start=job.paragraph_start,
            paragraph_end=job.paragraph_end,
            instruction=job.instruction,
            result_text=job.result_text,
        )
        if job.kind == "ai_edit"
        else None
    )
    return NovelJobResponse(
        id=job.id,
        kind=job.kind,
        status=job.status,
        charged_amount=job.charged_amount,
        refunded=job.refunded_at is not None,
        failure_reason=job.failure_code,
        chapter_id=job.chapter_id,
        revision_id=job.result_revision_id,
        ai_edit=ai_edit,
        created_at=job.created_at,
    )
