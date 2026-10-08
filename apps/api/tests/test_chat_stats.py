"""카운터 스탯(`per_turn_delta`)을 굴리는 쪽 — `apply_rule_judgment` 가 발동 규칙 없이 불려도(판정 LLM 을 부르지 않은 턴)
카운터는 매 턴 움직여야 한다. 규칙 고르기·폭 반영은 `test_chat_stat_rules.py` 가 본다."""

import uuid

from api.chat.stats import apply_rule_judgment
from api.db.models.story import StatDef


def test_apply_rule_judgment_ticks_per_turn_counter_without_any_fired_rule() -> None:
    """`per_turn_delta` 스탯은 판단 대상이 아니라 시스템이 굴리는 카운터다 — 발동한 규칙이 없어도 매 턴 반드시 그만큼
    움직여야 한다.

    실측(2026-08-07) 으로 판정 LLM 이 '남은 방송 회차' 의 감소를 여러 턴 건너뛰었고,
    그 카운터에 걸린 엔딩(`남은 방송 회차<=12`)은 그만큼 늦게/영영 안 열린다.
    """
    oxygen = uuid.uuid4()
    defs = [StatDef(entity_id=oxygen, min_value=0, max_value=100, initial_value=100, per_turn_delta=-5)]

    result = apply_rule_judgment({str(oxygen): 100.0}, [], {}, defs)

    assert result[str(oxygen)] == 95


def test_apply_rule_judgment_clamps_per_turn_counter_at_boundary() -> None:
    days = uuid.uuid4()
    defs = [StatDef(entity_id=days, min_value=0, max_value=30, initial_value=30, per_turn_delta=-1)]

    assert apply_rule_judgment({str(days): 0.0}, [], {}, defs)[str(days)] == 0


def test_apply_rule_judgment_falls_back_to_initial_value_when_counter_not_seeded() -> None:
    """첫 턴처럼 `current` 에 카운터 값이 아직 없으면 `initial_value` 에서 굴린다 — 폴백이 없으면 `None + delta` 로
    TypeError 가 나야 한다."""
    oxygen = uuid.uuid4()
    defs = [StatDef(entity_id=oxygen, min_value=0, max_value=100, initial_value=100, per_turn_delta=-5)]

    result = apply_rule_judgment({}, [], {}, defs)

    assert result[str(oxygen)] == 95


def test_apply_rule_judgment_keeps_judged_stats_while_counters_tick() -> None:
    """한 시작설정 안에 판정 스탯과 카운터가 섞인다. 발동 규칙이 없으면 판정 스탯은 그대로, 카운터만 움직인다."""
    trust = uuid.uuid4()
    days = uuid.uuid4()
    defs = [
        StatDef(entity_id=trust, min_value=0, max_value=100, initial_value=30),
        StatDef(entity_id=days, min_value=0, max_value=30, initial_value=30, per_turn_delta=-1),
    ]

    result = apply_rule_judgment({str(trust): 30.0, str(days): 30.0}, [], {}, defs)

    assert result == {str(trust): 30.0, str(days): 29.0}
