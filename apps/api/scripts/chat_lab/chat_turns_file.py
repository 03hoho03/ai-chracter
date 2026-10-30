"""턴 기록 내보내기 파일(`chat-turns.jsonl`)의 형식 — 쓰기와 읽기 둘 다 순수 함수다(DB 를 읽는 쪽은 내보내기 명령이다).

`chat_turns` 는 런 당시 로컬 DB 에만 있고 그 DB 볼륨은 대개 지워진다. 그래서 묶음 옆에 파일로 옮겨 둔다. 첫 줄은 머리 줄
(`kind` 가 `export`)이고 나머지는 행 하나당 한 줄(`kind` 가 `row`, 행은 `row` 칸)이다. 행을 한 칸 안에 감싸는 것은 행 자신에도
`kind` 칼럼(send·edit·regenerate)이 있어서다. 행은 `ChatTurn` 칼럼 이름 그대로이고 값은 uuid·시각만 문자열로 바꾼다.

머리 줄에 남기는 것:
- 내보낸 시각과 방 id, 그리고 이 파일이 "내보내기 시점 상태"라는 문장 — 같은 방을 여러 묶음이 쓰면(체크포인트 복원) DB 에는 그
  방의 마지막 상태만 있어, 이 파일의 행이 이 묶음의 턴만이라는 보장이 없다.
- 단가표 기준일(`PRICES_AS_OF`)과 단가표 내용의 sha256 — 기준일은 "표 전체를 다시 확인한 날"이라 그 뒤 줄이 더해져도 그대로여서
  날짜 하나로는 판을 가를 수 없다. 원가는 읽는 때 지금 단가표로 다시 내고, 해시가 다르면 그 사실을 주의로 보인다.
- 방 시작 설정의 스탯 정의(id·이름·숨김 여부) — 숨김 스탯은 방 스냅숏에 없고 턴 기록에 id 로만 남아, 정의가 없으면 이름도
  숨김 표시도 보일 수 없다.

이 파일은 묶음을 찾을 때 드라이버 로그로 잡히지 않아야 한다 — 어느 줄도 `kind` 가 `turn` 이 아니다."""

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from api.db.models import ChatTurn, StatDef
from api.llm import pricing

EXPORT_KIND = "export"
ROW_KIND = "row"
EXPORT_SCOPE = "내보내기 시점 상태 — 내보낸 시각에 로컬 DB 에 남아 있던 이 방의 턴 기록 전부다. 같은 방을 이어 친 다른 측정의 행이 섞일 수 있다"


class ChatTurnsFormatError(ValueError):
    """턴 기록 파일로 읽을 수 없다(머리 줄이 없거나 모양이 다르다)."""


@dataclass(frozen=True)
class ExportStatDef:
    """스탯 정의 하나. `id` 는 `StatDef.entity_id` 다 — 턴 기록 `stat_changes` 의 키·방 스냅숏 스탯 id 와 같은 값."""

    id: str
    name: str
    hidden_from_player: bool


def stat_def_entry(stat: StatDef) -> ExportStatDef:
    return ExportStatDef(id=str(stat.entity_id), name=stat.name, hidden_from_player=stat.hidden_from_player)


def chat_turn_row(turn: ChatTurn) -> dict[str, Any]:
    """행 객체의 칼럼 전부(칼럼 이름 → 값). 칼럼 목록을 모델에서 읽어, 칼럼이 늘어도 내보내기에서 빠지지 않는다."""
    return {column.key: getattr(turn, column.key) for column in ChatTurn.__table__.columns}


def prices_sha256() -> str:
    """지금 단가표 내용의 sha256(모델 id 로 정렬한 JSON)."""
    table = {model: asdict(price) for model, price in pricing.MODEL_PRICES.items()}
    return hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"턴 기록 칸 값을 JSON 으로 옮길 수 없다: {type(value).__name__}")


def export_text(
    *, room_id: str, exported_at: datetime, stat_defs: Sequence[ExportStatDef], rows: Sequence[Mapping[str, Any]]
) -> str:
    header = {
        "kind": EXPORT_KIND,
        "exportedAt": exported_at.isoformat(),
        "roomId": room_id,
        "scope": EXPORT_SCOPE,
        "pricesAsOf": pricing.PRICES_AS_OF.isoformat(),
        "pricesSha256": prices_sha256(),
        "statDefs": [
            {"id": stat.id, "name": stat.name, "hiddenFromPlayer": stat.hidden_from_player} for stat in stat_defs
        ],
    }
    lines = [header] + [{"kind": ROW_KIND, "row": dict(row)} for row in rows]
    return "".join(json.dumps(line, ensure_ascii=False, default=_plain) + "\n" for line in lines)


@dataclass(frozen=True)
class ChatTurnsExport:
    exported_at: str
    room_id: str
    scope: str
    prices_as_of: str
    prices_sha256: str
    stat_defs: list[ExportStatDef]
    rows: list[dict[str, Any]]
    # 읽지 못하고 건너뛴 줄의 (1부터 센 줄 번호, 까닭).
    problems: list[tuple[int, str]] = field(default_factory=list)


def parse_chat_turns(text: str) -> ChatTurnsExport:
    """머리 줄이 없거나 모양이 다르면 `ChatTurnsFormatError`. 그 뒤의 줄은 읽지 못해도 파일 전체를 버리지 않고 `problems` 에 남긴다
    — 행 하나가 깨졌다고 나머지 턴의 원가까지 감추지 않는다."""
    lines = text.splitlines()
    try:
        header = json.loads(lines[0]) if lines else None
    except json.JSONDecodeError as error:
        raise ChatTurnsFormatError("턴 기록 파일의 첫 줄을 읽을 수 없다") from error
    if not isinstance(header, dict) or header.get("kind") != EXPORT_KIND:
        raise ChatTurnsFormatError("턴 기록 파일의 첫 줄이 내보내기 머리 줄이 아니다")
    try:
        stat_defs = [
            ExportStatDef(id=str(s["id"]), name=str(s["name"]), hidden_from_player=bool(s["hiddenFromPlayer"]))
            for s in header["statDefs"]
        ]
        export = ChatTurnsExport(
            exported_at=str(header["exportedAt"]),
            room_id=str(header["roomId"]),
            scope=str(header["scope"]),
            prices_as_of=str(header["pricesAsOf"]),
            prices_sha256=str(header["pricesSha256"]),
            stat_defs=stat_defs,
            rows=[],
        )
    except (KeyError, TypeError) as error:
        raise ChatTurnsFormatError("턴 기록 머리 줄에 빠진 칸이 있다") from error
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            export.problems.append((number, "JSON 으로 읽을 수 없다"))
            continue
        if not isinstance(record, dict) or record.get("kind") != ROW_KIND or not isinstance(record.get("row"), dict):
            export.problems.append((number, "행 줄이 아니다"))
            continue
        export.rows.append(record["row"])
    return export


def read_chat_turns(path: Path) -> ChatTurnsExport:
    return parse_chat_turns(path.read_text(encoding="utf-8"))
