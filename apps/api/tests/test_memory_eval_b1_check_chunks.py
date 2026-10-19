"""묶음 누적 대본 검사기 — 핵심어 구만 보던 재등장 검사가 놓치던 결함을 합성 대본·합성 심기 표로 본다.

체크포인트 원문 창 [CP−29, CP] 안에 그 체크포인트가 묻는 정답 낱말이 다시 나오면 기억 없이 읽어서 맞히므로 위반이고,
그 밖(심은 뒤~묻기 전)에 다시 나오는 것은 사람이 볼 경고다. 숫자 표기·띄어쓰기·조사·한 글자 끼움 변형도 같은 낱말로 본다."""

import json
from pathlib import Path
from typing import Any

import pytest

from memory_eval.b1 import check_chunks

WINDOW_RULE = "체크포인트 원문 창 안 정답 낱말"
STATUS_RULE = "체크포인트 원문 창 안 상태창에 정답 낱말"
CORRECTION_RULE = "정정 턴에 옛 값 낱말"
AGAIN_WARN = "심기 뒤 묶음 낱말 재등장(사람 확인)"
COMMON_WARN = "정답 묶음이 흔한 낱말뿐(사람 확인)"
NEW_RULES = (WINDOW_RULE, STATUS_RULE, CORRECTION_RULE)

FILLER_USER = "*천천히 걸어간다* 그래, 오늘은 어디까지 가 볼까."
FILLER_NARR = (
    "*바람이 조용히 불고 거리는 평소처럼 한산하다. 둘은 별말 없이 나란히 걷는다. 가로등 불빛이 젖은 보도 위에"
    " 길게 번진다. 멀리서 버스가 지나가는 소리가 들리고, 가게 간판들이 하나씩 꺼져 간다. 그녀는 가끔 고개를 들어"
    " 하늘을 본다. 별 몇 개가 희미하게 깜빡이고 있다. 발소리만 규칙적으로 이어진다."
    " 밤공기가 서늘하다. 신호등이 깜박이며 색을 바꾸고, 길모퉁이 빵집 앞에 화분 몇 개가 나와 있다.*"
)


def _rows(**turns: str) -> list[dict[str, Any]]:
    """300턴 합성 대본. `t285="..."` 처럼 준 턴은 진행자 줄 채움 글 뒤에 그 글을 붙인다(길이 규칙은 지킨다)."""
    rows = [{"turn": t, "user": FILLER_USER, "assistant": FILLER_NARR} for t in range(1, 301)]
    for key, text in turns.items():
        rows[int(key[1:]) - 1]["assistant"] = FILLER_NARR + "\n\n" + text
    return rows


def _detail(keyword: str, bundles: list[list[str]], turn: int = 50, cps: tuple[int, ...] = (300,)) -> dict[str, Any]:
    return {
        "id": "d1",
        "category": "detail",
        "subtype": "object",
        "plants": [
            {"turn": turn, "line": "assistant", "who": "narration", "assertedBy": "narration", "keywords": [keyword]}
        ],
        "keywords": [keyword],
        "answer_key": {"mode": "match", "bundles": bundles},
        "expected_fact": {"truth_status": "confirmed"},
        "ask_checkpoints": list(cps),
    }


def _run(item: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    raw = {"plants": [item], "abstains": []}
    return check_chunks.check(raw, "", rows, 12, False, "asterisk"), check_chunks.check_warnings(raw, rows)


def test_answer_word_alone_in_raw_window_is_a_violation_though_the_keyword_phrase_is_absent() -> None:
    item = _detail("파란 우산", [["우산"]])
    v, _ = _run(item, _rows(t50="*그녀가 파란 우산을 펼친다.*", t285="*현관에 우산이 세워져 있다.*"))

    assert v[WINDOW_RULE] == ["d1 CP300 턴[285]"]
    assert "핵심어 재등장" not in v


@pytest.mark.parametrize(("turn", "in_window"), [(271, True), (300, True), (270, False), (150, False)])
def test_raw_window_edges_split_violation_from_warning(turn: int, in_window: bool) -> None:
    item = _detail("파란 우산", [["우산"]])
    v, w = _run(item, _rows(t50="*그녀가 파란 우산을 펼친다.*", **{f"t{turn}": "*현관에 우산이 세워져 있다.*"}))

    if in_window:
        assert v[WINDOW_RULE] == [f"d1 CP300 턴[{turn}]"]
        assert AGAIN_WARN not in w
    else:
        assert WINDOW_RULE not in v
        assert w[AGAIN_WARN] == [f"d1 턴[{turn}]"]


def test_checkpoint_100_window_is_checked_for_items_asked_at_both_checkpoints() -> None:
    item = _detail("파란 우산", [["우산"]], turn=20, cps=(100, 300))
    v, _ = _run(item, _rows(t20="*그녀가 파란 우산을 펼친다.*", t80="*현관에 우산이 세워져 있다.*"))

    assert v[WINDOW_RULE] == ["d1 CP100 턴[80]"]


def test_answer_in_status_block_inside_raw_window_is_its_own_violation() -> None:
    item = _detail("목요일 여섯 시", [["목요일"]], turn=40)
    status = "*둘이 동아리방에 들어선다.*\n\n```\n장소 | 동아리방\n시간 | 목요일 저녁\n함께 | 없음\n지금 | 회의\n```"
    v, _ = _run(item, _rows(t40="모임은 목요일 여섯 시야.", t290=status))

    assert v[STATUS_RULE] == ["d1 CP300 턴[290]"]
    assert WINDOW_RULE not in v


@pytest.mark.parametrize(
    ("answer", "written"),
    [
        ("팔월 십육 일", "*수첩에 8월 16일이 밑줄이 그어져 있다.*"),
        ("8월 16일", "*수첩에 팔월 십육 일이 밑줄이 그어져 있다.*"),
        ("사만 원", "*봉투에 4만원이 들어 있다.*"),
        ("사만 원", "*봉투에 40,000원이 들어 있다.*"),
        ("열 시 오십 분", "*시계가 10시 50분을 가리킨다.*"),
        ("염색 골목", "*염색소 골목에서 그녀를 본다.*"),
        ("우산", "*우산으로 비를 막는다.*"),
    ],
)
def test_number_spacing_particle_and_one_letter_variants_count_as_the_same_answer(answer: str, written: str) -> None:
    item = _detail(answer, [[answer]])
    v, _ = _run(item, _rows(t50=f"*{answer}.*", t280=written))

    assert v[WINDOW_RULE] == ["d1 CP300 턴[280]"]


@pytest.mark.parametrize(
    ("answer", "written"),
    [
        ("십이월 이 일", "*수첩에 12월 12일이 적혀 있다.*"),
        ("2장", "*당신이 장비를 꾸린다.*"),
    ],
)
def test_number_variants_do_not_match_a_different_number_or_a_word_inside_a_sentence(answer: str, written: str) -> None:
    item = _detail(answer, [[answer]])
    v, _ = _run(item, _rows(t50=f"*{answer}.*", t280=written))

    assert WINDOW_RULE not in v


def test_old_value_word_in_the_correction_turn_is_a_violation() -> None:
    item = {
        "id": "c1",
        "category": "correction",
        "subtype": "claim_then_narration",
        "plants": [
            {"turn": 60, "line": "assistant", "who": "나래솔", "assertedBy": "character", "keywords": ["오전 반"]},
            {"turn": 120, "line": "assistant", "who": "narration", "assertedBy": "narration", "keywords": ["오후 반"]},
        ],
        "keywords": ["오전 반", "오후 반"],
        "answer_key": {"mode": "match", "bundles": [["오후"]], "reject_bundles": [["오전"]]},
        "ask_checkpoints": [300],
    }
    v, _ = _run(item, _rows(t60="수업은 오전 반이야.", t120="*오전이 아니라 오후 반 수업이었다.*"))
    clean, _ = _run(item, _rows(t60="수업은 오전 반이야.", t120="*수업은 오후 반으로 잡혀 있었다.*"))

    assert v[CORRECTION_RULE] == ["c1 턴120"]
    assert CORRECTION_RULE not in clean


def test_single_syllable_answer_is_a_warning_and_never_a_window_violation() -> None:
    item = _detail("높은 산", [["산"]])
    v, w = _run(item, _rows(t50="*멀리 높은 산이 보인다.*", t290="*산 그림자가 길다.*"))

    assert WINDOW_RULE not in v
    assert w[COMMON_WARN] == ["d1"]


def test_answer_word_spread_over_many_turns_is_a_common_answer_warning_and_still_a_window_violation() -> None:
    many = {f"t{t}": "*그녀가 커피를 마신다.*" for t in range(100, 112)}
    item = _detail("식은 커피", [["커피"]])
    v, w = _run(item, _rows(t50="*식은 커피가 남아 있다.*", t290="*커피 향이 난다.*", **many))

    assert w[COMMON_WARN] == ["d1"]
    assert v[WINDOW_RULE] == ["d1 CP300 턴[290]"]


def test_secret_leak_word_in_raw_window_is_a_warning_not_a_violation() -> None:
    item = {
        "id": "s1",
        "category": "secret",
        "subtype": "confided",
        "plants": [
            {"turn": 30, "line": "assistant", "who": "석다빈", "assertedBy": "narration", "keywords": ["새벽 우유 배달"]}
        ],
        "keywords": ["새벽 우유 배달"],
        "answer_key": {"mode": "judge", "leak_bundles": [["새벽 우유 배달", "우유"]]},
        "ask_checkpoints": [300],
    }
    v, w = _run(item, _rows(t30="*석다빈은 새벽 우유 배달 일을 한다.*", t290="*문 앞에 우유 상자가 놓여 있다.*"))

    assert WINDOW_RULE not in v
    assert w[AGAIN_WARN] == ["s1 턴[290]"]


def test_item_without_bundles_watches_each_word_of_its_keyword_phrase() -> None:
    item = {
        "id": "f1",
        "category": "false_premise",
        "subtype": "user_lie",
        "plants": [{"turn": 40, "line": "user", "who": "사용자", "assertedBy": "user", "keywords": ["궁술 대회"]}],
        "keywords": ["궁술 대회"],
        "answer_key": {"mode": "judge"},
        "ask_checkpoints": [300],
    }
    _, w = _run(item, _rows(t150="*벽에 궁술 도장의 간판이 걸려 있다.*"))

    assert w[AGAIN_WARN] == ["f1 턴[150]"]


def test_clean_script_adds_no_new_violation_or_warning() -> None:
    item = _detail("파란 우산", [["우산"]])
    v, w = _run(item, _rows(t50="*그녀가 파란 우산을 펼친다.*"))

    assert not set(NEW_RULES) & set(v)
    assert w == {}


def test_warnings_do_not_fail_the_run_and_reviewed_ones_drop_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = _rows(t50="*그녀가 파란 우산을 펼친다.*", t150="*현관에 우산이 세워져 있다.*")
    for n in range(12):
        lines = [json.dumps(r, ensure_ascii=False) for r in rows[n * 25 : (n + 1) * 25]]
        (tmp_path / f"chunk-{n + 1:02d}.jsonl").write_text("\n".join(lines), encoding="utf-8")
    plants = tmp_path / "plants.json"
    plants.write_text(json.dumps({"plants": [_detail("파란 우산", [["우산"]])], "abstains": []}), encoding="utf-8")
    work = tmp_path / "work.json"
    work.write_text("{}", encoding="utf-8")
    argv = ["check_chunks.py", str(plants), str(work), str(tmp_path), "--upto", "12", "--markup", "asterisk"]
    monkeypatch.setattr("sys.argv", argv)

    code = check_chunks.main()
    first = capsys.readouterr().out
    (tmp_path / "review.json").write_text(
        json.dumps([{"rule": AGAIN_WARN, "entry": "d1 턴[150]", "reason": "합성"}], ensure_ascii=False),
        encoding="utf-8",
    )
    check_chunks.main()
    second = capsys.readouterr().out

    assert code == 0
    assert f"{AGAIN_WARN}: 1" in first and "경고 1" in first
    assert AGAIN_WARN not in second and "경고 0" in second
