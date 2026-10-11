"""최종 짝 비교 집계의 사전 등록 v2 규칙 — 불능 항목은 두 갈래 모두에서 빼고 계속, 되감기는 적중인데 판정 불능이면 누출로
센다, 빼고 난 분모가 0 이면 멈춘다. 그리고 프롬프트 궤적(⑥ 길이 기울기·최대 차, ⑦ 캐시 블록 동일)을 같은 판정에 묶는다."""

from typing import Any

from memory_eval.plants import PlantSet
from memory_eval.verdict import s8_verdict, trajectory_checks


def _set() -> PlantSet:
    rewinds = [
        {
            "id": i,
            "category": "되감기",
            "split": s,
            "plantTurn": 125,
            "answerKeys": [["스쿠버"]],
            "questionForm": "direct",
            "question": "q",
            "probeCheckpoints": {"opus": [300], "offline": [300]},
            "metrics": {},
        }
        for i, s in (("rew01", "dev"), ("rew02", "test"))
    ]
    abstains = [
        {"id": f"abs0{i}", "category": "기권", "split": "dev" if i <= 3 else "test", "question": "q",
         "probeCheckpoints": {"opus": [300], "offline": []}}
        for i in range(1, 7)
    ]  # fmt: skip
    return PlantSet(raw={"seed": 1, "checkpoints": [50, 100, 300]}, plants=rewinds, abstains=abstains)


def _score(item: str, arm: str, *, hit: bool = False, split: str = "test", status: str = "accept") -> dict[str, Any]:
    return {
        "stage": "s8", "arm": arm, "checkpoint": 300, "item": item, "split": split, "status": status,
        "scored": status != "unprobeable", "hit": hit,
    }  # fmt: skip


def _abstain_scores() -> list[dict[str, Any]]:
    return [_score(f"abs0{i}", arm, split="dev" if i <= 3 else "test") for i in range(1, 7) for arm in ("A", "B")]


def _judged(item: str, arm: str, value: str | None) -> dict[str, Any]:
    return {"arm": arm, "item": item, "checkpoint": 300, "judged": value}


def _all_abstains_declined() -> list[dict[str, Any]]:
    return [_judged(f"abs0{i}", arm, "declined") for i in range(1, 7) for arm in ("A", "B")]


def _rewind_scores(b_hit: dict[str, bool]) -> list[dict[str, Any]]:
    rows = []
    for item, split in (("rew01", "dev"), ("rew02", "test")):
        rows.append(_score(item, "A", split=split))
        rows.append(_score(item, "B", hit=b_hit[item], split=split))
    return rows


def test_abstain_items_unprobeable_or_unjudgeable_are_dropped_from_both_arms_and_the_rest_is_judged() -> None:
    scores = [
        r if not (r["item"] == "abs02" and r["arm"] == "B") else {**r, "status": "unprobeable", "scored": False}
        for r in _abstain_scores()
    ]
    judged = [j for j in _all_abstains_declined() if not (j["item"] == "abs01" and j["arm"] == "A")]
    judged.append(_judged("abs01", "A", None))
    judged = [j for j in judged if not (j["item"] == "abs02" and j["arm"] == "B")]
    result = s8_verdict(
        _set(), scores + _rewind_scores({"rew01": False, "rew02": False}), judge_rows=judged, offline_rows=[]
    )
    assert result["4"]["status"] == "pass"
    assert result["4"]["n"] == 4
    assert result["4"]["excluded"] == ["abs01", "abs02"]


def test_abstain_halts_when_every_item_is_dropped() -> None:
    judged = [_judged(f"abs0{i}", arm, None) for i in range(1, 7) for arm in ("A", "B")]
    rows = _abstain_scores() + _rewind_scores({"rew01": False, "rew02": False})
    result = s8_verdict(_set(), rows, judge_rows=judged, offline_rows=[])
    assert result["4"]["status"] == "halt"
    assert result["4"]["n"] == 0


def test_rewind_hit_with_unjudgeable_verdict_counts_as_a_leak() -> None:
    judged = [*_all_abstains_declined(), _judged("rew02", "B", None)]
    rows = _abstain_scores() + _rewind_scores({"rew01": False, "rew02": True})
    result = s8_verdict(_set(), rows, judge_rows=judged, offline_rows=[])
    assert result["5"]["leaksB"] == 1
    assert result["5"]["leakByUnjudgeable"] == ["rew02"]
    assert result["5"]["status"] == "fail"


def test_rewind_unprobeable_item_is_dropped_and_the_rest_decides() -> None:
    rows = _abstain_scores() + [
        r if r["item"] != "rew01" else {**r, "status": "unprobeable", "scored": False}
        for r in _rewind_scores({"rew01": True, "rew02": False})
    ]
    result = s8_verdict(_set(), rows, judge_rows=_all_abstains_declined(), offline_rows=[])
    assert result["5"]["status"] == "pass"
    assert result["5"]["n"] == 1
    assert result["5"]["excluded"] == ["rew01"]


def test_rewind_halts_when_every_item_is_dropped() -> None:
    rows = _abstain_scores() + [
        {**r, "status": "unprobeable", "scored": False} for r in _rewind_scores({"rew01": False, "rew02": False})
    ]
    result = s8_verdict(_set(), rows, judge_rows=_all_abstains_declined(), offline_rows=[])
    assert result["5"]["status"] == "halt"
    assert result["5"]["n"] == 0


# ---------------------------------------------------------------- ⑥·⑦ 프롬프트 궤적


def _points(b_extra: Any, *, sha_b: tuple[str, str] = ("s0", "s1")) -> list[dict[str, Any]]:
    points = []
    for turn in range(101, 301):
        base = 20_000
        points.append({"turn": turn, "arm": "A", "chars": base, "segmentSha": ["s0", "s1"]})
        points.append({"turn": turn, "arm": "B", "chars": base + b_extra(turn), "segmentSha": list(sha_b)})
    return points


def test_trajectory_passes_when_recall_adds_a_bounded_flat_amount() -> None:
    checks = trajectory_checks(_points(lambda t: 500 if t % 2 else 0), recall_section_max=1_343)
    assert checks["6"]["status"] == "pass"
    assert checks["6"]["maxDiff"] == 500
    assert checks["7"]["status"] == "pass"


def test_trajectory_fails_on_slope_difference_of_two_chars_per_turn() -> None:
    checks = trajectory_checks(_points(lambda t: 2 * (t - 101)), recall_section_max=1_000)
    assert checks["6"]["status"] == "fail"
    assert abs(checks["6"]["slopeDiff"] - 2.0) < 1e-9


def test_trajectory_fails_when_max_difference_exceeds_the_recall_section_max() -> None:
    checks = trajectory_checks(_points(lambda t: 1_344 if t == 200 else 0), recall_section_max=1_343)
    assert checks["6"]["status"] == "fail"


def test_cache_blocks_must_match_on_every_turn() -> None:
    checks = trajectory_checks(_points(lambda t: 0, sha_b=("s0", "other")), recall_section_max=1_343)
    assert checks["7"]["status"] == "fail"


def test_overall_verdict_ands_trajectory_checks_and_halts_without_them() -> None:
    rows = _abstain_scores() + _rewind_scores({"rew01": False, "rew02": False})
    without = s8_verdict(_set(), rows, judge_rows=_all_abstains_declined(), offline_rows=[])
    assert without["6"]["status"] == "halt"
    assert without["7"]["status"] == "halt"
    assert without["status"] == "halt"
    failing = s8_verdict(
        _set(), rows, judge_rows=_all_abstains_declined(), offline_rows=[],
        trajectory_points=_points(lambda t: 0, sha_b=("s0", "other")), recall_section_max=1_343,
    )  # fmt: skip
    assert failing["7"]["pass"] is False
    assert failing["allPass"] is False
