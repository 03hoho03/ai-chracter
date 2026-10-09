import uuid

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


async def load_room_stats(
    db: AsyncSession, room_id: uuid.UUID, setup_id: uuid.UUID
) -> tuple[list[StatDef], dict[str, ChatRoomStat], dict[str, float]]:
    """시작설정의 스탯 정의, 방의 스탯 행(스탯 entity_id 문자열 → 행), 지금 값(같은 키 → 값)을 읽는다. 판정 단계는
    행 사전을 라우터의 `_write_room_stat` 에 넘겨 바뀐 값을 쓰고, 생성 프롬프트 조립은 지금 값으로 상황 노트 조건을 본다 —
    두 자리가 같은 값을 보도록 한 곳에서 읽는다.

    행이 없는 스탯(버전을 옮긴 방에서 새 버전에 생긴 스탯)은 시작값으로 본다 — 승격이 채우는 값과 같다."""
    # 판정 프롬프트가 이 순서로 규칙 글자를 붙인다 — 정렬이 없으면 행이 놓인 순서를 따라 실행마다 달라진다.
    stat_defs = list(
        (await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup_id).order_by(StatDef.order))).all()
    )
    # 같은 요청 안에서 두 번째로 읽을 때(생성 프롬프트 조립 뒤의 판정 단계) 세션에 남아 있는 행 객체는 SELECT 만으로는
    # 값이 갱신되지 않는다. 스트리밍 동안 같은 방의 다른 요청이 커밋한 값을 판정이 보도록 매번 DB 값으로 덮어쓴다 —
    # 객체 자체는 같은 것이 돌아오므로 `_write_room_stat` 가 고치는 행은 그대로 세션이 추적하는 행이다.
    stat_rows = {
        str(row.stat_entity_id): row
        for row in (
            await db.scalars(
                select(ChatRoomStat)
                .where(ChatRoomStat.chat_room_id == room_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    current_stats = {stat_id: float(row.current_value) for stat_id, row in stat_rows.items()}
    for stat_def in stat_defs:
        current_stats.setdefault(str(stat_def.entity_id), float(stat_def.initial_value))
    return stat_defs, stat_rows, current_stats
