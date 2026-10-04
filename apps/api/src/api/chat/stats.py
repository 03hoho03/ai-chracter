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
    """LLM이 판단한 절대값(newValue)을
    stat_defs의 min/max 범위로 clamp한다. defs에 없는 statId는 무시하고 나머지
    스탯은 영향받지 않는다.

    **`per_turn_delta`가 있는 스탯은 판단 대상이 아니라 시스템이 굴리는 카운터다** —
    매 턴 그 값만큼 결정적으로 더하고, LLM이 그 스탯에 대해 낸 판단은 무시한다. "매 턴
    반드시 1씩 줄어든다" 류를 description 산문으로만 두면 판정 LLM이 조용히 건너뛰거나
    거꾸로 올리는 일이 실제로 있었고(2026-08-07 실측: '남은 날' 26→27), 그 카운터에
    걸린 엔딩은 도달 가능성이 통째로 흔들린다. 턴당 변화와 행동 반응이 **섞인** 스탯에는
    이 필드를 쓰지 않는다 — 쓰면 LLM이 그 스탯을 영영 못 건드리게 되어 설계가 깨진다.

    판정을 받는 스탯에는 작가가 **변화 방향**(`change_direction`: 양방향·증가만·감소만)과 **한 턴 최대 폭**
    (`max_change_per_turn`)을 걸 수 있고, 판정 LLM 이 낸 값을 코드가 그 둘로 자른다. 위의 '남은 날' 26→27 역행은
    그 스탯이 아직 판정을 받던 때 일어났다. 이야기 속 날짜처럼 "언제" 움직일지를 판정이 정해야 하는 스탯은 카운터로
    만들 수 없으므로, "감소만"으로 그 부류의 역행을 막는다. 판정 LLM 은 사건을 감지하고, 방향과 폭은 코드가 지킨다.

    자르기는 **턴 시작 값**(`current`, 없으면 `initial_value`)을 기준으로 하고, 판정 목록에 같은 스탯이 여러 번
    오면 마지막 항목 하나만 받는다. 항목마다 누적해 자르면 중복 항목으로 한 턴 최대 폭을 넘길 수 있기 때문이다.
    순서는 방향(반대쪽 변화는 버리고 시작 값 유지) → 폭(시작 값에서 최대 폭까지) → 최소·최대 clamp 다. clamp 가
    마지막이라, 버전이 범위를 좁혀 방의 현재값이 범위 밖에 남아 있으면 clamp 가 방향을 거슬러 값을 옮길 수 있다 —
    범위를 지키는 쪽을 택해 받아들인 동작이다. 두 옵션이 `None`(세션 없이 생성자로 만든 행)이면 양방향·제한
    없음이고, 0 이하 폭(발행이 막지만 초안 미리보기엔 들어올 수 있다)도 제한 없음으로 본다. 카운터 스탯은 판정을
    받지 않으므로 두 옵션을 쓰지 않는다.

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

    last_change_by_id = {change.stat_id: change for change in changes}
    for stat_id, change in last_change_by_id.items():
        judged = defs_by_id.get(stat_id)
        if judged is None or judged.per_turn_delta is not None:
            continue
        start = current[stat_id] if stat_id in current else float(judged.initial_value)
        new_value = change.new_value
        if judged.change_direction == "increase":
            new_value = max(new_value, start)
        elif judged.change_direction == "decrease":
            new_value = min(new_value, start)
        step = judged.max_change_per_turn
        if step is not None and step > 0:
            new_value = min(max(new_value, start - step), start + step)
        result[stat_id] = _clamp(new_value, judged)
    return result
