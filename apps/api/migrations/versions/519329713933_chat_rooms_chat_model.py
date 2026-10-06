"""chat_rooms chat_model

Revision ID: 519329713933
Revises: e6aa289fea62
Create Date: 2026-10-06 18:49:35.868246

방이 고른 글쓰기 모델 칸. NULL 이 기본 모델(Gemini)이라 기존 행은 건드리지 않는다. 값 제약은 두지 않는다 — 레지스트리에서
내린 모델의 옛 값이 남아도 행이 살아 있어야 하고, 쓸 수 없는 값은 턴마다 기본 모델로 다시 판정한다.

되돌리기는 열을 지우는 것으로 끝난다(방마다 고른 모델이 사라지고 전부 Gemini 로 돈다). 이 열을 모르는 옛 이미지는 열을
SELECT 하지 않고, NULL 을 허용하므로 새 방 INSERT 도 그대로 된다 — 이미지를 먼저 되돌리고 downgrade 한다.

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '519329713933'
down_revision: str | Sequence[str] | None = 'e6aa289fea62'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('chat_rooms', sa.Column('chat_model', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_rooms', 'chat_model')
