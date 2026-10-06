"""오프라인 스탯 판정 입력을 DB 없이 본다 — 오프라인 조립이 측정 때 서버 경로로 만든 프롬프트와 바이트까지 같은지(닻),
스토리 가이드 턴 기록의 이름 키 시작값이 직전 줄에서 entity_id 로 옮겨지는지, 지시문이 마지막 섹션이 아니면 L 갈래가
멈추는지.

DB 픽스처가 없는 순수 테스트라 `tests/` 밖에 둔다(그 디렉터리의 conftest 는 세션 시작에 테스트 DB 마이그레이션을 건다):

    uv run --env-file .env pytest scripts/experiments/filmclub_longturn/test_stat_misread_offline.py
"""

import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from experiments.filmclub_longturn import extract_stat_inputs as extract
from experiments.filmclub_longturn import judgment_replay as replay

RUN = Path(__file__).resolve().parents[3] / "probe-runs" / "stat-misread-2026-10-06"
# 측정 때(서버 경로, 격리 DB 의 방) 형식 비교 리플레이가 보낸 프롬프트의 sha256 앞 16자 — 그 실행 기록의 plan 줄 값.
MEASURED = {
    13: {"current": "339dce523e7ba429", "A": "6058aba51d6efb0c", "L": "5ff378174984947a", "B": "9648f005b810c22e"},
    25: {"current": "ded38aea0eb3ea48", "A": "544d27130f39dcc4", "L": "cf9f61d3c8e178de", "B": "296e93a6459e15a9"},
}


@pytest.mark.parametrize("turn", [13, 25], ids=["t013", "t025"])
def test_offline_assembly_reproduces_the_prompts_measured_through_the_server_path(turn: int) -> None:
    input_path = RUN / "inputs" / f"anchor-filmclub-6787bb78-t{turn:03d}.json"
    sections_path = RUN / "prod-v17-stat-judgment.json"
    if not (input_path.exists() and sections_path.exists()):
        pytest.skip(f"런 원자료가 없다: {input_path.parent}")
    prompt_set, sections = replay.load_sections(sections_path)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    inputs = replay.build_offline_inputs(data, prompt_set, sections, list(replay.STAT_FORMATS))
    got = {i.stat_format: hashlib.sha256(i.prompt.encode()).hexdigest()[:16] for i in inputs}
    assert got == MEASURED[turn]


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _sections_payload(instruction_order: int) -> dict[str, Any]:
    bodies = [
        ("stat_defs_intro", 1, False, "스탯 정의와 현재 값.\n{stat_lines}"),
        ("user_name", 2, True, "사용자의 이름: {user_name}"),
        ("turn_context", 3, False, "{user_label}: {user_message}\n{assistant_label}: {assistant_message}"),
        ("judgment_instruction", instruction_order, False, "각 스탯의 새 값을 정하라."),
    ]
    return {
        "labels": {"user_label": "사용자", "story_assistant_label": "진행자"},
        "stat_judgment_sections": [
            {
                "slot": slot,
                "scope": "story",
                "variant": "",
                "order": order,
                "conditional": cond,
                "body": body,
                "md5": _md5(body),
                "length": len(body),
            }
            for slot, order, cond, body in bodies
        ],
    }


def _input(stat_ids: list[str]) -> dict[str, Any]:
    return {
        "inputId": "E1-x-00000000-t001",
        "group": "E1",
        "turn": 1,
        "statDefs": [
            {
                "entity_id": sid,
                "name": f"{n} 호감도",
                "description": "{{user}}에게 응하면 오른다.",
                "min_value": 0,
                "max_value": 100,
                "initial_value": 20,
                "per_turn_delta": None,
                "change_direction": "both",
                "max_change_per_turn": None,
                "order": i,
                "serverIndex": i,
            }
            for i, (sid, n) in enumerate(zip(stat_ids, ["도희", "유나"], strict=True))
        ],
        "statStart": {stat_ids[0]: 52.5, stat_ids[1]: 24.5},
        "userMessage": "세빈 쪽을 본다",
        "assistantMessage": "{{user}}가 고개를 든다.",
        "names": {"personaName": None, "defaultUserName": "", "userNameLine": ""},
    }


def test_l_arm_is_the_current_prompt_plus_the_sentence_and_refuses_when_the_instruction_is_not_last(
    tmp_path: Path,
) -> None:
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    path = tmp_path / "sections.json"
    path.write_text(json.dumps(_sections_payload(instruction_order=4), ensure_ascii=False), encoding="utf-8")
    prompt_set, sections = replay.load_sections(path)
    by_format = {
        i.stat_format: i.prompt
        for i in replay.build_offline_inputs(_input(ids), prompt_set, sections, ["current", "L"])
    }
    assert by_format["L"] == by_format["current"] + " " + replay.BASELINE_SENTENCE
    assert "사용자의 이름" not in by_format["current"]  # 이름이 비면 조건부 섹션이 빠진다
    assert "당신이 고개를 든다." in by_format["current"]  # 응답의 {{user}} 는 서버처럼 바뀐다

    # 지시문이 맨 앞이면 본문에 붙인 문장이 프롬프트 끝이 아니다 — 게시 형태와 리플레이 형태가 갈리므로 멈춘다.
    path.write_text(json.dumps(_sections_payload(instruction_order=0), ensure_ascii=False), encoding="utf-8")
    prompt_set, sections = replay.load_sections(path)
    with pytest.raises(ValueError, match="마지막 섹션"):
        replay.build_offline_inputs(_input(ids), prompt_set, sections, ["L"])


def test_sections_file_with_an_edited_body_is_refused(tmp_path: Path) -> None:
    payload = _sections_payload(instruction_order=4)
    edited = copy.deepcopy(payload)
    edited["stat_judgment_sections"][3]["body"] += " 덧붙임"
    path = tmp_path / "sections.json"
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="md5"):
        replay.load_sections(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def test_storyguide_start_comes_from_the_previous_lines_room_after_mapped_from_names_to_ids(tmp_path: Path) -> None:
    room = str(uuid.uuid4())

    def stats(dohee: float, yuna: float, days: float) -> dict[str, float]:
        return {"도희 호감도": dohee, "유나 호감도": yuna, "상영회까지": days}

    _write_jsonl(
        tmp_path / "r2" / "dohee-1" / "turns.jsonl",
        [
            {"kind": "meta", "roomId": room},
            {"kind": "opening", "roomAfter": {"turnCount": 0, "stats": stats(20.0, 20.0, 20.0), "endingReached": False}},
            {"kind": "turn", "http": 200, "userText": "첫 턴", "reply": "응답1",
             "roomAfter": {"turnCount": 1, "stats": stats(23.0, 20.0, 19.0), "endingReached": False}},
            {"kind": "turn", "http": 500, "userText": "실패한 턴"},
            {"kind": "turn", "http": 200, "userText": "둘째 턴", "reply": "응답2",
             "roomAfter": {"turnCount": 2, "stats": stats(26.0, 21.0, 18.0), "endingReached": True}},
            {"kind": "turn", "http": 200, "userText": "엔딩 뒤",
             "roomAfter": {"turnCount": 3, "stats": stats(26.0, 21.0, 17.0), "endingReached": True}},
        ],
    )  # fmt: skip
    records = extract.read_storyguide_turns(tmp_path)
    # 실패한 줄은 턴이 아니고, 엔딩 뒤 턴은 판정이 없어 빠진다.
    assert [(r.turn, r.round, r.start_line, r.driver_user_text) for r in records] == [
        (1, "r2", 2, "첫 턴"),
        (2, "r2", 3, "둘째 턴"),
    ]
    ids = {"도희 호감도": str(uuid.uuid4()), "유나 호감도": str(uuid.uuid4()), "상영회까지": str(uuid.uuid4())}
    defs = [{"name": n, "entity_id": i} for n, i in ids.items()]
    extract.resolve_start(records[1], defs)
    assert records[1].start_by_id == {ids["도희 호감도"]: 23.0, ids["유나 호감도"]: 20.0, ids["상영회까지"]: 19.0}

    # 이름 키가 스탯 정의와 하나라도 다르면 추정하지 않고 멈춘다.
    with pytest.raises(extract.SourceFormatError, match="이름 키"):
        extract.resolve_start(records[0], [*defs[:2], {"name": "세빈 호감도", "entity_id": str(uuid.uuid4())}])
