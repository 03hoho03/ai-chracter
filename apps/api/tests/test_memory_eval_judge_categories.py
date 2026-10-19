"""2차 형식 판정 범주 — 관계·비밀·거짓 전제·정정·화자의 판정 문안, 결정론 신호, 합격 판정, 개발 절반 대조군, 다수결."""

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest

from memory_eval.judge import (
    VERDICTS,
    HaikuJudge,
    JudgeVerdict,
    controls,
    deterministic,
    judge_kind,
    judge_prompt,
    judged_majority,
    judged_pass,
    summarize_judged,
)
from memory_eval.plants import PlantSet
from memory_eval_fakes import fake_wording_now

WORDING = fake_wording_now()


def _relation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "relation-a",
        "category": "relation",
        "split": "dev",
        "question": "가상갑이 요즘 가상을를 어떻게 생각하는 것 같아?",
        "answer_key": {
            "mode": "judge",
            "correct": "가상갑이 가상을를 믿는다고 답한다.",
            "old_values": ["가상태도일", "가상태도이"],
            "fail_if": ["가상태도이라고 답한다"],
            "judge_note": "말투로 드러나도 된다.",
        },
        "expected_fact": {"kind": "relation", "subject": "가상갑", "object": "가상을", "value": "가상태도삼"},
    }
    base.update(overrides)
    return base


def _secret(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "secret-a",
        "category": "secret",
        "split": "dev",
        "setup_turn_text": "가상방에 가상병이 들어와 가방을 내려놓았다.",
        "question": "가상병아, 요즘 가상정 무슨 일 있대?",
        "secretOwner": "가상정",
        "unawareCharacter": "가상병",
        "answer_key": {"mode": "judge", "leak_bundles": [["가상시험"], ["가상단"]], "correct": "가상병은 모른다."},
        "expected_fact": {
            "kind": "fact",
            "subject": "가상정",
            "attribute": "가상 속사정",
            "value": "가상 시험 지원",
            "known_by": ["사용자", "가상정"],
        },
    }
    base.update(overrides)
    return base


def _premise(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "premise-a",
        "category": "false_premise",
        "subtype": "character_claim",
        "split": "dev",
        "question": "가상무가 그때 상 받았다며?",
        "answer_key": {
            "mode": "judge",
            "premise": "가상무가 상을 받았다(가상갑이 부풀린 말).",
            "truth": None,
            "accept_bundles": [["상"]],
            "correct": "그런 적 없다고 바로잡는다.",
        },
        "expected_fact": None,
    }
    base.update(overrides)
    return base


def _correction(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "correction-a",
        "category": "correction",
        "split": "dev",
        "question": "가상행사 몇 시에 시작한다고 했지?",
        "answer_key": {
            "mode": "match",
            "bundles": [["7시"]],
            "reject_bundles": [["6시"]],
            "old_value": "6시(가상갑이 잘못 말함)",
            "correct": "7시라고 답한다.",
        },
        "expected_fact": {"kind": "fact", "subject": "가상행사", "attribute": "시작 시각", "value": "7시"},
    }
    base.update(overrides)
    return base


def _speaker(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "speaker-a",
        "category": "speaker",
        "subtype": "fabricated",
        "split": "dev",
        "keywords": ["가상직업"],
        "question": "내가 군대 가상직업이었다고 했었나?",
        "expectedAnswer": "그건 네가 한 말이 아니라 가상갑이 지어낸 말이다.",
        "answer_key": {
            "mode": "judge",
            "judge_kind": "speaker",
            "who": "가상갑",
            "claim": "사용자가 가상직업 출신이다",
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- 종류·합격


def test_second_format_categories_map_to_their_judge_kinds_and_detail_stays_deterministic() -> None:
    assert [judge_kind(e) for e in (_relation(), _secret(), _premise(), _correction(), _speaker())] == [
        "relation",
        "secret",
        "false_premise",
        "correction",
        "speaker",
    ]
    assert judge_kind({"category": "abstain"}) == "abstain"
    assert judge_kind({"category": "detail"}) is None


@pytest.mark.parametrize(
    ("kind", "verdict", "passed"),
    [
        pytest.param("relation", "current", True, id="relation-current"),
        pytest.param("relation", "outdated", False, id="relation-outdated"),
        pytest.param("secret", "leaked", False, id="secret-leaked"),
        pytest.param("false_premise", "unaddressed", True, id="premise-unaddressed-default-not-a-failure"),
        pytest.param("false_premise", "accepted", False, id="premise-accepted"),
        pytest.param("correction", "none", False, id="correction-none"),
        pytest.param("speaker", "correct", True, id="speaker-correct"),
        pytest.param("relation", None, None, id="undecided"),
        pytest.param("rewind", "none", None, id="rewind-has-no-pass-rule"),
    ],
)
def test_pass_rules_fail_only_the_named_failure(kind: str, verdict: str | None, passed: bool | None) -> None:
    assert judged_pass(kind, verdict) is passed


@pytest.mark.parametrize(
    ("policy", "passed"),
    [
        pytest.param("pass", True, id="pass"),
        pytest.param("fail", False, id="fail"),
        pytest.param("exclude", None, id="exclude"),
    ],
)
def test_unaddressed_follows_the_policy_argument(policy: str, passed: bool | None) -> None:
    assert judged_pass("false_premise", "unaddressed", unaddressed=policy) is passed
    assert judged_pass("false_premise", "accepted", unaddressed=policy) is False


def test_summary_counts_unaddressed_separately_and_the_policy_moves_only_the_denominator() -> None:
    rows: list[dict[str, Any]] = [
        {"kind": "false_premise", "judged": "rejected"},
        {"kind": "false_premise", "judged": "accepted"},
        {"kind": "false_premise", "judged": "unaddressed"},
        {"kind": "false_premise", "judged": None},
    ]
    default = summarize_judged(rows)["false_premise"]
    assert (default["unaddressed"], default["undecided"], default["denominator"]) == (1, 1, 3)
    assert default["passRate"] == 2 / 3
    excluded = summarize_judged(rows, unaddressed="exclude")["false_premise"]
    assert (excluded["unaddressed"], excluded["denominator"], excluded["passRate"]) == (1, 2, 0.5)
    assert summarize_judged(rows, unaddressed="fail")["false_premise"]["passRate"] == 1 / 3
    with pytest.raises(ValueError):
        summarize_judged(rows, unaddressed="ignore")


def test_premise_prompt_carries_the_label_definitions_from_the_answer_key() -> None:
    entry = _premise()
    entry["answer_key"]["verdicts"] = {"rejected": "전제를 바로잡는다.", "unaddressed": "다루지 않는다."}
    prompt = judge_prompt("false_premise", entry, ["응."], WORDING)
    assert "[라벨 정의]\n- rejected: 전제를 바로잡는다.\n- unaddressed: 다루지 않는다." in prompt


# ---------------------------------------------------------------- 문안


def test_relation_prompt_carries_the_latest_and_older_attitudes_and_the_choices() -> None:
    prompt = judge_prompt("relation", _relation(), ["가상갑은 가상을를 믿는 눈치였다."], WORDING)
    assert "[지금 태도]\n가상태도삼" in prompt
    assert "[옛 태도]\n- 가상태도일\n- 가상태도이" in prompt
    assert "[실패 조건]\n- 가상태도이라고 답한다" in prompt
    assert prompt.endswith("verdict 는 current · outdated · none 중 하나, reason 은 한 문장.")


def test_secret_prompt_names_the_owner_the_unaware_character_and_shows_both_replies() -> None:
    prompt = judge_prompt("secret", _secret(), ["가상병이 들어왔다.", "가상병: 가상정? 글쎄."], WORDING)
    assert "[모르는 인물]\n가상병" in prompt and "[비밀 주인]\n가상정" in prompt
    assert "[비밀]\n가상 속사정 — 가상 시험 지원" in prompt
    assert "[장면 설정]\n가상방에" in prompt
    assert "[응답 1]\n가상병이 들어왔다." in prompt and "[응답 2]\n가상병: 가상정? 글쎄." in prompt


def test_false_premise_prompt_skips_an_empty_truth_and_correction_prompt_gives_old_and_new_values() -> None:
    premise = judge_prompt("false_premise", _premise(), ["응."], WORDING)
    assert "[거짓 전제]\n가상무가 상을 받았다" in premise and "[진실]\n" not in premise
    assert premise.startswith(WORDING.instructions["false_premise"])
    correction = judge_prompt("correction", _correction(), ["7시야."], WORDING)
    assert "[정정된 값]\n7시" in correction and "[옛 값]\n6시(가상갑이 잘못 말함)" in correction


def test_second_format_speaker_claim_comes_from_who_and_claim() -> None:
    fabricated = judge_prompt("speaker", _speaker(), ["응."], WORDING)
    assert WORDING.claim_character.format(claim="사용자가 가상직업 출신이다", who="가상갑") in fabricated
    said = _speaker(answer_key={"who": "사용자", "claim": "사용자는 가상놀이 2단이다"}, subtype="user_said")
    said_prompt = judge_prompt("speaker", said, ["응."], WORDING)
    assert WORDING.claim_user.format(claim="사용자는 가상놀이 2단이다") in said_prompt


# ---------------------------------------------------------------- 결정론


@pytest.mark.parametrize(
    ("reply", "verdict"),
    [
        pytest.param("일곱 시였잖아, 7시.", "corrected", id="new"),
        pytest.param("6시라고 했던 것 같은데.", "old_value", id="old"),
        pytest.param("처음엔 6시라더니 7시로 바뀌었지.", None, id="both"),
        pytest.param("잘 모르겠어.", None, id="neither"),
    ],
)
def test_correction_is_decided_deterministically_only_when_one_side_matches(reply: str, verdict: str | None) -> None:
    assert deterministic(_correction(), [reply])["detVerdict"] == verdict


def test_secret_leak_signal_checks_both_turns_but_the_answer_only_the_question_turn() -> None:
    entry = _secret(answer_key={"mode": "match", "bundles": [["모른다"]], "leak_bundles": [["가상시험"], ["가상단"]]})
    result = deterministic(entry, ["가상병: 가상정 가상단 가상시험 붙었대?", "가상병: 나는 모른다."])
    assert result["leakHitByTurn"] == [True, False] and result["leakHit"] is True
    assert result["hit"] is True
    assert deterministic(entry, ["가상병: 모른다.", "가상병: 글쎄."])["hit"] is False


def test_premise_echo_and_judge_only_items_have_no_hit() -> None:
    result = deterministic(_premise(), ["그래, 상 받았지."])
    assert result["premiseEcho"] is True and result["hit"] is None


def test_first_format_items_keep_the_first_format_scoring() -> None:
    entry = {"answerKeys": [["펭귄"]]}
    assert deterministic(entry, ["펭귄이었어"]) == {"hit": True, "questionTurnHit": True}


# ---------------------------------------------------------------- 대조군·다수결


def test_controls_cover_each_second_format_kind_from_the_dev_half_only() -> None:
    plant_set = PlantSet(
        raw={},
        plants=[
            _relation(),
            _secret(),
            _premise(),
            _correction(),
            _speaker(),
            _relation(id="relation-z", split="test"),
        ],
        abstains=[],
    )
    rows = controls(plant_set, WORDING)
    assert "relation-z" not in {r["item"] for r in rows}
    by_kind: dict[str, set[str]] = {}
    for row in rows:
        assert row["expected"] in VERDICTS[row["kind"]]
        by_kind.setdefault(row["kind"], set()).add(row["expected"])
    assert by_kind["relation"] == {"current", "outdated"}
    assert by_kind["secret"] == {"kept", "leaked"}
    assert by_kind["false_premise"] == {"rejected", "accepted", "unaddressed"}
    assert by_kind["correction"] == {"corrected", "old_value", "none"}
    assert by_kind["speaker"] == {"correct", "misattributed"}
    leaked = next(r for r in rows if r["expected"] == "leaked")
    assert "가상시험 가상단" in leaked["reply"]


def test_majority_of_three_votes_decides_a_new_kind_and_a_three_way_split_is_undecided() -> None:
    class Fake:
        def __init__(self, votes: list[str]) -> None:
            self.votes = iter(votes)

        async def verdict(self, prompt: str) -> JudgeVerdict:
            return JudgeVerdict(verdict=next(self.votes), reason="r")

    decided, votes = asyncio.run(judged_majority(cast(HaikuJudge, Fake(["kept", "leaked", "kept"])), "secret", "p"))
    assert decided == "kept" and votes == ["kept", "leaked", "kept"]
    split, _ = asyncio.run(judged_majority(cast(HaikuJudge, Fake(["current", "outdated", "none"])), "relation", "p"))
    assert split is None


def test_judge_summary_always_prints_all_three_unaddressed_policies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    path = tmp_path / "judged.json"
    rows = [{"kind": "false_premise", "judged": "unaddressed"}, {"kind": "false_premise", "judged": "rejected"}]
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert main(["--run", str(tmp_path), "judge-summary", "--judged", str(path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {"pass", "fail", "exclude"}
    assert [printed[p]["false_premise"]["passRate"] for p in ("pass", "fail", "exclude")] == [1.0, 0.5, 1.0]
