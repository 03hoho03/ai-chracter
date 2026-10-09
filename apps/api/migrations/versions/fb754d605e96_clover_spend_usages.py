"""clover spend usages

Revision ID: fb754d605e96
Revises: 92f51f19de16
Create Date: 2026-10-09 13:31:32.719866

크리에이터 정산의 근거가 되는 두 테이블을 만든다.

- `clover_spend_usages`: 채팅·소설화 차감 한 번(원장 음수 행 하나)이 어느 작품·대화방·소설에서 쓰였는지. 원장 id 가 PK 라
  차감과 1:1 이다. 지불자·작품 소유자는 사본이고, 대화방·소설 id 는 그 행이 실제로 지워지므로 FK 없는 사본이다.
- `clover_spend_refunds`: 환급 한 번이 차감 배분 하나에서 돌려준 양과 그 환급 원장 행. 배분에는 시각이 없어 정산이 환급을
  환급한 달에 빼려면 이 행이 필요하다.
- CHECK 여섯(사용처 다섯·환급 하나)과 부분 인덱스의 WHERE 는 alembic 1.18.5 의 `alembic check` 가 비교하지 않는다 — 행위
  테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 새 테이블이 `clover_ledger`·`clover_spend_allocations`·`users`·`contents` 에
FK 를 걸 때 참조 테이블에 짧은 `SHARE ROW EXCLUSIVE` 가 잡히는데, 떠 있는 API 가 그 테이블들을 늘 쓰므로 오래 걸린
트랜잭션 뒤에서 기다리며 뒤의 쓰기를 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 두 테이블을 모르고 쓰지도 않는다. 옛 색의 채팅·소설화 차감은
사용처가 없고 옛 색의 환급은 환급 행을 남기지 않는다. 정산은 사용처에서 출발하므로 사용처 없는 차감은 빠지고, 그 건수는
정산 배치가 센다.

**downgrade** — 두 테이블에 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 정산 근거라 스키마를
되돌리려고 지우지 않는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = 'fb754d605e96'
down_revision: str | Sequence[str] | None = '92f51f19de16'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgradable(conn: Connection) -> None:
    for table in ('clover_spend_usages', 'clover_spend_refunds'):
        count = conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(
                f"{table} 에 {count}행이 있다 — 크리에이터 정산 근거라 downgrade 로 지우지 않는다. 옛 코드로 돌아가기만"
                " 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
            )


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 원장·배분 쓰기가 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        'clover_spend_usages',
        sa.Column('spend_ledger_id', sa.Uuid(), nullable=False),
        sa.Column('usage_kind', sa.Text(), nullable=False),
        sa.Column('spender_user_id', sa.Uuid(), nullable=False),
        sa.Column('content_id', sa.Uuid(), nullable=True),
        sa.Column('content_owner_user_id', sa.Uuid(), nullable=True),
        sa.Column('chat_room_id', sa.Uuid(), nullable=True),
        sa.Column('novel_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "(usage_kind = 'novel') = (novel_id IS NOT NULL)", name='ck_clover_spend_usages_novel_has_novel'
        ),
        sa.CheckConstraint(
            "(usage_kind = 'preview') = (content_id IS NULL)", name='ck_clover_spend_usages_preview_has_no_content'
        ),
        sa.CheckConstraint(
            "usage_kind <> 'chat' OR chat_room_id IS NOT NULL", name='ck_clover_spend_usages_chat_has_room'
        ),
        sa.CheckConstraint("usage_kind IN ('chat', 'novel', 'preview')", name='ck_clover_spend_usages_kind'),
        sa.CheckConstraint(
            '(content_id IS NULL) = (content_owner_user_id IS NULL)', name='ck_clover_spend_usages_owner_with_content'
        ),
        sa.ForeignKeyConstraint(['content_id'], ['contents.id'], name='fk_clover_spend_usages_content_id'),
        sa.ForeignKeyConstraint(
            ['content_owner_user_id'], ['users.id'], name='fk_clover_spend_usages_content_owner_user_id'
        ),
        sa.ForeignKeyConstraint(
            ['spend_ledger_id'], ['clover_ledger.id'], name='fk_clover_spend_usages_spend_ledger_id'
        ),
        sa.ForeignKeyConstraint(['spender_user_id'], ['users.id'], name='fk_clover_spend_usages_spender_user_id'),
        sa.PrimaryKeyConstraint('spend_ledger_id'),
    )
    op.create_index('ix_clover_spend_usages_created_at', 'clover_spend_usages', ['created_at'], unique=False)
    op.create_index(
        'ix_clover_spend_usages_owner_created_at',
        'clover_spend_usages',
        ['content_owner_user_id', 'created_at'],
        unique=False,
        postgresql_where=sa.text('content_owner_user_id IS NOT NULL'),
    )
    op.create_table(
        'clover_spend_refunds',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('allocation_id', sa.Uuid(), nullable=False),
        sa.Column('refund_ledger_id', sa.Uuid(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_clover_spend_refunds_amount_positive'),
        sa.ForeignKeyConstraint(
            ['allocation_id'], ['clover_spend_allocations.id'], name='fk_clover_spend_refunds_allocation_id'
        ),
        sa.ForeignKeyConstraint(
            ['refund_ledger_id'], ['clover_ledger.id'], name='fk_clover_spend_refunds_refund_ledger_id'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_clover_spend_refunds_allocation_id', 'clover_spend_refunds', ['allocation_id'], unique=False)
    op.create_index('ix_clover_spend_refunds_created_at', 'clover_spend_refunds', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_downgradable(op.get_bind())
    op.drop_index('ix_clover_spend_refunds_created_at', table_name='clover_spend_refunds')
    op.drop_index('ix_clover_spend_refunds_allocation_id', table_name='clover_spend_refunds')
    op.drop_table('clover_spend_refunds')
    op.drop_index(
        'ix_clover_spend_usages_owner_created_at',
        table_name='clover_spend_usages',
        postgresql_where=sa.text('content_owner_user_id IS NOT NULL'),
    )
    op.drop_index('ix_clover_spend_usages_created_at', table_name='clover_spend_usages')
    op.drop_table('clover_spend_usages')
