"""첫 공개 운영자 승인이 신청 취소나 다른 운영자의 승인과 실제로 겹칠 때(독립 커넥션).

같은 커넥션의 테스트로는 두 요청이 순서대로 돌아 경쟁이 드러나지 않는다. 그래서 공개 상태 행을 붙든 트랜잭션을 먼저 세우고
그 뒤에 라우트 함수 둘을 차례로 띄워, 둘 다 정말 막혀 있는 것(`_assert_blocked`)을 확인한 뒤 붙든 것을 놓는다. 행 잠금을
기다리는 쪽은 도착 순서대로 줄을 서므로 먼저 띄운 승인이 먼저 끝난다. 막힘 확인이 없으면 둘을 순서대로 돌려도 같은 최종
상태가 나와 아무것도 증명하지 못한다.

작가의 소설 삭제·마지막 묶음 삭제와 겹치는 경우는 삭제를 먼저 띄운다. 삭제는 사용자 행을 잡은 뒤 붙든 공개 상태 행에서 막히고,
그 뒤에 띄운 승인·반려는 게시자 사용자 행에서 막혀야 한다. 승인·반려가 그 행을 건너뛰고 화 행부터 쥐면, 놓는 순간 삭제가
공개 상태 행을 얻고 화 행을 기다리며 승인·반려는 공개 상태 행을 기다려 교착한다(교착 오류는 500 감이라 테스트가 터진다)."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.db.models import AdminActionLog, AdminUser, User
from api.db.models.content import Content, ContentVersion
from api.db.models.novel import Novel, NovelChapterPublication, NovelPublication
from api.novel_public.admin import review_admin_novel
from api.novel_public.admin_schemas import AdminNovelReviewRequest
from api.novel_public.router import withdraw_novel_publication
from api.novelize.deletion import delete_novels
from api.novelize.router import delete_last_novel_batch, delete_novel
from factories import PublicNovel, _assert_blocked, _make_public_novel, _make_user

_MARKER_DOMAIN = "novel-review-races.test"


@pytest_asyncio.fixture
async def independent_factory(db_engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """커밋되는 독립 커넥션 세션 팩토리. 여기서 쓴 행은 롤백되지 않으므로 표지 도메인 회원·운영자와 그 소설·원작·감사 로그를
    끝에서 직접 지운다(FK 를 가리키는 쪽부터)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        admin_ids = (await cleanup.scalars(select(AdminUser.id).where(AdminUser.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if admin_ids:
            await cleanup.execute(delete(AdminActionLog).where(AdminActionLog.admin_id.in_(admin_ids)))
            await cleanup.execute(delete(AdminUser).where(AdminUser.id.in_(admin_ids)))
        user_ids = (await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            novel_ids = (await cleanup.scalars(select(Novel.id).where(Novel.user_id.in_(user_ids)))).all()
            await delete_novels(cleanup, novel_ids, freed_storage_keys=[])
            content_ids = select(Content.id).where(Content.creator_user_id.in_(user_ids))
            await cleanup.execute(
                update(Content).where(Content.id.in_(content_ids)).values(current_published_version_id=None)
            )
            await cleanup.execute(delete(ContentVersion).where(ContentVersion.content_id.in_(content_ids)))
            await cleanup.execute(delete(Content).where(Content.creator_user_id.in_(user_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def _admin(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with factory() as s:
        admin = AdminUser(email=f"admin-{uuid.uuid4()}@{_MARKER_DOMAIN}", password_hash="unused")
        s.add(admin)
        await s.commit()
    return admin.id


async def _pending_novel(factory: async_sessionmaker[AsyncSession]) -> PublicNovel:
    """1화 하나가 공개 신청돼 운영자 승인을 기다리는 소설. 원작은 다른 회원의 게시된 공개 작품이고 소설 공개를 허락해
    승인 때의 원작 재판정을 통과한다. 원작자에게도 표지 도메인을 달아 정리가 찾게 한다 — 소설이 지워지면 소설에서 원작을
    거슬러 찾을 수 없다."""
    async with factory() as s:
        publisher = _make_user(email=f"{uuid.uuid4()}@{_MARKER_DOMAIN}")
        s.add(publisher)
        await s.flush()
        novel = await _make_public_novel(s, publisher.id, batches=(1,))
        source = await s.get_one(Content, novel.content_id)
        version = ContentVersion(content_id=source.id, version_number=1, detail_description="설명")
        s.add(version)
        await s.flush()
        source.current_published_version_id = version.id
        source.novel_permission = "public"
        await s.execute(
            update(User).where(User.id == source.creator_user_id).values(email=f"{uuid.uuid4()}@{_MARKER_DOMAIN}")
        )
        # 대기 행의 공개 범위와 심사 칸은 한 문장으로 바꾼다(대기 행은 거둠 상태여야 한다는 CHECK).
        await s.execute(
            update(NovelPublication)
            .where(NovelPublication.novel_id == novel.novel_id)
            .values(visibility="withdrawn", review_status="pending")
        )
        await s.commit()
    return novel


def _in_own_session(
    factory: async_sessionmaker[AsyncSession], call: Callable[[AsyncSession], Awaitable[object]]
) -> "asyncio.Task[object]":
    """라우트 함수를 자기 세션으로 띄운다. 거절(`HTTPException`)은 결과로 돌려주고 성공은 None 이다 — 교착 오류 같은 500
    감은 그대로 터져 테스트를 실패시킨다."""

    async def run() -> object:
        async with factory() as s:
            try:
                await call(s)
            except HTTPException as exc:
                return exc
            return None

    return asyncio.create_task(run())


def _approve(factory: async_sessionmaker[AsyncSession], novel: PublicNovel, admin_id: uuid.UUID) -> "asyncio.Task[object]":
    body = AdminNovelReviewRequest(action="approve", admin_comment="운영자가 확인했다")
    return _in_own_session(
        factory, lambda s: review_admin_novel(novel_id=novel.novel_id, body=body, admin_id=admin_id, db=s)
    )


def _reject(factory: async_sessionmaker[AsyncSession], novel: PublicNovel, admin_id: uuid.UUID) -> "asyncio.Task[object]":
    body = AdminNovelReviewRequest(action="reject", admin_comment="원작 허락을 확인할 수 없다")
    return _in_own_session(
        factory, lambda s: review_admin_novel(novel_id=novel.novel_id, body=body, admin_id=admin_id, db=s)
    )


def _delete_novel(factory: async_sessionmaker[AsyncSession], novel: PublicNovel) -> "asyncio.Task[object]":
    async def call(s: AsyncSession) -> None:
        await delete_novel(novel=await s.get_one(Novel, novel.novel_id), db=s)

    return _in_own_session(factory, call)


def _delete_last_batch(factory: async_sessionmaker[AsyncSession], novel: PublicNovel) -> "asyncio.Task[object]":
    async def call(s: AsyncSession) -> None:
        await delete_last_novel_batch(batch_id=novel.batch_ids[-1], novel=await s.get_one(Novel, novel.novel_id), db=s)

    return _in_own_session(factory, call)


def _withdraw(factory: async_sessionmaker[AsyncSession], novel: PublicNovel) -> "asyncio.Task[object]":
    return _in_own_session(
        factory,
        lambda s: withdraw_novel_publication(novel_id=novel.novel_id, user_id=novel.publisher_id, db=s),
    )


async def _hold_publication(factory: async_sessionmaker[AsyncSession], novel: PublicNovel) -> AsyncSession:
    holder = factory()
    await holder.execute(
        select(NovelPublication.novel_id).where(NovelPublication.novel_id == novel.novel_id).with_for_update()
    )
    return holder


async def _release(holder: AsyncSession) -> None:
    await holder.rollback()
    await holder.close()


async def test_a_cancel_arriving_right_after_an_approval_becomes_a_plain_withdraw(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """승인이 공개 상태 행을 쥔 동안 도착한 신청 취소는 그 뒤에 줄을 선다. 승인이 커밋한 뒤의 취소는 지울 대기가 없으므로
    공개 상태 행과 화 공개본을 지우지 않고 지금의 거두기가 된다 — 공개 상태 행 없이 잠금만 남는 소설이 생기지 않는다."""
    novel = await _pending_novel(independent_factory)
    admin_id = await _admin(independent_factory)
    holder = await _hold_publication(independent_factory, novel)
    try:
        approve = _approve(independent_factory, novel, admin_id)
        await _assert_blocked(approve)
        cancel = _withdraw(independent_factory, novel)
        await _assert_blocked(cancel)
    finally:
        await _release(holder)

    assert await approve is None
    assert await cancel is None
    async with independent_factory() as s:
        publication = await s.get(NovelPublication, novel.novel_id)
        frozen = await s.scalar(
            select(func.count())
            .select_from(NovelChapterPublication)
            .where(NovelChapterPublication.novel_id == novel.novel_id)
        )
        locked_at = await s.scalar(select(Novel.serial_locked_at).where(Novel.id == novel.novel_id))
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("withdrawn", "approved")
    assert frozen == 1
    assert locked_at is not None


async def test_two_operators_approving_at_once_approve_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """두 운영자가 같은 대기를 동시에 승인하면 하나만 승인되고 나머지는 이미 처리됨(409)이다 — 감사 로그도 하나다."""
    novel = await _pending_novel(independent_factory)
    first_admin, second_admin = await _admin(independent_factory), await _admin(independent_factory)
    holder = await _hold_publication(independent_factory, novel)
    try:
        first = _approve(independent_factory, novel, first_admin)
        await _assert_blocked(first)
        second = _approve(independent_factory, novel, second_admin)
        await _assert_blocked(second)
    finally:
        await _release(holder)

    results = [await first, await second]
    assert results[0] is None
    assert isinstance(results[1], HTTPException)
    # `detail` 은 문자열로 선언돼 있지만 이 라우트는 dict 를 싣는다.
    detail: object = results[1].detail
    assert (results[1].status_code, detail) == (409, {"code": "NOVEL_REVIEW_NOT_PENDING"})
    async with independent_factory() as s:
        publication = await s.get(NovelPublication, novel.novel_id)
        approvals = await s.scalar(
            select(func.count())
            .select_from(AdminActionLog)
            .where(AdminActionLog.target_novel_id == novel.novel_id, AdminActionLog.action_type == "novel-review-approve")
        )
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("public", "approved")
    assert approvals == 1


def _assert_rejected(result: object, status_code: int, code: str) -> None:
    assert isinstance(result, HTTPException)
    # `detail` 은 문자열로 선언돼 있지만 이 라우트는 dict 를 싣는다.
    detail: object = result.detail
    assert (result.status_code, detail) == (status_code, {"code": code})


async def test_an_operator_rejecting_while_the_author_deletes_the_novel_waits_instead_of_deadlocking(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """작가가 승인 대기 중인 소설을 지우는 사이 운영자가 반려를 누르면, 반려는 삭제가 끝나기를 기다렸다가 지워진 소설이라
    404 다. 둘이 서로를 기다려 한쪽이 교착 오류로 끊기지 않는다."""
    novel = await _pending_novel(independent_factory)
    admin_id = await _admin(independent_factory)
    holder = await _hold_publication(independent_factory, novel)
    try:
        deletion = _delete_novel(independent_factory, novel)
        await _assert_blocked(deletion)
        reject = _reject(independent_factory, novel, admin_id)
        await _assert_blocked(reject)
    finally:
        await _release(holder)

    assert await deletion is None
    _assert_rejected(await reject, 404, "NOVEL_NOT_FOUND")
    async with independent_factory() as s:
        assert await s.get(Novel, novel.novel_id) is None
        assert await s.get(NovelPublication, novel.novel_id) is None


async def test_an_operator_approving_while_the_author_deletes_the_last_batch_waits_instead_of_deadlocking(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """작가가 승인 대기 중인 소설의 마지막(1화가 든) 묶음을 지우는 사이 운영자가 승인을 누르면, 승인은 삭제가 끝나기를
    기다렸다가 1화 공개본이 없어 409 다. 둘이 서로를 기다려 한쪽이 교착 오류로 끊기지 않고, 대기 행은 그대로 남아 운영자가
    반려로 처리할 수 있다."""
    novel = await _pending_novel(independent_factory)
    admin_id = await _admin(independent_factory)
    holder = await _hold_publication(independent_factory, novel)
    try:
        deletion = _delete_last_batch(independent_factory, novel)
        await _assert_blocked(deletion)
        approve = _approve(independent_factory, novel, admin_id)
        await _assert_blocked(approve)
    finally:
        await _release(holder)

    assert await deletion is None
    _assert_rejected(await approve, 409, "NOVEL_REVIEW_NO_FIRST_CHAPTER")
    async with independent_factory() as s:
        publication = await s.get(NovelPublication, novel.novel_id)
        frozen = await s.scalar(
            select(func.count())
            .select_from(NovelChapterPublication)
            .where(NovelChapterPublication.novel_id == novel.novel_id)
        )
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("withdrawn", "pending")
    assert frozen == 0
