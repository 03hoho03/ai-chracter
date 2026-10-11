"""chat memory episodes

Revision ID: f028a5a3b9e6
Revises: dea06f183a2c
Create Date: 2026-10-11 18:22:18.664476

장기 기억의 저장 자리를 만든다. 이 리비전은 넓히기만 한다 — 이 테이블·칸을 읽고 쓰는 코드는 아직 없다.

- `chat_memory_episodes`: 요약 접기 한 번이 접은 대화 구간에서 뽑은 장면 하나 = 한 행(제목·요약·명사·누가 말했는가·중요도,
  덮는 원문의 처음·마지막 메시지 키).
- `chat_memory_extractions`: 스냅샷 하나의 추출 기록 = 한 행(미추출 표지, 두 작업이 같은 스냅샷을 동시에 뽑지 않게 하는
  선점, 호출 원가).
- `chat_turns.memory_recall`: 그 턴 프롬프트에 실은 장면 기억 목록(JSONB, 기본값 `[]`).

두 테이블의 `snapshot_id` FK 는 `ON DELETE CASCADE` 다(방 FK 는 아니다). 편집·삭제·재생성·초기화·방 삭제·탈퇴는 바뀐 대화를
덮는 요약 스냅샷을 지우는데, 이 테이블들을 모르는 옛 이미지(배포 겹침·이미지 롤백)도 같은 DELETE 를 내므로 CASCADE 가 없으면
그 DELETE 가 FK 위반으로 500 이 된다. 새 코드도 이 두 테이블을 따로 지우지 않는다 — 추출 작업은 스냅샷을 잠근 채 추출 기록을
갱신하므로, 되감기가 추출 기록을 스냅샷보다 먼저 지우면 둘이 서로를 기다린다. 방 FK 는 방 삭제가 스냅샷부터 지우므로 방 DELETE
시점에는 자식이 남지 않는다. CHECK 는 `alembic check` 가 비교하지 않아 행위 테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. `chat_turns` 의 칸 추가(상수 기본값이라 메타데이터 변경)와 두 테이블의 FK 가
`chat_rooms`·`chat_room_memory_snapshots`·`chat_turns` 에 짧은 락을 잡는데, 떠 있는 API 가 그 테이블들을 턴마다 쓰므로
오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침** — 옛 코드는 두 테이블을 모르고 읽지도 쓰지도 않는다. 옛 코드의 `chat_turns` INSERT 는 새 칸을 몰라도
`server_default` 로 성공한다(그래서 기본값을 떼지 않는다). 옛 코드의 스냅샷 DELETE 는 위 CASCADE 로 이 행들까지 지운다.

**downgrade** — 두 테이블과 칸을 지운다. 버리는 것은 장면 기억·추출 기록·턴별 회상 목록으로 사용자에게 보이지 않는
데이터다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f028a5a3b9e6'
down_revision: str | Sequence[str] | None = 'dea06f183a2c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 요청이 FK·칸 추가의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('chat_memory_episodes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('chat_room_id', sa.Uuid(), nullable=False),
    sa.Column('snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('ordinal', sa.SmallInteger(), nullable=False),
    sa.Column('start_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('start_message_id', sa.Uuid(), nullable=False),
    sa.Column('end_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_message_id', sa.Uuid(), nullable=False),
    sa.Column('start_turn', sa.Integer(), nullable=False),
    sa.Column('end_turn', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('nouns', sa.ARRAY(sa.Text()), nullable=False),
    sa.Column('keywords', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('evidence', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('asserted_by', sa.Text(), nullable=False),
    sa.Column('importance', sa.SmallInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("asserted_by IN ('user', 'character', 'narration', 'mixed')", name='ck_chat_memory_episodes_asserted_by'),
    sa.CheckConstraint('(start_created_at, start_message_id) <= (end_created_at, end_message_id)', name='ck_chat_memory_episodes_range_order'),
    sa.CheckConstraint('cardinality(evidence) <= 2', name='ck_chat_memory_episodes_evidence_count'),
    sa.CheckConstraint('cardinality(keywords) <= 8', name='ck_chat_memory_episodes_keywords_count'),
    sa.CheckConstraint('cardinality(nouns) <= 30', name='ck_chat_memory_episodes_nouns_count'),
    sa.CheckConstraint('char_length(detail) BETWEEN 1 AND 300', name='ck_chat_memory_episodes_detail_length'),
    sa.CheckConstraint('char_length(title) BETWEEN 1 AND 60', name='ck_chat_memory_episodes_title_length'),
    sa.CheckConstraint('importance BETWEEN 1 AND 5', name='ck_chat_memory_episodes_importance'),
    sa.CheckConstraint('ordinal >= 0', name='ck_chat_memory_episodes_ordinal'),
    sa.CheckConstraint('start_turn <= end_turn', name='ck_chat_memory_episodes_turn_order'),
    sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['chat_room_memory_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('snapshot_id', 'ordinal', name='ux_chat_memory_episodes_snapshot_ordinal')
    )
    op.create_index('ix_chat_memory_episodes_room_end', 'chat_memory_episodes', ['chat_room_id', 'end_created_at', 'end_message_id'], unique=False)
    op.create_table('chat_memory_extractions',
    sa.Column('snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('chat_room_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('attempts', sa.SmallInteger(), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('model', sa.Text(), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('cached_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('thoughts_tokens', sa.Integer(), nullable=True),
    sa.Column('episode_count', sa.SmallInteger(), nullable=True),
    sa.CheckConstraint("(status = 'done') = (episode_count IS NOT NULL)", name='ck_chat_memory_extractions_done_count'),
    sa.CheckConstraint("status IN ('running', 'done', 'failed')", name='ck_chat_memory_extractions_status'),
    sa.CheckConstraint('attempts >= 1', name='ck_chat_memory_extractions_attempts'),
    sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['chat_room_memory_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('snapshot_id')
    )
    op.create_index('ix_chat_memory_extractions_room', 'chat_memory_extractions', ['chat_room_id'], unique=False)
    op.add_column('chat_turns', sa.Column('memory_recall', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_turns', 'memory_recall')
    op.drop_index('ix_chat_memory_extractions_room', table_name='chat_memory_extractions')
    op.drop_table('chat_memory_extractions')
    op.drop_index('ix_chat_memory_episodes_room_end', table_name='chat_memory_episodes')
    op.drop_table('chat_memory_episodes')
