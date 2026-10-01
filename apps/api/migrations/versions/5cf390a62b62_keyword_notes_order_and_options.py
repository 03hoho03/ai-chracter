"""keyword notes order and options

Revision ID: 5cf390a62b62
Revises: 0ffeb45ff1f4
Create Date: 2026-10-02 03:08:17.134158

키워드북 노트에 순서(`order`)·목록용 이름·금지 키워드·유지 턴·상시 적용 컬럼을 더한다. 다섯 컬럼 모두
NOT NULL + `server_default` 다 — 형제 테이블의 `order` 와 달리 기본값을 두는 이유는 API 를 이 컬럼을 모르는
이전 이미지로 되돌렸을 때 그 코드의 노트 INSERT 가 NOT NULL 위반으로 500 이 나지 않게 하기 위해서다.

기존 노트의 `order` 는 지금 빌더가 보여 주는 순서로 채운다. 빌더 GET 의 노트 조회는 ORDER BY 가 없고, 조회
조건인 `content_version_id` 에 인덱스가 없어(인덱스는 기본 키 `id` 에만 있다) 그 조회가 정렬 노드 없는 Seq Scan 으로 실행된다 — 반환 순서가 곧 힙(`ctid`) 순서다.
그래서 버전마다 `ctid` 순으로 0 부터 번호를 매긴다. 이 약속은 "마이그레이션 직전 GET 이 돌려줄 순서를 굳힌다"
까지다. 자동저장 UPDATE 가 행을 힙의 다른 자리로 옮기므로 작가가 기억하는 순서와는 원래부터 다를 수 있다.
테이블이 병렬 스캔 문턱(`min_parallel_table_scan_size`)이나 동기 스캔 문턱(`shared_buffers` 의 1/4)을 넘을 만큼
크면 Seq Scan 의 반환 순서가 힙 순서와 달라질 수 있으니, 적용 전에 테이블 크기를 확인한다.

downgrade 는 다섯 컬럼을 지운다 — 작가가 정한 순서·이름·금지 키워드·유지 턴·상시 설정이 사라지고 되살릴 수 없다.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5cf390a62b62'
down_revision: str | Sequence[str] | None = '0ffeb45ff1f4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 버전마다 힙 순서(`ctid`)로 0..n-1 을 매긴다. 테스트가 이 문장을 그대로 실행해 순서를 단언한다.
BACKFILL_ORDER_SQL = """
UPDATE keyword_notes k
SET "order" = s.rn - 1
FROM (
    SELECT id, row_number() OVER (PARTITION BY content_version_id ORDER BY ctid) AS rn
    FROM keyword_notes
) s
WHERE k.id = s.id
"""


def upgrade() -> None:
    """Upgrade schema."""
    # 순서 backfill 을 다른 컬럼 추가보다 먼저 한다 — 힙 순서를 읽는 것이니 그 전에 테이블을 건드리지 않는다.
    op.add_column('keyword_notes', sa.Column('order', sa.Integer(), nullable=True))
    op.execute(BACKFILL_ORDER_SQL)
    op.alter_column('keyword_notes', 'order', server_default=sa.text('0'), nullable=False)
    op.add_column('keyword_notes', sa.Column('name', sa.Text(), server_default='', nullable=False))
    op.add_column('keyword_notes', sa.Column('exclude_keywords', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False))
    op.add_column('keyword_notes', sa.Column('sticky_turns', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('keyword_notes', sa.Column('always_on', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('keyword_notes', 'always_on')
    op.drop_column('keyword_notes', 'sticky_turns')
    op.drop_column('keyword_notes', 'exclude_keywords')
    op.drop_column('keyword_notes', 'order')
    op.drop_column('keyword_notes', 'name')
