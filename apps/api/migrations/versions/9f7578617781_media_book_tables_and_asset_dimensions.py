"""media book tables and asset dimensions

Revision ID: 9f7578617781
Revises: 326a35d0a7d8
Create Date: 2026-10-01 16:30:08.574146

스토리 미디어 북(인물 축 · 장면 축 · 인물 × 장면 칸)과 그 보관함 노출 기록 테이블을 만들고, 자산에 픽셀
너비·높이 컬럼을 더한다. 스키마만 바꾼다 — 기존 자산의 너비·높이는 NULL 로 남고 값은 별도 스크립트가
채운다.

`story_media_exposures` 의 복합 PK 는 `alembic check` 가 비교하지 않아(이 리비전에서 PK 줄을 지워도
check 는 초록이었다) `tests/test_chat_models.py` 의 `raises(IntegrityError)` 테스트가 유일한 검증이다.
UNIQUE 는 check 가 모델과의 일치를 보고, 무엇을 막고 무엇을 허용하는지(다른 버전·같은 이름은 허용)는
`tests/test_story_models.py` 가 고정한다. 축 이름에는 UNIQUE 를 걸지 않는다 — 한 저장 요청 안에서
이름을 맞바꾸면 행을 하나씩 고치는 도중 잠깐 중복이 생긴다.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9f7578617781'
down_revision: str | Sequence[str] | None = '326a35d0a7d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('media_book_people',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('entity_id', sa.Uuid(), nullable=False),
    sa.Column('content_version_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['content_version_id'], ['content_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_version_id', 'entity_id', name='ux_media_book_people_version_entity')
    )
    op.create_table('media_book_scenes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('entity_id', sa.Uuid(), nullable=False),
    sa.Column('content_version_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['content_version_id'], ['content_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_version_id', 'entity_id', name='ux_media_book_scenes_version_entity')
    )
    op.create_table('media_book_cells',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('entity_id', sa.Uuid(), nullable=False),
    sa.Column('content_version_id', sa.Uuid(), nullable=False),
    sa.Column('person_entity_id', sa.Uuid(), nullable=False),
    sa.Column('scene_entity_id', sa.Uuid(), nullable=False),
    sa.Column('image_asset_id', sa.Uuid(), nullable=False),
    sa.Column('blurred_asset_id', sa.Uuid(), nullable=True),
    sa.Column('situation_description', sa.Text(), server_default='', nullable=False),
    sa.Column('unlock_hint', sa.Text(), server_default='', nullable=False),
    sa.Column('exclude_from_chat', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['blurred_asset_id'], ['assets.id'], ),
    sa.ForeignKeyConstraint(['content_version_id'], ['content_versions.id'], ),
    sa.ForeignKeyConstraint(['image_asset_id'], ['assets.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_version_id', 'entity_id', name='ux_media_book_cells_version_entity'),
    sa.UniqueConstraint(
        'content_version_id', 'person_entity_id', 'scene_entity_id', name='ux_media_book_cells_version_person_scene'
    )
    )
    op.create_table('story_media_exposures',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('content_id', sa.Uuid(), nullable=False),
    sa.Column('cell_entity_id', sa.Uuid(), nullable=False),
    sa.Column('first_exposed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['content_id'], ['contents.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'content_id', 'cell_entity_id')
    )
    op.add_column('assets', sa.Column('width', sa.Integer(), nullable=True))
    op.add_column('assets', sa.Column('height', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('assets', 'height')
    op.drop_column('assets', 'width')
    op.drop_table('story_media_exposures')
    op.drop_table('media_book_cells')
    op.drop_table('media_book_scenes')
    op.drop_table('media_book_people')
