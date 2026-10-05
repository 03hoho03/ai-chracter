"""실험 스크립트 `experiments/filmclub_longturn/longrun_bins.py` — 장기 턴 로그를 구간별 분석기 입력으로 바꾸는 것.

옛 판은 구간을 40턴까지 박아 두어 41턴째에서 예외로 멈췄다. 수백 턴 방에서는 모든 턴이 어느 구간엔가 들어가야
하고, 사람 턴·프로브 턴은 채점 분모에서 빠지되 다음 턴의 "직전 응답"으로는 남아야 한다.
"""

import json
from pathlib import Path
from typing import Any

from experiments.filmclub_longturn import longrun_bins as bins


def _opening() -> dict[str, Any]:
    return {"kind": "opening", "messages": ["오프닝"], "roomAfter": {"turnCount": 0, "stats": {}}}


def _turn(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "turn",
        "http": 200,
        "userText": f"발화 {n}",
        "reply": f"응답 {n}",
        "roomAfter": {"turnCount": n, "stats": {}},
        **extra,
    }


def _read(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_turns_after_forty_land_in_fifty_turn_bins(tmp_path: Path) -> None:
    rows = [_opening()] + [_turn(n) for n in range(1, 121)]

    summary = bins.convert(rows, tmp_path, label="room")

    assert [b["bin"] for b in summary["bins"]] == ["1-50", "51-100", "101-150"]
    covered = [t for b in summary["bins"] for t in b["turns"]]
    assert covered == list(range(1, 121))
    last = _read(tmp_path / "room__101-150.json")
    assert last["observed"] is True
    assert last["results"][0]["turns"] == list(range(101, 121))
    # 구간의 첫 transcript 는 직전 구간 마지막 응답이다(분석기의 자기복제 판정 입력).
    assert last["results"][0]["transcript"][0] == {"role": "진행자", "text": "응답 100"}


def test_bin_size_is_an_argument(tmp_path: Path) -> None:
    rows = [_opening()] + [_turn(n) for n in range(1, 8)]

    summary = bins.convert(rows, tmp_path, label="room", bin_size=3)

    assert [(b["bin"], b["turns"]) for b in summary["bins"]] == [
        ("1-3", [1, 2, 3]),
        ("4-6", [4, 5, 6]),
        ("7-9", [7]),
    ]


def test_human_and_probe_turns_are_marked_and_split_the_transcript(tmp_path: Path) -> None:
    rows = [
        _opening(),
        _turn(1),
        _turn(2, source="human"),
        _turn(3),
        _turn(4, tag="프로브"),
        _turn(5, tag="넘김"),
    ]

    bins.convert(rows, tmp_path, label="room")
    data = _read(tmp_path / "room__1-50.json")

    assert data["turns"] == [1, 3, 5]
    assert data["humanTurns"] == [2]
    assert data["probeTurns"] == [4]
    segments = data["results"]
    assert [s["turns"] for s in segments] == [[1], [3], [5]]
    # 빠진 턴의 응답이 다음 조각의 직전 응답이 된다 — 빠진 턴 앞 응답이 아니다.
    assert segments[1]["transcript"][0]["text"] == "응답 2"
    assert segments[2]["transcript"][0]["text"] == "응답 4"


def test_lost_turn_takes_the_attempted_number_and_rejected_lines_are_not_turns(tmp_path: Path) -> None:
    rows = [
        _opening(),
        _turn(1),
        {"kind": "turn", "http": 429, "userText": "재시도 전", "reply": "", "roomAfter": None},
        {
            "kind": "turn",
            "http": 200,
            "userText": "유실",
            "reply": "",
            "failure": "error: x",
            "roomAfter": {"turnCount": 1, "stats": {}},
        },
        _turn(2),
    ]

    summary = bins.convert(rows, tmp_path, label="room")
    data = _read(tmp_path / "room__1-50.json")

    assert summary["rejectedLines"] == 1
    assert data["turns"] == [1, 2, 2]
    assert data["lost"] == [2]
    replies = [t["text"] for t in data["results"][0]["transcript"][1:] if t["role"] == "진행자"]
    assert replies == ["응답 1", "", "응답 2"]


def test_phase_files_group_turns_by_phase(tmp_path: Path) -> None:
    rows = [_opening()] + [_turn(n) for n in range(1, 5)]
    phases = {1: "준비 초반", 2: "준비 초반", 3: "촬영 기간", 4: "준비 초반"}

    summary = bins.convert(rows, tmp_path, label="room", phases=phases)

    by_phase = {p["phase"]: p["turns"] for p in summary["phases"]}
    assert by_phase == {"준비 초반": [1, 2, 4], "촬영 기간": [3]}
    early = _read(tmp_path / "room__phase-준비_초반.json")
    # 다른 국면 턴을 사이에 두고 다시 돌아오면 transcript 를 새로 연다(직전 응답은 3턴 응답).
    assert [s["turns"] for s in early["results"]] == [[1, 2], [4]]
    assert early["results"][1]["transcript"][0]["text"] == "응답 3"
