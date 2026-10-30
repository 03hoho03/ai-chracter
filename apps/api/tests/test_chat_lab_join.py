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
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from analyze_chat_probe import reply_flags
from api.db.models import ChatTurn, StatDef
from api.llm import pricing
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
from chat_lab.report import run_detail, run_metrics, turn_detail
from chat_lab.schemas import RunMetrics, TurnMetrics
from driver_harness import (
    _DRIVE_RAISE_RULE,
    DRIVE_HIDDEN_RULE,
    DRIVE_HIDDEN_STAT_NAME,
    DRIVE_STAT_NAME,
    DrivenRoom,
    drive_room,
    says,
)
from replay.logs import generation_records, load_driver_logs, load_dump, turn_line


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
