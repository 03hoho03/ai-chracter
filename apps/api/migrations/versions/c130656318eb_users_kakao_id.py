"""users kakao_id

Revision ID: c130656318eb
Revises: 5cf390a62b62
Create Date: 2026-10-02 00:31:04.253757

카카오 로그인 회원을 식별하는 카카오 회원번호 칸. `google_sub` 와 같은 모양(Text, UNIQUE,
nullable)이다 — 이메일·구글 가입자는 값이 없고, 탈퇴하면 파기돼 NULL 이 된다. 기존 행은 전부
NULL 이라 백필이 없다.

제약 이름을 Postgres 기본 이름(`users_kakao_id_key`)으로 직접 준다. 프로젝트에 naming_convention
이 없어 autogenerate 가 이름을 `None` 으로 내고, 그대로 두면 downgrade 의
`drop_constraint(None, ...)` 가 실패한다.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c130656318eb'
down_revision: str | Sequence[str] | None = '5cf390a62b62'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIQUE_NAME = 'users_kakao_id_key'


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('kakao_id', sa.Text(), nullable=True))
    op.create_unique_constraint(_UNIQUE_NAME, 'users', ['kakao_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_UNIQUE_NAME, 'users', type_='unique')
    op.drop_column('users', 'kakao_id')
