"""소설 테이블의 CHECK 제약, 복합 PK, 유니크·부분 유니크 인덱스, 그리고 새 자식 테이블의 cascade·표지 SET NULL.

`alembic check` 는 CHECK 제약과 복합 PK 를 비교하지 않고 부분 인덱스의 조건식도 비교하지 않는다 — 이 불변식들은 여기
행위 테스트에서만 검증된다. 지우지 말 것."""

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterRevision,
    NovelCharacter,
    NovelJob,
    NovelReadingPosition,
    NovelSnapshot,
)
from factories import NovelTree, _make_asset, _make_novel_tree, _make_user


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


# ── 환불 금액 CHECK ─────────────────────────────────────────────────────────
# 갈래마다 허용 하나·거부 하나. 거부만 있으면 모든 환불을 막는 제약도 통과하고, 허용만 있으면 아무것도 막지 않는
# 제약도 통과한다.


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"status": "failed", "charged_amount": 40, "refunded_amount": 40, "failure_code": "llm_error"},
            id="failed-full-refund",
        ),
        pytest.param(
            {
                "kind": "chain_generate",
                "status": "failed",
                "charged_amount": 120,
                "consumed_amount": 40,
                "refunded_amount": 80,
                "failure_code": "llm_error",
            },
            id="chain-parent-refunds-unconsumed-share",
        ),
        pytest.param(
            {"status": "succeeded", "charged_amount": 120, "refunded_amount": 40}, id="succeeded-partial-refund"
        ),
        pytest.param(
            {"status": "failed", "charged_amount": 40, "refunded_amount": None, "failure_code": "llm_error"},
            id="old-code-refund-without-amount",
        ),
    ],
)
async def test_novel_job_refund_check_accepts_each_refund_shape(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    tree = await _tree(db_session)

    await _insert_job(db_session, _job_values(tree, refunded_at=sa.func.now(), **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"status": "succeeded", "charged_amount": 120, "refunded_amount": 120}, id="succeeded-full-refund"
        ),
        pytest.param(
            {"status": "failed", "charged_amount": 0, "refunded_amount": 0, "failure_code": "llm_error"},
            id="zero-refund-stamped",
        ),
        pytest.param(
            {
                "kind": "chain_generate",
                "status": "failed",
                "charged_amount": 120,
                "consumed_amount": 40,
                "refunded_amount": 120,
                "failure_code": "llm_error",
            },
            id="chain-parent-refunds-consumed-share-too",
        ),
        pytest.param(
            {"status": "succeeded", "charged_amount": 120, "refunded_amount": None},
            id="succeeded-refund-without-amount",
        ),
    ],
)
async def test_novel_job_refund_check_rejects_inconsistent_refunds(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        await _insert_job(db_session, _job_values(tree, refunded_at=sa.func.now(), **overrides))


async def test_novel_job_refund_amount_requires_refunded_at(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        await _insert_job(
            db_session,
            _job_values(tree, status="failed", charged_amount=40, refunded_amount=40, failure_code="llm_error"),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"kind": "chain_generate"}, id="chain-parent-kind"),
        pytest.param({"status": "failed", "failure_code": "malformed"}, id="malformed"),
        pytest.param({"status": "failed", "failure_code": "episode_count_mismatch"}, id="episode-count-mismatch"),
    ],
)
async def test_novel_job_accepts_the_added_kind_and_failure_codes(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    tree = await _tree(db_session)

    await _insert_job(db_session, _job_values(tree, **overrides))


# ── 진행 중 1건 부분 유니크와 연쇄 ─────────────────────────────────────────────


async def test_chain_child_can_run_while_its_parent_is_running(db_session: AsyncSession) -> None:
    """트리의 running 작업을 연쇄 부모로 보고 running 자식을 넣는다. 자식이 제약에서 빠지지 않으면 위반이다."""
    tree = await _tree(db_session)

    await _insert_job(db_session, _job_values(tree, status="running", parent_job_id=tree.active_job.id))


# ── 새 테이블의 유니크·CHECK·복합 PK ────────────────────────────────────────


async def test_novel_batch_ordinal_is_unique_per_novel(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(sa.insert(NovelBatch).values(**_batch_values(tree, ordinal=tree.batch.ordinal)))


async def test_novel_batch_rejects_a_zero_episode_target(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(sa.insert(NovelBatch).values(**_batch_values(tree, target_episode_count=0)))


async def test_novel_batch_accepts_a_multi_episode_target(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)

    async with db_session.begin_nested():
        await db_session.execute(sa.insert(NovelBatch).values(**_batch_values(tree, target_episode_count=3)))


async def test_novel_character_name_is_unique_per_novel(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)
    other = await _make_novel_tree(db_session, tree.novel.user_id)
    db_session.add_all(
        [NovelCharacter(novel_id=tree.novel.id, name="민아"), NovelCharacter(novel_id=other.novel.id, name="민아")]
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(sa.insert(NovelCharacter).values(novel_id=tree.novel.id, name="민아"))


async def test_novel_chapter_character_primary_key_is_the_pair(db_session: AsyncSession) -> None:
    """같은 화·같은 인물 쌍만 거부한다 — 한 화에 인물 둘, 한 인물이 두 화에 나오는 것은 받는다. 복합 PK 가 한 칸짜리로
    바뀌면 앞의 허용 중 하나가 깨진다."""
    tree = await _tree(db_session)
    second = await _add_chapter_row(db_session, tree, ordinal=2)
    mina = NovelCharacter(novel_id=tree.novel.id, name="민아")
    seo = NovelCharacter(novel_id=tree.novel.id, name="서")
    db_session.add_all([mina, seo])
    await db_session.flush()
    db_session.add_all(
        [
            NovelChapterCharacter(chapter_id=tree.chapter.id, character_id=mina.id),
            NovelChapterCharacter(chapter_id=tree.chapter.id, character_id=seo.id),
            NovelChapterCharacter(chapter_id=second.id, character_id=mina.id),
        ]
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.insert(NovelChapterCharacter).values(chapter_id=tree.chapter.id, character_id=mina.id)
            )


@pytest.mark.parametrize("kind", ["manual", "auto_before_restore"])
async def test_novel_snapshot_accepts_known_kinds(db_session: AsyncSession, kind: str) -> None:
    tree = await _tree(db_session)

    async with db_session.begin_nested():
        await db_session.execute(
            sa.insert(NovelSnapshot).values(novel_id=tree.novel.id, name="저장", kind=kind, payload={"v": 1})
        )


async def test_novel_snapshot_rejects_unknown_kind(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.insert(NovelSnapshot).values(novel_id=tree.novel.id, name="저장", kind="auto", payload={"v": 1})
            )


# ── 새 자식 테이블 cascade·표지 SET NULL ──────────────────────────────────────


async def test_old_delete_order_removes_novels_with_new_child_rows(db_session: AsyncSession) -> None:
    """이미지만 옛 판으로 되돌렸을 때 옛 소설 삭제(작업 → 개정 → 장 → 소설)는 새 테이블을 모른다. 새 자식 행이 모두
    있어도 그 순서만으로 지워지고 자식 행도 남지 않아야 한다 — cascade 가 빠지면 장·소설 DELETE 가 FK 위반이다."""
    tree = await _tree(db_session)
    await _add_new_child_rows(db_session, tree)
    novel_id = tree.novel.id

    chapter_ids = sa.select(NovelChapter.id).where(NovelChapter.novel_id == novel_id)
    await db_session.execute(sa.delete(NovelJob).where(NovelJob.novel_id == novel_id))
    await db_session.execute(sa.delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id.in_(chapter_ids)))
    await db_session.execute(sa.delete(NovelChapter).where(NovelChapter.novel_id == novel_id))
    await db_session.execute(sa.delete(Novel).where(Novel.id == novel_id))

    for condition in [
        NovelBatch.novel_id == novel_id,
        NovelCharacter.novel_id == novel_id,
        NovelSnapshot.novel_id == novel_id,
        NovelReadingPosition.novel_id == novel_id,
        NovelChapterCharacter.chapter_id == tree.chapter.id,
    ]:
        assert await _count(db_session, condition) == 0


async def test_old_chapter_delete_removes_its_appearances_and_reading_position(db_session: AsyncSession) -> None:
    """옛 코드의 마지막 장 삭제(작업 참조 비우기 → 개정 → 장)도 새 테이블을 모른다. 그 장의 등장 인물·읽은 위치는
    함께 지워지고, 인물 카드와 묶음은 남는다(묶음은 장 DELETE 로 지워지지 않는다)."""
    tree = await _tree(db_session)
    character = await _add_new_child_rows(db_session, tree)
    chapter_id = tree.chapter.id

    await db_session.execute(
        sa.update(NovelJob)
        .where(NovelJob.chapter_id == chapter_id)
        .values(chapter_id=None, base_revision_id=None, result_revision_id=None)
    )
    await db_session.execute(sa.delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id == chapter_id))
    await db_session.execute(sa.delete(NovelChapter).where(NovelChapter.id == chapter_id))

    assert await _count(db_session, NovelReadingPosition.chapter_id == chapter_id) == 0
    assert await _count(db_session, NovelChapterCharacter.character_id == character.id) == 0
    assert await _count(db_session, NovelCharacter.id == character.id) == 1
    assert await _count(db_session, NovelBatch.id == tree.batch.id) == 1


async def test_deleting_a_batch_does_not_cascade_to_its_episodes(db_session: AsyncSession) -> None:
    """묶음 → 화에는 cascade 가 없다 — 화가 남은 묶음을 지우면 조용히 화가 사라지지 않고 거부된다."""
    tree = await _tree(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(sa.delete(NovelBatch).where(NovelBatch.id == tree.batch.id))


async def test_deleting_the_cover_asset_clears_the_cover_and_keeps_the_novel(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)
    asset = await _make_asset(db_session, tree.novel.user_id)
    await db_session.execute(sa.update(Novel).where(Novel.id == tree.novel.id).values(cover_asset_id=asset.id))

    await db_session.execute(sa.delete(Asset).where(Asset.id == asset.id))

    cover = await db_session.scalar(sa.select(Novel.cover_asset_id).where(Novel.id == tree.novel.id))
    assert cover is None


async def _count(db_session: AsyncSession, condition: sa.ColumnElement[bool]) -> int:
    """조건의 칸이 속한 테이블에서 조건에 맞는 행 수. 테이블은 조건식에서 알아낸다."""
    return int(await db_session.scalar(sa.select(sa.func.count()).where(condition)) or 0)


def _batch_values(tree: NovelTree, **overrides: Any) -> dict[str, Any]:
    batch = tree.batch
    values: dict[str, Any] = {
        "novel_id": tree.novel.id,
        "ordinal": batch.ordinal + 1,
        "start_message_id": batch.start_message_id,
        "start_message_created_at": batch.start_message_created_at,
        "end_message_id": batch.end_message_id,
        "end_message_created_at": batch.end_message_created_at,
        "assistant_message_count": batch.assistant_message_count,
        "source_hash": batch.source_hash,
        "target_episode_count": 1,
    }
    values.update(overrides)
    return values


async def _add_chapter_row(db_session: AsyncSession, tree: NovelTree, *, ordinal: int) -> NovelChapter:
    batch = tree.batch
    chapter = NovelChapter(
        novel_id=tree.novel.id,
        ordinal=ordinal,
        batch_id=batch.id,
        episode_index=ordinal - 1,
        start_message_id=batch.start_message_id,
        start_message_created_at=batch.start_message_created_at,
        end_message_id=batch.end_message_id,
        end_message_created_at=batch.end_message_created_at,
        assistant_message_count=batch.assistant_message_count,
        source_hash=batch.source_hash,
    )
    db_session.add(chapter)
    await db_session.flush()
    return chapter


async def _add_new_child_rows(db_session: AsyncSession, tree: NovelTree) -> NovelCharacter:
    """트리의 소설·장 아래에 새 자식 테이블 행을 하나씩 넣고 인물 카드를 돌려준다."""
    character = NovelCharacter(novel_id=tree.novel.id, name="민아", aliases=["민"])
    db_session.add(character)
    await db_session.flush()
    db_session.add_all(
        [
            NovelChapterCharacter(chapter_id=tree.chapter.id, character_id=character.id),
            NovelSnapshot(novel_id=tree.novel.id, name="저장", kind="manual", payload={"v": 1}),
            NovelReadingPosition(
                chapter_id=tree.chapter.id,
                novel_id=tree.novel.id,
                paragraph_index=1,
                paragraph_count=3,
                revision_id=uuid.uuid4(),
            ),
        ]
    )
    await db_session.flush()
    return character
