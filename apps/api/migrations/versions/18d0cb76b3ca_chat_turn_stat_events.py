"""chat turn stat events

Revision ID: 18d0cb76b3ca
Revises: 914b076c9291
Create Date: 2026-10-24 18:00:00.000000

턴 기록에 스탯 판정 이벤트 칸(`chat_turns.stat_events`, JSONB, 기본 `'[]'`, NOT NULL)을 더한다. 그 턴 스탯 판정이 스탯마다 어떤
규칙을 발동했고 어느 규칙 하나를 적용했는지, 그 폭과 범위에 잘렸는지를 규칙 id 로만 남기는 칸이다 — 지금 턴 기록에는 반영 전·뒤
값만 남아 폭이 같은 규칙 둘 중 무엇이 적용됐는지 사후에 가를 수 없다. 규칙 조건 글은 싣지 않는다.

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안): 옛 코드는 칸을 매핑하지 않아 읽지도 쓰지도 않는다. 턴
기록 INSERT 는 칸을 비워 두고 서버 기본값 `[]` 이 채운다. 이 리비전만으로는 칸을 쓰는 코드가 없다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 턴마다 INSERT 하는 `chat_turns` 를 ALTER 하므로 오래 걸린 트랜잭션
뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(다시 돌리면 된다). 상수 기본값이 있는 칸 추가는 표를 다시
쓰지 않는다.

**downgrade**: 칸만 지운다. 쌓인 이벤트는 함께 사라지고 다시 올려도 돌아오지 않는다(스탯 값과 `stat_changes` 는 그대로다). 칸을 지우는
순간 이 칸을 매핑한 새 이미지의 턴 기록 INSERT·조회가 모두 실패하므로 **이미지를 먼저 되돌린 뒤** 일회성 컨테이너로 내린다(옛 이미지는
이 칸이 있어도 돈다 — 이미지만 되돌리는 데에는 downgrade 가 필요 없다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "18d0cb76b3ca"
down_revision: str | Sequence[str] | None = "914b076c9291"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "chat_turns",
        sa.Column(
            "stat_events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("chat_turns", "stat_events")
