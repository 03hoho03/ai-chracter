"""creator payout core

Revision ID: 9b1c1ed8faad
Revises: b09b766254c6
Create Date: 2026-10-09 15:25:05.198482

크리에이터 정산의 신청·확정 테이블 셋을 만든다.

- `creator_payout_applications`: 정산 신청 하나. 승인되면 적립 구간(`accrual_start_at` ~ `revoked_at`)과 월 확정 시작
  시각(`monthly_from_at`)이 생긴다. 정산 계산이 "그 차감이 적립 구간 안이었나"를 이 행에서 본다.
- `creator_payout_confirmations`: 크리에이터 한 명의 확정 한 번(소급 또는 월). 같은 사람의 같은 달 월 확정과 두 번째
  소급은 부분 유니크가 막는다.
- `creator_payout_confirmation_lines`: 확정 행의 작품 × 결제별 내역(복합 PK). 확정 뒤 결제가 취소되면 그 결제의 앞선
  줄을 찾아 몫을 줄이므로 `payment_id` 인덱스를 둔다.
- CHECK·부분 인덱스의 WHERE·복합 PK 는 alembic 1.18.5 의 `alembic check` 가 비교하지 않는다 — 행위 테스트가 유일한
  검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 새 테이블이 `users`·`admin_users`·`contents`·`payments` 에 FK 를 걸 때
참조 테이블에 짧은 `SHARE ROW EXCLUSIVE` 가 잡히는데, 떠 있는 API 가 그 테이블들을 늘 쓰므로 오래 걸린 트랜잭션 뒤에서
기다리며 뒤의 쓰기를 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 세 테이블을 모르고 쓰지도 않는다.

**downgrade** — 세 테이블에 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 신청은 적립 구간의
근거이고 확정·내역은 지급·세무의 근거라 스키마를 되돌리려고 지우지 않는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = '9b1c1ed8faad'
down_revision: str | Sequence[str] | None = 'b09b766254c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgradable(conn: Connection) -> None:
    for table in ('creator_payout_confirmation_lines', 'creator_payout_confirmations', 'creator_payout_applications'):
        count = conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(
                f"{table} 에 {count}행이 있다 — 크리에이터 정산 근거라 downgrade 로 지우지 않는다. 옛 코드로 돌아가기만"
                " 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
            )


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 쓰기가 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('creator_payout_applications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('consented_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('privacy_version', sa.Text(), nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by_admin_id', sa.Uuid(), nullable=True),
    sa.Column('decision_reason', sa.Text(), server_default='', nullable=False),
    sa.Column('accrual_start_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('monthly_from_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by_admin_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name='ck_creator_payout_applications_decided'),
    sa.CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name='ck_creator_payout_applications_revoked'),
    sa.CheckConstraint("(status IN ('approved', 'revoked')) = (accrual_start_at IS NOT NULL)", name='ck_creator_payout_applications_accrual'),
    sa.CheckConstraint("(status IN ('approved', 'revoked')) = (monthly_from_at IS NOT NULL) AND accrual_start_at <= monthly_from_at", name='ck_creator_payout_applications_monthly_from'),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'revoked')", name='ck_creator_payout_applications_status'),
    sa.ForeignKeyConstraint(['decided_by_admin_id'], ['admin_users.id'], name='fk_creator_payout_applications_decided_by_admin_id'),
    sa.ForeignKeyConstraint(['revoked_by_admin_id'], ['admin_users.id'], name='fk_creator_payout_applications_revoked_by_admin_id'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_creator_payout_applications_user_id'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_creator_payout_applications_status_applied_at', 'creator_payout_applications', ['status', 'applied_at'], unique=False)
    op.create_index('ux_creator_payout_applications_user_id_live', 'creator_payout_applications', ['user_id'], unique=True, postgresql_where=sa.text("status IN ('pending', 'approved')"))
    op.create_table('creator_payout_confirmations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('period_month', sa.Date(), nullable=True),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('gross_units', sa.Integer(), nullable=False),
    sa.Column('refunded_units', sa.Integer(), nullable=False),
    sa.Column('rate_bps', sa.Integer(), nullable=False),
    sa.Column('exact_krw', sa.Numeric(precision=30, scale=10), nullable=False),
    sa.Column('amount_krw', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'monthly') = (period_month IS NOT NULL)", name='ck_creator_payout_confirmations_period_month'),
    sa.CheckConstraint("kind IN ('retro', 'monthly')", name='ck_creator_payout_confirmations_kind'),
    sa.CheckConstraint('gross_units >= 0 AND refunded_units >= 0', name='ck_creator_payout_confirmations_units_non_negative'),
    sa.CheckConstraint('rate_bps BETWEEN 1 AND 10000', name='ck_creator_payout_confirmations_rate_bps'),
    sa.CheckConstraint('window_start < window_end', name='ck_creator_payout_confirmations_window'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_creator_payout_confirmations_user_id'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_creator_payout_confirmations_user_id_window_end', 'creator_payout_confirmations', ['user_id', sa.literal_column('window_end DESC')], unique=False)
    op.create_index('ux_creator_payout_confirmations_monthly', 'creator_payout_confirmations', ['user_id', 'period_month'], unique=True, postgresql_where=sa.text("kind = 'monthly'"))
    op.create_index('ux_creator_payout_confirmations_retro', 'creator_payout_confirmations', ['user_id'], unique=True, postgresql_where=sa.text("kind = 'retro'"))
    op.create_table('creator_payout_confirmation_lines',
    sa.Column('confirmation_id', sa.Uuid(), nullable=False),
    sa.Column('content_id', sa.Uuid(), nullable=False),
    sa.Column('payment_id', sa.Uuid(), nullable=False),
    sa.Column('net_units', sa.Integer(), nullable=False),
    sa.Column('cancel_adjust_krw', sa.Numeric(precision=30, scale=10), nullable=False),
    sa.Column('exact_krw', sa.Numeric(precision=30, scale=10), nullable=False),
    sa.CheckConstraint('cancel_adjust_krw <= 0', name='ck_creator_payout_confirmation_lines_cancel_adjust'),
    sa.ForeignKeyConstraint(['confirmation_id'], ['creator_payout_confirmations.id'], name='fk_creator_payout_confirmation_lines_confirmation_id'),
    sa.ForeignKeyConstraint(['content_id'], ['contents.id'], name='fk_creator_payout_confirmation_lines_content_id'),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name='fk_creator_payout_confirmation_lines_payment_id'),
    sa.PrimaryKeyConstraint('confirmation_id', 'content_id', 'payment_id')
    )
    op.create_index('ix_creator_payout_confirmation_lines_payment_id', 'creator_payout_confirmation_lines', ['payment_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_downgradable(op.get_bind())
    op.drop_index('ix_creator_payout_confirmation_lines_payment_id', table_name='creator_payout_confirmation_lines')
    op.drop_table('creator_payout_confirmation_lines')
    op.drop_index('ux_creator_payout_confirmations_retro', table_name='creator_payout_confirmations', postgresql_where=sa.text("kind = 'retro'"))
    op.drop_index('ux_creator_payout_confirmations_monthly', table_name='creator_payout_confirmations', postgresql_where=sa.text("kind = 'monthly'"))
    op.drop_index('ix_creator_payout_confirmations_user_id_window_end', table_name='creator_payout_confirmations')
    op.drop_table('creator_payout_confirmations')
    op.drop_index('ux_creator_payout_applications_user_id_live', table_name='creator_payout_applications', postgresql_where=sa.text("status IN ('pending', 'approved')"))
    op.drop_index('ix_creator_payout_applications_status_applied_at', table_name='creator_payout_applications')
    op.drop_table('creator_payout_applications')
