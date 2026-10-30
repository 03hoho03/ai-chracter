"""한 묶음의 드라이버 로그·덤프·턴 기록을 턴 단위로 잇는 규칙과, 그 위에서 내는 상태 계열·지표·원가.

런은 측정 드라이버를 테스트 앱에 실제로 붙여 만들고(`driver_harness.drive_room`), 턴 기록 파일은 테스트 트랜잭션의
`chat_turns` 행과 스탯 정의를 읽어 내보내기 직렬화 함수로 쓴다 — 내보내기 CLI 가 할 일 가운데 DB 를 읽는 부분만 여기서
한다. 기대값은 리플레이 규칙(`replay.logs`)·대화록 판정(`analyze_chat_probe.reply_flags`)·단가 함수(`api.llm.pricing.call_cost`)
를 직접 불러 만든다. 같은 입력에서 두 도구가 같은 답을 내야 화면과 리플레이·원가 리포트의 숫자가 갈리지 않는다."""

import copy
import json
from collections import Counter
import statistics
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from analyze_chat_probe import reply_flags
from api.db.models import ChatTurn, StatDef
from api.llm import pricing
from api.llm.call_policy import CALL_POLICIES
from api.llm.pricing import PRICES_AS_OF, ModelPrice, call_cost
from chat_lab.bundles import CHAT_TURNS_NAME, discover_bundles
from chat_lab.chat_turns_file import (
    ExportStatDef,
    chat_turn_row,
    export_text,
    parse_chat_turns,
    prices_sha256,
    stat_def_entry,
)
from chat_lab.join import JoinedRun, join_bundle
from chat_lab.report import (
    BACKGROUND_LIMIT,
    EXPORT_NEEDED_LIMIT,
    JUDGMENT_RESULT_LIMIT,
    LATENCY_LIMIT,
    NO_DUMP_LIMIT,
    call_site_kind,
    list_entry,
    run_detail,
    run_metrics,
    turn_detail,
)
from chat_lab.schemas import CallSiteKind, RunMetrics, TurnMetrics
from driver_harness import (
    _DRIVE_LOWER_RULE,
    _DRIVE_RAISE_RULE,
    DRIVE_HIDDEN_RULE,
    DRIVE_HIDDEN_STAT_NAME,
    DRIVE_STAT_NAME,
    DrivenRoom,
    drive_room,
    says,
)
from replay.logs import generation_records, load_driver_logs, load_dump, stats_line, turn_line


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


async def _db_turns(db_session: AsyncSession, driven: DrivenRoom) -> list[ChatTurn]:
    # 앱이 같은 세션에 남긴 행 객체가 있어도 DB 값으로 다시 읽는다(테스트가 행을 고친 뒤에 부른다).
    query = (
        sa.select(ChatTurn)
        .where(ChatTurn.chat_room_id == driven.room_id)
        .order_by(ChatTurn.turn_number)
        .execution_options(populate_existing=True)
    )
    return list((await db_session.scalars(query)).all())


async def _db_export(db_session: AsyncSession, driven: DrivenRoom) -> tuple[list[ExportStatDef], list[dict[str, Any]]]:
    """내보내기가 DB 에서 읽을 것 — 그 방의 턴 기록 행 전부와 방 시작 설정의 스탯 정의(id·이름·숨김 여부)."""
    defs = await db_session.scalars(
        sa.select(StatDef).where(StatDef.starting_setup_id == driven.setup_id).order_by(StatDef.order)
    )
    rows = [copy.deepcopy(chat_turn_row(turn)) for turn in await _db_turns(db_session, driven)]
    return [stat_def_entry(stat) for stat in defs.all()], rows


def _write_export(
    driven: DrivenRoom, stat_defs: list[ExportStatDef], rows: list[dict[str, Any]], *, room_id: str | None = None
) -> None:
    room = room_id if room_id is not None else str(driven.room_id)
    text = export_text(room_id=room, exported_at=datetime.now(UTC), stat_defs=stat_defs, rows=rows)
    (driven.log.parent / CHAT_TURNS_NAME).write_text(text, encoding="utf-8")


def _join(work_dir: Path) -> JoinedRun:
    [bundle] = discover_bundles(work_dir)
    return join_bundle(bundle)


def _key(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def _flags_dump(reply: str, previous: str) -> dict[str, Any]:
    flags = reply_flags(reply, previous)
    return {**asdict(flags), "brackets": list(flags.brackets)}


async def test_a_real_run_joins_turns_attempts_dumps_and_records_by_the_replay_rule(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """턴은 서로 다른 clientTurn 이고 유실 턴의 재시도는 같은 턴의 둘째 시도다. 마지막 생성 덤프가 리플레이가 DB 응답으로 보는
    시도에 붙어야 두 도구가 같은 턴을 같은 덤프로 본다. 이 방의 덤프 줄과 턴 기록 행은 하나도 빠짐없이 어딘가에 붙거나 불일치로
    보여야 한다 — 조용히 버리면 "없는 호출"과 "기록 안 된 호출"이 화면에서 갈리지 않는다. 깨끗한 런은 불일치가 0 이고, 백그라운드
    줄은 응답 뒤에 쓰여 턴 배치가 추정이므로 줄마다 주의를 단다. 턴 칸이 없는 백그라운드 줄(장면·사실 추출)은 파일 순서상 바로
    앞 생성 줄의 턴에 놓는다."""
    driven = await drive_room(db_session, monkeypatch, tmp_path)
    stat_defs, rows = await _db_export(db_session, driven)
    _write_export(driven, stat_defs, rows)

    joined = _join(tmp_path)

    turn_lines = [r for r in _jsonl(driven.log) if r["kind"] == "turn"]
    assert [turn.number for turn in joined.turns] == sorted({r["clientTurn"] for r in turn_lines}) == list(range(1, 13))
    assert [len(turn.attempts) for turn in joined.turns] == [2 if n == 7 else 1 for n in range(1, 13)]
    assert [attempt.record["done"] for attempt in joined.turn(7).attempts] == [False, True]

    logs = load_driver_logs(driven.log, driven.snapshot_log, driven.room_id)
    dump = load_dump(driven.dump)
    for turn in joined.turns:
        index, line = turn_line(logs, turn.number)
        expected = generation_records(dump, driven.room_id, turn.number)
        assert (turn.selected.line_index, turn.selected.record) == (index, line)
        assert turn.selected.generation_dump == expected[-1]
        assert turn.earlier_generation_dumps == expected[:-1]
        assert [a.generation_dump for a in turn.attempts if not a.selected] == [None] * (len(turn.attempts) - 1)
    assert len(joined.turn(7).earlier_generation_dumps) == 1
    assert [(marker.kind, marker.turn) for marker in joined.markers if marker.kind == "rebase"] == [("rebase", 6)]

    room_lines = [r for r in dump if r.get("roomId") == str(driven.room_id)]
    placed: list[dict[str, Any]] = []
    for turn in joined.turns:
        placed += [a.generation_dump for a in turn.attempts if a.generation_dump is not None]
        placed += turn.earlier_generation_dumps + turn.judgment_dumps + [b.record for b in turn.background_dumps]
    assert sorted(map(_key, placed)) == sorted(map(_key, room_lines))
    assert joined.mismatches == []

    attached = [
        (row["assistant_message_id"], attempt.record.get("assistantMessageId"))
        for turn in joined.turns
        for attempt in turn.attempts
        for row in attempt.chat_turn_rows
    ]
    assert sorted(row_id for row_id, _ in attached) == sorted(str(row["assistant_message_id"]) for row in rows)
    assert all(row_id == line_id for row_id, line_id in attached)
    assert len(rows) == 12 and joined.unmatched_rows == []

    background = [r for r in room_lines if r["kind"] == "background"]
    assert background, "요약 접기가 돌지 않았다 — 백그라운드 줄의 배치를 보지 못한다"
    by_turn_field = [(turn.number, b.placement) for turn in joined.turns for b in turn.background_dumps]
    assert by_turn_field == [(r["turn"], "turnField") for r in background]
    assert [caution.kind for caution in joined.cautions] == ["placementEstimated"] * len(background)

    previous_generation: list[int] = []
    last_generation = 0
    for record in room_lines:
        if record["kind"] == "generation":
            last_generation = record["turn"]
        elif record["kind"] == "background":
            previous_generation.append(last_generation)
    _write_jsonl(
        driven.dump,
        [{k: v for k, v in r.items() if not (r.get("kind") == "background" and k == "turn")} for r in dump],
    )
    rejoined = _join(tmp_path)
    assert [(turn.number, b.placement) for turn in rejoined.turns for b in turn.background_dumps] == [
        (n, "previousGeneration") for n in previous_generation
    ]
    assert rejoined.mismatches == []


async def test_hidden_stats_come_from_the_records_with_names_and_never_raise_a_false_mismatch(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """보이는 스탯은 드라이버 로그(이름 키)에, 숨김 스탯은 턴 기록(id 키)에만 남는다. 양쪽에 다 있는 스탯만 견줘야 숨김 스탯이
    "드라이버에 없음"으로 거짓 불일치가 되지 않고, 숨김 스탯은 내보낸 스탯 정의로 이름과 숨김 표시를 얻는다. 대조가 실제로
    일어났는지(비교 수)와, 턴 기록의 보이는 스탯 값을 하나 바꾸면 그 턴이 어긋남으로 잡히는지도 본다 — 늘 0 을 내는 대조는
    깨끗한 런과 구별되지 않는다. 숨김 스탯 값은 바꿔도 견줄 상대가 없어 어긋남이 되지 않아야 한다."""
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(3),
        failing_generations=(),
        stat_verdicts={2: (DRIVE_HIDDEN_RULE,), 3: (_DRIVE_RAISE_RULE,)},
        hidden_stat=True,
    )
    assert driven.hidden_stat_id is not None
    stat_defs, rows = await _db_export(db_session, driven)
    _write_export(driven, stat_defs, rows)

    detail = run_detail(_join(tmp_path))

    assert detail.mismatches == []
    assert detail.stat_comparisons == 1
    series = {s.id: s for s in detail.series}
    hidden = series[str(driven.hidden_stat_id)]
    assert (hidden.name, hidden.hidden, hidden.source) == (DRIVE_HIDDEN_STAT_NAME, True, "chatTurns")
    assert [(point.turn, point.value) for point in hidden.points] == [(2, 70.0)]
    trust = series[str(driven.trust_id)]
    assert (trust.name, trust.hidden, trust.source) == (DRIVE_STAT_NAME, False, "driver")
    assert [(point.turn, point.value) for point in trust.points] == [(1, 50.0), (2, 50.0), (3, 80.0)]

    tampered = copy.deepcopy(rows)
    for row in tampered:
        for stat_id in (str(driven.trust_id), str(driven.hidden_stat_id)):
            if stat_id in row["stat_changes"]:
                row["stat_changes"][stat_id][1] += 1
    _write_export(driven, stat_defs, tampered)

    tampered_detail = run_detail(_join(tmp_path))
    assert [(m.kind, m.turn) for m in tampered_detail.mismatches] == [("statMismatch", 3)]


async def test_cost_is_the_sum_of_call_cost_over_the_recorded_calls(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """원가를 따로 계산하면 원가 리포트들과 숫자가 말없이 갈라진다 — 같은 호출 칸을 단가 함수에 넣은 합이어야 한다. 가짜 LLM 은
    사용량을 보고하지 않아 행의 호출 칸이 비므로, 실제 꼴의 호출 칸을 DB 행에 넣은 뒤 내보낸다(단가 없는 모델 하나를 섞는다).
    첫 토큰 지연은 생성 호출에만 있고 판정 호출에는 없다."""
    driven = await drive_room(
        db_session, monkeypatch, tmp_path, script=says(2), failing_generations=(), stat_verdicts={}
    )
    calls: list[dict[str, Any]] = [
        {
            "callSite": "chat_generate",
            "model": "gemini-3.5-flash-lite",
            "promptTokens": 1200,
            "cachedTokens": 200,
            "cacheWriteTokens": None,
            "outputTokens": 300,
            "thoughtsTokens": 50,
            "firstTokenMs": 900,
            "streamFirstTokenMs": 700,
        },
        {
            "callSite": "chat_stat_judgment",
            "model": "claude-haiku-5-5",
            "promptTokens": 800,
            "cachedTokens": 0,
            "cacheWriteTokens": 100,
            "outputTokens": 40,
            "thoughtsTokens": None,
        },
        {
            "callSite": "chat_stat_judgment",
            "model": "no-such-model",
            "promptTokens": 10,
            "cachedTokens": 0,
            "cacheWriteTokens": None,
            "outputTokens": 1,
            "thoughtsTokens": None,
        },
    ]
    await db_session.execute(sa.update(ChatTurn).where(ChatTurn.chat_room_id == driven.room_id).values(llm_calls=calls))
    stat_defs, rows = await _db_export(db_session, driven)
    assert [row["llm_calls"] for row in rows] == [calls, calls]
    _write_export(driven, stat_defs, rows)

    joined = _join(tmp_path)
    detail = run_detail(joined)

    expected = sum(c.usd for c in (call_cost(call) for row in rows for call in row["llm_calls"]) if c.usd is not None)
    per_turn = sum(c.usd for c in map(call_cost, calls) if c.usd is not None)
    cost = detail.cost
    assert expected > 0 and cost is not None
    assert cost.total_usd == pytest.approx(expected)
    assert detail.run.cost_usd == cost.total_usd
    assert [turn.cost_usd for turn in detail.turns] == pytest.approx([per_turn, per_turn])
    assert (cost.unpriced_calls, cost.missing_token_calls, cost.prices_changed) == (2, 0, False)
    [record] = turn_detail(joined, 1).attempts[0].chat_turns
    assert [(c.call_site, c.usd is None, c.first_token_ms) for c in record.calls] == [
        ("chat_generate", False, 900),
        ("chat_stat_judgment", False, None),
        ("chat_stat_judgment", True, None),
    ]


async def test_metrics_are_reply_flags_against_the_reply_the_screen_shows_as_previous(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """지표는 대화록 분석과 같은 판정 함수로 내야 두 곳의 숫자가 갈리지 않는다. 자기복제 판정은 무엇을 직전 응답으로 보느냐에
    달려 있어, 직전 응답은 앞 턴에서 DB 응답으로 고른 시도의 응답(첫 턴은 오프닝)이어야 한다 — 유실 시도를 쓰면 화면이 가리키는
    응답과 다른 것과 견준다. 되받기는 고정 대본의 키워드에 묶여 자유 발화에는 뜻이 없어 내보내지 않는다."""
    driven = await drive_room(
        db_session, monkeypatch, tmp_path, script=says(4), failing_generations=(2,), stat_verdicts={}
    )

    metrics = run_metrics(_join(tmp_path))

    opening = next(r for r in _jsonl(driven.log) if r["kind"] == "opening")["messages"][-1]
    logs = load_driver_logs(driven.log, driven.snapshot_log, driven.room_id)
    replies = {n: str(turn_line(logs, n)[1]["reply"]) for n in (1, 2, 3)}
    previous = {1: opening, 2: replies[1], 3: replies[2]}
    assert [(m.turn, m.previous_from, m.previous_turn) for m in metrics.turns] == [
        (1, "opening", None),
        (2, "turn", 1),
        (3, "turn", 2),
    ]
    for m in metrics.turns:
        assert m.flags.model_dump() == _flags_dump(replies[m.turn], previous[m.turn])
    assert (metrics.scored, metrics.lost) == (3, 0)
    assert metrics.truncated == sum(m.flags.truncated for m in metrics.turns)
    assert metrics.scene_open == sum(m.flags.scene_open for m in metrics.turns)
    assert metrics.median_length == statistics.median(m.flags.length for m in metrics.turns)
    schema = json.dumps([RunMetrics.model_json_schema(), TurnMetrics.model_json_schema()], ensure_ascii=False)
    assert "parrot" not in schema.lower() and "되받기" not in schema


def _replacement(kind: str, room_id: str, turn_before: int, reply: str, user_text: str | None) -> dict[str, Any]:
    """옛 런(드라이버가 재생성·수정을 쓰던 때)의 `regenerate`·`edit` 줄 키 그대로. 수정 줄만 메시지 id 와 사용자 글이 있다."""
    return {
        "kind": kind,
        "roomId": room_id,
        "turnBefore": turn_before,
        "sentAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "tag": "lab",
        "userText": user_text,
        "messageId": str(uuid.uuid4()) if kind == "edit" else None,
        "seconds": 1.0,
        "http": 200,
        "done": True,
        "reply": reply,
        "failure": None,
        "appCode": None,
        "serverLogOffsetAfter": None,
    }


async def test_regenerate_and_edit_lines_replace_the_turn_reply_used_as_the_next_previous(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """재생성·수정 줄은 clientTurn 이 없고 대상 턴은 `turnBefore` 다. 그 턴의 DB 응답은 교체 뒤 응답이라, 다음 턴의 자기복제는
    교체 뒤 응답과 견줘야 지금 DB 에 없는 응답과 비교하지 않는다. 지금 드라이버는 이 두 줄을 쓰지 않아 옛 런의 키 그대로 실제
    런의 대상 턴 줄 바로 뒤에 넣는다."""
    driven = await drive_room(
        db_session, monkeypatch, tmp_path, script=says(3), failing_generations=(), stat_verdicts={}
    )
    room = str(driven.room_id)
    regenerate = _replacement("regenerate", room, 1, "다시 쓴 첫 응답이다. 바람이 멎는다.", None)
    edit = _replacement("edit", room, 2, "고쳐 쓴 둘째 응답이다. 문이 닫힌다.", "고친 말 2")
    lines: list[dict[str, Any]] = []
    for record in _jsonl(driven.log):
        lines.append(record)
        if record["kind"] == "turn":
            lines += {1: [regenerate], 2: [edit]}.get(record["clientTurn"], [])
    _write_jsonl(driven.log, lines)

    joined = _join(tmp_path)
    detail = run_detail(joined)
    metrics = run_metrics(joined)

    assert [(turn.turn, turn.replaced) for turn in detail.turns] == [(1, True), (2, True), (3, False)]
    assert [(m.kind, m.turn) for m in joined.markers if m.kind in ("regenerate", "edit")] == [
        ("regenerate", 1),
        ("edit", 2),
    ]
    assert [(m.turn, m.previous_from, m.previous_turn) for m in metrics.turns] == [
        (1, "opening", None),
        (2, "replacement", 1),
        (3, "replacement", 2),
    ]
    third = next(m for m in metrics.turns if m.turn == 3)
    assert third.flags.model_dump() == _flags_dump(str(joined.turn(3).selected.record["reply"]), edit["reply"])
    assert detail.mismatches == []


def _supplement(room_id: str, after: dict[str, Any], memory: dict[str, Any], turn_count: int) -> dict[str, Any]:
    """사람이 화면에서 친 턴을 나중에 드라이버 로그에 보충한 줄(조감독 장기 런의 실측 키 그대로) — clientTurn·turnBefore·sentAt 이
    없고 턴 번호는 방 턴 수로만 알 수 있다."""
    return {
        "kind": "turn",
        "source": "human",
        "roomId": room_id,
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "replyCreatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "seconds": 0.0,
        "tag": None,
        "userText": f"사람이 친 말 {turn_count}",
        "shortcut": None,
        "reply": f"사람 턴의 응답 {turn_count}.",
        "imageId": None,
        "imageLabel": None,
        "statChanges": [],
        "ending": None,
        "endingReachedHere": False,
        "postEnding": False,
        "failure": None,
        "http": 200,
        "done": True,
        "memory": memory,
        "roomAfter": {**after, "turnCount": turn_count},
        "links": {},
        "supplementedBy": "lab",
    }


async def test_supplement_lines_take_their_turn_number_from_the_room_turn_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """보충 줄을 clientTurn 으로만 묶으면 여러 줄이 번호 없는 한 턴의 시도로 뭉친다. 방 턴 수로 번호를 대신하고 보충 줄로
    표시한다. 덤프에는 그 턴의 생성 줄이 없으므로 그 턴은 덤프 없는 시도로 드러나야 한다."""
    driven = await drive_room(
        db_session, monkeypatch, tmp_path, script=says(2), failing_generations=(), stat_verdicts={}
    )
    lines = _jsonl(driven.log)
    last = [r for r in lines if r["kind"] == "turn"][-1]
    room = str(driven.room_id)
    _write_jsonl(driven.log, [*lines, *(_supplement(room, last["roomAfter"], last["memory"], n) for n in (3, 4))])

    detail = run_detail(_join(tmp_path))

    assert [(turn.turn, turn.attempt_count, turn.supplemented) for turn in detail.turns] == [
        (1, 1, False),
        (2, 1, False),
        (3, 1, True),
        (4, 1, True),
    ]
    assert [(m.kind, m.turn) for m in detail.mismatches] == [("missingDump", 3), ("missingDump", 4)]


async def test_chat_turns_export_round_trips_every_column_and_names_the_price_table(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """턴 기록은 런 당시 DB 볼륨이 지워지면 다시 읽을 수 없어 파일로 남긴다. 칼럼 하나를 빠뜨리면 그 값은 영영 사라지므로 행의
    모든 칼럼이 그대로 돌아와야 한다. 숨김 스탯을 이름으로 보이려면 스탯 정의도 함께 있어야 하고, 원가를 다시 낼 때 단가표가
    내보낸 때와 같은지 가르려면 기준일과 표 내용의 해시가 있어야 한다 — 기준일은 줄이 더해져도 그대로라 판을 가르지 못한다."""
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(2),
        failing_generations=(),
        stat_verdicts={2: (DRIVE_HIDDEN_RULE,)},
        hidden_stat=True,
    )
    exported_at = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    stat_defs, rows = await _db_export(db_session, driven)
    turns = await _db_turns(db_session, driven)

    parsed = parse_chat_turns(
        export_text(room_id=str(driven.room_id), exported_at=exported_at, stat_defs=stat_defs, rows=rows)
    )

    columns = {column.key for column in ChatTurn.__table__.columns}
    assert [set(row) for row in parsed.rows] == [columns, columns]

    def plain(value: Any) -> Any:
        if isinstance(value, uuid.UUID):
            return str(value)
        return value.isoformat() if isinstance(value, datetime) else value

    assert parsed.rows == [{key: plain(getattr(turn, key)) for key in columns} for turn in turns]
    assert (parsed.room_id, parsed.exported_at, parsed.prices_as_of) == (
        str(driven.room_id),
        exported_at.isoformat(),
        PRICES_AS_OF.isoformat(),
    )
    assert parsed.scope
    assert [(d.id, d.name, d.hidden_from_player) for d in parsed.stat_defs] == [
        (str(driven.trust_id), DRIVE_STAT_NAME, False),
        (str(driven.hidden_stat_id), DRIVE_HIDDEN_STAT_NAME, True),
    ]
    assert parsed.prices_sha256 == prices_sha256()
    monkeypatch.setitem(pricing.MODEL_PRICES, "lab-new-model", ModelPrice(1.0, 0.1, 2.0))
    assert prices_sha256() != parsed.prices_sha256


async def _plain_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, turns: int
) -> DrivenRoom:
    return await drive_room(
        db_session, monkeypatch, tmp_path, script=says(turns), failing_generations=(), stat_verdicts={}
    )


async def _hidden_stat_run(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> DrivenRoom:
    """턴 2 에 숨김 스탯이, 턴 3 에 보이는 스탯(신뢰 50 → 80)이 바뀌는 세 턴 런."""
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(3),
        failing_generations=(),
        stat_verdicts={2: (DRIVE_HIDDEN_RULE,), 3: (_DRIVE_RAISE_RULE,)},
        hidden_stat=True,
    )
    assert driven.hidden_stat_id is not None
    return driven


async def test_rows_that_match_no_attempt_are_kept_apart_from_the_run_cost(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """응답 id 가 어느 시도와도 맞지 않는 행(재생성·편집·같은 방을 이어 친 다른 측정)은 「짝 없는 기록」이다. 그 원가를 런 원가에
    더하면 이 런이 쓴 돈이 부풀므로 따로 싣고, 목록에는 원가 합에서 빠진 단가 없는 호출 수를 함께 싣는다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 2)
    calls: list[dict[str, Any]] = [
        {"callSite": "chat_generate", "model": "gemini-3.5-flash-lite", "promptTokens": 900, "outputTokens": 120},
        {"callSite": "chat_stat_judgment", "model": "no-such-model", "promptTokens": 10, "outputTokens": 1},
    ]
    await db_session.execute(sa.update(ChatTurn).where(ChatTurn.chat_room_id == driven.room_id).values(llm_calls=calls))
    stat_defs, rows = await _db_export(db_session, driven)
    stray = {**copy.deepcopy(rows[-1]), "id": uuid.uuid4(), "assistant_message_id": uuid.uuid4(), "kind": "regenerate"}
    _write_export(driven, stat_defs, [*rows, stray])

    detail = run_detail(_join(tmp_path))

    per_row = sum(c.usd for c in map(call_cost, calls) if c.usd is not None)
    cost = detail.cost
    assert per_row > 0 and cost is not None
    assert [(m.kind, m.turn) for m in detail.mismatches] == [("unmatchedRow", 2)]
    assert [(row.kind, row.turn_number) for row in detail.unmatched_rows] == [("regenerate", 2)]
    assert (cost.total_usd, cost.unmatched_usd) == pytest.approx((2 * per_row, per_row))
    assert (detail.run.cost_usd, detail.run.unpriced_calls) == (cost.total_usd, 2)


async def test_a_missing_turn_number_and_the_dump_lines_left_without_it_are_mismatches(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """드라이버 로그에서 턴 하나가 빠지면(서버는 마쳤는데 드라이버가 못 받아 다음 실행이 번호를 건너뛴 경우 등) 그 번호는 턴 번호
    건너뜀이고, 그 턴의 덤프 줄은 붙을 곳이 없어 짝 없는 덤프 줄이다 — 둘 다 조용히 사라지면 안 된다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 3)
    _write_jsonl(driven.log, [r for r in _jsonl(driven.log) if not (r["kind"] == "turn" and r["clientTurn"] == 2)])
    orphans = sum(1 for r in _jsonl(driven.dump) if r["turn"] == 2)

    detail = run_detail(_join(tmp_path))

    assert orphans >= 2
    assert Counter((m.kind, m.turn) for m in detail.mismatches) == Counter(
        {("turnGap", 2): 1, ("unmatchedDumpLine", 2): orphans}
    )


async def test_driver_lines_with_no_turn_to_sit_on_are_unplaced(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """없는 턴을 가리키는 재생성 줄과, clientTurn 도 방 턴 수도 없는 턴 줄은 놓을 턴이 없다. 버리면 기록에 있는 줄이 화면에서
    사라지므로 놓지 못한 줄로 센다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 2)
    room = str(driven.room_id)
    stray = _replacement("regenerate", room, 9, "어디에도 없는 턴의 재생성이다.", None)
    numberless = {
        "kind": "turn",
        "source": "human",
        "roomId": room,
        "userText": "번호 없는 말",
        "reply": "번호 없는 응답이다.",
        "http": 200,
        "done": True,
        "roomAfter": None,
    }
    _write_jsonl(driven.log, [*_jsonl(driven.log), stray, numberless])

    detail = run_detail(_join(tmp_path))

    assert [turn.turn for turn in detail.turns] == [1, 2]
    assert Counter((m.kind, m.turn) for m in detail.mismatches) == Counter(
        {("unplacedLine", 9): 1, ("unplacedLine", None): 1}
    )


def _refused(turn_record: dict[str, Any], client_turn: int) -> dict[str, Any]:
    """앱이 생성 전에 거부한 시도(HTTP 429)의 턴 줄 — 드라이버가 비200 응답에 쓰는 칸 그대로다. 측정 장치로 만들면 드라이버가 그
    호출에서 종료 코드 4 로 멈춰 대본을 이어 칠 수 없어, 실제 턴 줄의 공통 칸에 거부 칸을 얹는다."""
    common = {
        key: turn_record[key] for key in ("kind", "roomId", "sentAt", "tag", "userText", "shortcut", "shortcutId")
    }
    return {
        **common,
        "clientTurn": client_turn,
        "turnBefore": client_turn - 1,
        "memory": turn_record["memory"],
        "seconds": 0.1,
        "ttftMs": None,
        "http": 429,
        "done": False,
        "reply": "",
        "statChanges": [],
        "ending": None,
        "failure": "HTTP 429",
        "roomAfter": None,
        "appCode": "RATE_LIMITED",
        "retryAfterSeconds": 30,
    }


async def test_attempts_refused_before_the_server_have_no_dump_and_are_not_mismatches(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """서버 앞에서 거부된 시도(앱 429·409)는 생성까지 가지 않아 덤프가 없는 것이 정상이다. 재시도로 성공한 턴에서도, 거부로
    끝난 마지막 턴에서도 "덤프 없는 시도" 불일치로 세면 정상 런의 불일치 수가 0 이 아니게 된다. 거부로 끝난 턴에 그 방의 생성
    덤프를 붙이지도 않는다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 3)
    lines = _jsonl(driven.log)
    turn_lines = [r for r in lines if r["kind"] == "turn"]
    out: list[dict[str, Any]] = []
    for record in lines:
        if record is turn_lines[1]:
            out.append(_refused(record, 2))
        out.append(record)
    _write_jsonl(driven.log, [*out, _refused(turn_lines[-1], 4)])

    joined = _join(tmp_path)
    detail = run_detail(joined)

    assert detail.mismatches == []
    assert [
        (a.server_rejected, a.selected, a.generation_dump is not None) for a in turn_detail(joined, 2).attempts
    ] == [
        (True, False, False),
        (False, True, True),
    ]
    fourth = turn_detail(joined, 4)
    assert [(a.server_rejected, a.selected, a.generation_dump) for a in fourth.attempts] == [(True, True, None)]
    assert fourth.earlier_generation_dumps == []
    assert [(turn.turn, turn.lost) for turn in detail.turns] == [(1, False), (2, False), (3, False), (4, True)]


def _connection_lost(turn_record: dict[str, Any]) -> dict[str, Any]:
    """연결이 끊겨 끝난 시도의 턴 줄 — 드라이버가 `httpx.TransportError` 를 잡아 쓰는 칸 그대로다. 보내기 전에 정한 칸 위에 걸린
    시간, HTTP 상태 없음(`None`), 완료 없음, 빈 응답, `transport:` 로 시작하는 실패, 빈 방 상태를 얹는다. 측정 장치로 만들면
    드라이버가 그 호출에서 종료 코드 1 로 멈춰 대본을 이어 칠 수 없어, 실제 턴 줄의 보내기 전 칸에 연결 오류 칸을 얹는다."""
    sent = (
        "kind",
        "roomId",
        "clientTurn",
        "turnBefore",
        "sentAt",
        "tag",
        "userText",
        "shortcut",
        "shortcutId",
        "memory",
    )
    return {
        **{key: turn_record[key] for key in sent},
        "seconds": 30.0,
        "http": None,
        "done": False,
        "reply": "",
        "failure": "transport: ReadTimeout: timed out",
        "roomAfter": None,
    }


async def test_a_connection_lost_attempt_without_a_dump_is_not_a_mismatch_unlike_one_that_got_http_200(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """연결이 끊겨 끝난 시도는 드라이버 줄에 HTTP 상태가 없어 요청이 서버에 닿았는지조차 모른다. 생성 앞에서 끊겼으면 덤프가 없는
    것이 정상이라, 덤프 없음은 결합이 틀렸다는 증거가 아니고 "덤프 없는 시도" 불일치로 세지 않는다. 서버 앞 거부(HTTP 비200)로
    읽지도 않고, 그 턴은 응답 없는 턴이다. 같은 줄이 HTTP 200 이면 서버가 그 턴을 받은 것은 확실해 덤프가 없는 까닭을 "닿지
    않았다"로 설명할 수 없으므로 불일치로 드러나야 한다 — 두 줄은 HTTP 칸만 달라, 덤프 없음을 불일치로 볼지는 그 칸 하나가
    가른다. 서버가 생성까지 가지 못했으면 생성 뒤에 도는 판정 줄도 없으므로 그 턴의 덤프 줄은 모두 지운다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 2)
    lines = _jsonl(driven.log)
    [last] = [r for r in lines if r["kind"] == "turn" and r["clientTurn"] == 2]
    lost = _connection_lost(last)
    dump = _jsonl(driven.dump)
    kept = [r for r in dump if r.get("turn") != 2]
    assert any(r.get("turn") == 2 and r.get("kind") == "generation" for r in dump)
    _write_jsonl(driven.dump, kept)

    _write_jsonl(driven.log, [lost if r is last else r for r in lines])
    joined = _join(tmp_path)
    detail = run_detail(joined)

    assert detail.mismatches == []
    assert [(a.server_rejected, a.selected, a.generation_dump) for a in turn_detail(joined, 2).attempts] == [
        (False, True, None)
    ]
    assert [(turn.turn, turn.lost) for turn in detail.turns] == [(1, False), (2, True)]

    _write_jsonl(driven.log, [{**lost, "http": 200} if r is last else r for r in lines])
    answered = run_detail(_join(tmp_path))

    assert [(m.kind, m.turn) for m in answered.mismatches] == [("missingDump", 2)]


async def test_a_price_table_changed_since_export_is_a_caution_on_the_run_cost(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """원가는 읽는 때 지금 단가표로 낸다. 내보낸 뒤 단가표가 바뀌었으면 그 사실을 보여야 같은 파일의 원가가 날마다 달라 보이는 것을
    측정 차이로 읽지 않는다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 1)
    stat_defs, rows = await _db_export(db_session, driven)
    _write_export(driven, stat_defs, rows)
    monkeypatch.setitem(pricing.MODEL_PRICES, "lab-new-model", ModelPrice(1.0, 0.1, 2.0))

    joined = _join(tmp_path)
    cost = run_detail(joined).cost

    assert [caution.kind for caution in joined.cautions] == ["pricesChanged"]
    assert cost is not None and cost.prices_changed
    assert joined.mismatches == []


async def test_a_chat_turns_file_of_another_room_is_not_joined(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """다른 방의 턴 기록 파일을 짝으로 두면(복사 실수) 행마다 「짝 없는 기록」이 되고 원가에도 섞인다. 머리 줄의 방 id 가 묶음의
    방과 다르면 행을 하나도 붙이지 않고 그 사실 하나를 불일치로 보인다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 2)
    stat_defs, rows = await _db_export(db_session, driven)
    _write_export(driven, stat_defs, rows, room_id=str(uuid.uuid4()))

    joined = _join(tmp_path)
    detail = run_detail(joined)

    assert [(m.kind, m.turn) for m in detail.mismatches] == [("chatTurnsRoomMismatch", None)]
    assert (joined.chat_turns, detail.cost, detail.run.has_chat_turns) == (None, None, False)
    assert [attempt.chat_turn_rows for turn in joined.turns for attempt in turn.attempts] == [[], []]


async def test_without_snapshots_the_exported_definitions_name_the_visible_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """드라이버는 스탯을 이름 키로만 남겨, id↔이름 표가 없으면 턴 기록(id 키)과 견줄 수 없고 계열도 이름을 id 로 쓴다. 기억 스냅숏
    로그가 없는 묶음에서는 내보낸 스탯 정의(숨김 제외)가 그 표가 되어야 대조가 돈다."""
    driven = await _hidden_stat_run(db_session, monkeypatch, tmp_path)
    stat_defs, rows = await _db_export(db_session, driven)
    _write_export(driven, stat_defs, rows)
    driven.snapshot_log.unlink()

    detail = run_detail(_join(tmp_path))

    assert (detail.mismatches, detail.stat_comparisons) == ([], 1)
    trust = {series.id: series for series in detail.series}[str(driven.trust_id)]
    assert (trust.name, trust.hidden, [(p.turn, p.value) for p in trust.points]) == (
        DRIVE_STAT_NAME,
        False,
        [(1, 50.0), (2, 50.0), (3, 80.0)],
    )


async def test_room_statics_with_different_stat_lists_skip_the_stat_comparison(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """방 스냅숏이 다시 적힐 때 스탯 목록이 바뀌었으면(기준을 다시 잡는 사이 작품 버전을 옮김) 어느 턴의 이름이 어느 정의인지 가릴
    수 없다. 그대로 견주면 거짓 불일치가 나므로, 주의를 달고 그 묶음의 스탯 대조를 건너뛴다 — 턴 기록 값이 드라이버와 달라도
    불일치가 되지 않아야 한다."""
    driven = await _hidden_stat_run(db_session, monkeypatch, tmp_path)
    stat_defs, rows = await _db_export(db_session, driven)
    for row in rows:
        if str(driven.trust_id) in row["stat_changes"]:
            row["stat_changes"][str(driven.trust_id)][1] += 1
    _write_export(driven, stat_defs, rows)
    snapshots = _jsonl(driven.snapshot_log)
    renamed = copy.deepcopy(next(r for r in snapshots if r["kind"] == "roomStatic"))
    renamed["stats"] = [{**stat, "name": "믿음"} for stat in renamed["stats"]]
    _write_jsonl(driven.snapshot_log, [*snapshots, renamed])

    joined = _join(tmp_path)
    detail = run_detail(joined)

    assert [caution.kind for caution in joined.cautions] == ["statDefsChanged"]
    assert (detail.stat_comparisons, detail.mismatches) == (0, [])


async def test_a_lost_turn_without_a_retry_is_skipped_when_choosing_the_previous_reply(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """서버는 턴을 마쳤는데 드라이버가 완료를 못 받으면 다음 실행이 기준을 다시 잡아 다음 번호로 넘어가, 응답이 빈 턴이 재시도 없이
    남는다. 그 뒤 턴의 자기복제는 그 빈 턴이 아니라 앞의 응답 있는 턴과 견줘야 하고, 끊긴 조각(`partialReply`)은 응답이 아니다.
    측정 장치의 유실 턴은 늘 같은 번호로 재시도되어 이 모양이 생기지 않으므로, 실제 런의 턴 줄 하나를 그 꼴로 바꾼다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 3)
    lines = _jsonl(driven.log)
    for record in lines:
        if record["kind"] == "turn" and record["clientTurn"] == 2:
            record.update(
                done=False,
                reply="",
                partialReply="끊긴 조각이다.",
                statChanges=[],
                ending=None,
                assistantMessageId=None,
                roomAfter=None,
            )
    _write_jsonl(driven.log, lines)

    metrics = run_metrics(_join(tmp_path))

    logs = load_driver_logs(driven.log, driven.snapshot_log, driven.room_id)
    first, third = (str(turn_line(logs, n)[1]["reply"]) for n in (1, 3))
    assert [(m.turn, m.previous_from, m.previous_turn) for m in metrics.turns] == [(1, "opening", None), (3, "turn", 1)]
    assert next(m for m in metrics.turns if m.turn == 3).flags.model_dump() == _flags_dump(third, first)
    assert (metrics.scored, metrics.lost) == (2, 1)


async def test_driver_stat_changes_carry_the_value_the_turn_started_from_and_the_change(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """드라이버 줄 스탯 변화의 `value` 는 바뀐 뒤 값이다(드라이버가 SSE statChange 의 새 값을 적는다). 화면이 앞 턴 값을 빼서
    변화량을 내면 계산이 화면으로 새므로 서버가 그 턴이 시작한 값(`before`)과 변화량(`delta`)을 준다. 시작 값은 리플레이가 그
    턴을 조립할 때 읽는 스탯 줄과 같아야 두 도구가 같은 턴을 같은 상태로 본다 — 첫 턴은 오프닝, 유실 뒤 재시도 턴은 드라이버가
    기준을 다시 잡은 줄이다. 오르고 내리는 변화를 번갈아 넣어 부호나 앞뒤가 뒤집히면 드러나게 한다. 고르지 않은 시도(유실)의
    변화도 그 턴이 시작한 값에서 잰다 — 그 시도도 같은 상태에서 보냈다. 측정 장치의 유실 시도는 생성이 실패해 판정 전에 끝나므로
    그 줄에 변화를 하나 얹는다."""
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(5),
        failing_generations=(3,),
        stat_verdicts={
            1: (_DRIVE_RAISE_RULE,),
            2: (_DRIVE_LOWER_RULE,),
            4: (_DRIVE_RAISE_RULE,),
            5: (_DRIVE_LOWER_RULE,),
        },
    )

    detail = run_detail(_join(tmp_path))

    assert [(turn.turn, turn.attempt_count) for turn in detail.turns] == [(1, 1), (2, 1), (3, 2), (4, 1)]
    assert [[(c.name, c.before, c.value, c.delta) for c in turn.driver_stat_changes] for turn in detail.turns] == [
        [(DRIVE_STAT_NAME, 50.0, 80.0, 30.0)],
        [(DRIVE_STAT_NAME, 80.0, 40.0, -40.0)],
        [(DRIVE_STAT_NAME, 40.0, 70.0, 30.0)],
        [(DRIVE_STAT_NAME, 70.0, 30.0, -40.0)],
    ]
    logs = load_driver_logs(driven.log, driven.snapshot_log, driven.room_id)
    sources = [stats_line(logs, turn.turn)[1] for turn in detail.turns]
    assert [source["kind"] for source in sources] == ["opening", "turn", "rebase", "turn"]
    assert [turn.driver_stat_changes[0].before for turn in detail.turns] == [
        source["roomAfter"]["stats"][DRIVE_STAT_NAME] for source in sources
    ]

    lines = _jsonl(driven.log)
    [lost] = [r for r in lines if r["kind"] == "turn" and r["clientTurn"] == 3 and not r["done"]]
    lost["statChanges"] = [{"name": DRIVE_STAT_NAME, "value": 95}]
    _write_jsonl(driven.log, lines)

    attempts = turn_detail(_join(tmp_path), 3).attempts
    assert [(a.selected, [(c.before, c.value, c.delta) for c in a.driver_stat_changes]) for a in attempts] == [
        (False, [(40.0, 95.0, 55.0)]),
        (True, [(40.0, 70.0, 30.0)]),
    ]


async def test_the_turn_after_a_replaced_reply_has_no_known_start_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """재생성·수정 줄에는 바뀐 뒤 스탯이 없고 재생성은 스탯을 다시 판정하므로, 응답이 교체된 턴의 다음 턴이 어느 값에서 시작했는지
    기록으로 알 수 없다. 교체 전 줄의 값으로 채우면 틀릴 수 있는 숫자를 보이게 되어 시작 값과 변화량을 비운다. 교체된 턴 자신은
    교체 전에 시작했으니 그대로이고, 응답을 받지 못한 교체는 응답도 스탯도 바꾸지 않아 다음 턴의 시작 값을 지우지 않는다."""
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(3),
        failing_generations=(),
        stat_verdicts={1: (_DRIVE_RAISE_RULE,), 2: (_DRIVE_LOWER_RULE,), 3: (_DRIVE_RAISE_RULE,)},
    )
    room = str(driven.room_id)
    failed = {**_replacement("regenerate", room, 1, "", None), "done": False, "failure": "가짜 생성 실패"}
    regenerate = _replacement("regenerate", room, 2, "다시 쓴 둘째 응답이다. 바람이 멎는다.", None)
    lines: list[dict[str, Any]] = []
    for record in _jsonl(driven.log):
        lines.append(record)
        if record["kind"] == "turn":
            lines += {1: [failed], 2: [regenerate]}.get(record["clientTurn"], [])
    _write_jsonl(driven.log, lines)

    detail = run_detail(_join(tmp_path))

    assert [(turn.turn, turn.replaced) for turn in detail.turns] == [(1, False), (2, True), (3, False)]
    assert [[(c.before, c.value, c.delta) for c in turn.driver_stat_changes] for turn in detail.turns] == [
        [(50.0, 80.0, 30.0)],
        [(80.0, 40.0, -40.0)],
        [(None, 70.0, None)],
    ]
    assert [turn.stats_start_known for turn in detail.turns] == [True, True, False]


async def test_a_turn_continues_the_line_only_from_the_previous_numbered_turn_with_the_same_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """시작 값을 알아도 그 값이 바로 앞 번호 턴이 끝난 값과 이어진다는 보장은 없다. 사람이 앱에서 몇 턴 친 뒤 드라이버가 기준을
    다시 잡으면 턴 번호가 건너뛰고, 점검이 어긋나 손으로 기준을 다시 잡으면 앞 턴 뒤 값과 다른 값에서 시작한다. 그런 턴으로 선을
    이으면 기울기가 그 턴의 변화량과 다르다 — 턴 요약은 시작 값이 바로 앞 번호 턴의 고른 시도가 남긴 값과 같을 때만 이어진다고
    싣는다(첫 턴은 앞 턴이 없다). 실제 드라이버 런에 기준 다시 잡기 줄을 끼워 두 경우를 만든다. 견주는 쪽은 앞 턴의 고른
    시도다 — 첫 생성이 실패해 같은 턴을 다시 보낸 런에서 드라이버는 완료되지 않은 시도 줄에 방 상태(`roomAfter`)를 적지 않으므로,
    첫 시도와 견주면 다시 보내 스탯을 바꾼 턴 다음 턴이 이어지지 않는 것으로 잘못 보인다."""
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(3),
        failing_generations=(),
        stat_verdicts={1: (_DRIVE_RAISE_RULE,)},
    )
    lines = _jsonl(driven.log)
    room = str(driven.room_id)
    turns = {r["clientTurn"]: r for r in lines if r["kind"] == "turn"}

    def rebase(after: dict[str, Any], value: float) -> dict[str, Any]:
        return {
            "kind": "rebase",
            "roomId": room,
            "at": turns[2]["sentAt"],
            "reason": "점검이 어긋나 손으로 기준 다시 잡기",
            "roomAfter": {**after, "stats": {**after["stats"], DRIVE_STAT_NAME: value}, "source": "refetch"},
        }

    def flags() -> list[tuple[int, bool, bool]]:
        detail = run_detail(_join(tmp_path))
        return [(t.turn, t.stats_start_known, t.stats_continue_from_previous) for t in detail.turns]

    assert flags() == [(1, True, False), (2, True, True), (3, True, True)]

    def before_third(extra: dict[str, Any], *, drop_second: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for record in lines:
            if record is turns[3]:
                out.append(extra)
            if not (drop_second and record is turns[2]):
                out.append(record)
        return out

    same = rebase(turns[2]["roomAfter"], turns[2]["roomAfter"]["stats"][DRIVE_STAT_NAME])
    moved = rebase(turns[2]["roomAfter"], 65.0)
    assert same["roomAfter"]["stats"] == turns[2]["roomAfter"]["stats"] != moved["roomAfter"]["stats"]
    _write_jsonl(driven.log, before_third(same))
    assert flags() == [(1, True, False), (2, True, True), (3, True, True)]
    _write_jsonl(driven.log, before_third(moved))
    assert flags() == [(1, True, False), (2, True, True), (3, True, False)]

    # 사람이 턴 2 를 앱에서 쳐 드라이버 로그에는 그 턴 줄이 없고, 드라이버가 같은 값으로 기준을 다시 잡았다.
    _write_jsonl(driven.log, before_third(same, drop_second=True))
    assert flags() == [(1, True, False), (3, True, False)]

    # 턴 2 의 첫 생성(호출 2)이 실패하고 다음 대본 줄이 같은 턴을 다시 보내, 고른 시도(호출 3)가 신뢰를 올린다.
    retry_dir = tmp_path / "retry"
    retry_dir.mkdir()
    retried = await drive_room(
        db_session,
        monkeypatch,
        retry_dir,
        script=says(4),
        failing_generations=(2,),
        stat_verdicts={3: (_DRIVE_RAISE_RULE,)},
    )
    attempts = [r for r in _jsonl(retried.log) if r["kind"] == "turn" and r["clientTurn"] == 2]
    assert [(a["done"], a["roomAfter"] is None) for a in attempts] == [(False, True), (True, False)]
    assert attempts[1]["roomAfter"]["stats"][DRIVE_STAT_NAME] == 80
    [retried_bundle] = discover_bundles(retry_dir)
    retried_turns = run_detail(join_bundle(retried_bundle)).turns
    assert [(t.turn, t.attempt_count) for t in retried_turns] == [(1, 1), (2, 2), (3, 1)]
    assert retried_turns[2].stats_continue_from_previous is True


async def test_supplement_lines_and_a_rebase_after_a_lost_turn_give_the_next_start_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """사람이 친 턴을 보충한 줄도 방 상태(`roomAfter`)를 남겨, 첫 보충 턴의 시작 값은 앞 드라이버 턴 줄에서, 다음 보충 턴의 시작
    값은 앞 보충 줄에서 온다. 앞 턴이 재시도 없이 유실되면 그 턴 뒤 상태를 아는 줄이 없어 시작 값이 빈다 — 더 앞 턴의 값으로
    채우면 유실 턴이 바꿨을 수 있는 값을 보인다. 드라이버가 기준을 다시 잡은 줄이 있으면 그 값이다(방을 다시 읽은 실제 상태다)."""
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(2),
        failing_generations=(),
        stat_verdicts={1: (_DRIVE_RAISE_RULE,)},
    )
    lines = _jsonl(driven.log)
    second = [r for r in lines if r["kind"] == "turn"][-1]
    room = str(driven.room_id)

    def supplement(turn_count: int, value: float) -> dict[str, Any]:
        record = _supplement(room, second["roomAfter"], second["memory"], turn_count)
        record["statChanges"] = [{"name": DRIVE_STAT_NAME, "value": value}]
        record["roomAfter"]["stats"] = {**record["roomAfter"]["stats"], DRIVE_STAT_NAME: value}
        return record

    def changes() -> list[list[tuple[float | None, float, float | None]]]:
        detail = run_detail(_join(tmp_path))
        return [[(c.before, c.value, c.delta) for c in turn.driver_stat_changes] for turn in detail.turns]

    supplements = [supplement(3, 60.0), supplement(4, 65.0)]
    _write_jsonl(driven.log, [*lines, *supplements])
    known = [[(50.0, 80.0, 30.0)], [], [(80.0, 60.0, -20.0)], [(60.0, 65.0, 5.0)]]
    assert changes() == known

    lost = {
        **second,
        "done": False,
        "reply": "",
        "partialReply": "끊긴 조각이다.",
        "statChanges": [],
        "assistantMessageId": None,
        "roomAfter": None,
    }
    without_retry = [lost if r is second else r for r in lines]
    _write_jsonl(driven.log, [*without_retry, *supplements])
    assert changes() == [[(50.0, 80.0, 30.0)], [], [(None, 60.0, None)], [(60.0, 65.0, 5.0)]]
    # 바뀐 스탯이 없는 턴도 시작 값을 모를 수 있다 — 변화 칸이 비면 빈 시작 값으로는 알 수 없어 턴 요약이 따로 싣는다.
    quiet = {**supplements[0], "statChanges": []}
    _write_jsonl(driven.log, [*without_retry, quiet, supplements[1]])
    assert [turn.stats_start_known for turn in run_detail(_join(tmp_path)).turns] == [True, True, False, True]

    rebase = {
        "kind": "rebase",
        "roomId": room,
        "at": second["sentAt"],
        "reason": "유실 턴 뒤 기준 다시 잡기",
        "roomAfter": {**second["roomAfter"], "source": "refetch"},
    }
    _write_jsonl(driven.log, [*without_retry, rebase, *supplements])
    assert changes() == known


async def test_turn_summaries_carry_the_metric_flags_of_the_same_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """턴 목록은 응답 단위 플래그를 턴 요약에서 바로 읽는다. 그 값은 런 지표의 같은 턴 칸과 같아야 한다 — 따로 판정하면 자기복제처럼
    직전 응답에 달린 판정이 목록과 지표 탭에서 갈린다. 앞 턴이 유실되면 직전 응답은 그보다 앞의 응답이므로, 셋째 응답이 첫 응답으로
    시작하게 바꿔 직전 응답을 잘못 고르면 자기복제가 갈리게 한다. 응답이 없는 턴에는 플래그가 없다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 3)
    lines = _jsonl(driven.log)
    turns = {r["clientTurn"]: r for r in lines if r["kind"] == "turn"}
    first_reply = "첫 응답은 자기복제 판정이 보는 머리 쉰 글자보다 길게 쓴다. 바람이 분다. 등불이 흔들리고 골목 끝에서 문이 천천히 닫힌다."
    turns[1]["reply"] = first_reply
    turns[2].update(
        done=False,
        reply="",
        partialReply="끊긴 조각이다.",
        statChanges=[],
        ending=None,
        assistantMessageId=None,
        roomAfter=None,
    )
    turns[3]["reply"] = first_reply + " 그리고 다시 걷는다."
    _write_jsonl(driven.log, lines)

    joined = _join(tmp_path)
    detail = run_detail(joined)
    metrics = run_metrics(joined)

    by_turn = {m.turn: m.flags for m in metrics.turns}
    assert [(turn.turn, turn.flags) for turn in detail.turns] == [(1, by_turn[1]), (2, None), (3, by_turn[3])]
    third = detail.turns[2].flags
    assert third is not None and third.self_copy


def test_every_call_policy_row_gets_exactly_one_kind() -> None:
    """호출 뷰의 종류는 화면이 call_site 이름을 따로 해석하지 않게 서버가 준다. 표의 행마다 기대 종류를 나열하면 다른 작업이 엔진에
    호출 위치를 더할 때마다 이 도구의 테스트가 그 작업을 막으므로, 여기서는 분류가 호출 정책 표의 모든 행에 빠짐없이 정해진 종류
    하나를 내는지(표에 없는 이름은 `other`)만 보고 종류마다의 대표 분류는 아래 테스트가 지킨다."""
    kinds = set(get_args(CallSiteKind))
    assert [site for site in CALL_POLICIES if call_site_kind(site) not in kinds] == []
    assert call_site_kind("no_such_call_site") == "other"


# 종류마다 대표 호출 위치. 임베딩 둘은 호출 정책 표 밖 이름이고 나머지는 표의 행이다.
_REPRESENTATIVE_KINDS: dict[str, CallSiteKind] = {
    "chat_generate": "generation",
    "replay_generate": "generation",
    "chat_stat_judgment": "judgment",
    "chat_ending_judgment": "judgment",
    "chat_situational_image": "judgment",
    "chat_scene_judgment": "judgment",
    "chat_memory_summary": "background",
    "chat_memory_episode": "background",
    "chat_memory_fact": "background",
    "chat_memory_impression": "background",
    "chat_memory_query_embedding": "embedding",
    "chat_memory_embedding": "embedding",
}


def test_representative_call_sites_keep_their_kind() -> None:
    """종류의 근거는 호출 정책 표의 행(스트리밍으로 부르면 생성, 판정 종류가 있으면 판정, 판정 종류 없이 모델 설정이 있으면 기억
    요약·추출·인상이라 백그라운드)과 표 밖 임베딩 호출 이름이다. 대표 행은 표에 있어야 한다 — 엔진에서 사라지면 이 도구가 알아야
    할 변화다."""
    assert {site for site, kind in _REPRESENTATIVE_KINDS.items() if kind != "embedding"} <= set(CALL_POLICIES)
    assert {site: call_site_kind(site) for site in _REPRESENTATIVE_KINDS} == _REPRESENTATIVE_KINDS


async def test_call_views_and_turn_costs_leave_unknown_costs_empty_instead_of_zero(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """원가를 모르는 자리를 0 으로 채우면 공짜 호출·공짜 턴으로 읽힌다. 입력 토큰이 기록되지 않은 호출(그림을 싣는 판정, 시간 안에
    오지 않은 질의 임베딩)은 호출 원가가 비고, 턴 기록 행이 하나도 붙지 않은 턴은 턴 원가가 빈다. 단가 없는 호출이나 토큰 없는
    호출이 섞인 턴·행은 합을 내되 하한이라고 표시한다 — 합은 원가 리포트와 같은 단가 함수 값의 합이라 토큰 없는 호출도 기록된
    칸만큼은 들어간다. 호출 뷰는 화면이 call_site 이름을 해석하지 않게 종류를 싣고, 새 입력 토큰(입력 − 캐시 읽기 − 캐시 쓰기,
    음수면 0)은 단가 함수가 정가를 곱하는 몫과 같아야 한다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 4)
    generation: dict[str, Any] = {
        "callSite": "chat_generate",
        "model": "gemini-3.5-flash-lite",
        "promptTokens": 1200,
        "cachedTokens": 200,
        "cacheWriteTokens": None,
        "outputTokens": 300,
        "thoughtsTokens": 50,
        "firstTokenMs": 900,
        "streamFirstTokenMs": 700,
    }
    judgment: dict[str, Any] = {
        "callSite": "chat_stat_judgment",
        "model": "claude-haiku-5-5",
        "promptTokens": 800,
        "cachedTokens": 100,
        "cacheWriteTokens": 300,
        "outputTokens": 40,
        "thoughtsTokens": None,
    }
    over_cached: dict[str, Any] = {
        "callSite": "chat_scene_judgment",
        "model": "claude-haiku-5-5",
        "promptTokens": 10,
        "cachedTokens": 50,
        "cacheWriteTokens": 0,
        "outputTokens": 5,
        "thoughtsTokens": None,
    }
    image_without_input: dict[str, Any] = {
        "callSite": "chat_situational_image",
        "model": "gemini-3.5-flash-lite",
        "promptTokens": None,
        "cachedTokens": None,
        "cacheWriteTokens": None,
        "outputTokens": 30,
        "thoughtsTokens": None,
    }
    embedding_timeout: dict[str, Any] = {
        "callSite": "chat_memory_query_embedding",
        "model": "voyage-4-lite",
        "dims": 1024,
        "promptTokens": None,
        "latencyMs": 1500,
        "outcome": "timeout",
    }
    unpriced: dict[str, Any] = {
        "callSite": "chat_ending_judgment",
        "model": "no-such-model",
        "promptTokens": 10,
        "cachedTokens": 0,
        "cacheWriteTokens": None,
        "outputTokens": 1,
        "thoughtsTokens": None,
    }
    calls_by_turn = {
        1: [generation, judgment, over_cached],
        2: [generation, image_without_input, embedding_timeout],
        3: [generation, unpriced],
    }
    for number, calls in calls_by_turn.items():
        await db_session.execute(
            sa.update(ChatTurn)
            .where(ChatTurn.chat_room_id == driven.room_id, ChatTurn.turn_number == number)
            .values(llm_calls=calls)
        )
    stat_defs, rows = await _db_export(db_session, driven)
    _write_export(driven, stat_defs, [row for row in rows if row["turn_number"] != 4])

    joined = _join(tmp_path)
    detail = run_detail(joined)

    records = {number: turn_detail(joined, number).attempts[0].chat_turns for number in (1, 2, 3)}
    assert [
        [
            (c.call_site, c.kind, c.new_input_tokens, c.usd is None, c.missing_tokens)
            for r in records[n]
            for c in r.calls
        ]
        for n in (1, 2, 3)
    ] == [
        [
            ("chat_generate", "generation", 1000, False, False),
            ("chat_stat_judgment", "judgment", 400, False, False),
            ("chat_scene_judgment", "judgment", 0, False, False),
        ],
        [
            ("chat_generate", "generation", 1000, False, False),
            ("chat_situational_image", "judgment", None, True, True),
            ("chat_memory_query_embedding", "embedding", None, True, True),
        ],
        [
            ("chat_generate", "generation", 1000, False, False),
            ("chat_ending_judgment", "judgment", 10, True, False),
        ],
    ]
    priced = [
        (call, view)
        for n in (1, 2, 3)
        for record in records[n]
        for call, view in zip(record.row["llm_calls"], record.calls, strict=True)
        if view.usd is not None
    ]
    assert len(priced) == 5
    for call, view in priced:
        price = pricing.MODEL_PRICES[view.model]
        assert view.new_input_tokens is not None
        assert view.usd == call_cost(call).usd
        assert view.usd == pytest.approx(
            (
                view.new_input_tokens * price.input_usd_per_million
                + (view.cached_tokens or 0) * price.cached_input_usd_per_million
                + (view.cache_write_tokens or 0) * price.cache_write_usd_per_million
                + ((view.output_tokens or 0) + (view.thoughts_tokens or 0)) * price.output_usd_per_million
            )
            / 1_000_000
        )

    def summed(calls: list[dict[str, Any]]) -> float:
        return sum(c.usd for c in map(call_cost, calls) if c.usd is not None)

    costs = [turn.cost_usd for turn in detail.turns]
    assert costs[3] is None
    assert costs[:3] == pytest.approx([summed(calls_by_turn[n]) for n in (1, 2, 3)])
    assert summed(calls_by_turn[2]) > summed([generation])
    assert [turn.cost_is_lower_bound for turn in detail.turns] == [False, True, True, False]
    assert [record.cost_is_lower_bound for n in (1, 2, 3) for record in records[n]] == [False, True, True]
    assert detail.cost is not None
    assert (detail.cost.unpriced_calls, detail.cost.missing_token_calls) == (1, 2)
    assert detail.cost.total_usd == pytest.approx(sum(summed(calls_by_turn[n]) for n in (1, 2, 3)))


async def test_record_limits_name_the_slot_each_sentence_stands_in_for(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """기록 한계 문장은 값이 있어야 할 자리에 놓인다 — 화면이 문장 글을 보고 자리를 짐작하면 문장을 고칠 때 자리가 말없이 바뀐다.
    문장마다 자리 이름을 함께 싣고 글은 그대로 둔다. 판정 응답·판정 지연은 늘, 백그라운드 토큰은 그 턴에 백그라운드 줄이 있을 때,
    내보내기 필요는 턴 기록 파일이 없을 때, 프롬프트 덤프는 덤프가 없을 때만 실린다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 4)

    def slots(number: int) -> list[tuple[str, str]]:
        return [(limit.slot, limit.text) for limit in turn_detail(_join(tmp_path), number).record_limits]

    always = [("judgmentResponse", JUDGMENT_RESULT_LIMIT), ("judgmentLatency", LATENCY_LIMIT)]
    folded = [turn.number for turn in _join(tmp_path).turns if turn.background_dumps]
    assert folded, "요약 접기가 돌지 않았다 — 백그라운드 자리를 보지 못한다"
    assert 1 not in folded
    assert slots(1) == [*always, ("exportNeeded", EXPORT_NEEDED_LIMIT)]
    assert slots(folded[0]) == [*always, ("backgroundTokens", BACKGROUND_LIMIT), ("exportNeeded", EXPORT_NEEDED_LIMIT)]

    stat_defs, rows = await _db_export(db_session, driven)
    _write_export(driven, stat_defs, rows)
    driven.dump.unlink()
    assert slots(1) == [*always, ("promptDump", NO_DUMP_LIMIT)]


async def test_the_list_item_marks_a_lower_bound_cost_like_the_turn_summaries(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """목록의 단가 없는 호출 수만으로는 입력 토큰이 기록되지 않은 호출을 모른다 — 그런 호출만 있는 런은 단가 없는 호출이 0 이라
    목록이 정확한 원가로 보이는데 턴 요약은 하한이라고 말한다. 목록 항목도 런 원가 합과 같은 행으로 같은 판정을 실어야 두 화면이
    갈리지 않는다. 모든 호출에 단가와 토큰이 있으면 하한이 아니다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 2)
    priced: dict[str, Any] = {
        "callSite": "chat_generate",
        "model": "gemini-3.5-flash-lite",
        "promptTokens": 900,
        "outputTokens": 120,
    }
    tokenless: dict[str, Any] = {
        "callSite": "chat_situational_image",
        "model": "gemini-3.5-flash-lite",
        "promptTokens": None,
        "outputTokens": 30,
    }

    async def export(second_turn_calls: list[dict[str, Any]]) -> None:
        for number, calls in ((1, [priced]), (2, second_turn_calls)):
            await db_session.execute(
                sa.update(ChatTurn)
                .where(ChatTurn.chat_room_id == driven.room_id, ChatTurn.turn_number == number)
                .values(llm_calls=calls)
            )
        _write_export(driven, *(await _db_export(db_session, driven)))

    await export([priced])
    [bundle] = discover_bundles(tmp_path)
    exact = list_entry(bundle)
    assert (exact.cost_is_lower_bound, exact.unpriced_calls) == (False, 0)

    await export([priced, tokenless])
    item = list_entry(bundle)
    detail = run_detail(_join(tmp_path))
    assert [turn.cost_is_lower_bound for turn in detail.turns] == [False, True]
    assert (item.cost_is_lower_bound, item.unpriced_calls) == (True, 0)
    assert detail.run.cost_is_lower_bound is item.cost_is_lower_bound
    assert item.cost_is_lower_bound == any(turn.cost_is_lower_bound for turn in detail.turns)


async def test_a_status_block_fenced_at_the_end_of_a_complete_reply_is_not_a_truncated_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """작품 규칙이 응답 끝에 상태창을 코드 블록으로 붙이게 하면 응답의 마지막 줄은 닫는 펜스다. 그 펜스를 문장으로 읽으면 완결
    응답이 전부 절단이 된다 — 실제 드라이버 런의 응답에 상태창을 실어, 드라이버 로그의 응답이 펜스로 끝나는데도 턴 요약 플래그가
    절단이 아니고, 길이는 상태창을 뺀 본문이며 상태창 몫은 따로 실림을 본다."""
    tail = "\n\n```\n장소 | 학생회관 동아리방\n시간 | 9월 30일 화요일 밤\n```"
    driven = await drive_room(
        db_session, monkeypatch, tmp_path, script=says(2), failing_generations=(), stat_verdicts={}, reply_tail=tail
    )

    detail = run_detail(_join(tmp_path))

    replies = [r["reply"] for r in _jsonl(driven.log) if r["kind"] == "turn"]
    assert len(replies) == 2 and all(reply.endswith(tail) for reply in replies)
    flags = [turn.flags for turn in detail.turns]
    assert all(flag is not None for flag in flags)
    assert [(f.truncated, f.length, f.status_block_length) for f in flags if f is not None] == [
        (False, len(reply) - len(tail), len(tail)) for reply in replies
    ]


async def test_the_sent_model_comes_from_the_call_records_before_the_room_setting(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """모델을 바꿔 돌린 런에서는 방 스냅숏의 `effectiveChatModel`(방 설정에서 서버가 쓰겠다고 한 값)이 실제로 보낸 모델과 다르다.
    그래서 보낸 모델은 호출 기록에서 찾는다 — 덤프 생성 줄의 보낸 id 가 먼저, 덤프에 생성 줄이 없으면 턴 기록 파일의 행 전부에서
    행마다 생성 호출 칸의 모델(판정 호출의 모델은 아니다), 생성 호출이 기록되지 않은 행은 그 행의 `chat_model` 이다. 그 방을 쓴
    모델을 보이는 칸이라 시도에 붙지 않은 행도 센다. 스냅숏의 값은 설정값으로 따로 싣고 보낸 모델 칸에 섞지 않는다. 실제 드라이버
    런의 덤프 생성 줄을 설정과 다른 모델로 생성한 것처럼 바꿔 쓴다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 2)
    dump = _jsonl(driven.dump)
    generation_lines = [r for r in dump if r.get("kind") == "generation"]
    for record in generation_lines:
        record["model"] = "lab-sent-model"
    _write_jsonl(driven.dump, dump)
    stat_defs, rows = await _db_export(db_session, driven)
    rows[0]["chat_model"] = "lab-row-model-of-a-recorded-call"
    rows[0]["llm_calls"] = [
        {"callSite": "chat_generate", "model": "lab-call-model", "promptTokens": 10, "outputTokens": 1},
        {"callSite": "chat_stat_judgment", "model": "lab-judge-model", "promptTokens": 10, "outputTokens": 1},
    ]
    rows[1]["chat_model"] = "lab-row-model"
    stray = {
        **copy.deepcopy(rows[-1]),
        "id": uuid.uuid4(),
        "assistant_message_id": uuid.uuid4(),
        "chat_model": "lab-stray-model",
    }
    _write_export(driven, stat_defs, [*rows, stray])
    snapshot_model = next(r for r in _jsonl(driven.snapshot_log) if r["kind"] == "roomStatic")["effectiveChatModel"]

    def models() -> tuple[list[str], str | None, list[str]]:
        [bundle] = discover_bundles(tmp_path)
        item = list_entry(bundle)
        detail_run = run_detail(_join(tmp_path)).run
        assert (detail_run.sent_chat_models, detail_run.sent_chat_models_from, detail_run.configured_chat_models) == (
            item.sent_chat_models,
            item.sent_chat_models_from,
            item.configured_chat_models,
        )
        return item.sent_chat_models, item.sent_chat_models_from, item.configured_chat_models

    assert len(generation_lines) == 2
    assert isinstance(snapshot_model, str) and snapshot_model != "lab-sent-model"
    assert models() == (["lab-sent-model"], "dump", [snapshot_model])
    driven.dump.unlink()
    assert models() == (["lab-call-model", "lab-row-model", "lab-stray-model"], "chatTurns", [snapshot_model])
    (driven.log.parent / CHAT_TURNS_NAME).unlink()
    assert models() == ([], None, [snapshot_model])


async def test_a_chat_turns_file_beside_a_log_without_message_ids_is_a_caution_not_unmatched_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`assistantMessageId` 이전 형식의 턴 줄에는 행을 붙일 응답 id 가 없어, 턴 기록 파일을 짝으로 두면 이을 수 없다. 이어 보면 모든
    행이 짝 없는 기록이 되어 불일치가 행 수만큼 쌓이는데, 결합이 어긋난 것이 아니라 처음부터 이을 수 없는 형식이다 — 행을 잇지 않고
    주의 하나만 달며, 붙은 행이 없으니 원가를 0 원으로 내지 않는다. 덤프가 없을 때 보낸 모델 칸은 행을 잇지 않아도 파일의 행으로
    채운다. 이 형식은 내보내기를 거부하므로, 턴 기록 파일이 없을 때도 내보내라는 기록 한계를 싣지 않는다."""
    driven = await _plain_run(db_session, monkeypatch, tmp_path, 2)
    stat_defs, rows = await _db_export(db_session, driven)
    rows[0]["chat_model"], rows[1]["chat_model"] = "lab-model-b", "lab-model-a"
    _write_export(driven, stat_defs, rows)
    driven.snapshot_log.unlink()
    lines = _jsonl(driven.log)
    for record in lines:
        if record["kind"] == "turn":
            record.pop("shortcutId", None)
            record.pop("assistantMessageId", None)
    _write_jsonl(driven.log, lines)

    joined = _join(tmp_path)
    detail = run_detail(joined)

    assert joined.bundle.format == "preMessageId" and len(rows) == 2
    assert detail.mismatches == []
    assert [c.kind for c in joined.cautions if c.kind != "placementEstimated"] == ["chatTurnsNotJoined"]
    assert joined.unmatched_rows == [] and detail.unmatched_rows == []
    assert [attempt.chat_turn_rows for turn in joined.turns for attempt in turn.attempts] == [[], []]
    assert (detail.cost, detail.run.cost_usd, detail.run.has_chat_turns) == (None, None, True)
    driven.dump.unlink()
    without_dump = run_detail(_join(tmp_path)).run
    assert (without_dump.sent_chat_models, without_dump.sent_chat_models_from) == (
        ["lab-model-a", "lab-model-b"],
        "chatTurns",
    )
    (driven.log.parent / CHAT_TURNS_NAME).unlink()
    without_file = _join(tmp_path)
    assert without_file.chat_turns is None
    assert "exportNeeded" not in [limit.slot for limit in turn_detail(without_file, 1).record_limits]
