import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

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

    턴은 값과 함께 판정 이벤트도 받는 `apply_rule_judgment_with_events` 를 부른다 — 반영은 그 함수 하나이고 이 함수는 그 값만
    돌려준다. 호출부가 턴당 정확히 한 번만 부르는 것이 전제다(`chat/turn_judgments.py` 의 `_await_stat_judgment` — 방·미리보기 스탯 판정이 함께 부른다 — 와, 재생성의 재판정이 성공한 결과 하나에 부르는 `_await_stat_rejudgment`). 판정 LLM 호출이
    실패하면 반영 자체가 호출되지 않아 그 턴은 카운터도 함께 멈춘다 — 턴 전체를 무효로 보는 기존 실패 처리와 같은 결이다.
    """
    return apply_rule_judgment_with_events(current, fired_rule_ids, rule_ids, defs).values


@dataclass(frozen=True)
class RuleJudgmentOutcome:
    """반영 결과 — 스탯 값(키 → 값, 바뀌지 않은 스탯 포함)과 그 값을 만든 판정 이벤트 목록."""

    values: dict[str, float]
    events: list[dict[str, Any]]


def _rule_ref(rule: StatRule) -> dict[str, str]:
    """규칙 하나를 가리키는 쌍 — `entityId` 는 판본을 넘어 같은 규칙, `id` 는 그 판본의 규칙 행이다. 방이 대화 중에 새 판본으로
    옮겨지면(최신 판본 고정·이용제한 승격) 같은 `entityId` 가 조건 글이나 폭이 바뀐 규칙을 가리킬 수 있어, 판정기가 그때 본 규칙을
    되짚으려면 행 id 가 함께 있어야 한다."""
    return {"entityId": str(rule.entity_id), "id": str(rule.id)}


def apply_rule_judgment_with_events(
    current: dict[str, float],
    fired_rule_ids: Sequence[str],
    rule_ids: Mapping[str, tuple[str, StatRule]],
    defs: list[StatDef],
) -> RuleJudgmentOutcome:
    """`apply_rule_judgment` 와 같은 반영을 하고, 그 값이 어떻게 나왔는지를 이벤트 목록으로 함께 돌려준다. 턴 기록의
    `stat_events` 가 이 목록이다. 원소는 `defs` 순서로 스탯마다 하나다.

    - 판정 스탯은 그 스탯에 대응하는 발동 규칙이 하나라도 있을 때만 원소가 있다 —
      `{statEntityId, firedRuleIds, appliedRuleId, delta, clamped}`. `firedRuleIds` 는 발동한 그 스탯의 규칙 전부(작가 순서),
      `appliedRuleId` 는 값 반영이 고른 하나, `delta` 는 그 규칙의 폭, `clamped` 는 `시작 값 + 폭` 이 최소·최대를 벗어나 잘렸는지다.
      규칙은 `{entityId, id}` 쌍(`_rule_ref`)으로 가리키고 조건 글은 싣지 않는다. 이미 최대인 스탯에 양의 폭이 적용되면 값은
      그대로지만 원소는 남는다(적용됐고 잘렸다).
    - 카운터 스탯은 매 턴 `{statEntityId, counter: true, delta, clamped}` 하나다 — 발동 규칙 없이 턴당 폭만큼 움직이므로.
    - 대응표에 없는 짧은 id(모델이 지어낸 것)는 하나라도 있으면 맨 끝에 `{unknownRuleIdCount}` 하나로 개수만 남긴다. 짧은 id 는
      프롬프트마다 다시 매기는 글자라 원문은 뜻이 없다. `defs` 에 없거나 카운터인 스탯을 가리키는 규칙은 값처럼 원소에서도 뺀다.

    그래서 이벤트만으로 값이 다시 나온다: 스탯마다 원소가 있으면 `clamp(시작 값 + delta)`, 없으면 시작 값이다(시작 값은 `current`,
    없으면 `initial_value`). 턴 기록에서는 이 값이 시작 값과 다를 때만 `stat_changes` 에 `[시작 값, 그 값]` 으로 오른다."""
    defs_by_id = {str(stat_def.entity_id): stat_def for stat_def in defs}
    values = dict(current)
    event_by_stat_id: dict[str, dict[str, Any]] = {}

    # 값의 키 순서는 이 함수가 생기기 전과 같게 둔다(카운터 먼저 `defs` 순서, 그다음 판정 스탯은 처음 발동한 순서) — 반영
    # 결과의 키 순서가 `statChange` 이벤트와 `stat_changes` 의 순서가 된다.
    for stat_id, counter in defs_by_id.items():
        if counter.per_turn_delta is None:
            continue
        raw = values.get(stat_id, float(counter.initial_value)) + counter.per_turn_delta
        values[stat_id] = _clamp(raw, counter)
        event_by_stat_id[stat_id] = {
            "statEntityId": stat_id,
            "counter": True,
            "delta": counter.per_turn_delta,
            "clamped": values[stat_id] != raw,
        }

    fired_by_stat_id: dict[str, list[StatRule]] = {}
    unknown_ids: list[str] = []
    for rule_id in dict.fromkeys(fired_rule_ids):
        target = rule_ids.get(rule_id)
        if target is None:
            unknown_ids.append(rule_id)
            continue
        stat_id, rule = target
        fired_by_stat_id.setdefault(stat_id, []).append(rule)
    if unknown_ids:
        logger.warning("스탯 규칙 판정이 모르는 규칙 id 를 냈다 — 버린다: %s", unknown_ids)

    for stat_id, fired in fired_by_stat_id.items():
        judged = defs_by_id.get(stat_id)
        if judged is None or judged.per_turn_delta is not None:
            continue
        # |폭| 이 가장 크고, 같으면 작가 순서(`order`)가 앞선 규칙 하나 — 모델이 낸 목록 순서와 무관하다.
        applied = max(fired, key=lambda rule: (abs(rule.delta), -rule.order))
        raw = (current[stat_id] if stat_id in current else float(judged.initial_value)) + applied.delta
        values[stat_id] = _clamp(raw, judged)
        event_by_stat_id[stat_id] = {
            "statEntityId": stat_id,
            "firedRuleIds": [_rule_ref(rule) for rule in sorted(fired, key=lambda rule: rule.order)],
            "appliedRuleId": _rule_ref(applied),
            "delta": applied.delta,
            "clamped": values[stat_id] != raw,
        }

    events = [event_by_stat_id[stat_id] for stat_id in defs_by_id if stat_id in event_by_stat_id]
    if unknown_ids:
        events.append({"unknownRuleIdCount": len(unknown_ids)})
    return RuleJudgmentOutcome(values=values, events=events)
