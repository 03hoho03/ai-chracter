import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from api.db.models.story import StatDef, StatRule

logger = logging.getLogger(__name__)


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


def apply_rule_judgment(
    current: dict[str, float],
    fired_rule_ids: Sequence[str],
    rule_ids: Mapping[str, tuple[str, StatRule]],
    defs: list[StatDef],
) -> dict[str, float]:
    """판정 LLM 이 고른 규칙(짧은 id 목록)을 스탯 값에 반영한다. `rule_ids` 는 판정 프롬프트 빌더
    (`build_stat_rule_judgment_prompt`)가 돌려준 짧은 id → (스탯 entity_id, 규칙) 대응표다.

    카운터 스탯(`per_turn_delta`)은 `apply_stat_changes` 와 똑같이 먼저 굴리고, 판정 폭은 더하지 않는다.

    판정 스탯은 그 스탯에 대응하는 발동 규칙 중 |폭| 이 가장 큰 **하나**만 골라 **턴 시작 값**(`current`, 없으면
    `initial_value`)에 더하고 최소·최대로 자른다. 폭을 합치지 않으므로 한 턴에 한 스탯이 움직이는 폭은 작가가 쓴 규칙 하나의
    폭을 넘지 않는다. |폭| 이 같으면 규칙 순서(`order`)가 앞선 것을 고른다 — 모델이 낸 목록 순서가 아니라 작가가 정한 순서로
    정해, 결과가 응답의 나열 순서에 좌우되지 않는다. 대응은 (스탯, 규칙) 쌍으로 하므로 다른 스탯의 규칙이 이 스탯의 비교에
    섞이지 않는다.

    대응표에 없는 id(모델이 지어낸 것)는 버리고 경고를 남긴다. 같은 id 가 여러 번 와도 한 번이다. 대응표가 `defs` 에 없는
    스탯이나 카운터 스탯을 가리키면 그 규칙은 쓰지 않는다. 발동한 규칙이 없는 스탯은 값 그대로다.

    변화 방향·한 턴 최대 폭 옵션은 보지 않는다 — 두 옵션은 판정이 낸 절대값을 자르는 장치이고, 이 경로의 폭은 작가가 규칙에
    직접 쓴 값이다.

    호출 전제는 `apply_stat_changes` 와 같다 — 턴당 한 번, 판정 호출이 실패하면 부르지 않는다(그 턴은 카운터도 멈춘다).
    """
    defs_by_id = {str(stat_def.entity_id): stat_def for stat_def in defs}
    result = dict(current)

    for stat_id, counter in defs_by_id.items():
        if counter.per_turn_delta is None:
            continue
        base = result.get(stat_id, float(counter.initial_value))
        result[stat_id] = _clamp(base + counter.per_turn_delta, counter)

    chosen_by_stat_id: dict[str, StatRule] = {}
    unknown_ids: list[str] = []
    for rule_id in dict.fromkeys(fired_rule_ids):
        target = rule_ids.get(rule_id)
        if target is None:
            unknown_ids.append(rule_id)
            continue
        stat_id, rule = target
        chosen = chosen_by_stat_id.get(stat_id)
        if chosen is None or (abs(rule.delta), -rule.order) > (abs(chosen.delta), -chosen.order):
            chosen_by_stat_id[stat_id] = rule
    if unknown_ids:
        logger.warning("스탯 규칙 판정이 모르는 규칙 id 를 냈다 — 버린다: %s", unknown_ids)

    for stat_id, rule in chosen_by_stat_id.items():
        judged = defs_by_id.get(stat_id)
        if judged is None or judged.per_turn_delta is not None:
            continue
        start = current[stat_id] if stat_id in current else float(judged.initial_value)
        result[stat_id] = _clamp(start + rule.delta, judged)
    return result
