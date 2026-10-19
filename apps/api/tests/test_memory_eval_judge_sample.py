"""판정 표본 생성 준비 — 대본 읽기와 층 검사, 엔딩 갈래 덤프 이름, 갈래 실행의 작업 DB 가드, 드라이버 로그에서 카운트다운 층 표
만들기, 망친 입력 대조군 고르기, 표본 생성 원가 견적(Opus 직결 생성의 프롬프트 캐시 쓰기·읽기 포함).

대본·대조군 설정은 측정 데이터라 저장소에 두지 않는다. 여기의 대본은 층·갈래·표시의 꼴만 맞춘 지어낸 것이다."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from memory_eval import judge_agreement as ja
from memory_eval import judge_sample as js


def _story() -> dict[str, Any]:
    cell = {1: True, 3: True, 4: True, 9: False, 12: True}
    return {
        "lane": "story",
        "strata": {
            "S-a": {"expectDecrement": False},
            "S-c": {"expectDecrement": True},
            "E-fit": {"expectEnding": True},
            "E-miss": {"expectEnding": False},
        },
        "turns": [
            {
                "stratum": "S-a" if n <= 7 else "S-c",
                "say": f"지어낸 사용자 말 {n}번",
                "cellMatch": cell.get(n, False) is True,
                **({"controlEligible": False} if n == 9 else {}),
            }
            for n in range(1, 13)
        ],
        "branches": [
            {"id": "fit1", "stratum": "E-fit", "say": "지어낸 엔딩 말 하나"},
            {"id": "fit2", "stratum": "E-fit", "say": "지어낸 엔딩 말 둘"},
            {"id": "miss1", "stratum": "E-miss", "say": "지어낸 빗나간 말 하나"},
            {"id": "miss2", "stratum": "E-miss", "say": "지어낸 빗나간 말 둘"},
        ],
    }


def _character() -> dict[str, Any]:
    return {
        "lane": "character",
        "strata": {"C-a": {"expectDecrement": False}},
        "turns": [
            {"stratum": "C-a", "say": f"지어낸 캐릭터 말 {n}번", "imageCondition": n % 2 == 0} for n in range(1, 7)
        ],
    }


def _config() -> dict[str, Any]:
    return {
        "perCallSite": 2,
        "sentences": {
            "chat_stat_judgment": "지어낸 스탯 망침 문장.",
            "chat_ending_judgment": "지어낸 엔딩 망침 문장.",
            "chat_media_book_image": "지어낸 칸 망침 문장.",
            "chat_situational_image": "지어낸 그림 망침 문장.",
        },
    }


def _data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    for name, body in (
        (js.STORY_SCRIPT_FILE, _story()),
        (js.CHARACTER_SCRIPT_FILE, _character()),
        (js.CONTROLS_CONFIG_FILE, _config()),
    ):
        (data / name).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return data


def _loaded(tmp_path: Path, name: str) -> dict[str, Any]:
    return js.load_script(_data_dir(tmp_path) / name)


def test_a_branch_with_an_unknown_stratum_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(
        json.dumps(
            {
                "lane": "story",
                "strata": {"S-a": {"expectDecrement": False}},
                "turns": [{"stratum": "S-a", "say": "x"}],
                "branches": [{"id": "E1", "stratum": "E-z", "say": "y"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="E-z"):
        js.load_script(path)


def test_a_script_turn_with_an_unknown_stratum_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(
        json.dumps(
            {"lane": "story", "strata": {"S-a": {"expectDecrement": False}}, "turns": [{"stratum": "S-z", "say": "x"}]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="S-z"):
        js.load_script(path)


def test_the_branch_turn_is_the_one_right_after_the_script(tmp_path: Path) -> None:
    assert js.branch_turn(_loaded(tmp_path, js.STORY_SCRIPT_FILE)) == 13


def test_each_branch_writes_its_own_dump_so_judgment_line_ids_do_not_collide(tmp_path: Path) -> None:
    # 갈래들은 같은 방·같은 턴 번호라 판정 줄은 덤프 파일 이름으로만 가려진다(줄 id = 파일 이름:줄 번호).
    script = _loaded(tmp_path, js.STORY_SCRIPT_FILE)
    dumps = [js.branch_dump(tmp_path / "run", b["id"]) for b in script["branches"]]
    assert len({d.name for d in dumps}) == len(dumps)
    assert all(d.name.startswith("dump-story-") for d in dumps)


def test_a_branch_run_outside_the_eval_database_is_refused_before_touching_anything(tmp_path: Path) -> None:
    script = _loaded(tmp_path, js.STORY_SCRIPT_FILE)
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(SystemExit, match="lm_eval_"):
        js.run_branch(
            script["branches"][0],
            database_url="postgresql+asyncpg://u:p@localhost/ai_character_chat",
            run_dir=run,
            room_id=uuid.uuid4(),
            checkpoint_no=12,
            label="judge",
            port=8131,
            cred_file=run / "cred",
            cookie_file=run / "cookie",
            server_overrides={},
            allow_paid=False,
        )
    assert not any(run.iterdir())


def test_strata_come_from_tagged_finished_turns_of_the_driver_log(tmp_path: Path) -> None:
    script = _loaded(tmp_path, js.STORY_SCRIPT_FILE)
    log = tmp_path / "chat.jsonl"
    rows = [
        {"kind": "opening", "roomId": "r"},
        {"kind": "turn", "roomId": "r", "clientTurn": 1, "tag": "S-a", "done": True},
        # 유실 턴은 같은 번호로 다시 친다 — 끝나지 않은 줄은 층 표에 넣지 않는다.
        {"kind": "turn", "roomId": "r", "clientTurn": 2, "tag": "S-c", "done": False},
        {"kind": "turn", "roomId": "r", "clientTurn": 2, "tag": "S-c", "done": True},
        {"kind": "turn", "roomId": "r", "clientTurn": 3, "tag": None, "done": True},
    ]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert js.strata_from_log(log, script) == [
        {"roomId": "r", "turn": 1, "stratum": "S-a", "expectDecrement": False},
        {"roomId": "r", "turn": 2, "stratum": "S-c", "expectDecrement": True},
    ]


def test_generation_estimate_prices_cache_writes_and_reads_per_turn() -> None:
    report = js.generation_estimate(turns=10, prompt_tokens=20_000, new_tokens_per_turn=1_000, output_tokens=500)
    # 첫 턴은 프롬프트 전체를 캐시에 쓰고, 다음 턴부터는 앞을 캐시에서 읽고 새로 붙은 만큼만 쓴다.
    first = (20_000 * 5.00 + 500 * 20.00) / 1_000_000
    later = (19_000 * 0.20 + 1_000 * 5.00 + 500 * 20.00) / 1_000_000
    assert report["model"] == "claude-opus-5-5"
    assert report["usd"] == pytest.approx(first + 9 * later)


def test_branch_turns_restored_from_the_template_pay_the_full_cache_write_each() -> None:
    # 갈래 턴은 템플릿에서 복원한 뒤 서버를 새로 띄워 치므로 앞 턴의 캐시를 읽지 못한다 — 첫 턴처럼 프롬프트 전체를 쓴다.
    plain = js.generation_estimate(turns=10, prompt_tokens=20_000, new_tokens_per_turn=1_000, output_tokens=500)
    with_branches = js.generation_estimate(
        turns=10, prompt_tokens=20_000, new_tokens_per_turn=1_000, output_tokens=500, cold_turns=9
    )
    first = (20_000 * 5.00 + 500 * 20.00) / 1_000_000
    assert with_branches["usd"] == pytest.approx(plain["usd"] + 9 * first)
    assert with_branches["coldTurns"] == 9


def test_cell_control_candidates_skip_matching_turns_and_turns_marked_ineligible(tmp_path: Path) -> None:
    # 칸 해당 여부는 사람마다 갈려, 해당 아님이어도 애매로 본 턴(`controlEligible` 거짓)은 대조군 후보에서 뺀다.
    assert js.cell_control_turns(_loaded(tmp_path, js.STORY_SCRIPT_FILE)) == [2, 5, 6, 7, 8, 10, 11]


def _line(file: str, number: int, call_site: str, turn: int, prompt: str) -> ja.JudgmentLine:
    schema = {
        "chat_stat_judgment": "StatRuleJudgmentResult",
        "chat_ending_judgment": "EndingJudgmentResult",
        "chat_situational_image": "ImageMatchJudgmentResult",
        "chat_media_book_image": "ImageMatchJudgmentResult",
    }[call_site]
    return ja.JudgmentLine(
        line_id=f"{file}:{number}", room_id="r", turn=turn, call_site=call_site, schema=schema, prompt=prompt
    )


def test_controls_are_picked_by_the_registered_rule_and_get_the_registered_sentence(tmp_path: Path) -> None:
    data = _data_dir(tmp_path)
    story = js.load_script(data / js.STORY_SCRIPT_FILE)
    character = js.load_script(data / js.CHARACTER_SCRIPT_FILE)
    config = js.load_controls_config(data / js.CONTROLS_CONFIG_FILE)
    say = {n: turn["say"] for n, turn in enumerate(story["turns"], start=1)}
    lines = [
        _line("dump-story.jsonl", n, "chat_stat_judgment", n, f"판정\n나: {say[n]}") for n in range(1, 8) if n != 4
    ]
    # 2번 턴은 사용자 말이 프롬프트에 두 번 나와 어느 자리를 망칠지 모르므로 건너뛴다.
    lines[1] = _line("dump-story.jsonl", 2, "chat_stat_judgment", 2, f"나: {say[2]}\n나: {say[2]}")
    lines += [_line("dump-story.jsonl", 100 + n, "chat_media_book_image", n, f"칸\n나: {say[n]}") for n in range(1, 13)]
    for branch in story["branches"]:
        lines.append(
            _line(js.branch_dump_name(branch["id"]), 1, "chat_ending_judgment", 13, f"엔딩\n나: {branch['say']}")
        )
    lines += [
        _line("dump-character.jsonl", n, "chat_situational_image", n, f"그림\n나: {turn['say']}")
        for n, turn in enumerate(character["turns"], start=1)
    ]
    # 층 표 확정에서 3번 턴을 뺐다.
    strata = [{"roomId": "r", "turn": n, "stratum": "S-a", "expectDecrement": False} for n in (1, 2, 4, 5, 6, 7)]
    built = js.build_controls(lines, story=story, character=character, strata=strata, config=config)
    by_site: dict[str, list[dict[str, Any]]] = {}
    for item in built["controls"]:
        site = next(line.call_site for line in lines if line.line_id == item["base"]["lineId"])
        by_site.setdefault(site, []).append(item)
    # 층 표에 남은 S-a 턴(1·2·4·5·…)에서 프롬프트에 사용자 말이 한 번뿐인 줄을 앞에서 둘. 4번은 줄이 없다.
    assert [c["base"]["lineId"] for c in by_site["chat_stat_judgment"]] == ["dump-story.jsonl:1", "dump-story.jsonl:5"]
    stat = by_site["chat_stat_judgment"][0]
    assert stat["replace"] == [[say[1], f"{say[1]} {config['sentences']['chat_stat_judgment']}"]]
    assert [c["base"]["lineId"] for c in by_site["chat_ending_judgment"]] == [
        f"{js.branch_dump_name(b)}:1" for b in ("miss1", "miss2")
    ]
    assert [c["base"]["lineId"] for c in by_site["chat_media_book_image"]] == [
        f"dump-story.jsonl:{100 + n}" for n in (2, 5)
    ]
    assert [c["base"]["lineId"] for c in by_site["chat_situational_image"]] == [
        f"dump-character.jsonl:{n}" for n in (1, 3)
    ]
    assert built["shortfall"] == {}
    assert ja.control_lines(lines, built["controls"])


def test_the_estimate_command_reads_both_scripts_from_the_data_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    argv = ["--run", str(tmp_path / "run"), "--data-dir", str(_data_dir(tmp_path)), "judge-sample-estimate"]
    assert main(argv) == 0
    rooms = json.loads(capsys.readouterr().out)["rooms"]
    assert set(rooms) == {js.STORY_SCRIPT_FILE, js.CHARACTER_SCRIPT_FILE}
    assert rooms[js.STORY_SCRIPT_FILE]["coldTurns"] == 4


def test_the_estimate_command_without_a_data_dir_stops_instead_of_reading_a_repository_file(tmp_path: Path) -> None:
    from memory_eval_cli import main

    assert main(["--run", str(tmp_path), "judge-sample-estimate"]) == 2
