"""novel bible knowledge onset

Revision ID: a3780c25c1b4
Revises: 45e57ce4d815
Create Date: 2026-11-04 15:00:00.000000

정본 기억 지식 표 `novel_bible_knowledge` 에 `onset`(이 장면에서 알게 됐다·믿게 됐다고 서술됨)을 더한다. 사실 표의 같은 칸과
같은 뜻이다 — 이미 알던 것을 이 장면에서 처음 서술한 앎은 거짓이다. "그 일이 일어났다고 서술되기 전에 이미 안다"를 막는 검사는
시작이 서술된 앎에만 걸어야 해서, 앎마다 이 표시를 저장한다.

- 기존 행은 거짓으로 채운 뒤 NOT NULL 을 건다. 거짓은 "알게 된 자리가 서술되지 않음"이라 그 행을 막는 쪽으로 기울지 않는다.
  이 표에 쓰는 코드(지식 슬롯)는 이 리비전과 같은 배포에 처음 들어오므로 운영 표는 비어 있다.
- 기본값은 두지 않는다. 배포 겹침 동안 도는 옛 이미지는 지식 슬롯이 등록부에 없어 이 표에 행을 넣지 않고, 이 표를 건드리는
  옛 코드는 소설·화 삭제의 DELETE 뿐이라 새 칸을 몰라도 된다. 새 코드는 언제나 값을 명시한다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 칸 추가가 이 표에 `ACCESS EXCLUSIVE` 를 잡는데, 소설
삭제가 이 표를 지우므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체
롤백, 다시 돌리면 된다).

**downgrade** 는 칸을 지운다 — 앎마다 저장한 시작 표시가 사라진다(그 앞 판 코드는 이 칸을 읽지 않는다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3780c25c1b4'
down_revision: str | Sequence[str] | None = '45e57ce4d815'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column('novel_bible_knowledge', sa.Column('onset', sa.Boolean(), nullable=True))
    op.execute("UPDATE novel_bible_knowledge SET onset = false")
    op.alter_column('novel_bible_knowledge', 'onset', existing_type=sa.Boolean(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column('novel_bible_knowledge', 'onset')
