"""chat memory embeddings

Revision ID: b3b2636b9184
Revises: 726aad108167
Create Date: 2026-10-15 23:32:36.696217

장기 기억에 임베딩의 저장 자리를 만든다. 이 리비전은 넓히기만 한다 — 이 표를 읽고 쓰는 코드는 아직 없다.

- 벡터 확장 `vector`(pgvector)를 켠다(`CREATE EXTENSION IF NOT EXISTS`). 서버 이미지에 확장이 깔려 있어야 한다 — 없으면
  이 문장이 실패하고 체인 전체가 롤백된다.
- `chat_memory_embeddings`: 장면 기억 한 행 또는 사실 기억 한 행의 임베딩 하나 = 한 행. 대상 칸 둘 중 정확히 하나를
  채우고, 모델 id·차원·차원 없는 `halfvec` 벡터를 담는다. INSERT 만 하고 고쳐 쓰지 않는다. 장면·사실 행에 칸을 두지 않는
  이유는 두 테이블의 행이 한 번 쓰면 고쳐 쓰지 않는 행이라서다 — 나중에 채우거나 모델을 바꿔 다시 채우면 UPDATE 가 생긴다.

두 대상 FK 는 `ON DELETE CASCADE` 다(방 FK 는 아니다). 편집·삭제·재생성·초기화·방 삭제·탈퇴는 요약 스냅샷을 지우고, 그
CASCADE 가 장면·사실 행을, 다시 그 CASCADE 가 이 표의 행을 지운다. 이 표를 모르는 옛 이미지도 같은 스냅샷 DELETE 를 내므로
CASCADE 가 없으면 그 DELETE 가 FK 위반으로 500 이 된다. CHECK 는 `alembic check` 가 비교하지 않아 행위 테스트가 유일한
검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 세 FK 생성이 참조하는 `chat_rooms`·`chat_memory_episodes`·`chat_memory_facts`
에 `SHARE ROW EXCLUSIVE` 를 잠깐 잡는다. 떠 있는 API 가 방 행을 턴마다 쓰고 추출 작업이 장면·사실 행을 넣으므로, 오래 걸린
트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다). 새 표는
비어 있어 FK 검증이 훑을 행이 없다.

**배포 겹침** — 옛 코드는 이 표를 모르고 읽지도 쓰지도 않는다. 옛 코드의 스냅샷 DELETE 는 위 CASCADE 로 이 행들까지 지운다.

**downgrade** — 표를 지우고, 확장은 그것에 기대는 것이 더 없을 때만 지운다(다른 표의 벡터 칸 등이 있으면 남기고 넘어간다).
버리는 것은 임베딩뿐이라 장면·사실 행에서 다시 만들 수 있다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이
스키마에서 옛 코드가 그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례) — 그래서 벡터 칸 타입을 아래에 따로 둔다.
"""

from collections.abc import Sequence
from typing import Any

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3b2636b9184'
down_revision: str | Sequence[str] | None = '726aad108167'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _HalfVec(sa.types.UserDefinedType[object]):
    """차원을 적지 않은 pgvector `halfvec` 칸. 이 리비전이 만든 DDL 만 담는다."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "halfvec"


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 요청이 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('chat_memory_embeddings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('chat_room_id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=True),
    sa.Column('fact_id', sa.Uuid(), nullable=True),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('dims', sa.SmallInteger(), nullable=False),
    sa.Column('embedding', _HalfVec(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('dims BETWEEN 1 AND 16000', name='ck_chat_memory_embeddings_dims'),
    sa.CheckConstraint('num_nonnulls(episode_id, fact_id) = 1', name='ck_chat_memory_embeddings_one_target'),
    sa.CheckConstraint('vector_dims(embedding) = dims', name='ck_chat_memory_embeddings_dims_match'),
    sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id'], ),
    sa.ForeignKeyConstraint(['episode_id'], ['chat_memory_episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['fact_id'], ['chat_memory_facts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('episode_id', 'model', 'dims', name='ux_chat_memory_embeddings_episode_model_dims'),
    sa.UniqueConstraint('fact_id', 'model', 'dims', name='ux_chat_memory_embeddings_fact_model_dims')
    )
    op.create_index('ix_chat_memory_embeddings_room_model_dims', 'chat_memory_embeddings', ['chat_room_id', 'model', 'dims'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_memory_embeddings_room_model_dims', table_name='chat_memory_embeddings')
    op.drop_table('chat_memory_embeddings')
    # 확장에 기대는 것(다른 표의 벡터 칸 등)이 남아 있으면 DROP 이 거부된다 — 그때는 확장을 남기고 넘어간다. 예외 블록이
    # 서브트랜잭션이라 거부돼도 이 체인의 트랜잭션은 그대로다.
    op.execute(
        """
        DO $$
        BEGIN
            DROP EXTENSION IF EXISTS vector;
        EXCEPTION WHEN dependent_objects_still_exist THEN
            RAISE NOTICE 'vector extension kept: other objects still depend on it';
        END
        $$
        """
    )
