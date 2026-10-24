"""chat memory impressions

Revision ID: 8b045061cad4
Revises: 18d0cb76b3ca
Create Date: 2026-10-24 18:26:28.476206

장기 기억에 인상(요약 접기 몇 번마다 방 하나에 쌓는, 인물 사이 감정·태도의 흐름을 적은 짧은 글)의 저장 자리를 만든다. 이
리비전은 넓히기만 한다 — 이 테이블을 읽고 쓰는 코드는 이 리비전과 함께 들어가지 않는다.

- `chat_memory_impressions`: 인상 하나 = 한 행. 덮는 스냅샷 묶음에서 커서가 가장 큰 스냅샷(FK, 스냅샷마다 한 행), 묶음의 첫
  커서, 글, 입력에 실은 장면·사실 행 id 의 JSON 배열 둘. 고쳐 쓰지 않고 쌓기만 한다.

`snapshot_id` FK 는 `ON DELETE CASCADE` 다(방 FK 는 아니다). 장면·사실 기억 테이블과 같은 이유다 — 편집·삭제·재생성·초기화·
방 삭제·탈퇴는 바뀐 대화를 덮는 요약 스냅샷을 지우는데, 이 테이블을 모르는 옛 이미지도 같은 DELETE 를 내므로 CASCADE 가 없으면
그 DELETE 가 FK 위반으로 500 이 된다. CHECK 는 `alembic check` 가 비교하지 않아 행위 테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 새 테이블의 FK 생성은 참조하는 `chat_rooms`·`chat_room_memory_snapshots` 에
`SHARE ROW EXCLUSIVE` 를 잠깐 잡는다. 떠 있는 API 가 그 테이블들을 턴마다 쓰므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 요청을
줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침** — 옛 코드는 이 테이블을 모르고 읽지도 쓰지도 않는다. 옛 코드의 스냅샷 DELETE 는 위 CASCADE 로 이 행까지 지운다.

**downgrade** — 테이블을 지운다. 버리는 것은 인상 행으로, 생성에 쓰이지 않고 사용자에게 보이지 않는 파생 데이터다. 옛 코드로
돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8b045061cad4'
down_revision: str | Sequence[str] | None = '18d0cb76b3ca'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 요청이 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('chat_memory_impressions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('chat_room_id', sa.Uuid(), nullable=False),
    sa.Column('snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('first_cursor_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('first_cursor_message_id', sa.Uuid(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('episode_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fact_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(episode_ids) = 'array'", name='ck_chat_memory_impressions_episode_ids_array'),
    sa.CheckConstraint("jsonb_typeof(fact_ids) = 'array'", name='ck_chat_memory_impressions_fact_ids_array'),
    sa.CheckConstraint('char_length(text) BETWEEN 1 AND 600', name='ck_chat_memory_impressions_text_length'),
    sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['chat_room_memory_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('snapshot_id', name='ux_chat_memory_impressions_snapshot')
    )
    op.create_index('ix_chat_memory_impressions_room', 'chat_memory_impressions', ['chat_room_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_memory_impressions_room', table_name='chat_memory_impressions')
    op.drop_table('chat_memory_impressions')
