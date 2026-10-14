"""체크포인트 DB 의 사실 행(`chat_memory_facts`)을 사실 오프라인 지표 입력 꼴로 내보낸다. 읽기만 한다.

칸은 지표가 읽는 이름(`kind`·`subject`·`object`·`attribute`·`value`·`truth_status`·`asserted_by`·`speaker`·`known_by`·
`importance`·`start_turn`·`end_turn`·`snapshot_id`)을 테이블에서 같은 이름으로 읽는다 — 운영 사실 테이블이 따라야 할 칸 이름이다.
없는 칸은 비운다(None). 행 순서는 쓴 순서(스냅샷 커서 순, 같은 스냅샷 안은 행의 생성 순)이고, 검색 대상이 되는 첫 턴은 장면
내보내기와 같이 그 스냅샷이 생긴 시각까지 들어온 응답 수 + 1 이다. 테이블이 없으면 거부한다."""

import uuid
from typing import Any

from memory_eval.server_recall import available_from_turns

FACT_TABLE = "chat_memory_facts"
FACT_COLUMNS = (
    "id", "snapshot_id", "kind", "subject", "object", "attribute", "fact_key", "value", "truth_status",
    "asserted_by", "speaker", "known_by", "importance", "start_turn", "end_turn",
)  # fmt: skip


def fact_rows_from_db(records: list[dict[str, Any]], assistant_times: list[Any]) -> list[dict[str, Any]]:
    """테이블 행(칸 → 값, 스냅샷 생성 시각 `snapshot_created_at` 포함)을 지표 입력 꼴로."""
    first_turn = available_from_turns(sorted({r["snapshot_created_at"] for r in records}), assistant_times)
    out = []
    for record in records:
        row = {name: record.get(name) for name in FACT_COLUMNS}
        row["id"] = str(row["id"]) if row["id"] is not None else None
        row["snapshot_id"] = str(row["snapshot_id"]) if row["snapshot_id"] is not None else None
        row["known_by"] = list(row["known_by"]) if row["known_by"] else None
        row["available_from_turn"] = first_turn[record["snapshot_created_at"]]
        out.append(row)
    return out


async def export_facts(db: Any, room_id: uuid.UUID) -> list[dict[str, Any]]:
    from sqlalchemy import select, text

    from api.chat.memory_window import opening_message
    from api.db.models import ChatMessage, ChatMessageRole

    if not await db.scalar(text(f"SELECT to_regclass('{FACT_TABLE}') IS NOT NULL")):
        raise SystemExit(f"이 DB 에 사실 테이블({FACT_TABLE})이 없다 — 사실 계층 코드로 넣은 체크포인트만 내보낸다")
    present = set(
        (
            await db.scalars(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": FACT_TABLE}
            )
        ).all()
    )
    for required in ("snapshot_id", "chat_room_id"):
        if required not in present:
            raise SystemExit(f"사실 테이블에 {required} 칸이 없다 — 하네스가 가정한 칸 이름과 다르다")
    columns = ", ".join(f"f.{c}" for c in FACT_COLUMNS if c in present)
    order = "f.created_at, f.id" if "created_at" in present else "f.id"
    result = await db.execute(
        text(
            f"SELECT {columns}, s.created_at AS snapshot_created_at FROM {FACT_TABLE} f "
            "JOIN chat_room_memory_snapshots s ON s.id = f.snapshot_id WHERE f.chat_room_id = :room "
            f"ORDER BY s.cursor_created_at, s.cursor_message_id, {order}"
        ),
        {"room": room_id},
    )
    records = [dict(r._mapping) for r in result]
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )
    opening = opening_message(messages)
    assistant = [m.created_at for m in messages if m.role == ChatMessageRole.ASSISTANT and m is not opening]
    return fact_rows_from_db(records, assistant)
