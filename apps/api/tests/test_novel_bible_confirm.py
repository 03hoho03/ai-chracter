"""정본 기억 확정 입구 — 화 개정 하나를 확정 행 하나와 슬롯마다 작업 행 하나로 받는다.

아무것도 하지 않는 경우는 하나뿐이다: 그 화의 현재 확정 개정과 같은 개정이 다시 들어왔을 때. 진행 중인 확정과 같은 개정이
다시 들어와도, 본문이 옛 개정과 같은 되돌리기 개정이 들어와도 새 확정이다(앞 진행 중 확정은 밀려난다)."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.core.config import settings
from api.db.models import Novel
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleJob, NovelBibleRevision
from api.db.models.novel_bible_facts import NovelBibleFact
from api.novel_bible import entry
from api.novel_bible.core.confirm import Actor, ConfirmTargetNotFoundError, confirm
from api.novel_bible.core.queries import bible_at
from factories import _committed_engine, _wait_until_a_lock_is_awaited
from novel_bible_fakes import (
    COMMITTED_DOMAIN,
    FakeAdapter,
    add_chapter,
    add_revision,
    delete_committed_novels,
    drain,
    fake_registry,
    full_registry,
    make_novel,
    savepoint_factory,
)

BODY = "사건: 둘이 정원에서 만난다\n\n사실: 하나|life|-|alive|참\n\n앎: 둘|knows|하나|life|-|alive"
SYSTEM = Actor(kind="system")


async def _status(db: AsyncSession, commit_id: uuid.UUID) -> str | None:
    status: str | None = await db.scalar(select(NovelBibleCommit.status).where(NovelBibleCommit.id == commit_id))
    return status


async def test_reconfirming_the_current_revision_is_the_only_no_op(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    registry, adapter = full_registry(), FakeAdapter()
    first = await confirm(
        db_session, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )
    assert (first.created, first.status) == (True, "pending")
    await drain(savepoint_factory(db_session), registry, adapter)
    assert await _status(db_session, first.commit_id) == "committed"

    again = await confirm(
        db_session, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )

    assert (again.commit_id, again.created, again.status) == (first.commit_id, False, "committed")
    assert await db_session.scalar(select(func.count()).select_from(NovelBibleCommit)
                                   .where(NovelBibleCommit.novel_id == novel.id)) == 1


async def test_reconfirming_an_in_flight_revision_makes_a_new_commit_and_stales_the_old(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    registry = full_registry()
    first = await confirm(
        db_session, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )

    second = await confirm(
        db_session, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )

    assert second.created is True and second.commit_id != first.commit_id
    assert await _status(db_session, first.commit_id) == "stale"
    assert await _status(db_session, second.commit_id) == "pending"
    jobs = await db_session.scalar(
        select(func.count()).select_from(NovelBibleJob).where(NovelBibleJob.commit_id == second.commit_id)
    )
    assert jobs == 3


async def test_a_reverting_revision_is_a_new_confirmation_that_replaces_the_chapter(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, original = await add_chapter(db_session, novel.id, 1, BODY)
    registry, adapter = full_registry(), FakeAdapter()
    factory = savepoint_factory(db_session)
    await confirm(db_session, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=original.id, actor=SYSTEM)
    await drain(factory, registry, adapter)
    before = await bible_at(db_session, novel.id, registry, revision_no=None)
    reverting = await add_revision(
        db_session, chapter.id, BODY, block_ids=original.block_ids, source="revert", reverted_from=original.id
    )

    result = await confirm(
        db_session, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=reverting.id, actor=SYSTEM
    )
    await drain(factory, registry, adapter)

    assert result.created is True
    assert await _status(db_session, result.commit_id) == "committed"
    after = await bible_at(db_session, novel.id, registry, revision_no=None)
    assert before.facts is not None and after.facts is not None
    assert len(after.facts) == len(before.facts) == 1
    assert after.facts[0].id != before.facts[0].id
    # 옛 행은 남아 있지만 머리에서는 만료돼 보이지 않는다.
    assert await db_session.scalar(
        select(func.count()).select_from(NovelBibleFact).where(NovelBibleFact.novel_id == novel.id)
    ) == 2


async def test_confirm_refuses_mismatched_or_hidden_targets(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    other = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    other_chapter, other_revision = await add_chapter(db_session, other.id, 1, BODY)
    registry = full_registry()

    for novel_id, chapter_id, revision_id in [
        (novel.id, chapter.id, other_revision.id),
        (novel.id, other_chapter.id, other_revision.id),
        (novel.id, uuid.uuid4(), revision.id),
    ]:
        with pytest.raises(ConfirmTargetNotFoundError):
            await confirm(
                db_session, registry, novel_id=novel_id, chapter_id=chapter_id, revision_id=revision_id, actor=SYSTEM
            )

    # 숨긴 소설(팔린 뒤 작가가 지웠거나 탈퇴해 작가 전용 데이터를 지운 소설)에는 늦게 들어오는 확정도 쓰지 않는다.
    await db_session.execute(update(Novel).where(Novel.id == novel.id).values(hidden_at=datetime.now(UTC)))
    with pytest.raises(ConfirmTargetNotFoundError):
        await confirm(
            db_session, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
        )
    assert await db_session.scalar(
        select(func.count()).select_from(NovelBibleCommit).where(NovelBibleCommit.novel_id.in_([novel.id, other.id]))
    ) == 0


async def test_the_entry_refuses_while_the_switch_is_off(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    admin = Actor(kind="admin", id=uuid.uuid4())

    with pytest.raises(entry.BibleDisabledError):
        await entry.confirm_chapter(
            db_session, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=admin
        )
    assert await db_session.scalar(
        select(func.count()).select_from(NovelBibleCommit).where(NovelBibleCommit.novel_id == novel.id)
    ) == 0

    monkeypatch.setattr(settings, "novel_bible_enabled", True)
    monkeypatch.setattr(entry, "REGISTRY", fake_registry())
    result = await entry.confirm_chapter(
        db_session, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=admin
    )
    # 등록된 슬롯이 없으면 작업 없이 추출 끝 상태로 들어간다.
    assert (result.created, result.status) == (True, "extracting")
    commit = await db_session.get(NovelBibleCommit, result.commit_id)
    assert commit is not None and (commit.actor_kind, commit.actor_id) == ("admin", admin.id)
    assert await db_session.scalar(select(func.count()).select_from(NovelBibleRevision)
                                   .where(NovelBibleRevision.novel_id == novel.id)) == 0


@pytest_asyncio.fixture
async def committed_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    engine = _committed_engine(db_engine)
    try:
        yield engine
    finally:
        await delete_committed_novels(engine)
        await engine.dispose()


async def test_concurrent_confirms_of_one_chapter_leave_one_in_flight_commit(committed_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    async with factory() as setup:
        novel = await make_novel(setup, email_domain=COMMITTED_DOMAIN)
        chapter, first_revision = await add_chapter(setup, novel.id, 1, BODY)
        second_revision = await add_revision(setup, chapter.id, BODY + "\n\n사건: 다시 만난다")
        await setup.commit()
    registry = full_registry()

    async with factory() as first, factory() as second:
        # 뒤 입구가 진행 중 확정을 stale 로 돌리는 UPDATE(0행)를 지난 뒤, 확정을 넣기 직전에 세운다. 그 사이 앞 입구가 넣으면
        # 두 입구가 모두 UPDATE 를 통과한 채 INSERT 하는 경합이 된다.
        passed_stale_update, go = asyncio.Event(), asyncio.Event()
        real_flush = second.flush

        async def flush_after_the_other_inserts(*args: Any, **kwargs: Any) -> None:
            if not passed_stale_update.is_set():
                passed_stale_update.set()
                await go.wait()
            await real_flush(*args, **kwargs)

        second.flush = flush_after_the_other_inserts  # type: ignore[method-assign]
        later_task = asyncio.create_task(
            confirm(
                second, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=second_revision.id,
                actor=SYSTEM,
            )
        )
        await passed_stale_update.wait()
        # 뒤 입구가 화 행을 쥔 채 서 있다 — 입구가 화 행을 키 공유보다 세게 잡으면 앞 입구가 그 잠금을 기다린다. 행 잠금
        # 대기는 이 엔진의 잠금 대기 상한(5초)이 끊지만, 그 밖의 대기로 멈추지 않게 시간 상한을 두고, 어느 쪽으로 끝나든 뒤
        # 입구를 풀어 준다.
        try:
            async with asyncio.timeout(10):
                earlier = await confirm(
                    first, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=first_revision.id,
                    actor=SYSTEM,
                )
        finally:
            go.set()
        # 뒤 입구의 INSERT 는 앞 입구의 아직 커밋되지 않은 진행 중 확정을 부분 유니크에서 기다리다가, 앞 입구가 커밋하면
        # 위반을 맞고 세이브포인트로 되돌아가 한 번 더 한다 — 이번에는 앞 확정이 보여 stale 로 돌린다.
        await _wait_until_a_lock_is_awaited(committed_engine)
        await first.commit()
        later = await later_task
        await second.commit()

    assert earlier.created and later.created
    async with factory() as check:
        rows = (
            await check.execute(
                select(NovelBibleCommit.id, NovelBibleCommit.status).where(NovelBibleCommit.novel_id == novel.id)
            )
        ).all()
    assert dict((row.id, row.status) for row in rows) == {earlier.commit_id: "stale", later.commit_id: "pending"}
