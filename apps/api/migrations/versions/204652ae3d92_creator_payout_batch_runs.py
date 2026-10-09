"""creator payout batch runs

Revision ID: 204652ae3d92
Revises: 9b1c1ed8faad
Create Date: 2026-10-09 18:30:16.668662

크리에이터 정산 월 확정 배치의 달별 실행 기록 `creator_payout_batch_runs` 를 만든다. 행이 있는 달은 배치가 다시 확정하지
않고, 그 달의 감시 수(사용처 없는 채팅·소설 차감 수, 환급 합과 환급 행 합이 다른 유료 배분 수)가 여기 남는다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 이 테이블은 다른 테이블을 참조하지 않아 떠 있는 API
의 쓰기와 잠금이 겹치지 않는다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 이 테이블을 모르고 쓰지도 않는다.

**downgrade** — 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 이 행이 사라지면 배치가 끝난 달을
다시 확정하려 들고, 그때 결제 취소 조정만 있는 크리에이터는 지난달에 없던 확정 행을 새로 받는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '204652ae3d92'
down_revision: str | Sequence[str] | None = '9b1c1ed8faad'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('creator_payout_batch_runs',
    sa.Column('period_month', sa.Date(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('creator_count', sa.Integer(), nullable=False),
    sa.Column('total_amount_krw', sa.BigInteger(), nullable=False),
    sa.Column('unattributed_spend_count', sa.Integer(), nullable=False),
    sa.Column('refund_event_mismatch_count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('period_month')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM creator_payout_batch_runs")).scalar_one()
    if count:
        raise RuntimeError(
            f"creator_payout_batch_runs 에 {count}행이 있다 — 지우면 배치가 끝난 달을 다시 확정하려 든다. 옛 코드로"
            " 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
        )
    op.drop_table('creator_payout_batch_runs')
