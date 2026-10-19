"""novel free ordinals

Revision ID: 2975c3a6fa6f
Revises: 3b4b814583dc
Create Date: 2026-10-19 18:57:05.410365

소설마다 무료로 독자에게 내놓은 적이 있는 화 번호를 남기는 표(`novel_free_ordinals`)를 만든다. 화를 지우면 화 공개본과 그
가격 칸이 함께 사라지고 다시 만든 화는 새 화라, 지금까지는 무료로 공개했던 번호를 다시 만들어 유료로 낼 수 있었다. 이제 한 번
무료로 준 번호는 다시 만들어도 무료로 공개한다(정책 스위치가 켜져 있을 때 지킨다).

**표**: `(novel_id, ordinal)` 복합 PK, `recorded_at`, CHECK `ordinal >= 1`. `novel_id` 는 소설 FK `ON DELETE CASCADE` — 이 표를
모르는 옛 코드의 소설 삭제·숨긴 소설 파기가 FK 위반 없이 함께 지운다. 앞 무료 화 수(5)를 CHECK 에 넣지 않는다 — 상수를 바꿀
때마다 마이그레이션이 필요해진다.

**백필**: 지금 무료인 6화 이후 화 공개본의 번호를 남긴다(`BACKFILL_FREE_ORDINALS_SQL`). 6화 이후 무료는 정책 스위치가 켜졌을
때만 생기므로 스위치가 꺼진 운영에서는 0행이다. `ON CONFLICT DO NOTHING` 이라 다시 돌려도 이미 있는 행은 그대로다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 이 표를 읽지도 쓰지도 않는다. 스위치가 꺼져 있으면 옛 코드도 6화 이후를
무료로 공개하거나 무료로 바꾸지 못하므로 겹침 동안 빠지는 기록이 없다. 스위치가 켜진 채 배포하면 겹침 동안 옛 이미지가 무료로
만든 번호가 빠지는데, 옛 이미지가 다 내려간 뒤 같은 백필을 한 번 더 돌리면 채워진다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 소설 FK 를 거는 동안 떠 있는 API 가 늘 읽고 쓰는 소설 표를 잠그므로, 오래 걸린
트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 잠금을 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**downgrade**: 표를 지운다. 기억한 번호를 잃어, 그 번호의 화를 지우고 다시 만들면 유료로 낼 수 있게 된다. 행이 있어도 멈추는
가드는 두지 않는다(테스트 스위트 끝의 `alembic downgrade base` 가 테스트가 커밋한 행 때문에 깨진다). 옛 코드로 돌아가기만
하려면 downgrade 없이 이미지만 되돌린다 — 옛 코드는 이 표를 모른 채 그대로 돈다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2975c3a6fa6f"
down_revision: str | Sequence[str] | None = "3b4b814583dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# 앞 무료 화 수는 이 리비전을 쓸 때의 값(5)으로 고정한다 — 마이그레이션은 그때의 규칙을 기록한다.
BACKFILL_FREE_ORDINALS_SQL = """
INSERT INTO novel_free_ordinals (novel_id, ordinal)
SELECT novel_id, ordinal FROM novel_chapter_publications
WHERE ordinal > 5 AND price = 0
ON CONFLICT DO NOTHING
"""


def backfill_free_ordinals(connection: sa.Connection) -> int:
    """지금 무료인 6화 이후 번호를 남기고 새로 남긴 행 수를 돌려준다."""
    return connection.execute(sa.text(BACKFILL_FREE_ORDINALS_SQL)).rowcount


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "novel_free_ordinals",
        sa.Column("novel_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ordinal >= 1", name="ck_novel_free_ordinals_ordinal_positive"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("novel_id", "ordinal"),
    )
    filled = backfill_free_ordinals(op.get_bind())
    logger.warning("novel_free_ordinals: 무료로 공개한 6화 이후 번호 %d개를 남겼다", filled)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("novel_free_ordinals")
