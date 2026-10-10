"""chat turns

Revision ID: 42ba15156c84
Revises: 46bda819407c
Create Date: 2026-10-10 14:49:57.080876

턴 기록 테이블 `chat_turns` 를 만든다. 턴이 남긴 응답 하나가 한 행이고, 생성 모델·차감·LLM 호출별 토큰·그 응답에 귀속된
스탯 변화·도달한 엔딩을 숫자와 id 로만 담는다. 이 리비전과 함께 들어가는 코드는 방 삭제·탈퇴·초기화에서 그 방의 행을
지우기만 하고, 아직 아무도 행을 쓰지 않는다.

- 방에는 FK 를 걸고, `assistant_message_id`(유니크)·`spend_ledger_id` 에는 걸지 않는다 — 메시지는 재생성·편집·메시지
  삭제·초기화가 실제로 지우고, 원장 행에는 턴 쓰기가 FK 확인 잠금을 걸지 않게 한다.
- CHECK 둘(`kind`·`charge_source` 값 범위)은 alembic 1.18.5 의 `alembic check` 가 비교하지 않는다 — 행위 테스트가 유일한
  검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 새 테이블이 `chat_rooms` 에 FK 를 걸 때 그 테이블에 짧은
`SHARE ROW EXCLUSIVE` 가 잡히는데, 떠 있는 API 가 `chat_rooms` 를 턴마다 쓰므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의
쓰기를 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 이 테이블을 모르지만 행이 하나도 없으므로 옛 코드의 방
DELETE 가 FK 에 걸리지 않는다. 반대로 행이 생긴 뒤에는 이 리비전 이전 이미지로 되돌리면 그 코드가 방 삭제·탈퇴에서 이
행을 지우지 않아 FK 위반이 난다 — 이미지를 되돌리기 전에 이 테이블을 비운다.

**downgrade** — 테이블을 지운다. 기록은 정산 근거가 아니라 잃어도 된다. 다만 이 리비전의 코드가 떠 있는 동안 downgrade 하면
그 코드의 방 삭제·탈퇴·초기화가 없는 테이블에 DELETE 해 실패하므로, 이미지를 이전 태그로 먼저 되돌린 뒤 이 리비전의
이미지를 일회성 컨테이너로 띄워 downgrade 한다(`DEPLOY.md` 「3-2. DB 마이그레이션」).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '42ba15156c84'
down_revision: str | Sequence[str] | None = '46bda819407c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 방 쓰기가 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        'chat_turns',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('chat_room_id', sa.Uuid(), nullable=False),
        sa.Column('assistant_message_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('turn_number', sa.Integer(), nullable=False),
        sa.Column('chat_model', sa.Text(), nullable=False),
        sa.Column('charge_source', sa.Text(), nullable=False),
        sa.Column('clover_amount', sa.Integer(), nullable=False),
        sa.Column('spend_ledger_id', sa.Uuid(), nullable=True),
        sa.Column('shortcut_entity_id', sa.Uuid(), nullable=True),
        sa.Column(
            'llm_calls',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'stat_changes',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('ending_entity_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("charge_source IN ('free', 'clover', 'skipped')", name='ck_chat_turns_charge_source'),
        sa.CheckConstraint("kind IN ('send', 'edit', 'regenerate')", name='ck_chat_turns_kind'),
        sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('assistant_message_id', name='ux_chat_turns_assistant_message_id'),
    )
    op.create_index(
        'ix_chat_turns_chat_room_id_turn_number', 'chat_turns', ['chat_room_id', 'turn_number'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index('ix_chat_turns_chat_room_id_turn_number', table_name='chat_turns')
    op.drop_table('chat_turns')
