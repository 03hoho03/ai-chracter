"""content fks set null for draft deletion

Revision ID: bc062c967f3c
Revises: 6016f9d01da2
Create Date: 2026-09-28 00:47:04.976565

관리자 조치는 초안에도 걸린다(관리자 작품 목록이 초안만 있는 작품도 나열하고 조치는 발행 여부를
보지 않는다). 그 초안을 소유자가 지우면 조치가 남긴 세 행 — `moderation_actions.content_id`,
`admin_action_logs.target_content_id`, 소유자 알림의 `notifications.content_id` — 의 FK가
`contents` 행 DELETE를 막아 500이 됐다. 셋 다 기록이라 지우지 않고 사라진 작품을 가리키던 칸만
비운다(`ON DELETE SET NULL`). 그러려면 `moderation_actions.content_id`가 NULL을 받아야 해서
nullable로 바꾼다. 세 테이블에 CHECK 제약은 없다.

제약 이름은 Postgres가 최초 생성 때 붙인 기본 이름을 그대로 쓴다 — autogenerate가 새 FK 이름을
`None`으로 내서, 그대로 두면 downgrade의 `drop_constraint(None, ...)`가 실패한다.

downgrade는 `moderation_actions.content_id`를 NOT NULL로 되돌리므로, 작품이 삭제돼 NULL이 된
조치 행이 하나라도 있으면 실패한다. 조치 기록을 조용히 지우지 않으려고 일부러 그대로 둔다.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'bc062c967f3c'
down_revision: str | Sequence[str] | None = '6016f9d01da2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (테이블, 컬럼, 제약 이름)
_FKS = (
    ('moderation_actions', 'content_id', 'moderation_actions_content_id_fkey'),
    ('admin_action_logs', 'target_content_id', 'admin_action_logs_target_content_id_fkey'),
    ('notifications', 'content_id', 'notifications_content_id_fkey'),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('moderation_actions', 'content_id', existing_type=sa.UUID(), nullable=True)
    for table, column, name in _FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, 'contents', [column], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, name in _FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, 'contents', [column], ['id'])
    op.alter_column('moderation_actions', 'content_id', existing_type=sa.UUID(), nullable=False)
