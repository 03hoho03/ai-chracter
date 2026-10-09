"""creator payouts

Revision ID: 46bda819407c
Revises: 3554549a4ea2
Create Date: 2026-10-09 23:12:32.567815

크리에이터 지급 테이블 둘을 만든다.

- `creator_payout_profiles`: 지급 정보 한 판(실명·주민등록번호·계좌번호는 앱 키로 암호화한 바이트, 은행 코드와 계좌 끝
  4자리는 평문). 고치지 않고 새 판을 넣으며, 지금 쓰는 판은 한 사람에 하나(부분 유니크).
- `creator_payouts`: 지급 신청과 그 처리 기록. 신청 때의 지급 정보 판을 FK 로 가리키고 원천징수 세율·세액을 남긴다.
  처리 중(`requested`)인 지급은 한 사람에 하나(부분 유니크).
- CHECK·부분 인덱스의 WHERE 는 `alembic check` 가 비교하지 않는다 — 행위 테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 새 테이블이 `users`·`admin_users` 에 FK 를 걸 때 참조 테이블에 짧은
`SHARE ROW EXCLUSIVE` 가 잡히는데, 떠 있는 API 가 `users` 를 늘 쓰므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 쓰기를
줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 두 테이블을 모르고 쓰지도 않는다.

**downgrade** — 두 테이블에 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 지급 기록은 원천징수와
지급명세서의 근거이고 지급 정보는 그 수취인이라 스키마를 되돌리려고 지우지 않는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = '46bda819407c'
down_revision: str | Sequence[str] | None = '3554549a4ea2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgradable(conn: Connection) -> None:
    for table in ('creator_payouts', 'creator_payout_profiles'):
        count = conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(
                f"{table} 에 {count}행이 있다 — 크리에이터 지급 근거라 downgrade 로 지우지 않는다. 옛 코드로 돌아가기만"
                " 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
            )


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 쓰기가 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('creator_payout_profiles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('key_id', sa.Text(), nullable=False),
    sa.Column('legal_name_ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('rrn_ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('account_number_ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('bank_code', sa.Text(), nullable=False),
    sa.Column('account_last4', sa.Text(), nullable=False),
    sa.Column('consented_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('privacy_version', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("key_id <> ''", name='ck_creator_payout_profiles_key_id'),
    sa.CheckConstraint('char_length(account_last4) = 4', name='ck_creator_payout_profiles_account_last4'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_creator_payout_profiles_user_id'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ux_creator_payout_profiles_user_id_current', 'creator_payout_profiles', ['user_id'], unique=True, postgresql_where=sa.text('superseded_at IS NULL'))
    op.create_table('creator_payouts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('amount_krw', sa.Integer(), nullable=False),
    sa.Column('for_withdrawal', sa.Boolean(), nullable=False),
    sa.Column('income_tax_rate_bps', sa.Integer(), nullable=False),
    sa.Column('income_tax_krw', sa.Integer(), nullable=False),
    sa.Column('local_tax_krw', sa.Integer(), nullable=False),
    sa.Column('net_amount_krw', sa.Integer(), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('transferred_on', sa.Date(), nullable=True),
    sa.Column('returned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by_admin_id', sa.Uuid(), nullable=True),
    sa.Column('admin_memo', sa.Text(), server_default='', nullable=False),
    sa.Column('return_reason', sa.Text(), server_default='', nullable=False),
    sa.CheckConstraint("(status = 'paid') = (paid_at IS NOT NULL AND transferred_on IS NOT NULL)", name='ck_creator_payouts_paid'),
    sa.CheckConstraint("(status = 'returned') = (returned_at IS NOT NULL)", name='ck_creator_payouts_returned'),
    sa.CheckConstraint("status IN ('requested', 'paid', 'returned')", name='ck_creator_payouts_status'),
    sa.CheckConstraint('amount_krw > 0', name='ck_creator_payouts_amount'),
    sa.CheckConstraint('income_tax_krw >= 0 AND local_tax_krw >= 0', name='ck_creator_payouts_taxes_non_negative'),
    sa.CheckConstraint('income_tax_rate_bps > 0', name='ck_creator_payouts_income_tax_rate_bps'),
    sa.CheckConstraint('net_amount_krw = amount_krw - income_tax_krw - local_tax_krw', name='ck_creator_payouts_net_amount'),
    sa.ForeignKeyConstraint(['decided_by_admin_id'], ['admin_users.id'], name='fk_creator_payouts_decided_by_admin_id'),
    sa.ForeignKeyConstraint(['profile_id'], ['creator_payout_profiles.id'], name='fk_creator_payouts_profile_id'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_creator_payouts_user_id'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_creator_payouts_status_requested_at', 'creator_payouts', ['status', 'requested_at'], unique=False)
    op.create_index('ix_creator_payouts_user_id_requested_at', 'creator_payouts', ['user_id', sa.literal_column('requested_at DESC')], unique=False)
    op.create_index('ux_creator_payouts_user_id_requested', 'creator_payouts', ['user_id'], unique=True, postgresql_where=sa.text("status = 'requested'"))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_downgradable(op.get_bind())
    op.drop_index('ux_creator_payouts_user_id_requested', table_name='creator_payouts', postgresql_where=sa.text("status = 'requested'"))
    op.drop_index('ix_creator_payouts_user_id_requested_at', table_name='creator_payouts')
    op.drop_index('ix_creator_payouts_status_requested_at', table_name='creator_payouts')
    op.drop_table('creator_payouts')
    op.drop_index('ux_creator_payout_profiles_user_id_current', table_name='creator_payout_profiles', postgresql_where=sa.text('superseded_at IS NULL'))
    op.drop_table('creator_payout_profiles')
