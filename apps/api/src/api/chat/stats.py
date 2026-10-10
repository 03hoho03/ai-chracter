import logging
from collections.abc import Mapping, Sequence

from api.db.models.story import StatDef, StatRule

logger = logging.getLogger(__name__)


def _clamp(value: float, stat_def: StatDef) -> float:
    return min(max(value, stat_def.min_value), stat_def.max_value)


def apply_rule_judgment(
    current: dict[str, float],
    fired_rule_ids: Sequence[str],
    rule_ids: Mapping[str, tuple[str, StatRule]],
    defs: list[StatDef],
) -> dict[str, float]:
    """판정 LLM 이 고른 규칙(짧은 id 목록)을 스탯 값에 반영한다. `rule_ids` 는 판정 프롬프트 빌더
    (`build_stat_rule_judgment_prompt`)가 돌려준 짧은 id → (스탯 entity_id, 규칙) 대응표다.

    **`per_turn_delta`가 있는 스탯은 판단 대상이 아니라 시스템이 굴리는 카운터다** — 매 턴 그 값만큼 결정적으로 더하고
    최소·최대로 자르며, 규칙 폭은 더하지 않는다. "매 턴 반드시 1씩 줄어든다" 류를 description 산문으로만 두면 판정 LLM이
    조용히 건너뛰거나 거꾸로 올리는 일이 실제로 있었고(2026-08-07 실측: '남은 날' 26→27), 그 카운터에 걸린 엔딩은 도달
    가능성이 통째로 흔들린다. 턴당 변화와 행동 반응이 **섞인** 스탯에는 이 필드를 쓰지 않는다 — 쓰면 그 스탯이 판정을 영영
    받지 못해 설계가 깨진다. 판정 LLM 을 부르지 않은 턴(규칙 있는 판정 스탯이 없는 턴)도 `fired_rule_ids` 를 비워 이 함수를
    불러 카운터를 굴린다.

    판정 스탯은 그 스탯에 대응하는 발동 규칙 중 |폭| 이 가장 큰 **하나**만 골라 **턴 시작 값**(`current`, 없으면
    `initial_value`)에 더하고 최소·최대로 자른다. 폭을 합치지 않으므로 한 턴에 한 스탯이 움직이는 폭은 작가가 쓴 규칙 하나의
    폭을 넘지 않는다. |폭| 이 같으면 규칙 순서(`order`)가 앞선 것을 고른다 — 모델이 낸 목록 순서가 아니라 작가가 정한 순서로
    정해, 결과가 응답의 나열 순서에 좌우되지 않는다. 대응은 (스탯, 규칙) 쌍으로 하므로 다른 스탯의 규칙이 이 스탯의 비교에
    섞이지 않는다.

    대응표에 없는 id(모델이 지어낸 것)는 버리고 경고를 남긴다. 같은 id 가 여러 번 와도 한 번이다. 대응표가 `defs` 에 없는
    스탯이나 카운터 스탯을 가리키면 그 규칙은 쓰지 않는다. 발동한 규칙이 없는 스탯은 값 그대로다.

    호출부가 턴당 정확히 한 번만 부르는 것이 이 함수의 전제다(`chat/turn_judgments.py` 의 `_await_stat_judgment` — 방·미리보기 스탯 판정이 함께 부른다). 판정 LLM 호출이
    실패하면 이 함수 자체가 호출되지 않아 그 턴은 카운터도 함께 멈춘다 — 턴 전체를 무효로 보는 기존 실패 처리와 같은 결이다.
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
