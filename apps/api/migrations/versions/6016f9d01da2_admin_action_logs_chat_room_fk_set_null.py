"""admin action logs chat room fk set null

Revision ID: 6016f9d01da2
Revises: b72c33c70240
Create Date: 2026-09-27 23:49:17.124486

`admin_action_logs.target_chat_room_id` FK에 `ON DELETE SET NULL`을 단다. 관리자가 한 번이라도
열람한 방은 이 FK가 방 행 DELETE를 막아, 소유자의 방 삭제와 회원 탈퇴가 FK 위반으로 500이
됐다. 열람 로그는 감사 기록이라 지우지 않고 사라진 방을 가리키던 칸만 비운다 — 누구의 채팅을
봤는지는 `target_user_id`로 남는다. 컬럼은 원래 nullable이고 이 테이블에 CHECK 제약이 없어
NULL이 되어도 걸리는 것이 없다.

제약 이름은 Postgres가 최초 생성 때 붙인 기본 이름을 그대로 쓴다. autogenerate가 새 FK 이름을
`None`으로 내서, 그대로 두면 downgrade의 `drop_constraint(None, ...)`가 실패한다. 같은 이름을
유지하면 upgrade·downgrade 양쪽에서 대상이 하나로 정해진다.
"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6016f9d01da2'
down_revision: str | Sequence[str] | None = 'b72c33c70240'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = 'admin_action_logs_target_chat_room_id_fkey'


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(_FK_NAME, 'admin_action_logs', type_='foreignkey')
    op.create_foreign_key(
        _FK_NAME, 'admin_action_logs', 'chat_rooms', ['target_chat_room_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_FK_NAME, 'admin_action_logs', type_='foreignkey')
    op.create_foreign_key(_FK_NAME, 'admin_action_logs', 'chat_rooms', ['target_chat_room_id'], ['id'])
