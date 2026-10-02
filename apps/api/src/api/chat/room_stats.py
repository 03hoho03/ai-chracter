from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.chat import ChatRoom, ChatRoomStat
from api.db.models.story import StartingSetup, StatDef


async def seed_missing_room_stats(db: AsyncSession, rooms: ColumnElement[bool]) -> None:
    """`rooms` 조건에 맞는 방마다, 방이 고정한 버전의 시작설정 스탯 중 행이 없는 것을 시작값으로 채운다.

    방을 새 발행 버전으로 옮기는 두 경로(사용자의 최신 버전 고정, 제한 해제·이의 수용의 일괄 승격)가 부른다. 새 버전에
    생긴 스탯의 행이 없으면 화면 스탯 패널에 나오지 않는다. 이미 있는 행(플레이한 값)은 덮지 않고, 새 버전에서 빠진
    스탯의 행도 지우지 않는다 — 옮기기는 초기화가 아니다. 캐릭터 방은 시작설정이 없어 아무것도 채우지 않는다.
    방의 버전 변경이 먼저 반영돼 있어야 한다(ORM 대입은 이 문장 전의 자동 flush 로 나간다)."""
    await db.execute(
        pg_insert(ChatRoomStat)
        .from_select(
            ["chat_room_id", "stat_entity_id", "current_value"],
            select(ChatRoom.id, StatDef.entity_id, StatDef.initial_value)
            .join(
                StartingSetup,
                and_(
                    StartingSetup.content_version_id == ChatRoom.content_version_id,
                    StartingSetup.entity_id == ChatRoom.starting_setup_entity_id,
                ),
            )
            .join(StatDef, StatDef.starting_setup_id == StartingSetup.id)
            .where(rooms),
        )
        .on_conflict_do_nothing(index_elements=[ChatRoomStat.chat_room_id, ChatRoomStat.stat_entity_id])
    )
