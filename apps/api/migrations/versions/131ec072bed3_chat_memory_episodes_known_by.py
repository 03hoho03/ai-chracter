"""chat memory episodes known_by

Revision ID: 131ec072bed3
Revises: d6abfd9f92ce
Create Date: 2026-10-18 22:00:00.000000

장면 기억 행에 그 장면을 아는 인물 이름 목록 칸 `chat_memory_episodes.known_by text[] NULL` 을 넓히기만 한다. 칸의 뜻과
규칙은 사실 기억 행의 같은 칸과 같다 — NULL 은 공개이거나 알 수 없다는 뜻이고, 빈 배열은 쓰지 않는다("아무도 모른다"와
"모른다"를 NULL 하나로 둔다). CHECK 둘도 사실 기억 행의 것과 같은 식이다.

- `ck_chat_memory_episodes_known_by_count`: 원소 수 1~10.
- `ck_chat_memory_episodes_known_by_items`: NULL 원소 없음, 원소마다 60자 이하. CHECK 에 하위 질의를 쓸 수 없어서 원소를
  제어 문자 U+001F 로 이어 붙인 문자열에 구분자 없이 61자가 이어지는 구간이 없는지로 본다.
CHECK 는 `alembic check` 가 비교하지 않아 행위 테스트가 유일한 검증이다.

이 리비전에서는 칸을 채우는 코드가 없다 — 장면 추출 결과 스키마는 아직 이 칸을 모르므로 새 행도 NULL 이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 칸 추가와 CHECK 추가는 `chat_memory_episodes` 에 `ACCESS EXCLUSIVE` 를 잡는데,
떠 있는 추출 작업이 이 테이블에 장면 행을 넣는다. 그 쓰기와 겹쳐 락을 오래 기다리면 이 테이블을 읽는 회상·쓰는 추출이 모두
이 DDL 뒤에 줄을 선다. 5초 안에 못 잡으면 실패시켜 배포를 멈추는 쪽이 안전하다(체인 전체 롤백, 다시 돌리면 된다). 칸은
기본값 없는 NULL 이라 테이블을 다시 쓰지 않고, CHECK 검증은 모두 NULL 인 칸을 한 번 훑을 뿐이다.

**배포 겹침** — 옛 코드는 이 칸을 모른다. 옛 코드의 장면 INSERT 는 칸을 빼고 넣어 NULL 이 되고, CHECK 는 NULL 을 통과시킨다.

**downgrade** — CHECK 둘을 지운 뒤 칸을 지운다. 이 리비전에서는 칸을 채우는 코드가 없어 잃는 값이 없다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '131ec072bed3'
down_revision: str | Sequence[str] | None = 'd6abfd9f92ce'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 추출 작업의 장면 쓰기와 겹치면 오래 기다리지 않고 실패시킨다 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column('chat_memory_episodes', sa.Column('known_by', sa.ARRAY(sa.Text()), nullable=True))
    op.create_check_constraint(
        'ck_chat_memory_episodes_known_by_count',
        'chat_memory_episodes',
        'cardinality(known_by) BETWEEN 1 AND 10',
    )
    op.create_check_constraint(
        'ck_chat_memory_episodes_known_by_items',
        'chat_memory_episodes',
        "array_position(known_by, NULL) IS NULL AND array_to_string(known_by, E'\\x1F') !~ '[^\\x1F]{61}'",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_chat_memory_episodes_known_by_items', 'chat_memory_episodes', type_='check')
    op.drop_constraint('ck_chat_memory_episodes_known_by_count', 'chat_memory_episodes', type_='check')
    op.drop_column('chat_memory_episodes', 'known_by')
