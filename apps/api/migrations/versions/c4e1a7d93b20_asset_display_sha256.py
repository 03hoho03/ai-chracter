"""asset display sha256

Revision ID: c4e1a7d93b20
Revises: b871b88d2a90
Create Date: 2026-10-22 21:00:00.000000

`assets.display_sha256`(TEXT NULL): 크게 그리는 정지 변형 바이트의 sha256. 소설 삽화의 공개 심사와 운영자 내림이 채우고, 화
읽기가 이 값으로 내림 표를 이어 같은 파일을 담은 다른 자산도 내린 그림으로 본다. 채워 넣을 과거 값은 없다 — 공개 심사가 다음에
그 그림을 볼 때 채운다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 이 칸을 매핑하지 않아 SELECT·INSERT 에 싣지 않고, 새 자산 행은 NULL 을
받는다. 그 구간에 옛 코드가 공개 심사·내림을 하면 이 칸을 채우지 않을 뿐이다 — 독자 읽기는 내림 행의 자산 id 로도 보므로 내린
그 자산은 그대로 비워진다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 늘 읽고 쓰는 표의 ALTER 라 5초 안에 잠금을 못 잡으면 실패시킨다
(다시 돌리면 된다). NULL 칸 추가라 표를 다시 쓰지 않는다.

**downgrade**: 칸을 지운다. 그 뒤 독자 읽기는 이 칸을 모르는 옛 코드처럼 내림 행의 자산 id 로만 본다(같은 파일을 담은 다른
자산은 다시 보인다 — 되돌릴 때 운영자가 그 자산을 노벨 이용제한으로 닫는다). 다시 올리면 공개 심사·내림이 다시 채운다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e1a7d93b20"
down_revision: str | Sequence[str] | None = "b871b88d2a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("assets", sa.Column("display_sha256", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("assets", "display_sha256")
