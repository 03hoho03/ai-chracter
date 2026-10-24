"""chat room memory forget generation

Revision ID: 914b076c9291
Revises: 174f78b92e5c
Create Date: 2026-10-24 12:00:00.000000

방 행에 잊기 세대 칸(`chat_rooms.memory_forget_generation`, 정수, 기본 0, NOT NULL)을 더한다. 방 주인이 사실 기억을 잊게 하면 같은
트랜잭션에서 하나 오르고, 사실 추출은 입력을 읽기 전과 결과를 넣기 직전에 이 값을 읽어 바뀌었으면 결과를 버린다 — 잊기 직전에 그
키를 입력으로 읽은 추출이 잊기 뒤에 같은 키를 다시 넣지 못하게.

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안): 옛 코드는 칸을 매핑하지 않아 읽지도 쓰지도 않는다. 방
INSERT 는 칸을 비워 두고 서버 기본값 0 이 채운다. 이 리비전만으로는 칸을 쓰는 코드가 없다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 늘 읽는 `chat_rooms` 를 ALTER 하므로 오래 걸린 트랜잭션 뒤에서 기다리며
뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(다시 돌리면 된다). 상수 기본값이 있는 칸 추가는 표를 다시 쓰지 않는다.

**downgrade**: 칸만 지운다. 이미 잊게 한 장면·사실 행은 실제로 지워졌으므로 내려도 돌아오지 않는다. 칸을 지우는 순간 이 칸을
매핑한 새 이미지의 방 조회가 모두 실패하므로 **이미지를 먼저 되돌린 뒤** 일회성 컨테이너로 내린다(옛 이미지는 이 칸이 있어도 돈다 —
이미지만 되돌리는 데에는 downgrade 가 필요 없다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "914b076c9291"
down_revision: str | Sequence[str] | None = "174f78b92e5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "chat_rooms", sa.Column("memory_forget_generation", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("chat_rooms", "memory_forget_generation")
