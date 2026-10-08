"""payments

Revision ID: dd7fdcffccd7
Revises: b28f36aa9fd6
Create Date: 2026-10-08 19:20:23.911050

클로버 구매 주문 `payments`, 그 취소 기록 `payment_cancellations` 를 만들고, 구매로 생긴 로트가 자기 결제를 가리키게
`clover_lots.payment_id` 를 더한다. 환불이 그 구매의 남은 유료·보너스 로트를 정확히 집으려면 로트에 결제 참조가 있어야 한다.

- 주문 CHECK 셋: 상태 값 범위, 금액·유료 수량 양수와 보너스 0 이상, 성공 취소액이 0 ~ 결제액.
- 취소 CHECK: 출처·상태 값 범위, 금액 양수, 어드민 행만 어드민 id·신청 접수일을 갖는다, 회수 수량 0 이상. 부분 유니크
  `(payment_id) WHERE status = 'requested'` 가 한 결제에 진행 중 환불 시도를 하나로 묶는다.
- 로트 CHECK `ck_clover_lots_purchase_has_payment`: 구매 kind 와 결제 참조가 함께 있거나 함께 없다. 부분 유니크
  `(payment_id, kind) WHERE payment_id IS NOT NULL` 이 한 결제에 유료·보너스 로트를 하나씩으로 묶는다(이중 지급의 마지막
  방어선, 환불 조회 인덱스 겸).
- alembic 1.18.5 의 `alembic check` 는 CHECK 와 부분 인덱스의 WHERE 를 비교하지 않는다 — 행위 테스트가 유일한 검증이다.
  기존 테이블에 붙는 로트 CHECK 는 autogenerate 가 만들지도 않아 손으로 더했다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(떠 있는 API 가 `clover_lots` 를 늘 읽고 쓴다). NULL 칸 추가는 메타데이터만
바꾸고, CHECK 추가·부분 유니크 생성은 로트 표를 한 번 훑는다(행 수가 작다).

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 새 두 테이블을 모르고, 로트를 쓸 때 `payment_id` 를 비운 채
구매가 아닌 kind 로만 쓴다. 새 CHECK 는 그 쓰기(구매 kind 아님·결제 참조 없음)를 받아들이고, 부분 유니크는 결제 참조가
있는 행만 보므로 옛 쓰기를 거절하지 않는다.

**downgrade** — 결제 행이 하나라도 있으면 멈춘다(`RuntimeError`). 결제 기록은 법정 보존 대상이라 스키마를 되돌리려고
지우지 않는다.

**운영 메모 — 되돌리기**: "downgrade 없이 이미지만 되돌린다"는 **결제를 켜기 전까지만** 안전하다. 구매가 한 건이라도 생긴
뒤 옛 이미지로 돌아가면, 옛 코드의 원장 범주 맵에 `purchase_*` 가 없어 구매자의 클로버 내역 API 가 500 이 되고, 옛
어드민 회수는 kind 를 거르지 않아 구매 로트까지 깎는다(환불 견적의 바탕이 결제 기록 밖에서 줄어든다). 결제를 켠 뒤의
되돌리기는 이미지가 아니라 `PAYMENTS_ENABLED=false` 로 한다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = 'dd7fdcffccd7'
down_revision: str | Sequence[str] | None = 'b28f36aa9fd6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgradable(conn: Connection) -> None:
    count = conn.execute(sa.text("SELECT count(*) FROM payments")).scalar_one()
    if count:
        raise RuntimeError(
            f"payments 에 결제 기록 {count}행이 있다 — 법정 보존 대상이라 downgrade 로 지우지 않는다. 옛 코드로 돌아가기만"
            " 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        'payments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('payment_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('product_key', sa.Text(), nullable=False),
        sa.Column('order_name', sa.Text(), nullable=False),
        sa.Column('amount_krw', sa.Integer(), nullable=False),
        sa.Column('paid_amount', sa.Integer(), nullable=False),
        sa.Column('bonus_amount', sa.Integer(), nullable=False),
        sa.Column('channel_key', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('consented_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('terms_version', sa.Text(), nullable=False),
        sa.Column('refund_policy_version', sa.Text(), nullable=False),
        sa.Column('transaction_id', sa.Text(), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_amount_krw', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'mismatch', 'owner_withdrawn', 'cancelled', 'partially_cancelled')",
            name='ck_payments_status',
        ),
        sa.CheckConstraint(
            'amount_krw > 0 AND paid_amount > 0 AND bonus_amount >= 0', name='ck_payments_amounts_positive'
        ),
        sa.CheckConstraint(
            'cancelled_amount_krw >= 0 AND cancelled_amount_krw <= amount_krw', name='ck_payments_cancelled_in_range'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_payments_user_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_payments_user_id_created_at', 'payments', ['user_id', sa.literal_column('created_at DESC')], unique=False
    )
    op.create_index('ux_payments_payment_id', 'payments', ['payment_id'], unique=True)

    op.create_table(
        'payment_cancellations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('payment_id', sa.Uuid(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('amount_krw', sa.Integer(), nullable=False),
        sa.Column('ratio_percent', sa.SmallInteger(), nullable=True),
        sa.Column('request_received_on', sa.Date(), nullable=True),
        sa.Column('company_fault', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('clawback_paid', sa.Integer(), server_default='0', nullable=False),
        sa.Column('clawback_bonus', sa.Integer(), server_default='0', nullable=False),
        sa.Column('portone_cancellation_id', sa.Text(), nullable=True),
        sa.Column('admin_id', sa.Uuid(), nullable=True),
        sa.Column('reason', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("source IN ('admin', 'console')", name='ck_payment_cancellations_source'),
        sa.CheckConstraint("status IN ('requested', 'succeeded', 'failed')", name='ck_payment_cancellations_status'),
        sa.CheckConstraint('amount_krw > 0', name='ck_payment_cancellations_amount_positive'),
        sa.CheckConstraint(
            "(source = 'admin') = (admin_id IS NOT NULL)", name='ck_payment_cancellations_admin_source'
        ),
        sa.CheckConstraint(
            "(source = 'admin') = (request_received_on IS NOT NULL)", name='ck_payment_cancellations_admin_received_on'
        ),
        sa.CheckConstraint(
            'clawback_paid >= 0 AND clawback_bonus >= 0', name='ck_payment_cancellations_clawback_non_negative'
        ),
        sa.ForeignKeyConstraint(['admin_id'], ['admin_users.id'], name='fk_payment_cancellations_admin_id'),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name='fk_payment_cancellations_payment_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ux_payment_cancellations_payment_id_requested',
        'payment_cancellations',
        ['payment_id'],
        unique=True,
        postgresql_where=sa.text("status = 'requested'"),
    )
    op.create_index(
        'ux_payment_cancellations_portone_cancellation_id',
        'payment_cancellations',
        ['portone_cancellation_id'],
        unique=True,
    )

    op.add_column('clover_lots', sa.Column('payment_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_clover_lots_payment_id', 'clover_lots', 'payments', ['payment_id'], ['id'])
    op.create_check_constraint(
        'ck_clover_lots_purchase_has_payment',
        'clover_lots',
        "(kind IN ('purchase_paid', 'purchase_bonus')) = (payment_id IS NOT NULL)",
    )
    op.create_index(
        'ux_clover_lots_payment_id_kind',
        'clover_lots',
        ['payment_id', 'kind'],
        unique=True,
        postgresql_where=sa.text('payment_id IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_downgradable(op.get_bind())
    op.drop_index(
        'ux_clover_lots_payment_id_kind', table_name='clover_lots', postgresql_where=sa.text('payment_id IS NOT NULL')
    )
    op.drop_constraint('ck_clover_lots_purchase_has_payment', 'clover_lots', type_='check')
    op.drop_constraint('fk_clover_lots_payment_id', 'clover_lots', type_='foreignkey')
    op.drop_column('clover_lots', 'payment_id')
    op.drop_index('ux_payment_cancellations_portone_cancellation_id', table_name='payment_cancellations')
    op.drop_index(
        'ux_payment_cancellations_payment_id_requested',
        table_name='payment_cancellations',
        postgresql_where=sa.text("status = 'requested'"),
    )
    op.drop_table('payment_cancellations')
    op.drop_index('ux_payments_payment_id', table_name='payments')
    op.drop_index('ix_payments_user_id_created_at', table_name='payments')
    op.drop_table('payments')
