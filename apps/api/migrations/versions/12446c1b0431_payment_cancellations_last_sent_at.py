"""payment cancellations last_sent_at

Revision ID: 12446c1b0431
Revises: bc4dd4fad61c
Create Date: 2026-10-08 21:53:33.952541

어드민 환불 시도 행에 `last_sent_at`(포트원에 취소를 마지막으로 보내기 시작한 시각)을 더한다. 결제 행 잠금 아래에서 이
칸을 적고 읽어, 첫 전송이 아직 포트원 응답을 기다리는 동안 두 번째 클릭·다른 어드민의 재시도가 같은 취소를 다시 보내지
않게 한다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. NULL 칸 추가는 메타데이터만 바꾼다.

**배포 겹침** — 옛 코드는 이 칸을 모르고 쓰지 않는다(NULL 로 남는다). 새 코드는 NULL 을 "보낸 적 없음"이 아니라 "지금
보내는 중이 아님"으로 읽으므로 옛 코드가 만든 행도 재시도로 이어진다. 결제를 켜기 전에는 행이 없다.

**downgrade** — 칸을 지운다. 이 칸은 진행 중 전송의 잠깐짜리 표시라 잃어도 결제·환불 기록은 그대로다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "12446c1b0431"
down_revision: str | Sequence[str] | None = "bc4dd4fad61c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("payment_cancellations", sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("payment_cancellations", "last_sent_at")
