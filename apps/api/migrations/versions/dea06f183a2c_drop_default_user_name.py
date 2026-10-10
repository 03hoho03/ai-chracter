"""drop default_user_name

Revision ID: dea06f183a2c
Revises: 1a843a0b2d8f
Create Date: 2026-10-10 21:47:51.990515

스토리·캐릭터 버전의 작품 기본 이름 칸(`default_user_name`)을 지운다. 이 저장소에서 `upgrade()` 가 컬럼을 지우는
첫 리비전, 곧 첫 contract 다. 앞선 배포가 이 칸을 읽고 쓰는 코드를 모두 없애고 모델 매퍼에서도 빼 두었으므로, 배포가
겹치는 동안 새 스키마 위에서 도는 옛 이미지(그 앞선 배포의 이미지)는 이 칸을 SELECT·INSERT 에 넣지 않는다. 그 앞선
배포보다 더 옛 이미지는 이 칸을 SELECT 하므로 칸이 없는 채로 띄우면 안 된다 — 거기까지 되돌릴 때는 먼저 이 리비전을
downgrade 한다.

`upgrade()` 는 첫 문장으로 `SET LOCAL lock_timeout = '5s'` 를 건다. 배포 중에도 떠 있는 API 가 두 테이블을 읽으므로
`ALTER TABLE` 이 오래 걸린 트랜잭션 뒤에서 락을 기다리면 그 뒤로 모든 읽기가 줄을 선다. 5초 안에 락을 못 잡으면
마이그레이션이 실패해 배포가 멈추고(체인 전체 롤백), 다시 돌리면 된다.

`downgrade()` 는 칸을 `Text NOT NULL server_default ''` 로 되살린다. **되살려도 옛 값은 복원되지 않는다** — 모든 행이
빈 값(= 대체어 "당신")으로 돌아온다. 그래서 이 리비전은 운영에서 값이 든 행이 0건인 것을 확인한 뒤에 적용한다.
`server_default` 는 이 칸을 모르는 코드의 INSERT 가 NOT NULL 위반이 되지 않게 하려는 것이다.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dea06f183a2c'
down_revision: str | Sequence[str] | None = '1a843a0b2d8f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 읽기가 ALTER 의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column('story_version_details', 'default_user_name')
    op.drop_column('character_version_details', 'default_user_name')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('character_version_details', sa.Column('default_user_name', sa.Text(), server_default='', nullable=False))
    op.add_column('story_version_details', sa.Column('default_user_name', sa.Text(), server_default='', nullable=False))
