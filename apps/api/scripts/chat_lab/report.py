"""이은 묶음(`JoinedRun`)에서 응답 모델을 만든다 — 런 목록 항목, 런 상세(턴 요약·상태 계열·표지·원가), 턴 상세, 지표.

- 지표는 대화록 분석의 `reply_flags(reply, previous)` 를 턴마다 부른다. `previous` 는 앞 턴 가운데 응답이 있는 마지막 턴의 응답
  — 그 턴에 DB 응답으로 고른 시도의 응답이고, 재생성·수정으로 바뀌었으면 바뀐 뒤 응답이다 — 이고, 첫 턴은 오프닝 마지막
  메시지다. 유실 시도의 조각(`partialReply`)은 쓰지 않는다. 지표와 화면이 같은 응답을 가리켜야 해서다. 되받기는 내지 않는다
  (고정 대본의 턴 순번 키워드에 묶여 있어 자유 발화에는 뜻이 없다).
- 원가는 턴 기록 호출 칸마다 `api.llm.pricing.call_cost` 를 부른 합이다. 첫 토큰 지연은 생성 호출 칸에만 있다.
- 기록 한계는 화면이 사실대로 말하도록 문장으로 함께 싣는다."""

import statistics
from datetime import datetime
from typing import Any

from analyze_chat_probe import ReplyFlags, is_monotonic_shrinking, reply_flags
from api.llm.pricing import call_cost
from chat_lab.bundles import Bundle
from chat_lab.join import JoinedRun, Turn, as_int, as_number, join_bundle, recorded_after
from chat_lab.schemas import (
    AttemptDetail,
    BackgroundDump,
    CallCostView,
    ChatTurnRecord,
    DriverStatChange,
    RecordedStatChange,
    ReplyFlagsView,
    RunBundle,
    RunCost,
    RunDetail,
    RunListItem,
    RunMetrics,
    SeriesPoint,
    StatSeries,
    TimelineMarker,
    TurnDetail,
    TurnMetrics,
    PreviousFrom,
    TurnSummary,
    UnmatchedRow,
)
from replay.logs import ReplayRefusedError, memory_snapshot

JUDGMENT_RESULT_LIMIT = (
    "판정 응답 원문은 기록되지 않음 — 판정 결과는 드라이버의 스탯 변화·엔딩과 턴 기록의 스탯 전후로 대신 보인다"
)
LATENCY_LIMIT = "지연은 생성 호출에만 기록된다 — 판정·임베딩 호출의 지연은 기록 없음"
BACKGROUND_LIMIT = "백그라운드 호출은 프롬프트만 덤프에 남는다 — 토큰·원가는 기록 없음"
EXPORT_NEEDED_LIMIT = "턴 기록 파일(chat-turns.jsonl)이 없어 토큰·원가는 내보내기 필요"
NO_DUMP_LIMIT = "이 묶음에는 프롬프트 덤프가 없어 프롬프트·지시문 원문이 없다"
REPLY_HEAD_CHARS = 200
# 시각을 읽는 드라이버 줄 칸 — 줄 종류마다 이름이 다르다(meta 는 createdAt, 턴은 sentAt, 보충 줄은 createdAt, 나머지는 at).
_TIME_KEYS = ("createdAt", "sentAt", "at")


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _calls(row: dict[str, Any]) -> list[dict[str, Any]]:
    calls = row.get("llm_calls")
    return [call for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []


def call_view(call: dict[str, Any]) -> CallCostView:
    cost = call_cost(call)
    return CallCostView(
        call_site=cost.call_site,
        model=cost.model,
        prompt_tokens=as_int(call.get("promptTokens")),
        cached_tokens=as_int(call.get("cachedTokens")),
        cache_write_tokens=as_int(call.get("cacheWriteTokens")),
        output_tokens=as_int(call.get("outputTokens")),
        thoughts_tokens=as_int(call.get("thoughtsTokens")),
        usd=cost.usd,
        missing_tokens=cost.missing_tokens,
        first_token_ms=as_int(call.get("firstTokenMs")),
        stream_first_token_ms=as_int(call.get("streamFirstTokenMs")),
    )


def row_cost(row: dict[str, Any]) -> float:
    """행 하나의 원가 합(단가 없는 모델의 칸은 뺀다 — 몇 칸인지는 `RunCost.unpriced_calls` 가 센다)."""
    return sum(cost.usd for cost in (call_cost(call) for call in _calls(row)) if cost.usd is not None)


def _turn_rows(turn: Turn) -> list[dict[str, Any]]:
    return [row for attempt in turn.attempts for row in attempt.chat_turn_rows]


def run_cost(joined: JoinedRun) -> RunCost | None:
    """런 원가. 시도에 붙은 행만 합하고 「짝 없는 기록」의 원가는 따로 낸다."""
    export = joined.chat_turns
    if export is None:
        return None
    total = 0.0
    unpriced = missing = 0
    for turn in joined.turns:
        for row in _turn_rows(turn):
            for call in _calls(row):
                cost = call_cost(call)
                if cost.usd is None:
                    unpriced += 1
                else:
                    total += cost.usd
                missing += cost.missing_tokens
    return RunCost(
        total_usd=total,
        unmatched_usd=sum(row_cost(row) for row in joined.unmatched_rows),
        unpriced_calls=unpriced,
        missing_token_calls=missing,
        prices_as_of_export=export.prices_as_of,
        prices_sha256_export=export.prices_sha256,
        prices_changed=any(c.kind == "pricesChanged" for c in joined.cautions),
    )


def _times(joined: JoinedRun) -> tuple[str | None, str | None]:
    stamps: list[tuple[datetime, str]] = []
    for record in joined.logs.lines:
        for key in _TIME_KEYS:
            text = _str(record.get(key))
            if text is None:
                continue
            try:
                stamps.append((datetime.fromisoformat(text), text))
            except ValueError:
                continue
    if not stamps:
        return None, None
    try:
        stamps.sort(key=lambda stamp: stamp[0])
    except TypeError:
        # 시간대가 있는 시각과 없는 시각이 섞이면 견줄 수 없다 — 파일 순서의 처음과 끝을 쓴다.
        pass
    return stamps[0][1], stamps[-1][1]


def run_list_item(bundle: Bundle, joined: JoinedRun | None) -> RunListItem:
    """`joined` 가 없으면(열지 않는 형식, 아직 열지 않은 묶음) 묶음을 찾을 때 안 것만 싣는다."""
    base = RunListItem(
        run_id=bundle.run_id,
        path=bundle.path,
        group=bundle.group,
        format=bundle.format,
        supported=bundle.supported,
        room_id=bundle.room_id,
        has_snapshots=bundle.snapshots is not None,
        has_dump=bundle.dump is not None,
        has_chat_turns=bundle.chat_turns is not None,
    )
    if joined is None:
        return base
    started, ended = _times(joined)
    cost = run_cost(joined)
    return base.model_copy(
        update={
            "story_name": _str((joined.meta or {}).get("storyName")),
            "turn_count": len(joined.turns),
            "started_at": started,
            "ended_at": ended,
            "effective_chat_models": sorted(
                {m for m in (_str(r.get("effectiveChatModel")) for r in joined.room_statics) if m is not None}
            ),
            "generation_models": sorted(
                {
                    model
                    for model in (
                        _str(r.get("model")) for r in joined.dump_records if r.get("kind", "generation") == "generation"
                    )
                    if model is not None
                }
            ),
            "cost_usd": cost.total_usd if cost is not None else None,
            "unpriced_calls": cost.unpriced_calls if cost is not None else None,
            "has_dump": joined.has_dump,
            "has_chat_turns": joined.chat_turns is not None,
            "mismatch_count": len(joined.mismatches),
            "caution_count": len(joined.cautions),
        }
    )


def list_entry(bundle: Bundle) -> RunListItem:
    """목록 한 줄 — 묶음을 열어(지원하는 형식만) 항목을 만든다. 열다 실패하면(파일을 못 읽음, 줄의 칸 타입이 예상과 다름 등)
    그 묶음만 "열 수 없음"으로 싣고 까닭을 남긴다. 측정 기록은 사람이 고치거나 기록 중에 끊긴 파일이라 어떤 모양이든 올 수 있고,
    묶음 하나의 예외가 목록 전체를 막으면 나머지 런도 볼 수 없다."""
    if not bundle.supported:
        return run_list_item(bundle, None)
    try:
        return run_list_item(bundle, join_bundle(bundle))
    except Exception as error:  # 묶음 하나의 어떤 실패도 목록 밖으로 내보내지 않는다(위 까닭).
        return run_list_item(bundle, None).model_copy(update={"open_error": f"{type(error).__name__}: {error}"})


def _stat_labels(joined: JoinedRun) -> dict[str, tuple[str | None, bool | None]]:
    """스탯 id → (이름, 숨김 여부). 내보낸 스탯 정의가 먼저고, 없으면 방 스냅숏(보이는 스탯만 실린다)."""
    labels: dict[str, tuple[str | None, bool | None]] = {
        stat_id: (name, False) for stat_id, name in joined.stat_names.items()
    }
    if joined.chat_turns is not None:
        for stat in joined.chat_turns.stat_defs:
            labels[stat.id] = (stat.name, stat.hidden_from_player)
    return labels


def _recorded_changes(joined: JoinedRun, turn: Turn) -> list[RecordedStatChange]:
    labels = _stat_labels(joined)
    changes: list[RecordedStatChange] = []
    for row in turn.selected.chat_turn_rows:
        stat_changes = row.get("stat_changes")
        for stat_id, change in (stat_changes if isinstance(stat_changes, dict) else {}).items():
            name, hidden = labels.get(stat_id, (None, None))
            before = as_number(change[0]) if isinstance(change, list) and len(change) == 2 else None
            changes.append(
                RecordedStatChange(id=stat_id, name=name, hidden=hidden, before=before, after=recorded_after(change))
            )
    return changes


def _driver_changes(record: dict[str, Any]) -> list[DriverStatChange]:
    changes = record.get("statChanges")
    out: list[DriverStatChange] = []
    for change in changes if isinstance(changes, list) else []:
        value = as_number(change.get("value")) if isinstance(change, dict) else None
        name = _str(change.get("name")) if isinstance(change, dict) else None
        if name is not None and value is not None:
            out.append(DriverStatChange(name=name, value=value))
    return out


def turn_summary(joined: JoinedRun, turn: Turn) -> TurnSummary:
    record = turn.selected.record
    reply = _str(record.get("reply")) or ""
    ending = record.get("ending")
    return TurnSummary(
        turn=turn.number,
        attempt_count=len(turn.attempts),
        supplemented=turn.supplemented,
        replaced=turn.replacement is not None,
        lost=not reply and turn.replacement is None,
        user_text=_str(record.get("userText")),
        shortcut=_str(record.get("shortcut")),
        reply_head=reply[:REPLY_HEAD_CHARS],
        reply_length=len(reply),
        driver_stat_changes=_driver_changes(record),
        recorded_stat_changes=_recorded_changes(joined, turn),
        ending=ending if isinstance(ending, dict) else None,
        failure=_str(record.get("failure")),
        earlier_generation_dumps=len(turn.earlier_generation_dumps),
        judgment_dumps=len(turn.judgment_dumps),
        background_dumps=len(turn.background_dumps),
        cost_usd=sum(row_cost(row) for row in _turn_rows(turn)) if joined.chat_turns is not None else None,
        mismatch_count=sum(1 for m in joined.mismatches if m.turn == turn.number),
    )


def stat_series(joined: JoinedRun) -> list[StatSeries]:
    """보이는 스탯은 드라이버 `roomAfter` 에서(방 스냅숏 이름 → id), 그 밖의 스탯(숨김)은 턴 기록에서."""
    names = joined.stat_names
    ids_by_name = {name: stat_id for stat_id, name in names.items()}
    labels = _stat_labels(joined)
    series: dict[str, StatSeries] = {
        stat_id: StatSeries(id=stat_id, name=name, hidden=False, source="driver", points=[])
        for stat_id, name in names.items()
    }
    for turn in joined.turns:
        after = turn.selected.record.get("roomAfter")
        stats = after.get("stats") if isinstance(after, dict) else None
        for key, value in (stats if isinstance(stats, dict) else {}).items():
            number = as_number(value)
            if number is None:
                continue
            # 드라이버는 정의를 모르는 스탯을 id 그대로 키로 싣는다.
            name = str(key)
            stat_id = ids_by_name.get(name, name)
            entry = series.setdefault(
                stat_id, StatSeries(id=stat_id, name=name, hidden=False, source="driver", points=[])
            )
            entry.points.append(SeriesPoint(turn=turn.number, value=number))
    for turn in joined.turns:
        for row in _turn_rows(turn):
            changes = row.get("stat_changes")
            for stat_id, change in (changes if isinstance(changes, dict) else {}).items():
                after_value = recorded_after(change)
                if stat_id in names or after_value is None:
                    continue
                label, hidden = labels.get(stat_id, (None, None))
                entry = series.setdefault(
                    stat_id,
                    StatSeries(id=stat_id, name=label or stat_id, hidden=hidden, source="chatTurns", points=[]),
                )
                entry.points.append(SeriesPoint(turn=turn.number, value=after_value))
    return [entry for entry in series.values() if entry.points]


def _line_marker_detail(kind: str, record: dict[str, Any]) -> str | None:
    if kind == "rebase":
        return _str(record.get("reason"))
    if kind == "check":
        return "누적값과 조회값이 같다" if record.get("ok") else "누적값과 조회값이 다르다"
    return None


def markers(joined: JoinedRun) -> list[TimelineMarker]:
    found = [
        TimelineMarker(kind=m.kind, turn=m.turn, detail=_line_marker_detail(m.kind, m.record)) for m in joined.markers
    ]
    previous_memory: dict[str, Any] | None = None
    for turn in joined.turns:
        record = turn.selected.record
        ending = record.get("ending")
        if isinstance(ending, dict):
            found.append(TimelineMarker(kind="ending", turn=turn.number, detail=_str(ending.get("name"))))
        failures = [a.record.get("failure") or "완료 없음" for a in turn.attempts if not a.record.get("done")]
        if failures:
            found.append(TimelineMarker(kind="failure", turn=turn.number, detail=str(failures[0])))
        memory = record.get("memory")
        if isinstance(memory, dict):
            if previous_memory is not None and memory.get("noteSha") != previous_memory.get("noteSha"):
                found.append(TimelineMarker(kind="noteChange", turn=turn.number))
            if previous_memory is not None and memory.get("summarySha") != previous_memory.get("summarySha"):
                found.append(TimelineMarker(kind="summaryUpdate", turn=turn.number))
            previous_memory = memory
    return sorted(found, key=lambda marker: marker.turn)


def run_detail(joined: JoinedRun) -> RunDetail:
    cost = run_cost(joined)
    return RunDetail(
        run=run_list_item(joined.bundle, joined),
        meta=joined.meta,
        room_static=joined.room_statics[-1] if joined.room_statics else None,
        turns=[turn_summary(joined, turn) for turn in joined.turns],
        series=stat_series(joined),
        markers=markers(joined),
        stat_comparisons=joined.stat_comparisons,
        cost=cost,
        unmatched_rows=[
            UnmatchedRow(
                assistant_message_id=_str(row.get("assistant_message_id")),
                kind=_str(row.get("kind")),
                turn_number=as_int(row.get("turn_number")),
                cost_usd=row_cost(row),
            )
            for row in joined.unmatched_rows
        ],
        mismatches=joined.mismatches,
        cautions=joined.cautions,
    )


def flags_view(flags: ReplyFlags) -> ReplyFlagsView:
    return ReplyFlagsView(
        length=flags.length,
        sentence_count=flags.sentence_count,
        truncated=flags.truncated,
        self_copy=flags.self_copy,
        solicit=flags.solicit,
        ignored=flags.ignored,
        scene_open=flags.scene_open,
        label_leak=flags.label_leak,
        user_turn=flags.user_turn,
        broken=flags.broken,
        brackets=list(flags.brackets),
    )


def _opening_text(joined: JoinedRun) -> str | None:
    messages = (joined.opening or {}).get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[-1], str):
        return messages[-1]
    return None


def run_metrics(joined: JoinedRun) -> RunMetrics:
    opening = _opening_text(joined)
    previous = opening or ""
    previous_from: PreviousFrom = "opening" if opening is not None else "none"
    previous_turn: int | None = None
    turns: list[TurnMetrics] = []
    lost = 0
    for turn in joined.turns:
        reply = _str(turn.selected.record.get("reply")) or ""
        if reply:
            turns.append(
                TurnMetrics(
                    turn=turn.number,
                    flags=flags_view(reply_flags(reply, previous)),
                    previous_from=previous_from,
                    previous_turn=previous_turn,
                )
            )
            previous, previous_from, previous_turn = reply, "turn", turn.number
        else:
            lost += 1
        replacement = turn.replacement
        if replacement is not None:
            previous, previous_from, previous_turn = str(replacement["reply"]), "replacement", turn.number
    lengths = [m.flags.length for m in turns]
    return RunMetrics(
        scored=len(turns),
        lost=lost,
        truncated=sum(m.flags.truncated for m in turns),
        self_copy=sum(m.flags.self_copy for m in turns),
        solicit=sum(m.flags.solicit for m in turns),
        ignored=sum(m.flags.ignored for m in turns),
        scene_open=sum(m.flags.scene_open for m in turns),
        label_leak=sum(m.flags.label_leak for m in turns),
        user_turn=sum(m.flags.user_turn for m in turns),
        broken=sum(m.flags.broken is not None for m in turns),
        brackets=sum(bool(m.flags.brackets) for m in turns),
        median_length=statistics.median(lengths) if lengths else None,
        median_sentences=statistics.median(m.flags.sentence_count for m in turns) if turns else None,
        length_non_increasing=is_monotonic_shrinking(lengths) if lengths else None,
        turns=turns,
    )


def turn_detail(joined: JoinedRun, number: int, *, metrics: RunMetrics | None = None) -> TurnDetail:
    """없는 턴이면 `KeyError`. `metrics` 는 이미 낸 런 지표 — 턴마다 런 지표를 다시 내지 않게 묶음 전체를 낼 때 넘긴다."""
    turn = joined.turn(number)
    try:
        snapshot: dict[str, Any] | None = memory_snapshot(joined.logs, number)
    except ReplayRefusedError:
        snapshot = None
    limits = [JUDGMENT_RESULT_LIMIT, LATENCY_LIMIT]
    if turn.background_dumps:
        limits.append(BACKGROUND_LIMIT)
    if joined.chat_turns is None:
        limits.append(EXPORT_NEEDED_LIMIT)
    if not joined.has_dump:
        limits.append(NO_DUMP_LIMIT)
    return TurnDetail(
        turn=turn.number,
        supplemented=turn.supplemented,
        replaced=turn.replacement is not None,
        attempts=[
            AttemptDetail(
                index=attempt.index,
                selected=attempt.selected,
                server_rejected=attempt.server_rejected,
                record=attempt.record,
                generation_dump=attempt.generation_dump,
                chat_turns=[
                    ChatTurnRecord(row=row, calls=[call_view(call) for call in _calls(row)], cost_usd=row_cost(row))
                    for row in attempt.chat_turn_rows
                ],
            )
            for attempt in turn.attempts
        ],
        earlier_generation_dumps=turn.earlier_generation_dumps,
        judgment_dumps=turn.judgment_dumps,
        background_dumps=[BackgroundDump(record=b.record, placement=b.placement) for b in turn.background_dumps],
        replacements=turn.replacements,
        memory_snapshot=snapshot,
        memory_snapshot_changed_here=snapshot is not None and snapshot.get("turn") == number,
        metrics=next(
            (m for m in (metrics if metrics is not None else run_metrics(joined)).turns if m.turn == number), None
        ),
        mismatches=[m for m in joined.mismatches if m.turn == number],
        cautions=[c for c in joined.cautions if c.turn == number],
        record_limits=limits,
    )


# 원문 없는 묶음에서 키째 빼는 칸 — 덤프 줄의 프롬프트·지시문, 기억 스냅숏의 노트·요약 본문.
RAW_DUMP_KEYS = frozenset({"prompt", "systemInstruction"})
RAW_SNAPSHOT_KEYS = frozenset({"note", "summary"})


def _without(record: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in keys}


def _without_raw(detail: TurnDetail) -> TurnDetail:
    snapshot = detail.memory_snapshot
    return detail.model_copy(
        update={
            "attempts": [
                attempt.model_copy(
                    update={
                        "generation_dump": None
                        if attempt.generation_dump is None
                        else _without(attempt.generation_dump, RAW_DUMP_KEYS)
                    }
                )
                for attempt in detail.attempts
            ],
            "earlier_generation_dumps": [_without(r, RAW_DUMP_KEYS) for r in detail.earlier_generation_dumps],
            "judgment_dumps": [_without(r, RAW_DUMP_KEYS) for r in detail.judgment_dumps],
            "background_dumps": [
                b.model_copy(update={"record": _without(b.record, RAW_DUMP_KEYS)}) for b in detail.background_dumps
            ],
            "memory_snapshot": None if snapshot is None else _without(snapshot, RAW_SNAPSHOT_KEYS),
        }
    )


def run_bundle(joined: JoinedRun, *, raw: bool) -> RunBundle:
    """런 상세·지표·모든 턴 상세. 정적 HTML 이 결합·지표를 따로 다시 계산하지 않게 서버가 낸 값을 그대로 싣는다."""
    metrics = run_metrics(joined)
    turns = [turn_detail(joined, turn.number, metrics=metrics) for turn in joined.turns]
    return RunBundle(
        raw=raw,
        detail=run_detail(joined),
        metrics=metrics,
        turns=turns if raw else [_without_raw(turn) for turn in turns],
    )
