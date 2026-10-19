"""판 이력·숨김·환급 사유·재구매 유니크 마이그레이션(`d77bce2bba4c`)의 CHECK·부분 유니크·백필·옛 코드 쓰기·왕복 검증.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 백필 함수는 테스트마다 롤백되는 `db_session`
커넥션에 직접 부르고, 리비전의 downgrade·upgrade 를 실제로 돌려야 하는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션 안에서
돌린다(세션 스코프 스키마는 그대로 남는다). `alembic check` 는 CHECK 제약·복합 PK·부분 인덱스의 조건식을 비교하지 않으므로
(조건식만 바꿔 `alembic check` 를 돌려 봐도 차이를 보고하지 않았다) 이 파일의 테스트가 그 유일한 신호다."""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import ChatRoom, ContentVersion, Novel, NovelChapterEdition, NovelChapterPublication
from api.db.models.clover import CloverLedger
from api.db.models.novel import NovelPurchase
from factories import _make_draft_content, _make_novel_tree, _make_public_novel, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("d77bce2bba4c")

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    """리비전의 upgrade·downgrade 를 이 커넥션에서 alembic `op` 가 쓰이도록 돌린다."""

    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _backfill(db_session: AsyncSession) -> int:
    connection = await db_session.connection()
    filled: int = await connection.run_sync(_M.backfill_chapter_editions)
    return filled


async def _user_id(db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return user.id


async def _purchase(db_session: AsyncSession, **overrides: object) -> None:
    """정상 구매 행을 기본값으로, `overrides` 로 칸을 바꿔 넣는다. 차감 원장 행은 매번 새로 만든다(원장 유니크)."""
    buyer_id = await _user_id(db_session)
    ledger = CloverLedger(user_id=buyer_id, amount=-30, balance_after=0, kind="novel_read_spend")
    db_session.add(ledger)
    await db_session.flush()
    values: dict[str, object] = {
        "buyer_user_id": buyer_id,
        "publisher_user_id": buyer_id,
        "novel_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "chapter_ordinal": 6,
        "edition": 1,
        "spend_ledger_id": ledger.id,
        "price": 30,
    }
    values.update(overrides)
    db_session.add(NovelPurchase(**values))
    await db_session.flush()


_REFUNDED: dict[str, object] = {"refunded_at": _T0, "refunded_amount": 30}


# ── CHECK · 복합 PK ─────────────────────────────────────────────────────────
async def test_edition_number_starts_at_one_and_each_chapter_has_one_row_per_edition(db_session: AsyncSession) -> None:
    """판 번호는 1 이상이고, 한 화의 같은 판은 한 행뿐이다(복합 PK). 경계: 0 은 거부, 1 은 통과. 깨지는 시나리오: 0판 행이
    생겨 "산 때의 판"이 존재하지 않는 판을 가리키거나, 같은 판이 둘이라 산 때의 판 본문이 둘 중 아무것으로 읽힌다."""
    tree = await _make_novel_tree(db_session, await _user_id(db_session))
    row: dict[str, Any] = {
        "chapter_id": tree.chapter.id,
        "novel_id": tree.novel.id,
        "revision_id": tree.first_revision.id,
    }
    db_session.add(NovelChapterEdition(edition=1, **row))
    await db_session.flush()

    with pytest.raises(IntegrityError, match="ck_novel_chapter_editions_edition_positive"):
        async with db_session.begin_nested():
            db_session.add(NovelChapterEdition(edition=0, **row))
            await db_session.flush()
    with pytest.raises(IntegrityError, match="novel_chapter_editions_pkey"):
        async with db_session.begin_nested():
            db_session.add(NovelChapterEdition(edition=1, **{**row, "revision_id": tree.reverting_revision.id}))
            await db_session.flush()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({**_REFUNDED, "refund_reason": "DELETED"}, "ck_novel_purchases_refund_reason", id="uppercase"),
        pytest.param({**_REFUNDED, "refund_reason": "withdrawn"}, "ck_novel_purchases_refund_reason", id="unknown"),
        pytest.param(
            {"refund_reason": "novel_restricted"},
            "ck_novel_purchases_refund_reason_after_refund",
            id="reason-without-refund",
        ),
    ],
)
async def test_refund_reason_is_one_of_the_known_reasons_and_only_on_a_refund(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    """환급 사유는 정해진 값만, 사유가 있으면 환급 시각도 있다. 깨지는 시나리오: 오타 사유가 남아 독자에게 열람이 끝난 이유를
    고를 수 없거나, 환급하지 않은 구매에 사유만 붙어 "환급됐다"로 읽힌다."""
    with pytest.raises(IntegrityError, match=constraint):
        await _purchase(db_session, **overrides)


async def test_refund_reason_accepts_every_reason_and_an_old_refund_without_one(db_session: AsyncSession) -> None:
    """위 CHECK 들이 정상 모양을 막지 않는다 — 다섯 사유 각각의 환급, 사유 없는 옛 환급, 환급 없는 구매. 깨지는 시나리오:
    너무 좁은 CHECK 가 한 경로의 환급 전체를 실패시킨다."""
    for reason in ("deleted", "publisher_withdrawn", "novel_restricted", "source_restricted", "source_deleted"):
        await _purchase(db_session, **_REFUNDED, refund_reason=reason)
    await _purchase(db_session, **_REFUNDED)
    await _purchase(db_session)


async def _room_id(db_session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    content = await _make_draft_content(db_session, creator_user_id=user_id)
    version = ContentVersion(content_id=content.id, version_number=None, published_at=None, detail_description="")
    db_session.add(version)
    await db_session.flush()
    room = ChatRoom(user_id=user_id, content_id=content.id, content_version_id=version.id)
    db_session.add(room)
    await db_session.flush()
    return room.id


async def test_a_hidden_novel_is_never_tied_to_a_room(db_session: AsyncSession) -> None:
    """숨긴 소설은 방 칸이 비어 있다 — 숨기면서 방 칸을 남기거나, 숨긴 소설에 방을 다시 붙이는 쓰기는 거부된다. 숨기지 않은
    방 소설과 방 없는 숨긴 소설은 통과한다. 깨지는 시나리오: 방 칸이 남은 숨긴 소설이 방의 소설 조회로 되살아나 작가가 다시
    고치거나 공개하고, 같은 방의 새 소설 만들기는 방 유니크에 막힌다."""
    user_id = await _user_id(db_session)
    room_id = await _room_id(db_session, user_id)
    in_room = (await _make_novel_tree(db_session, user_id, chat_room_id=room_id)).novel.id
    hidden = (await _make_novel_tree(db_session, user_id)).novel.id
    await db_session.execute(sa.update(Novel).where(Novel.id == hidden).values(hidden_at=_T0))

    with pytest.raises(IntegrityError, match="ck_novels_hidden_without_room"):
        async with db_session.begin_nested():
            await db_session.execute(sa.update(Novel).where(Novel.id == in_room).values(hidden_at=_T0))
    await db_session.execute(sa.update(Novel).where(Novel.id == in_room).values(chat_room_id=None))
    with pytest.raises(IntegrityError, match="ck_novels_hidden_without_room"):
        await db_session.execute(sa.update(Novel).where(Novel.id == hidden).values(chat_room_id=room_id))


# ── 재구매 부분 유니크 ───────────────────────────────────────────────────────
async def test_a_refunded_purchase_leaves_room_for_one_new_purchase_of_the_same_chapter(
    db_session: AsyncSession,
) -> None:
    """같은 화·같은 구매자는 환급된 행이 몇이든 미환급 행을 하나 더 가질 수 있고, 미환급 행은 둘이 될 수 없다. 깨지는
    시나리오: 환급 뒤 다시 열린 화를 다시 사는 쓰기가 유니크에 막혀 500 이 되거나, 반대로 조건이 빠진 인덱스가 같은 화를
    두 번 차감하는 구매를 받아들인다."""
    buyer_id = await _user_id(db_session)
    chapter_id = uuid.uuid4()
    same = {"buyer_user_id": buyer_id, "chapter_id": chapter_id}
    await _purchase(db_session, **same, **_REFUNDED, refund_reason="novel_restricted")
    await _purchase(db_session, **same, **_REFUNDED, refund_reason="source_restricted")
    await _purchase(db_session, **same)

    with pytest.raises(IntegrityError, match="ux_novel_purchases_unrefunded_chapter_buyer"):
        await _purchase(db_session, **same)


# ── 백필 ────────────────────────────────────────────────────────────────────
async def _editions(db_session: AsyncSession, chapter_ids: list[uuid.UUID]) -> list[tuple[Any, ...]]:
    rows = await db_session.execute(
        sa.select(
            NovelChapterEdition.chapter_id,
            NovelChapterEdition.edition,
            NovelChapterEdition.novel_id,
            NovelChapterEdition.revision_id,
            NovelChapterEdition.title,
            NovelChapterEdition.author_note,
            NovelChapterEdition.published_at,
        )
        .where(NovelChapterEdition.chapter_id.in_(chapter_ids))
        .order_by(NovelChapterEdition.chapter_id, NovelChapterEdition.edition)
    )
    return [tuple(row) for row in rows]


async def test_backfill_copies_each_current_edition_once_and_a_rerun_adds_only_missing_ones(
    db_session: AsyncSession,
) -> None:
    """화 공개본마다 같은 판 번호·개정·제목·작가의 말·공개 시각의 판 행이 하나 생긴다. 다시 돌리면 아무것도 더하지 않고, 그
    사이 판 행 없이 다시 공개된 화(옛 코드)는 새 판만 더한다 — 앞 판 행은 그대로다. 깨지는 시나리오: 재실행이 판 행을
    중복으로 만들거나, 백필 이후 옛 코드가 올린 판이 이력에서 빠져 그 판을 산 사람이 산 때의 판을 못 읽는다."""
    novel = await _make_public_novel(db_session, await _user_id(db_session), batches=(2,))
    first, second = novel.chapter_ids
    await db_session.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == second)
        .values(edition=3, title="둘째 화", author_note="작가의 말", published_at=_T0)
    )
    publications = {
        chapter_id: (revision_id, title, note, published_at, edition)
        for chapter_id, revision_id, title, note, published_at, edition in (
            await db_session.execute(
                sa.select(
                    NovelChapterPublication.chapter_id,
                    NovelChapterPublication.revision_id,
                    NovelChapterPublication.title,
                    NovelChapterPublication.author_note,
                    NovelChapterPublication.published_at,
                    NovelChapterPublication.edition,
                ).where(NovelChapterPublication.novel_id == novel.novel_id)
            )
        ).tuples()
    }

    assert await _backfill(db_session) == 2
    expected = sorted(
        (chapter_id, edition, novel.novel_id, revision_id, title, note, published_at)
        for chapter_id, (revision_id, title, note, published_at, edition) in publications.items()
    )
    assert await _editions(db_session, [first, second]) == expected
    assert [row[1] for row in expected if row[0] == second] == [3]

    assert await _backfill(db_session) == 0
    assert await _editions(db_session, [first, second]) == expected

    later = _T0 + timedelta(days=1)
    await db_session.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == second)
        .values(edition=4, title="고친 둘째 화", published_at=later)
    )
    assert await _backfill(db_session) == 1
    rows = await _editions(db_session, [second])
    assert [(row[1], row[4], row[6]) for row in rows] == [(3, "둘째 화", _T0), (4, "고친 둘째 화", later)]


# ── 옛 코드 쓰기 ────────────────────────────────────────────────────────────
async def test_old_code_writes_without_the_new_columns_still_pass(db_session: AsyncSession) -> None:
    """새 칸·새 표를 모르는 옛 코드 꼴의 쓰기(원시 SQL)가 모두 통과한다 — 소설 INSERT(숨김 칸 없음), 구매 INSERT(사유 칸
    없음), 삭제 환급 UPDATE(사유 없이 환급 시각·양만), 다시 공개 UPDATE(판 행 없이 공개본만). 깨지는 시나리오: 배포 겹침 동안
    옛 이미지의 소설 만들기·구매·삭제·다시 공개가 새 CHECK 에 걸려 500 이 된다."""
    user_id = await _user_id(db_session)
    novel = await _make_public_novel(db_session, user_id, batches=(6,))
    connection = await db_session.connection()
    await connection.execute(
        sa.text(
            "INSERT INTO novels (id, user_id, content_id, content_type, content_title)"
            " VALUES (:id, :user_id, :content_id, 'story', '원작')"
        ),
        {"id": uuid.uuid4(), "user_id": user_id, "content_id": uuid.uuid4()},
    )
    ledger_id = uuid.uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO clover_ledger (id, user_id, amount, balance_after, kind)"
            " VALUES (:id, :user_id, -30, 0, 'novel_read_spend')"
        ),
        {"id": ledger_id, "user_id": user_id},
    )
    purchase_id = uuid.uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO novel_purchases (id, buyer_user_id, publisher_user_id, novel_id, chapter_id, chapter_ordinal,"
            " edition, spend_ledger_id, price) VALUES (:id, :buyer, :publisher, :novel_id, :chapter_id, 6, 1, :ledger, 30)"
        ),
        {
            "id": purchase_id,
            "buyer": user_id,
            "publisher": user_id,
            "novel_id": novel.novel_id,
            "chapter_id": novel.chapter_ids[5],
            "ledger": ledger_id,
        },
    )
    await connection.execute(
        sa.text("UPDATE novel_purchases SET refunded_at = now(), refunded_amount = 30 WHERE id = :id"),
        {"id": purchase_id},
    )
    await connection.execute(
        sa.text(
            "UPDATE novel_chapter_publications SET title = '다시 공개', edition = edition + 1, published_at = now()"
            " WHERE chapter_id = :chapter_id"
        ),
        {"chapter_id": novel.chapter_ids[0]},
    )

    reason = await db_session.scalar(sa.select(NovelPurchase.refund_reason).where(NovelPurchase.id == purchase_id))
    assert reason is None


# ── 왕복 ────────────────────────────────────────────────────────────────────
async def _scalar(connection: AsyncConnection, sql: str, **params: object) -> Any:
    return (await connection.execute(sa.text(sql), params)).scalar_one()


async def test_downgrade_restores_the_old_unique_and_upgrade_backfills_again(ddl_engine: AsyncEngine) -> None:
    """리비전을 실제로 내리고 → 옛 스키마를 확인하고 → 다시 올린다. 내리면 판 이력 표·숨김 칸·사유 칸이 사라지고 옛 (화,
    구매자) 전체 유니크가 돌아와 환급된 행이 있어도 같은 화 두 번째 행을 막는다. 다시 올리면 부분 유니크로 돌아가 그 두 번째
    행을 받고, 내릴 때 판 이력과 함께 사라졌던 화 공개본의 지금 판이 다시 채워진다. 깨지는 시나리오: downgrade 가 옛 유니크를 되살리지 않아 옛 코드의
    구매가 중복 차감을 받아들이거나, 다시 올린 스키마에 판 이력이 비어 산 때의 판을 못 고른다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            # 공개 소설은 내리기 전에 만든다 — ORM 의 소설 INSERT 는 내린 스키마에 없는 숨김 칸을 안다.
            session = AsyncSession(bind=connection)
            buyer = _make_user()
            session.add(buyer)
            await session.flush()
            novel = await _make_public_novel(session, buyer.id, batches=(6,))
            chapter_id = novel.chapter_ids[5]
            await _run(connection, _M.downgrade)
            editions_table = await _scalar(connection, "SELECT to_regclass('novel_chapter_editions') IS NOT NULL")
            new_columns = await _scalar(
                connection,
                "SELECT count(*) FROM information_schema.columns"
                " WHERE (table_name, column_name) IN (('novels', 'hidden_at'), ('novel_purchases', 'refund_reason'))",
            )

            async def old_purchase(refunded: bool) -> None:
                ledger_id = uuid.uuid4()
                await connection.execute(
                    sa.text(
                        "INSERT INTO clover_ledger (id, user_id, amount, balance_after, kind)"
                        " VALUES (:id, :user_id, -30, 0, 'novel_read_spend')"
                    ),
                    {"id": ledger_id, "user_id": buyer.id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO novel_purchases (id, buyer_user_id, publisher_user_id, novel_id, chapter_id,"
                        " chapter_ordinal, edition, spend_ledger_id, price, refunded_at, refunded_amount)"
                        " VALUES (:id, :buyer, :buyer, :novel_id, :chapter_id, 6, 1, :ledger, 30, :at, :amount)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "buyer": buyer.id,
                        "novel_id": novel.novel_id,
                        "chapter_id": chapter_id,
                        "ledger": ledger_id,
                        "at": _T0 if refunded else None,
                        "amount": 30 if refunded else None,
                    },
                )

            await old_purchase(refunded=True)
            savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError, match="ux_novel_purchases_chapter_id_buyer_user_id"):
                await old_purchase(refunded=False)
            await savepoint.rollback()

            await _run(connection, _M.upgrade)
            await old_purchase(refunded=False)
            backfilled = await _scalar(
                connection,
                "SELECT count(*) FROM novel_chapter_editions WHERE novel_id = :novel_id",
                novel_id=novel.novel_id,
            )
        finally:
            await transaction.rollback()

    assert (editions_table, new_columns) == (False, 0)
    assert backfilled == 6


async def test_downgrade_refuses_while_a_chapter_was_bought_again_after_a_refund(ddl_engine: AsyncEngine) -> None:
    """환급 뒤 같은 화를 다시 산 행이 있으면 옛 전체 유니크를 만들 수 없으므로 downgrade 가 아무것도 바꾸기 전에 멈춘다.
    깨지는 시나리오: 판 이력 표를 먼저 지운 뒤 유니크 생성에서 실패해 원인을 알 수 없는 오류로 끝나거나, 가드 없이 재구매
    행을 지워 거래 기록을 잃는다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            buyer_id = await _user_id(session)
            chapter_id = uuid.uuid4()
            await _purchase(session, buyer_user_id=buyer_id, chapter_id=chapter_id, **_REFUNDED)
            await _purchase(session, buyer_user_id=buyer_id, chapter_id=chapter_id)

            with pytest.raises(RuntimeError, match="1쌍"):
                await _run(connection, _M.downgrade)
            still_there = await _scalar(connection, "SELECT to_regclass('novel_chapter_editions') IS NOT NULL")
        finally:
            await transaction.rollback()

    assert still_there is True
