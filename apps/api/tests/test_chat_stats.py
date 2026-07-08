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
