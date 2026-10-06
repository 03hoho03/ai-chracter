"""novel_jobs model

Revision ID: 2494aa0e607e
Revises: 519329713933
Create Date: 2026-10-06 19:44:03.236470

소설 장 작업이 쓴 글쓰기 모델 칸. NULL 은 기본 모델(Gemini)이라 기존 행(전부 Gemini 장이거나 모델을 고르지 않는 AI 수정)은
건드리지 않는다. 값 제약(CHECK)은 두지 않는다 — 허용 값의 소스는 코드의 모델 레지스트리이고, 레지스트리에서 모델을 내려도
그 모델로 만든 옛 작업 행은 차감 기록의 짝으로 남아야 한다. 새 값은 요청 스키마가 레지스트리 id 만 받아서 거르고, 저장된
값을 어떻게 읽을지는 코드가 정한다.

되돌리기는 열을 지우는 것으로 끝난다(작업마다 적은 모델이 사라진다). 이 열을 모르는 옛 이미지는 열을 SELECT 하지 않고,
NULL 을 허용하므로 작업 INSERT 도 그대로 된다 — 이미지를 먼저 되돌리고 downgrade 한다. 진행 중인 상위 모델 장 작업이 있으면
옛 이미지는 그 작업을 Gemini 로 돌리게 되므로, 스위치를 끄고 진행 중 작업이 0 인 것을 본 뒤 되돌린다.

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2494aa0e607e'
down_revision: str | Sequence[str] | None = '519329713933'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('novel_jobs', sa.Column('model', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('novel_jobs', 'model')
