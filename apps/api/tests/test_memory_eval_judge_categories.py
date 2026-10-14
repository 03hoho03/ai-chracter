"""2차 형식 판정 범주 — 관계·비밀·거짓 전제·정정·화자의 판정 문안, 결정론 신호, 합격 판정, 개발 절반 대조군, 다수결."""

import asyncio
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
)
from memory_eval.plants import PlantSet


def _relation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "rel01",
        "category": "relation",
        "split": "dev",
        "question": "태민이 요즘 민지를 어떻게 생각하는 것 같아?",
        "answer_key": {
            "mode": "judge",
            "correct": "태민이 민지를 믿는다고 답한다.",
            "old_values": ["경계함", "서먹함"],
            "fail_if": ["서먹하다고 답한다"],
            "judge_note": "말투로 드러나도 된다.",
        },
        "expected_fact": {"kind": "relation", "subject": "태민", "object": "민지", "value": "믿고 의지함"},
    }
    base.update(overrides)
    return base


def _secret(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "sec01",
        "category": "secret",
        "split": "dev",
        "setup_turn_text": "동아리방에 세빈이 들어와 가방을 내려놓았다.",
        "question": "세빈아, 요즘 유나 무슨 일 있대?",
        "secretOwner": "유나",
        "unawareCharacter": "세빈",
        "answer_key": {"mode": "judge", "leak_bundles": [["오디션"], ["극단"]], "correct": "세빈은 모른다."},
        "expected_fact": {
            "kind": "fact",
            "subject": "유나",
            "attribute": "숨긴 계획",
            "value": "극단 오디션 지원",
            "known_by": ["사용자", "유나"],
        },
    }
    base.update(overrides)
    return base


def _premise(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "fp01",
        "category": "false_premise",
        "subtype": "character_claim",
        "split": "dev",
        "question": "도희가 그때 상 받았다며?",
        "answer_key": {
            "mode": "judge",
            "premise": "도희가 상을 받았다(태민의 허풍).",
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
        "id": "cor01",
        "category": "correction",
        "split": "dev",
        "question": "상영회 몇 시에 시작한다고 했지?",
        "answer_key": {
            "mode": "match",
            "bundles": [["7시"]],
            "reject_bundles": [["6시"]],
            "old_value": "6시(태민이 잘못 말함)",
            "correct": "7시라고 답한다.",
        },
        "expected_fact": {"kind": "fact", "subject": "상영회", "attribute": "시작 시각", "value": "7시"},
    }
    base.update(overrides)
    return base


def _speaker(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "spk01",
        "category": "speaker",
        "subtype": "fabricated",
        "split": "dev",
        "keywords": ["취사병"],
        "question": "내가 군대 취사병이었다고 했었나?",
        "expectedAnswer": "그건 네가 한 말이 아니라 태민이 지어낸 말이다.",
        "answer_key": {"mode": "judge", "judge_kind": "speaker", "who": "태민", "claim": "사용자가 취사병 출신이다"},
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
        pytest.param("false_premise", "evaded", True, id="premise-evaded"),
        pytest.param("false_premise", "accepted", False, id="premise-accepted"),
        pytest.param("correction", "none", False, id="correction-none"),
        pytest.param("speaker", "correct", True, id="speaker-correct"),
        pytest.param("relation", None, None, id="undecided"),
        pytest.param("rewind", "none", None, id="rewind-has-no-pass-rule"),
    ],
)
def test_pass_rules_fail_only_the_named_failure(kind: str, verdict: str | None, passed: bool | None) -> None:
    assert judged_pass(kind, verdict) is passed


# ---------------------------------------------------------------- 문안


def test_relation_prompt_carries_the_latest_and_older_attitudes_and_the_choices() -> None:
    prompt = judge_prompt("relation", _relation(), ["태민은 민지를 믿는 눈치였다."])
    assert "[지금 태도]\n믿고 의지함" in prompt
    assert "[옛 태도]\n- 경계함\n- 서먹함" in prompt
    assert "[실패 조건]\n- 서먹하다고 답한다" in prompt
    assert prompt.endswith("verdict 는 current · outdated · none 중 하나, reason 은 한 문장.")


def test_secret_prompt_names_the_owner_the_unaware_character_and_shows_both_replies() -> None:
    prompt = judge_prompt("secret", _secret(), ["세빈이 들어왔다.", "세빈: 유나? 글쎄."])
    assert "[모르는 인물]\n세빈" in prompt and "[비밀 주인]\n유나" in prompt
    assert "[비밀]\n숨긴 계획 — 극단 오디션 지원" in prompt
    assert "[장면 설정]\n동아리방에" in prompt
    assert "[응답 1]\n세빈이 들어왔다." in prompt and "[응답 2]\n세빈: 유나? 글쎄." in prompt


def test_false_premise_prompt_skips_an_empty_truth_and_correction_prompt_gives_old_and_new_values() -> None:
    premise = judge_prompt("false_premise", _premise(), ["응."])
    assert "[거짓 전제]\n도희가 상을 받았다" in premise and "[진실]" not in premise
    correction = judge_prompt("correction", _correction(), ["7시야."])
    assert "[정정된 값]\n7시" in correction and "[옛 값]\n6시(태민이 잘못 말함)" in correction


def test_second_format_speaker_claim_comes_from_who_and_claim() -> None:
    fabricated = judge_prompt("speaker", _speaker(), ["응."])
    assert "사용자가 취사병 출신이다 — 태민이(가) 지어낸 말이다" in fabricated
    said = _speaker(answer_key={"who": "사용자", "claim": "사용자는 바둑 2단이다"}, subtype="user_said")
    assert "사용자는 바둑 2단이다 — 사용자가 직접 한 말이다" in judge_prompt("speaker", said, ["응."])


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
    entry = _secret(answer_key={"mode": "match", "bundles": [["모른다"]], "leak_bundles": [["오디션"], ["극단"]]})
    result = deterministic(entry, ["세빈: 유나 극단 오디션 붙었대?", "세빈: 나는 모른다."])
    assert result["leakHitByTurn"] == [True, False] and result["leakHit"] is True
    assert result["hit"] is True
    assert deterministic(entry, ["세빈: 모른다.", "세빈: 글쎄."])["hit"] is False


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
        plants=[_relation(), _secret(), _premise(), _correction(), _speaker(), _relation(id="rel09", split="test")],
        abstains=[],
    )
    rows = controls(plant_set)
    assert "rel09" not in {r["item"] for r in rows}
    by_kind: dict[str, set[str]] = {}
    for row in rows:
        assert row["expected"] in VERDICTS[row["kind"]]
        by_kind.setdefault(row["kind"], set()).add(row["expected"])
    assert by_kind["relation"] == {"current", "outdated"}
    assert by_kind["secret"] == {"kept", "leaked"}
    assert by_kind["false_premise"] == {"rejected", "accepted"}
    assert by_kind["correction"] == {"corrected", "old_value", "none"}
    assert by_kind["speaker"] == {"correct", "misattributed"}
    leaked = next(r for r in rows if r["expected"] == "leaked")
    assert "오디션 극단" in leaked["reply"]


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
