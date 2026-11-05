"""feature switch overrides

Revision ID: 1c7f96fd67d8
Revises: 7eb6d96b147f
Create Date: 2026-11-05 14:18:52.734838

어드민이 켜고 끄는 기능 스위치의 덮어쓰기 표 `feature_switch_overrides` 와 그 변경 이력 표 `feature_switch_changes` 를 만든다.
덮어쓰기 행이 있는 스위치는 그 값으로, 없으면 `.env` 값으로 돈다. 이력의 사유는 비우거나 스페이스(U+0020)만으로 둘 수 없다
(Postgres `btrim` 은 스페이스만 깎는다 — 탭·줄바꿈·전각 공백만 있는 사유는 어드민 API 가 거른다) — 그 CHECK 는
alembic 1.18.5 의 `alembic check` 가 비교하지 않아 `IntegrityError` 행위 테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 두 표 모두 새 표이고 비어 있다. 운영자 칸의 FK 를 만들
때 `admin_users` 에 쓰기만 막는 짧은 잠금을 잡는다 — 떠 있는 API 는 그 표를 읽기만 하므로(어드민 로그인) 기다리는 요청이 없다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 표를 더하기만 하므로 옛 코드는 두 표를 모른 채 `.env` 값으로 돈다. 그 구간에는
덮어쓰기를 쓰는 화면·API 가 옛 색에 없어 덮어쓰기 행이 생기지 않는다.

**downgrade** — 두 표를 지운다. 덮어쓰기와 이력이 함께 사라지고 모든 스위치가 `.env` 값으로 돌아간다. 옛 코드로 돌아가기만
하려면 downgrade 없이 이미지만 되돌린다(옛 코드는 이 표를 읽지 않는다) — 다만 그러면 표가 남아, 새 이미지를 다시 올리는 순간
남은 덮어쓰기가 다시 먹는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c7f96fd67d8'
down_revision: str | Sequence[str] | None = '7eb6d96b147f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('feature_switch_changes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('before_override', sa.Boolean(), nullable=True),
    sa.Column('after_override', sa.Boolean(), nullable=True),
    sa.Column('env_value', sa.Boolean(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('admin_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(reason) <> ''", name='ck_feature_switch_changes_reason_not_blank'),
    sa.ForeignKeyConstraint(['admin_id'], ['admin_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('feature_switch_overrides',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('value', sa.Boolean(), nullable=False),
    sa.Column('admin_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['admin_id'], ['admin_users.id'], ),
    sa.PrimaryKeyConstraint('name')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table('feature_switch_overrides')
    op.drop_table('feature_switch_changes')
