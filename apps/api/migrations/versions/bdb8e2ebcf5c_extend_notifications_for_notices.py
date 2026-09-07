"""extend notifications for notices

Revision ID: bdb8e2ebcf5c
Revises: 6040220ae77b
Create Date: 2026-09-07 23:18:46.541505

tasks/techspec.md §3-2·§3-3(리비전 2/3). 조치 통지 전용이던 `notifications`를 공지도
담을 수 있게 넓힌다 — `inquiry_id`는 여기서 넣지 않는다(`inquiries` 테이블이 아직 없어
FK를 걸 수 없다, 리비전 3에서 추가).

- `reason_category`/`admin_comment`를 `nullable=True`로 완화. 조치 통지 3종
  (`moderation-action`/`user-warned`/`user-suspended`)은 계속 두 컬럼을 채우지만
  공지는 인용할 사유가 없다. 기존 행에는 NULL이 없으므로(공지 알림은 아직 만들어지지
  않는다) 이 ALTER 자체는 안전하다.
- `notice_id` FK 컬럼 + 부분 유니크 인덱스. 숨김 → 재게시로 같은 유저에게 같은 공지의
  알림이 두 번 가는 것을 DB가 막는다.
- **`op.create_foreign_key`에 autogenerate가 이름을 `None`으로 냈다** — 그대로 두면
  downgrade의 `op.drop_constraint(None, ...)`가 실제 제약 이름을 모른 채 호출돼 실패한다.
  `aceda536013c`/`91a008760f4a` 선례를 따라 `fk_notifications_notice_id`로 손으로
  이름을 붙였다.
- ⚠️ **downgrade의 두 `alter_column(nullable=False)`는 그 시점에 NULL 행이 있으면
  실패한다.** 이 리비전 시점에는 없지만(공지 알림은 리비전 2 배포 시점엔 아직 안 만들어짐),
  이후 리비전(공지 fan-out)이 배포된 뒤에는 조건부로 위험해진다 — `0741a91285ed`의
  downgrade와 같은 수준으로 방어 코드는 넣지 않는다.
"""
from typing import Union
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bdb8e2ebcf5c'
down_revision: str | Sequence[str] | None = '6040220ae77b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('notifications', 'reason_category',
               existing_type=sa.TEXT(),
               nullable=True)
    op.alter_column('notifications', 'admin_comment',
               existing_type=sa.TEXT(),
               nullable=True)
    op.add_column('notifications', sa.Column('notice_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_notifications_notice_id', 'notifications', 'notices', ['notice_id'], ['id'])
    op.create_index('ux_notifications_notice_user', 'notifications', ['notice_id', 'user_id'], unique=True, postgresql_where=sa.text('notice_id IS NOT NULL'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ux_notifications_notice_user', table_name='notifications', postgresql_where=sa.text('notice_id IS NOT NULL'))
    op.drop_constraint('fk_notifications_notice_id', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'notice_id')
    # 위 경고 참고 — 이 시점에 NULL인 행이 있으면 아래 두 ALTER가 실패한다.
    op.alter_column('notifications', 'admin_comment',
               existing_type=sa.TEXT(),
               nullable=False)
    op.alter_column('notifications', 'reason_category',
               existing_type=sa.TEXT(),
               nullable=False)
