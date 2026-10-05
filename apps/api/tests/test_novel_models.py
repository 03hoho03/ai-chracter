"""소설 테이블의 CHECK 제약과 진행 중 작업 부분 유니크 인덱스.

`alembic check` 는 CHECK 제약을 비교하지 않고 부분 인덱스의 조건식도 비교하지 않는다 — 이 불변식들은 여기 행위
테스트에서만 검증된다. 지우지 말 것."""

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import NovelChapter, NovelChapterRevision, NovelJob
from factories import NovelTree, _make_novel_tree, _make_user


async def _tree(db_session: AsyncSession) -> NovelTree:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return await _make_novel_tree(db_session, user.id)


def _job_values(tree: NovelTree, **overrides: Any) -> dict[str, Any]:
    # 기본값은 끝난 작업이라 진행 중 부분 유니크(트리에 이미 running 하나가 있다)에 걸리지 않는다.
    values: dict[str, Any] = {
        "novel_id": tree.novel.id,
        "user_id": tree.novel.user_id,
        "kind": "chapter_generate",
        "status": "succeeded",
        "charged_amount": 0,
    }
    values.update(overrides)
    return values


async def _insert_job(db_session: AsyncSession, values: dict[str, Any]) -> None:
    async with db_session.begin_nested():
        await db_session.execute(sa.insert(NovelJob).values(**values))


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"status": "cancelled"}, id="unknown-status"),
        pytest.param({"kind": "chapter"}, id="unknown-kind"),
        pytest.param({"charged_amount": -1}, id="negative-charge"),
        pytest.param({"status": "succeeded", "refunded_at": sa.func.now()}, id="refund-on-succeeded"),
        pytest.param({"status": "failed", "failure_code": "network"}, id="unknown-failure-code"),
    ],
)
async def test_novel_job_rejects_values_outside_its_check_constraints(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        await _insert_job(db_session, _job_values(tree, **overrides))


async def test_novel_job_accepts_a_refunded_failure(db_session: AsyncSession) -> None:
    """환불 CHECK 가 실패 작업의 환불까지 막지 않는지 — 위 거부 테스트만으로는 모든 환불을 막는 제약도 통과한다."""
    tree = await _tree(db_session)

    await _insert_job(
        db_session, _job_values(tree, status="failed", refunded_at=sa.func.now(), failure_code="truncated")
    )


async def test_novel_job_allows_only_one_active_job_per_novel(db_session: AsyncSession) -> None:
    """트리에는 이미 running 작업이 하나 있다. queued 하나를 더 넣으면 같은 소설의 진행 중 작업이 둘이 된다."""
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        await _insert_job(db_session, _job_values(tree, status="queued"))


async def test_novel_job_allows_a_new_active_job_once_the_previous_one_finished(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)
    await db_session.execute(sa.update(NovelJob).where(NovelJob.id == tree.active_job.id).values(status="failed"))

    await _insert_job(db_session, _job_values(tree, status="queued"))

    active = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(NovelJob)
        .where(NovelJob.novel_id == tree.novel.id, NovelJob.status.in_(["queued", "running"]))
    )
    assert active == 1


async def test_novel_job_active_limit_is_per_novel(db_session: AsyncSession) -> None:
    """부분 유니크가 소설 단위인지 — 같은 사람의 다른 소설은 각자 진행 중 작업을 하나씩 가질 수 있다(두 번째 트리의
    running 작업 INSERT 가 위반이면 여기서 IntegrityError 가 난다)."""
    tree = await _tree(db_session)
    await _make_novel_tree(db_session, tree.novel.user_id)

    running = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(NovelJob)
        .where(NovelJob.user_id == tree.novel.user_id, NovelJob.status == "running")
    )
    assert running == 2


async def test_novel_chapter_rejects_zero_assistant_messages(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)
    chapter = tree.chapter

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.insert(NovelChapter).values(
                    novel_id=tree.novel.id,
                    ordinal=2,
                    start_message_id=chapter.start_message_id,
                    start_message_created_at=chapter.start_message_created_at,
                    end_message_id=chapter.end_message_id,
                    end_message_created_at=chapter.end_message_created_at,
                    assistant_message_count=0,
                    source_hash=chapter.source_hash,
                )
            )


async def test_novel_chapter_revision_rejects_unknown_source(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.insert(NovelChapterRevision).values(
                    chapter_id=tree.chapter.id, revision_no=3, body="본문", source="import"
                )
            )
