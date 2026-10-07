"""인물·읽은 위치·스냅샷 라우트가 다른 쓰기와 실제로 겹칠 때(독립 커넥션).

같은 커넥션의 테스트로는 두 요청이 순서대로 돌아 경쟁이 드러나지 않는다. 그래서 상대 트랜잭션이 잠금을 쥔 채 커밋하지
않은 상태에서 라우트 함수를 띄우고, 그 라우트가 정말 막혀 있는 것(`_assert_blocked`)을 먼저 확인한 뒤 상대를 커밋한다.
최종 상태만 보면 둘을 순서대로 돌려도 같은 값이 나오므로 막힘 확인이 없으면 이 테스트들은 아무것도 증명하지 못한다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.db.models import User
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterRevision,
    NovelCharacter,
    NovelJob,
    NovelReadingPosition,
)
from api.novelize import router as novelize_router
from api.novelize import runner
from api.novelize.billing import _lock_user
from api.novelize.deletion import delete_batch, delete_novels
from api.novelize.output import ParsedEpisode
from api.novelize.schemas import (
    NovelCharacterMergeRequest,
    NovelReadingPositionRequest,
    NovelRevisionCreateRequest,
)
from api.novelize.snapshots import save_snapshot
from factories import _assert_blocked, _make_novel_tree, _make_user

_MARKER_DOMAIN = "novelize-edit-races.test"


def _detail(exc: HTTPException) -> object:
    """`HTTPException.detail` 은 `str` 로 선언돼 있어 dict 와 비교하면 mypy 가 막는다 — 실제로는 dict 를 싣는다."""
    return exc.detail


@pytest_asyncio.fixture
async def independent_factory(db_engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """커밋되는 독립 커넥션 세션 팩토리. 여기서 쓴 행은 롤백되지 않으므로 이 표지 도메인의 사용자와 그 소설을 끝에서
    직접 지운다."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            novel_ids = (await cleanup.scalars(select(Novel.id).where(Novel.user_id.in_(user_ids)))).all()
            await delete_novels(cleanup, novel_ids)
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


@dataclass(frozen=True)
class _Seed:
    user_id: uuid.UUID
    novel_id: uuid.UUID
    batch_id: uuid.UUID
    chapter_id: uuid.UUID
    revision_id: uuid.UUID
    current_revision_id: uuid.UUID
    doyun_id: uuid.UUID
    yuni_id: uuid.UUID
    snapshot_id: uuid.UUID


async def _seed(factory: async_sessionmaker[AsyncSession]) -> _Seed:
    """화 하나짜리 묶음 하나, 인물 카드 둘(도윤·윤이), 스냅샷 하나가 있는 소설. 진행 중 작업은 없다."""
    async with factory() as s:
        owner = _make_user(email=f"{uuid.uuid4()}@{_MARKER_DOMAIN}")
        s.add(owner)
        await s.flush()
        tree = await _make_novel_tree(s, owner.id)
        tree.active_job.status = "succeeded"
        doyun = NovelCharacter(novel_id=tree.novel.id, name="도윤")
        yuni = NovelCharacter(novel_id=tree.novel.id, name="윤이")
        s.add_all([doyun, yuni])
        await s.flush()
        snapshot = await save_snapshot(s, tree.novel.id, name="저장", kind="manual")
        await s.commit()
    return _Seed(
        owner.id,
        tree.novel.id,
        tree.batch.id,
        tree.chapter.id,
        tree.first_revision.id,
        tree.reverting_revision.id,
        doyun.id,
        yuni.id,
        snapshot.id,
    )


def _in_own_session(
    factory: async_sessionmaker[AsyncSession],
    novel_id: uuid.UUID,
    call: Callable[[Novel, AsyncSession], Awaitable[None]],
) -> "asyncio.Task[object]":
    """라우트 함수 하나를 자기 세션으로 띄운다. 라우트처럼 소설을 잠금 없이 먼저 읽는다. 거절(`HTTPException`)은 예외 대신
    결과로 돌려주고 성공은 None 이다 — 500 이 될 예외(FK 위반 등)는 그대로 터져 테스트를 실패시킨다."""

    async def run() -> object:
        async with factory() as s:
            novel = await s.get_one(Novel, novel_id)
            try:
                await call(novel, s)
            except HTTPException as exc:
                return exc
            return None

    return asyncio.create_task(run())


async def test_reading_position_waiting_on_a_last_batch_deletion_is_404_not_a_foreign_key_error(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """묶음 삭제가 화를 잠그고 지우는 중에 읽은 위치가 오면, 화를 확인하지 않고 바로 저장하면 삭제 커밋 뒤 FK 위반(500)
    이다. 화를 키 공유 잠금으로 확인하면 삭제를 기다렸다가 화가 없음을 보고 404 다."""
    seed = await _seed(independent_factory)
    payload = NovelReadingPositionRequest(
        paragraph_index=0, paragraph_count=1, revision_id=seed.revision_id, finished=True
    )

    async def save(novel: Novel, db: AsyncSession) -> None:
        await novelize_router.save_novel_reading_position(
            chapter_id=seed.chapter_id, payload=payload, novel=novel, db=db
        )

    deleter = independent_factory()
    try:
        await _lock_user(deleter, seed.user_id)
        await delete_batch(deleter, novel_id=seed.novel_id, batch_id=seed.batch_id)
        task = _in_own_session(independent_factory, seed.novel_id, save)
        await _assert_blocked(task)
        await deleter.commit()
        result = await task
    finally:
        await deleter.close()

    assert isinstance(result, HTTPException)
    assert (result.status_code, _detail(result)) == (404, {"code": "NOVEL_CHAPTER_NOT_FOUND"})


async def test_last_batch_deletion_waits_for_a_reading_position_save_and_removes_it(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """반대 순서: 위치 저장이 화를 먼저 잡았으면 삭제가 그 커밋을 기다렸다가 새 위치까지 지운다(남으면 화 DELETE 가 FK 에
    걸린다)."""
    seed = await _seed(independent_factory)
    reader = independent_factory()
    try:
        await reader.execute(
            select(NovelChapter.id).where(NovelChapter.id == seed.chapter_id).with_for_update(key_share=True, read=True)
        )
        reader.add(
            NovelReadingPosition(
                chapter_id=seed.chapter_id,
                novel_id=seed.novel_id,
                paragraph_index=0,
                paragraph_count=1,
                revision_id=seed.revision_id,
            )
        )
        await reader.flush()

        async def delete_last(novel: Novel, db: AsyncSession) -> None:
            await novelize_router.delete_last_novel_batch(batch_id=seed.batch_id, novel=novel, db=db)

        task = _in_own_session(independent_factory, seed.novel_id, delete_last)
        await _assert_blocked(task)
        await reader.commit()
        result = await task
    finally:
        await reader.close()

    assert result is None
    async with independent_factory() as s:
        left = await s.scalar(
            select(func.count()).select_from(NovelReadingPosition).where(NovelReadingPosition.novel_id == seed.novel_id)
        )
        assert left == 0


async def test_restore_waiting_on_a_job_being_created_sees_it_and_is_409(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """작업 생성은 사용자 행을 잡고 진행 중 작업을 넣는다. 복원이 사용자 행을 잡지 않으면 아직 커밋되지 않은 그 작업을 못
    보고 되돌리기를 마치고, 그 뒤 생성 결과 저장이 되돌린 화·인물·제목을 다시 덮는다. 잡으면 기다렸다가 작업을 보고 409."""
    seed = await _seed(independent_factory)

    async def restore(novel: Novel, db: AsyncSession) -> None:
        await novelize_router.restore_novel_snapshot(snapshot_id=seed.snapshot_id, novel=novel, db=db)

    creator = independent_factory()
    try:
        await _lock_user(creator, seed.user_id)
        creator.add(
            NovelJob(novel_id=seed.novel_id, user_id=seed.user_id, kind="ai_edit", status="queued", charged_amount=5)
        )
        await creator.flush()
        task = _in_own_session(independent_factory, seed.novel_id, restore)
        await _assert_blocked(task)
        await creator.commit()
        result = await task
    finally:
        await creator.close()

    assert isinstance(result, HTTPException)
    assert (result.status_code, _detail(result)) == (409, {"code": "NOVEL_JOB_IN_PROGRESS"})


async def test_merge_waiting_on_a_generation_save_moves_the_link_it_just_made(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """생성 결과 저장은 사용자 행을 쥔 채 카드 목록을 읽고 이름을 붙인다. 합치기가 그 잠금을 기다리지 않으면 아직 보이지
    않는 새 연결을 옮기지 못하고 흡수되는 카드를 지워, 그 화의 등장 인물이 사라진다. 기다리면 새 연결까지 남는 카드로
    옮긴다."""
    seed = await _seed(independent_factory)

    async def merge(novel: Novel, db: AsyncSession) -> None:
        await novelize_router.merge_novel_character(
            character_id=seed.yuni_id,
            payload=NovelCharacterMergeRequest(into_character_id=seed.doyun_id),
            novel=novel,
            db=db,
        )

    saver = independent_factory()
    try:
        await _lock_user(saver, seed.user_id)
        chapter = await saver.get_one(NovelChapter, seed.chapter_id)
        episode = ParsedEpisode(title="제목", summary="요약", characters=("윤이",), body="본문")
        await runner._link_characters(saver, seed.novel_id, [chapter], [episode])
        task = _in_own_session(independent_factory, seed.novel_id, merge)
        await _assert_blocked(task)
        await saver.commit()
        result = await task
    finally:
        await saver.close()

    assert result is None
    async with independent_factory() as s:
        linked = (
            await s.scalars(
                select(NovelChapterCharacter.character_id).where(NovelChapterCharacter.chapter_id == seed.chapter_id)
            )
        ).all()
        assert linked == [seed.doyun_id]
        assert await s.get(NovelCharacter, seed.yuni_id) is None


async def _pending_preview(
    factory: async_sessionmaker[AsyncSession], seed: _Seed, base_revision_id: uuid.UUID
) -> uuid.UUID:
    """기준 개정이 `base_revision_id` 인, 적용도 버리기도 안 한 AI 수정 결과 하나(커밋)."""
    async with factory() as s:
        job = NovelJob(
            novel_id=seed.novel_id,
            user_id=seed.user_id,
            kind="ai_edit",
            status="succeeded",
            charged_amount=5,
            chapter_id=seed.chapter_id,
            base_revision_id=base_revision_id,
            paragraph_start=0,
            paragraph_end=0,
            instruction="고쳐 줘",
            result_text="고친 본문",
        )
        s.add(job)
        await s.commit()
    return job.id


async def _preview_texts(factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> tuple[str | None, str | None]:
    """다른 커넥션에서 읽는다 — 요청 세션이 커밋하지 않은 비우기는 여기서 보이지 않는다."""
    async with factory() as s:
        row = (await s.execute(select(NovelJob.instruction, NovelJob.result_text).where(NovelJob.id == job_id))).one()
        return row.instruction, row.result_text


async def test_a_direct_edit_commits_the_stale_preview_cleanup(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """비우기는 새 개정을 커밋한 뒤 같은 세션에서 돈다. 그 뒤에 커밋이 없으면 세션이 닫힐 때 되돌려져, 같은 커넥션의
    테스트에서는 비워진 것처럼 보여도 실제로는 낡은 지시문·결과 본문이 남는다."""
    seed = await _seed(independent_factory)
    job_id = await _pending_preview(independent_factory, seed, seed.current_revision_id)

    async with independent_factory() as s:
        novel = await s.get_one(Novel, seed.novel_id)
        await novelize_router.create_novel_chapter_revision(
            chapter_id=seed.chapter_id,
            payload=NovelRevisionCreateRequest(base_revision_id=seed.current_revision_id, body="고친 판"),
            novel=novel,
            db=s,
        )

    assert await _preview_texts(independent_factory, job_id) == (None, None)


async def test_a_snapshot_restore_commits_the_stale_preview_cleanup(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed = await _seed(independent_factory)
    async with independent_factory() as s:
        newer = NovelChapterRevision(chapter_id=seed.chapter_id, revision_no=3, body="고침", source="manual_edit")
        s.add(newer)
        await s.commit()
    job_id = await _pending_preview(independent_factory, seed, newer.id)

    async with independent_factory() as s:
        novel = await s.get_one(Novel, seed.novel_id)
        await novelize_router.restore_novel_snapshot(snapshot_id=seed.snapshot_id, novel=novel, db=s)

    assert await _preview_texts(independent_factory, job_id) == (None, None)
