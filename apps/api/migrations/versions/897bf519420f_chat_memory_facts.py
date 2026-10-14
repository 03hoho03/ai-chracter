"""chat memory facts

Revision ID: 897bf519420f
Revises: fc6f0e134782
Create Date: 2026-10-14 16:57:59.057207

장기 기억에 사실 계층의 저장 자리를 만든다. 이 리비전은 넓히기만 한다 — 이 테이블·칸을 읽고 쓰는 코드는 아직 없다.

- `chat_memory_facts`: 요약 접기 한 번이 접은 대화 구간에서 뽑은 사실 하나 = 한 행(관계 또는 속성, 서버가 정규화한 키,
  확인·주장·반박 상태, 누가 말했는가, 아는 인물, 중요도, 근거 원문의 처음·마지막 메시지 키). 고쳐 쓰지 않고 쌓기만 한다.
- `chat_memory_fact_extractions`: 스냅샷 하나의 사실 추출 기록 = 한 행. 장면 추출 기록 `chat_memory_extractions` 와 같은
  모양이다(미추출 표지, 선점, 호출 원가).
- `chat_turns.memory_facts`: 그 턴 프롬프트에 실은 사실 기억 목록(JSONB, 기본값 `[]`).

두 테이블의 `snapshot_id` FK 는 `ON DELETE CASCADE` 다(방 FK 는 아니다). 장면 기억 테이블과 같은 이유다 — 편집·삭제·재생성·
초기화·방 삭제·탈퇴는 바뀐 대화를 덮는 요약 스냅샷을 지우는데, 이 테이블들을 모르는 옛 이미지도 같은 DELETE 를 내므로 CASCADE
가 없으면 그 DELETE 가 FK 위반으로 500 이 된다. 새 코드도 이 두 테이블을 따로 지우지 않는다 — 추출 작업은 스냅샷을 잠근 채
추출 기록을 갱신하므로, 되감기가 추출 기록을 스냅샷보다 먼저 지우면 둘이 서로를 기다린다. CHECK 는 `alembic check` 가 비교하지
않아 행위 테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. `chat_turns` 의 칸 추가는 상수 기본값이라 메타데이터 변경이지만
`ACCESS EXCLUSIVE` 를 잠깐 잡고, 두 테이블의 FK 생성은 참조하는 `chat_rooms`·`chat_room_memory_snapshots` 에
`SHARE ROW EXCLUSIVE` 를 잠깐 잡는다. 떠 있는 API 가 그 테이블들을 턴마다 쓰므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의
요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침** — 옛 코드는 두 테이블을 모르고 읽지도 쓰지도 않는다. 옛 코드의 `chat_turns` INSERT 는 새 칸을 몰라도
`server_default` 로 성공한다(그래서 기본값을 떼지 않는다). 옛 코드의 스냅샷 DELETE 는 위 CASCADE 로 이 행들까지 지운다.

**downgrade** — 두 테이블과 칸을 지운다. 버리는 것은 사실 기억·추출 기록·턴별 사실 목록으로 사용자에게 보이지 않는
데이터다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '897bf519420f'
down_revision: str | Sequence[str] | None = 'fc6f0e134782'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 요청이 FK·칸 추가의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('chat_memory_fact_extractions',
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
    sa.Column('fact_count', sa.SmallInteger(), nullable=True),
    sa.CheckConstraint("(status = 'done') = (fact_count IS NOT NULL)", name='ck_chat_memory_fact_extractions_done_count'),
    sa.CheckConstraint("status IN ('running', 'done', 'failed')", name='ck_chat_memory_fact_extractions_status'),
    sa.CheckConstraint('attempts >= 1', name='ck_chat_memory_fact_extractions_attempts'),
    sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['chat_room_memory_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('snapshot_id')
    )
    op.create_index('ix_chat_memory_fact_extractions_room', 'chat_memory_fact_extractions', ['chat_room_id'], unique=False)
    op.create_table('chat_memory_facts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('chat_room_id', sa.Uuid(), nullable=False),
    sa.Column('snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('ordinal', sa.SmallInteger(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('subject', sa.Text(), nullable=False),
    sa.Column('object', sa.Text(), nullable=True),
    sa.Column('attribute', sa.Text(), nullable=True),
    sa.Column('fact_key', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('truth_status', sa.Text(), nullable=False),
    sa.Column('asserted_by', sa.Text(), nullable=False),
    sa.Column('speaker', sa.Text(), nullable=True),
    sa.Column('known_by', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('importance', sa.SmallInteger(), nullable=False),
    sa.Column('start_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('start_message_id', sa.Uuid(), nullable=False),
    sa.Column('end_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_message_id', sa.Uuid(), nullable=False),
    sa.Column('start_turn', sa.Integer(), nullable=False),
    sa.Column('end_turn', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'relation' AND object IS NOT NULL AND attribute IS NULL) OR (kind = 'fact' AND object IS NULL AND attribute IS NOT NULL)", name='ck_chat_memory_facts_kind_columns'),
    sa.CheckConstraint("array_position(known_by, NULL) IS NULL AND array_to_string(known_by, E'\\x1F') !~ '[^\\x1F]{61}'", name='ck_chat_memory_facts_known_by_items'),
    sa.CheckConstraint("asserted_by IN ('user', 'character', 'narration')", name='ck_chat_memory_facts_asserted_by'),
    sa.CheckConstraint("kind IN ('relation', 'fact')", name='ck_chat_memory_facts_kind'),
    sa.CheckConstraint("truth_status IN ('confirmed', 'claimed', 'disproved')", name='ck_chat_memory_facts_truth_status'),
    sa.CheckConstraint('(start_created_at, start_message_id) <= (end_created_at, end_message_id)', name='ck_chat_memory_facts_range_order'),
    sa.CheckConstraint('cardinality(known_by) BETWEEN 1 AND 10', name='ck_chat_memory_facts_known_by_count'),
    sa.CheckConstraint('char_length(attribute) BETWEEN 1 AND 60', name='ck_chat_memory_facts_attribute_length'),
    sa.CheckConstraint('char_length(fact_key) BETWEEN 1 AND 200', name='ck_chat_memory_facts_fact_key_length'),
    sa.CheckConstraint('char_length(object) BETWEEN 1 AND 60', name='ck_chat_memory_facts_object_length'),
    sa.CheckConstraint('char_length(speaker) BETWEEN 1 AND 60', name='ck_chat_memory_facts_speaker_length'),
    sa.CheckConstraint('char_length(subject) BETWEEN 1 AND 60', name='ck_chat_memory_facts_subject_length'),
    sa.CheckConstraint('char_length(value) BETWEEN 1 AND 200', name='ck_chat_memory_facts_value_length'),
    sa.CheckConstraint('importance BETWEEN 1 AND 5', name='ck_chat_memory_facts_importance'),
    sa.CheckConstraint('ordinal >= 0 AND ordinal < 20', name='ck_chat_memory_facts_ordinal'),
    sa.CheckConstraint('start_turn <= end_turn', name='ck_chat_memory_facts_turn_order'),
    sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['chat_room_memory_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('snapshot_id', 'ordinal', name='ux_chat_memory_facts_snapshot_ordinal')
    )
    op.create_index('ix_chat_memory_facts_room_end', 'chat_memory_facts', ['chat_room_id', 'end_created_at', 'end_message_id'], unique=False)
    op.add_column('chat_turns', sa.Column('memory_facts', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_turns', 'memory_facts')
    op.drop_index('ix_chat_memory_facts_room_end', table_name='chat_memory_facts')
    op.drop_table('chat_memory_facts')
    op.drop_index('ix_chat_memory_fact_extractions_room', table_name='chat_memory_fact_extractions')
    op.drop_table('chat_memory_fact_extractions')
