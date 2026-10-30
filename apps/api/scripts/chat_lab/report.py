"""이은 묶음(`JoinedRun`)에서 응답 모델을 만든다 — 런 목록 항목, 런 상세(턴 요약·상태 계열·표지·원가), 턴 상세, 지표.

- 지표는 대화록 분석의 `reply_flags(reply, previous)` 를 턴마다 부른다. `previous` 는 앞 턴 가운데 응답이 있는 마지막 턴의 응답
  — 그 턴에 DB 응답으로 고른 시도의 응답이고, 재생성·수정으로 바뀌었으면 바뀐 뒤 응답이다 — 이고, 첫 턴은 오프닝 마지막
  메시지다. 유실 시도의 조각(`partialReply`)은 쓰지 않는다. 지표와 화면이 같은 응답을 가리켜야 해서다. 되받기는 내지 않는다
  (고정 대본의 턴 순번 키워드에 묶여 있어 자유 발화에는 뜻이 없다). 턴 요약의 플래그는 이 지표의 같은 턴 칸을 그대로 싣는다.
- 드라이버 스탯 변화의 시작 값은 리플레이가 그 턴을 조립할 때 읽는 스탯 줄(`replay.logs.stats_line`)에서 얻는다(규칙은
  `DriverStatChange`).
- 원가는 턴 기록 호출 칸마다 `api.llm.pricing.call_cost` 를 부른 합이다 — 원가 리포트들과 같은 합이다. 원가를 모르는 자리는 0 이
  아니라 비운다: 단가 없는 호출과 입력 토큰이 기록되지 않은 호출의 호출 원가, 턴 기록 행이 붙지 않은 턴의 턴 원가. 그런 호출이
  섞인 합은 하한이라고 표시한다. 첫 토큰 지연은 생성 호출 칸에만 있다.
- 기록 한계는 화면이 사실대로 말하도록 문장과 그 문장이 대신 서는 자리를 함께 싣는다."""

import statistics
from datetime import datetime
from typing import Any

from analyze_chat_probe import ReplyFlags, is_monotonic_shrinking, reply_flags
from api.chat.memory_embeddings import EMBEDDING_CALL_SITE
from api.chat.memory_vector import QUERY_EMBEDDING_CALL_SITE
from api.llm.call_policy import CALL_POLICIES, CallPolicy
from api.llm.pricing import call_cost
from chat_lab.bundles import Bundle
from chat_lab.join import JoinedRun, Turn, as_int, as_number, join_bundle, recorded_after
from chat_lab.schemas import (
    AttemptDetail,
    BackgroundDump,
    CallCostView,
    CallSiteKind,
    ChatTurnRecord,
    DriverStatChange,
    RecordedStatChange,
    RecordLimit,
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
from replay.logs import ReplayRefusedError, memory_snapshot, stats_line

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


# 호출 정책 표에 없는 임베딩 호출 이름 — 질의 임베딩(턴 기록 호출 칸에 실린다)과 저장 임베딩. Voyage 호출은 그 표에 넣지 않는다.
_EMBEDDING_CALL_SITES = frozenset({QUERY_EMBEDDING_CALL_SITE, EMBEDDING_CALL_SITE})
# 기록의 call_site 는 그냥 문자열이라 표를 문자열 키로 찾는다.
_CALL_POLICIES: dict[str, CallPolicy] = {site: policy for site, policy in CALL_POLICIES.items()}


def call_site_kind(call_site: str) -> CallSiteKind:
    """호출 종류. 임베딩은 표 밖 이름으로, 나머지는 호출 정책 표(`api.llm.call_policy`)의 행으로 가른다 — 스트리밍으로 부르는
    호출이 생성, 판정 종류가 있는 호출이 판정(어드민 판정 비율이 세는 집합과 같다), 판정 종류 없이 모델 설정이 있는 호출이
    백그라운드다. 표가 모델 설정을 판정 종류마다와 기억 요약·추출·인상에만 두므로 마지막 갈래는 그 넷이고, 넷 모두 응답을 보낸
    뒤 요약 접기에서 돈다. 표에 없는 이름과 그 밖의 행(심사·시드·소설 구조화, 판정 종류가 없는 정본 기억 추출·판정)은 `other` 다."""
    if call_site in _EMBEDDING_CALL_SITES:
        return "embedding"
    policy = _CALL_POLICIES.get(call_site)
    if policy is None:
        return "other"
    if policy.call_kind == "stream":
        return "generation"
    if policy.judgment_kind is not None:
        return "judgment"
    if policy.model_setting is not None:
        return "background"
    return "other"


def new_input_tokens(call: dict[str, Any]) -> int | None:
    """정가로 치는 입력 토큰 — 입력 − 캐시 읽기 − 캐시 쓰기, 음수면 0. 단가 함수(`api.llm.pricing.estimate_cost_usd`)가 입력 정가를
    곱하는 몫과 같은 전제다: 입력 토큰은 캐시 읽기·쓰기를 포함한 전체이고(Claude 는 빼고 보고하지만 공급자 모듈이 셋을 더해
    기록한다 — `api.llm.claude_messages.to_usage`), 비어 있는 캐시 칸은 0 으로 친다. 다른 점은 입력 토큰이 기록되지 않은
    호출뿐이다 — 단가 함수는 0 으로 치지만 여기는 None 이다(0 이면 새 입력이 없었던 호출로 읽힌다)."""
    prompt = as_int(call.get("promptTokens"))
    if prompt is None:
        return None
    cached = as_int(call.get("cachedTokens")) or 0
    cache_write = as_int(call.get("cacheWriteTokens")) or 0
    return max(prompt - cached - cache_write, 0)


def call_view(call: dict[str, Any]) -> CallCostView:
    cost = call_cost(call)
    return CallCostView(
        call_site=cost.call_site,
        kind=call_site_kind(cost.call_site),
        model=cost.model,
        prompt_tokens=as_int(call.get("promptTokens")),
        cached_tokens=as_int(call.get("cachedTokens")),
        cache_write_tokens=as_int(call.get("cacheWriteTokens")),
        output_tokens=as_int(call.get("outputTokens")),
        thoughts_tokens=as_int(call.get("thoughtsTokens")),
        new_input_tokens=new_input_tokens(call),
        # 단가 함수는 없는 입력 토큰을 0 으로 쳐 값을 내지만, 그 값은 이 호출의 원가가 아니다.
        usd=None if cost.missing_tokens else cost.usd,
        missing_tokens=cost.missing_tokens,
        first_token_ms=as_int(call.get("firstTokenMs")),
        stream_first_token_ms=as_int(call.get("streamFirstTokenMs")),
    )


def row_cost(row: dict[str, Any]) -> float:
    """행 하나의 원가 합(단가 없는 모델의 칸은 뺀다 — 몇 칸인지는 `RunCost.unpriced_calls` 가 센다)."""
    return sum(cost.usd for cost in (call_cost(call) for call in _calls(row)) if cost.usd is not None)


def cost_is_lower_bound(rows: list[dict[str, Any]]) -> bool:
    """행들의 원가 합이 실제보다 낮을 수 있는가 — 단가 없는 호출(합에서 빠진다)이나 입력 토큰이 기록되지 않은 호출(기록된 칸만
    들어간다)이 하나라도 있다."""
    return any(
        cost.usd is None or cost.missing_tokens for cost in (call_cost(call) for row in rows for call in _calls(row))
    )


def _turn_rows(turn: Turn) -> list[dict[str, Any]]:
    return [row for attempt in turn.attempts for row in attempt.chat_turn_rows]


def run_cost(joined: JoinedRun) -> RunCost | None:
    """런 원가. 시도에 붙은 행만 합하고 「짝 없는 기록」의 원가는 따로 낸다. 턴 기록이 없으면 없다. `assistantMessageId` 이전
    형식도 없다 — 행을 잇지 않아(`join_bundle`) 붙은 행이 없으니, 합 0 은 0 원이 아니라 모르는 원가다."""
    export = joined.chat_turns
    if export is None or joined.bundle.format == "preMessageId":
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


def _effective_chat_models(joined: JoinedRun) -> list[str]:
    """실제 생성 모델 — 방 스냅숏의 `effectiveChatModel` 이고, 스냅숏에 그 값이 없으면 턴 기록 파일의 행 전부의 `chat_model`(그
    응답을 실제로 쓴 모델)이다. 다른 방의 파일은 결합에서 이미 버려(`chat_turns` 가 None) 여기 오는 행은 모두 이 방의 것이다.
    시도에 붙지 않은 행(재생성·편집, 같은 방을 이어 친 다른 측정)과 행을 잇지 않는 `assistantMessageId` 이전 형식의 행도 센다 —
    원가와 달리 이 칸은 그 방을 쓴 모델을 보이는 것이라 붙었는지를 따지지 않는다."""
    snapshot = {m for m in (_str(r.get("effectiveChatModel")) for r in joined.room_statics) if m is not None}
    if snapshot or joined.chat_turns is None:
        return sorted(snapshot)
    return sorted({m for m in (_str(row.get("chat_model")) for row in joined.chat_turns.rows) if m is not None})


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
            "effective_chat_models": _effective_chat_models(joined),
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
            # 런 원가 합(`run_cost`)과 같은 행 — 시도에 붙은 행만 본다.
            "cost_is_lower_bound": (
                cost_is_lower_bound([row for turn in joined.turns for row in _turn_rows(turn)])
                if cost is not None
                else None
            ),
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


def stats_before(joined: JoinedRun, turn: Turn) -> dict[str, Any] | None:
    """그 턴이 시작한 스탯(드라이버 줄의 이름 키). 리플레이가 그 턴을 조립할 때 읽는 줄(`replay.logs.stats_line`)의
    `roomAfter.stats` 다 — 따로 고르면 화면과 리플레이가 같은 턴을 다른 상태로 본다. 앞 턴의 응답을 재생성·수정이 바꿨으면 그
    줄의 값이 교체 뒤에도 맞는지 알 수 없어 None 이다. 규칙 전체는 `DriverStatChange`."""
    previous = next((t for t in joined.turns if t.number == turn.number - 1), None)
    if previous is not None and previous.replacement is not None:
        return None
    try:
        _, record = stats_line(joined.logs, turn.number)
    except ReplayRefusedError:
        return None
    stats = record["roomAfter"].get("stats")
    return stats if isinstance(stats, dict) else None


def _driver_changes(record: dict[str, Any], before: dict[str, Any] | None) -> list[DriverStatChange]:
    changes = record.get("statChanges")
    out: list[DriverStatChange] = []
    for change in changes if isinstance(changes, list) else []:
        value = as_number(change.get("value")) if isinstance(change, dict) else None
        name = _str(change.get("name")) if isinstance(change, dict) else None
        if name is not None and value is not None:
            start = as_number(before.get(name)) if before is not None else None
            out.append(
                DriverStatChange(name=name, value=value, before=start, delta=None if start is None else value - start)
            )
    return out


def turn_summary(joined: JoinedRun, turn: Turn, flags: ReplyFlagsView | None) -> TurnSummary:
    """`flags` 는 런 지표의 이 턴 칸 — 플래그를 여기서 다시 판정하지 않는다."""
    record = turn.selected.record
    reply = _str(record.get("reply")) or ""
    ending = record.get("ending")
    rows = _turn_rows(turn)
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
        driver_stat_changes=_driver_changes(record, stats_before(joined, turn)),
        recorded_stat_changes=_recorded_changes(joined, turn),
        ending=ending if isinstance(ending, dict) else None,
        failure=_str(record.get("failure")),
        earlier_generation_dumps=len(turn.earlier_generation_dumps),
        judgment_dumps=len(turn.judgment_dumps),
        background_dumps=len(turn.background_dumps),
        flags=flags,
        cost_usd=sum(row_cost(row) for row in rows) if rows else None,
        cost_is_lower_bound=cost_is_lower_bound(rows),
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


def run_detail(joined: JoinedRun, *, metrics: RunMetrics | None = None) -> RunDetail:
    """`metrics` 는 이미 낸 런 지표 — 묶음 전체를 낼 때 넘겨 지표를 두 번 내지 않는다. 턴 요약의 플래그는 그 지표에서 온다."""
    cost = run_cost(joined)
    flags = {m.turn: m.flags for m in (metrics if metrics is not None else run_metrics(joined)).turns}
    return RunDetail(
        run=run_list_item(joined.bundle, joined),
        meta=joined.meta,
        room_static=joined.room_statics[-1] if joined.room_statics else None,
        turns=[turn_summary(joined, turn, flags.get(turn.number)) for turn in joined.turns],
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
        status_block_length=flags.status_block_length,
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
    limits = [
        RecordLimit(slot="judgmentResponse", text=JUDGMENT_RESULT_LIMIT),
        RecordLimit(slot="judgmentLatency", text=LATENCY_LIMIT),
    ]
    if turn.background_dumps:
        limits.append(RecordLimit(slot="backgroundTokens", text=BACKGROUND_LIMIT))
    # `assistantMessageId` 이전 형식은 내보내기를 거부하므로(`export_chat_turns`) 내보내라고 하지 않는다.
    if joined.chat_turns is None and joined.bundle.format != "preMessageId":
        limits.append(RecordLimit(slot="exportNeeded", text=EXPORT_NEEDED_LIMIT))
    if not joined.has_dump:
        limits.append(RecordLimit(slot="promptDump", text=NO_DUMP_LIMIT))
    before = stats_before(joined, turn)
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
                driver_stat_changes=_driver_changes(attempt.record, before),
                generation_dump=attempt.generation_dump,
                chat_turns=[
                    ChatTurnRecord(
                        row=row,
                        calls=[call_view(call) for call in _calls(row)],
                        cost_usd=row_cost(row),
                        cost_is_lower_bound=cost_is_lower_bound([row]),
                    )
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
        detail=run_detail(joined, metrics=metrics),
        metrics=metrics,
        turns=turns if raw else [_without_raw(turn) for turn in turns],
    )
