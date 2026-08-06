from dataclasses import dataclass

from api.db.models.story import StatDef


@dataclass(frozen=True)
class StatChange:
    stat_id: str
    new_value: float


def _clamp(value: float, stat_def: StatDef) -> float:
    return min(max(value, stat_def.min_value), stat_def.max_value)


def apply_stat_changes(
    current: dict[str, float],
    changes: list[StatChange],
    defs: list[StatDef],
) -> dict[str, float]:
    """techspec-backend-chat.md §3.1 판단 로직 — LLM이 판단한 절대값(newValue)을
    stat_defs의 min/max 범위로 clamp한다. defs에 없는 statId는 무시하고 나머지
    스탯은 영향받지 않는다.

    **`per_turn_delta`가 있는 스탯은 판단 대상이 아니라 시스템이 굴리는 카운터다** —
    매 턴 그 값만큼 결정적으로 더하고, LLM이 그 스탯에 대해 낸 판단은 무시한다. "매 턴
    반드시 1씩 줄어든다" 류를 description 산문으로만 두면 판정 LLM이 조용히 건너뛰거나
    거꾸로 올리는 일이 실제로 있었고(2026-08-07 실측: '남은 날' 26→27), 그 카운터에
    걸린 엔딩은 도달 가능성이 통째로 흔들린다. 턴당 변화와 행동 반응이 **섞인** 스탯에는
    이 필드를 쓰지 않는다 — 쓰면 LLM이 그 스탯을 영영 못 건드리게 되어 설계가 깨진다.

    호출부가 턴당 정확히 한 번만 부르는 것이 이 함수의 전제다(`_stream_new_turn` /
    `_stream_preview_turn`). 판정 LLM 호출이 실패하면 이 함수 자체가 호출되지 않아 그 턴은
    카운터도 함께 멈춘다 — 턴 전체를 무효로 보는 기존 실패 처리와 같은 결이다.
    """
    defs_by_id = {str(stat_def.entity_id): stat_def for stat_def in defs}
    result = dict(current)

    for stat_id, counter in defs_by_id.items():
        if counter.per_turn_delta is None:
            continue
        base = result.get(stat_id, float(counter.initial_value))
        result[stat_id] = _clamp(base + counter.per_turn_delta, counter)

    for change in changes:
        judged = defs_by_id.get(change.stat_id)
        if judged is None or judged.per_turn_delta is not None:
            continue
        result[change.stat_id] = _clamp(change.new_value, judged)
    return result
