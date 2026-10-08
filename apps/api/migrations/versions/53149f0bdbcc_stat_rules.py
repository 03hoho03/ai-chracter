"""stat rules

Revision ID: 53149f0bdbcc
Revises: a7a87e3ba631
Create Date: 2026-10-08 17:36:38.094539

스탯마다 작가가 쓰는 「조건 → ±n」 규칙 목록(`stat_rules`)을 더한다. 판정 LLM 이 절대값을 내는 대신 발동한 규칙만
고르고 코드가 폭을 더하게 하려는 것이다. 이 리비전은 테이블만 만든다 — 기존 스탯에는 규칙이 없고, 규칙이 없는 스탯은
그대로 현행 판정으로 돈다.

**옛 이미지가 이 스키마 위에서 도는 구간** — 옛 코드는 이 테이블을 모르므로 읽지도 쓰지도 않는다. 다만 옛 코드도
스탯을 지운다(저장에서 스탯 제거, 시작설정 제거, 초안 삭제, 편집 취소). 그래서 `stat_def_id` FK 에 `ON DELETE CASCADE`
를 건다 — 이 저장소의 "cascade 없음" 관례의 예외다. cascade 가 없으면 규칙이 달린 스탯을 옛 코드가 지우는 순간 FK
위반으로 500 이 난다(배포 중 겹치는 수십 초, 그리고 이미지만 되돌린 뒤 내내). 새 코드는 cascade 와 상관없이 규칙을
먼저 지우고 스탯을 지운다.

CHECK 제약은 두지 않는다. 개수·조건 글자 수·폭 0 은 저장 요청 검증이 422 로 막고, 폭이 스탯 범위를 넘는지는 발행 검증이
막는다 — 폭 범위는 스탯 행의 최소·최대를 봐야 해 이 테이블의 CHECK 로 쓸 수 없고, 개수·글자 수 상한은 바뀔 수 있는 제품
값이라 요청 검증 한 곳에만 둔다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. FK 를 만들 때 참조되는 `stat_defs` 에 SHARE ROW EXCLUSIVE 락을 잡고 체인이
커밋될 때까지 쥔다. 읽기와는 부딪히지 않지만 쓰기(빌더 자동저장·발행 복제의 스탯 INSERT·UPDATE·DELETE)와는 부딪혀,
오래 걸린 쓰기 트랜잭션 뒤에서 락을 기다리는 동안 그 뒤의 스탯 쓰기가 모두 줄을 선다. 5초 안에 못 잡으면 마이그레이션을
실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**downgrade** 는 테이블을 지운다. 작가가 쓴 규칙은 사라진다.

**이미지만 되돌릴 때** — 이 리비전 이전 이미지로 되돌린 상태에서의 발행·편집 취소는 초안 쪽 규칙을 복제하지 않아(옛 코드는
이 테이블을 모른다) 그 작품의 규칙을 잃는다. 빌더가 규칙을 쓰기 시작한 뒤에는 이 리비전 이전 이미지로 되돌리지 않는다.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53149f0bdbcc'
down_revision: str | Sequence[str] | None = 'a7a87e3ba631'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 스탯 쓰기가 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('stat_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('entity_id', sa.Uuid(), nullable=False),
    sa.Column('stat_def_id', sa.Uuid(), nullable=False),
    sa.Column('condition', sa.Text(), nullable=False),
    sa.Column('delta', sa.Integer(), nullable=False),
    sa.Column('order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['stat_def_id'], ['stat_defs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_stat_rules_stat_def_id', 'stat_rules', ['stat_def_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_stat_rules_stat_def_id', table_name='stat_rules')
    op.drop_table('stat_rules')
