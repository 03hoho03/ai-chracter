"""측정이 실제로 돌았나 — 질의 임베딩 성공 비율(프로브 행), 장면 아는 사람 가림과 따옴표 안 이름 재분류(필터 재계산, 서버 함수
그대로)를 갈래별로 세고, 판정·집계 명령은 그 수가 미리 고정한 문턱에 못 미치면 집계를 거부한다. 문안·이름은 전부 지어낸 것이다."""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import memory_recall
from api.chat.memory_facts import fact_rows_statement
from api.chat.memory_knowledge import KnowledgeScope, scene_for_turn
from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import PromptNames
from api.db.models import ChatRoomMemorySnapshot
from factories import Room, _make_memory_episode, _make_memory_fact, _open_room
from memory_eval import knowledge_recompute as kr
from memory_eval import ran_gate as rg
from memory_eval.runtime import ARMS

NAMES = PromptNames(persona_name=None, char_name=None)
USER_LABEL = "사용자"
# 질문 턴의 직전 응답 — 아는 사람(민수)이 대사 따옴표 안에서만 불린다.
QUOTED_ONLY = '"민수야, 거기 있어?" 하고 불렀지만 대답이 없었다.'
QUESTION = "밀알당 기억나?"
TURNS = [{"user": "누구 불러 봐", "reply": QUOTED_ONLY}, {"user": QUESTION, "reply": "기억나."}]


async def _room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, *, episodes: int = 6, secret: bool = True
) -> tuple[Room, MessageKey, uuid.UUID]:
    """6턴 스토리 방 — 턴 6 응답까지 접은 스냅샷 하나, 장면 `episodes` 개(턴 1부터), 턴 3 장면과 근거가 겹치는 사실 하나(`secret`
    이면 민수만 아는 비밀, 아니면 아는 사람 없음)."""
    room = await _open_room(db_client, db_session, turns=6, lane="story")
    cursor_message = room.turns[6][1]
    snapshot = ChatRoomMemorySnapshot(
        chat_room_id=room.room_id, cursor_created_at=cursor_message.created_at, cursor_message_id=cursor_message.id,
        summary_text="지어낸 요약", source="auto",
    )  # fmt: skip
    db_session.add(snapshot)
    await db_session.flush()
    secret_scene = uuid.uuid4()
    for turn in range(1, episodes + 1):
        start, end = room.turns[turn]
        db_session.add(
            _make_memory_episode(
                room.room_id, snapshot.id, ordinal=turn, start_created_at=start.created_at,
                start_message_id=start.id, end_created_at=end.created_at, end_message_id=end.id, start_turn=turn,
                end_turn=turn, title=f"지어낸 장면 {turn}", detail=f"지어낸 일 {turn}", nouns=[f"낱말{turn}"],
                **({"id": secret_scene} if turn == 3 else {}),
            )
        )  # fmt: skip
    start, end = room.turns[3]
    db_session.add(
        _make_memory_fact(
            room.room_id, snapshot.id, kind="fact", subject="유나", object=None, attribute="비밀",
            fact_key="fact|유나|비밀", value="지어낸 비밀", asserted_by="narration", known_by=["민수"] if secret else None,
            start_created_at=start.created_at, start_message_id=start.id, end_created_at=end.created_at,
            end_message_id=end.id, start_turn=3, end_turn=3,
        )
    )  # fmt: skip
    await db_session.flush()
    return room, (cursor_message.created_at, cursor_message.id), secret_scene


async def _server_hidden(
    db_session: AsyncSession, room: Room, cursor: MessageKey, *, ignore_quoted: bool
) -> set[uuid.UUID]:
    """서버 회상이 그 질문 턴에 가리는 장면 — 하네스 재계산과 견줄 기준."""
    base = await kr.room_history(db_session, room.room_id)
    history, question = kr.probe_history(base, TURNS)
    rows = (await db_session.execute(memory_recall._candidate_statement(room.room_id, cursor))).all()
    return await memory_recall._hidden_episodes(
        db_session, rows, room_id=room.room_id, cursor=cursor, history=history, user_content=question, names=NAMES,
        scope=KnowledgeScope(user_label=USER_LABEL, ignore_quoted_reply_names=ignore_quoted),
    )  # fmt: skip


async def _ran(db_session: AsyncSession, room: Room, cursor: MessageKey, arm: str) -> dict[str, Any]:
    return await kr.recompute_ran(
        db_session, room.room_id, cursor=cursor, turns=TURNS, names=NAMES, user_label=USER_LABEL,
        arm_overrides=ARMS[arm],
    )  # fmt: skip


async def test_hidden_and_reclassified_counts_match_the_server_functions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, cursor, secret_scene = await _room(db_client, db_session)

    filtered = await _ran(db_session, room, cursor, "b1-B1")
    assert filtered["hiddenEpisodeIds"] == [str(secret_scene)]
    assert set(filtered["hiddenEpisodeIds"]) == {
        str(i) for i in await _server_hidden(db_session, room, cursor, ignore_quoted=True)
    }
    assert filtered["hiddenEpisodes"] == 1

    facts = list((await db_session.scalars(fact_rows_statement(room.room_id, cursor))).all())
    history, question = kr.probe_history(await kr.room_history(db_session, room.room_id), TURNS)

    def scene(ignore_quoted: bool) -> frozenset[str]:
        return scene_for_turn(
            facts, KnowledgeScope(user_label=USER_LABEL, ignore_quoted_reply_names=ignore_quoted), history=history,
            user_content=question, names=NAMES,
        )  # fmt: skip

    assert filtered["reclassifiedNames"] == sorted(scene(False) - scene(True)) == ["민수"]
    assert filtered["reclassified"] == 1

    # 필터를 끈 회상 갈래 — 서버는 따옴표 안 이름도 장면 인물로 세므로 민수가 장면에 있고 아무것도 가리지 않는다.
    unfiltered = await _ran(db_session, room, cursor, "b1-A1")
    assert await _server_hidden(db_session, room, cursor, ignore_quoted=False) == set()
    assert unfiltered["hiddenEpisodes"] == 0 and unfiltered["reclassified"] == 0


async def test_arms_with_the_switches_off_count_zero(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, cursor, _ = await _room(db_client, db_session)
    off = await _ran(db_session, room, cursor, "b1-A0")
    assert off == {"hiddenEpisodeIds": [], "hiddenEpisodes": 0, "reclassifiedNames": [], "reclassified": 0}
    # 회상·사실 주입이 꺼진 필터 갈래 — 서버가 장면 인물을 세는 경로가 없으므로 둘 다 0.
    marking = await _ran(db_session, room, cursor, "b1-A0M")
    assert marking == off


async def test_below_the_recall_minimum_the_recall_path_counts_nothing_but_the_fact_path_still_does(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """후보 장면이 회상 하한 아래면 서버 회상은 가림까지 가지 않는다. 사실 주입을 켠 갈래는 사실 섹션이 비밀 행으로 필터를 걸며
    장면 인물을 세므로 재분류가 남는다."""
    room, cursor, _ = await _room(db_client, db_session, episodes=memory_recall.MIN_EPISODES - 1)
    recall_only = await _ran(db_session, room, cursor, "b1-B1")
    assert recall_only["hiddenEpisodes"] == 0 and recall_only["reclassified"] == 0
    with_facts = await _ran(db_session, room, cursor, "b1-B2")
    assert with_facts["hiddenEpisodes"] == 0 and with_facts["reclassifiedNames"] == ["민수"]


async def test_without_any_known_by_the_server_skips_the_scene_and_nothing_is_counted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, cursor, _ = await _room(db_client, db_session, secret=False)
    for arm in ("b1-B1", "b1-B2"):
        ran = await _ran(db_session, room, cursor, arm)
        assert ran["hiddenEpisodes"] == 0 and ran["reclassified"] == 0, arm


# --- 문턱 ------------------------------------------------------------------------------------------------------------

CP = 300


def _probe(
    arm: str, outcomes: list[str], *, item: str = "q1", status: str = "accept", facts: list[int] | None = None
) -> dict[str, Any]:
    """`facts` 는 턴마다 실린 사실 행 수(없으면 턴마다 하나)."""
    turns = [{"user": "u", "reply": "r"} for _ in outcomes]
    calls = [{"callSite": "chat_memory_query_embedding", "outcome": o} for o in outcomes if o != "none"]
    loaded = [[{"factId": f"f{i}", "chars": 10} for i in range(n)] for n in (facts or [1] * len(outcomes))]
    return {"arm": arm, "item": item, "checkpoint": CP, "status": status, "turns": turns, "queryEmbeddings": calls,
            "memoryFacts": loaded}  # fmt: skip


def _recomputed(arm: str, *, hidden: int, reclassified: int, item: str = "q1") -> dict[str, Any]:
    return {"arm": arm, "item": item, "checkpoint": CP, "hiddenEpisodes": hidden, "reclassified": reclassified}


GOOD_RECOMPUTE = [_recomputed(arm, hidden=1, reclassified=1) for arm in ("b1-B1", "b1-B1E", "b1-B2")]


def _probes(ok: int, total: int) -> list[dict[str, Any]]:
    return [_probe(arm, ["ok"] * ok + ["failed"] * (total - ok)) for arm in rg.GATED_ARMS]


def test_reclassification_is_gated_only_where_the_server_counts_scene_people() -> None:
    assert rg.RECLASSIFIED_ARMS == ("b1-B1", "b1-B1E", "b1-B2")
    assert "b1-A0M" not in rg.GATED_ARMS


def test_query_embedding_ratio_counts_missing_calls_as_not_ok_and_skips_unaccepted_rows() -> None:
    rows = [
        _probe("b1-B2", ["ok", "timeout"]),
        _probe("b1-B2", ["ok", "none"], item="q2"),
        _probe("b1-B2", ["failed"], item="q3", status="unprobeable"),
    ]
    assert rg.query_embedding_ok(rows)["b1-B2"] == {"ok": 2, "turns": 4, "ratio": 0.5}


def test_gate_passes_at_exactly_the_embedding_threshold() -> None:
    rg.require_ran(set(rg.GATED_ARMS), probe_rows=_probes(19, 20), recompute_rows=GOOD_RECOMPUTE, facts_loaded_min=20)


def test_gate_refuses_below_the_embedding_threshold_naming_arm_metric_and_value() -> None:
    with pytest.raises(SystemExit) as stop:
        rg.require_ran(set(rg.GATED_ARMS), probe_rows=_probes(18, 20), recompute_rows=GOOD_RECOMPUTE, facts_loaded_min=1)
    message = str(stop.value.code)
    assert "b1-B1E" in message and "b1-B2" in message and "queryEmbeddingOk" in message and "0.9" in message


def _without(arm: str, *, hidden: int = 1, reclassified: int = 1) -> list[dict[str, Any]]:
    return [
        *(r for r in GOOD_RECOMPUTE if r["arm"] != arm),
        _recomputed(arm, hidden=hidden, reclassified=reclassified),
    ]


@pytest.mark.parametrize(
    ("arm", "metric", "rows"),
    [
        pytest.param("b1-B1", "hiddenEpisodes", _without("b1-B1", hidden=0), id="hidden-B1"),
        pytest.param("b1-B1E", "hiddenEpisodes", _without("b1-B1E", hidden=0), id="hidden-B1E"),
        pytest.param("b1-B2", "hiddenEpisodes", _without("b1-B2", hidden=0), id="hidden-B2"),
        pytest.param("b1-B1", "reclassified", _without("b1-B1", reclassified=0), id="reclassified-B1"),
        pytest.param("b1-B1E", "reclassified", _without("b1-B1E", reclassified=0), id="reclassified-B1E"),
        pytest.param("b1-B2", "reclassified", _without("b1-B2", reclassified=0), id="reclassified-B2"),
    ],
)
def test_gate_refuses_when_a_recompute_total_is_zero(arm: str, metric: str, rows: list[dict[str, Any]]) -> None:
    with pytest.raises(SystemExit) as stop:
        rg.require_ran(set(rg.GATED_ARMS), probe_rows=_probes(20, 20), recompute_rows=rows, facts_loaded_min=1)
    assert f"{arm} {metric}=0" in str(stop.value.code)


def test_gate_ignores_arms_it_has_no_threshold_for() -> None:
    rg.require_ran({"b1-A0", "b1-A0M", "b1-A1", "A2", "B2"}, probe_rows=[], recompute_rows=[], facts_loaded_min=None)


def test_facts_loaded_turns_count_only_turns_whose_recorded_fact_list_is_not_empty() -> None:
    rows = [
        _probe("b1-B2", ["ok", "ok"], facts=[0, 3]),
        _probe("b1-B2", ["ok"], item="q2", facts=[2]),
        _probe("b1-B2", ["ok"], item="q3", status="unprobeable", facts=[5]),
        _probe("b1-B1E", ["ok"], item="q4", facts=[0]),
    ]
    assert rg.facts_loaded_turns(rows) == {"b1-B1E": {"loaded": 0, "turns": 1}, "b1-B2": {"loaded": 2, "turns": 3}}


def test_the_fact_arm_is_gated_and_the_current_production_arm_is_not() -> None:
    """사실 주입을 켠 갈래만 사실 섹션 실림 턴 수 문턱을 받는다 — 사실 주입이 꺼진 갈래는 섹션이 비어야 맞다."""
    assert rg.FACTS_ARMS == ("b1-B2",)
    assert "b1-B2" in rg.GATED_ARMS
    rg.require_ran({"b1-B1E"}, probe_rows=_probes(20, 20), recompute_rows=GOOD_RECOMPUTE, facts_loaded_min=None)


def _fact_probes(loaded: int, total: int) -> list[dict[str, Any]]:
    return [_probe(arm, ["ok"] * total, facts=[1] * loaded + [0] * (total - loaded)) for arm in rg.GATED_ARMS]


def test_gate_passes_at_exactly_the_facts_loaded_threshold_and_refuses_one_below() -> None:
    rg.require_ran(set(rg.GATED_ARMS), probe_rows=_fact_probes(7, 20), recompute_rows=GOOD_RECOMPUTE, facts_loaded_min=7)
    with pytest.raises(SystemExit) as stop:
        rg.require_ran(
            set(rg.GATED_ARMS), probe_rows=_fact_probes(6, 20), recompute_rows=GOOD_RECOMPUTE, facts_loaded_min=7
        )
    assert "b1-B2 factsLoadedTurns=6 (문턱 7)" in str(stop.value.code)


def test_gate_refuses_when_no_fact_section_was_ever_loaded() -> None:
    with pytest.raises(SystemExit) as stop:
        rg.require_ran(
            set(rg.GATED_ARMS), probe_rows=_fact_probes(0, 20), recompute_rows=GOOD_RECOMPUTE, facts_loaded_min=1
        )
    assert "b1-B2 factsLoadedTurns=0" in str(stop.value.code)


def test_gate_refuses_the_fact_arm_without_a_facts_threshold_naming_the_flag() -> None:
    """문턱은 봉인 문서가 정하는 실행 인자다 — 기본값이 없어 주지 않으면 사실 주입 갈래를 집계하지 않는다."""
    with pytest.raises(SystemExit) as stop:
        rg.require_ran(
            set(rg.GATED_ARMS), probe_rows=_fact_probes(20, 20), recompute_rows=GOOD_RECOMPUTE, facts_loaded_min=None
        )
    assert "--ran-facts-min" in str(stop.value.code)


def _aggregated(arms: list[str], items: tuple[str, ...] = ("q1",)) -> list[dict[str, Any]]:
    return [
        {"arm": arm, "item": item, "checkpoint": CP, "kind": "recall", "judged": "pass"}
        for arm in arms
        for item in items
    ]


def test_aggregated_rows_missing_from_the_probe_rows_are_refused_with_count_and_first_keys() -> None:
    rows = _aggregated(["b1-B2"], ("q1", "q2", "q3"))
    with pytest.raises(SystemExit) as stop:
        rg.require_covered(
            rows,
            probe_rows=_probes(20, 20),
            recompute_rows=[
                *GOOD_RECOMPUTE,
                *(_recomputed("b1-B2", hidden=1, reclassified=1, item=i) for i in ("q2", "q3")),
            ],
        )
    message = str(stop.value.code)
    assert "--ran-probes" in message and "--ran-recompute" not in message
    assert "2개" in message and "b1-B2:q2:300" in message


def test_aggregated_rows_missing_from_the_recompute_rows_are_refused() -> None:
    rows = _aggregated(["b1-B1"])
    with pytest.raises(SystemExit) as stop:
        rg.require_covered(rows, probe_rows=_probes(20, 20), recompute_rows=_without("b1-B1")[:-1])
    message = str(stop.value.code)
    assert "--ran-recompute" in message and "b1-B1:q1:300" in message


def test_unaccepted_aggregated_rows_need_no_recompute_row_and_covered_rows_pass() -> None:
    rows = [
        *_aggregated(["b1-B1", "b1-B2"]),
        {"arm": "b1-B1", "item": "q9", "checkpoint": CP, "status": "unprobeable", "scored": False},
    ]
    probes = [*_probes(20, 20), _probe("b1-B1", ["failed"], item="q9", status="unprobeable")]
    rg.require_covered(rows, probe_rows=probes, recompute_rows=GOOD_RECOMPUTE)


def _judged(path: Path, arms: list[str]) -> Path:
    path.write_text(json.dumps(_aggregated(arms)), encoding="utf-8")
    return path


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_judge_summary_refuses_before_aggregating_when_the_gate_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    judged = _judged(tmp_path / "judged.json", ["b1-A0", "b1-B2"])
    recompute = tmp_path / "recompute.json"
    recompute.write_text(json.dumps(GOOD_RECOMPUTE), encoding="utf-8")
    base = ["--run", str(tmp_path), "judge-summary", "--judged", str(judged)]

    assert main(base) == 2
    assert "--ran-probes" in capsys.readouterr().err

    low = _jsonl(tmp_path / "low.jsonl", _probes(18, 20))
    # 사실 실림 문턱은 채워 준다 — 문턱 인자 누락(사용 오류)이 게이트보다 먼저 거부되므로, 그 거부는 아래에서 따로 본다.
    assert main([*base, "--ran-probes", str(low), "--ran-recompute", str(recompute), "--ran-facts-min", "20"]) == 2
    captured = capsys.readouterr()
    assert "b1-B2 queryEmbeddingOk" in captured.err and captured.out == ""

    good = _jsonl(tmp_path / "good.jsonl", _probes(20, 20))
    ran = [*base, "--ran-probes", str(good), "--ran-recompute", str(recompute)]
    assert main(ran) == 2
    assert "--ran-facts-min" in capsys.readouterr().err
    assert main([*ran, "--ran-facts-min", "21"]) == 2
    assert "b1-B2 factsLoadedTurns=20 (문턱 21)" in capsys.readouterr().err
    assert main([*ran, "--ran-facts-min", "20"]) == 0
    assert "recall" in capsys.readouterr().out


def test_judge_summary_refuses_aggregated_rows_the_ran_inputs_do_not_cover(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    judged = tmp_path / "judged.json"
    judged.write_text(json.dumps(_aggregated(["b1-B2"], ("q1", "q7"))), encoding="utf-8")
    recompute = tmp_path / "recompute.json"
    recompute.write_text(
        json.dumps([*GOOD_RECOMPUTE, _recomputed("b1-B2", hidden=1, reclassified=1, item="q7")]), encoding="utf-8"
    )
    probes = _jsonl(tmp_path / "good.jsonl", _probes(20, 20))
    code = main(
        ["--run", str(tmp_path), "judge-summary", "--judged", str(judged), "--ran-probes", str(probes),
         "--ran-recompute", str(recompute)]
    )  # fmt: skip
    assert code == 2
    captured = capsys.readouterr()
    assert "--ran-probes 에 없는 집계 행 1개" in captured.err and "b1-B2:q7:300" in captured.err
    assert captured.out == ""


def test_judge_summary_of_runs_without_gated_arms_needs_no_ran_inputs(tmp_path: Path) -> None:
    from memory_eval_cli import main

    judged = _judged(tmp_path / "judged.json", ["A2", "B2", "b1-A0M"])
    assert main(["--run", str(tmp_path), "judge-summary", "--judged", str(judged)]) == 0


def test_bundle_verdict_refuses_before_reading_the_seal_when_the_gate_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    judged = _judged(tmp_path / "judged.json", ["b1-B1"])
    scores = _judged(tmp_path / "scores.json", ["b1-B1"])
    recompute = tmp_path / "recompute.json"
    recompute.write_text(json.dumps([_recomputed("b1-B1", hidden=0, reclassified=1)]), encoding="utf-8")
    probes = _jsonl(tmp_path / "probes.jsonl", _probes(20, 20))
    code = main(
        ["--run", str(tmp_path), "v4-verdict", "--seal-sha", "0" * 64, "--story", "p.json", "s",
         "--character", "c.json", "s", "--scores", str(scores), "--judged", str(judged),
         "--ran-probes", str(probes), "--ran-recompute", str(recompute)]
    )  # fmt: skip
    assert code == 2
    assert "b1-B1 hiddenEpisodes=0" in capsys.readouterr().err


@pytest.mark.parametrize("given", ["none", "probes-only", "recompute-only"])
def test_gated_rows_without_both_ran_inputs_are_refused_by_both_aggregate_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], given: str
) -> None:
    from memory_eval_cli import main

    judged = _judged(tmp_path / "judged.json", ["b1-B1"])
    probes = _jsonl(tmp_path / "probes.jsonl", _probes(20, 20))
    recompute = tmp_path / "recompute.json"
    recompute.write_text(json.dumps(GOOD_RECOMPUTE), encoding="utf-8")
    extra = {
        "none": [],
        "probes-only": ["--ran-probes", str(probes)],
        "recompute-only": ["--ran-recompute", str(recompute)],
    }[given]
    summary = ["--run", str(tmp_path), "judge-summary", "--judged", str(judged), *extra]
    verdict = ["--run", str(tmp_path), "v4-verdict", "--seal-sha", "0" * 64, "--story", "p.json", "s",
               "--character", "c.json", "s", "--scores", str(judged), "--judged", str(judged), *extra]  # fmt: skip
    for argv in (summary, verdict):
        assert main(argv) == 2
        captured = capsys.readouterr()
        assert "--ran-probes" in captured.err and "--ran-recompute" in captured.err
        assert captured.out == ""


def test_bundle_verdict_refuses_aggregated_rows_the_ran_inputs_do_not_cover(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps(_aggregated(["b1-B2"], ("q1", "q7"))), encoding="utf-8")
    recompute = tmp_path / "recompute.json"
    recompute.write_text(
        json.dumps([*GOOD_RECOMPUTE, _recomputed("b1-B2", hidden=1, reclassified=1, item="q7")]), encoding="utf-8"
    )
    probes = _jsonl(tmp_path / "good.jsonl", _probes(20, 20))
    code = main(
        ["--run", str(tmp_path), "v4-verdict", "--seal-sha", "0" * 64, "--story", "p.json", "s",
         "--character", "c.json", "s", "--scores", str(rows), "--judged", str(rows),
         "--ran-probes", str(probes), "--ran-recompute", str(recompute)]
    )  # fmt: skip
    assert code == 2
    captured = capsys.readouterr()
    assert "--ran-probes 에 없는 집계 행 1개" in captured.err and "b1-B2:q7:300" in captured.err
    assert captured.out == ""
