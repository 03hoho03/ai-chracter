"""llm credentials

Revision ID: 7eb6d96b147f
Revises: 45e57ce4d815
Create Date: 2026-11-04 16:20:18.821496

Claude 자격 목록 표 셋을 만든다 — 자격(`llm_credentials`), 확인 기록(`llm_credential_checks`), 목록 사용 칸과 목록 판
번호를 담는 한 행 표(`llm_credential_settings`, 이 리비전이 그 행을 심는다). 키 원문은 `LLM_CREDENTIAL_ENCRYPTION_KEYS` 의
키로 AES-256-GCM 암호화한 바이트만 남고, 연관 데이터가 행 id 와 칸 이름이라 행 id 는 INSERT 전에 코드가 정한다.

**배포 겹침** — 새 표만 더한다. 옛 코드는 이 표들을 모르고 읽지도 쓰지도 않는다.

CHECK 는 `alembic check` 가 비교하지 않는다 — 행위 테스트가 유일한 검증이다.

**downgrade 는 세 표를 지운다. 저장한 자격의 암호문이 함께 사라져, 다시 올린 뒤에는 어드민에서 키를 다시 붙여넣어야
한다**(원문을 다른 곳에 두지 않았다면 콘솔에서 새 키를 발급해 넣는다). 런타임이 이 목록을 읽는 판이 배포된 뒤라면 downgrade
전에 어드민에서 목록 사용을 먼저 끈다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7eb6d96b147f'
down_revision: str | Sequence[str] | None = '45e57ce4d815'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('llm_credential_settings',
    sa.Column('id', sa.SmallInteger(), server_default='1', autoincrement=False, nullable=False),
    sa.Column('pool_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('list_revision', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('id = 1', name='ck_llm_credential_settings_singleton'),
    sa.CheckConstraint('list_revision >= 0', name='ck_llm_credential_settings_list_revision'),
    sa.PrimaryKeyConstraint('id')
    )
    # 목록 사용 칸과 판 번호는 이 한 행에만 있다 — 꺼짐·판 0 으로 시작한다.
    op.execute("INSERT INTO llm_credential_settings (id) VALUES (1)")
    op.create_table('llm_credentials',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('state_reason', sa.Text(), nullable=True),
    sa.Column('state_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('state_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('account_ref', sa.Text(), nullable=True),
    sa.Column('key_id', sa.Text(), nullable=False),
    sa.Column('secret_ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('secret_last4', sa.Text(), nullable=False),
    sa.Column('secret_fingerprint', sa.Text(), nullable=False),
    sa.Column('region', sa.Text(), nullable=True),
    sa.Column('credit_micro_usd', sa.BigInteger(), nullable=True),
    sa.Column('credit_since', sa.DateTime(timezone=True), nullable=True),
    sa.Column('alert_pct', sa.SmallInteger(), server_default='20', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(provider = 'bedrock') = (region IS NOT NULL)", name='ck_llm_credentials_region'),
    sa.CheckConstraint("(state = 'active' AND state_reason IS NULL) OR (state = 'exhausted' AND state_reason IN ('credit', 'auth', 'limit')) OR (state = 'disabled' AND state_reason = 'admin')", name='ck_llm_credentials_state_reason'),
    sa.CheckConstraint("account_ref IS NULL OR account_ref <> ''", name='ck_llm_credentials_account_ref'),
    sa.CheckConstraint("key_id <> ''", name='ck_llm_credentials_key_id'),
    sa.CheckConstraint("label <> ''", name='ck_llm_credentials_label'),
    sa.CheckConstraint("provider IN ('anthropic', 'bedrock')", name='ck_llm_credentials_provider'),
    sa.CheckConstraint("secret_fingerprint ~ '^[0-9a-f]{8}$'", name='ck_llm_credentials_secret_fingerprint'),
    sa.CheckConstraint("state IN ('active', 'exhausted', 'disabled')", name='ck_llm_credentials_state'),
    sa.CheckConstraint('(credit_micro_usd IS NULL) = (credit_since IS NULL)', name='ck_llm_credentials_credit_since'),
    sa.CheckConstraint('alert_pct BETWEEN 1 AND 99', name='ck_llm_credentials_alert_pct'),
    sa.CheckConstraint('char_length(secret_last4) = 4', name='ck_llm_credentials_secret_last4'),
    sa.CheckConstraint('credit_micro_usd IS NULL OR credit_micro_usd > 0', name='ck_llm_credentials_credit'),
    sa.CheckConstraint('position > 0', name='ck_llm_credentials_position'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_llm_credentials_position', 'llm_credentials', ['position'], unique=True)
    op.create_index('ix_llm_credentials_provider_account_ref', 'llm_credentials', ['provider', 'account_ref'], unique=True)
    op.create_table('llm_credential_checks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('credential_id', sa.Uuid(), nullable=False),
    sa.Column('run', sa.Integer(), nullable=False),
    sa.Column('state_version', sa.Integer(), nullable=False),
    sa.Column('model_axis', sa.Text(), nullable=False),
    sa.Column('sent_model_id', sa.Text(), nullable=False),
    sa.Column('secret_fingerprint', sa.Text(), nullable=False),
    sa.Column('passed', sa.Boolean(), nullable=False),
    sa.Column('error_kind', sa.Text(), nullable=True),
    sa.Column('organization_header', sa.Text(), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.CheckConstraint("secret_fingerprint ~ '^[0-9a-f]{8}$'", name='ck_llm_credential_checks_secret_fingerprint'),
    sa.CheckConstraint("sent_model_id <> ''", name='ck_llm_credential_checks_sent_model_id'),
    sa.CheckConstraint('passed = (error_kind IS NULL)', name='ck_llm_credential_checks_outcome'),
    sa.CheckConstraint('run > 0', name='ck_llm_credential_checks_run'),
    sa.ForeignKeyConstraint(['credential_id'], ['llm_credentials.id'], name='fk_llm_credential_checks_credential_id', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_llm_credential_checks_run_axis', 'llm_credential_checks', ['credential_id', 'run', 'model_axis'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_llm_credential_checks_run_axis', table_name='llm_credential_checks')
    op.drop_table('llm_credential_checks')
    op.drop_index('ix_llm_credentials_provider_account_ref', table_name='llm_credentials')
    op.drop_index('ix_llm_credentials_position', table_name='llm_credentials')
    op.drop_table('llm_credentials')
    op.drop_table('llm_credential_settings')
