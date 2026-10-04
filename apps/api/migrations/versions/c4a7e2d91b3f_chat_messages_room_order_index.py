"""chat messages room order index

Revision ID: c4a7e2d91b3f
Revises: 8e895c898730
Create Date: 2026-10-04 20:30:00.000000

`chat_messages` 에 `(chat_room_id, created_at, id)` 인덱스를 더한다. 이 테이블에는 PK 말고 인덱스가 없어서, 턴마다의
히스토리 로드·방 조회·방 목록의 마지막 메시지 조회가 한 방의 메시지를 찾으려고 플랫폼 전체 메시지를 순차 스캔했다.
열 순서는 그 조회들의 정렬 `(created_at, id)` 와 같아 방 하나의 메시지를 정렬된 채로 읽는다.

`CREATE INDEX CONCURRENTLY` 를 쓰지 않는다. 평범한 `CREATE INDEX` 는 만드는 동안 테이블 쓰기(메시지 저장)를 막지만,
작성 시점 운영 테이블은 277행이라 그 시간이 무시할 만하다. `CONCURRENTLY` 는 트랜잭션 안에서 실행할 수 없어 체인을 한
트랜잭션으로 도는 `migrations/env.py` 와 맞지 않고, 실패하면 무효 인덱스가 남아 손으로 지워야 한다 — 얻는 것 없이 그
비용만 진다. 행 수가 수백만으로 커진 뒤 이 인덱스를 지웠다 다시 만들 일이 생기면, 그때는 배포 마이그레이션이 아니라
운영 DB 에서 `CREATE INDEX CONCURRENTLY` 를 따로 돌린 뒤 이 리비전으로 stamp 하는 쪽을 검토한다(만드는 동안 채팅 저장이
멈춘다).
"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4a7e2d91b3f'
down_revision: str | Sequence[str] | None = '8e895c898730'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'ix_chat_messages_chat_room_id_created_at_id',
        'chat_messages',
        ['chat_room_id', 'created_at', 'id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_chat_messages_chat_room_id_created_at_id', table_name='chat_messages')
