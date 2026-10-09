"""스탯 규칙 판정 — 반영 함수(`apply_rule_judgment`), 판정 프롬프트 빌더(`build_stat_rule_judgment_prompt`), 판정을
부를지 정하는 함수(`prepare_stat_judgment`). 전부 DB 없이 생성자로 채운 ORM 객체로 돈다."""

import logging
import uuid

import pytest

from api.chat.prompt_builder import (
    PromptNames,
    build_stat_rule_judgment_prompt,
    prepare_stat_judgment,
    stat_rule_letters,
)
from api.chat.stats import apply_rule_judgment
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StatDef, StatRule

_NAMES = PromptNames(persona_name="하늘", default_user_name="", char_name=None)


def _stat(
    *,
    name: str = "호감도",
    description: str | None = None,
    min_value: int = 0,
    max_value: int = 100,
    per_turn_delta: int | None = None,
) -> StatDef:
    return StatDef(
        entity_id=uuid.uuid4(),
        name=name,
        description=description if description is not None else f"{name} 설명",
        min_value=min_value,
        max_value=max_value,
        initial_value=50,
        per_turn_delta=per_turn_delta,
    )


def _rule(delta: int, order: int, condition: str = "조건") -> StatRule:
    return StatRule(entity_id=uuid.uuid4(), condition=condition, delta=delta, order=order)


def _ids(stat: StatDef, *rules: StatRule, letter: str = "a") -> dict[str, tuple[str, StatRule]]:
    return {f"{letter}{index}": (str(stat.entity_id), rule) for index, rule in enumerate(rules, start=1)}


# ---- 반영 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("deltas", "fired", "expected"),
    [
        pytest.param([3, -7, 5], ["a1", "a2", "a3"], 43.0, id="largest-magnitude-wins-over-sign"),
        pytest.param([3, 5], ["a1", "a2"], 55.0, id="largest-positive"),
        pytest.param([5, -5], ["a2", "a1"], 55.0, id="tie-goes-to-earlier-order-not-list-order"),
        pytest.param([-5, 5], ["a2", "a1"], 45.0, id="tie-goes-to-earlier-order-reversed"),
        pytest.param([4], ["a1", "a1", "a1"], 54.0, id="repeated-id-applies-once"),
        pytest.param([4], [], 50.0, id="nothing-fired"),
    ],
)
def test_apply_rule_judgment_adds_one_rule_per_stat(deltas: list[int], fired: list[str], expected: float) -> None:
    """한 스탯에서 여러 규칙이 발동해도 |폭| 이 가장 큰 하나만 더한다. 동점은 규칙 순서(`order`)가 앞선 것이다 — 모델이 낸
    목록 순서가 아니다. 같은 id 가 여러 번 와도 한 번이다. 발동이 없으면 값 그대로."""
    stat = _stat()
    rules = [_rule(delta, order) for order, delta in enumerate(deltas)]

    result = apply_rule_judgment({str(stat.entity_id): 50.0}, fired, _ids(stat, *rules), [stat])

    assert result == {str(stat.entity_id): expected}


@pytest.mark.parametrize(
    ("start", "delta", "expected"),
    [
        pytest.param(95.0, 10, 100.0, id="clamped-at-max"),
        pytest.param(5.0, -10, 0.0, id="clamped-at-min"),
        pytest.param(90.0, 10, 100.0, id="lands-on-max"),
    ],
)
def test_apply_rule_judgment_clamps_to_the_stat_range(start: float, delta: int, expected: float) -> None:
    stat = _stat()
    rule = _rule(delta, 0)

    result = apply_rule_judgment({str(stat.entity_id): start}, ["a1"], _ids(stat, rule), [stat])

    assert result[str(stat.entity_id)] == expected


def test_apply_rule_judgment_starts_from_initial_value_without_a_current_value() -> None:
    """방에 아직 값이 없는 스탯(버전을 옮긴 방의 새 스탯)은 시작값에서 더한다."""
    stat = _stat()

    result = apply_rule_judgment({}, ["a1"], _ids(stat, _rule(7, 0)), [stat])

    assert result == {str(stat.entity_id): 57.0}


def test_apply_rule_judgment_drops_unknown_ids_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    stat = _stat()

    with caplog.at_level(logging.WARNING, logger="api.chat.stats"):
        result = apply_rule_judgment({str(stat.entity_id): 50.0}, ["z9", "a1"], _ids(stat, _rule(2, 0)), [stat])

    assert result == {str(stat.entity_id): 52.0}
    assert "z9" in caplog.text


def test_apply_rule_judgment_keeps_each_stats_rules_to_that_stat() -> None:
    """규칙은 (스탯, 규칙) 쌍으로 대응한다 — 다른 스탯의 큰 폭 규칙이 이 스탯의 최대 폭 비교에 끼면 안 된다."""
    affection, trust = _stat(name="호감도"), _stat(name="신뢰")
    rule_ids = {**_ids(affection, _rule(2, 0)), **_ids(trust, _rule(-9, 0), letter="b")}
    current = {str(affection.entity_id): 50.0, str(trust.entity_id): 50.0}

    result = apply_rule_judgment(current, ["a1", "b1"], rule_ids, [affection, trust])

    assert result == {str(affection.entity_id): 52.0, str(trust.entity_id): 41.0}


def test_apply_rule_judgment_rolls_counters_and_ignores_rules_pointing_at_them() -> None:
    """카운터 스탯은 현행처럼 매 턴 굴린다. 대응표가 카운터를 가리켜도(빌더는 싣지 않는다) 판정 폭은 더하지 않는다."""
    judged, counter = _stat(name="호감도"), _stat(name="남은 날", per_turn_delta=-1)
    rule_ids = {**_ids(judged, _rule(3, 0)), **_ids(counter, _rule(-20, 0), letter="b")}
    current = {str(judged.entity_id): 50.0, str(counter.entity_id): 10.0}

    result = apply_rule_judgment(current, ["a1", "b1"], rule_ids, [judged, counter])

    assert result == {str(judged.entity_id): 53.0, str(counter.entity_id): 9.0}


def test_apply_rule_judgment_skips_a_stat_missing_from_defs() -> None:
    """대응표의 스탯이 스탯 목록에 없으면 그 규칙은 쓰지 않는다(범위를 모르면 자를 수 없다)."""
    known, gone = _stat(), _stat()
    rule_ids = {**_ids(known, _rule(1, 0)), **_ids(gone, _rule(5, 0), letter="b")}

    result = apply_rule_judgment({str(known.entity_id): 50.0}, ["a1", "b1"], rule_ids, [known])

    assert result == {str(known.entity_id): 51.0}


# ---- 빌더 ---------------------------------------------------------------------------------------


def _prompt_set() -> PromptSet:
    return PromptSet(user_label="사용자", story_assistant_label="진행자")


def _sections(channel: str = "stat_rule_judgment") -> list[PromptSection]:
    bodies = [
        ("stat_defs_intro", "[스탯]\n{stat_lines}", False),
        ("user_name", "이름: {user_name}", True),
        ("turn_context", "{user_label}: {user_message}\n{assistant_label}: {assistant_message}", False),
        ("judgment_instruction", "[지시]", False),
    ]
    return [
        PromptSection(channel=channel, scope="story", slot=slot, variant="", body=body, conditional=conditional, order=order)
        for order, (slot, body, conditional) in enumerate(bodies, start=1)
    ]


def test_build_stat_rule_judgment_prompt_lists_rules_under_short_ids_without_values() -> None:
    """판정 스탯마다 이름·범위·설명과 규칙 줄을 싣는다. 현재값과 폭은 싣지 않고(맥락의 점수가 판정을 끌어당긴다), 카운터
    스탯은 블록째 뺀다. 짧은 id 는 스탯 글자 + 규칙 순서(`order`)이고, 대응표가 그 id 를 (스탯, 규칙) 으로 돌려준다.
    작가 글(이름·설명·조건)과 이번 턴 응답의 `{{user}}` 는 이름으로 바꾸고, 사용자 메시지는 그대로 둔다."""
    affection = _stat(name="{{user}}의 호감", description="{{user}}를 향한 마음")
    counter = _stat(name="남은 날", per_turn_delta=-1)
    trust = _stat(name="신뢰", min_value=-10, max_value=10)
    later, earlier = _rule(5, 1, "{{user}}가 감싸 준다"), _rule(-30, 0, "거짓말이 들킨다")
    trust_rule = _rule(2, 0, "약속을 지킨다")

    prompt, rule_ids = build_stat_rule_judgment_prompt(
        prompt_set=_prompt_set(),
        sections=_sections(),
        stat_defs=[affection, counter, trust],
        rules_by_stat_id={affection.entity_id: [later, earlier], trust.entity_id: [trust_rule], counter.entity_id: []},
        user_message="{{user}} 왔어",
        assistant_message="{{user}}, 어서 와",
        names=_NAMES,
    )

    assert prompt == (
        "[스탯]\n"
        "하늘의 호감 / 범위 [0, 100] / 하늘을 향한 마음\n"
        "- a1: 거짓말이 들킨다\n"
        "- a2: 하늘이 감싸 준다\n"
        "\n"
        "신뢰 / 범위 [-10, 10] / 신뢰 설명\n"
        "- b1: 약속을 지킨다"
        "\n\n이름: 하늘"
        "\n\n사용자: {{user}} 왔어\n진행자: 하늘, 어서 와"
        "\n\n[지시]"
    )
    assert "50" not in prompt and "-30" not in prompt and "남은 날" not in prompt
    assert rule_ids == {
        "a1": (str(affection.entity_id), earlier),
        "a2": (str(affection.entity_id), later),
        "b1": (str(trust.entity_id), trust_rule),
    }


@pytest.mark.parametrize(
    ("index", "letters"),
    [
        pytest.param(0, "a", id="first"),
        pytest.param(25, "z", id="last-single"),
        pytest.param(26, "aa", id="first-double"),
        pytest.param(27, "ab", id="second-double"),
        pytest.param(51, "az", id="last-of-a"),
        pytest.param(52, "ba", id="first-of-b"),
        pytest.param(701, "zz", id="last-double"),
        pytest.param(702, "aaa", id="first-triple"),
    ],
)
def test_stat_rule_letters_never_repeat_past_twenty_six_stats(index: int, letters: str) -> None:
    """스탯 수에는 상한이 없다 — 26개를 넘어도 글자가 겹치면 두 스탯의 규칙 id 가 같아진다."""
    assert stat_rule_letters(index) == letters


def test_stat_rule_letters_are_unique_for_many_stats() -> None:
    assert len({stat_rule_letters(index) for index in range(2000)}) == 2000


# ---- 판정을 부를지 정하기 ------------------------------------------------------------------------


def _prepare(
    stat_defs: list[StatDef], rules_by_stat_id: dict[uuid.UUID, list[StatRule]], sections: list[PromptSection]
) -> tuple[str | None, dict[str, tuple[str, StatRule]]]:
    request = prepare_stat_judgment(
        prompt_set=_prompt_set(),
        sections=sections,
        stat_defs=stat_defs,
        rules_by_stat_id=rules_by_stat_id,
        user_message="메시지",
        assistant_message="응답",
        names=_NAMES,
    )
    return request.prompt, request.rule_ids


def test_prepare_stat_judgment_judges_only_stats_with_rules() -> None:
    """규칙이 있는 판정 스탯만 싣는다. 규칙 없는 판정 스탯(초안에만 생긴다)과 카운터는 빠져 값이 그대로 남는다."""
    judged, unruled = _stat(), _stat(name="신뢰")
    counter = _stat(name="남은 날", per_turn_delta=-1)
    rule = _rule(1, 0)

    prompt, rule_ids = _prepare([unruled, judged, counter], {judged.entity_id: [rule], unruled.entity_id: []}, _sections())

    assert prompt is not None
    assert prompt.startswith("[스탯]\n호감도 / ")
    assert "신뢰" not in prompt and "남은 날" not in prompt
    assert rule_ids == {"a1": (str(judged.entity_id), rule)}


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("judged-stats-without-rules", id="judged-stats-without-rules"),
        pytest.param("counters-only", id="counters-only"),
        pytest.param("no-stats", id="no-stats"),
    ],
)
def test_prepare_stat_judgment_skips_the_call_without_any_ruled_judged_stat(
    case: str, caplog: pytest.LogCaptureFixture
) -> None:
    """규칙 있는 판정 스탯이 없으면 판정을 부르지 않는 요청이다(호출부가 "변화 없음"으로 반영하고 엔딩 판정을 잇는다).
    세트 설정 문제가 아니므로 경고를 남기지 않는다."""
    judged = _stat()
    counter = _stat(name="남은 날", per_turn_delta=-1)
    stat_defs: list[StatDef] = [judged, counter]
    rules: dict[uuid.UUID, list[StatRule]] = {judged.entity_id: []}
    if case == "counters-only":
        stat_defs, rules = [counter], {counter.entity_id: [_rule(1, 0)]}
    elif case == "no-stats":
        stat_defs, rules = [], {}

    with caplog.at_level(logging.WARNING):
        prompt, rule_ids = _prepare(stat_defs, rules, _sections())

    assert prompt is None
    assert rule_ids == {}
    assert not caplog.records


def test_prepare_stat_judgment_skips_the_call_and_warns_when_the_channel_renders_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """활성 세트에 규칙 판정 채널 행이 없어 렌더가 빈 문자열이면, 빈 프롬프트로 판정을 부르지 않고 경고를 남긴다."""
    judged = _stat()

    with caplog.at_level(logging.WARNING):
        prompt, rule_ids = _prepare([judged], {judged.entity_id: [_rule(1, 0)]}, _sections(channel="stat_judgment"))

    assert prompt is None
    assert rule_ids == {}
    assert any("렌더가 비었다" in record.getMessage() for record in caplog.records)
