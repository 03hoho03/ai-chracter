from dataclasses import dataclass

from api.db.models.story import StatDef


@dataclass(frozen=True)
class StatChange:
    stat_id: str
    new_value: float


def apply_stat_changes(
    current: dict[str, float],
    changes: list[StatChange],
    defs: list[StatDef],
) -> dict[str, float]:
    """techspec-backend-chat.md §3.1 판단 로직 — LLM이 판단한 절대값(newValue)을
    stat_defs의 min/max 범위로 clamp한다. defs에 없는 statId는 무시하고 나머지
    스탯은 영향받지 않는다."""
    defs_by_id = {str(stat_def.entity_id): stat_def for stat_def in defs}
    result = dict(current)
    for change in changes:
        stat_def = defs_by_id.get(change.stat_id)
        if stat_def is None:
            continue
        result[change.stat_id] = min(max(change.new_value, stat_def.min_value), stat_def.max_value)
    return result
