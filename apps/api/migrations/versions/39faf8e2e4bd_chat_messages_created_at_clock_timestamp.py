"""chat_messages created_at clock_timestamp

Revision ID: 39faf8e2e4bd
Revises: bc062c967f3c
Create Date: 2026-09-28 06:39:57.000000

메시지 순서는 `ORDER BY created_at` 하나로 정해지는데 기본값 `now()`는 트랜잭션 시작 시각이라,
한 트랜잭션에 넣은 메시지들이 같은 값을 갖고 순서가 힙의 물리 위치에 맡겨진다. 그 사이 VACUUM이
앞서 죽은 행의 슬롯을 풀면 뒤에 넣은 메시지가 앞에 정렬된다. 기본값을 문장 실행 시각
(`clock_timestamp()`)으로 바꿔 삽입 순서가 곧 정렬 순서가 되게 한다.

기본값만 바꾸므로 기존 행은 다시 쓰지 않는다(카탈로그만 바뀌고 테이블 재작성 없음).

`alembic check`는 서버 기본값을 비교하지 않는다(`compare_server_default`를 켜지 않았다) — 모델과
이 마이그레이션이 어긋나도 초록이므로, 기본값은 삽입 순서 정렬 테스트가 지킨다.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '39faf8e2e4bd'
down_revision: str | Sequence[str] | None = 'bc062c967f3c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('chat_messages', 'created_at', server_default=sa.text('clock_timestamp()'))


def downgrade() -> None:
    op.alter_column('chat_messages', 'created_at', server_default=sa.text('now()'))
