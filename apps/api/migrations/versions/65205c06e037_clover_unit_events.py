"""clover unit events

Revision ID: 65205c06e037
Revises: 265a8f26c44a
Create Date: 2026-10-26 15:31:37.308999

클로버 단위(한 개의 원화 값)를 바꾼 기록 `clover_unit_events` 를 빈 표로 만든다. 이 리비전은 행을 쓰지 않는다 — 전환과
되돌림을 하는 쪽이 쓴다. 표를 전환보다 먼저 만드는 이유: 이 배포부터 매 기동마다 기동 가드가 실제 표를 읽으므로, 읽기
경로(권한·이름·쿼리)가 전환 전에 운영에서 날마다 확인된다. 전환과 함께 만들면 가드가 "행 있음" 갈래를 처음 타는 순간이 급한
롤백이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 이 표는 다른 표를 참조하지 않아 떠 있는 API 의 쓰기와
잠금이 겹치지 않는다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 이 표를 모르고 읽지도 쓰지도 않는다.

**downgrade** — 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 행이 있다는 것은 단위를 바꾼 적이 있다는
뜻이고, 표를 지우면 기동 가드가 "전환한 적 없음"으로 읽어 옛 단위 코드가 새 단위 잔액 위에서 뜬다(환불이 세 배가 된다). 테스트
세션 정리(`downgrade base`)에서는 표가 비어 있어 그대로 지운다 — 이 표에 쓰는 테스트는 롤백되는 연결에서만 쓴다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65205c06e037'
down_revision: str | Sequence[str] | None = '265a8f26c44a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('clover_unit_events',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('lock_started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('money_rows', sa.Integer(), nullable=False),
    sa.Column('written_by', sa.Text(), nullable=False),
    sa.CheckConstraint("action IN ('convert', 'revert')", name='ck_clover_unit_events_action'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM clover_unit_events")).scalar_one()
    if count:
        raise RuntimeError(
            f"clover_unit_events 에 {count}행이 있다 — 클로버 단위를 바꾼 적이 있는 DB 다. 표를 지우면 기동 가드가 전환한 적이"
            " 없다고 읽어 옛 단위 코드가 새 단위 잔액 위에서 뜬다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만"
            " 되돌리되, 전환된 DB 에서는 기동 가드가 있는 이미지만 고른다(교체 스크립트가 가드 없는 이미지를 막는다)."
        )
    op.drop_table('clover_unit_events')
