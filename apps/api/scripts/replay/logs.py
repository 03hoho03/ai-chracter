"""측정 드라이버 로그(`--log`·`--snapshot-log`)와 서버 프롬프트 덤프 읽기 — 리플레이가 지난 턴의 상태를 되살리는 출처.

DB 에는 요약·기억 노트·스탯의 지금 값만 남으므로, 턴 N 직전 값은 드라이버가 그때 남긴 줄에서 읽는다. 여기 규칙은
드라이버가 줄을 쓰는 방식(`scripts/chat_play.py`)에 맞춰져 있다:

- 턴 번호는 서버 턴 수 + 1 이다. 덤프의 `turn`, 드라이버 턴 줄의 `clientTurn`, 기억 스냅숏의 `turn` 이 모두 이 번호다.
- 스탯은 판정 뒤 값만 남는다(`roomAfter`). 생성은 판정보다 먼저라 턴 N 은 턴 N−1 을 마친 뒤의 값으로 조립됐다 — 그래서
  `roomAfter.turnCount == N−1` 인 마지막 줄을 쓴다. 유실 턴 뒤에는 다시 기준을 잡은 줄이, 첫 턴에는 오프닝 줄이 그 줄이다.
  완료 없이 끝난 턴 줄(전송 실패·생성 오류)은 `roomAfter` 가 비어 출처가 되지 않고, 그 줄의 `partialReply` 는 보지 않는다.
- 기억 노트·요약 본문은 바뀐 턴에만 스냅숏이 남는다. 턴 N 이하의 마지막 스냅숏이 그 턴에 보낸 값이다. 유실 턴과 그
  재시도 사이에 노트를 바꾸면 같은 턴 번호의 스냅숏이 둘 생기므로 파일 순서로 마지막 것을 쓴다.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from replay.room_fixed import RoomFixed

# 스탯 기준이 되는 줄 — 드라이버가 누적 기준을 다시 읽는 종류와 같고, 턴 줄을 더한다.
STAT_SOURCE_KINDS = ("opening", "turn", "rebase", "check")
NO_FIXED_RECORD = "고정값 기록 없음"


class ReplayRefusedError(Exception):
    """이 턴(또는 이 방)은 리플레이하지 않는다. 되살린 상태를 믿을 수 없을 때 조용히 비슷한 값으로 채우지 않고 멈춘다 —
    틀린 입력으로 만든 응답은 쌍 판정에서 버전 차이처럼 보인다."""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass(frozen=True)
class DriverLogs:
    """한 방의 드라이버 줄(파일 순서 그대로). `lines` 는 `--log`, `snapshots` 는 `--snapshot-log` 이다."""

    room_id: uuid.UUID
    lines: list[dict[str, Any]]
    snapshots: list[dict[str, Any]]


def load_driver_logs(log: Path, snapshot_log: Path, room_id: uuid.UUID) -> DriverLogs:
    room = str(room_id)
    return DriverLogs(
        room_id=room_id,
        lines=[r for r in _jsonl(log) if r.get("roomId") == room],
        snapshots=[r for r in _jsonl(snapshot_log) if r.get("roomId") == room],
    )


def dump_record(path: Path, room_id: uuid.UUID, turn: int) -> tuple[dict[str, Any], int]:
    """서버 덤프에서 그 방·그 턴의 마지막 기록과 기록 수. 유실 턴의 재시도와 재생성은 같은 턴 번호로 다시 덤프되고,
    DB 에 남은 응답은 마지막 시도의 것이다. 없으면 거부한다 — 덤프 없는 턴은 다시 조립한 입력을 대조할 기준이 없다."""
    found = [record for record in _jsonl(path) if record.get("roomId") == str(room_id) and record.get("turn") == turn]
    if not found:
        raise ReplayRefusedError(f"덤프에 턴 {turn} 이 없다")
    return found[-1], len(found)


def turn_line(logs: DriverLogs, turn: int) -> tuple[int, dict[str, Any]]:
    """턴 N 을 마친 턴 줄의 (파일 순번, 줄). 보통은 `roomAfter.turnCount == N` 인 첫 턴 줄이다(사람이 친 턴을 보충한 줄도
    같은 모양이다). 완료 이벤트를 못 받았지만 서버는 턴을 마친 경우(다음 실행이 다시 기준을 잡아 턴 수가 올라 있다)는
    그 번호의 마지막 턴 줄이다. 둘 다 없으면 이 로그로 그 턴을 알 수 없다."""
    for index, record in enumerate(logs.lines):
        if record.get("kind") == "turn" and (record.get("roomAfter") or {}).get("turnCount") == turn:
            return index, record
    attempts = [
        (index, record)
        for index, record in enumerate(logs.lines)
        if record.get("kind") == "turn" and record.get("clientTurn") == turn
    ]
    if not attempts:
        raise ReplayRefusedError(f"드라이버 로그에 턴 {turn} 줄이 없다")
    return attempts[-1]


def stats_line(logs: DriverLogs, turn: int) -> tuple[int, dict[str, Any]]:
    """턴 N 을 조립할 때의 스탯이 담긴 줄 — 턴 N 줄보다 앞에서 `roomAfter.turnCount == N−1` 인 마지막 줄."""
    end, _ = turn_line(logs, turn)
    found = [
        (index, record)
        for index, record in enumerate(logs.lines[:end])
        if record.get("kind") in STAT_SOURCE_KINDS
        and record.get("roomAfter")
        and record["roomAfter"].get("turnCount") == turn - 1
    ]
    if not found:
        raise ReplayRefusedError(f"턴 {turn} 앞에 턴 수 {turn - 1} 의 스탯 기준 줄이 없다")
    return found[-1]


def memory_snapshot(logs: DriverLogs, turn: int) -> dict[str, Any]:
    """턴 N 에 보낸 기억(노트·요약 본문) — 턴 N 이하 스냅숏 중 파일 순서로 마지막 것."""
    found = [
        record
        for record in logs.snapshots
        if record.get("kind") == "memorySnapshot" and record.get("turn") is not None and record["turn"] <= turn
    ]
    if not found:
        raise ReplayRefusedError(f"턴 {turn} 이하의 기억 스냅숏이 없다")
    return found[-1]


@dataclass(frozen=True)
class RoomStatic:
    """방의 `roomStatic` 기록 중 리플레이가 쓰는 것. `fixed` 는 고정값을 남기기 전의 옛 로그면 None 이다."""

    stat_ids: dict[str, str]
    shortcut_ids: dict[str, str]
    fixed: RoomFixed | None
    effective_chat_model: str | None


def room_static(logs: DriverLogs) -> RoomStatic:
    """`roomStatic` 은 방을 만들 때와 기준을 다시 잡을 때마다 다시 적힌다. 스탯·단축어 이름표와 방 고정값이 기록마다
    같아야 한다 — 드라이버는 실행 중 이것들을 바꾸지 않으므로, 다르면 측정 중 방 조건이 바뀐 것이고 어느 턴에 어느 값이
    걸렸는지 이 로그로 가릴 수 없다. 스탯 이름이 겹치면 이름으로 적힌 `roomAfter` 를 id 로 되돌릴 수 없어 거부한다."""
    records = [r for r in logs.snapshots if r.get("kind") == "roomStatic"]
    if not records:
        raise ReplayRefusedError("스냅숏 로그에 이 방의 roomStatic 이 없다")

    def key(record: dict[str, Any]) -> tuple[Any, ...]:
        fixed = RoomFixed.from_record(record)
        return (
            [(s["id"], s["name"]) for s in record.get("stats", [])],
            [(s["id"], s["name"]) for s in record.get("shortcuts", [])],
            fixed.as_record() if fixed is not None else None,
        )

    if any(key(record) != key(records[0]) for record in records):
        raise ReplayRefusedError("roomStatic 의 스탯·단축어·방 고정값이 기록마다 다르다")
    last = records[-1]
    stats = [(s["name"], s["id"]) for s in last.get("stats", [])]
    if len({name for name, _ in stats}) != len(stats):
        raise ReplayRefusedError("roomStatic 에 이름이 같은 스탯이 있다")
    return RoomStatic(
        stat_ids=dict(stats),
        shortcut_ids={s["name"]: s["id"] for s in last.get("shortcuts", [])},
        fixed=RoomFixed.from_record(last),
        effective_chat_model=last.get("effectiveChatModel"),
    )
