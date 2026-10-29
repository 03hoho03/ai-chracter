"""`analyze_chat_probe.py` 의 지금 출력을 그대로 고정한다 — 지표 계산을 떼어 내는 리팩터가 숫자를 바꾸지 않았음을 보이는 증거다.

지표(길이·절단·자기복제·되받기·턴 열기·라벨 누출·한글 깨짐·대괄호)는 `summarize()` 루프 안에 인라인으로 있고, 이 모듈을
import 하는 테스트가 이 파일 전에는 하나도 없었다. 그래서 판정을 순수 함수로 옮기는 동작 불변 리팩터를 하기 전에, 리팩터
전 코드가 git 이 추적하는 프로브 대화록(`probe-runs/archive/transcripts/`)마다 내던 출력을 기대값 파일
(`fixtures/analyze_chat_probe_characterization.json`)에 적어 두고 리팩터 뒤 코드가 같은 출력을 내는지 본다.

대화록마다 세 가지를 대조한다.

- `--json` 출력 — 파싱한 값이 같고, 같은 인자로 다시 덤프한 글자까지 같다(정수·실수 표기가 바뀌어도 잡는다).
- 표 출력 — 줄 단위로 같다(라벨 폭·비율 표기·항목별 줄·결함 후보 줄 포함).
- 턴별 값 — 절단·문장 수·되받기는 출력에 합계로만 나와 서로 상쇄되는 두 판정 오류를 못 잡으므로, 지금 있는 판정 함수
  `_is_truncated`·`_sentences`(문장마다 글자 수)·`_parroted`(세 창)의 결과를 채점되는 응답마다 적었다.

아카이브 대화록에는 사용자 턴 대필·대괄호 출력·오류 항목·여섯 번째 응답·공백만 다른 직전 복사·50자 경계·오프닝 복사·같은 길이의
인접 턴이 한 번도 없어서 그 판정을 바꿔도 위 대조가 초록으로 남는다. 그래서 이 경로만 짚는 합성 대화록
(`fixtures/analyze_chat_probe_synthetic.json`, chat_probe 형식)을 같은 방식으로 대조한다 — 내용은 대화처럼 보일 필요가 없고 경로마다
정확히 그 판정을 가르는 최소 입력이다.

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


def _scored_replies(path: str) -> Iterator[tuple[int, int, str]]:
    """`summarize()` 가 채점하는 응답을 같은 (항목 순번, 턴 인덱스)로 낸다 — 유실 턴은 건너뛰되 인덱스는 소비한다."""
    data = json.loads((API_DIR / path).read_text(encoding="utf-8"))
    stories = data["results"] if isinstance(data, dict) else data
    for story_index, story in enumerate(stories):
        if "error" in story:
            continue
        replies = [turn["text"] for turn in story["transcript"][1:] if turn["role"] == "진행자"]
        for turn_index, reply in enumerate(replies):
            if reply:
                yield story_index, turn_index, reply


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
    actual = [
        {
            "story": story_index,
            "turn": turn_index,
            "chars": len(reply),
            "truncated": analyze_chat_probe._is_truncated(reply),
            "sentence_lengths": [len(part) for part in analyze_chat_probe._sentences(reply)],
            "parroted": {
                window: analyze_chat_probe._parroted(reply, turn_index, window) for window in analyze_chat_probe.WINDOWS
            },
        }
        for story_index, turn_index, reply in _scored_replies(path)
    ]
    assert actual == GOLDEN["transcripts"][path]["turns"]


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
