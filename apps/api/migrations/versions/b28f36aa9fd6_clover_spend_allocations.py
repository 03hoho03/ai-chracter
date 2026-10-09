"""clover spend allocations

Revision ID: b28f36aa9fd6
Revises: d9768bc0cfee
Create Date: 2026-10-08 12:00:00.000000

차감 한 번이 어느 로트에서 얼마를 깎았는지 남기는 `clover_spend_allocations` 를 만들고, 소설화 작업 행에 선차감의 원장
id `novel_jobs.spend_ledger_id` 를 더한다. 환급이 이 기록을 따라 깎은 그 로트로 되돌리게 하려는 것이다 — 유료로 산
클로버를 쓴 몫을 무료 로트로 돌려주면, 그 구매의 남은 유료 수량(환불 견적의 바탕)이 실제보다 작아진다.

- 배분 CHECK 둘: `amount > 0`, `0 <= refunded_amount <= amount`. 뒤의 것이 이중 환급의 마지막 그물이다(깎은 양을 넘는
  환급은 거절된다). alembic 1.18.5 의 `alembic check` 는 CHECK 를 비교하지 않아 행위 테스트가 유일한 검증이다.
- 인덱스: `(spend_ledger_id, seq)` 유니크(환급 조회 겸), `lot_id`(로트별 사용량 집계·FK 검사).
- `novel_jobs.spend_ledger_id` 는 NULL 허용이다. 차감 0 인 연쇄 자식과 이 리비전 전의 작업이 NULL 이다.

첫 문장은 앞 리비전들과 같은 `SET LOCAL lock_timeout = '5s'` 다(떠 있는 API 가 `novel_jobs` 를 읽는다). NULL 칸 추가는
메타데이터만 바꾸므로 잠금이 짧다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 배분을 남기지 않고 `spend_ledger_id` 를 모른다. 새 테이블은
옛 쓰기를 받지 않고 새 칸은 NULL 허용이라 옛 쓰기가 거절되지 않는다. 옛 색이 만든 차감은 배분이 없으므로 새 코드는 그
환급을 예전처럼 무기한 새 로트로 돌려준다.

**downgrade** — 칸과 테이블을 지운다. 막지 않는다: 배분은 차감에서 파생된 기록이라 잃어도 잔액과 로트 합의 불변식은
그대로이고, 잃는 것은 "깎은 그 로트로 환급"뿐이다(옛 코드는 어차피 새 로트로 환급한다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b28f36aa9fd6'
down_revision: str | Sequence[str] | None = 'd9768bc0cfee'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        'clover_spend_allocations',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('spend_ledger_id', sa.Uuid(), nullable=False),
        sa.Column('lot_id', sa.Uuid(), nullable=False),
        sa.Column('seq', sa.SmallInteger(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('refunded_amount', sa.Integer(), server_default='0', nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_clover_spend_allocations_amount_positive'),
        sa.CheckConstraint(
            'refunded_amount >= 0 AND refunded_amount <= amount',
            name='ck_clover_spend_allocations_refunded_in_range',
        ),
        sa.ForeignKeyConstraint(
            ['spend_ledger_id'], ['clover_ledger.id'], name='fk_clover_spend_allocations_spend_ledger_id'
        ),
        sa.ForeignKeyConstraint(['lot_id'], ['clover_lots.id'], name='fk_clover_spend_allocations_lot_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ux_clover_spend_allocations_spend_ledger_id_seq',
        'clover_spend_allocations',
        ['spend_ledger_id', 'seq'],
        unique=True,
    )
    op.create_index('ix_clover_spend_allocations_lot_id', 'clover_spend_allocations', ['lot_id'], unique=False)

    op.add_column('novel_jobs', sa.Column('spend_ledger_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_novel_jobs_spend_ledger_id', 'novel_jobs', 'clover_ledger', ['spend_ledger_id'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint('fk_novel_jobs_spend_ledger_id', 'novel_jobs', type_='foreignkey')
    op.drop_column('novel_jobs', 'spend_ledger_id')
    op.drop_index('ix_clover_spend_allocations_lot_id', table_name='clover_spend_allocations')
    op.drop_index('ux_clover_spend_allocations_spend_ledger_id_seq', table_name='clover_spend_allocations')
    op.drop_table('clover_spend_allocations')
