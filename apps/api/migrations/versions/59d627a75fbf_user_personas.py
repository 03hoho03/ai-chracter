"""user personas

Revision ID: 59d627a75fbf
Revises: cf74d6d53561
Create Date: 2026-09-24 16:56:33.562610

대화 프로필 스키마. 컬럼·인덱스 근거는
`db/models/persona.py`의 `UserPersona` docstring과 `User.default_persona_id`·
`ChatRoom.persona_id` 주석에 있다 — 여기서 되풀이하지 않는다.

**순환 FK**(`users.default_persona_id` → `user_personas.id`, `user_personas.user_id` →
`users.id`): `op.create_table`은 `use_alter`를 무시하므로 테이블을 만든 뒤
`op.create_foreign_key`로 따로 건다(apps/api/CLAUDE.md §마이그레이션, `aceda536013c` 선례).
downgrade는 FK 두 개를 먼저 `drop_constraint(type_='foreignkey')`로 끊고 컬럼·인덱스·테이블을
역순으로 지운다.

FK에 `ondelete`를 주지 않는다(저장소 규약) — 참조를 끊는 순서는 호출부가 지킨다.

프롬프트 슬롯 데이터(`generation/user_persona`)는 다음 리비전(`b72c33c70240`)이 넣는다 — 스키마와
데이터를 나눠 두면 그 리비전의 가정 검증이 실패했을 때 원인이 어느 쪽인지 분명하다. 체인이 한
트랜잭션이라(`migrations/env.py`) 그 리비전이 raise하면 이 리비전도 함께 롤백된다.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '59d627a75fbf'
down_revision: str | Sequence[str] | None = 'cf74d6d53561'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_personas',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('gender', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_personas_user_id', 'user_personas', ['user_id'], unique=False)

    # 순환 FK — 테이블 생성 뒤 따로 건다(위 docstring).
    op.add_column('users', sa.Column('default_persona_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_users_default_persona_id', 'users', 'user_personas', ['default_persona_id'], ['id']
    )

    op.add_column('chat_rooms', sa.Column('persona_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_chat_rooms_persona_id', 'chat_rooms', 'user_personas', ['persona_id'], ['id'])
    op.create_index('ix_chat_rooms_persona_id', 'chat_rooms', ['persona_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_chat_rooms_persona_id', 'chat_rooms', type_='foreignkey')
    op.drop_constraint('fk_users_default_persona_id', 'users', type_='foreignkey')
    op.drop_index('ix_chat_rooms_persona_id', table_name='chat_rooms')
    op.drop_column('chat_rooms', 'persona_id')
    op.drop_column('users', 'default_persona_id')
    op.drop_index('ix_user_personas_user_id', table_name='user_personas')
    op.drop_table('user_personas')
