import uuid

from api.chat.stats import StatChange, apply_stat_changes
from api.db.models.story import StatDef


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
