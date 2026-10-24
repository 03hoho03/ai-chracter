"""chat turn stage routes

Revision ID: 265a8f26c44a
Revises: d0051f733bb7
Create Date: 2026-10-24 22:00:00.000000

턴 기록에 단계별 모델 배정 스냅샷 칸(`chat_turns.stage_routes`, JSONB, 기본값 `[]`, NOT NULL)을 더한다. 방 턴의 쓰기 구간이 그 레인의
단계마다 읽은 체인·세트 id·부를 모델·경로·출처를 한 칸씩 적는다 — 배정 표의 행이 실제로 어느 턴에 적용됐는지를 턴 단위로 되짚을
수 있게. 이 리비전만으로는 칸을 쓰는 코드가 없다.

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안): 옛 코드는 칸을 매핑하지 않아 읽지도 쓰지도 않는다. 옛
코드의 턴 기록 INSERT 는 칸을 비워 두고 서버 기본값 `[]` 이 채운다(그래서 기본값을 떼지 않는다).

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 상수 기본값이 있는 칸 추가는 표를 다시 쓰지 않는 메타데이터 변경이지만 그 순간
`chat_turns` 에 `ACCESS EXCLUSIVE` 를 잡아야 한다. 그래서 이 표를 만진 채 열려 있는 트랜잭션(턴 쓰기 구간, 재생성·되돌리기의 기록
읽기, 원가 보기 스크립트의 읽기 전용 트랜잭션)이 끝날 때까지 기다리고, 기다리는 동안 그 뒤에 오는 턴 쓰기와 기록 읽기가 모두 이
잠금 뒤에 줄을 선다. 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**downgrade**: 칸만 지운다. 버리는 것은 턴마다의 배정 스냅샷이고 사용자에게 보이지 않는 진단 기록이라 지우기를 막는 가드는 두지
않는다(내린 뒤 다시 올려도 돌아오지 않는다 — 그 사이 행은 `[]` 이다). 칸을 지우는 순간 이 칸을 매핑한 새 이미지의 턴 기록 INSERT 와
기록 읽기가 실패해 턴 쓰기 구간이 깨지므로 **이미지를 먼저 되돌린 뒤** 일회성 컨테이너로 내린다(옛 이미지는 이 칸이 있어도 돈다 —
이미지만 되돌리는 데에는 downgrade 가 필요 없다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "265a8f26c44a"
down_revision: str | Sequence[str] | None = "d0051f733bb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "chat_turns",
        sa.Column(
            "stage_routes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("chat_turns", "stage_routes")
