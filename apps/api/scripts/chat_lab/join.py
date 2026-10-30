"""한 묶음의 드라이버 로그·덤프·턴 기록을 턴 단위로 잇는다.

- 턴은 서로 다른 `clientTurn` 이고, 같은 번호의 턴 줄들은 그 턴의 시도(파일 순서)다. 사람이 친 턴을 나중에 보충한 줄은
  `clientTurn` 이 없어 `roomAfter.turnCount` 로 번호를 대신하고 보충 줄로 표시한다.
- 그 턴의 DB 응답인 시도는 생성 리플레이가 고르는 줄(`replay.logs.turn_line`)이다. 그 턴의 마지막 생성 덤프(고르는 규칙은
  `replay.logs.generation_records`)를 그 시도에 붙이고, 앞선 생성 덤프는 시도별로 가르지 않고 "앞선 생성 덤프"로 둔다 — 연결
  오류 시도는 서버에 닿았는지 모르고 HTTP 200 이어도 생성 앞에서 끝나면 덤프가 없어, n번째 시도와 n번째 덤프를 짝지으면
  틀릴 수 있다. 고른 시도가 서버 앞에서 거부된 것(HTTP 비200)이면 덤프가 없는 것이 정상이라 생성 덤프는 모두 앞선 것이다.
- 판정 덤프 줄은 (방, 턴)으로 그 턴에 순서대로 모두 붙인다. 백그라운드 줄은 턴 칸이 있으면 그 턴, 없으면 파일 순서상 바로 앞
  생성 줄의 턴에 둔다. 백그라운드 작업은 응답을 보낸 뒤 돌아 다음 턴 생성 줄보다 늦게 쓰일 수 있고 요약 접기 줄의 턴 칸은
  작업이 읽은 방 턴 수라 다음 턴이 먼저 커밋되면 하나 크므로, 어느 쪽이든 배치는 추정이라 줄마다 주의를 단다.
- 재생성·수정 줄은 `clientTurn` 이 없고 대상 턴은 `turnBefore` 다. 그 턴에 "응답 교체됨"으로 붙이고 타임라인 표지가 된다.
  기준 다시 잡기·대조·노트 저장·일시 정지 줄도 표지다.
- 턴 기록 행은 시도의 `assistantMessageId` 로 붙이고, 붙지 않는 행은 「짝 없는 기록」이다.
- 보이는 스탯은 드라이버 `roomAfter.stats`(이름 키), 턴 기록은 `stat_changes`(id 키)라, 방 스냅숏의 id↔이름 표로 양쪽에 다 있는
  스탯만 견준다. 숨김 스탯은 방 스냅숏에 없어 견주지 않는다(견주면 늘 "드라이버에 없음"인 거짓 불일치가 된다).

결합이 틀린 것(불일치)과 결합은 맞지만 알아야 하는 것(주의)을 따로 모은다. 조용히 버리는 줄은 없다 — 이 방의 덤프 줄과 턴
기록 행은 모두 어딘가에 붙거나 불일치로 남는다."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from chat_lab.bundles import Bundle, read_jsonl
from chat_lab.chat_turns_file import ChatTurnsExport, ChatTurnsFormatError, prices_sha256, read_chat_turns
from chat_lab.schemas import Caution, MarkerKind, Mismatch
from replay.logs import DriverLogs, ReplayRefusedError, generation_records, turn_line

# 드라이버 줄 종류 → 타임라인 표지 종류.
LINE_MARKERS: dict[str, MarkerKind] = {
    "rebase": "rebase",
    "check": "check",
    "noteUpdate": "noteUpdate",
    "pause": "pause",
}
REPLACEMENT_MARKERS: dict[str, MarkerKind] = {"regenerate": "regenerate", "edit": "edit"}
DUMP_KINDS = ("generation", "judgment", "background")
CHAT_TURNS_LABEL = "턴 기록 파일"


class UnsupportedBundleError(Exception):
    """이 묶음은 열지 않는다(옛 형식, 방 id 가 uuid 가 아닌 로그)."""


@dataclass
class Attempt:
    # 그 턴 안에서 1부터 센 시도 순번.
    index: int
    # 이 방 드라이버 줄(파일 순서) 안의 위치 — `replay.logs.turn_line` 이 돌려주는 순번과 같은 기준이다.
    line_index: int
    record: dict[str, Any]
    selected: bool = False
    generation_dump: dict[str, Any] | None = None
    chat_turn_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def server_rejected(self) -> bool:
        http = self.record.get("http")
        return isinstance(http, int) and http != 200


@dataclass(frozen=True)
class PlacedDump:
    record: dict[str, Any]
    placement: Literal["turnField", "previousGeneration"]


@dataclass
class Turn:
    number: int
    attempts: list[Attempt]
    supplemented: bool = False
    earlier_generation_dumps: list[dict[str, Any]] = field(default_factory=list)
    judgment_dumps: list[dict[str, Any]] = field(default_factory=list)
    background_dumps: list[PlacedDump] = field(default_factory=list)
    replacements: list[dict[str, Any]] = field(default_factory=list)

    @property
    def selected(self) -> Attempt:
        return next(attempt for attempt in self.attempts if attempt.selected)

    @property
    def replacement(self) -> dict[str, Any] | None:
        """이 턴의 응답을 마지막으로 바꾼 재생성·수정 줄(응답을 받은 것만). 실패한 교체는 응답을 바꾸지 않는다."""
        done = [
            r
            for r in self.replacements
            if r.get("http") == 200 and r.get("done") and isinstance(r.get("reply"), str) and r["reply"]
        ]
        return done[-1] if done else None


@dataclass(frozen=True)
class Marker:
    kind: MarkerKind
    turn: int
    record: dict[str, Any]


@dataclass
class JoinedRun:
    bundle: Bundle
    logs: DriverLogs
    meta: dict[str, Any] | None
    opening: dict[str, Any] | None
    room_statics: list[dict[str, Any]]
    turns: list[Turn]
    markers: list[Marker]
    # 이 방의 덤프 줄(방 id·프롬프트가 있는 줄, 파일 순서).
    dump_records: list[dict[str, Any]]
    # 덤프로 읽을 줄이 하나라도 있는 파일이 짝으로 있다 — 없으면 "덤프 없는 시도"를 세지 않는다.
    has_dump: bool
    chat_turns: ChatTurnsExport | None
    unmatched_rows: list[dict[str, Any]]
    # 보이는 스탯 id → 이름(`stat_name_table`).
    stat_names: dict[str, str]
    stat_comparisons: int
    mismatches: list[Mismatch]
    cautions: list[Caution]

    def turn(self, number: int) -> Turn:
        for turn in self.turns:
            if turn.number == number:
                return turn
        raise KeyError(number)


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _marker_turn(record: dict[str, Any]) -> int | None:
    """표지 줄을 쓸 때까지 마친 턴 수."""
    if record.get("kind") in ("noteUpdate", "pause"):
        return as_int(record.get("turnCount"))
    for key in ("roomAfter", "accumulated", "fetched"):
        after = record.get(key)
        if isinstance(after, dict) and as_int(after.get("turnCount")) is not None:
            return as_int(after.get("turnCount"))
    return None


def _is_dump_line(record: dict[str, Any]) -> bool:
    # 옛 덤프의 줄은 kind 칸이 없고 생성 줄로 읽는다(리플레이 규칙과 같다).
    return "roomId" in record and "prompt" in record and record.get("kind", "generation") in DUMP_KINDS


def _read_turns(lines: list[dict[str, Any]], mismatches: list[Mismatch]) -> tuple[dict[int, Turn], list[Marker]]:
    turns: dict[int, Turn] = {}
    markers: list[Marker] = []
    replacements: list[tuple[int, MarkerKind, dict[str, Any]]] = []
    for index, record in enumerate(lines):
        kind = str(record.get("kind"))
        if kind == "turn":
            number = as_int(record.get("clientTurn"))
            supplemented = number is None
            if number is None:
                after = record.get("roomAfter")
                number = as_int(after.get("turnCount")) if isinstance(after, dict) else None
            if number is None:
                mismatches.append(
                    Mismatch(
                        kind="unplacedLine", detail=f"방 줄 {index + 1}: clientTurn·roomAfter.turnCount 가 없는 턴 줄"
                    )
                )
                continue
            turn = turns.setdefault(number, Turn(number=number, attempts=[]))
            turn.supplemented = turn.supplemented or supplemented
            turn.attempts.append(Attempt(index=len(turn.attempts) + 1, line_index=index, record=record))
        elif kind in LINE_MARKERS:
            marker_turn = _marker_turn(record)
            if marker_turn is not None:
                markers.append(Marker(kind=LINE_MARKERS[kind], turn=marker_turn, record=record))
        elif kind in REPLACEMENT_MARKERS:
            replacements.append((index, REPLACEMENT_MARKERS[kind], record))
    for index, marker_kind, record in replacements:
        target = as_int(record.get("turnBefore"))
        if target is None or target not in turns:
            mismatches.append(
                Mismatch(
                    kind="unplacedLine", turn=target, detail=f"방 줄 {index + 1}: {marker_kind} 줄의 대상 턴이 없다"
                )
            )
            continue
        turns[target].replacements.append(record)
        markers.append(Marker(kind=marker_kind, turn=target, record=record))
    return turns, markers


def _select_attempts(logs: DriverLogs, turns: dict[int, Turn]) -> None:
    for number, turn in turns.items():
        try:
            line_index, _ = turn_line(logs, number)
        except ReplayRefusedError:
            line_index = turn.attempts[-1].line_index
        chosen = next((a for a in turn.attempts if a.line_index == line_index), turn.attempts[-1])
        chosen.selected = True


def _attach_dumps(
    room_id: uuid.UUID,
    records: list[dict[str, Any]],
    turns: dict[int, Turn],
    mismatches: list[Mismatch],
    cautions: list[Caution],
) -> None:
    for number, turn in turns.items():
        generations = generation_records(records, room_id, number)
        selected = turn.selected
        if selected.server_rejected:
            turn.earlier_generation_dumps = generations
        elif generations:
            selected.generation_dump = generations[-1]
            turn.earlier_generation_dumps = generations[:-1]
        elif selected.record.get("http") == 200:
            mismatches.append(Mismatch(kind="missingDump", turn=number, detail="응답을 받은 시도인데 생성 덤프가 없다"))
    last_generation: int | None = None
    for position, record in enumerate(records, start=1):
        kind = record.get("kind", "generation")
        line_turn = as_int(record.get("turn"))
        if kind == "generation":
            last_generation = line_turn
            if line_turn not in turns:
                mismatches.append(
                    Mismatch(
                        kind="unmatchedDumpLine",
                        turn=line_turn,
                        detail=f"이 방 덤프 줄 {position}: 그 턴이 없는 생성 줄",
                    )
                )
        elif kind == "judgment":
            if line_turn in turns:
                turns[line_turn].judgment_dumps.append(record)
            else:
                mismatches.append(
                    Mismatch(
                        kind="unmatchedDumpLine",
                        turn=line_turn,
                        detail=f"이 방 덤프 줄 {position}: 그 턴이 없는 판정 줄",
                    )
                )
        else:
            placement: Literal["turnField", "previousGeneration"] = (
                "turnField" if line_turn is not None else "previousGeneration"
            )
            target = line_turn if line_turn is not None else last_generation
            if target is None or target not in turns:
                mismatches.append(
                    Mismatch(
                        kind="unmatchedDumpLine",
                        turn=target,
                        detail=f"이 방 덤프 줄 {position}: 놓을 턴이 없는 백그라운드 줄",
                    )
                )
                continue
            turns[target].background_dumps.append(PlacedDump(record=record, placement=placement))
            why = (
                "턴 칸을 따랐다 — 응답 뒤에 돌아 다음 턴과 엇갈릴 수 있다"
                if placement == "turnField"
                else "턴 칸이 없어 파일 순서상 바로 앞 생성 줄의 턴에 놓았다"
            )
            cautions.append(
                Caution(kind="placementEstimated", turn=target, detail=f"백그라운드 {record.get('callSite')} 줄: {why}")
            )


def _attach_rows(export: ChatTurnsExport, turns: list[Turn], mismatches: list[Mismatch]) -> list[dict[str, Any]]:
    by_message: dict[str, Attempt] = {}
    for turn in turns:
        for attempt in turn.attempts:
            message_id = attempt.record.get("assistantMessageId")
            if isinstance(message_id, str):
                by_message[message_id] = attempt
    unmatched: list[dict[str, Any]] = []
    for row in export.rows:
        matched = by_message.get(str(row.get("assistant_message_id")))
        if matched is not None:
            matched.chat_turn_rows.append(row)
            continue
        unmatched.append(row)
        mismatches.append(
            Mismatch(
                kind="unmatchedRow",
                turn=as_int(row.get("turn_number")),
                detail=f"턴 기록 행({row.get('kind')})의 응답 id 가 어느 시도와도 맞지 않는다",
            )
        )
    return unmatched


def _stat_pairs(record: dict[str, Any]) -> list[tuple[str, str]]:
    """방 스냅숏 하나의 (스탯 id, 이름) — 보이는 스탯만 실린다."""
    stats = record.get("stats")
    return [
        (str(stat["id"]), str(stat["name"]))
        for stat in (stats if isinstance(stats, list) else [])
        if isinstance(stat, dict) and "id" in stat and "name" in stat
    ]


def stat_name_table(
    room_statics: list[dict[str, Any]], export: ChatTurnsExport | None
) -> tuple[dict[str, str], str | None]:
    """보이는 스탯 id → 이름. 드라이버는 스탯을 이름 키로만 남기므로 턴 기록(id 키)과 견주려면 이 표가 있어야 한다. 방 스냅숏이
    먼저이고, 스냅숏이 없거나 내보낸 스탯 정의(숨김 제외)에 스냅숏에 없는 스탯이 있으면 그 정의로 채운다 — 스냅숏 없는 묶음에서도
    보이는 스탯이 id 로 한 계열이 되고 대조가 돈다.

    두 번째 값은 이름 키를 id 로 되돌릴 수 없는 까닭이다(방 스냅숏마다 스탯 목록이 다르다, 이름이 같은 스탯이 있다). 그때는 어느
    턴에 어느 정의가 걸렸는지 가릴 수 없어, 부르는 쪽이 스탯 대조를 건너뛴다."""
    names: dict[str, str] = {}
    for record in room_statics:
        names.update(_stat_pairs(record))
    if export is not None:
        for stat in export.stat_defs:
            if not stat.hidden_from_player:
                names.setdefault(stat.id, stat.name)
    if len({frozenset(_stat_pairs(record)) for record in room_statics}) > 1:
        return names, "방 스냅숏마다 스탯 목록이 다르다"
    if len(set(names.values())) != len(names):
        return names, "이름이 같은 스탯이 있다"
    return names, None


def recorded_after(change: object) -> float | None:
    """턴 기록 `stat_changes` 한 칸(`[before, after]`)의 뒤 값."""
    return as_number(change[1]) if isinstance(change, list) and len(change) == 2 else None


def _compare_stats(
    turns: list[Turn],
    names: dict[str, str],
    export: ChatTurnsExport,
    room_statics: list[dict[str, Any]],
    mismatches: list[Mismatch],
) -> int:
    if export.stat_defs and room_statics:
        visible = {d.id: d.name for d in export.stat_defs if not d.hidden_from_player}
        if visible != dict(_stat_pairs(room_statics[-1])):
            mismatches.append(
                Mismatch(
                    kind="statMismatch",
                    detail="내보낸 스탯 정의(숨김 제외)와 방 스냅숏의 스탯 목록이 다르다 — 버전을 옮긴 방이면 정의가 섞였다",
                )
            )
    comparisons = 0
    for turn in turns:
        after = turn.selected.record.get("roomAfter")
        stats = after.get("stats") if isinstance(after, dict) else None
        if not isinstance(stats, dict):
            continue
        for row in turn.selected.chat_turn_rows:
            changes = row.get("stat_changes")
            for stat_id, change in (changes if isinstance(changes, dict) else {}).items():
                name = names.get(stat_id)
                driver = as_number(stats.get(name)) if name is not None else None
                recorded = recorded_after(change)
                if driver is None or recorded is None:
                    continue
                comparisons += 1
                if driver != recorded:
                    mismatches.append(
                        Mismatch(
                            kind="statMismatch",
                            turn=turn.number,
                            detail=f"{name}: 드라이버 {driver:g} · 턴 기록 {recorded:g}",
                        )
                    )
    return comparisons


def join_bundle(bundle: Bundle) -> JoinedRun:
    if not bundle.supported:
        raise UnsupportedBundleError(f"{bundle.path}: 턴 줄에 방 id 가 없는 옛 형식이라 열지 않는다")
    try:
        room_id = uuid.UUID(bundle.room_id)
    except ValueError as error:
        raise UnsupportedBundleError(f"{bundle.path}: 방 id 가 uuid 가 아니다") from error
    mismatches: list[Mismatch] = []
    cautions: list[Caution] = list(bundle.cautions)

    log_file = read_jsonl(bundle.log)
    cautions += log_file.cautions
    lines = [r for r in log_file.records if r.get("roomId") == bundle.room_id]
    snapshots: list[dict[str, Any]] = []
    if bundle.snapshots is not None:
        snapshot_file = read_jsonl(bundle.snapshots)
        cautions += snapshot_file.cautions
        snapshots = [r for r in snapshot_file.records if r.get("roomId") == bundle.room_id]
    logs = DriverLogs(room_id=room_id, lines=lines, snapshots=snapshots)
    room_statics = [r for r in snapshots if r.get("kind") == "roomStatic"]

    by_number, markers = _read_turns(lines, mismatches)
    _select_attempts(logs, by_number)
    numbers = sorted(by_number)
    turns = [by_number[n] for n in numbers]
    if numbers:
        present = set(numbers)
        mismatches += [
            Mismatch(kind="turnGap", turn=n, detail="이 턴 번호의 턴 줄이 없다")
            for n in range(numbers[0], numbers[-1] + 1)
            if n not in present
        ]

    dump_records: list[dict[str, Any]] = []
    has_dump = False
    if bundle.dump is not None:
        dump_file = read_jsonl(bundle.dump)
        cautions += dump_file.cautions
        shaped = [r for r in dump_file.records if _is_dump_line(r)]
        if len(shaped) < len(dump_file.records):
            cautions.append(
                Caution(
                    kind="notDumpLine",
                    detail=f"{bundle.dump.name} 에 방 id·프롬프트가 없는 줄 {len(dump_file.records) - len(shaped)}개 — 덤프 줄로 읽지 않았다",
                )
            )
        has_dump = bool(shaped)
        dump_records = [r for r in shaped if r.get("roomId") == bundle.room_id]
    if has_dump:
        _attach_dumps(room_id, dump_records, by_number, mismatches, cautions)

    export: ChatTurnsExport | None = None
    unmatched_rows: list[dict[str, Any]] = []
    stat_comparisons = 0
    if bundle.chat_turns is not None:
        try:
            export = read_chat_turns(bundle.chat_turns)
        except (ChatTurnsFormatError, UnicodeDecodeError) as error:
            cautions.append(Caution(kind="unreadableLine", detail=f"{bundle.chat_turns.name} 를 읽지 않았다: {error}"))
    if export is not None and export.room_id != bundle.room_id:
        # 다른 방의 행을 붙이면 응답 id 가 하나도 맞지 않아 행마다 「짝 없는 기록」이 되고 원가에도 섞인다 — 파일 째 쓰지 않는다.
        mismatches.append(
            Mismatch(
                kind="chatTurnsRoomMismatch", detail="턴 기록 파일의 방 id 가 이 묶음의 방과 달라 행을 붙이지 않았다"
            )
        )
        export = None
    stat_names, stat_trouble = stat_name_table(room_statics, export)
    if stat_trouble is not None:
        cautions.append(Caution(kind="statDefsChanged", detail=f"{stat_trouble} — 스탯 대조를 건너뛰었다"))
    if export is not None:
        cautions += [
            Caution(kind="unreadableLine", detail=f"{CHAT_TURNS_LABEL} {number}번째 줄: {why}")
            for number, why in export.problems
        ]
        if export.prices_sha256 != prices_sha256():
            cautions.append(
                Caution(
                    kind="pricesChanged",
                    detail=f"내보낸 때(기준일 {export.prices_as_of})와 단가표가 다르다 — 원가는 지금 단가표로 냈다",
                )
            )
        unmatched_rows = _attach_rows(export, turns, mismatches)
        if stat_trouble is None:
            stat_comparisons = _compare_stats(turns, stat_names, export, room_statics, mismatches)

    mismatches.sort(key=lambda m: (m.turn is None, m.turn or 0))
    return JoinedRun(
        bundle=bundle,
        logs=logs,
        meta=next((r for r in lines if r.get("kind") == "meta"), None),
        opening=next((r for r in lines if r.get("kind") == "opening"), None),
        room_statics=room_statics,
        turns=turns,
        markers=markers,
        dump_records=dump_records,
        has_dump=has_dump,
        chat_turns=export,
        unmatched_rows=unmatched_rows,
        stat_names=stat_names,
        stat_comparisons=stat_comparisons,
        mismatches=mismatches,
        cautions=cautions,
    )
