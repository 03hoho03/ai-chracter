import uuid

from api.chat.stats import StatChange, apply_stat_changes
from api.db.models.story import StatChangeDirection, StatDef


def _stat_def(entity_id: uuid.UUID, min_value: int, max_value: int) -> StatDef:
    return StatDef(entity_id=entity_id, min_value=min_value, max_value=max_value)


def test_apply_stat_changes_clamps_value_below_min() -> None:
    affection = uuid.uuid4()
    defs = [_stat_def(affection, min_value=0, max_value=100)]

    result = apply_stat_changes({str(affection): 20.0}, [StatChange(str(affection), -10.0)], defs)

    assert result[str(affection)] == 0


def test_apply_stat_changes_clamps_value_above_max() -> None:
    affection = uuid.uuid4()
    defs = [_stat_def(affection, min_value=0, max_value=100)]

    result = apply_stat_changes({str(affection): 20.0}, [StatChange(str(affection), 150.0)], defs)

    assert result[str(affection)] == 100


def test_apply_stat_changes_keeps_value_exactly_at_boundary() -> None:
    affection = uuid.uuid4()
    defs = [_stat_def(affection, min_value=0, max_value=100)]

    result = apply_stat_changes({str(affection): 20.0}, [StatChange(str(affection), 100.0)], defs)

    assert result[str(affection)] == 100


def test_apply_stat_changes_within_range_is_unaffected() -> None:
    affection = uuid.uuid4()
    defs = [_stat_def(affection, min_value=0, max_value=100)]

    result = apply_stat_changes({str(affection): 20.0}, [StatChange(str(affection), 55.0)], defs)

    assert result[str(affection)] == 55


def test_apply_stat_changes_ignores_undefined_stat_id() -> None:
    affection = uuid.uuid4()
    unknown = uuid.uuid4()
    defs = [_stat_def(affection, min_value=0, max_value=100)]

    result = apply_stat_changes({str(affection): 20.0}, [StatChange(str(unknown), 999.0)], defs)

    assert result == {str(affection): 20.0}


def test_apply_stat_changes_leaves_other_stats_unaffected() -> None:
    affection = uuid.uuid4()
    trust = uuid.uuid4()
    defs = [_stat_def(affection, min_value=0, max_value=100), _stat_def(trust, min_value=0, max_value=100)]
    current = {str(affection): 20.0, str(trust): 30.0}

    result = apply_stat_changes(current, [StatChange(str(affection), 150.0)], defs)

    assert result[str(affection)] == 100
    assert result[str(trust)] == 30


def test_apply_stat_changes_ticks_per_turn_counter_without_any_llm_change() -> None:
    """`per_turn_delta` 스탯은 판단 대상이 아니라 시스템이 굴리는 카운터다 — LLM 이
    statChanges 에 아무것도 넣지 않아도 매 턴 반드시 그만큼 움직여야 한다.

    실측(2026-08-07) 으로 판정 LLM 이 '남은 방송 회차' 의 감소를 여러 턴 건너뛰었고,
    그 카운터에 걸린 엔딩(`남은 방송 회차<=12`)은 그만큼 늦게/영영 안 열린다.
    """
    oxygen = uuid.uuid4()
    defs = [StatDef(entity_id=oxygen, min_value=0, max_value=100, initial_value=100, per_turn_delta=-5)]

    result = apply_stat_changes({str(oxygen): 100.0}, [], defs)

    assert result[str(oxygen)] == 95


def test_apply_stat_changes_ignores_llm_judgment_for_per_turn_counters() -> None:
    """카운터를 LLM 이 거꾸로 올려도(실측: '남은 날' 26→27) 무시하고 델타만 적용한다."""
    days = uuid.uuid4()
    defs = [StatDef(entity_id=days, min_value=0, max_value=30, initial_value=30, per_turn_delta=-1)]

    result = apply_stat_changes({str(days): 26.0}, [StatChange(str(days), 27.0)], defs)

    assert result[str(days)] == 25


def test_apply_stat_changes_clamps_per_turn_counter_at_boundary() -> None:
    days = uuid.uuid4()
    defs = [StatDef(entity_id=days, min_value=0, max_value=30, initial_value=30, per_turn_delta=-1)]

    assert apply_stat_changes({str(days): 0.0}, [], defs)[str(days)] == 0


def test_apply_stat_changes_falls_back_to_initial_value_when_counter_not_seeded() -> None:
    """뮤테이션: stats.py:42 의 `.get(stat_id, float(initial_value))` 폴백을
    `.get(stat_id, None)`으로 바꿔도 기존 테스트가 안 죽었다 — 전부 `per_turn_delta` 스탯을
    `current`에 미리 심어서 폴백을 안 탔다. 첫 턴처럼 `current`에 아직 없는 케이스를 넣는다 —
    폴백이 없으면 `None + delta`로 TypeError 가 나야 한다.
    """
    oxygen = uuid.uuid4()
    defs = [StatDef(entity_id=oxygen, min_value=0, max_value=100, initial_value=100, per_turn_delta=-5)]

    result = apply_stat_changes({}, [], defs)

    assert result[str(oxygen)] == 95


def test_apply_stat_changes_applies_valid_change_after_an_invalid_one_in_list() -> None:
    """뮤테이션: stats.py:48 의 `continue`가 `break`로 바뀌어도 기존 테스트가
    안 죽었다 — `changes`에 무효 항목(미정의 statId)이 있는 케이스는 있었지만 그게 항상
    마지막이었다. 무효 항목을 중간에 두고 뒤에 유효 항목을 이어 붙여, `break`라면 뒤쪽이
    조용히 사라지는 것을 잡는다.
    """
    affection = uuid.uuid4()
    unknown = uuid.uuid4()
    defs = [_stat_def(affection, min_value=0, max_value=100)]

    result = apply_stat_changes(
        {str(affection): 20.0},
        [StatChange(str(unknown), 999.0), StatChange(str(affection), 80.0)],
        defs,
    )

    assert result[str(affection)] == 80


def test_apply_stat_changes_still_judges_stats_without_a_delta() -> None:
    """델타가 없는 스탯은 종전 그대로 LLM 판단을 따른다 — 한 시작설정 안에 두 종류가 섞인다."""
    trust = uuid.uuid4()
    days = uuid.uuid4()
    defs = [
        StatDef(entity_id=trust, min_value=0, max_value=100, initial_value=30),
        StatDef(entity_id=days, min_value=0, max_value=30, initial_value=30, per_turn_delta=-1),
    ]

    result = apply_stat_changes(
        {str(trust): 30.0, str(days): 30.0}, [StatChange(str(trust), 55.0)], defs
    )

    assert result[str(trust)] == 55
    assert result[str(days)] == 29


def _limited_stat_def(
    entity_id: uuid.UUID,
    *,
    change_direction: StatChangeDirection | None = None,
    max_change_per_turn: int | None = None,
    min_value: int = 0,
    max_value: int = 100,
) -> StatDef:
    return StatDef(
        entity_id=entity_id,
        min_value=min_value,
        max_value=max_value,
        initial_value=50,
        change_direction=change_direction,
        max_change_per_turn=max_change_per_turn,
    )


def test_apply_stat_changes_decrease_only_stat_keeps_value_when_judged_upward() -> None:
    """'남은 날' 같은 스탯을 판정 LLM 이 거꾸로 올리는 일이 실제로 있었다. 감소만 허용한 스탯은 올라가지 않고 그대로
    남고, 내려가는 판정은 그대로 받는다."""
    days = uuid.uuid4()
    defs = [_limited_stat_def(days, change_direction="decrease")]

    assert apply_stat_changes({str(days): 26.0}, [StatChange(str(days), 27.0)], defs)[str(days)] == 26
    assert apply_stat_changes({str(days): 26.0}, [StatChange(str(days), 20.0)], defs)[str(days)] == 20


def test_apply_stat_changes_increase_only_stat_keeps_value_when_judged_downward() -> None:
    progress = uuid.uuid4()
    defs = [_limited_stat_def(progress, change_direction="increase")]

    assert apply_stat_changes({str(progress): 40.0}, [StatChange(str(progress), 35.0)], defs)[str(progress)] == 40
    assert apply_stat_changes({str(progress): 40.0}, [StatChange(str(progress), 45.0)], defs)[str(progress)] == 45


def test_apply_stat_changes_limits_step_to_max_change_per_turn_in_both_directions() -> None:
    trust = uuid.uuid4()
    defs = [_limited_stat_def(trust, max_change_per_turn=3)]

    assert apply_stat_changes({str(trust): 50.0}, [StatChange(str(trust), 60.0)], defs)[str(trust)] == 53
    assert apply_stat_changes({str(trust): 50.0}, [StatChange(str(trust), 40.0)], defs)[str(trust)] == 47
    assert apply_stat_changes({str(trust): 50.0}, [StatChange(str(trust), 52.0)], defs)[str(trust)] == 52


def test_apply_stat_changes_measures_step_from_turn_start_and_uses_only_the_last_entry_per_stat() -> None:
    """판정 결과에 같은 스탯이 여러 번 오면 마지막 항목 하나만 받고, 폭은 턴 시작 값에서 잰다. 항목마다 누적해 자르면
    50→53→56 처럼 중복 항목으로 한 턴 최대 폭을 넘길 수 있다."""
    trust = uuid.uuid4()
    defs = [_limited_stat_def(trust, max_change_per_turn=3)]

    stacked = [StatChange(str(trust), 53.0), StatChange(str(trust), 56.0)]
    assert apply_stat_changes({str(trust): 50.0}, stacked, defs)[str(trust)] == 53

    last_wins = [StatChange(str(trust), 60.0), StatChange(str(trust), 49.0)]
    assert apply_stat_changes({str(trust): 50.0}, last_wins, defs)[str(trust)] == 49


def test_apply_stat_changes_measures_constraints_from_initial_value_when_stat_not_seeded() -> None:
    days = uuid.uuid4()
    defs = [_limited_stat_def(days, change_direction="decrease", max_change_per_turn=5)]

    assert apply_stat_changes({}, [StatChange(str(days), 60.0)], defs)[str(days)] == 50
    assert apply_stat_changes({}, [StatChange(str(days), 10.0)], defs)[str(days)] == 45


def test_apply_stat_changes_clamps_to_range_after_direction_and_step() -> None:
    """범위 clamp 가 마지막이다. 버전이 범위를 좁혀 현재값이 범위 밖에 남은 방에서는 증가만 허용한 스탯도 범위
    안으로 내려간다 — 범위가 방향보다 우선한다."""
    progress = uuid.uuid4()
    defs = [_limited_stat_def(progress, change_direction="increase", max_change_per_turn=3, max_value=60)]

    assert apply_stat_changes({str(progress): 70.0}, [StatChange(str(progress), 65.0)], defs)[str(progress)] == 60


def test_apply_stat_changes_treats_unset_options_as_both_directions_without_step_limit() -> None:
    """세션 없이 만든 스탯 행은 두 옵션이 `None` 이다. 양방향·제한 없음으로 읽어 종전과 똑같이 움직여야 한다."""
    trust = uuid.uuid4()
    defs = [_limited_stat_def(trust)]

    assert apply_stat_changes({str(trust): 50.0}, [StatChange(str(trust), 95.0)], defs)[str(trust)] == 95
    assert apply_stat_changes({str(trust): 50.0}, [StatChange(str(trust), 5.0)], defs)[str(trust)] == 5


def test_apply_stat_changes_ignores_non_positive_step_limit_left_in_a_draft() -> None:
    """초안 저장은 0 이하 폭도 받아 준다(발행이 막는다). 미리보기에서 그 값을 그대로 쓰면 스탯이 엉뚱한 쪽으로 튀므로
    제한 없음으로 본다."""
    trust = uuid.uuid4()
    defs = [_limited_stat_def(trust, max_change_per_turn=-2)]

    assert apply_stat_changes({str(trust): 50.0}, [StatChange(str(trust), 60.0)], defs)[str(trust)] == 60


def test_apply_stat_changes_counter_ignores_direction_and_step_options() -> None:
    """턴당 변화가 있는 스탯은 판정을 받지 않으므로 두 옵션도 쓰이지 않는다(초안·미리보기엔 함께 들어올 수 있다)."""
    days = uuid.uuid4()
    defs = [
        StatDef(
            entity_id=days,
            min_value=0,
            max_value=30,
            initial_value=30,
            per_turn_delta=-5,
            change_direction="increase",
            max_change_per_turn=1,
        )
    ]

    assert apply_stat_changes({str(days): 26.0}, [StatChange(str(days), 27.0)], defs)[str(days)] == 21
