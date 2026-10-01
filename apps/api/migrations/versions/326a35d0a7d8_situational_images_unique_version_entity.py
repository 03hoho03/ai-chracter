"""situational images unique version entity

Revision ID: 326a35d0a7d8
Revises: e6d1de89970a
Create Date: 2026-10-01 16:07:15.907262

한 버전 안에서 상황별 이미지 항목(entity_id)이 행 하나만 갖게 한다. 자동저장 PATCH 와 이미지 등록이
같은 새 항목을 동시에 insert 하면 행이 둘이 될 수 있었고, 그 뒤로 PATCH 는 한 행만 추적해 남은 행이
발행본까지 복제됐다. 두 쓰기 경로는 이 제약을 대상으로 `ON CONFLICT DO UPDATE` 한다.

중복 행을 정리하는 단계는 없다. 이 리비전을 쓸 당시 운영 DB 에 같은 (버전, entity_id) 중복이 0건이었다.
중복이 있는 DB 에서는 제약 생성이 실패해 업그레이드가 멈춘다 — 어느 행을 남길지 정하지 않고 지우는 것보다
멈추는 쪽이 낫다.
"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '326a35d0a7d8'
down_revision: str | Sequence[str] | None = 'e6d1de89970a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        'ux_situational_images_version_entity', 'situational_images', ['content_version_id', 'entity_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ux_situational_images_version_entity', 'situational_images', type_='unique')
