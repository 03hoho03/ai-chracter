"""턴 N 직전 상태 되살리기 — 드라이버 로그(스탯·기억)와 DB(메시지·요약 커서·단축어 행)를 합쳐 `_build_prompt` 주입
자리에 넣을 묶음과 히스토리·사용자 발화를 만든다.

값이 하나라도 확실하지 않으면 그 턴을 거부한다(`ReplayRefusedError`). 비슷한 값으로 채우면 현행 갈래가 덤프와 우연히 맞아도
변형 갈래는 다른 상태에서 조립될 수 있다.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import CurrentSummary
from api.chat.router import InjectedPersona, InjectedTurnState
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomMemorySnapshot
from api.db.models.story import Shortcut, StatDef
from replay.logs import DriverLogs, ReplayRefusedError, RoomStatic, memory_snapshot, sha256, stats_line, turn_line


@dataclass(frozen=True)
class RestoredTurn:
    """`stats_by_id` 는 스탯 entity_id 문자열 → 값(로그에 적힌 값 그대로, 시작 설정 정의로 거르기 전), `sources` 는 plan 의
    `state` 칸에 남길 출처 메모다."""

    turn: int
    history: list[ChatMessage]
    user_message: ChatMessage
    shortcut_entity_id: uuid.UUID | None
    memory_note: str
    summary: CurrentSummary | None
    stats_by_id: dict[str, float]
    stats_by_name: dict[str, float]
    sources: dict[str, Any]

    def turn_state(self, stats: dict[str, float], persona: InjectedPersona | None) -> InjectedTurnState:
        return InjectedTurnState(summary=self.summary, memory_note=self.memory_note, stats=stats, persona=persona)


async def stats_for_setup(db: AsyncSession, setup_id: uuid.UUID, values: dict[str, float]) -> dict[str, float]:
    """시작 설정의 스탯 정의 전부를 `str(entity_id)` 키로 채운 값. 하나라도 빠지면 거부한다 — 주입 경로는 빠진 스탯을
    상황 노트 조건에서 거짓으로 보는데, DB 경로는 시작값으로 본다. 조용히 시작값으로 채우면 그 턴의 실제 값과 다를 수
    있다."""
    ids = [str(i) for i in (await db.scalars(select(StatDef.entity_id).where(StatDef.starting_setup_id == setup_id)))]
    missing = sorted(set(ids) - set(values))
    if missing:
        raise ReplayRefusedError(f"스탯 기준 줄에 값이 없는 스탯: {missing}")
    return {stat_id: values[stat_id] for stat_id in ids}


async def find_shortcut(db: AsyncSession, version_id: uuid.UUID, entity_id: uuid.UUID) -> Shortcut:
    """서버가 단축어를 찾는 규칙과 같다: 방이 고정한 버전 안에서 entity_id 로."""
    shortcut = await db.scalar(
        select(Shortcut).where(Shortcut.entity_id == entity_id, Shortcut.content_version_id == version_id)
    )
    if shortcut is None:
        raise ReplayRefusedError(f"버전 {version_id} 에 단축어 {entity_id} 가 없다")
    return shortcut


def _turn_pairs(messages: list[ChatMessage]) -> list[int]:
    """턴 번호(1부터) → 그 턴 사용자 메시지의 인덱스. 바로 뒤가 응답인 사용자 메시지만 턴이다 — 유실 턴의 사용자 메시지는
    응답 없이 남고, 서버는 다음 턴을 조립할 때 그 메시지도 히스토리에 싣는다."""
    return [
        index
        for index in range(len(messages) - 1)
        if messages[index].role == ChatMessageRole.USER and messages[index + 1].role == ChatMessageRole.ASSISTANT
    ]


def _stats_by_name(logs: DriverLogs, static: RoomStatic, turn: int) -> tuple[dict[str, float], dict[str, Any]]:
    index, record = stats_line(logs, turn)
    by_name = {name: float(value) for name, value in record["roomAfter"]["stats"].items()}
    return by_name, {"kind": record["kind"], "index": index, "source": record["roomAfter"].get("source")}


async def _summary_cursor(
    db: AsyncSession, room_id: uuid.UUID, text: str, snapshot_id: str | None
) -> tuple[CurrentSummary, str]:
    """드라이버는 요약 본문만 남기고(API 가 커서를 주지 않는다) 윈도 자르기에는 커서가 필요하다. 그래서 DB 스냅숏 중
    본문 해시가 같은 행의 커서를 쓴다. 그 행이 없거나 커서가 다른 행이 여럿이면 어느 커서였는지 모르므로 거부한다.
    사람 턴을 보충한 줄처럼 스냅숏 id 를 함께 적은 줄이면 그 행을 쓰되, 해시가 맞는 행이어야 한다."""
    digest = sha256(text)
    rows = (
        await db.execute(
            select(
                ChatRoomMemorySnapshot.id,
                ChatRoomMemorySnapshot.cursor_created_at,
                ChatRoomMemorySnapshot.cursor_message_id,
                ChatRoomMemorySnapshot.summary_text,
            ).where(ChatRoomMemorySnapshot.chat_room_id == room_id)
        )
    ).all()
    matches = [row for row in rows if sha256(row.summary_text) == digest]
    if snapshot_id is not None:
        chosen = [row for row in matches if str(row.id) == snapshot_id]
        if not chosen:
            raise ReplayRefusedError(f"줄에 적힌 요약 스냅숏 {snapshot_id} 의 본문이 기억 스냅숏의 요약과 다르다")
        row = chosen[0]
        return CurrentSummary(cursor=(row.cursor_created_at, row.cursor_message_id), text=text), "snapshotId"
    cursors = {(row.cursor_created_at, row.cursor_message_id) for row in matches}
    if not cursors:
        raise ReplayRefusedError("요약 본문과 해시가 같은 DB 스냅숏이 없다")
    if len(cursors) > 1:
        raise ReplayRefusedError(f"요약 본문과 해시가 같은 DB 스냅숏의 커서가 {len(cursors)}개다")
    (cursor,) = cursors
    return CurrentSummary(cursor=cursor, text=text), "sha256"


async def restore_turn(
    db: AsyncSession, room: ChatRoom, turn: int, logs: DriverLogs, static: RoomStatic
) -> RestoredTurn:
    _, line = turn_line(logs, turn)
    by_name, stats_source = _stats_by_name(logs, static, turn)
    unknown = sorted(set(by_name) - set(static.stat_ids))
    if unknown:
        raise ReplayRefusedError(f"roomStatic 에 없는 스탯 이름: {unknown}")
    by_id = {static.stat_ids[name]: value for name, value in by_name.items()}

    snapshot = memory_snapshot(logs, turn)
    note = str(snapshot.get("note") or "")
    summary_text = str(snapshot.get("summary") or "")
    memory = line.get("memory") or {}
    # 턴 줄에도 그 턴에 보낸 기억의 해시가 있다. 스냅숏과 다르면 스냅숏이 빠진 것이다.
    for key, text in (("noteSha", note), ("summarySha", summary_text)):
        if memory.get(key) is not None and memory[key] != sha256(text):
            raise ReplayRefusedError(f"턴 {turn} 줄의 {key} 가 턴 {snapshot.get('turn')} 기억 스냅숏과 다르다")
    summary: CurrentSummary | None = None
    summary_rule = None
    if summary_text:
        summary, summary_rule = await _summary_cursor(db, room.id, summary_text, memory.get("snapshotId"))

    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        ).all()
    )
    pairs = _turn_pairs(messages)
    if not 1 <= turn <= len(pairs):
        raise ReplayRefusedError(f"DB 에 턴 {turn} 이 없다(완결 턴 {len(pairs)}개)")
    index = pairs[turn - 1]
    assistant_id = line.get("assistantMessageId") or (line.get("links") or {}).get("assistantMessageId")
    if assistant_id is not None and str(messages[index + 1].id) != assistant_id:
        raise ReplayRefusedError(f"DB 의 턴 {turn} 응답이 로그의 응답 메시지 {assistant_id} 가 아니다")

    shortcut_id = line.get("shortcutId")
    if shortcut_id is None and line.get("shortcut") is not None:
        # 단축어 id 를 남기기 전의 로그는 이름만 있다.
        shortcut_id = static.shortcut_ids.get(line["shortcut"])
        if shortcut_id is None:
            raise ReplayRefusedError(f"roomStatic 에 없는 단축어 이름: {line['shortcut']}")

    return RestoredTurn(
        turn=turn,
        history=messages[:index],
        user_message=messages[index],
        shortcut_entity_id=uuid.UUID(shortcut_id) if shortcut_id is not None else None,
        memory_note=note,
        summary=summary,
        stats_by_id=by_id,
        stats_by_name=by_name,
        sources={
            "statsLine": stats_source,
            "memorySnapshotTurn": snapshot.get("turn"),
            "summaryCursor": None
            if summary is None
            else {
                "createdAt": summary.cursor[0].isoformat(),
                "messageId": str(summary.cursor[1]),
                "rule": summary_rule,
            },
        },
    )
