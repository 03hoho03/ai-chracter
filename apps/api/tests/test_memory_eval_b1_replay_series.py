"""궤적 재조립의 계열 고르기 — 갈래마다 자기 계열의 체크포인트 템플릿에서 조립한다. B 계열 갈래(요약 표기 켬)를 A 템플릿에서
조립하면 A 요약 위의 궤적이 B 갈래 이름으로 남으므로, 템플릿 이름을 주지 않으면 B 계열 갈래를 거부하고, 열기 전에 템플릿 지문(B
계열은 요약 글 해시 포함)을 그 지문 파일과 견준다.

B 계열 갈래는 자기 자신을 대화 기록 뒤 섹션(회상·사실·임베딩 회상) 없이 다시 렌더한 점도 함께 만든다 — 요약 글이 다른 두 계열
사이에서는 앞 두 캐시 블록이 정의상 달라, B 계열의 블록 검사는 그 자기 재렌더와의 비교로 한다."""

import argparse
from pathlib import Path

import pytest

from memory_eval import runtime
from memory_eval import trajectory_replay as tr
from memory_eval.checkpoint import SUMMARY_DIGEST_KEY
from memory_eval.cli_infra import cmd_trajectory_replay


def test_each_arm_reads_its_own_series_template() -> None:
    assert tr.replay_template(300, "b1-measure", "b1-A1") == "lm_eval_b1-measure_cp300_frozen"
    for arm in ("b1-B1", "b1-B2", "b1-B1E"):
        assert tr.replay_template(300, "b1-measure", arm) == "lm_eval_b1-measure-b_cp300_frozen"
    assert tr.arms_by_series(["b1-A0", "b1-B1", "b1-A1", "b1-B2"]) == {
        "A": ["b1-A0", "b1-A1"],
        "B": ["b1-B1", "b1-B2"],
    }


def test_template_check_requires_the_summary_digest_only_for_the_b_series() -> None:
    fp = {"turnCount": 300, "snapshotCount": 28}
    tr.check_template(fp, dict(fp), digest=None)
    tr.check_template({**fp, SUMMARY_DIGEST_KEY: "d1"}, dict(fp), digest="d1")
    with pytest.raises(SystemExit, match=SUMMARY_DIGEST_KEY):
        tr.check_template({**fp, SUMMARY_DIGEST_KEY: "d1"}, dict(fp), digest="d2")
    with pytest.raises(SystemExit, match=SUMMARY_DIGEST_KEY):
        tr.check_template(dict(fp), dict(fp), digest="d1")  # 해시 없는 B 지문(요약을 바꾸기 전 지문)
    with pytest.raises(SystemExit, match="turnCount"):
        tr.check_template(fp, {**fp, "turnCount": 301}, digest=None)


def test_bare_rerender_keeps_summary_marking_and_turns_off_every_post_history_section() -> None:
    for arm in ("b1-B1", "b1-B2", "b1-B1E"):
        bare = runtime.ARMS[tr.bare_arm(arm)]
        assert bare["memory_summary_secret_marking"] is True and bare["memory_knowledge_filter"] is True
        assert not any(bare[n] for n in ("memory_episodes_recall", "memory_facts_inject", "memory_embed_recall"))
    with pytest.raises(SystemExit, match="B 계열"):
        tr.bare_arm("b1-A1")


def _p(arm: str, turn: int, sha: list[str]) -> dict[str, object]:
    return {"arm": arm, "turn": turn, "chars": 100, "segmentSha": sha}


def test_self_render_check_compares_each_b_arm_with_its_bare_rerender() -> None:
    points = [
        _p("b1-B2", 2, ["x", "y", "fact"]),
        _p(tr.bare_arm("b1-B2"), 2, ["x", "y"]),
        _p("b1-B2", 3, ["x", "z"]),
        _p(tr.bare_arm("b1-B2"), 3, ["x", "y"]),
        _p("b1-B1", 2, ["x", "y"]),
    ]
    out = tr.self_render_checks(points)
    assert out["b1-B2"] == {"turns": 2, "mismatchedTurns": [3], "status": "fail", "pass": False}
    assert out["b1-B1"]["status"] == "halt"  # 자기 재렌더 점이 없으면 판정하지 않는다


def _args(tmp_path: Path, **extra: object) -> argparse.Namespace:
    log = tmp_path / "insert.jsonl"
    log.write_text('{"turn": 1, "snapshots": 0}\n', encoding="utf-8")
    base = {
        "arms": "b1-A1,b1-B1", "insert_log": log, "baseline": None, "turns": "2,3", "label": None,
        "checkpoint": None, "room": None, "model": "opus", "section_max": 970, "out_dir": tmp_path / "out",
        "compare_turns": "", "run": tmp_path,
    }  # fmt: skip
    return argparse.Namespace(**(base | extra))


def test_b_series_arms_need_a_template_label_and_checkpoint(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="--label"):
        cmd_trajectory_replay(_args(tmp_path))
    with pytest.raises(SystemExit, match="--checkpoint"):
        cmd_trajectory_replay(_args(tmp_path, label="b1-measure"))
