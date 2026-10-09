"""사용처에 자기 플레이 칸을 더하는 마이그레이션 `10d8d3ed6e0f` 의 백필과 downgrade 가드 검증.

마이그레이션 자체는 다시 돌리지 않는다. 세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했으므로 백필
문장을 테스트마다 롤백되는 `db_session` 커넥션에서 그대로 실행한다. 행은 실제 차감으로 만들고 칸을 일부러 틀어 둔 뒤
백필이 바로잡는지 본다."""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.clover import SpendUsage, spend
from api.db.models.clover import CloverSpendUsage
from factories import _make_draft_content, _make_user_with_clover_lot

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("10d8d3ed6e0f")


async def test_backfill_marks_only_the_owners_own_play(db_session: AsyncSession) -> None:
    """작가가 자기 작품에서 쓴 행만 참이고, 남의 작품에서 쓴 행과 작품 없는 미리보기는 거짓이다.

    빨개지는 조건: 모두 거짓으로 채우면 자기 플레이 행이, 비교를 뒤집으면 남의 플레이 행이 틀리고, 미리보기의 NULL 비교를
    거짓으로 바꾸지 않으면 NOT NULL 에 걸린다."""
    owner = await _make_user_with_clover_lot(db_session, clover_balance=30)
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)
    content = await _make_draft_content(db_session, creator_user_id=owner.id)
    expected: dict[uuid.UUID, bool] = {}
    for user_id, usage, self_play in [
        (owner.id, SpendUsage("chat", content_id=content.id, chat_room_id=uuid.uuid4()), True),
        (player.id, SpendUsage("chat", content_id=content.id, chat_room_id=uuid.uuid4()), False),
        (owner.id, SpendUsage("preview"), False),
    ]:
        spent = await spend(db_session, user_id=user_id, amount=10, kind="chat_spend", usage=usage)
        assert spent is not None
        expected[spent.ledger_id] = self_play
    # 모두 거짓으로 덮어 자기 플레이 행을 틀어 둔다(모두 참으로 덮으면 미리보기가 CHECK 에 걸린다).
    await db_session.execute(sa.update(CloverSpendUsage).values(is_self_play=False))

    await db_session.execute(sa.text(_M.BACKFILL_SELF_PLAY_SQL))

    rows = (await db_session.execute(sa.select(CloverSpendUsage.spend_ledger_id, CloverSpendUsage.is_self_play))).tuples()
    assert dict(rows.all()) == expected


async def test_downgrade_refuses_while_a_spender_is_erased(db_session: AsyncSession) -> None:
    """탈퇴로 지불자가 끊긴 행이 있으면 아무것도 바꾸기 전에 멈춘다. 깨지는 시나리오: 가드가 없으면 NOT NULL 을 다시 걸다
    실패하거나, 그 행을 지워 작품 소유자의 정산 근거를 없애는 손 작업으로 이어진다."""
    player = await _make_user_with_clover_lot(db_session, clover_balance=30)
    owner = await _make_user_with_clover_lot(db_session, clover_balance=0)
    content = await _make_draft_content(db_session, creator_user_id=owner.id)
    spent = await spend(
        db_session,
        user_id=player.id,
        amount=10,
        kind="chat_spend",
        usage=SpendUsage("chat", content_id=content.id, chat_room_id=uuid.uuid4()),
    )
    assert spent is not None
    await db_session.execute(sa.update(CloverSpendUsage).values(spender_user_id=None))

    def downgrade(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            _M.downgrade()

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="지불자가 끊긴 행이 1개"):
        await connection.run_sync(downgrade)
    assert await db_session.scalar(sa.select(CloverSpendUsage.is_self_play)) is False
