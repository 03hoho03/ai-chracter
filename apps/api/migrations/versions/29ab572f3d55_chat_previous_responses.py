"""chat previous responses

Revision ID: 29ab572f3d55
Revises: 5cab2abe4e7b
Create Date: 2026-10-15 08:20:57.800642

재생성이 밀어낸 직전 AI 응답 하나를 방마다 보관하는 테이블 `chat_previous_responses` 를 만든다. 이 리비전은 넓히기만 한다 —
기존 테이블·칸은 바꾸지 않는다.

PK 가 방 FK 를 겸해(방당 한 행) 방으로 찾는 인덱스를 따로 두지 않는다. 방 FK 는 `ON DELETE CASCADE` 다. 장면 기억 테이블과 같은
이유다 — 방 삭제·탈퇴는 이 행을 따로 지우지 않고, 이 테이블을 모르는 옛 이미지가 방을 지울 때도 FK 위반으로 500 이 되지 않는다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. FK 생성은 참조하는 `chat_rooms` 에 `SHARE ROW EXCLUSIVE` 를 잠깐 잡는데, 떠 있는
API 가 그 테이블을 턴마다 쓰므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다
(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침** — 옛 코드는 이 테이블을 모르고 읽지도 쓰지도 않는다. 옛 코드의 방 삭제는 위 CASCADE 로 이 행까지 지운다. 옛
코드가 보내기·수정·삭제·초기화·재생성으로 대화를 바꾸면 이 행이 지워지지 않고 남지만, 새 코드는 이 행을 밀어낸 응답이 지금도
방의 마지막 메시지일 때만 되돌리므로 낡은 행을 쓰지 않는다.

**downgrade** — 테이블을 지운다. 버리는 것은 되돌리기용으로 보관한 직전 응답들이다. 옛 코드로 돌아가기만 하려면 downgrade
없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29ab572f3d55'
down_revision: str | Sequence[str] | None = '5cab2abe4e7b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 요청이 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('chat_previous_responses',
    sa.Column('chat_room_id', sa.Uuid(), nullable=False),
    sa.Column('replaced_by_message_id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('message_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('image_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_room_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('chat_previous_responses')
