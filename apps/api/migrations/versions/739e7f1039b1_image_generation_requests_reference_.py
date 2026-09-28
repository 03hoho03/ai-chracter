"""image generation requests reference asset

Revision ID: 739e7f1039b1
Revises: 697222d13fe8
Create Date: 2026-09-28 16:55:51.453816

이미지 생성 요청 행에 참조 이미지로 쓴 asset id 를 남긴다. 기본값 없는 NULL 컬럼이라 기존 행을
다시 쓰지 않고, 채우는 백필도 없다(이 컬럼 전의 요청은 참조를 보낼 수 없었다).

FK 는 `ON DELETE SET NULL` 이다 — 참조로 쓰인 이미지도 사용자가 지울 수 있어야 하고, 지우면 요청
행은 남기고 그 칸만 비운다. `assets.request_id` 와 서로를 가리키지만 두 테이블 모두 이미 있어
`add_column` 뒤 `create_foreign_key` 로 충분하다. 제약 이름은 downgrade 의 `drop_constraint` 가
대상을 하나로 정하도록 명시한다(autogenerate 가 이름을 비워 내면 downgrade 가 실패한다).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '739e7f1039b1'
down_revision: str | Sequence[str] | None = '697222d13fe8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = 'fk_image_generation_requests_reference_asset_id'
_INDEX_NAME = 'ix_image_generation_requests_reference_asset_id'


def upgrade() -> None:
    op.add_column('image_generation_requests', sa.Column('reference_asset_id', sa.Uuid(), nullable=True))
    op.create_index(_INDEX_NAME, 'image_generation_requests', ['reference_asset_id'], unique=False)
    op.create_foreign_key(
        _FK_NAME, 'image_generation_requests', 'assets', ['reference_asset_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, 'image_generation_requests', type_='foreignkey')
    op.drop_index(_INDEX_NAME, table_name='image_generation_requests')
    op.drop_column('image_generation_requests', 'reference_asset_id')
