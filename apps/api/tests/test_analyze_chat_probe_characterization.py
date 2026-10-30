"""`analyze_chat_probe.py` 의 지금 출력을 그대로 고정한다 — 지표 계산을 떼어 내는 리팩터가 숫자를 바꾸지 않았음을 보이는 증거다.

지표(길이·절단·자기복제·되받기·턴 열기·라벨 누출·한글 깨짐·대괄호)는 `summarize()` 루프 안에 인라인으로 있었고, 이 모듈을
import 하는 테스트가 이 파일 전에는 하나도 없었다. 그래서 판정을 순수 함수로 옮기는 동작 불변 리팩터를 하기 전에, 리팩터
전 코드가 git 이 추적하는 프로브 대화록(`probe-runs/archive/transcripts/`)마다 내던 출력을 기대값 파일
(`fixtures/analyze_chat_probe_characterization.json`)에 적어 두고 리팩터 뒤 코드가 같은 출력을 내는지 본다.

대화록마다 세 가지를 대조한다.

- `--json` 출력 — 파싱한 값이 같고, 같은 인자로 다시 덤프한 글자까지 같다(정수·실수 표기가 바뀌어도 잡는다).
- 표 출력 — 줄 단위로 같다(라벨 폭·비율 표기·항목별 줄·결함 후보 줄 포함).
- 턴별 값 — 절단·문장 수·자기복제·턴 열기 지표는 출력에 합계나 중앙값으로만 나와 서로 상쇄되는 두 판정 오류를 못 잡으므로,
  채점되는 응답마다 `reply_flags()` 를 직접 불러 그 판정 전부(길이·절단·문장 수·자기복제·의문·청유 어미·무시 표현·장면 이동형 열기·화자 라벨
  누출·사용자 턴 대필·한글 깨짐 첫 자리·대괄호 토큰 전부)를 대조하고, 문장마다 글자 수(`_sentences`)와 세 창 되받기
  (`_parroted`)도 대조한다. `reply_flags()` 에 넘기는 직전 발화는 `summarize()` 와 같은 규칙으로 따라간다.

턴별 기대값은 리팩터 전 코드로 만들었다. 길이·절단·문장마다 글자 수·되받기 칸은 응답마다 그 글자 수와 리팩터 전 판정 함수
(`_is_truncated`·`_sentences`·`_parroted`)의 결과를 적은 값이다. 나머지 판정 칸은 리팩터 전 코드에 응답 하나를 판정하는 함수가 없어서,
리팩터 전 파일 사본의 `summarize()` 채점 루프에 기록 줄만 더한 계측 사본을 돌려 각 판정 분기가 그 응답에서 실행됐는지(깨짐은
찾은 첫 자리 글자, 대괄호는 낸 토큰 전부)를 응답마다 적었다. 계측 사본은 기록 줄을 지우면 리팩터 전 파일과 글자까지 같고, 출력도
리팩터 전 파일과 글자까지 같으며, 계측 사본이 적은 길이·절단·문장 수가 위 판정 함수 값과 같음을 확인했다 — 기대값을 리팩터
뒤 코드로 만들면 같은 함수끼리 비교하게 되기 때문이다.

아카이브 대화록에는 사용자 턴 대필·대괄호 출력·오류 항목·여섯 번째 응답·공백만 다른 직전 복사·50자 경계·오프닝 복사·같은 길이의
인접 턴·한 응답 안의 대괄호 여럿(같은 토큰 반복 포함)·깨짐 자리 둘·앞 120자 경계에 걸친 무시 표현·빈 줄로 시작하는 응답(분할
조각 수와 문장 수가 갈린다)·별표만 남은 마지막 줄(응답 전체로는 종결, 마지막 문장만 보면 미종결)이 한 번도 없어서 그 판정을
바꿔도 위 대조가 초록으로 남는다. 그래서 이 경로만 짚는 합성 대화록(`fixtures/analyze_chat_probe_synthetic.json`, chat_probe
형식)을 같은 방식으로 대조한다 — 내용은 대화처럼 보일 필요가 없고 경로마다 정확히 그 판정을 가르는 최소 입력이며, 무시 표현은
마지막 글자가 120번째인 응답과 121번째인 응답 한 쌍으로 자르는 폭을 양쪽에서 고정한다. 나중에 더한 합성 항목의 기대값도 리팩터
전 코드로 만들었고, 다시 만든 기대값에서 아카이브 대화록·먼저 있던 합성 항목·비교 모드 쌍의 값은 바뀌지 않았다.

여러 파일을 나란히 비교하는 모드는 리스트 포맷 베이스라인과 유실 턴이 많은 메타 객체 포맷 파일 한 쌍으로 고정한다.

`*_summary.json` 세 개는 이 스크립트의 옛 `--json` 출력(분석 결과)이지 대화록이 아니라서 대상이 아니다. 기대값이 다르면 기대값을
고치지 말고 멈춘다 — 바뀐 코드로 기대값을 다시 만들면 대조가 항진명제가 된다.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import analyze_chat_probe

API_DIR = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "analyze_chat_probe_characterization.json"
GOLDEN: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
TRANSCRIPTS: list[str] = sorted(GOLDEN["transcripts"])
TRANSCRIPT_PARAMS = [pytest.param(path, id=Path(path).stem) for path in TRANSCRIPTS]


def _run_main(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], args: list[str]) -> str:
    # 기대값의 `path` 칸은 apps/api 기준 상대 경로라, 그 디렉터리에서 같은 인자로 부른다.
    monkeypatch.chdir(API_DIR)
    monkeypatch.setattr(sys, "argv", ["analyze_chat_probe.py", *args])
    analyze_chat_probe.main()
    return capsys.readouterr().out


def _assert_json_output(out: str, expected: Any) -> None:
    assert json.loads(out) == expected
    assert out == json.dumps(expected, ensure_ascii=False, indent=2) + "\n"


def _scored_replies(path: str) -> Iterator[tuple[int, int, str, str]]:
    """`summarize()` 가 채점하는 응답을 같은 (항목 순번, 턴 인덱스)로, 그 응답의 직전 발화와 함께 낸다.

    유실 턴은 건너뛰되 인덱스는 소비한다. 직전 발화는 `summarize()` 와 같은 규칙으로 따라간다 — 대화록 첫 항목(오프닝)에서
    시작해 채점한 응답으로만 바꾸므로, 유실 턴은 직전 발화를 바꾸지 않는다."""
    data = json.loads((API_DIR / path).read_text(encoding="utf-8"))
    stories = data["results"] if isinstance(data, dict) else data
    for story_index, story in enumerate(stories):
        if "error" in story:
            continue
        replies = [turn["text"] for turn in story["transcript"][1:] if turn["role"] == "진행자"]
        previous = story["transcript"][0]["text"] if story["transcript"] else ""
        for turn_index, reply in enumerate(replies):
            if reply:
                yield story_index, turn_index, reply, previous
                previous = reply


@pytest.mark.parametrize("path", TRANSCRIPT_PARAMS)
def test_json_output_matches_pre_refactor_output(
    path: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run_main(monkeypatch, capsys, [path, "--json"])
    _assert_json_output(out, GOLDEN["transcripts"][path]["json"])


@pytest.mark.parametrize("path", TRANSCRIPT_PARAMS)
def test_table_output_matches_pre_refactor_output(
    path: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run_main(monkeypatch, capsys, [path])
    assert out.split("\n") == GOLDEN["transcripts"][path]["table"]


@pytest.mark.parametrize("path", TRANSCRIPT_PARAMS)
def test_per_turn_judgments_match_pre_refactor_values(path: str) -> None:
    actual: list[dict[str, Any]] = []
    for story_index, turn_index, reply, previous in _scored_replies(path):
        flags = analyze_chat_probe.reply_flags(reply, previous)
        actual.append(
            {
                "story": story_index,
                "turn": turn_index,
                "chars": flags.length,
                "truncated": flags.truncated,
                "sentence_count": flags.sentence_count,
                "sentence_lengths": [len(part) for part in analyze_chat_probe._sentences(reply)],
                "parroted": {
                    window: analyze_chat_probe._parroted(reply, turn_index, window)
                    for window in analyze_chat_probe.WINDOWS
                },
                "self_copy": flags.self_copy,
                "solicit": flags.solicit,
                "ignored": flags.ignored,
                "scene_open": flags.scene_open,
                "label_leak": flags.label_leak,
                "user_turn": flags.user_turn,
                "broken": flags.broken,
                "brackets": list(flags.brackets),
            }
        )
    # 기대값은 문장 수를 따로 적지 않았다 — 문장마다 글자 수의 개수가 리팩터 전 코드가 센 문장 수다.
    expected = [{**row, "sentence_count": len(row["sentence_lengths"])} for row in GOLDEN["transcripts"][path]["turns"]]
    assert actual == expected


def test_side_by_side_json_output_matches_pre_refactor_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pair = GOLDEN["pair"]
    out = _run_main(monkeypatch, capsys, [*pair["paths"], "--json"])
    _assert_json_output(out, pair["json"])


def test_side_by_side_table_output_matches_pre_refactor_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pair = GOLDEN["pair"]
    out = _run_main(monkeypatch, capsys, pair["paths"])
    assert out.split("\n") == pair["table"]
